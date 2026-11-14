"""
API 테스트 (백엔드2)

실행:  pytest -q      (backend 폴더에서)
명세서 v02 예시(경영학과 학술제) 흐름과 주요 오류 응답을 확인합니다.
"""
import pytest
from fastapi.testclient import TestClient

from main import app
from services import adapters

client = TestClient(app)

EXAMPLE_ITEMS = [
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


@pytest.fixture(autouse=True)
def _reset():
    adapters.reset_store()


def _create_event(budget=1000000):
    res = client.post("/api/events", json={
        "event_name": "경영학과 학술제", "event_type": "학과·학생회 행사", "participants": 100, "budget": budget,
    })
    assert res.status_code == 200, res.text
    return res.json()["event_id"]


def _event_with_items():
    event_id = _create_event()
    res = client.put(f"/api/events/{event_id}/items", json={"items": EXAMPLE_ITEMS})
    assert res.status_code == 200, res.text
    return event_id


# ---------------------------------------------------------------------------
# 정상 흐름
# ---------------------------------------------------------------------------
def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_list_items():
    res = client.get("/api/items")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 25
    leaflet = next(i for i in items if i["item_id"] == "leaflet")
    assert leaflet["input_method"] == "count_variant"
    assert [v["variant"] for v in leaflet["variants"] if v["is_default"]] == ["a4"]


def test_list_items_by_category_name_and_code():
    by_name = client.get("/api/items", params={"category": "굿즈"}).json()["items"]
    by_code = client.get("/api/items", params={"category": "goods"}).json()["items"]
    assert len(by_name) == len(by_code) == 5


def test_full_flow_example():
    event_id = _event_with_items()

    # 분석
    res = client.post(f"/api/events/{event_id}/analyze")
    assert res.status_code == 200, res.text
    analysis = res.json()
    assert analysis["scenario_type"] == "original"
    assert analysis["total_cost"] == 975500
    assert analysis["priced_item_count"] == 4
    assert analysis["budget_usage_rate"] == 97.6
    eco_bag = next(i for i in analysis["by_item"] if i["item_id"] == "eco_bag")
    assert eco_bag["emission"] == pytest.approx(50 * 1.833, abs=0.01)  # 계산기 catalogue_v02 계수
    assert len(analysis["top_items"]) == 3

    # 추천
    res = client.post(f"/api/events/{event_id}/recommend", json={"goal": {"budget_increase_allowed": False}})
    assert res.status_code == 200, res.text
    recs = res.json()["recommendations"]
    assert recs, "추천이 1개 이상 있어야 함"
    for rec in recs:
        assert rec["emission_reduction"] > 0
        assert rec["category"]

    # 비교: 품목이 서로 다른 추천 2개까지 적용
    applicable = [r for r in recs if r["applicable"]]
    chosen, seen = [], set()
    for rec in applicable:
        if rec["item_id"] not in seen:
            chosen.append(rec["rec_id"])
            seen.add(rec["item_id"])
        if len(chosen) == 2:
            break
    res = client.post(f"/api/events/{event_id}/compare", json={"applied_rec_ids": chosen})
    assert res.status_code == 200, res.text
    comparison = res.json()
    assert comparison["after"]["total_emission"] < comparison["before"]["total_emission"]
    assert len(comparison["item_comparison"]) == len(EXAMPLE_ITEMS)
    assert sum(1 for i in comparison["item_comparison"] if i["changed"]) == len(chosen)


def test_replace_recommendation_fields():
    event_id = _event_with_items()
    recs = client.post(f"/api/events/{event_id}/recommend").json()["recommendations"]
    replace = next(r for r in recs if r["action_type"] == "replace_item")
    assert replace["target_field"] == "item_id"
    assert replace["current_value"] is None
    assert replace["alternative_item_id"] == "can_drink"
    assert replace["emission_reduction"] == pytest.approx(50 * (0.1798 - 0.0936), abs=0.01)

    comparison = client.post(f"/api/events/{event_id}/compare",
                             json={"applied_rec_ids": [replace["rec_id"]]}).json()
    row = next(i for i in comparison["item_comparison"] if i["item_id"] == "pet_drink")
    assert row["before_item_id"] == "pet_drink"
    assert row["after_item_id"] == "can_drink"
    assert row["before_value"] is None


# ---------------------------------------------------------------------------
# 오류 응답
# ---------------------------------------------------------------------------
def test_event_validation_error_format():
    res = client.post("/api/events", json={"event_name": "", "event_type": "특강", "participants": 0})
    assert res.status_code == 400
    body = res.json()
    assert body["error"] == "INVALID_INPUT"
    assert set(body) == {"error", "field", "message"}


def test_no_items():
    event_id = _create_event()
    res = client.put(f"/api/events/{event_id}/items", json={"items": []})
    assert res.status_code == 400
    assert res.json()["error"] == "NO_ITEMS"


def test_unknown_and_duplicate_item():
    event_id = _create_event()
    res = client.put(f"/api/events/{event_id}/items", json={"items": [{"item_id": "car", "quantity": 1}]})
    assert res.json()["error"] == "UNKNOWN_ITEM"
    res = client.put(f"/api/events/{event_id}/items", json={"items": [
        {"item_id": "paper_cup", "quantity": 1}, {"item_id": "paper_cup", "quantity": 2}]})
    assert res.json()["error"] == "DUPLICATE_ITEM"
    assert res.json()["field"] == "items[1].item_id"


def test_quantity_rules():
    event_id = _create_event()
    res = client.put(f"/api/events/{event_id}/items", json={"items": [{"item_id": "paper_cup", "quantity": 0}]})
    assert res.json()["error"] == "INVALID_QUANTITY"
    res = client.put(f"/api/events/{event_id}/items", json={"items": [{"item_id": "paper_cup", "quantity": 1.5}]})
    assert res.json()["error"] == "INVALID_QUANTITY"


def test_input_method_rules():
    event_id = _create_event()
    # 현수막 가로 누락
    res = client.put(f"/api/events/{event_id}/items", json={"items": [{"item_id": "banner", "quantity": 1, "height_m": 1}]})
    assert res.json() == {"error": "INVALID_INPUT", "field": "items[0].width_m",
                          "message": "현수막 가로(m)를 입력해 주세요"}
    # count_only 품목에 variant
    res = client.put(f"/api/events/{event_id}/items", json={"items": [{"item_id": "paper_cup", "quantity": 1, "variant": "a4"}]})
    assert res.json()["error"] == "INVALID_INPUT"
    # 없는 변형
    res = client.put(f"/api/events/{event_id}/items", json={"items": [{"item_id": "water", "quantity": 1, "variant": "3l"}]})
    assert res.json()["field"] == "items[0].variant"
    # 삭제된 필드(duplex)
    res = client.put(f"/api/events/{event_id}/items", json={"items": [{"item_id": "a4_paper", "quantity": 1, "duplex": True}]})
    assert res.json()["error"] == "INVALID_INPUT"


def test_not_found():
    assert client.post("/api/events/EVT_9999/analyze").json()["error"] == "EVENT_NOT_FOUND"
    event_id = _event_with_items()
    other_event = _event_with_items()
    other_scenario = client.post(f"/api/events/{other_event}/analyze").json()["scenario_id"]
    res = client.post(f"/api/events/{event_id}/analyze", json={"scenario_id": other_scenario})
    assert res.status_code == 404
    assert res.json()["error"] == "SCENARIO_NOT_FOUND"


def test_custom_condition_limit():
    event_id = _event_with_items()
    res = client.post(f"/api/events/{event_id}/recommend", json={"goal": {"custom_condition": "가" * 301}})
    assert res.status_code == 400
    assert res.json()["field"] == "goal.custom_condition"


def test_stale_after_items_updated():
    event_id = _event_with_items()
    rec_id = client.post(f"/api/events/{event_id}/recommend").json()["recommendations"][0]["rec_id"]
    client.put(f"/api/events/{event_id}/items", json={"items": EXAMPLE_ITEMS})  # 입력 수정 → 추천 무효
    res = client.post(f"/api/events/{event_id}/compare", json={"applied_rec_ids": [rec_id]})
    assert res.status_code == 409
    assert res.json()["error"] == "STALE_DATA"


def test_conflicting_recommendations():
    event_id = _event_with_items()
    recs = client.post(f"/api/events/{event_id}/recommend").json()["recommendations"]
    # 같은 품목 추천 2개를 직접 만들어 확인 (임시 AI 는 품목당 1개만 추천하므로)
    first = recs[0]
    with adapters.transaction():
        scenario = adapters.find_scenario(event_id, "original")
        extra = adapters.replace_recommendations(event_id, scenario["scenario_id"], [
            {k: first[k] for k in first if k != "rec_id"},
            {k: first[k] for k in first if k != "rec_id"},
        ], scenario["version"])
    res = client.post(f"/api/events/{event_id}/compare", json={"applied_rec_ids": [r["rec_id"] for r in extra]})
    assert res.status_code == 400
    assert res.json()["error"] == "CONFLICTING_RECOMMENDATIONS"


def test_ai_unavailable(monkeypatch):
    event_id = _event_with_items()

    def broken_ai(_):
        raise RuntimeError("AI 서버 오류")

    monkeypatch.setattr(adapters, "call_ai", broken_ai)
    res = client.post(f"/api/events/{event_id}/recommend")
    assert res.status_code == 503
    assert res.json()["error"] == "AI_UNAVAILABLE"
