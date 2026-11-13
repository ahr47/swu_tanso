# 탄소줄이슈 백엔드3 — API v02 계산 모듈 완성본

2026-11-05. **품목 계산 → 행사 전체 분석 → 추천 효과 계산 → 개선안 전체 비교**를 구현했다.
실제 팀 구조의 `backend/calculator/`와 `backend/tests/test_calculator.py`에 배치한다.
기존 1·2단계 파일을 이 완성본으로 교체한다. 다른 팀원 담당 파일은 포함하지 않는다.

## 1. 완료한 기능과 파일

| 단계 | 구현·검증 |
|---|---|
| 1. 구조·인터페이스 | 팀 폴더 확인, schemas.py와 공개 import 작성 |
| 2. 품목별 계산 | COUNT·AREA, 기본 변형, 배송 고정 수량, 품목별 비용 |
| 3. 테스트 | 정상·오류 입력, 계수·변형 누락, 비용 null, 반올림, 입력 불변성 |
| 4. 행사 분석 | 총량·1인당·비용·예산·품목/분야 비중·상위 3개·경고 |
| 5. 추천·비교 | 수량 감축·호환 품목 교체·원값 감축량·불명확 비용 null·전체 품목 비교 |
| 6. 전체 품목 검증 | 제공 v02 데이터 25개 품목/39개 계수 전부, 25개 품목 동시 분석, 9개 품목 흐름 통합 테스트 |

```text
backend/
  calculator/
    __init__.py           # 공개 함수 4개 import
    schemas.py            # 입력·품목·계수·원값 결과·오류
    emissions.py          # calculate_item
    analysis.py           # analyze_scenario
    comparison.py         # calculate_recommendation_effect, compare_scenarios
    catalogue.py          # DB 조회 행 -> 계산 객체 변환 (DB 접속 없음)
    catalogue_v02.json    # 백엔드1 전달/예시/테스트용 25품목·39계수 데이터
    example.py            # 백엔드2 호출 예시: 분석→추천 효과→비교
    requirements-dev.txt  # pytest만 (계산 실행은 표준 라이브러리)
    README.md
  tests/
    test_calculator.py    # 전체 테스트 코드
```

총 11개 파일이다. `__init__.py`는 앞뒤 밑줄이 두 개씩이며 `init.py`와 다르다.
API·DB·AI 담당자는 이 계산 모듈을 호출한다. 계산 모듈에는 DB 접속, FastAPI 라우터, AI 호출을 넣지 않았다.

## 2. 설치와 실행

Python 3.10 이상. 실제 검증 환경: Python 3.12 / pytest 9.2.0.
팀 저장소 **루트**에서:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/calculator/requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_calculator.py
.\.venv\Scripts\python.exe -m backend.calculator.example
```

가상환경 파이썬을 직접 지정했으므로 PowerShell 활성화 권한 변경은 필요 없다.
Python 환경이 준비됐다면 루트에서 `python -m pytest`로도 테스트를 찾을 수 있다.
다른 팀원 테스트가 추가된 저장소에서 계산 파트만 확인하려면 위처럼 파일 경로를 지정한다.

`backend` 폴더에서 실행하는 경우:

```bash
python -m pip install -r calculator/requirements-dev.txt
python -m pytest -q tests/test_calculator.py
python -m calculator.example
```

2026-11-05 루트와 backend 폴더에서 검증: **141 passed**.
예시 출력도 실행하고 JSON 직렬화를 검증했다.
이는 계산 모듈과 전달 데이터 기반의 통합 검증이다. 실제 PostgreSQL/FastAPI/AI 서버 연결 테스트는 아니다.

## 3. 백엔드2 호출 인터페이스

backend에서 실행하는 서버는 아래처럼 import한다.
저장소 루트에서 backend 경로로 실행한다면 `from backend.calculator import ...`도 가능하다.
같은 프로세스 안에서는 import 경로를 하나로 통일한다.

```python
from calculator import (
    calculate_item, analyze_scenario,
    calculate_recommendation_effect, compare_scenarios,
)
from calculator.catalogue import catalogue_from_records

