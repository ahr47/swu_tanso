"""
어댑터 (백엔드2) — services/*.py 는 DB·계산·AI 를 직접 부르지 않고 이 파일의 함수만 부릅니다.

    [품목·계수] 백엔드3 calculator/catalogue_v02.json   → 연결 완료
    [계산]     백엔드3 calculator                       → 연결 완료
    [AI]       백엔드4 ai/recommender                   → 연결 완료 (AI_API_KEY 없으면 임시 규칙 추천)
    [DB]       백엔드1 db/repositories                  → 연결 완료 (DATABASE_URL 이 비어 있으면 메모리 저장소)

함수 이름과 반환 형태는 임시 구현 때와 같습니다. 배출량은 계산기의 Decimal 원값을 그대로 돌려주고,
반올림은 서비스(round1/round2, HALF_UP)에서 합니다.
"""
import asyncio
import copy
import json
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from calculator import CalculationError, analyze_scenario, calculate_item
from calculator.catalogue import catalogue_from_records
from core.config import get_settings
from db.connection import transaction as db_transaction
from db.repositories import event_repository, item_repository


def _use_db() -> bool:
    """DATABASE_URL 이 입력됐으면 PostgreSQL, 아니면 메모리 저장소 (테스트·로컬 확인용)"""
    return get_settings().database_url_is_set

# ===========================================================================
# 품목 마스터·배출계수 (DB: items·item_variants·emission_factors / DB 없으면 catalogue_v02.json)
# ===========================================================================
CAT_PRINT = "인쇄물·홍보물"
CAT_DRINK = "음료·일회용품"
CAT_FOOD = "음식·간식"
CAT_GOODS = "굿즈"
CAT_DELIVERY = "배송"

# 입력값 명세서 2번의 영문 분야 코드도 category 조회에 쓸 수 있게 함
CATEGORY_CODES: Dict[str, str] = {
    "print": CAT_PRINT,
    "drink_disposable": CAT_DRINK,
    "food": CAT_FOOD,
    "goods": CAT_GOODS,
    "delivery_pack": CAT_DELIVERY,
}

_CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "calculator" / "catalogue_v02.json"


class _Catalogue:
    def __init__(self, item_records: List[Dict[str, Any]], factor_records: List[Dict[str, Any]]) -> None:
        # API 응답용 품목 dict (v02 품목 목록 필드)
        self.items: List[Dict[str, Any]] = [
            {
                "item_id": row["item_id"], "item_name": row["item_name"], "category": row["category"],
                "input_unit": row["input_unit"], "input_method": row["input_method"], "calc_type": row["calc_type"],
                "variants": copy.deepcopy(row.get("variants")) or None, "notes": list(row.get("notes") or []),
                "description": row.get("description"), "is_active": row.get("is_active", True),
            }
            for row in item_records
        ]
        self.by_id: Dict[str, Dict[str, Any]] = {item["item_id"]: item for item in self.items}
        # 계산기 객체 (ItemDefinition, EmissionFactor)
        self.calc_items, self.calc_factors = catalogue_from_records(item_records, factor_records)


_catalogue_cache: Optional[_Catalogue] = None
_catalogue_lock = threading.Lock()


def _catalogue() -> _Catalogue:
    """품목·계수를 한 번 읽어 캐시. 계수를 DB 에서 바꿨으면 reload_catalogue() 호출"""
    global _catalogue_cache
    with _catalogue_lock:
        if _catalogue_cache is None:
            if _use_db():
                item_records, factor_records = item_repository.fetch_catalogue()
            else:
                data = json.loads(_CATALOGUE_PATH.read_text(encoding="utf-8"))
                item_records, factor_records = data["items"], data["factors"]
            _catalogue_cache = _Catalogue(item_records, factor_records)
        return _catalogue_cache


def reload_catalogue() -> None:
    global _catalogue_cache
    with _catalogue_lock:
        _catalogue_cache = None


def list_active_items(category: Optional[str] = None) -> List[Dict[str, Any]]:
    if category:
        category = CATEGORY_CODES.get(category, category)
    return [copy.deepcopy(i) for i in _catalogue().items
            if i["is_active"] and (not category or i["category"] == category)]


def get_item(item_id: str) -> Optional[Dict[str, Any]]:
    item = _catalogue().by_id.get(item_id)
    return item if item and item["is_active"] else None


def get_variant(item: Dict[str, Any], code: Optional[str]) -> Optional[Dict[str, Any]]:
    for variant in item.get("variants") or []:
        if variant["variant"] == code:
            return variant
    return None


