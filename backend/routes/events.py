"""POST /api/events, PUT /api/events/{event_id}/items (백엔드2)"""
from fastapi import APIRouter

from schemas.events import EventCreateRequest, EventCreateResponse, ItemsSaveRequest, ItemsSaveResponse
from services import event_service

router = APIRouter(tags=["2. 행사·품목 입력"])


@router.post("/events", response_model=EventCreateResponse, summary="행사 생성 (1번 화면 '다음')")
def create_event(req: EventCreateRequest):
    return event_service.create_event(req)


@router.put("/events/{event_id}/items", response_model=ItemsSaveResponse,
            summary="품목 입력 저장 (2번 화면 '다음', original 품목 통째로 덮어쓰기)")
def save_items(event_id: str, req: ItemsSaveRequest):
    return event_service.save_items(event_id, req)
