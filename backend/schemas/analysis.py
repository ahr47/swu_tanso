"""POST /api/events/{event_id}/analyze 요청·응답 형식 (명세서 v02 4번)"""
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ScenarioType = Literal["original", "improved"]


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: Optional[str] = Field(None, description="생략하면 original")


class Source(BaseModel):
    name: str
    year: Optional[int] = None
    url: Optional[str] = None
    factor_version: str


class ItemResult(BaseModel):
    item_id: str
    item_name: str
    category: str
    variant_label: Optional[str] = None
    quantity: float
    unit: str
    emission: float = Field(..., description="kgCO₂e")
    ratio: Optional[float] = Field(None, description="%")
    cost: Optional[int] = Field(None, description="원. 단가 미입력이면 null")
    confidence: Optional[str] = Field(None, description="계수 신뢰도 (A~D)")
    notes: List[str] = Field(default_factory=list)
    source: Source


class CategoryResult(BaseModel):
    category: str
    emission: float
    ratio: Optional[float] = None


class AnalyzeResponse(BaseModel):
    scenario_id: str
    scenario_type: ScenarioType
    total_emission: float = Field(..., description="kgCO₂e")
    emission_per_person: float = Field(..., description="kgCO₂e/인")
    total_cost: Optional[int] = Field(None, description="단가 입력 품목만 합산. 하나도 없으면 null")
    priced_item_count: int
    budget_usage_rate: Optional[float] = Field(None, description="총 비용 ÷ 예산(%)")
    by_item: List[ItemResult]
    by_category: List[CategoryResult]
    top_items: List[str]
    top_items_share: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)
