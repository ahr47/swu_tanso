"""
⚠️ 임시 어댑터 (백엔드2 작성) — 다른 파트 코드가 올라오면 이 파일만 바꿉니다.

services/*.py 는 DB·계산·AI 를 직접 부르지 않고 이 파일의 함수만 부릅니다.
그래서 다른 파트 코드가 준비되면 이 파일 안의 함수 내용만 교체하면 됩니다.

    [DB]   백엔드1 db/repositories      → "DB (백엔드1 교체 예정)" 구역
    [계산] 백엔드3 calculator            → "계산 (백엔드3 교체 예정)" 구역
    [AI]   백엔드4 ai/recommender       → "AI (백엔드4 교체 예정)" 구역

지금은
- DB 대신 메모리 저장소를 씁니다 (서버를 끄면 데이터가 사라집니다).
- 계수는 품목·입력값 명세서 6장 + 필드명세서 v02 품목표 값을 씁니다.
- AI 대신 규칙 기반 임시 추천을 씁니다. AI_API_KEY 가 입력돼도 백엔드4 코드 연결 전까지는 동일합니다.
"""
import copy
import threading
from typing import Any, Dict, List, Optional, Tuple

from core.config import get_settings

# ===========================================================================
# 품목 마스터·배출계수 (백엔드1 seed.sql + 백엔드3 계수 테이블로 교체 예정)
# ===========================================================================
CAT_PRINT = "인쇄물·홍보물"
CAT_DRINK = "음료·일회용품"
CAT_FOOD = "음식·간식"
CAT_GOODS = "굿즈"
CAT_DELIVERY = "배송"

# 입력값 명세서 2번의 영문 분야 코드도 category 조회에 쓸 수 있게 함
CATEGORY_CODES: Dict[str, str] = {
    "print": CAT_PRINT,
    "drink_disposable": CAT_DRINK,
    "food": CAT_FOOD,
    "goods": CAT_GOODS,
    "delivery_pack": CAT_DELIVERY,
}

_ECOSQUARE = ("ECOSQUARE (국내 통합 DB)",
              "https://ecosq.or.kr/websquare.do#w2xPath=/ui/cer/ic/oh/ICOH110M01.xml&valVl=tabs3&menuSn=20018500")
_KEITI = ("한국환경산업기술원 탄소발자국 인증", "https://www.data.go.kr/data/15089157/fileData.do?recommendDataYn=Y")
_ADEME = ("ADEME AGRIBALYSE 3.2", None)
_BIG_CLIMATE = ("The Big Climate Database v1.2", None)


def _v(code: str, label: str, factor: float, default: bool = False, notes: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"variant": code, "label": label, "factor": factor, "is_default": default, "notes": notes or []}


def _item(item_id: str, name: str, category: str, unit: str, *, input_method: str = "count_only",
          calc_type: str = "COUNT", factor: Optional[float] = None, variants: Optional[List[Dict[str, Any]]] = None,
          source: Tuple[str, Optional[str]] = ("팀 조사값", None), year: Optional[int] = None,
          confidence: Optional[str] = None, notes: Optional[List[str]] = None, scope: str = "제품 전과정",
          description: Optional[str] = None) -> Dict[str, Any]:
    return {
        "item_id": item_id, "item_name": name, "category": category, "input_unit": unit,
        "input_method": input_method, "calc_type": calc_type, "factor": factor, "variants": variants,
        "source_name": source[0], "source_url": source[1], "source_year": year,
        "confidence": confidence, "notes": notes or [], "scope": scope,
        "description": description, "is_active": True,
    }


