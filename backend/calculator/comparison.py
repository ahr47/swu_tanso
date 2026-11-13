"""추천의 실제 효과 및 기존안/개선안 비교. AI 생성·추천 저장·적용 가능 정책은 API 담당."""
from dataclasses import replace
from decimal import Decimal
from typing import Mapping, Sequence

from .analysis import analyze_scenario
from .emissions import calculate_item
from .schemas import (CalculationError, EmissionFactor, ItemDefinition, ItemInput,
                      RecommendationEffect, ScenarioComparison, decimal_number, difference)


def calculate_recommendation_effect(
    original_input: ItemInput | Mapping, *, action_type: str,
    items: Mapping[str, ItemDefinition], factors: Sequence[EmissionFactor], factor_version: str,
    recommended_value=None, alternative_item_id: str | None = None,
    alternative_variant: str | None = None, alternative_unit_price: int | None = None,
) -> RecommendationEffect:
    """추천 1개의 효과. 실패 시 can_calculate=False와 error, 효과값 None.

    API는 계산 불가 추천만 제외한다. applicable/예산 조건/추천 ID 소속은 여기서 결정하지 않는다.
    대체 가격은 AI 출력이 아니라 서버가 확인한 실제 가격만 전달한다. 미상은 None.
    """
    before = None
    try:
        request = ItemInput.from_dict(original_input) if isinstance(original_input, Mapping) else original_input
        if not isinstance(request, ItemInput):
            raise CalculationError("INVALID_INPUT", "item_id", "품목 입력이 올바르지 않습니다")
        item = items.get(request.item_id)
        if item is None:
            raise CalculationError("UNKNOWN_ITEM", "item_id", "대상 품목이 없습니다")
        before = calculate_item(original_input, item=item, factors=factors, factor_version=factor_version)
        if item.input_method == "fixed_use":
            raise CalculationError("INVALID_INPUT", "quantity", "수량 고정 품목은 변경할 수 없습니다")
        if action_type == "reduce_quantity":
            value = decimal_number(recommended_value, "recommended_value", "INVALID_QUANTITY")
            if not 0 < value < before.quantity or value != value.to_integral_value():
                raise CalculationError("INVALID_QUANTITY", "recommended_value", "추천 수량은 현재보다 작은 양의 정수여야 합니다")
            after_request = replace(request, quantity=value, variant=before.variant)
            after_item = item
        elif action_type == "replace_item":
            after_item = items.get(alternative_item_id)
            if after_item is None or not after_item.is_active:
                raise CalculationError("UNKNOWN_ITEM", "alternative_item_id", "등록된 활성 대체 품목이 아닙니다")
            if after_item.item_id == item.item_id:
                raise CalculationError("INVALID_INPUT", "alternative_item_id", "서로 다른 품목으로 교체해야 합니다")
            if (item.calc_type, item.input_unit) != (after_item.calc_type, after_item.input_unit):
                raise CalculationError("INVALID_INPUT", "alternative_item_id", "대체 품목의 계산 유형과 수량 단위가 호환되지 않습니다")
            if after_item.input_method == "fixed_use":
                raise CalculationError("INVALID_INPUT", "alternative_item_id", "고정 수량 품목으로 교체할 수 없습니다")
            after_request = ItemInput(
                item_id=after_item.item_id, quantity=before.quantity, variant=alternative_variant,
                width_m=request.width_m if after_item.calc_type == "AREA" else None,
                height_m=request.height_m if after_item.calc_type == "AREA" else None,
                unit_price=alternative_unit_price,
            )
        else:
            raise CalculationError("INVALID_INPUT", "action_type", "지원하지 않는 추천 유형입니다")
        after = calculate_item(after_request, item=after_item, factors=factors, factor_version=factor_version)
        cost_change = after.cost - before.cost if before.cost is not None and after.cost is not None else None
        return RecommendationEffect(True, before, after, difference(before.emission, after.emission), cost_change)
    except CalculationError as exc:
        return RecommendationEffect(False, before=before, error=exc)


