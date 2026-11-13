# 탄소줄이슈 — 백엔드 4 AI 추천 모듈 (API v02)

## 통합 전 주의

- 이 폴더는 **기존 GitHub 저장소를 열람하지 않고** 최신 API v02를 바탕으로 작성한 독립 모듈입니다. 기존에 같은 이름의 파일이 있으면 덮어쓰지 말고 내용 비교 후 PR로 합쳐 주세요.
- 본 구현은 **OpenAI Python SDK를 사용하는 참고 구현**입니다. 팀에서 다른 AI 제공업체를 사용한다면 `recommender.py`의 모델 호출 어댑터를 해당 SDK로 교체하세요. 사용 모델명은 임의로 가정하지 않았습니다.
- **DB 연결, 배출량·비용 계산, API 라우트, 추천 저장은 구현하지 않습니다.** 백엔드 1·2·3의 담당 기능입니다.

## 파일

| 파일 | 역할 |
|---|---|
| `schemas.py` | v02 내부 AI 입력과 AI만 반환하는 9개 추천 필드 정의 |
| `prompt.py` | 정책·허용 행동·출력 형식 및 비신뢰 텍스트 규칙 |
| `parser.py` | JSON 구문 및 스키마·행동별 형태 검증 |
| `recommender.py` | OpenAI Responses API 비동기 호출, 1회 재시도, 사용자에게 안전한 오류 전달 |
| `example_payload.json` | 일관된 테스트용 행사·품목 예시 |
| `../tests/test_ai.py` | 실제 AI 호출 비용 없이 실행하는 단위 테스트 |

## 의존성 (기존 backend/requirements.txt에 누락된 것만 추가)

```text
pydantic>=2,<3
openai>=2,<3
pytest>=8,<10
```

`openai`는 실제 OpenAI 호출에만 필요합니다. 오프라인 단위 테스트는 `pydantic`과 `pytest`만 필요합니다.

## 환경변수 (기존 backend/.env.example에 이름만 추가)

```dotenv
OPENAI_API_KEY=                 # 반드시 실제 키를 비공개 환경변수에만 설정
AI_MODEL=                       # 팀이 선정한 Responses API/Structured Outputs 지원 모델 이름
AI_TIMEOUT_SECONDS=30
```

설정하지 않은 `AI_MODEL`과 `OPENAI_API_KEY`는 실제 호출에서 명시적인 설정 오류를 발생시킵니다. `.env`는 SDK가 자동으로 불러오지 않으므로, **기존 `core/config.py`에서 `.env`를 읽어 환경변수로 노출**하거나 서버 실행 전에 환경변수를 설정해 주세요. `.env` 파일 자체는 GitHub에 올리지 마세요.

## 테스트

**`backend/` 폴더에서** 실행하세요:

```bash
python -m pytest tests/test_ai.py -v
```

단위 테스트는 가짜 응답을 이용하므로 네트워크·API 키·PostgreSQL이 필요하지 않습니다.

## 백엔드 2 연결 예시

`backend/`를 작업 디렉터리로 사용할 때:

```python
from ai.recommender import AIConfigurationError, AIUnavailableError, generate_recommendations

# payload: API v02 §5 '백엔드4 함수 입력 JSON'과 동일한 데이터 (goal 기본값은 백엔드2가 채움)
# 트랜잭션을 열지 않은 상태에서 호출
result = await generate_recommendations(payload)
# result == {"recommendations": [{"item_id": ..., "action_type": ..., ...}]}
```

- 입력 검증 오류(`pydantic.ValidationError`)는 **백엔드 2가 전달한 내부 데이터 계약 오류**입니다.
- 설정 오류(`AIConfigurationError`)는 서버 설정 문제입니다.
- AI 모델 호출·출력 오류(`AIUnavailableError`)를 API v02의 `503 AI_UNAVAILABLE`로 변환합니다. 이전 유효 추천은 삭제하지 않습니다.
- 반환된 추천은 백엔드 2가 **실제 품목 여부·수량·대체 품목 변형·버전**을 검증하고, 백엔드 3의 계산 함수로 배출량·비용 변화 및 적용 가능 여부를 채웁니다.
- `recommendations: []`은 **성공**이며, `empty_reason`은 백엔드 2가 판단합니다.
- AI 호출 중 DB 트랜잭션/행 잠금을 유지하지 않습니다.

## 최초 실제 연동 체크

1. `AI_MODEL`/`OPENAI_API_KEY` 설정 (모델은 **Structured Outputs json_schema** 지원 필요).
2. `python -m pytest tests/test_ai.py -v` 통과.
3. 명세서의 샘플과 비슷한 payload로 한 번 실제 모델 호출.
4. 백엔드2의 `/recommend`에서 모듈을 호출해 추천 필드가 채워지는지 확인.
5. 백엔드3의 공통 계산기로 감축량·비용 변화 검증 및 저장.

> 모델은 프롬프트와 출력 스키마를 만족하도록 요청하지만, **실제 대체 품목의 유효성·가격·탄소 감축 가능성까지 보장하지 않습니다.** 해당 최종 검증은 백엔드2·3에서 수행합니다.
