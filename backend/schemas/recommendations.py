"""POST /api/events/{event_id}/recommend 요청·응답 형식 (명세서 v02 5번)"""
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

CUSTOM_CONDITION_MAX_LENGTH = 300

ActionType = Literal["reduce_quantity", "replace_item"]
TargetField = Literal["quantity", "item_id"]
Difficulty = Literal["쉬움", "보통", "어려움"]
NotApplicableReason = Literal["FIXED_QUANTITY", "BUDGET_INCREASE"]
EmptyReason = Literal["NO_CANDIDATE", "ALL_FILTERED"]


class Goal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_increase_allowed: bool = Field(False, description="'예산은 그대로' 카드면 false")
    target_reduction_percent: Optional[float] = Field(None, ge=0, le=100, description="'탄소 20% 이상' 카드면 20")
    preserve_event_quality: bool = True
    custom_condition: Optional[str] = Field(None, description="직접 입력. 1~300자")

    @field_validator("custom_condition")
    @classmethod
    def _check_custom_condition(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None  # 빈 문자열은 null
        if len(value) > CUSTOM_CONDITION_MAX_LENGTH:
            raise ValueError(f"직접 입력은 {CUSTOM_CONDITION_MAX_LENGTH}자 이하로 입력해 주세요")
        return value


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: Optional[str] = Field(None, description="생략하면 original")
    goal: Optional[Goal] = Field(None, description="생략하면 기본값으로 추천")


class Recommendation(BaseModel):
    rec_id: str
    item_id: str
    item_name: str
    title: str
    category: str
    difficulty: Difficulty
    action_type: ActionType
    target_field: TargetField
    current_value: Optional[float] = None
    recommended_value: Optional[float] = None
    alternative_item_id: Optional[str] = None
    alternative_item_name: Optional[str] = None
    alternative_variant: Optional[str] = None
    reason: str
    emission_reduction: float = Field(..., description="이 추천만 적용했을 때 감축량(kgCO₂e)")
    cost_change: Optional[int] = Field(None, description="원. 음수면 절감")
    applicable: bool
    not_applicable_reason: Optional[NotApplicableReason] = None


class RecommendResponse(BaseModel):
    scenario_id: str
    empty_reason: Optional[EmptyReason] = None
    recommendations: List[Recommendation]
