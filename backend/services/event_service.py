"""
행사 생성·품목 저장 처리 흐름 (백엔드2) — 명세서 v02 2·3번

다른 서비스에서도 쓰는 공통 함수(행사·시나리오 조회, 반올림)가 여기에 있습니다.
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from core.errors import ApiError, ErrorCode
from schemas.events import (
    EventCreateRequest,
    EventCreateResponse,
    ItemInput,
    ItemsSaveRequest,
    ItemsSaveResponse,
)
from services import adapters


# ---------------------------------------------------------------------------
# 공통 함수
# ---------------------------------------------------------------------------
def _round_half_up(value: Optional[float], places: str) -> Optional[float]:
    # 파이썬 round() 는 97.55 → 97.5 처럼 내릴 수 있어서 일반 반올림으로 계산
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP))


def round2(value: Optional[float]) -> Optional[float]:
    """배출량: 소수 둘째 자리"""
    return _round_half_up(value, "0.01")


def round1(value: Optional[float]) -> Optional[float]:
    """비율(%): 소수 첫째 자리"""
    return _round_half_up(value, "0.1")


def get_event_or_raise(event_id: str) -> Dict[str, Any]:
    event = adapters.get_event(event_id)
    if event is None:
        raise ApiError(ErrorCode.EVENT_NOT_FOUND)
    return event


def resolve_scenario(event_id: str, scenario_id: Optional[str], field: str = "scenario_id") -> Dict[str, Any]:
    """scenario_id 를 생략하면 original. 다른 행사의 시나리오면 없는 것으로 봄 (소속 확인)"""
    if scenario_id is None:
        scenario = adapters.find_scenario(event_id, "original")
    else:
        scenario = adapters.get_scenario(scenario_id)
        if scenario is not None and scenario["event_id"] != event_id:
            scenario = None
    if scenario is None:
        raise ApiError(ErrorCode.SCENARIO_NOT_FOUND, field=field if scenario_id else None)
    return scenario


# ---------------------------------------------------------------------------
# 2. POST /api/events
# ---------------------------------------------------------------------------
def create_event(req: EventCreateRequest) -> EventCreateResponse:
    data = req.model_dump()
    data["event_date"] = req.event_date.isoformat() if req.event_date else None
    event_id, scenario_id = adapters.create_event(data)
    return EventCreateResponse(event_id=event_id, scenario_id=scenario_id, created=True)


# ---------------------------------------------------------------------------
# 3. PUT /api/events/{event_id}/items
# ---------------------------------------------------------------------------
_FIELDS_BY_METHOD = {
    # input_method 별로 보낼 수 있는 입력 필드 (item_id, unit_price 제외)
    "count_only": {"quantity"},
    "count_variant": {"quantity", "variant"},
    "dimension": {"quantity", "width_m", "height_m"},
    "fixed_use": set(),
}
_INPUT_FIELDS = ("quantity", "variant", "width_m", "height_m")


def _validate_item(index: int, item_input: ItemInput) -> Dict[str, Any]:
    """품목 1줄 검증 후 저장할 값(기본 변형 적용) 반환"""
    path = f"items[{index}]"
    item = adapters.get_item(item_input.item_id)
    if item is None:
        raise ApiError(ErrorCode.UNKNOWN_ITEM, field=f"{path}.item_id")

    method = item["input_method"]
    allowed = _FIELDS_BY_METHOD[method]
    for name in _INPUT_FIELDS:
        if getattr(item_input, name) is not None and name not in allowed:
            raise ApiError(ErrorCode.INVALID_INPUT, f"{item['item_name']}에는 {name} 값을 보낼 수 없습니다",
                           f"{path}.{name}")
    if method == "fixed_use" and item_input.unit_price is not None:
        raise ApiError(ErrorCode.INVALID_INPUT, f"{item['item_name']}은(는) 단가를 받지 않습니다",
                       f"{path}.unit_price")

    # 수량: fixed_use 는 1 고정, 나머지는 필수·정수
    if method == "fixed_use":
        quantity = 1
    else:
        if item_input.quantity is None:
            raise ApiError(ErrorCode.INVALID_QUANTITY, f"{item['item_name']} 수량을 입력해 주세요", f"{path}.quantity")
        if not float(item_input.quantity).is_integer():
            raise ApiError(ErrorCode.INVALID_QUANTITY, f"{item['item_name']} 수량은 정수로 입력해 주세요",
                           f"{path}.quantity")
        quantity = int(item_input.quantity)

    # 현수막: 가로·세로 필수
    if method == "dimension":
        for name, label in (("width_m", "가로(m)"), ("height_m", "세로(m)")):
            if getattr(item_input, name) is None:
                raise ApiError(ErrorCode.INVALID_INPUT, f"{item['item_name']} {label}를 입력해 주세요",
                               f"{path}.{name}")

    # 변형: 비우면 기본 변형, 있으면 허용된 값인지 확인
    variant_code = None
    if method == "count_variant":
        if item_input.variant is None:
            default = adapters.default_variant(item)
            if default is None:
                raise ApiError(ErrorCode.INVALID_INPUT, f"{item['item_name']}의 종류를 선택해 주세요",
                               f"{path}.variant")
            variant_code = default["variant"]
        elif adapters.get_variant(item, item_input.variant) is None:
            raise ApiError(ErrorCode.INVALID_INPUT, f"{item['item_name']}에서 선택할 수 없는 종류입니다",
                           f"{path}.variant")
        else:
            variant_code = item_input.variant

    return {
        "item_id": item["item_id"],
        "quantity": quantity,
        "variant": variant_code,
        "width_m": item_input.width_m,
        "height_m": item_input.height_m,
        "unit_price": item_input.unit_price,
    }


def save_items(event_id: str, req: ItemsSaveRequest) -> ItemsSaveResponse:
    get_event_or_raise(event_id)
    scenario = resolve_scenario(event_id, None)

    if not req.items:
        raise ApiError(ErrorCode.NO_ITEMS, field="items")

    seen: Dict[str, int] = {}
    rows: List[Dict[str, Any]] = []
    for index, item_input in enumerate(req.items):
        if item_input.item_id in seen:
            raise ApiError(ErrorCode.DUPLICATE_ITEM, field=f"items[{index}].item_id")
        seen[item_input.item_id] = index
        rows.append(_validate_item(index, item_input))

    # 한 트랜잭션: 품목 통째로 교체 + 기존 추천·improved 삭제
    with adapters.transaction():
        adapters.replace_scenario_items(scenario["scenario_id"], rows)

    return ItemsSaveResponse(event_id=event_id, scenario_id=scenario["scenario_id"], saved=True,
                             item_count=len(rows))