# 계수 단위: COUNT 는 kgCO₂e/input_unit, AREA 는 kgCO₂e/㎡
# ⚠️ 표시 값은 백엔드3 확정 전 값입니다.
ITEM_MASTER: List[Dict[str, Any]] = [
    # --- 인쇄물·홍보물 ---
    _item("a4_paper", "A4 용지", CAT_PRINT, "장", factor=0.0056, source=_ECOSQUARE,
          description="실제 사용한 종이 장수를 입력하세요"),
    _item("leaflet", "리플릿", CAT_PRINT, "장", input_method="count_variant", source=_ECOSQUARE, notes=["잠정값"],
          variants=[_v("a5", "A5", 0.006316), _v("a4", "A4", 0.012631, True), _v("a3", "A3", 0.025262)]),  # ⚠️
    _item("poster", "포스터", CAT_PRINT, "장", input_method="count_variant", source=_ECOSQUARE, notes=["잠정값"],
          variants=[_v("a4", "A4", 0.012631), _v("a3", "A3", 0.025262, True), _v("a2", "A2", 0.050523)]),  # ⚠️
    _item("banner", "현수막", CAT_PRINT, "개", input_method="dimension", calc_type="AREA", factor=0.9511,
          confidence="D", notes=["참고값"], scope="확인 필요", description="가로·세로는 m 단위로 입력하세요"),
    _item("name_tag", "종이 명찰·프로그램북", CAT_PRINT, "부", factor=0.000946, source=_ECOSQUARE,
          notes=["잠정값"]),  # ⚠️ 명찰 1개 기준
    # --- 음료·일회용품 ---
    _item("water", "생수", CAT_DRINK, "병", input_method="count_variant", source=_KEITI,
          variants=[_v("330ml", "330mL", 0.0769), _v("500ml", "500mL", 0.0793, True),
                    _v("1l", "1L", 0.1658, notes=["대표 제품 값 기준"]),
                    _v("1.5l", "1.5L", 0.1551, notes=["대표 제품 값 기준"]), _v("2l", "2L", 0.2258)]),
    _item("can_drink", "캔 음료", CAT_DRINK, "개", input_method="count_variant", source=_KEITI,
          notes=["대표 제품 값 기준"], variants=[_v("210ml", "210mL", 0.0851), _v("250ml", "250mL", 0.0936, True)]),
    _item("pet_drink", "페트 음료", CAT_DRINK, "개", input_method="count_variant", source=_KEITI,
          notes=["대표 제품 값 기준"], variants=[_v("500ml", "500mL", 0.1798, True), _v("1.5l", "1.5L", 0.3955)]),
    _item("paper_cup", "종이컵(+PP 뚜껑)", CAT_DRINK, "개", factor=0.0428, source=("학술자료", None)),
    _item("pet_cup", "PET컵(+PET 뚜껑)", CAT_DRINK, "개", factor=0.0778,
          source=("학술자료", "https://www.e-lca.org/archive/view_article_pubreader?pid=kjlca-27-2-99")),
    _item("cutlery_set", "일회용 수저 세트", CAT_DRINK, "세트", factor=0.110,
          source=("한국기후환경네트워크 탄소발자국 계산기", "https://www.gihoo.or.kr/menu.es?mid=a11302000000")),
    _item("hygiene_gloves", "위생장갑", CAT_DRINK, "매", input_method="count_variant", source=_KEITI,
          variants=[_v("pack_400", "400매입", 0.012437, True), _v("pack_150", "150매입", 0.012962)]),
    _item("wrap_film", "포장랩", CAT_DRINK, "롤", factor=4.2327, source=_KEITI,
          description="25cm × 250m 1롤 기준"),
    # --- 음식·간식 ---
    _item("sandwich", "샌드위치", CAT_FOOD, "개", factor=0.560, source=_ADEME, notes=["잠정값"], scope="원료~제조"),
    _item("pizza", "피자", CAT_FOOD, "조각", factor=0.190, source=_ADEME, notes=["잠정값"], scope="원료~제조"),
    _item("snack", "봉지과자", CAT_FOOD, "봉지", input_method="count_variant", source=_ADEME, notes=["잠정값"],
          scope="원료~제조", variants=[_v("regular", "일반", 0.152, True), _v("small", "소형", 0.092)]),
    _item("choco_bar", "초콜릿바", CAT_FOOD, "개", factor=0.363, source=_ADEME, notes=["잠정값"], scope="원료~제조"),
    _item("jelly", "젤리", CAT_FOOD, "봉지", factor=0.084, source=_BIG_CLIMATE, notes=["잠정값"], scope="원료~제조"),
    _item("cup_noodle", "컵라면", CAT_FOOD, "개", input_method="count_variant", source=_BIG_CLIMATE,
          notes=["잠정값"], scope="제조공정", variants=[_v("large", "큰컵", 0.232, True), _v("small", "작은컵", 0.137)]),
    # --- 굿즈 ---
    _item("eco_bag", "에코백", CAT_GOODS, "개", factor=0.9447, year=2026, notes=["잠정값"],
          source=("영국 환경청 LCA 데이터 정리 자료", "https://edu.rsc.org/download?ac=531823")),  # ⚠️ 67g 기준
    _item("tshirt", "티셔츠", CAT_GOODS, "벌", factor=6.5, notes=["참고값"],
          source=("Arbor", "https://www.arbor.eco/carbon-footprint/t-shirt")),
    _item("tumbler", "텀블러", CAT_GOODS, "개", input_method="count_variant",
          source=("24Bottles 자사 LCA 데이터 인용 자료",
                  "https://green-alliance.org.uk/wp-content/uploads/2021/11/losing_the_bottle_methodology.pdf"),
          variants=[_v("basic", "일반", 0.543, True), _v("insulated", "보온", 1.137)]),
    _item("ballpoint_pen", "볼펜", CAT_GOODS, "개", factor=0.005, notes=["참고값"],
          source=("Fountain Pen Revolution 블로그", None)),
    _item("acrylic_keyring", "아크릴 키링", CAT_GOODS, "개", factor=0.045339, year=2018, notes=["잠정값"],
          source=("미국 EPA LCA 보고서",
                  "https://www.epa.gov/sites/default/files/2018-02/documents/lca_mfd_printer.pdf")),  # ⚠️ 8.925g 기준
    # --- 배송 ---
    _item("delivery", "일반 배송", CAT_DELIVERY, "회", input_method="fixed_use", factor=0.33, year=2018,
          confidence="D", notes=["대표값 기준"], scope="운행만", source=("UK DEFRA 온실가스 환산계수 2018", None)),
]

