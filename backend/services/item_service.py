"""품목 목록 조회 처리 흐름 (백엔드2) — 명세서 v02 1번"""
from typing import Optional

from schemas.items import Item, ItemListResponse, Variant
from services import adapters


def list_items(category: Optional[str] = None) -> ItemListResponse:
    """is_active=true 품목만. category 는 한글 분야명 또는 영문 코드(print, food 등) 모두 가능"""
    items = []
    for row in adapters.list_active_items(category):
        variants = None
        if row.get("variants"):
            variants = [Variant(variant=v["variant"], label=v["label"], is_default=v["is_default"])
                        for v in row["variants"]]
        items.append(Item(
            item_id=row["item_id"],
            item_name=row["item_name"],
            category=row["category"],
            calc_type=row["calc_type"],
            input_method=row["input_method"],
            input_unit=row["input_unit"],
            variants=variants,
            notes=row["notes"],
            description=row["description"],
        ))
    return ItemListResponse(items=items)
