"""calculator/catalogue_v02.json (백엔드3 제공) -> db/sql/seed.sql 생성

실행 (backend 폴더에서):  python -m db.seed_from_catalogue
계수 데이터가 바뀌면 이 스크립트를 다시 돌려 seed.sql 을 갱신한 뒤 함께 커밋하세요.
"""
import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOGUE = BACKEND / "calculator" / "catalogue_v02.json"
SEED = BACKEND / "db" / "sql" / "seed.sql"


def q(value) -> str:
    """SQL 리터럴 (문자열은 작은따옴표 이스케이프)"""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def jsonb(values) -> str:
    return q(json.dumps(list(values or []), ensure_ascii=False)) + "::jsonb"


def build() -> str:
    data = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    lines = [
        "-- 자동 생성 파일: python -m db.seed_from_catalogue  (직접 수정하지 마세요)",
        f"-- 원본: calculator/catalogue_v02.json  factor_version={data['factor_version']}",
        f"-- {data.get('data_status', '')}",
        "",
        "INSERT INTO items (item_id, item_name, category, input_unit, calc_type, input_method, is_active, notes,"
        " description, sort_order) VALUES",
    ]
    rows = [
        f"({q(i['item_id'])}, {q(i['item_name'])}, {q(i['category'])}, {q(i['input_unit'])}, {q(i['calc_type'])},"
        f" {q(i['input_method'])}, {q(i.get('is_active', True))}, {jsonb(i.get('notes'))},"
        f" {q(i.get('description'))}, {n})"
        for n, i in enumerate(data["items"], start=1)
    ]
    lines.append(",\n".join(rows) + ";\n")

    variants = [
        f"({q(i['item_id'])}, {q(v['variant'])}, {q(v['label'])}, {q(v.get('is_default', False))}, {n})"
        for i in data["items"] for n, v in enumerate(i.get("variants") or [], start=1)
    ]
    lines.append("INSERT INTO item_variants (item_id, variant, label, is_default, sort_order) VALUES")
    lines.append(",\n".join(variants) + ";\n")

    factors = [
        f"({q(f['item_id'])}, {q(f['variant'])}, {q(f['factor_version'])},"
        f" {'NULL' if f.get('value') is None else str(f['value'])}, {q(f['unit'])}, {q(f['calc_type'])},"
        f" {q(f['source_name'])}, {q(f.get('source_url'))}, {q(f.get('source_year'))}, {q(f.get('confidence'))},"
        f" {jsonb(f.get('notes'))}, {q(f.get('scope_group'))})"
        for f in data["factors"]
    ]
    lines.append("INSERT INTO emission_factors (item_id, variant, factor_version, value, unit, calc_type, source_name,"
                 " source_url, source_year, confidence, notes, scope_group) VALUES")
    lines.append(",\n".join(factors) + ";")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    SEED.write_text(build(), encoding="utf-8")
    print(f"{SEED.relative_to(BACKEND)} 생성 완료")
