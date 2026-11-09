"""POST /api/events, PUT /api/events/{event_id}/items 요청·응답 형식 (명세서 v02 2·3번)"""
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# 2. POST /api/events
# ---------------------------------------------------------------------------
class EventCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_name: str = Field(..., min_length=1, max_length=50, examples=["경영학과 학술제"])
    event_type: str = Field(..., min_length=1, description="행사 유형 (목록은 Figma와 통일 예정)",
                            examples=["학과·학생회 행사"])
    participants: int = Field(..., ge=1, description="참여 인원(명). 1인당 배출량 계산에 사용", examples=[100])
    budget: Optional[int] = Field(None, ge=0, description="예산(원). 화면의 '총 예산'. total_budget은 쓰지 않음",
                                  examples=[1000000])
    event_date: Optional[date] = Field(None, description="YYYY-MM-DD")
    location: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, description="행사 자유 설명란")

    @field_validator("event_name", "event_type")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("빈 값은 입력할 수 없습니다")
        return value


class EventCreateResponse(BaseModel):
    event_id: str = Field(..., examples=["EVT_0001"])
    scenario_id: str = Field(..., description="자동 생성된 original 시나리오 ID", examples=["SCN_0001"])
    created: bool


# ---------------------------------------------------------------------------
# 3. PUT /api/events/{event_id}/items
# ---------------------------------------------------------------------------
class ItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(..., examples=["leaflet"])
    quantity: Optional[float] = Field(None, gt=0, description="수량(input_unit 단위). fixed_use 품목은 생략",
                                      examples=[300])
    variant: Optional[str] = Field(None, description="count_variant 품목만. 비우면 기본 변형", examples=["a4"])
    width_m: Optional[float] = Field(None, gt=0, description="dimension 품목(현수막)만. 가로(m)")
    height_m: Optional[float] = Field(None, gt=0, description="dimension 품목(현수막)만. 세로(m)")
    unit_price: Optional[int] = Field(None, ge=0, description="개당 단가(원). fixed_use 제외. 비우면 비용 미입력")


class ItemsSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: List[ItemInput]


class ItemsSaveResponse(BaseModel):
    event_id: str
    scenario_id: str
    saved: bool
    item_count: int
