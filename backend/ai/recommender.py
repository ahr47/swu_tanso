"""OpenAI Responses API 참고 구현 (API 제공업체가 다르면 이 파일의 어댑터 교체).

백엔드2 계약:
    result = await generate_recommendations(payload)
    # result == {'recommendations': [...]} (v02에서 AI가 생성하는 9개 필드만)

- DB 접근/탄소 계산/추천 저장/HTTP 오류 응답 생성은 하지 않습니다.
- AI 호출은 트랜잭션 밖에서 이루어져야 합니다.
- 1회 재시도(총 2회), 기본 요청 제한 30초; SDK 자동 재시도는 끕니다.
"""

import os
from typing import Any

from pydantic import ValidationError

from .parser import AIOutputFormatError, parse_ai_output
from .prompt import SYSTEM_INSTRUCTIONS, build_user_message
from .schemas import AIInput


class AIConfigurationError(RuntimeError):
    """필수 AI 모델/API 설정 누락."""


class AIUnavailableError(RuntimeError):
    """호출·시간초과·출력 오류로 추천을 만들 수 없음 (API에서는 AI_UNAVAILABLE/503)."""


# Structured Outputs의 strict 모드가 지원하는 단순 JSON Schema 사용.
# 조건부 규칙(수량 감축/품목 교체 구분)은 parser.py/Pydantic으로 추가 검증.
AI_OUTPUT_FORMAT = {
    "type": "json_schema",
    "name": "carbon_recommendations_v02",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string"},
                        "action_type": {"type": "string", "enum": ["reduce_quantity", "replace_item"]},
                        "target_field": {"type": "string", "enum": ["quantity", "item_id"]},
                        "recommended_value": {"type": ["integer", "null"]},
                        "alternative_item_id": {"type": ["string", "null"]},
                        "alternative_variant": {"type": ["string", "null"]},
                        "title": {"type": "string"},
                        "difficulty": {"type": "string", "enum": ["쉬움", "보통", "어려움"]},
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "item_id", "action_type", "target_field", "recommended_value",
                        "alternative_item_id", "alternative_variant", "title", "difficulty", "reason",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["recommendations"],
        "additionalProperties": False,
    },
}


def _new_openai_client() -> Any:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AIConfigurationError("OPENAI_API_KEY가 설정되지 않았습니다")
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise AIConfigurationError("openai Python SDK를 설치해야 합니다") from exc
    return AsyncOpenAI(api_key=api_key, max_retries=0)


async def generate_recommendations(
    payload: dict[str, Any],
    *,
    client: Any | None = None,
    model: str | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """v02 백엔드4 입력 -> v02 백엔드4 출력 (async).

    payload가 잘못된 경우 ValidationError (호출자/계약 오류),
    설정 누락 시 AIConfigurationError, 모델/출력 오류 시 AIUnavailableError.
    client 주입으로 네트워크 없는 단위 테스트 가능.
    """
    data = AIInput.model_validate(payload)  # 잘못된 내부 입력은 재시도하지 않음

    selected_model = (model or os.getenv("AI_MODEL", "")).strip()
    if not selected_model:
        raise AIConfigurationError("AI_MODEL 환경변수에 사용할 모델명을 지정해 주세요")
    try:
        timeout = float(timeout_seconds if timeout_seconds is not None else os.getenv("AI_TIMEOUT_SECONDS", "30"))
    except (TypeError, ValueError) as exc:
        raise AIConfigurationError("AI_TIMEOUT_SECONDS는 양의 숫자여야 합니다") from exc
    if not 0 < timeout <= 300:
        raise AIConfigurationError("AI_TIMEOUT_SECONDS는 0 초과 300 이하로 설정해 주세요")

    if client is None:
        client = _new_openai_client()

    user_message = build_user_message(data)
    last_error: Exception | None = None
    for attempt in range(2):  # v02: 최대 1회 직접 재시도
        try:
            response = await client.responses.create(
                model=selected_model,
                instructions=SYSTEM_INSTRUCTIONS,
                input=user_message,
                text={"format": AI_OUTPUT_FORMAT},
                timeout=timeout,
            )
            parsed = parse_ai_output(
                response.output_text,
                max_recommendations=data.constraints.max_recommendations,
            )
            return parsed.model_dump(mode="json")
        except Exception as exc:  # SDK 오류/타임아웃/AI JSON 오류를 1회 재시도
            last_error = exc
            if attempt == 1:
                break

    # 원본 오류/응답에 API 키나 개인정보가 포함될 수 있으니 메시지에 넣지 않는다.
    raise AIUnavailableError("AI 추천 생성에 실패했습니다 (1회 재시도 후)") from last_error
