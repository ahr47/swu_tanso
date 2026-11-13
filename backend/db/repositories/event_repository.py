"""행사·시나리오·추천 저장 (백엔드1). 반환 dict 는 services/adapters.py 메모리 저장소와 같은 형태"""
from typing import Any, Dict, List, Optional, Tuple


from db.connection import connection, in_transaction

_ROW_FIELDS = ("item_id", "quantity", "variant", "width_m", "height_m", "unit_price")
_REC_FIELDS = (
    "item_id", "item_name", "category", "action_type", "target_field", "current_value", "recommended_value",
    "alternative_item_id", "alternative_item_name", "alternative_variant", "title", "difficulty", "reason",
    "emission_reduction", "cost_change", "applicable", "not_applicable_reason",
)


# ---------------------------------------------------------------------------
# 행사
# ---------------------------------------------------------------------------
def create_event(data: Dict[str, Any]) -> Tuple[str, str]:
    """행사 + original 시나리오를 함께 만들고 (event_id, scenario_id) 반환"""
    with connection() as conn:
        event_id = conn.execute(
            """
            INSERT INTO events (event_name, event_type, participants, budget, event_date, location, description)
            VALUES (%(event_name)s, %(event_type)s, %(participants)s, %(budget)s, %(event_date)s,
                    %(location)s, %(description)s)
            RETURNING event_id
            """,
            {key: data.get(key) for key in ("event_name", "event_type", "participants", "budget", "event_date",
                                             "location", "description")},
        ).fetchone()["event_id"]
        scenario_id = conn.execute(
            "INSERT INTO scenarios (event_id, scenario_type) VALUES (%s, 'original') RETURNING scenario_id",
            (event_id,),
        ).fetchone()["scenario_id"]
    return event_id, scenario_id


def get_event(event_id: str) -> Optional[Dict[str, Any]]:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT event_id, event_name, event_type, participants, budget, event_date, location, description
            FROM events WHERE event_id = %s
            """,
            (event_id,),
        ).fetchone()
    if row is None:
        return None
    row = dict(row)
    row["event_date"] = row["event_date"].isoformat() if row["event_date"] else None
    return row


# ---------------------------------------------------------------------------
# 시나리오
# ---------------------------------------------------------------------------
def _load_scenario(conn, where: str, params: tuple) -> Optional[Dict[str, Any]]:
    # 트랜잭션 안에서는 행을 잠가서, 확인한 version 이 저장할 때까지 바뀌지 않게 함
    lock = " FOR UPDATE" if in_transaction() else ""
    scenario = conn.execute(
        f"SELECT scenario_id, event_id, scenario_type, version FROM scenarios WHERE {where}{lock}", params
    ).fetchone()
    if scenario is None:
        return None
    items = conn.execute(
        """
        SELECT item_id, quantity, variant, width_m, height_m, unit_price
        FROM scenario_items WHERE scenario_id = %s ORDER BY position
        """,
        (scenario["scenario_id"],),
    ).fetchall()
    return {**scenario, "items": [dict(row) for row in items]}


def get_scenario(scenario_id: str) -> Optional[Dict[str, Any]]:
    with connection() as conn:
        return _load_scenario(conn, "scenario_id = %s", (scenario_id,))


def find_scenario(event_id: str, scenario_type: str) -> Optional[Dict[str, Any]]:
    with connection() as conn:
        return _load_scenario(conn, "event_id = %s AND scenario_type = %s", (event_id, scenario_type))


def _insert_items(conn, scenario_id: str, items: List[Dict[str, Any]]) -> None:
    for position, row in enumerate(items, start=1):
        conn.execute(
            """
            INSERT INTO scenario_items (scenario_id, position, item_id, quantity, variant, width_m, height_m,
                                        unit_price)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (scenario_id, position, *(row.get(field) for field in _ROW_FIELDS)),
        )


def _delete_improved_and_recs(conn, event_id: str) -> None:
    conn.execute("DELETE FROM recommendations WHERE event_id = %s", (event_id,))
    conn.execute("DELETE FROM scenarios WHERE event_id = %s AND scenario_type = 'improved'", (event_id,))


def replace_scenario_items(scenario_id: str, items: List[Dict[str, Any]]) -> int:
    """original 품목 통째로 교체 + 기존 추천·improved 삭제. 새 version 반환"""
    with connection() as conn:
        scenario = conn.execute(
            "UPDATE scenarios SET version = version + 1, updated_at = now() WHERE scenario_id = %s"
            " RETURNING event_id, version",
            (scenario_id,),
        ).fetchone()
        conn.execute("DELETE FROM scenario_items WHERE scenario_id = %s", (scenario_id,))
        _insert_items(conn, scenario_id, items)
        _delete_improved_and_recs(conn, scenario["event_id"])
        return scenario["version"]


def save_improved_scenario(event_id: str, items: List[Dict[str, Any]]) -> str:
    """improved 시나리오를 덮어쓰고 scenario_id 반환 (행사당 1개)"""
    with connection() as conn:
        scenario_id = conn.execute(
            """
            INSERT INTO scenarios (event_id, scenario_type) VALUES (%s, 'improved')
            ON CONFLICT (event_id, scenario_type) DO UPDATE SET updated_at = now()
            RETURNING scenario_id
            """,
            (event_id,),
        ).fetchone()["scenario_id"]
        conn.execute("DELETE FROM scenario_items WHERE scenario_id = %s", (scenario_id,))
        _insert_items(conn, scenario_id, items)
        return scenario_id


# ---------------------------------------------------------------------------
# 추천
# ---------------------------------------------------------------------------
def replace_recommendations(event_id: str, scenario_id: str, recs: List[Dict[str, Any]],
                            base_version: int) -> List[Dict[str, Any]]:
    """이전 추천·improved 삭제 후 새 추천 저장. rec_id 를 붙여서 반환"""
    with connection() as conn:
        _delete_improved_and_recs(conn, event_id)
        saved = []
        for position, rec in enumerate(recs, start=1):
            row = conn.execute(
                f"""
                INSERT INTO recommendations (event_id, scenario_id, base_version, position, {", ".join(_REC_FIELDS)})
                VALUES (%s, %s, %s, %s, {", ".join(["%s"] * len(_REC_FIELDS))})
                RETURNING rec_id
                """,
                (event_id, scenario_id, base_version, position, *(rec.get(field) for field in _REC_FIELDS)),
            ).fetchone()
            saved.append({**{field: rec.get(field) for field in _REC_FIELDS}, "rec_id": row["rec_id"],
                          "event_id": event_id, "scenario_id": scenario_id, "base_version": base_version})
        return saved


def get_recommendations(rec_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not rec_ids:
        return {}
    with connection() as conn:
        rows = conn.execute(
            f"""
            SELECT rec_id, event_id, scenario_id, base_version, {", ".join(_REC_FIELDS)}
            FROM recommendations WHERE rec_id = ANY(%s)
            """,
            (list(rec_ids),),
        ).fetchall()
    return {row["rec_id"]: dict(row) for row in rows}


# ---------------------------------------------------------------------------
# 테스트용
# ---------------------------------------------------------------------------
def reset_all() -> None:
    """행사·시나리오·추천 전부 삭제하고 ID 번호를 1부터. 품목·계수는 그대로"""
    with connection() as conn:
        conn.execute("TRUNCATE recommendations, scenario_items, scenarios, events")
        for seq in ("event_id_seq", "scenario_id_seq", "rec_id_seq"):
            conn.execute(f"ALTER SEQUENCE {seq} RESTART WITH 1")