# DB 저장소가 조회한 행. 컬럼명이 다르면 서비스에서 아래 내부 형식으로 변환한다.
items, factors = catalogue_from_records(item_rows, factor_rows)
common = dict(items=items, factors=factors, factor_version=current_factor_version)
# current_factor_version은 core.config에서 읽은 CURRENT_FACTOR_VERSION 서버 값.
# 클라이언트가 보내는 버전을 사용하지 않는다.

analysis = analyze_scenario(
    inputs, **common, participants=100, budget=1_000_000,
    scenario_id="SCN_0001", scenario_type="original",
)
analyze_response = analysis.to_api_response()

effect = calculate_recommendation_effect(
    {"item_id": "eco_bag", "quantity": 50, "unit_price": 6750},
    **common, action_type="reduce_quantity", recommended_value=30,
)
if effect.can_calculate:
    recommendation_fields = effect.to_api_fields()
    # {"emission_reduction": 36.66, "cost_change": -135000}
else:
    # API는 이 추천만 제외하고 원인을 기록한다.
    error_for_log = effect.error.as_dict()

replacement = calculate_recommendation_effect(
    {"item_id": "pet_drink", "quantity": 50, "variant": "500ml"},
    **common, action_type="replace_item", alternative_item_id="can_drink",
    alternative_variant="250ml", alternative_unit_price=None,
)
# replacement.to_api_fields(): {"emission_reduction": 4.31, "cost_change": None}
# alternative_unit_price는 내부 연동 인자. AI 추정 가격을 쓰지 않는다.

