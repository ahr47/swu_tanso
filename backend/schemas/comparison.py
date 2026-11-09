"""POST /api/events/{event_id}/compare 요청·응답 형식 (명세서 v02 6번)"""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_scenario_id: Optional[str] = Field(None, description="생략하면 original")
    applied_rec_ids: List[str] = Field(..., min_length=1, description="적용할 추천 ID. 같은 품목은 하나만",
                                       examples=[["REC_1", "REC_2"]])


class ScenarioTotals(BaseModel):
    total_emission: float
    emission_per_person: float
    total_cost: Optional[int] = None


class ItemComparison(BaseModel):
    item_id: str
    item_name: str
    before_emission: float
    after_emission: float
    emission_diff: float
    changed: bool
    target_field: Optional[str] = None
    before_value: Optional[float] = Field(None, description="수량만")
    after_value: Optional[float] = Field(None, description="수량만")
    before_item_id: Optional[str] = None
    after_item_id: Optional[str] = None
    after_item_name: Optional[str] = None


class CompareResponse(BaseModel):
    original_scenario_id: str
    improved_scenario_id: str
    before: ScenarioTotals
    after: ScenarioTotals
    reduction: float = Field(..., description="before − after (kgCO₂e)")
    reduction_rate: Optional[float] = Field(None, description="%")
    cost_change: Optional[int] = Field(None, description="원. 음수면 절감")
    item_comparison: List[ItemComparison]
