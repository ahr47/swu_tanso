"""
통합 테스트: API(백엔드2) → 계산기(백엔드3) → AI 모듈(백엔드4) 실제 연결 경로

AI_API_KEY 가 입력된 상태를 흉내 내고, OpenAI 호출만 가짜 client 로 바꿉니다 (네트워크·키 불필요).
서비스가 만드는 입력 JSON 이 백엔드4의 엄격한 v02 입력 스키마(ai/schemas.py)를 통과하는지,
AI 출력이 검증·재계산되어 저장·비교까지 이어지는지 확인합니다.
"""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.config import get_settings
from main import app
from services import adapters

client = TestClient(app)

ITEMS = [
    {"item_id": "leaflet", "quantity": 300, "variant": "a4", "unit_price": 450},
    {"item_id": "banner", "quantity": 2, "width_m": 3, "height_m": 0.9},
    {"item_id": "pet_drink", "quantity": 50, "variant": "500ml"},
    {"item_id": "eco_bag", "quantity": 50, "unit_price": 6750},
    {"item_id": "delivery"},
]


def rec(item_id, action, value=None, alt=None, variant=None, title="추천"):
    return {"item_id": item_id, "action_type": action,
            "target_field": "quantity" if action == "reduce_quantity" else "item_id",
            "recommended_value": value, "alternative_item_id": alt, "alternative_variant": variant,
            "title": title, "difficulty": "쉬움", "reason": "테스트 추천입니다."}


class FakeOpenAI:
    """OpenAI Responses API 형태. 받은 요청을 기록하고 정해진 응답(또는 예외)을 돌려줌"""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.responses = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(output_text=json.dumps({"recommendations": outcome}, ensure_ascii=False))


@pytest.fixture(autouse=True)
def _real_ai(monkeypatch):
    adapters.reset_store()
    monkeypatch.setenv("AI_API_KEY", "sk-test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _use_fake(monkeypatch, fake):
    monkeypatch.setattr(adapters, "_get_openai_client", lambda: fake)


def _event_with_items():
    res = client.post("/api/events", json={"event_name": "경영학과 학술제", "event_type": "학과·학생회 행사",
                                           "participants": 100, "budget": 1000000})
    event_id = res.json()["event_id"]
    assert client.put(f"/api/events/{event_id}/items", json={"items": ITEMS}).status_code == 200
    return event_id


def test_ai_input_passes_backend4_schema_and_flow_completes(monkeypatch):
    fake = FakeOpenAI([
        rec("eco_bag", "reduce_quantity", 30, title="에코백 수량 조정"),
        rec("pet_drink", "replace_item", alt="can_drink", variant="250ml", title="캔 음료로 교체"),
        rec("snack", "reduce_quantity", 10, title="행사에 없는 품목"),           # 서비스 검증에서 제외
    ])
    _use_fake(monkeypatch, fake)
    event_id = _event_with_items()

    res = client.post(f"/api/events/{event_id}/recommend", json={"goal": {"budget_increase_allowed": False}})
    assert res.status_code == 200, res.text
    recs = {r["title"]: r for r in res.json()["recommendations"]}
    assert set(recs) == {"에코백 수량 조정", "캔 음료로 교체"}
    assert recs["에코백 수량 조정"]["emission_reduction"] == pytest.approx(20 * 1.833, abs=0.01)
    assert recs["에코백 수량 조정"]["cost_change"] == -20 * 6750

    call = fake.calls[0]
    assert len(fake.calls) == 1
    assert call["model"] == "gpt-6.1-sol"
    assert call["text"]["format"]["type"] == "json_schema"
    payload = json.loads(call["input"].split("\n", 1)[1])
    assert payload["event"]["participants"] == 100
    assert {i["item_id"] for i in payload["items"]} == {i["item_id"] for i in ITEMS}
    assert all(isinstance(a["variants"], list) for a in payload["alternatives"])

    res = client.post(f"/api/events/{event_id}/compare",
                      json={"applied_rec_ids": [r["rec_id"] for r in recs.values()]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reduction"] > 0
    assert body["cost_change"] == -20 * 6750


def test_backend4_retry_is_not_doubled(monkeypatch):
    """백엔드4 모듈이 1회 재시도 후 실패 → 서비스는 다시 부르지 않고 503"""
    fake = FakeOpenAI(TimeoutError("slow"), TimeoutError("still slow"))
    _use_fake(monkeypatch, fake)
    event_id = _event_with_items()

    res = client.post(f"/api/events/{event_id}/recommend")
    assert res.status_code == 503
    assert res.json()["error"] == "AI_UNAVAILABLE"
    assert len(fake.calls) == 2  # 백엔드4 재시도 1회 포함 총 2번


def test_backend4_retry_recovers(monkeypatch):
    fake = FakeOpenAI(RuntimeError("temporary"), [rec("eco_bag", "reduce_quantity", 40, title="에코백 조정")])
    _use_fake(monkeypatch, fake)
    event_id = _event_with_items()

    res = client.post(f"/api/events/{event_id}/recommend")
    assert res.status_code == 200, res.text
    assert [r["title"] for r in res.json()["recommendations"]] == ["에코백 조정"]


def test_analysis_matches_calculator_rounding():
    event_id = _event_with_items()
    res = client.post(f"/api/events/{event_id}/analyze")
    assert res.status_code == 200, res.text
    body = res.json()
    by_id = {i["item_id"]: i for i in body["by_item"]}
    assert by_id["banner"]["emission"] == pytest.approx(2 * 3 * 0.9 * 0.9511, abs=0.005)
    assert by_id["delivery"]["emission"] == 0.33
    assert by_id["eco_bag"]["source"]["factor_version"] == "v1.0-2026-10"
    assert sum(c["ratio"] for c in body["by_category"]) == pytest.approx(100, abs=0.3)
