"""DB와 API 라이브러리에 의존하지 않는 계산 경계 객체 (Python 3.10+)."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any, Mapping
from fractions import Fraction


class CalculationError(ValueError):
    """HTTP 응답이 아닌 계산 오류. API 계층에서 code/field/message를 매핑한다."""

    def __init__(self, code: str, field: str, message: str):
        self.code, self.field, self.message = code, field, message
        super().__init__(message)

    def as_dict(self) -> dict:
        return {"error": self.code, "field": self.field, "message": self.message}


def decimal_number(value: Any, field: str, code: str = "INVALID_INPUT") -> Decimal:
    # Decimal(str(float))는 호출자가 보낸 십진 표현을 사용한다.
    # DB NUMERIC은 Decimal로 넘기는 편이 가장 정확하다.
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise CalculationError(code, field, "유한한 숫자를 입력해 주세요")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise CalculationError(code, field, "유한한 숫자를 입력해 주세요") from exc
    if not number.is_finite():
        raise CalculationError(code, field, "유한한 숫자를 입력해 주세요")
    return number


def multiply_exact(*values: Decimal) -> Decimal:
    """곱의 유효 자릿수만큼 문맥을 확보하여 중간 반올림을 피한다."""
    with localcontext() as context:
        context.prec = max(28, sum(len(v.as_tuple().digits) for v in values) + 2)
        result = Decimal(1)
        for value in values:
            result *= value
        return result


def response_emission(value: Decimal) -> float:
    """API 경계에서만 소수 둘째 자리 반올림 (동률은 HALF_UP)."""
    with localcontext() as context:
        context.prec = max(28, value.adjusted() + 5, len(value.as_tuple().digits) + 3)
        return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def sum_exact(values) -> Decimal:
    values = tuple(values)
    if not values:
        return Decimal(0)
    low = min(v.as_tuple().exponent for v in values)
    high = max(v.adjusted() for v in values)
    with localcontext() as context:
        context.prec = max(28, high - low + len(str(len(values))) + 5)
        return sum(values, Decimal(0))


def difference(before: Decimal, after: Decimal) -> Decimal:
    return sum_exact((before, after.copy_negate()))


def rounded_fraction(numerator: Decimal, denominator: Decimal, places: int, scale=1):
    """유리수로 나눈 뒤 최종 자리에서만 HALF_UP. 순환소수 중간 반올림 없음."""
    if denominator == 0:
        return None
    value = Fraction(numerator) / Fraction(denominator) * scale * 10**places
    sign = -1 if value < 0 else 1
    q, r = divmod(abs(value.numerator), value.denominator)
    if 2 * r >= value.denominator:
        q += 1
    return sign * q / 10**places


def percent(numerator: Decimal, denominator: Decimal):
    return rounded_fraction(numerator, denominator, 1, scale=100)


@dataclass(frozen=True)
class Variant:
    variant: str
    label: str
    is_default: bool = False


@dataclass(frozen=True)
class ItemDefinition:
    item_id: str
    item_name: str
    category: str
    calc_type: str
    input_method: str
    input_unit: str
    is_active: bool = True
    variants: tuple[Variant, ...] = ()
    notes: tuple[str, ...] = ()
    description: str | None = None


@dataclass(frozen=True)
class EmissionFactor:
    item_id: str
    variant: str  # 변형 없는 품목의 DB 계수 키는 'default'
    value: Decimal | int | float | None
    unit: str
    calc_type: str
    factor_version: str
    source_name: str
    source_year: int | None = None
    source_url: str | None = None
    confidence: str | None = None
    notes: tuple[str, ...] = ()
    scope_group: str | None = None


@dataclass(frozen=True)
class ItemInput:
    item_id: str
    quantity: Decimal | int | float | None = None
    variant: str | None = None
    width_m: Decimal | int | float | None = None
    height_m: Decimal | int | float | None = None
    unit_price: int | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ItemInput":
        allowed = set(cls.__dataclass_fields__)
        extra = set(data) - allowed
        if extra:
            field = sorted(extra)[0]
            raise CalculationError("INVALID_INPUT", field, "v02에서 지원하지 않는 입력 필드입니다")
        if not isinstance(data.get("item_id"), str) or not data["item_id"]:
            raise CalculationError("INVALID_INPUT", "item_id", "품목 ID를 입력해 주세요")
        return cls(**data)


@dataclass(frozen=True)
class ItemCalculation:
    item_id: str
    item_name: str
    category: str
    variant: str | None
    variant_label: str | None
    quantity: Decimal
    unit: str
    emission: Decimal  # 합계·비율·비교는 이 원값을 사용
    cost: int | None
    confidence: str | None
    notes: tuple[str, ...]
    source_name: str
    source_year: int | None
    source_url: str | None
    factor_version: str
    scope_group: str | None

    def to_api_fields(self) -> dict:
        """v02 by_item 필드 중 단일 품목으로 계산 가능한 필드만 반환.

        ratio는 전체 분석 단계에서 계산한다. 이 메서드 출력은 재계산용이 아니다.
        """
        return {
            "item_id": self.item_id, "item_name": self.item_name,
            "category": self.category, "variant_label": self.variant_label,
            "quantity": int(self.quantity), "unit": self.unit,
            "emission": response_emission(self.emission), "cost": self.cost,
            "confidence": self.confidence, "notes": list(self.notes),
            "source": {"name": self.source_name, "year": self.source_year,
                       "url": self.source_url, "factor_version": self.factor_version},
        }


@dataclass(frozen=True)
class ScenarioAnalysis:
    scenario_id: str
    scenario_type: str
    participants: int
    budget: int | None
    inputs: tuple[ItemInput, ...]
    results: tuple[ItemCalculation, ...]
    total_emission: Decimal
    total_cost: int | None
    priced_item_count: int
    warnings: tuple[str, ...]

    def summary(self) -> dict:
        return {"total_emission": response_emission(self.total_emission),
                "emission_per_person": rounded_fraction(self.total_emission, Decimal(self.participants), 2),
                "total_cost": self.total_cost}

    def to_api_response(self) -> dict:
        ordered = sorted(self.results, key=lambda r: (-Fraction(r.emission), r.item_id))
        categories = {}
        for result in self.results:
            categories.setdefault(result.category, []).append(result.emission)
        category_totals = [(name, sum_exact(values)) for name, values in categories.items()]
        category_totals.sort(key=lambda row: (-Fraction(row[1]), row[0]))
        by_item = [{**r.to_api_fields(), "ratio": percent(r.emission, self.total_emission)} for r in ordered]
        return {
            "scenario_id": self.scenario_id, "scenario_type": self.scenario_type, **self.summary(),
            "priced_item_count": self.priced_item_count,
            "budget_usage_rate": (percent(Decimal(self.total_cost), Decimal(self.budget))
                                  if self.total_cost is not None and self.budget else None),
            "by_item": by_item,
            "by_category": [{"category": name, "emission": response_emission(value),
                             "ratio": percent(value, self.total_emission)} for name, value in category_totals],
            "top_items": [r.item_id for r in ordered[:3]],
            "top_items_share": percent(sum_exact(r.emission for r in ordered[:3]), self.total_emission),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class RecommendationEffect:
    # 계산기 내부 반환 형식. can_calculate/error는 API 응답에 새 필드를 추가하는 것이 아니다.
    can_calculate: bool
    before: ItemCalculation | None = None
    after: ItemCalculation | None = None
    emission_reduction: Decimal | None = None
    cost_change: int | None = None
    error: CalculationError | None = None

    def to_api_fields(self) -> dict:
        return {"emission_reduction": (response_emission(self.emission_reduction)
                                      if self.emission_reduction is not None else None),
                "cost_change": self.cost_change}

    @property
    def reduction_rate(self):
        return (percent(self.emission_reduction, self.before.emission)
                if self.before is not None and self.emission_reduction is not None else None)


@dataclass(frozen=True)
class ScenarioComparison:
    before: ScenarioAnalysis
    after: ScenarioAnalysis
    reduction: Decimal
    cost_change: int | None
    item_comparison: tuple[dict, ...]

    def to_api_response(self) -> dict:
        rows = []
        for row in self.item_comparison:
            row = dict(row)
            for field in ("before_emission", "after_emission", "emission_diff"):
                row[field] = response_emission(row[field])
            rows.append(row)
        return {"original_scenario_id": self.before.scenario_id,
                "improved_scenario_id": self.after.scenario_id,
                "before": self.before.summary(), "after": self.after.summary(),
                "reduction": response_emission(self.reduction),
                "reduction_rate": percent(self.reduction, self.before.total_emission),
                "cost_change": self.cost_change, "item_comparison": rows}
