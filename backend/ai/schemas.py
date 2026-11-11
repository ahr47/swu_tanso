"""API 필드명세서 v02 §5: 백엔드4 내부 입력/출력 계약.

- 백엔드2가 입력 payload를 구성하고 목표의 기본값을 채운다.
- AI는 추천 변경안과 문구만 출력한다. rec_id/배출량/비용/적용 가능 여부 등은 출력 금지.
- 실제 품목·대체 품목의 DB 유효성/계산/비용 검증은 백엔드2·3의 책임이다.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class StrictData(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EventContext(StrictData):
    event_name: str
    event_type: str
    participants: Annotated[StrictInt, Field(gt=0)]
    budget: Annotated[StrictInt, Field(ge=0)] | None
    description: str | None


class ScenarioItem(StrictData):
    item_id: str
    item_name: str
    category: str
    input_method: Literal["count_only", "count_variant", "dimension", "fixed_use"]
    input_unit: str
    quantity: Annotated[StrictInt, Field(gt=0)]
    variant: str | None
    unit_price: Annotated[StrictInt, Field(ge=0)] | None
    emission: float
    ratio: float | None
    cost: Annotated[StrictInt, Field(ge=0)] | None


class AnalysisContext(StrictData):
    total_emission: float
    total_cost: Annotated[StrictInt, Field(ge=0)] | None
    top_items: list[str]


class AlternativeItem(StrictData):
    item_id: str
    item_name: str
    category: str
    input_unit: str
    variants: list[str]


class Goal(StrictData):
    budget_increase_allowed: bool
    target_reduction_percent: float | None
    preserve_event_quality: bool
    custom_condition: Annotated[str, Field(max_length=300)] | None


class Constraints(StrictData):
    allowed_action_types: list[Literal["reduce_quantity", "replace_item"]]
    max_recommendations: Annotated[StrictInt, Field(ge=1, le=5)]


class AIInput(StrictData):
    event: EventContext
    items: list[ScenarioItem]
    analysis: AnalysisContext
    alternatives: list[AlternativeItem]
    goal: Goal
    constraints: Constraints


PositiveQuantity = Annotated[StrictInt, Field(gt=0)]


class Recommendation(StrictData):
    item_id: str
    action_type: Literal["reduce_quantity", "replace_item"]
    target_field: Literal["quantity", "item_id"]
    recommended_value: PositiveQuantity | None
    alternative_item_id: str | None
    alternative_variant: str | None
    title: str
    difficulty: Literal["쉬움", "보통", "어려움"]
    reason: str

    @model_validator(mode="after")
    def check_action_fields(self):
        if not self.item_id.strip() or not self.title.strip() or not self.reason.strip():
            raise ValueError("item_id, title, reason은 비어 있을 수 없습니다")
        if self.action_type == "reduce_quantity":
            if self.target_field != "quantity" or self.recommended_value is None:
                raise ValueError("수량 감축은 quantity와 양의 정수 recommended_value가 필요합니다")
            if self.alternative_item_id is not None or self.alternative_variant is not None:
                raise ValueError("수량 감축에 대체 품목 필드를 사용할 수 없습니다")
        else:
            if self.target_field != "item_id" or self.recommended_value is not None:
                raise ValueError("품목 교체는 item_id를 변경하며 recommended_value는 null입니다")
            if not self.alternative_item_id or self.alternative_item_id == self.item_id:
                raise ValueError("품목 교체에는 원래 품목과 다른 alternative_item_id가 필요합니다")
        return self


class AIOutput(StrictData):
    recommendations: list[Recommendation]