comparison = compare_scenarios(
    original_inputs, improved_inputs, **common, participants=100, budget=1_000_000,
    original_scenario_id="SCN_0001", improved_scenario_id="SCN_0002",
    replacements={"pet_drink": "can_drink"},
)
compare_response = comparison.to_api_response()
```

실행 가능한 전체 호출 예시는 `example.py`에 있다. DB·AI 대신 제공 JSON 데이터를 사용한다.
외부 API 응답은 `to_api_response()` / `to_api_fields()`로 만든다.
내부 `can_calculate`, `error`, `replacements`, `scope_group`, `alternative_unit_price`를
API v02의 새로운 필드처럼 보내지 않는다.

| 함수 | 입력 | 반환 |
|---|---|---|
| calculate_item | ItemInput 또는 dict, 단일 ItemDefinition, 계수 목록, 버전 | ItemCalculation. emission은 Decimal 원값, cost는 int/None |
| analyze_scenario | 품목 입력 목록, 품목 사전, 계수, 버전, 인원, 시나리오 ID, 예산 | ScenarioAnalysis. 전체/품목 원값과 to_api_response() |
| calculate_recommendation_effect | 원본 입력, action_type, 추천 수량 또는 대체 품목/변형, 공통 데이터 | RecommendationEffect. 계산 가능 여부, 전후 원값, 감축량, 비용 변화, 오류 |
| compare_scenarios | 원본/개선안 입력 목록, 공통 데이터, 인원, 두 시나리오 ID, 교체 대응표 | ScenarioComparison. 전후 분석, 원값 감축량, 비용 변화, 전체 행 비교 |

`ItemInput`은 v02 PUT의 item_id/quantity/variant/width_m/height_m/unit_price이다.
결과의 원값은 후속 계산에 쓰고, 반올림한 API 응답을 합계·비교 계산에 다시 넣지 않는다.
시나리오 ID를 응답에 넣는 기능이 DB 소속 검사를 대신하지는 않는다.

## 4. 백엔드1에서 전달할 데이터

`catalogue_v02.json`에 전체 25품목·39계수 데이터 예시가 있다.
사용자 제공 v02 값을 옮긴 전달 데이터이며, DB에 실행하는 SQL이 아니다.
계산 코드에는 품목별 계수를 중복 하드코딩하지 않았다.
실서비스에서는 JSON을 자동 대체 계수로 읽지 않고 DB 조회 결과를 전달한다.

| item_rows 필드 | 내용 |
|---|---|
| item_id / item_name / category | 문자열 ID, 표시명, 분야 |
| calc_type / input_method / input_unit | COUNT/AREA, 입력 방식 4종, 개/장/부/회 등 |
| is_active | bool. 비활성 품목은 계산 거부 |
| variants | null 또는 variant/label/is_default 행의 배열. 기본 변형은 정확히 1개 |
| notes / description | 표시 문구 배열, 선택 보조 문구 |

| factor_rows 필드 | 내용 |
|---|---|
| item_id / variant | 품목과 변형. 변형 없는 품목의 DB 내부 키는 default |
| value / unit / calc_type | Decimal 권장 계수, 단위 문자열, 계산 유형 |
| factor_version | 서버 지정 버전과 완전히 일치하는 행만 사용 |
| source_name / source_url / source_year | 사이트명 수준 출처, URL/연도는 null 가능 |
| confidence / notes | 신뢰도 또는 null, 주의 문구 배열 |
| scope_group | production/material/transport. 전체 경고용 내부 그룹 |

계수 NULL은 None으로, 실제 0 계수는 숫자 0으로 전달한다.
같은 (item_id, variant, factor_version)의 계수가 없거나 중복이면 계산 불가이다.
DB 단위가 다르면 서비스에서 맞춘다. 계산기는 단위 문자열을 보고 무게 환산을 추측하지 않는다.

### 버전·출처

JSON 버전 표기는 v02 문서와 동일하게 `v1.0-2026-10`이다.
예전 WEIGHT 데이터에도 같은 라벨을 사용했다면 같은 버전에 덮어쓰거나 섞지 않는다.
이미 쓰던 버전의 계산 의미가 바뀌면 백엔드1·2가 새 버전을 정하고 DB 행과 환경변수를 맞춰야 한다.
계산기는 버전을 임의로 바꾸지 않고 전달받은 정확한 버전만 선택한다.
과거 리포트 재현에 필요한 버전·입력·결과 스냅샷 저장은 API/DB 담당이다.

출처는 요청대로 ECOSQUARE 등 **사이트명·링크 수준**으로 수록했다. 상세 쪽수를 요구하지 않는다.
테스트 통과가 원출처 계수의 정확성을 입증하는 것은 아니다.
볼펜·젤리·키링·에코백 등의 출처/산출 설명 불일치는 notes에 표시하고, 계산기가 값을 바꾸지 않는다.
참고 단가를 이용해서 실제 비용을 만들어 내지 않는다.

## 5. 계산·비용·null·반올림

- COUNT=수량×등록된 단위당 계수. AREA=가로m×세로m×수량×㎡당 계수.
- fixed_use는 입력 수량 없이 내부 수량 1. 배송은 DB가 0.33을 제공하며 코드에 중복 정의하지 않는다.
- 변형 null/생략은 기본값 적용. 실제 변형은 result.variant와 analysis.inputs에 남는다.
- 배출량의 곱·합계는 Decimal 원값. 나눗셈·비율은 Fraction으로 계산한 후 최종 자리에서만 반올림한다.
- 배출량 응답은 소수 둘째 자리, 비율은 첫째 자리, HALF_UP(동률은 절댓값이 커지는 방향)이다.
- JSON number는 끝자리 0을 보존하지 않는다. 2자리 고정 표시는 프론트에서 처리한다.
- 총 배출량 0이면 비중/감축률은 null. 참여 인원은 반드시 1 이상이다.
- 단가 없음은 cost=None. 0원 단가는 알려진 무료이므로 cost=0이다.
- total_cost는 알려진 단가 품목 비용의 부분 합계. 전부 미입력이면 None이며 priced_item_count도 반환한다.
- 예산 없음/0 또는 비용 미입력이면 budget_usage_rate=None이다.
- scope_group이 2종 이상이면 전체 warnings에 `계산 범위가 다른 자료를 포함함`을 한 번 넣는다.
- 잠정값·참고값은 by_item.notes에 반환한다. 개선안 경고는 개선 후 품목으로 별도 판정한다.

### 비용 변화의 중요 처리

교체 품목의 단가를 모르면 원래 단가를 복사하지 않고 추천 효과의 cost_change=None을 반환한다.
전체 비교는 **변경된 품목 중 하나라도 전후 비용이 불명확하면 cost_change=None**이다.
그대로 유지된 품목의 단가 미입력은 변경분 계산에 영향을 주지 않는다.
에코백만 50→30으로 바꾸면 다른 미입력 품목이 있어도 -135000원을 반환할 수 있다.
가격 미상 PET→캔 교체도 동시에 적용되면, 알려진 비용 합계의 차이를 전체 절감액으로 단정하지 않는다.
단가가 하나도 없으면 변경이 없어도 cost_change=None이다.

이는 요청한 ‘불명확한 비용을 절감액으로 추정하지 말 것’에 따른다.
v02 복합 추천 예시의 cost_change=-135000과는 다른 부분이다.
before/after.total_cost는 계속 알려진 비용의 부분 합계를 반환한다.

## 6. 추천·비교의 역할 분담

계산 모듈은 다음을 처리한다.

- 원본·대체 품목 모두 해당 버전으로 계산할 수 있는지 검사.
- 교체 시 calc_type과 input_unit이 모두 같은지, 원래 수량을 유지하는지 검사.
- 수량 감축은 양의 정수이고 현재 수량보다 작은지 검사. 수량 고정 품목 변경은 거부.
- 추천 계산 실패는 can_calculate=False/error, 감축량 None. 0으로 성공 처리하지 않음.
- 전체 비교는 바뀌지 않은 품목도 포함하며 감축량은 반올림 전 before-after로 계산.
- 교체 전후는 내부 replacements로 명시. 이름·배출량으로 대응 관계를 추측하지 않음.
- 실제 제거·추가 품목은 존재하지 않는 쪽의 배출량을 0으로 표시. 계산 불가를 0으로 바꾸는 것과 다름.
- 여러 원본을 동일한 대체 행에 합치는 모호한 매핑은 CONFLICTING_RECOMMENDATIONS로 거부.

다음은 API/DB/AI 파트의 연결 작업이다. 이 계산기가 대신 수행했다고 주장하지 않는다.

- event/scenario/rec ID 소속, 추천 최신성, 같은 품목 추천 중복, 동시 수정 검사.
- AI 입력·호출·재시도·시간 제한 및 title/difficulty/reason 생성·검증.
- applicable/not_applicable_reason, 예산 유지 정책, 추천 개수/empty_reason 결정.
- DB 저장, improved 덮어쓰기, 트랜잭션, CURRENT_FACTOR_VERSION 설정.
- 검증된 추천으로 improved_inputs/replacements를 작성하여 계산기를 호출.

API/AI/DB 담당 파일을 수정하지 않고 위 네 함수가 호출될 수 있게 분리했다.

## 7. 오류·검증

CalculationError에 code/field/message/as_dict()가 있다. HTTP 예외는 직접 발생시키지 않는다.
단품 함수는 상대 field, analyze는 `items[1].width_m` 같은 경로를 붙인다.

| 코드 | 의미 | API HTTP 매핑 |
|---|---|---|
| INVALID_INPUT | 누락, 비지원 필드, 치수, 변형, 가격 등 | 400 |
| INVALID_QUANTITY | 수량 정수·범위 위반 | 400 |
| UNKNOWN_ITEM | 미등록/비활성 품목 | 400 |
| DUPLICATE_ITEM / NO_ITEMS | 품목 중복/빈 목록 | 400 |
| CONFLICTING_RECOMMENDATIONS | 비교의 모호한 교체 매핑 | 400 |
| CALC_NOT_AVAILABLE | 버전·계수 누락/중복/불일치 | 422 |

analyze에서 한 줄이라도 잘못되면 부분 합계를 정상 응답으로 반환하지 않는다.
화면의 줄별 미리보기는 calculate_item을 각각 호출해 처리할 수 있다.
API 저장/분석은 v02의 일괄 검증 규칙에 따른다.

수량 1~1,000,000 정수, 길이 0 초과~50m, 단가 0~10,000,000 정수 원.
상한은 이전 백엔드3 확정 범위를 유지했다. bool/NaN/Infinity/문자열 숫자는 거부한다.
paper_size/gsm/duplex/sheets_per_copy/unit_weight_g/weight_kg는 삭제된 필드로 거부한다.
해당 품목과 관련 없는 요청 키는 null이어도 거부한다. 내부 ItemInput 미사용 속성 None은 허용한다.

## 8. 이전 명세서와 충돌한 부분

| 이전 내용 | 이번 구현 |
|---|---|
| WEIGHT/TRANSPORT와 무게 입력 | v02 COUNT/AREA만 적용 |
| input_method 6종 | count_only/count_variant/dimension/fixed_use 4종 |
| A4 인쇄 면 수·양면·평량 | 실제 장수. 100장×0.0056=0.56 |
| 종이 규격 마스터와 무게 식 | 리플릿·포스터 소문자 variant의 등록 계수 사용 |
| kg 계수×사용자 입력 무게 | v02 개당 계수를 그대로 사용 |
| 에코백 67g 또는 120g 예시 | 130g 대표값 1.833/개 |
| 키링 8.925g 환산 | v02 6g 대표값 0.0305/개 |
| 식품 kg당 계수로 매번 환산 | 0.560/0.190/0.152/0.363 등 v02 값을 그대로 사용 |

리플릿·포스터 면적 비례 값은 잠정이다. 명찰 계수는 86×55mm 1개 기준으로 여러 장 프로그램북에는 맞지 않는다.
임의 수정 대신 제공 계수와 notes를 반환한다. scope_group도 팀의 가정이며 실제 LCA 범위를 입증하는 정보는 아니다.

## 9. 샘플 입력·출력

전체 입력과 응답 코드는 example.py에 있다. 입력은 v02의 9품목 예시다.
아래는 출력의 주요 값만 발췌했으며 새 API 필드 제안이 아니다.

| 결과 | 값 |
|---|---:|
| 내부 총 배출량 | 179.34894 kgCO₂e |
| 응답 총 배출량 / 1인당 | 179.35 / 1.79 |
| 알려진 비용 / 단가 입력 품목 수 | 975500원 / 4개 |
| 예산 사용률 | 97.6% |
| 상위 3개 | eco_bag / sandwich / pet_drink |
| 상위 3개 합계 비중 | 87.3% |
| 에코백 50→30 감축량 / 비용 변화 | 36.66 kgCO₂e / -135000원 |
| PET→캔 감축량 / 비용 변화 | 4.31 kgCO₂e / null |
| 두 추천 반영 후 총량 / 1인당 | 138.38 / 1.38 |
| 두 추천 총 감축량 / 감축률 | 40.97 / 22.8% |
| 개선 후 알려진 비용 부분 합계 | 840500원 |
| 두 추천 전체 비용 변화 | null (교체 단가 미상) |

예시는 analyze의 전 품목·분야 응답과 compare의 전체 9행을 출력한다.

## 10. GitHub 업로드와 PR

현재 사진의 작업 브랜치는 `feat/carculator`이다. `main`에 바로 올리지 않는다.
이 ZIP을 풀고 아래 경로로 파일을 업로드한다.

1. GitHub에서 리포지토리 **최상위**로 이동하고 작업 브랜치인지 확인한다.
2. Add file → Upload files를 누른다.
3. ZIP을 푼 뒤 나온 `backend` 폴더를 드래그한다. ZIP 파일 자체를 올리지 않는다.
4. 업로드 목록이 backend/calculator의 10개와 backend/tests/test_calculator.py, 총 11개인지 확인한다.
5. 다른 사람의 파일이 포함되지 않았는지 확인하고 작업 브랜치에 커밋한다.
6. Pull requests → New pull request에서 base=main, compare=feat/carculator를 선택한다.
7. Files changed를 확인한 뒤 PR을 만든다. 충돌이 있으면 자동으로 덮어쓰지 말고 내용을 비교한다.

작업 브랜치가 main보다 뒤처졌다면 GitHub의 Update branch 기능으로 먼저 최신 변경을 반영한다.
로컬 Git을 쓰는 경우에는 팀 규칙대로 작업 전·업로드 전 git pull로 최신 변경을 반영한다.
이 환경에는 팀 비공개 저장소 인증이 없어 원격 pull/push/PR 생성은 실행하지 않았다.
ZIP을 git init해서 원격 연결된 것처럼 가장하지 않는다.

PR 제목 예시:

`feat: implement v02 carbon analysis and comparison calculator`

PR 본문 예시:

> v02 COUNT/AREA 계산, 기본 변형, 행사 전체 분석, 추천 효과, 개선안 전체 비교를 추가했습니다.
> DB/AI 접근 없이 조회된 계수와 서버 지정 버전을 인자로 받습니다.
> 대체 단가가 미상인 교체는 비용 변화를 null로 반환합니다.
> 25품목·39계수 및 9품목 흐름을 포함한 141개 테스트가 통과했습니다.
> 실제 PostgreSQL/FastAPI/AI 연결 검증은 이 계산 모듈 테스트에 포함하지 않았습니다.
