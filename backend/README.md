# 탄소줄이슈 백엔드

API 필드명세서 v02 기준 FastAPI 서버입니다.

## 실행 방법

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
| `DATABASE_URL` | 백엔드1 | 지금은 `여기에_DB_연결_주소_입력` 그대로 둬도 메모리 저장소로 동작 |
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

## 임시 어댑터 (`services/adapters.py`)

DB·계산·AI 코드가 올라오기 전까지 서버가 동작하도록 만든 임시 구현입니다.
`services/*.py` 는 이 파일의 함수만 부르므로, 각 파트 코드가 준비되면 이 파일 안의 해당 구역만 교체합니다.

| 구역 | 지금 | 교체할 코드 |
| --- | --- | --- |
| 품목 마스터·계수 | 파일 안의 `ITEM_MASTER` | 백엔드1 `item_repository` + 백엔드3 계수 테이블 |
| DB | 메모리 저장소 (서버를 끄면 사라짐) | 백엔드1 `db/repositories` |
| 계산 | `calc_item`, `analyze_items` | 백엔드3 `calculator` |
| AI | `call_ai` (규칙 기반) | 백엔드4 `ai/recommender` |
