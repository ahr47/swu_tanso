"""GET /api/items 응답 형식 (명세서 v02 1번)"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

CalcType = Literal["COUNT", "AREA"]
InputMethod = Literal["count_only", "count_variant", "dimension", "fixed_use"]


class Variant(BaseModel):
    variant: str = Field(..., description="변형 코드", examples=["500ml"])
    label: str = Field(..., description="화면 표시명", examples=["500mL"])
    is_default: bool


class Item(BaseModel):
    item_id: str = Field(..., examples=["a4_paper"])
    item_name: str = Field(..., examples=["A4 용지"])
    category: str = Field(..., description="인쇄물·홍보물 / 음료·일회용품 / 음식·간식 / 굿즈 / 배송")
    calc_type: CalcType
    input_method: InputMethod
    input_unit: str = Field(..., description="수량 칸 옆에 표시할 단위", examples=["장"])
    variants: Optional[List[Variant]] = Field(None, description="count_variant 품목만")
    notes: List[str] = Field(default_factory=list, description="표시 문구 (잠정값, 참고값 등)")
    description: Optional[str] = Field(None, description="카드 보조 문구")


class ItemListResponse(BaseModel):
    items: List[Item]