ITEMS_BY_ID: Dict[str, Dict[str, Any]] = {item["item_id"]: item for item in ITEM_MASTER}


def list_active_items(category: Optional[str] = None) -> List[Dict[str, Any]]:
    if category:
        category = CATEGORY_CODES.get(category, category)
    return [copy.deepcopy(i) for i in ITEM_MASTER if i["is_active"] and (not category or i["category"] == category)]


def get_item(item_id: str) -> Optional[Dict[str, Any]]:
    item = ITEMS_BY_ID.get(item_id)
    return item if item and item["is_active"] else None


def get_variant(item: Dict[str, Any], code: Optional[str]) -> Optional[Dict[str, Any]]:
    for variant in item.get("variants") or []:
        if variant["variant"] == code:
            return variant
    return None


def default_variant(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for variant in item.get("variants") or []:
        if variant["is_default"]:
            return variant
    return None


# ===========================================================================
# DB (백엔드1 교체 예정) — 지금은 메모리 저장소
# ===========================================================================
class _MemoryStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()  # DB 트랜잭션 대신 사용
        self.events: Dict[str, Dict[str, Any]] = {}
        self.scenarios: Dict[str, Dict[str, Any]] = {}
        self.recommendations: Dict[str, Dict[str, Any]] = {}
        self._event_seq = 0
        self._scenario_seq = 0
        self._rec_seq = 0

    def next_event_id(self) -> str:
        self._event_seq += 1
        return f"EVT_{self._event_seq:04d}"

    def next_scenario_id(self) -> str:
        self._scenario_seq += 1
        return f"SCN_{self._scenario_seq:04d}"

    def next_rec_id(self) -> str:
        self._rec_seq += 1
        return f"REC_{self._rec_seq}"


_store = _MemoryStore()


def transaction() -> threading.RLock:
    """with transaction(): 블록 = DB 트랜잭션 자리. 백엔드1 connection.py 의 트랜잭션 함수로 교체."""
    return _store.lock


def reset_store() -> None:
    """테스트용: 저장소 초기화"""
    global _store
    _store = _MemoryStore()


def create_event(data: Dict[str, Any]) -> Tuple[str, str]:
    """행사 + original 시나리오를 함께 만들고 (event_id, scenario_id) 반환"""
    with _store.lock:
        event_id = _store.next_event_id()
        scenario_id = _store.next_scenario_id()
        _store.events[event_id] = {"event_id": event_id, **data}
        _store.scenarios[scenario_id] = {
            "scenario_id": scenario_id, "event_id": event_id, "scenario_type": "original",
            "items": [], "version": 0,
        }
        return event_id, scenario_id


def get_event(event_id: str) -> Optional[Dict[str, Any]]:
    event = _store.events.get(event_id)
    return copy.deepcopy(event) if event else None


def get_scenario(scenario_id: str) -> Optional[Dict[str, Any]]:
    scenario = _store.scenarios.get(scenario_id)
    return copy.deepcopy(scenario) if scenario else None


def find_scenario(event_id: str, scenario_type: str) -> Optional[Dict[str, Any]]:
    for scenario in _store.scenarios.values():
        if scenario["event_id"] == event_id and scenario["scenario_type"] == scenario_type:
            return copy.deepcopy(scenario)
    return None


def _delete_improved_and_recs(event_id: str) -> None:
    for sid in [s for s, v in _store.scenarios.items() if v["event_id"] == event_id and v["scenario_type"] == "improved"]:
        del _store.scenarios[sid]
    for rid in [r for r, v in _store.recommendations.items() if v["event_id"] == event_id]:
        del _store.recommendations[rid]


def replace_scenario_items(scenario_id: str, items: List[Dict[str, Any]]) -> int:
    """original 품목 통째로 교체 + 기존 추천·improved 삭제. 새 version 반환"""
    with _store.lock:
        scenario = _store.scenarios[scenario_id]
        scenario["items"] = copy.deepcopy(items)
        scenario["version"] += 1
        _delete_improved_and_recs(scenario["event_id"])
        return scenario["version"]


def replace_recommendations(event_id: str, scenario_id: str, recs: List[Dict[str, Any]],
                            base_version: int) -> List[Dict[str, Any]]:
    """이전 추천·improved 삭제 후 새 추천 저장. rec_id 를 붙여서 반환. 호출 전에 transaction() 안에서 버전 확인"""
    with _store.lock:
        _delete_improved_and_recs(event_id)
        saved = []
        for rec in recs:
            rec_id = _store.next_rec_id()
            row = {**copy.deepcopy(rec), "rec_id": rec_id, "event_id": event_id,
                   "scenario_id": scenario_id, "base_version": base_version}
            _store.recommendations[rec_id] = row
            saved.append(copy.deepcopy(row))
        return saved


def get_recommendations(rec_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    return {rid: copy.deepcopy(_store.recommendations[rid]) for rid in rec_ids if rid in _store.recommendations}


def save_improved_scenario(event_id: str, items: List[Dict[str, Any]]) -> str:
    """improved 시나리오를 덮어쓰고 scenario_id 반환 (행사당 1개)"""
    with _store.lock:
        existing = find_scenario(event_id, "improved")
        scenario_id = existing["scenario_id"] if existing else _store.next_scenario_id()
        _store.scenarios[scenario_id] = {
            "scenario_id": scenario_id, "event_id": event_id, "scenario_type": "improved",
            "items": copy.deepcopy(items), "version": 0,
        }
        return scenario_id


# ===========================================================================
# 계산 (백엔드3 교체 예정) — calculator/emissions.py, analysis.py 자리
# ===========================================================================
def calc_item(row: Dict[str, Any]) -> Dict[str, Any]:
    """품목 1줄 계산. row: item_id, quantity, variant, width_m, height_m, unit_price"""
    item = ITEMS_BY_ID.get(row["item_id"])
    if item is None:
        raise ValueError(f"계수를 찾을 수 없음: {row['item_id']}")
    variant = get_variant(item, row.get("variant")) if item.get("variants") else None
    factor = variant["factor"] if variant else item["factor"]
    if factor is None:
        raise ValueError(f"계수를 찾을 수 없음: {row['item_id']} / {row.get('variant')}")

    quantity = row.get("quantity") or 0
    if item["calc_type"] == "AREA":
        emission = row["width_m"] * row["height_m"] * quantity * factor
    else:
        emission = quantity * factor

    unit_price = row.get("unit_price")
    cost = int(round(unit_price * quantity)) if unit_price is not None else None
    notes = list(item["notes"]) + (variant["notes"] if variant else [])
    return {
        "item_id": item["item_id"], "item_name": item["item_name"], "category": item["category"],
        "variant_label": variant["label"] if variant else None, "quantity": quantity, "unit": item["input_unit"],
        "emission": emission, "cost": cost, "confidence": item["confidence"], "notes": notes,
        "source": {"name": item["source_name"], "year": item["source_year"], "url": item["source_url"]},
        "scope": item["scope"],
    }


def analyze_items(rows: List[Dict[str, Any]], participants: int, budget: Optional[int]) -> Dict[str, Any]:
    """행사 전체 분석. 반올림 전 값으로 돌려주고, 반올림은 서비스에서 합니다."""
    results = sorted((calc_item(r) for r in rows), key=lambda r: r["emission"], reverse=True)
    total = sum(r["emission"] for r in results)
    for r in results:
        r["ratio"] = (r["emission"] / total * 100) if total > 0 else None

    categories: Dict[str, float] = {}
    for r in results:
        categories[r["category"]] = categories.get(r["category"], 0.0) + r["emission"]
    by_category = [
        {"category": c, "emission": e, "ratio": (e / total * 100) if total > 0 else None}
        for c, e in sorted(categories.items(), key=lambda kv: kv[1], reverse=True)
    ]

    priced = [r for r in results if r["cost"] is not None]
    total_cost = sum(r["cost"] for r in priced) if priced else None
    top = results[:3]
    warnings = []
    # TODO(백엔드3): "계산 범위가 다른 자료를 포함함" 표시 조건 확정 후 교체. 지금은 계산 범위가 2종류 이상이면 표시
    if len({r["scope"] for r in results}) > 1:
        warnings.append("계산 범위가 다른 자료를 포함함")

    return {
        "total_emission": total,
        "emission_per_person": total / participants if participants else 0.0,
        "total_cost": total_cost,
        "priced_item_count": len(priced),
        "budget_usage_rate": (total_cost / budget * 100) if (total_cost is not None and budget) else None,
        "by_item": results,
        "by_category": by_category,
        "top_items": [r["item_id"] for r in top],
        "top_items_share": (sum(r["emission"] for r in top) / total * 100) if total > 0 else None,
        "warnings": warnings,
    }


# ===========================================================================
# AI (백엔드4 교체 예정) — ai/recommender.py 자리
# ===========================================================================
# 품목 교체 후보 (임시 규칙)
_REPLACEMENTS: Dict[str, Tuple[str, str, str]] = {
    "pet_drink": ("can_drink", "250ml", "같은 수량을 캔 음료로 바꾸면 개당 배출량이 절반 수준으로 줄어듭니다."),
    "pet_cup": ("paper_cup", None, "PET컵을 종이컵으로 바꾸면 개당 배출량이 줄어듭니다."),
}


def call_ai(ai_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    백엔드4 AI 함수 자리. 입력·출력 형식은 명세서 v02 5번 '백엔드4 함수 입력·출력 JSON'.

    TODO(백엔드4): 아래처럼 교체
        from ai.recommender import generate_recommendations
        return generate_recommendations(ai_input, api_key=get_settings().ai_api_key)
    """
    settings = get_settings()
    _api_key = settings.ai_api_key  # "여기에_AI_API_키_입력" 이면 아직 발급 전

    max_recs = ai_input["constraints"]["max_recommendations"]
    recs: List[Dict[str, Any]] = []
    for item in sorted(ai_input["items"], key=lambda i: i["emission"], reverse=True):
        if len(recs) >= max_recs:
            break
        if item["input_method"] == "fixed_use":
            continue
        replacement = _REPLACEMENTS.get(item["item_id"])
        if replacement:
            alt_id, alt_variant, reason = replacement
            recs.append({
                "item_id": item["item_id"], "action_type": "replace_item", "target_field": "item_id",
                "recommended_value": None, "alternative_item_id": alt_id, "alternative_variant": alt_variant,
                "title": f"{item['item_name']} → {ITEMS_BY_ID[alt_id]['item_name']}", "difficulty": "쉬움", "reason": reason,
            })
        elif item["quantity"] and item["quantity"] >= 2:
            new_quantity = int(item["quantity"] * 0.6)
            if 0 < new_quantity < item["quantity"]:
                recs.append({
                    "item_id": item["item_id"], "action_type": "reduce_quantity", "target_field": "quantity",
                    "recommended_value": new_quantity, "alternative_item_id": None, "alternative_variant": None,
                    "title": f"{item['item_name']} 수량 조정", "difficulty": "쉬움",
                    "reason": f"{item['item_name']} 배출 비중이 커서, 참여 인원에 맞게 수량을 줄이면 감축 효과가 큽니다.",
                })
    return {"recommendations": recs}
