"""GET /api/items (백엔드2)"""
from typing import Optional

from fastapi import APIRouter, Query

from schemas.items import ItemListResponse
from services import item_service

router = APIRouter(tags=["1. 품목"])


@router.get("/items", response_model=ItemListResponse, summary="품목 목록 조회")
def list_items(category: Optional[str] = Query(None, description="분야. 생략하면 전체 (예: 인쇄물·홍보물 또는 print)")):
    return item_service.list_items(category)