def default_variant(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for variant in item.get("variants") or []:
        if variant["is_default"]:
            return variant
    return None


# ===========================================================================
# DB (백엔드1 db/repositories 연결) — DATABASE_URL 이 비어 있으면 아래 메모리 저장소 사용
# ===========================================================================
class _MemoryStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()  # DB 트랜잭션 대신 사용
        self.events: Dict[str, Dict[str, Any]] = {}
        self.scenarios: Dict[str, Dict[str, Any]] = {}
        self.recommendations: Dict[str, Dict[str, Any]] = {}
        self._event_seq = 0
        self._scenario_seq = 0
        self._rec_seq = 0

    def next_event_id(self) -> str:
        self._event_seq += 1
        return f"EVT_{self._event_seq:04d}"

    def next_scenario_id(self) -> str:
        self._scenario_seq += 1
        return f"SCN_{self._scenario_seq:04d}"

    def next_rec_id(self) -> str:
        self._rec_seq += 1
        return f"REC_{self._rec_seq}"


_store = _MemoryStore()


def transaction() -> Any:
    """with transaction(): 블록 = 한 DB 트랜잭션 (블록 안의 어댑터 함수는 같은 연결 사용)"""
    if _use_db():
        return db_transaction()
    return _store.lock


def reset_store() -> None:
    """테스트용: 저장소 초기화 (DB 면 행사·시나리오·추천 삭제. 운영 환경에서는 금지)"""
    global _store
    if _use_db():
        if get_settings().app_env == "production":
            raise RuntimeError("운영 DB 에서는 reset_store 를 쓸 수 없습니다")
        event_repository.reset_all()
        reload_catalogue()
        return
    _store = _MemoryStore()


def create_event(data: Dict[str, Any]) -> Tuple[str, str]:
    """행사 + original 시나리오를 함께 만들고 (event_id, scenario_id) 반환"""
    if _use_db():
        return event_repository.create_event(data)
    with _store.lock:
        event_id = _store.next_event_id()
        scenario_id = _store.next_scenario_id()
        _store.events[event_id] = {"event_id": event_id, **data}
        _store.scenarios[scenario_id] = {
            "scenario_id": scenario_id, "event_id": event_id, "scenario_type": "original",
            "items": [], "version": 0,
        }
        return event_id, scenario_id


def get_event(event_id: str) -> Optional[Dict[str, Any]]:
    if _use_db():
        return event_repository.get_event(event_id)
    event = _store.events.get(event_id)
    return copy.deepcopy(event) if event else None


def get_scenario(scenario_id: str) -> Optional[Dict[str, Any]]:
    if _use_db():
        return event_repository.get_scenario(scenario_id)
    scenario = _store.scenarios.get(scenario_id)
    return copy.deepcopy(scenario) if scenario else None


def find_scenario(event_id: str, scenario_type: str) -> Optional[Dict[str, Any]]:
    if _use_db():
        return event_repository.find_scenario(event_id, scenario_type)
    for scenario in _store.scenarios.values():
        if scenario["event_id"] == event_id and scenario["scenario_type"] == scenario_type:
            return copy.deepcopy(scenario)
    return None


def _delete_improved_and_recs(event_id: str) -> None:
    for sid in [s for s, v in _store.scenarios.items() if v["event_id"] == event_id and v["scenario_type"] == "improved"]:
        del _store.scenarios[sid]
    for rid in [r for r, v in _store.recommendations.items() if v["event_id"] == event_id]:
        del _store.recommendations[rid]


def replace_scenario_items(scenario_id: str, items: List[Dict[str, Any]]) -> int:
    """original 품목 통째로 교체 + 기존 추천·improved 삭제. 새 version 반환"""
    if _use_db():
        return event_repository.replace_scenario_items(scenario_id, items)
    with _store.lock:
        scenario = _store.scenarios[scenario_id]
        scenario["items"] = copy.deepcopy(items)
        scenario["version"] += 1
        _delete_improved_and_recs(scenario["event_id"])
        return scenario["version"]


def replace_recommendations(event_id: str, scenario_id: str, recs: List[Dict[str, Any]],
                            base_version: int) -> List[Dict[str, Any]]:
    """이전 추천·improved 삭제 후 새 추천 저장. rec_id 를 붙여서 반환. 호출 전에 transaction() 안에서 버전 확인"""
    if _use_db():
        return event_repository.replace_recommendations(event_id, scenario_id, recs, base_version)
    with _store.lock:
        _delete_improved_and_recs(event_id)
        saved = []
        for rec in recs:
            rec_id = _store.next_rec_id()
            row = {**copy.deepcopy(rec), "rec_id": rec_id, "event_id": event_id,
                   "scenario_id": scenario_id, "base_version": base_version}
            _store.recommendations[rec_id] = row
            saved.append(copy.deepcopy(row))
        return saved


def get_recommendations(rec_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if _use_db():
        return event_repository.get_recommendations(rec_ids)
    return {rid: copy.deepcopy(_store.recommendations[rid]) for rid in rec_ids if rid in _store.recommendations}


def save_improved_scenario(event_id: str, items: List[Dict[str, Any]]) -> str:
    """improved 시나리오를 덮어쓰고 scenario_id 반환 (행사당 1개)"""
    if _use_db():
        return event_repository.save_improved_scenario(event_id, items)
    with _store.lock:
        existing = find_scenario(event_id, "improved")
        scenario_id = existing["scenario_id"] if existing else _store.next_scenario_id()
        _store.scenarios[scenario_id] = {
            "scenario_id": scenario_id, "event_id": event_id, "scenario_type": "improved",
            "items": copy.deepcopy(items), "version": 0,
        }
        return scenario_id


# ===========================================================================
# 계산 (백엔드3 calculator 연결)
# ===========================================================================
# 계산기는 품목 유형별로 받는 필드가 정해져 있어서, 저장된 줄에서 해당 필드만 골라 넘깁니다.
_CALC_FIELDS = {
    "count_only": ("quantity", "unit_price"),
    "count_variant": ("quantity", "variant", "unit_price"),
    "dimension": ("quantity", "width_m", "height_m", "unit_price"),
    "fixed_use": (),  # 일반 배송: 수량 1 고정, 계산기가 처리
}


def _factor_version() -> str:
    return get_settings().current_factor_version


def _to_calc_input(row: Dict[str, Any]) -> Dict[str, Any]:
    item = _catalogue().by_id.get(row["item_id"])
    if item is None:
        raise ValueError(f"등록된 품목이 아닙니다: {row['item_id']}")
    data: Dict[str, Any] = {"item_id": row["item_id"]}
    for name in _CALC_FIELDS[item["input_method"]]:
        if row.get(name) is not None:
            data[name] = row[name]
    return data


def _item_result(calc: Any) -> Dict[str, Any]:
    """ItemCalculation -> 서비스가 쓰는 dict (emission 은 Decimal 원값)"""
    return {
        "item_id": calc.item_id, "item_name": calc.item_name, "category": calc.category,
        "variant_label": calc.variant_label, "quantity": int(calc.quantity), "unit": calc.unit,
        "emission": calc.emission, "cost": calc.cost, "confidence": calc.confidence,
        "notes": list(calc.notes),
        "source": {"name": calc.source_name, "year": calc.source_year, "url": calc.source_url},
        "scope": calc.scope_group,
    }


def calc_item(row: Dict[str, Any]) -> Dict[str, Any]:
    """품목 1줄 계산. row: item_id, quantity, variant, width_m, height_m, unit_price.
    계수 없음 등 계산 불가면 ValueError (CalculationError 는 ValueError 하위 클래스)."""
    data = _to_calc_input(row)
    catalogue = _catalogue()
    calc = calculate_item(data, item=catalogue.calc_items.get(data["item_id"]), factors=catalogue.calc_factors,
                          factor_version=_factor_version())
    return _item_result(calc)


def analyze_items(rows: List[Dict[str, Any]], participants: int, budget: Optional[int]) -> Dict[str, Any]:
    """행사 전체 분석. 배출량은 Decimal 원값, 비율은 계산기가 확정한 값(소수 첫째 자리)."""
    try:
        catalogue = _catalogue()
        analysis = analyze_scenario([_to_calc_input(r) for r in rows], items=catalogue.calc_items,
                                    factors=catalogue.calc_factors,
                                    factor_version=_factor_version(), participants=participants,
                                    scenario_id="adapter", budget=budget)
    except CalculationError as exc:
        raise ValueError(exc.message) from exc
    api = analysis.to_api_response()  # 정렬·비율·상위 3개·경고는 계산기 기준
    total = analysis.total_emission
    calc_by_id = {c.item_id: c for c in analysis.results}

    by_item = []
    for row in api["by_item"]:
        result = _item_result(calc_by_id[row["item_id"]])
        result["ratio"] = row["ratio"]
        by_item.append(result)

    category_totals: Dict[str, Decimal] = {}
    for calc in analysis.results:
        category_totals[calc.category] = category_totals.get(calc.category, Decimal(0)) + calc.emission
    by_category = [
        {"category": row["category"], "emission": category_totals[row["category"]], "ratio": row["ratio"]}
        for row in api["by_category"]
    ]

    return {
        "total_emission": total,
        "emission_per_person": total / participants if participants else Decimal(0),
        "total_cost": analysis.total_cost,
        "priced_item_count": analysis.priced_item_count,
        "budget_usage_rate": api["budget_usage_rate"],
        "by_item": by_item,
        "by_category": by_category,
        "top_items": api["top_items"],
        "top_items_share": api["top_items_share"],
        "warnings": api["warnings"],
    }


# ===========================================================================
# AI (백엔드4 ai/recommender 연결)
# ===========================================================================
def ai_is_connected() -> bool:
    """AI_API_KEY 가 입력됐으면 실제 AI(백엔드4) 호출, 아니면 임시 규칙 기반 추천"""
    return get_settings().ai_api_key_is_set


def ai_call_policy() -> Tuple[int, float]:
    """(호출 횟수, 1회 대기 시간 초). 실제 AI 는 백엔드4 모듈이 1회 재시도를 직접 하므로 서비스는 1번만 부른다."""
    settings = get_settings()
    if ai_is_connected():
        return 1, settings.ai_timeout_seconds * 2 + 5
    return settings.ai_max_retries + 1, settings.ai_timeout_seconds


_openai_client: Any = None
_openai_lock = threading.Lock()


def _get_openai_client() -> Any:
    global _openai_client
    with _openai_lock:
        if _openai_client is None:
            from openai import AsyncOpenAI

            # SDK 자동 재시도 끔 (백엔드4 모듈이 재시도 담당)
            _openai_client = AsyncOpenAI(api_key=get_settings().ai_api_key, max_retries=0)
        return _openai_client


def call_ai(ai_input: Dict[str, Any]) -> Dict[str, Any]:
    """백엔드4 함수 호출. 입력·출력 형식은 명세서 v02 5번 '백엔드4 함수 입력·출력 JSON'.
    스레드 풀에서 실행되므로 비동기 함수를 asyncio.run 으로 돌립니다."""
    if not ai_is_connected():
        return _rule_based_recommendations(ai_input)

    from ai.recommender import generate_recommendations

    settings = get_settings()
    return asyncio.run(generate_recommendations(
        ai_input, client=_get_openai_client(), model=settings.ai_model, timeout_seconds=settings.ai_timeout_seconds,
    ))


# 품목 교체 후보 (AI 키 발급 전 임시 규칙)
_REPLACEMENTS: Dict[str, Tuple[str, Optional[str], str]] = {
    "pet_drink": ("can_drink", "250ml", "같은 수량을 캔 음료로 바꾸면 개당 배출량이 절반 수준으로 줄어듭니다."),
    "pet_cup": ("paper_cup", None, "PET컵을 종이컵으로 바꾸면 개당 배출량이 줄어듭니다."),
}


def _rule_based_recommendations(ai_input: Dict[str, Any]) -> Dict[str, Any]:
    max_recs = ai_input["constraints"]["max_recommendations"]
    recs: List[Dict[str, Any]] = []
    for item in sorted(ai_input["items"], key=lambda i: i["emission"], reverse=True):
        if len(recs) >= max_recs:
            break
        if item["input_method"] == "fixed_use":
            continue
        replacement = _REPLACEMENTS.get(item["item_id"])
        if replacement:
            alt_id, alt_variant, reason = replacement
            recs.append({
                "item_id": item["item_id"], "action_type": "replace_item", "target_field": "item_id",
                "recommended_value": None, "alternative_item_id": alt_id, "alternative_variant": alt_variant,
                "title": f"{item['item_name']} → {_catalogue().by_id[alt_id]['item_name']}", "difficulty": "쉬움", "reason": reason,
            })
        elif item["quantity"] and item["quantity"] >= 2:
            new_quantity = int(item["quantity"] * 0.6)
            if 0 < new_quantity < item["quantity"]:
                recs.append({
                    "item_id": item["item_id"], "action_type": "reduce_quantity", "target_field": "quantity",
                    "recommended_value": new_quantity, "alternative_item_id": None, "alternative_variant": None,
                    "title": f"{item['item_name']} 수량 조정", "difficulty": "쉬움",
                    "reason": f"{item['item_name']} 배출 비중이 커서, 참여 인원에 맞게 수량을 줄이면 감축 효과가 큽니다.",
                })
    return {"recommendations": recs}
