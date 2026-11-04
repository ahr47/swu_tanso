"""DB 없이 실행. 아래 수치는 v02 제공값을 복사한 테스트용 계수다 (seed 아님)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from calculator import (
    CalculationError, EmissionFactor, ItemDefinition, ItemInput, Variant, calculate_item,
)

VERSION = "test-v02"


def definition(item_id, *, method="count_only", calc="COUNT", unit="개", variants=()):
    return ItemDefinition(item_id, item_id, "테스트 카테고리", calc, method, unit,
                          variants=variants)


def factor(item_id, value, variant="default", calc="COUNT", version=VERSION):
    return EmissionFactor(item_id, variant, Decimal(value), "테스트 계수 단위", calc,
                          version, "테스트용 출처", source_url=None)


@pytest.fixture
def water():
    return definition("water", method="count_variant", unit="병", variants=(
        Variant("330ml", "330mL"), Variant("500ml", "500mL", True)))


@pytest.fixture
def water_factors():
    return [factor("water", "0.0769", "330ml"), factor("water", "0.0793", "500ml")]


def run(data, item, factors):
    return calculate_item(data, item=item, factors=factors, factor_version=VERSION)


@pytest.mark.parametrize("item_id,method,calc,unit,quantity,value,extra,raw,shown", [
    ("pet_cup", "count_only", "COUNT", "개", 100, "0.0778", {}, "7.7800", 7.78),
    ("banner", "dimension", "AREA", "개", 2, "0.9511",
     {"width_m": 3, "height_m": 0.9}, "5.13594", 5.14),
    ("eco_bag", "count_only", "COUNT", "개", 50, "1.833", {}, "91.650", 91.65),
    ("a4_paper", "count_only", "COUNT", "장", 100, "0.0056", {}, "0.5600", 0.56),
])
def test_priority_items(item_id, method, calc, unit, quantity, value, extra, raw, shown):
    item = definition(item_id, method=method, calc=calc, unit=unit)
    result = run({"item_id": item_id, "quantity": quantity, **extra}, item,
                 [factor(item_id, value, calc=calc)])
    assert result.emission == Decimal(raw)
    assert result.to_api_fields()["emission"] == shown


def test_water_default_and_selected_variant(water, water_factors):
    original = {"item_id": "water", "quantity": 100}
    snapshot = deepcopy(original)
    result = run(original, water, water_factors)
    assert result.emission == Decimal("7.93")
    assert result.variant == "500ml"
    assert result.variant_label == "500mL"
    assert run({**original, "variant": "330ml"}, water, water_factors).emission == Decimal("7.69")
    assert original == snapshot


def test_fixed_delivery():
    item = definition("delivery", method="fixed_use", unit="회")
    result = run({"item_id": "delivery"}, item, [factor("delivery", "0.33")])
    assert result.quantity == 1
    assert result.emission == Decimal("0.33")
    assert result.cost is None


@pytest.mark.parametrize("price,cost", [(None, None), (0, 0), (6750, 337500)])
def test_cost_null_free_and_known(price, cost):
    result = run(ItemInput("eco_bag", 50, unit_price=price), definition("eco_bag"),
                 [factor("eco_bag", "1.833")])
    assert result.cost == cost


@pytest.mark.parametrize("quantity", [0, -1, 1_000_001, 1.5, True, "100", float("nan"), float("inf")])
def test_invalid_quantity(quantity):
    with pytest.raises(CalculationError) as error:
        run({"item_id": "pet_cup", "quantity": quantity}, definition("pet_cup"), [])
    assert error.value.code == "INVALID_QUANTITY"


@pytest.mark.parametrize("field", ["gsm", "duplex", "paper_size", "sheets_per_copy", "unit_weight_g", "weight_kg"])
def test_deleted_v01_fields_rejected_even_if_null(field):
    with pytest.raises(CalculationError) as error:
        run({"item_id": "a4_paper", "quantity": 100, field: None}, definition("a4_paper"), [])
    assert error.value.code == "INVALID_INPUT"
    assert error.value.field == field


@pytest.mark.parametrize("variant", ["3l", "500ML", "", 500])
def test_invalid_variant(water, water_factors, variant):
    with pytest.raises(CalculationError) as error:
        run({"item_id": "water", "quantity": 1, "variant": variant}, water, water_factors)
    assert error.value.code == "INVALID_INPUT"


@pytest.mark.parametrize("value", [None, 0, -1, 50.1, True, "3", float("nan")])
def test_bad_dimensions(value):
    with pytest.raises(CalculationError) as error:
        run({"item_id": "banner", "quantity": 2, "width_m": value, "height_m": 0.9},
            definition("banner", method="dimension", calc="AREA"), [])
    assert error.value.code == "INVALID_INPUT"
    assert error.value.field == "width_m"


@pytest.mark.parametrize("price", [-1, 10_000_001, 1.5, True, "100"])
def test_invalid_price(price):
    with pytest.raises(CalculationError) as error:
        run({"item_id": "pet_cup", "quantity": 1, "unit_price": price}, definition("pet_cup"), [])
    assert error.value.field == "unit_price"


def test_absent_quantity():
    with pytest.raises(CalculationError) as error:
        run({"item_id": "pet_cup"}, definition("pet_cup"), [])
    assert error.value.code == "INVALID_INPUT"


@pytest.mark.parametrize("value", [None, Decimal("-1"), Decimal("NaN")])
def test_unavailable_factor(value):
    f = replace(factor("pet_cup", "1"), value=value)
    with pytest.raises(CalculationError) as error:
        run({"item_id": "pet_cup", "quantity": 1}, definition("pet_cup"), [f])
    assert error.value.code == "CALC_NOT_AVAILABLE"


def test_no_silent_version_fallback():
    with pytest.raises(CalculationError) as error:
        run({"item_id": "pet_cup", "quantity": 1}, definition("pet_cup"),
            [factor("pet_cup", "0.0778", version="old")])
    assert error.value.code == "CALC_NOT_AVAILABLE"


def test_duplicate_factor_rejected():
    f = factor("pet_cup", "0.0778")
    with pytest.raises(CalculationError):
        run({"item_id": "pet_cup", "quantity": 1}, definition("pet_cup"), [f, f])


def test_missing_default_is_not_arbitrary_selection(water, water_factors):
    item = replace(water, variants=(Variant("500ml", "500mL"),))
    with pytest.raises(CalculationError) as error:
        run({"item_id": "water", "quantity": 1}, item, water_factors)
    assert error.value.code == "CALC_NOT_AVAILABLE"


def test_zero_factor_is_real_zero():
    result = run({"item_id": "sample", "quantity": 1}, definition("sample"), [factor("sample", "0")])
    assert result.emission == 0


def test_precision_and_response_rounding_only():
    with localcontext() as context:
        context.prec = 6  # 호출 측 Decimal 환경이 낮아도 곱셈은 정확해야 한다.
        result = run({"item_id": "sample", "quantity": 1_000_000}, definition("sample"),
                     [factor("sample", "0.12345678901234567890123456789")])
    assert result.emission == Decimal("123456.78901234567890123456789")
    assert result.to_api_fields()["emission"] == 123456.79
    tie = run({"item_id": "sample", "quantity": 1}, definition("sample"), [factor("sample", "0.005")])
    assert tie.to_api_fields()["emission"] == 0.01


def test_metadata_and_source_pass_through():
    item = replace(definition("sample"), notes=("잠정값",))
    f = replace(factor("sample", "1"), notes=("잠정값", "참고값"), confidence="D",
                source_name="ECOSQUARE", source_url="https://ecosq.or.kr/", scope_group="production")
    result = run({"item_id": "sample", "quantity": 1}, item, [f])
    api = result.to_api_fields()
    assert api["notes"] == ["잠정값", "참고값"]
    assert api["source"]["factor_version"] == VERSION
    assert api["source"]["name"] == "ECOSQUARE"
    assert api["confidence"] == "D"
    assert "ratio" not in api


@pytest.mark.parametrize("data,method", [
    ({"item_id": "sample", "quantity": 1, "variant": "small"}, "count_only"),
    ({"item_id": "sample", "quantity": 1, "width_m": 2}, "count_only"),
    ({"item_id": "sample", "quantity": 1}, "fixed_use"),
    ({"item_id": "sample", "unit_price": 0}, "fixed_use"),
])
def test_inapplicable_fields(data, method):
    with pytest.raises(CalculationError) as error:
        run(data, definition("sample", method=method), [])
    assert error.value.code == "INVALID_INPUT"


def test_inactive_and_unknown_item():
    for item in [replace(definition("sample"), is_active=False), definition("different")]:
        with pytest.raises(CalculationError) as error:
            run({"item_id": "sample", "quantity": 1}, item, [])
        assert error.value.code == "UNKNOWN_ITEM"


def test_old_weight_type_not_supported():
    with pytest.raises(CalculationError) as error:
        run({"item_id": "sample", "quantity": 1}, definition("sample", calc="WEIGHT"), [])
    assert error.value.code == "CALC_NOT_AVAILABLE"


# 행사 전체 분석 / 추천 / 비교 및 25개 품목 통합 검증
import json
from calculator import analyze_scenario, calculate_recommendation_effect, compare_scenarios
from calculator.catalogue import catalogue_from_records

CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "calculator" / "catalogue_v02.json"
CATALOGUE = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def catalogue():
    items, factors = catalogue_from_records(CATALOGUE["items"], CATALOGUE["factors"])
    return dict(items=items, factors=factors, factor_version=CATALOGUE["factor_version"])


@pytest.fixture
def sample_inputs():
    return [
        {"item_id": "leaflet", "quantity": 300, "variant": "a4", "unit_price": 450},
        {"item_id": "banner", "quantity": 2, "width_m": 3, "height_m": 0.9},
        {"item_id": "water", "quantity": 100, "variant": "500ml", "unit_price": 430},
        {"item_id": "paper_cup", "quantity": 100},
        {"item_id": "pet_drink", "quantity": 50, "variant": "500ml"},
        {"item_id": "hygiene_gloves", "quantity": 100, "variant": "pack_400"},
        {"item_id": "sandwich", "quantity": 100, "unit_price": 4600},
        {"item_id": "eco_bag", "quantity": 50, "unit_price": 6750},
        {"item_id": "delivery"},
    ]


def analysis(inputs, catalogue, participants=100, budget=1_000_000):
    return analyze_scenario(inputs, **catalogue, participants=participants,
                            budget=budget, scenario_id="SCN_original")


def comparison(before, after, catalogue, replacements=None):
    return compare_scenarios(before, after, **catalogue, participants=100,
                             original_scenario_id="SCN_original", improved_scenario_id="SCN_improved",
                             budget=1_000_000, replacements=replacements)


def test_v02_nine_item_integration(catalogue, sample_inputs):
    snapshot = deepcopy(sample_inputs)
    raw = analysis(sample_inputs, catalogue)
    api = raw.to_api_response()
    assert raw.total_emission == Decimal("179.34894")
    assert api["total_emission"] == 179.35
    assert api["emission_per_person"] == 1.79
    assert api["total_cost"] == 975500
    assert api["priced_item_count"] == 4
    assert api["budget_usage_rate"] == 97.6
    assert api["top_items"] == ["eco_bag", "sandwich", "pet_drink"]
    assert api["top_items_share"] == 87.3
    assert len(api["by_item"]) == 9
    assert len(api["by_category"]) == 5
    assert api["warnings"] == ["계산 범위가 다른 자료를 포함함"]
    assert [r["emission"] for r in api["by_category"]] == [91.65, 56.0, 22.44, 8.93, 0.33]
    assert api["by_item"][0]["ratio"] == 51.1
    assert sample_inputs == snapshot
    json.dumps(api, ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize("budget", [None, 0])
def test_budget_absent_or_zero(catalogue, budget):
    result = analysis([{"item_id": "water", "quantity": 1, "unit_price": 0}], catalogue, budget=budget)
    api = result.to_api_response()
    assert api["budget_usage_rate"] is None
    assert api["total_cost"] == 0
    assert api["priced_item_count"] == 1


def test_no_prices_are_not_zero(catalogue):
    api = analysis([{"item_id": "pet_cup", "quantity": 100}], catalogue).to_api_response()
    assert api["total_cost"] is None
    assert api["by_item"][0]["cost"] is None
    assert api["priced_item_count"] == 0
    assert api["budget_usage_rate"] is None


def test_raw_sums_and_ratios_not_rounded_items():
    items = {id: definition(id) for id in ["a", "b", "c", "d"]}
    factors = [factor(id, "0.005") for id in items]
    result = analyze_scenario([{"item_id": id, "quantity": 1} for id in items],
                              items=items, factors=factors, factor_version=VERSION,
                              participants=3, scenario_id="s")
    api = result.to_api_response()
    assert result.total_emission == Decimal("0.020")
    assert api["total_emission"] == 0.02  # 0.01씩 4개를 더한 0.04가 아님
    assert api["emission_per_person"] == 0.01
    assert all(row["ratio"] == 25.0 for row in api["by_item"])
    assert api["top_items_share"] == 75.0


def test_zero_total_ratios_are_null():
    result = analyze_scenario([{"item_id": "zero", "quantity": 1}], items={"zero": definition("zero")},
                              factors=[factor("zero", "0")], factor_version=VERSION,
                              participants=1, scenario_id="s")
    api = result.to_api_response()
    assert api["total_emission"] == 0
    assert api["by_item"][0]["ratio"] is None
    assert api["by_category"][0]["ratio"] is None
    assert api["top_items_share"] is None


@pytest.mark.parametrize("participants,budget", [(0, None), (True, None), (1.5, None), (1, -1), (1, True)])
def test_invalid_event_inputs(catalogue, participants, budget):
    with pytest.raises(CalculationError):
        analysis([{"item_id": "water", "quantity": 1}], catalogue, participants, budget)


def test_no_items_and_duplicate(catalogue):
    for payload, code in [([], "NO_ITEMS"), ([{"item_id": "water", "quantity": 1}]*2, "DUPLICATE_ITEM")]:
        with pytest.raises(CalculationError) as error:
            analysis(payload, catalogue)
        assert error.value.code == code


def test_line_error_path_and_no_partial_total(catalogue):
    with pytest.raises(CalculationError) as error:
        analysis([{"item_id": "water", "quantity": 1},
                  {"item_id": "banner", "quantity": 1, "height_m": 1}], catalogue)
    assert error.value.field == "items[1].width_m"


def test_single_scope_no_warning(catalogue):
    result = analysis([{"item_id": "water", "quantity": 1}, {"item_id": "paper_cup", "quantity": 1}], catalogue)
    assert result.to_api_response()["warnings"] == []


def test_reduce_eco_bag(catalogue):
    effect = calculate_recommendation_effect({"item_id": "eco_bag", "quantity": 50, "unit_price": 6750},
                                             action_type="reduce_quantity", recommended_value=30, **catalogue)
    assert effect.can_calculate
    assert effect.before.emission == Decimal("91.65")
    assert effect.after.emission == Decimal("54.99")
    assert effect.to_api_fields() == {"emission_reduction": 36.66, "cost_change": -135000}
    assert effect.reduction_rate == 40.0


def test_replace_pet_to_can(catalogue):
    effect = calculate_recommendation_effect({"item_id": "pet_drink", "quantity": 50, "variant": "500ml", "unit_price": 980},
                                             action_type="replace_item", alternative_item_id="can_drink",
                                             alternative_variant="250ml", **catalogue)
    assert effect.can_calculate
    assert effect.before.emission == Decimal("8.99")
    assert effect.after.emission == Decimal("4.68")
    assert effect.to_api_fields() == {"emission_reduction": 4.31, "cost_change": None}
    assert effect.after.cost is None  # 원본 가격을 대체 품목으로 복사하지 않음


def test_known_replacement_price(catalogue):
    effect = calculate_recommendation_effect({"item_id": "pet_drink", "quantity": 50, "unit_price": 980},
                                             action_type="replace_item", alternative_item_id="can_drink",
                                             alternative_unit_price=790, **catalogue)
    assert effect.can_calculate
    assert effect.cost_change == -9500
    assert effect.after.variant == "250ml"  # 대체 기본 변형


@pytest.mark.parametrize("target", ["water", "banner", "delivery", "missing"])
def test_incompatible_replacement_filtered(catalogue, target):
    effect = calculate_recommendation_effect({"item_id": "pet_drink", "quantity": 50},
                                             action_type="replace_item", alternative_item_id=target, **catalogue)
    assert not effect.can_calculate
    assert effect.to_api_fields() == {"emission_reduction": None, "cost_change": None}
    assert effect.error is not None


@pytest.mark.parametrize("value", [0, -1, 50, 51, 1.5, True, None])
def test_bad_reduction_is_not_effect(catalogue, value):
    effect = calculate_recommendation_effect({"item_id": "eco_bag", "quantity": 50},
                                             action_type="reduce_quantity", recommended_value=value, **catalogue)
    assert not effect.can_calculate
    assert effect.emission_reduction is None


def test_missing_replacement_factor(catalogue):
    catalogue["factors"] = tuple(f for f in catalogue["factors"] if f.item_id != "can_drink")
    effect = calculate_recommendation_effect({"item_id": "pet_drink", "quantity": 50},
                                             action_type="replace_item", alternative_item_id="can_drink", **catalogue)
    assert not effect.can_calculate
    assert effect.error.code == "CALC_NOT_AVAILABLE"


def test_fixed_quantity_recommendation(catalogue):
    effect = calculate_recommendation_effect({"item_id": "delivery"}, action_type="reduce_quantity",
                                             recommended_value=1, **catalogue)
    assert not effect.can_calculate


def test_compare_nine_items_and_unknown_replacement_cost(catalogue, sample_inputs):
    snapshot = deepcopy(sample_inputs)
    after = deepcopy(sample_inputs)
    after[7]["quantity"] = 30
    after[4] = {"item_id": "can_drink", "quantity": 50, "variant": "250ml"}
    result = comparison(sample_inputs, after, catalogue, {"pet_drink": "can_drink"})
    api = result.to_api_response()
    assert result.reduction == Decimal("40.97000")
    assert api["before"]["total_emission"] == 179.35
    assert api["after"]["total_emission"] == 138.38
    assert api["reduction"] == 40.97
    assert api["reduction_rate"] == 22.8
    assert api["after"]["total_cost"] == 840500  # 알 수 있는 비용 합계
    assert api["cost_change"] is None  # 교체 비용 미상이라 전체 절감액을 단정하지 않음
    assert len(api["item_comparison"]) == 9
    rows = {r["item_id"]: r for r in api["item_comparison"]}
    assert rows["eco_bag"]["emission_diff"] == -36.66
    assert rows["pet_drink"]["after_item_id"] == "can_drink"
    assert rows["pet_drink"]["after_item_name"] == "캔 음료"
    assert rows["pet_drink"]["before_value"] is None
    assert not rows["sandwich"]["changed"]
    assert sample_inputs == snapshot
    json.dumps(api, allow_nan=False)


def test_reduction_known_cost_despite_unchanged_unpriced_items(catalogue, sample_inputs):
    after = deepcopy(sample_inputs)
    after[7]["quantity"] = 30
    api = comparison(sample_inputs, after, catalogue).to_api_response()
    assert api["cost_change"] == -135000
    assert api["reduction"] == 36.66


def test_default_and_explicit_same_variant_not_changed(catalogue):
    before = [{"item_id": "water", "quantity": 10}]
    after = [{"item_id": "water", "quantity": 10, "variant": "500ml"}]
    api = comparison(before, after, catalogue).to_api_response()
    assert not api["item_comparison"][0]["changed"]
    assert api["cost_change"] is None  # 가격 입력이 하나도 없음


def test_added_and_removed_items_are_all_included(catalogue):
    result = comparison([{"item_id": "water", "quantity": 1, "unit_price": 430}],
                         [{"item_id": "eco_bag", "quantity": 1, "unit_price": 1000}], catalogue)
    api = result.to_api_response()
    assert len(api["item_comparison"]) == 2
    assert api["item_comparison"][0]["after_emission"] == 0  # 실제 품목 제거, 계산 실패가 아님
    assert api["item_comparison"][1]["before_emission"] == 0
    assert api["cost_change"] == 570


def test_incompatible_compare_mapping_rejected(catalogue):
    with pytest.raises(CalculationError):
        comparison([{"item_id": "pet_drink", "quantity": 1}], [{"item_id": "water", "quantity": 1}],
                    catalogue, {"pet_drink": "water"})


def test_replacement_must_preserve_quantity(catalogue):
    with pytest.raises(CalculationError):
        comparison([{"item_id": "pet_drink", "quantity": 2}], [{"item_id": "can_drink", "quantity": 1}],
                    catalogue, {"pet_drink": "can_drink"})


def test_comparison_zero_total_rate_null():
    records = [dict(item_id="zero", quantity=1)]
    api = compare_scenarios(records, records, items={"zero": definition("zero")}, factors=[factor("zero", "0")],
                            factor_version=VERSION, participants=1, original_scenario_id="old",
                            improved_scenario_id="new").to_api_response()
    assert api["reduction"] == 0
    assert api["reduction_rate"] is None


@pytest.mark.parametrize("row", CATALOGUE["factors"], ids=lambda row: row["item_id"]+":"+row["variant"])
def test_all_25_items_and_39_factors(catalogue, row):
    item = catalogue["items"][row["item_id"]]
    payload = {"item_id": item.item_id}
    if item.input_method != "fixed_use":
        payload["quantity"] = 1
    if item.input_method == "count_variant":
        payload["variant"] = row["variant"]
    if item.input_method == "dimension":
        payload.update(width_m=1, height_m=1)
    result = calculate_item(payload, item=item, factors=catalogue["factors"], factor_version=catalogue["factor_version"])
    assert result.emission == Decimal(row["value"])


def test_all_25_items_in_one_scenario(catalogue):
    payloads = []
    for item in catalogue["items"].values():
        row = {"item_id": item.item_id}
        if item.input_method != "fixed_use":
            row["quantity"] = 1
        if item.input_method == "dimension":
            row.update(width_m=1, height_m=1)
        payloads.append(row)
    result = analysis(payloads, catalogue)
    assert len(result.results) == 25
    assert len(result.to_api_response()["by_item"]) == 25
    assert result.total_emission == sum((r.emission for r in result.results), Decimal(0))


def test_unrelated_null_field_is_rejected(catalogue):
    item = catalogue["items"]["paper_cup"]
    with pytest.raises(CalculationError) as error:
        calculate_item({"item_id": "paper_cup", "quantity": 1, "variant": None}, item=item,
                       factors=catalogue["factors"], factor_version=catalogue["factor_version"])
    assert error.value.code == "INVALID_INPUT"
    with pytest.raises(CalculationError):
        analysis([{"item_id": "paper_cup", "quantity": 1, "variant": None}], catalogue)


def test_two_replacements_to_same_item_rejected(catalogue):
    with pytest.raises(CalculationError) as error:
        comparison([{"item_id": "pet_drink", "quantity": 1}, {"item_id": "paper_cup", "quantity": 1}],
                    [{"item_id": "can_drink", "quantity": 1}], catalogue,
                    {"pet_drink": "can_drink", "paper_cup": "can_drink"})
    assert error.value.code == "CONFLICTING_RECOMMENDATIONS"


def test_recommendation_does_not_mutate_input(catalogue):
    request = {"item_id": "pet_drink", "quantity": 50, "unit_price": 1000}
    snapshot = deepcopy(request)
    calculate_recommendation_effect(request, action_type="replace_item", alternative_item_id="can_drink", **catalogue)
    assert request == snapshot


def test_scope_warning_recomputed_for_each_scenario(catalogue):
    result = comparison([{"item_id": "eco_bag", "quantity": 1}, {"item_id": "paper_cup", "quantity": 1}],
                         [{"item_id": "paper_cup", "quantity": 1}], catalogue)
    assert result.before.warnings == ("계산 범위가 다른 자료를 포함함",)
    assert result.after.warnings == ()


def test_variant_labels_notes_and_exact_defaults(catalogue):
    result = analysis([{"item_id": "snack", "quantity": 1, "variant": "small"},
                       {"item_id": "poster", "quantity": 1}], catalogue)
    results = {r.item_id: r for r in result.results}
    assert results["snack"].emission == Decimal("0.092")
    assert results["snack"].variant_label == "소형"
    assert "잠정값" in results["snack"].notes
    assert results["poster"].variant == "a3"
    assert results["poster"].emission == Decimal("0.025262")


def test_per_person_uses_unrounded_total():
    item = definition("small")
    result = analyze_scenario([{"item_id": "small", "quantity": 1}], items={"small": item},
                              factors=[factor("small", "0.01499")], factor_version=VERSION,
                              participants=2, scenario_id="s")
    api = result.to_api_response()
    assert api["total_emission"] == 0.01
    assert api["emission_per_person"] == 0.01  # 원값 .007495 -> .01


def test_response_rounding_survives_low_decimal_context(catalogue, sample_inputs):
    with localcontext() as ctx:
        ctx.prec = 3
        result = analysis(sample_inputs, catalogue)
        assert result.total_emission == Decimal("179.34894")
        assert result.to_api_response()["total_emission"] == 179.35


def test_count_and_area_mismatch_for_same_unit_is_rejected(catalogue):
    effect = calculate_recommendation_effect({"item_id": "pet_cup", "quantity": 1},
                                             action_type="replace_item", alternative_item_id="banner", **catalogue)
    assert not effect.can_calculate


def test_compare_unknown_cost_does_not_fake_savings(catalogue):
    result = comparison([{"item_id": "pet_drink", "quantity": 1, "unit_price": 1000}],
                         [{"item_id": "can_drink", "quantity": 1}], catalogue,
                         {"pet_drink": "can_drink"})
    api = result.to_api_response()
    assert api["before"]["total_cost"] == 1000
    assert api["after"]["total_cost"] is None
    assert api["cost_change"] is None
