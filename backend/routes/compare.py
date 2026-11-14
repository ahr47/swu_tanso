"""POST /api/events/{event_id}/compare (백엔드2)"""
from fastapi import APIRouter

from schemas.comparison import CompareRequest, CompareResponse
from services import comparison_service

router = APIRouter(tags=["5. 개선안 비교"])


@router.post("/events/{event_id}/compare", response_model=CompareResponse,
             summary="추천 적용 → 개선안 생성 → 전·후 비교 (5번 화면)")
def compare(event_id: str, req: CompareRequest):
    return comparison_service.compare(event_id, req)
