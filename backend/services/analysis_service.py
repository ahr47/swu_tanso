"""탄소 분석 처리 흐름 (백엔드2) — 명세서 v02 4번"""
from typing import Any, Dict, List, Optional

from core.config import get_settings
from core.errors import ApiError, ErrorCode
from schemas.analysis import AnalyzeRequest, AnalyzeResponse, CategoryResult, ItemResult, Source
from services import adapters
from services.event_service import get_event_or_raise, resolve_scenario, round1, round2


def run_analysis(event: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """계산 함수 호출 (반올림 전 값). recommend·compare 에서도 사용"""
    if not rows:
        raise ApiError(ErrorCode.NO_ITEMS, "품목을 먼저 저장해 주세요")
    try:
        return adapters.analyze_items(rows, event["participants"], event.get("budget"))
    except ValueError as exc:
        raise ApiError(ErrorCode.CALC_NOT_AVAILABLE, str(exc)) from exc


def to_response(scenario: Dict[str, Any], result: Dict[str, Any]) -> AnalyzeResponse:
    factor_version = get_settings().current_factor_version
    by_item = [
        ItemResult(
            item_id=r["item_id"], item_name=r["item_name"], category=r["category"],
            variant_label=r["variant_label"], quantity=r["quantity"], unit=r["unit"],
            emission=round2(r["emission"]), ratio=round1(r["ratio"]), cost=r["cost"],
            confidence=r["confidence"], notes=r["notes"],
            source=Source(name=r["source"]["name"], year=r["source"]["year"], url=r["source"]["url"],
                          factor_version=factor_version),
        )
        for r in result["by_item"]
    ]
    by_category = [CategoryResult(category=c["category"], emission=round2(c["emission"]), ratio=round1(c["ratio"]))
                   for c in result["by_category"]]
    return AnalyzeResponse(
        scenario_id=scenario["scenario_id"],
        scenario_type=scenario["scenario_type"],
        total_emission=round2(result["total_emission"]),
        emission_per_person=round2(result["emission_per_person"]),
        total_cost=result["total_cost"],
        priced_item_count=result["priced_item_count"],
        budget_usage_rate=round1(result["budget_usage_rate"]),
        by_item=by_item,
        by_category=by_category,
        top_items=result["top_items"],
        top_items_share=round1(result["top_items_share"]),
        warnings=result["warnings"],
    )


def analyze(event_id: str, req: Optional[AnalyzeRequest]) -> AnalyzeResponse:
    event = get_event_or_raise(event_id)
    scenario = resolve_scenario(event_id, req.scenario_id if req else None)
    result = run_analysis(event, scenario["items"])
    return to_response(scenario, result)
