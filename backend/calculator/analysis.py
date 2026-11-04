"""행사 전체 분석. DB/HTTP/환경변수 접근 없음."""
from dataclasses import replace
from typing import Mapping, Sequence

from .emissions import calculate_item
from .schemas import (CalculationError, EmissionFactor, ItemDefinition, ItemInput,
                      ScenarioAnalysis, decimal_number, sum_exact)


def analyze_scenario(
    inputs: Sequence[ItemInput | Mapping], *, items: Mapping[str, ItemDefinition],
    factors: Sequence[EmissionFactor], factor_version: str, participants: int,
    scenario_id: str, scenario_type: str = "original", budget: int | None = None,
) -> ScenarioAnalysis:
    """품목 입력을 모두 검증/계산한 원값 객체 반환. 오류가 있으면 전체 분석 실패.

    API 출력은 result.to_api_response(). 프론트의 줄별 미리보기는 calculate_item을 사용.
    계수·출처·기본값·버전은 호출자가 전달하며 입력 객체를 변경하지 않는다.
    """
    if type(participants) is not int or participants < 1:
        raise CalculationError("INVALID_INPUT", "participants", "참여 인원은 1 이상의 정수여야 합니다")
    if budget is not None and (type(budget) is not int or budget < 0):
        raise CalculationError("INVALID_INPUT", "budget", "예산은 0 이상의 정수여야 합니다")
    if not isinstance(scenario_id, str) or not scenario_id:
        raise CalculationError("INVALID_INPUT", "scenario_id", "시나리오 ID가 필요합니다")
    if scenario_type not in ("original", "improved"):
        raise CalculationError("INVALID_INPUT", "scenario_type", "시나리오 유형이 올바르지 않습니다")
    if not inputs:
        raise CalculationError("NO_ITEMS", "items", "품목을 1개 이상 추가해 주세요")
    seen, normalized, results = set(), [], []
    for index, data in enumerate(inputs):
        try:
            request = ItemInput.from_dict(data) if isinstance(data, Mapping) else data
            if not isinstance(request, ItemInput) or not isinstance(request.item_id, str):
                raise CalculationError("INVALID_INPUT", "item_id", "올바른 품목 입력이 필요합니다")
            if request.item_id in seen:
                raise CalculationError("DUPLICATE_ITEM", "item_id", "같은 품목을 두 번 추가할 수 없습니다")
            seen.add(request.item_id)
            item = items.get(request.item_id)
            if item is None:
                raise CalculationError("UNKNOWN_ITEM", "item_id", "등록된 활성 품목이 아닙니다")
            result = calculate_item(data, item=item, factors=factors, factor_version=factor_version)
            # 기본 변형은 결과에 고정. fixed_use 입력에는 수량을 새로 넣지 않는다.
            normalized.append(replace(
                request, variant=result.variant,
                quantity=None if item.input_method == "fixed_use" else result.quantity,
                width_m=(decimal_number(request.width_m, "width_m") if request.width_m is not None else None),
                height_m=(decimal_number(request.height_m, "height_m") if request.height_m is not None else None),
            ))
            results.append(result)
        except CalculationError as exc:
            raise CalculationError(exc.code, f"items[{index}].{exc.field}", exc.message) from exc
    known = [r.cost for r in results if r.cost is not None]
    scopes = {r.scope_group for r in results if r.scope_group is not None}
    # 품목 잠정값/참고값은 by_item.notes. 전체 warnings는 범위가 혼합될 때만 1회.
    warnings = ("계산 범위가 다른 자료를 포함함",) if len(scopes) > 1 else ()
    return ScenarioAnalysis(scenario_id, scenario_type, participants, budget,
                            tuple(normalized), tuple(results),
                            sum_exact(r.emission for r in results),
                            sum(known) if known else None, len(known), warnings)
