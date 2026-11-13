"""DB 전용 테스트 (백엔드1). TEST_DATABASE_URL 이 있을 때만 실행 — conftest.py 참고"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import os
from main import app
from services import adapters

TEST_DB = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL 이 없으면 건너뜀")
client = TestClient(app)
CATALOGUE = json.loads((Path(__file__).resolve().parents[1] / "calculator" / "catalogue_v02.json").read_text("utf-8"))


@pytest.fixture(autouse=True)
def _reset():
    adapters.reset_store()
    yield
    adapters.reset_store()


def _event(items):
    res = client.post("/api/events", json={"event_name": "DB 테스트", "event_type": "축제", "participants": 10,
                                           "event_date": "2026-11-20", "location": "중앙광장"})
    event_id = res.json()["event_id"]
    assert client.put(f"/api/events/{event_id}/items", json={"items": items}).status_code == 200
    return event_id


def test_seed_matches_backend3_catalogue():
    from db.repositories import item_repository

    items, factors = item_repository.fetch_catalogue()
    assert [i["item_id"] for i in items] == [i["item_id"] for i in CATALOGUE["items"]]
    assert len(factors) == len(CATALOGUE["factors"]) == 39
    leaflet = next(i for i in items if i["item_id"] == "leaflet")
    assert [(v["variant"], v["is_default"]) for v in leaflet["variants"]] == \
        [(v["variant"], v["is_default"]) for v in next(i for i in CATALOGUE["items"] if i["item_id"] == "leaflet")["variants"]]


def test_ids_and_event_round_trip():
    event_id = _event([{"item_id": "a4_paper", "quantity": 100}])
    assert event_id == "EVT_0001"
    event = adapters.get_event(event_id)
    assert event["event_date"] == "2026-11-20" and event["location"] == "중앙광장"
    scenario = adapters.find_scenario(event_id, "original")
    assert scenario["scenario_id"] == "SCN_0001" and scenario["version"] == 1
    assert scenario["items"] == [{"item_id": "a4_paper", "quantity": 100, "variant": None, "width_m": None,
                                  "height_m": None, "unit_price": None}]


def test_factor_change_in_db_is_used_after_reload():
    from db.connection import connection

    event_id = _event([{"item_id": "a4_paper", "quantity": 100}])
    before = client.post(f"/api/events/{event_id}/analyze").json()["total_emission"]
    with connection() as conn:
        conn.execute("UPDATE emission_factors SET value = value * 2 WHERE item_id = 'a4_paper'")
    try:
        adapters.reload_catalogue()
        after = client.post(f"/api/events/{event_id}/analyze").json()["total_emission"]
        assert after == pytest.approx(before * 2, abs=0.01)
    finally:
        with connection() as conn:
            conn.execute("UPDATE emission_factors SET value = value / 2 WHERE item_id = 'a4_paper'")
        adapters.reload_catalogue()


def test_transaction_rolls_back_on_error():
    event_id = _event([{"item_id": "a4_paper", "quantity": 100}])
    scenario = adapters.find_scenario(event_id, "original")
    with pytest.raises(RuntimeError):
        with adapters.transaction():
            adapters.replace_scenario_items(scenario["scenario_id"], [{"item_id": "a4_paper", "quantity": 5}])
            raise RuntimeError("중간 실패")
    current = adapters.get_scenario(scenario["scenario_id"])
    assert current["version"] == 1 and current["items"][0]["quantity"] == 100


def test_recommend_compare_persist_and_items_update_clears():
    event_id = _event([{"item_id": "pet_drink", "quantity": 50, "variant": "500ml"},
                       {"item_id": "eco_bag", "quantity": 50, "unit_price": 6750}])
    recs = client.post(f"/api/events/{event_id}/recommend").json()["recommendations"]
    assert recs and all(r["rec_id"].startswith("REC_") for r in recs)
    stored = adapters.get_recommendations([r["rec_id"] for r in recs])
    assert set(stored) == {r["rec_id"] for r in recs}

    res = client.post(f"/api/events/{event_id}/compare", json={"applied_rec_ids": [r["rec_id"] for r in recs]})
    assert res.status_code == 200, res.text
    improved = adapters.find_scenario(event_id, "improved")
    assert improved["scenario_id"] == res.json()["improved_scenario_id"]

    # 품목을 다시 저장하면 추천·improved 가 지워져야 함
    client.put(f"/api/events/{event_id}/items", json={"items": [{"item_id": "eco_bag", "quantity": 10}]})
    assert adapters.find_scenario(event_id, "improved") is None
    assert adapters.get_recommendations([r["rec_id"] for r in recs]) == {}


def test_health_reports_database():
    assert client.get("/health").json()["database"] == "ok"
