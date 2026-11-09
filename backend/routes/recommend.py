"""POST /api/events/{event_id}/recommend (백엔드2)"""
from typing import Optional

from fastapi import APIRouter, Body

from schemas.recommendations import RecommendRequest, RecommendResponse
from services import recommendation_service

router = APIRouter(tags=["4. AI 추천"])


@router.post("/events/{event_id}/recommend", response_model=RecommendResponse,
             summary="AI 개선안 추천 (4번 화면 진입·방향 변경)")
def recommend(event_id: str, req: Optional[RecommendRequest] = Body(None)):
    return recommendation_service.recommend(event_id, req)
