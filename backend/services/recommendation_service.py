"""
AI 추천 처리 흐름 (백엔드2) — 명세서 v02 5번

처리 순서
1. 행사·시나리오 소속 확인, 최신 분석 결과 계산
2. 백엔드4 함수 입력 JSON 만들어 호출 (트랜잭션 밖. 시간 제한 + 재시도)
3. 추천 하나씩 검증 → 감축량·비용 변화·적용 가능 여부 계산 (백엔드3 계산 함수)
4. 트랜잭션 안에서 입력이 그사이 바뀌지 않았는지 확인 → 이전 추천·improved 삭제 → 새 추천 저장
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ValidationError

from core.config import get_settings
from core.errors import ApiError, ErrorCode
from schemas.recommendations import Goal, Recommendation, RecommendRequest, RecommendResponse
from services import adapters
from services.analysis_service import run_analysis
from services.event_service import get_event_or_raise, resolve_scenario, round1, round2

logger = logging.getLogger("api.recommend")

ALLOWED_ACTION_TYPES = ["reduce_quantity", "replace_item"]
ALLOWED_DIFFICULTIES = ("쉬움", "보통", "어려움")
_ai_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ai-call")


# ---------------------------------------------------------------------------
# 백엔드4 함수 출력 형식 (명세서 5번 '백엔드4 함수 출력 JSON')
# 백엔드4와 합의되면 ai/schemas.py 로 옮겨서 함께 사용
# ---------------------------------------------------------------------------
class AiRecommendation(BaseModel):
    item_id: str
    action_type: str
    target_field: Optional[str] = None
    recommended_value: Optional[float] = None
    alternative_item_id: Optional[str] = None
    alternative_variant: Optional[str] = None
    title: Optional[str] = None
    difficulty: Optional[str] = None
    reason: str = ""


class AiOutput(BaseModel):
    recommendations: List[AiRecommendation]


# ---------------------------------------------------------------------------
# 1~2. AI 입력 만들기, 호출
# ---------------------------------------------------------------------------
def _build_ai_input(event: Dict[str, Any], rows: List[Dict[str, Any]], analysis: Dict[str, Any],
                    goal: Goal) -> Dict[str, Any]:
    by_item = {r["item_id"]: r for r in analysis["by_item"]}
    items = []
    for row in rows:
        item = adapters.get_item(row["item_id"])
        result = by_item[row["item_id"]]
        items.append({
            "item_id": row["item_id"], "item_name": item["item_name"], "category": item["category"],
            "input_method": item["input_method"], "input_unit": item["input_unit"],
            "quantity": row["quantity"], "variant": row["variant"], "unit_price": row["unit_price"],
            "emission": round2(result["emission"]), "ratio": round1(result["ratio"]), "cost": result["cost"],
        })

    # 대체 후보: 활성 품목 중 행사 품목과 같은 카테고리 (AI 가 없는 품목을 만들지 않게)
    used_ids = {row["item_id"] for row in rows}
    used_categories = {adapters.get_item(i)["category"] for i in used_ids}
    alternatives = [
        {"item_id": i["item_id"], "item_name": i["item_name"], "category": i["category"],
         "input_unit": i["input_unit"], "variants": [v["variant"] for v in i["variants"]] if i["variants"] else None}
        for i in adapters.list_active_items()
        if i["category"] in used_categories and i["item_id"] not in used_ids and i["input_method"] != "fixed_use"
    ]

    return {
        "event": {"event_name": event["event_name"], "event_type": event["event_type"],
                  "participants": event["participants"], "budget": event.get("budget"),
                  "description": event.get("description")},
        "items": items,
        "analysis": {"total_emission": round2(analysis["total_emission"]), "total_cost": analysis["total_cost"],
                     "top_items": analysis["top_items"]},
        "alternatives": alternatives,
        "goal": goal.model_dump(),
        "constraints": {"allowed_action_types": ALLOWED_ACTION_TYPES,
                        "max_recommendations": get_settings().ai_max_recommendations},
    }


def _call_ai_with_retry(ai_input: Dict[str, Any]) -> AiOutput:
    """시간 제한 + 재시도. 끝내 실패하면 503 AI_UNAVAILABLE (이전 추천은 그대로 둠)"""
    settings = get_settings()
    attempts = settings.ai_max_retries + 1
    for attempt in range(1, attempts + 1):
        try:
            future = _ai_executor.submit(adapters.call_ai, ai_input)
            raw = future.result(timeout=settings.ai_timeout_seconds)
            return AiOutput.model_validate(raw)
        except FutureTimeoutError:
            logger.warning("AI 호출 시간 초과 (%s/%s)", attempt, attempts)
        except ValidationError as exc:
            logger.warning("AI 출력 형식 오류 (%s/%s): %s", attempt, attempts, exc)
        except Exception:  # noqa: BLE001 - AI 쪽 어떤 오류든 재시도
            logger.exception("AI 호출 실패 (%s/%s)", attempt, attempts)
    raise ApiError(ErrorCode.AI_UNAVAILABLE)


# ---------------------------------------------------------------------------
# 3. 추천 검증 + 재계산
# ---------------------------------------------------------------------------
def _apply_to_row(row: Dict[str, Any], rec: Dict[str, Any]) -> Dict[str, Any]:
    """추천 1개를 품목 1줄에 적용한 새 줄 (compare 에서도 사용)"""
    new_row = dict(row)
    if rec["action_type"] == "reduce_quantity":
        new_row["quantity"] = int(rec["recommended_value"])
    else:  # replace_item: 수량 유지, 단가는 다른 제품이라 비움
        new_row["item_id"] = rec["alternative_item_id"]
        new_row["variant"] = rec["alternative_variant"]
        new_row["unit_price"] = None
    return new_row


def _check_recommendation(ai_rec: AiRecommendation, rows_by_id: Dict[str, Dict[str, Any]],
                          goal: Goal) -> Optional[Dict[str, Any]]:
    """검증 실패면 None (그 추천만 제외). 통과하면 저장할 추천 dict"""
    if ai_rec.action_type not in ALLOWED_ACTION_TYPES:
        return None
    row = rows_by_id.get(ai_rec.item_id)
    item = adapters.get_item(ai_rec.item_id)
    if row is None or item is None:
        return None

    rec: Dict[str, Any] = {
        "item_id": item["item_id"], "item_name": item["item_name"], "category": item["category"],
        "action_type": ai_rec.action_type,
        "title": (ai_rec.title or "").strip() or f"{item['item_name']} 개선",
        "difficulty": ai_rec.difficulty if ai_rec.difficulty in ALLOWED_DIFFICULTIES else "보통",
        "reason": ai_rec.reason, "current_value": None, "recommended_value": None,
        "alternative_item_id": None, "alternative_item_name": None, "alternative_variant": None,
        "applicable": True, "not_applicable_reason": None,
    }

    # 수량 고정 품목(일반 배송): 계산 없이 적용 불가로 표시
    if item["input_method"] == "fixed_use":
        rec.update(target_field="quantity", current_value=row["quantity"], recommended_value=ai_rec.recommended_value,
                   emission_reduction=0.0, cost_change=None, applicable=False, not_applicable_reason="FIXED_QUANTITY")
        return rec

    if ai_rec.action_type == "reduce_quantity":
        value = ai_rec.recommended_value
        if value is None or not float(value).is_integer() or not (0 < value < row["quantity"]):
            return None
        rec.update(target_field="quantity", current_value=row["quantity"], recommended_value=int(value))
    else:
        alt = adapters.get_item(ai_rec.alternative_item_id or "")
        if alt is None or alt["item_id"] == item["item_id"] or alt["input_method"] == "fixed_use":
            return None
        if alt["calc_type"] != item["calc_type"] or alt["input_unit"] != item["input_unit"]:
            return None  # 단위 호환 안 됨 (교체는 수량을 유지하므로)
        if alt["item_id"] in rows_by_id:
            return None  # 이미 행사에 있는 품목으로 바꾸면 중복 품목이 됨
        alt_variant = None
        if alt.get("variants"):
            chosen = adapters.get_variant(alt, ai_rec.alternative_variant) or adapters.default_variant(alt)
            if chosen is None:
                return None
            alt_variant = chosen["variant"]
        rec.update(target_field="item_id", alternative_item_id=alt["item_id"], alternative_item_name=alt["item_name"],
                   alternative_variant=alt_variant)

    # 이 추천만 적용했을 때 재계산 (백엔드3 계산 함수)
    try:
        before = adapters.calc_item(row)
        after = adapters.calc_item(_apply_to_row(row, rec))
    except ValueError:
        return None  # 계수 없음
    reduction = before["emission"] - after["emission"]
    if reduction <= 0:
        return None  # 줄어들지 않는 추천은 제외
    cost_change = (after["cost"] - before["cost"]) if (before["cost"] is not None and after["cost"] is not None) else None

    rec["emission_reduction"] = reduction
    rec["cost_change"] = cost_change
    if not goal.budget_increase_allowed and cost_change is not None and cost_change > 0:
        rec["applicable"] = False
        rec["not_applicable_reason"] = "BUDGET_INCREASE"
    return rec


# ---------------------------------------------------------------------------
# 5. POST /api/events/{event_id}/recommend
# ---------------------------------------------------------------------------
def recommend(event_id: str, req: Optional[RecommendRequest]) -> RecommendResponse:
    event = get_event_or_raise(event_id)
    scenario = resolve_scenario(event_id, req.scenario_id if req else None)
    if scenario["scenario_type"] != "original":
        raise ApiError(ErrorCode.INVALID_INPUT, "추천은 original 시나리오 기준으로만 받을 수 있습니다", "scenario_id")
    goal = (req.goal if req and req.goal else None) or Goal()

    rows = scenario["items"]
    base_version = scenario["version"]
    analysis = run_analysis(event, rows)

    # AI 호출 (트랜잭션 밖)
    ai_output = _call_ai_with_retry(_build_ai_input(event, rows, analysis, goal))

    rows_by_id = {row["item_id"]: row for row in rows}
    checked = []
    for ai_rec in ai_output.recommendations:
        rec = _check_recommendation(ai_rec, rows_by_id, goal)
        if rec is None:
            logger.info("추천 제외: %s", ai_rec.model_dump())
            continue
        checked.append(rec)
    checked = checked[: get_settings().ai_max_recommendations]

    # 저장 (트랜잭션 안): AI 호출 중 입력이 바뀌었으면 STALE_DATA
    with adapters.transaction():
        current = adapters.get_scenario(scenario["scenario_id"])
        if current is None or current["version"] != base_version:
            raise ApiError(ErrorCode.STALE_DATA, "추천을 만드는 동안 품목이 수정되었습니다. 다시 시도해 주세요")
        saved = adapters.replace_recommendations(event_id, scenario["scenario_id"], checked, base_version)

    empty_reason = None
    if not saved:
        empty_reason = "NO_CANDIDATE" if not ai_output.recommendations else "ALL_FILTERED"

    recommendations = [
        Recommendation(
            rec_id=r["rec_id"], item_id=r["item_id"], item_name=r["item_name"], title=r["title"],
            category=r["category"], difficulty=r["difficulty"], action_type=r["action_type"],
            target_field=r["target_field"], current_value=r["current_value"],
            recommended_value=r["recommended_value"], alternative_item_id=r["alternative_item_id"],
            alternative_item_name=r["alternative_item_name"], alternative_variant=r["alternative_variant"],
            reason=r["reason"], emission_reduction=round2(r["emission_reduction"]), cost_change=r["cost_change"],
            applicable=r["applicable"], not_applicable_reason=r["not_applicable_reason"],
        )
        for r in saved
    ]
    return RecommendResponse(scenario_id=scenario["scenario_id"], empty_reason=empty_reason,
                             recommendations=recommendations)
