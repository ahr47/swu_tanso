"""실행: backend에서 python -m calculator.example. 실제 DB·AI 대신 제공 v02 데이터를 사용."""
from copy import deepcopy
import json
from pathlib import Path

from . import analyze_scenario, calculate_recommendation_effect, compare_scenarios
from .catalogue import catalogue_from_records


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


def main():
    data = json.loads(Path(__file__).with_name("catalogue_v02.json").read_text(encoding="utf-8"))
    items, factors = catalogue_from_records(data["items"], data["factors"])
    # 실서비스에서는 DB 조회 결과를 위 객체로 변환하고 CURRENT_FACTOR_VERSION을 서버가 전달한다.
    common = dict(items=items, factors=factors, factor_version=data["factor_version"])
    original = sample_inputs()
    analysis = analyze_scenario(original, participants=100, budget=1_000_000,
                                 scenario_id="SCN_0001", **common)
    eco_effect = calculate_recommendation_effect(original[7], action_type="reduce_quantity",
                                                 recommended_value=30, **common)
    can_effect = calculate_recommendation_effect(original[4], action_type="replace_item",
                                                 alternative_item_id="can_drink", alternative_variant="250ml", **common)
    # 백엔드2가 검증된 추천으로 개선안 목록을 작성한 결과를 전달하는 예시.
    improved = deepcopy(original)
    improved[7]["quantity"] = 30
    improved[4] = {"item_id": "can_drink", "quantity": 50, "variant": "250ml"}
    comparison = compare_scenarios(original, improved, participants=100, budget=1_000_000,
                                   original_scenario_id="SCN_0001", improved_scenario_id="SCN_0002",
                                   replacements={"pet_drink": "can_drink"}, **common)
    print(json.dumps({"analyze": analysis.to_api_response(),
                      "recommendation_effects": [eco_effect.to_api_fields(), can_effect.to_api_fields()],
                      "compare": comparison.to_api_response()}, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
