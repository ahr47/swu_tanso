"""DB 조회 행을 계산 객체로 변환. DB에 접속하거나 데이터를 저장하지 않는다."""
from decimal import Decimal
from .schemas import EmissionFactor, ItemDefinition, Variant


def catalogue_from_records(item_records, factor_records):
    """입력 형식은 README와 catalogue_v02.json 참고. production 계수의 원천은 DB."""
    items = {}
    for row in item_records:
        if row["item_id"] in items:
            raise ValueError("품목 마스터 ID 중복")
        items[row["item_id"]] = ItemDefinition(
            item_id=row["item_id"], item_name=row["item_name"], category=row["category"],
            calc_type=row["calc_type"], input_method=row["input_method"], input_unit=row["input_unit"],
            is_active=row.get("is_active", True),
            variants=tuple(Variant(v["variant"], v["label"], v.get("is_default", False))
                           for v in row.get("variants") or ()),
            notes=tuple(row.get("notes") or ()), description=row.get("description"),
        )
    factors = tuple(EmissionFactor(
        item_id=row["item_id"], variant=row["variant"],
        value=None if row.get("value") is None else Decimal(str(row["value"])),
        unit=row["unit"], calc_type=row["calc_type"], factor_version=row["factor_version"],
        source_name=row["source_name"], source_year=row.get("source_year"),
        source_url=row.get("source_url"), confidence=row.get("confidence"),
        notes=tuple(row.get("notes") or ()), scope_group=row.get("scope_group"),
    ) for row in factor_records)
    return items, factors
