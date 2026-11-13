"""품목 마스터·배출계수 조회 (백엔드1). 반환 형식은 calculator/catalogue_v02.json 과 같음"""
from typing import Any, Dict, List, Tuple

from db.connection import connection


def fetch_catalogue() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(item_records, factor_records) — calculator.catalogue.catalogue_from_records 입력 형식"""
    with connection() as conn:
        items = conn.execute(
            """
            SELECT item_id, item_name, category, input_unit, calc_type, input_method, is_active, notes, description
            FROM items ORDER BY sort_order, item_id
            """
        ).fetchall()
        variants = conn.execute(
            "SELECT item_id, variant, label, is_default FROM item_variants ORDER BY item_id, sort_order"
        ).fetchall()
        factors = conn.execute(
            """
            SELECT item_id, variant, factor_version, value, unit, calc_type, source_name, source_url, source_year,
                   confidence, notes, scope_group
            FROM emission_factors ORDER BY item_id, variant, factor_version
            """
        ).fetchall()

    by_item: Dict[str, List[Dict[str, Any]]] = {}
    for v in variants:
        by_item.setdefault(v["item_id"], []).append(
            {"variant": v["variant"], "label": v["label"], "is_default": v["is_default"]})
    item_records = [{**row, "variants": by_item.get(row["item_id"])} for row in items]
    return item_records, [dict(row) for row in factors]
