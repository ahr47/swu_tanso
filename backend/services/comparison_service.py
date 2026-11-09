"""
개선안 비교 처리 흐름 (백엔드2) — 명세서 v02 6번

추천 검증 → improved 시나리오 저장(덮어쓰기) → 전·후 재계산 → 비교 응답 조립
"""
from typing import Any, Dict, List

from core.errors import ApiError, ErrorCode
from schemas.comparison import CompareRequest, CompareResponse, ItemComparison, ScenarioTotals
from services import adapters
from services.analysis_service import run_analysis
from services.event_service import get_event_or_raise, resolve_scenario, round1, round2
from services.recommendation_service import _apply_to_row


def _load_recommendations(event_id: str, original: Dict[str, Any], rec_ids: List[str]) -> List[Dict[str, Any]]:
    """적용할 추천 검증: 현재 추천인지, 같은 품목 중복 없는지, 적용 가능한지"""
    unique_ids = list(dict.fromkeys(rec_ids))  # 같은 ID 중복은 한 번만
    found = adapters.get_recommendations(unique_ids)

    recs = []
    for index, rec_id in enumerate(unique_ids):
        rec = found.get(rec_id)
        is_current = (
            rec is not None
            and rec["event_id"] == event_id
            and rec["scenario_id"] == original["scenario_id"]
            and rec["base_version"] == original["version"]
        )
        if not is_current:
            raise ApiError(ErrorCode.STALE_DATA, field=f"applied_rec_ids[{index}]")
        recs.append(rec)

    seen_items: Dict[str, str] = {}
    for rec in recs:
        if rec["item_id"] in seen_items:
            raise ApiError(ErrorCode.CONFLICTING_RECOMMENDATIONS,
                           f"{rec['item_name']} 추천은 하나만 적용할 수 있습니다 ({seen_items[rec['item_id']]}, {rec['rec_id']})",
                           "applied_rec_ids")
        seen_items[rec["item_id"]] = rec["rec_id"]

    for rec in recs:
        if not rec["applicable"]:
            raise ApiError(ErrorCode.INVALID_INPUT, f"적용할 수 없는 추천입니다 ({rec['rec_id']})", "applied_rec_ids")
    return recs


def compare(event_id: str, req: CompareRequest) -> CompareResponse:
    event = get_event_or_raise(event_id)
    original = resolve_scenario(event_id, req.original_scenario_id, field="original_scenario_id")
    if original["scenario_type"] != "original":
        raise ApiError(ErrorCode.INVALID_INPUT, "original 시나리오를 지정해 주세요", "original_scenario_id")

    recs = _load_recommendations(event_id, original, req.applied_rec_ids)
    rec_by_item = {rec["item_id"]: rec for rec in recs}

    original_rows = original["items"]
    improved_rows = [_apply_to_row(row, rec_by_item[row["item_id"]]) if row["item_id"] in rec_by_item else dict(row)
                     for row in original_rows]

    before = run_analysis(event, original_rows)
    after = run_analysis(event, improved_rows)

    # 한 트랜잭션: 입력이 그사이 바뀌지 않았는지 확인 후 improved 덮어쓰기
    with adapters.transaction():
        current = adapters.get_scenario(original["scenario_id"])
        if current is None or current["version"] != original["version"]:
            raise ApiError(ErrorCode.STALE_DATA)
        improved_id = adapters.save_improved_scenario(event_id, improved_rows)

    before_by_id = {r["item_id"]: r for r in before["by_item"]}
    after_by_id = {r["item_id"]: r for r in after["by_item"]}
    item_comparison = []
    for old_row, new_row in zip(original_rows, improved_rows):
        old = before_by_id[old_row["item_id"]]
        new = after_by_id[new_row["item_id"]]
        rec = rec_by_item.get(old_row["item_id"])
        is_quantity = rec is not None and rec["action_type"] == "reduce_quantity"
        is_replace = rec is not None and rec["action_type"] == "replace_item"
        item_comparison.append(ItemComparison(
            item_id=old_row["item_id"], item_name=old["item_name"],
            before_emission=round2(old["emission"]), after_emission=round2(new["emission"]),
            emission_diff=round2(new["emission"] - old["emission"]),
            changed=rec is not None,
            target_field=rec["target_field"] if rec else None,
            before_value=old_row["quantity"] if is_quantity else None,
            after_value=new_row["quantity"] if is_quantity else None,
            before_item_id=old_row["item_id"] if is_replace else None,
            after_item_id=new_row["item_id"] if is_replace else None,
            after_item_name=new["item_name"] if is_replace else None,
        ))

    before_total, after_total = before["total_emission"], after["total_emission"]
    cost_change = None
    if before["total_cost"] is not None and after["total_cost"] is not None:
        cost_change = after["total_cost"] - before["total_cost"]

    return CompareResponse(
        original_scenario_id=original["scenario_id"],
        improved_scenario_id=improved_id,
        before=ScenarioTotals(total_emission=round2(before_total),
                              emission_per_person=round2(before["emission_per_person"]),
                              total_cost=before["total_cost"]),
        after=ScenarioTotals(total_emission=round2(after_total),
                             emission_per_person=round2(after["emission_per_person"]),
                             total_cost=after["total_cost"]),
        reduction=round2(before_total - after_total),
        reduction_rate=round1((before_total - after_total) / before_total * 100) if before_total > 0 else None,
        cost_change=cost_change,
        item_comparison=item_comparison,
    )
