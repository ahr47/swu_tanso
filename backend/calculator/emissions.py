"""API v02 COUNT/AREA 품목 계산. DB 조회·환경변수 접근·HTTP 처리는 하지 않는다."""
from decimal import Decimal
from typing import Mapping, Sequence

from .schemas import (
    CalculationError, EmissionFactor, ItemCalculation, ItemDefinition, ItemInput,
    decimal_number, multiply_exact,
)


def calculate_item(
    item_input: ItemInput | Mapping,
    *,
    item: ItemDefinition,
    factors: Sequence[EmissionFactor],
    factor_version: str,
) -> ItemCalculation:
    """조회한 품목·계수와 서버가 선택한 버전으로 단일 품목을 계산한다.

    반환 emission은 Decimal 원값. 응답 반올림은 result.to_api_fields()에서만 한다.
    계수 누락은 CALC_NOT_AVAILABLE 예외이며 정상적인 0으로 반환하지 않는다.
    모든 입력 객체는 읽기만 한다.
    """
    request = ItemInput.from_dict(item_input) if isinstance(item_input, Mapping) else item_input
    if not isinstance(request, ItemInput):
        raise CalculationError("INVALID_INPUT", "item", "ItemInput 또는 dict가 필요합니다")
    if request.item_id != item.item_id or not item.is_active:
        raise CalculationError("UNKNOWN_ITEM", "item_id", "등록된 활성 품목이 아닙니다")
    expected = {"count_only": "COUNT", "count_variant": "COUNT",
                "dimension": "AREA", "fixed_use": "COUNT"}
    if expected.get(item.input_method) != item.calc_type:
        raise CalculationError("CALC_NOT_AVAILABLE", "item_id", "품목 계산 방식이 v02와 맞지 않습니다")

    # 단일 품목의 관련 없는 필드도 방어적으로 검사한다. null은 미입력으로 본다.
    permitted = {
        "count_only": {"quantity", "unit_price"},
        "count_variant": {"quantity", "variant", "unit_price"},
        "dimension": {"quantity", "width_m", "height_m", "unit_price"},
        "fixed_use": set(),
    }[item.input_method]
    if isinstance(item_input, Mapping):
        extra = set(item_input) - permitted - {"item_id"}
        if extra:
            field = sorted(extra)[0]
            raise CalculationError("INVALID_INPUT", field, "이 품목에서 지원하지 않는 필드입니다")
    for name in ("quantity", "variant", "width_m", "height_m", "unit_price"):
        if name not in permitted and getattr(request, name) is not None:
            raise CalculationError("INVALID_INPUT", name, "이 품목에서 지원하지 않는 필드입니다")
    required = [] if item.input_method == "fixed_use" else ["quantity"]
    if item.input_method == "dimension":
        required += ["width_m", "height_m"]
    for name in required:
        if getattr(request, name) is None:
            raise CalculationError("INVALID_INPUT", name, "계산에 필요한 값을 입력해 주세요")

    quantity = Decimal(1)
    if item.input_method != "fixed_use":
        quantity = decimal_number(request.quantity, "quantity", "INVALID_QUANTITY")
        if not 0 < quantity <= 1_000_000 or quantity != quantity.to_integral_value():
            raise CalculationError("INVALID_QUANTITY", "quantity", "수량은 1~1,000,000의 정수여야 합니다")
    dimensions = []
    if item.input_method == "dimension":
        for name in ("width_m", "height_m"):
            value = decimal_number(getattr(request, name), name)
            if not 0 < value <= 50:
                raise CalculationError("INVALID_INPUT", name, "길이는 0 초과 50m 이하여야 합니다")
            dimensions.append(value)
    if request.unit_price is not None:
        if type(request.unit_price) is not int or not 0 <= request.unit_price <= 10_000_000:
            raise CalculationError("INVALID_INPUT", "unit_price", "단가는 0~10,000,000원의 정수여야 합니다")

    variant = None
    variant_label = None
    if item.input_method == "count_variant":
        if request.variant is not None and not isinstance(request.variant, str):
            raise CalculationError("INVALID_INPUT", "variant", "변형 코드는 문자열이어야 합니다")
        codes = [v.variant for v in item.variants]
        if len(codes) != len(set(codes)):
            raise CalculationError("CALC_NOT_AVAILABLE", "variant", "품목 변형 코드가 중복되었습니다")
        variant = request.variant
        if variant is None:
            defaults = [v.variant for v in item.variants if v.is_default]
            if len(defaults) != 1:
                raise CalculationError("CALC_NOT_AVAILABLE", "variant", "기본 변형을 하나로 결정할 수 없습니다")
            variant = defaults[0]
        matches = [v for v in item.variants if v.variant == variant]
        if not matches:
            raise CalculationError("INVALID_INPUT", "variant", "허용되지 않는 변형 코드입니다")
        variant_label = matches[0].label

    if not isinstance(factor_version, str) or not factor_version.strip():
        raise CalculationError("CALC_NOT_AVAILABLE", "factor_version", "서버 배출계수 버전이 필요합니다")
    matching = [f for f in factors if f.item_id == item.item_id
                and f.variant == (variant if variant is not None else "default")
                and f.factor_version == factor_version]
    if len(matching) != 1 or matching[0].value is None:
        raise CalculationError("CALC_NOT_AVAILABLE", "factor", "해당 버전의 유일한 배출계수가 필요합니다")
    factor = matching[0]
    if factor.calc_type != item.calc_type:
        raise CalculationError("CALC_NOT_AVAILABLE", "factor", "품목과 계수의 계산 유형이 다릅니다")
    value = decimal_number(factor.value, "factor", "CALC_NOT_AVAILABLE")
    if value < 0:
        raise CalculationError("CALC_NOT_AVAILABLE", "factor", "배출계수는 0 이상이어야 합니다")
    if item.calc_type == "AREA":
        emission = multiply_exact(quantity, *dimensions, value)
    else:
        emission = multiply_exact(quantity, value)
    cost = None if request.unit_price is None else int(quantity) * request.unit_price
    return ItemCalculation(
        item_id=item.item_id, item_name=item.item_name, category=item.category,
        variant=variant, variant_label=variant_label, quantity=quantity, unit=item.input_unit,
        emission=emission, cost=cost, confidence=factor.confidence,
        notes=tuple(dict.fromkeys((*item.notes, *factor.notes))),
        source_name=factor.source_name, source_year=factor.source_year,
        source_url=factor.source_url, factor_version=factor.factor_version,
        scope_group=factor.scope_group,
    )
