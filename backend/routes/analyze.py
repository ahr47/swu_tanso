"""POST /api/events/{event_id}/analyze (백엔드2)"""
from typing import Optional

from fastapi import APIRouter, Body

from schemas.analysis import AnalyzeRequest, AnalyzeResponse
from services import analysis_service

router = APIRouter(tags=["3. 탄소 분석"])


@router.post("/events/{event_id}/analyze", response_model=AnalyzeResponse, summary="탄소배출량 계산 (3번 화면)")
def analyze(event_id: str, req: Optional[AnalyzeRequest] = Body(None)):
    return analysis_service.analyze(event_id, req)