def compare_scenarios(
    original_inputs: Sequence[ItemInput | Mapping], improved_inputs: Sequence[ItemInput | Mapping], *,
    items: Mapping[str, ItemDefinition], factors: Sequence[EmissionFactor], factor_version: str,
    participants: int, original_scenario_id: str, improved_scenario_id: str,
    budget: int | None = None, replacements: Mapping[str, str] | None = None,
) -> ScenarioComparison:
    """API가 작성한 개선안 전체를 다시 계산. replacements는 원본 ID -> 대체 ID 내부 매핑.

    품목 교체의 대응 관계를 추측하지 않는다. 한 대체 줄로 여러 원본을 합치는 경우는
    개별 전후 귀속이 모호하므로 거부한다. 원본/개선안 품목 중복도 분석기에서 거부한다.
    """
    before = analyze_scenario(original_inputs, items=items, factors=factors, factor_version=factor_version,
                              participants=participants, scenario_id=original_scenario_id, budget=budget)
    after = analyze_scenario(improved_inputs, items=items, factors=factors, factor_version=factor_version,
                             participants=participants, scenario_id=improved_scenario_id,
                             scenario_type="improved", budget=budget)
    old = {r.item_id: r for r in before.results}
    new = {r.item_id: r for r in after.results}
    old_inputs = {r.item_id: r for r in before.inputs}
    new_inputs = {r.item_id: r for r in after.inputs}
    mapping = dict(replacements or {})
    if len(set(mapping.values())) != len(mapping):
        raise CalculationError("CONFLICTING_RECOMMENDATIONS", "replacements", "여러 원본을 같은 대체 품목으로 합칠 수 없습니다")
    for source, target in mapping.items():
        if source not in old or target not in new or source == target:
            raise CalculationError("INVALID_INPUT", "replacements", "교체 전후 품목 매핑이 올바르지 않습니다")
        # 기존에 유지되는 별도 품목으로 교체/합산하면 전후 귀속을 알 수 없다.
        if target in old and target not in mapping:
            raise CalculationError("CONFLICTING_RECOMMENDATIONS", "replacements", "기존 품목과 대체 품목의 결과가 겹칩니다")
        a, b = items[source], items[target]
        if (a.calc_type, a.input_unit) != (b.calc_type, b.input_unit):
            raise CalculationError("INVALID_INPUT", "replacements", "교체 품목의 계산 유형과 단위가 호환되지 않습니다")
        if a.input_method == "fixed_use" or b.input_method == "fixed_use":
            raise CalculationError("INVALID_INPUT", "replacements", "고정 수량 품목은 교체할 수 없습니다")
        if old[source].quantity != new[target].quantity:
            raise CalculationError("INVALID_INPUT", "replacements", "품목 교체는 원래 수량을 유지해야 합니다")
    claimed, rows, deltas = set(), [], []
    costs_known = True
    for source, a in old.items():
        target = mapping.get(source, source)
        b = new.get(target)
        if b is not None:
            if target in claimed:
                raise CalculationError("CONFLICTING_RECOMMENDATIONS", "replacements", "대체 품목의 귀속이 중복됩니다")
            claimed.add(target)
        replaced = source in mapping
        changed = replaced or b is None or old_inputs[source] != new_inputs[target]
        if changed:
            if a.cost is None or (b is not None and b.cost is None):
                costs_known = False
            else:
                deltas.append((b.cost if b is not None else 0) - a.cost)
        e_after = b.emission if b is not None else Decimal(0)
        quantity_changed = not replaced and (b is None or a.quantity != b.quantity)
        rows.append({
            "item_id": source, "item_name": a.item_name,
            "before_emission": a.emission, "after_emission": e_after,
            "emission_diff": difference(e_after, a.emission), "changed": changed,
            "target_field": "item_id" if replaced else ("quantity" if quantity_changed else None),
            "before_value": int(a.quantity) if quantity_changed else None,
            "after_value": int(b.quantity) if quantity_changed and b is not None else (0 if quantity_changed else None),
            "before_item_id": source if replaced else None,
            "after_item_id": target if replaced else None,
            "after_item_name": b.item_name if replaced else None,
        })
    # 추가된 품목도 빠뜨리지 않는다. MVP 추천에서는 보통 교체 매핑으로 처리된다.
    for target, b in new.items():
        if target in claimed:
            continue
        if b.cost is None:
            costs_known = False
        else:
            deltas.append(b.cost)
        rows.append({"item_id": target, "item_name": b.item_name,
                     "before_emission": Decimal(0), "after_emission": b.emission,
                     "emission_diff": b.emission, "changed": True, "target_field": "quantity",
                     "before_value": 0, "after_value": int(b.quantity),
                     "before_item_id": None, "after_item_id": None, "after_item_name": None})
    known_prices = before.priced_item_count or after.priced_item_count
    cost_change = sum(deltas) if costs_known and known_prices else None
    return ScenarioComparison(before, after, difference(before.total_emission, after.total_emission),
                              cost_change, tuple(rows))
