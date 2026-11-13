# 탄소줄이슈 백엔드

API 필드명세서 v02 기준 FastAPI 서버입니다.

## 로컬 체험 (가장 쉬운 방법)

저장소 맨 위 폴더에서 명령 하나로 DB + 백엔드 + 화면이 모두 켜집니다. 브라우저가 자동으로 열립니다.

```bash
./run.sh          # 맥은 start.command 더블클릭도 가능
```

- 화면: http://127.0.0.1:8000  /  API 문서: http://127.0.0.1:8000/docs
- 종료: 실행한 창에서 Ctrl+C
- 필요한 것: Python 3.10+, Node.js 20+. 처음 한 번은 설치 때문에 1~2분 걸리고 인터넷이 필요합니다.
- 데이터는 `backend/pgdata/` 에 남습니다. 처음 상태로 되돌리려면 그 폴더를 지우고 다시 실행하세요.
- AI 추천을 실제 모델로 쓰려면 `backend/.env` 의 `AI_API_KEY` 에 OpenAI 키를 넣으세요 (없으면 임시 규칙 추천).

## 실행 방법 (개발용으로 직접 켜기)

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # 값 채우기 (아래 참고)
uvicorn main:app --reload
```

- API 문서: http://127.0.0.1:8000/docs
- 상태 확인: http://127.0.0.1:8000/health
- 테스트: `pytest -q`

## .env 에 채울 값

| 항목 | 받을 곳 | 비고 |
| --- | --- | --- |
| `DATABASE_URL` | 백엔드1 | 비워 두면(`여기에_DB_연결_주소_입력`) 메모리 저장소로 동작. 아래 "DB" 참고 |
| `AI_API_KEY` | 백엔드4 | 지금은 `여기에_AI_API_키_입력` 그대로 둬도 임시 규칙 기반 추천으로 동작 |

`.env` 는 깃허브에 올리지 않습니다 (`.gitignore` 에 포함).

## 폴더 담당과 호출 규칙

| 폴더 | 담당 | 역할 |
| --- | --- | --- |
| `main.py`, `core/`, `routes/`, `schemas/`, `services/` | 백엔드2 | API, 요청·응답 형식, 처리 흐름 |
| `db/` | 백엔드1 | DB 연결, 조회·저장 (seed 데이터는 백엔드3이 제공) |
| `calculator/` | 백엔드3 | 탄소·비용 계산 (DB 접근 없음) |
| `ai/` | 백엔드4 | AI 추천 (DB 접근 없음) |

1. 호출 방향은 `routes → services → (db, calculator, ai)` 한 방향만 허용합니다.
2. 파트 사이 데이터 형식을 바꿀 때는 백엔드2와 먼저 합의합니다.
3. API 를 구현할 때마다 `/docs` 와 필드명세서가 맞는지 확인합니다.

## 어댑터 (`services/adapters.py`)

`services/*.py` 는 이 파일의 함수만 부릅니다. 파트 코드가 준비될 때마다 이 파일 안의 해당 구역만 교체합니다.

| 구역 | 지금 | 비고 |
| --- | --- | --- |
| 품목 마스터·계수 | DB `items`·`item_variants`·`emission_factors` | DB 없으면 `calculator/catalogue_v02.json` |
| 계산 | 백엔드3 `calculator` (`analyze_scenario`, `calculate_item`) | 연결 완료 |
| AI | 백엔드4 `ai/recommender` (OpenAI `gpt-6.1-sol`) | 연결 완료. `AI_API_KEY` 가 비어 있으면 임시 규칙 기반 추천 |
| DB | 백엔드1 `db/repositories` (PostgreSQL) | 연결 완료. `DATABASE_URL` 이 비어 있으면 메모리 저장소 |

- 재시도는 백엔드4 모듈이 1회 직접 합니다. 실제 AI 를 쓸 때 서비스는 한 번만 부르고 `AI_TIMEOUT_SECONDS × 2 + 5`초까지 기다립니다 (`adapters.ai_call_policy`).
- 배출량은 계산기의 Decimal 원값을 받아 서비스에서 HALF_UP 으로 반올림합니다.

## DB

PostgreSQL 14 이상 (또는 개발용 PGlite). `.env` 에 `DATABASE_URL` 을 넣고 서버를 켜면,
테이블이 없을 때 `db/sql/schema.sql` + `seed.sql` 을 자동으로 실행합니다 (`DB_AUTO_INIT=true`).

```bash
# PostgreSQL 이 없으면 PGlite (Node.js 20+, 동시 연결 1개라 DB_POOL_MAX=1)
npx -y -p @electric-sql/pglite-socket pglite-server --db=./pgdata --port=5432
# .env: DATABASE_URL=postgresql://postgres@127.0.0.1:5432/postgres?sslmode=disable

python -m db            # 수동 초기화 (테이블이 없을 때만)
python -m db --reset    # 모두 지우고 다시 생성 — 데이터가 사라집니다
```

| 테이블 | 내용 |
| --- | --- |
| `items`, `item_variants`, `emission_factors` | 품목 마스터·변형·버전별 배출계수 (출처 포함) |
| `events` | 행사 (`EVT_0001`) |
| `scenarios`, `scenario_items` | 행사별 original / improved 시나리오와 품목 (`SCN_0001`), `version` 으로 추천 유효성 확인 |
| `recommendations` | 추천 (`REC_1`), 생성 시점 `base_version` 저장 |

- **계수 데이터의 원본은 백엔드3의 `calculator/catalogue_v02.json`** 입니다. 바뀌면
  `python -m db.seed_from_catalogue` 로 `seed.sql` 을 다시 만들고 함께 커밋하세요.
  이미 만든 DB 에 반영하려면 `python -m db --reset` (행사 데이터도 지워짐) 또는 계수 테이블만 갱신합니다.
- 품목·계수는 서버가 처음 쓸 때 읽어 캐시합니다. DB 에서 직접 계수를 바꿨다면 서버를 재시작하세요.
- 테스트를 실제 DB 로 돌리려면 **비어 있어도 되는 테스트 전용 DB** 를 지정합니다 (시작 시 초기화됨):
  `TEST_DATABASE_URL=postgresql://... pytest -q`
