"""AI 문자열 응답의 JSON/Pydantic 형식 검증. DB/계수/단가 유효성 검사는 하지 않음."""

import json
from pydantic import ValidationError

from .schemas import AIOutput


class AIOutputFormatError(ValueError):
    """AI가 v02 JSON 계약을 지키지 않았다는 의미."""


def parse_ai_output(raw: str, *, max_recommendations: int = 5) -> AIOutput:
    if not isinstance(raw, str) or not raw.strip():
        raise AIOutputFormatError("AI 응답이 비어 있습니다")
    try:
        result = AIOutput.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise AIOutputFormatError("AI 응답이 v02 JSON 형식과 일치하지 않습니다") from exc
    if len(result.recommendations) > max_recommendations:
        raise AIOutputFormatError("허용된 추천 개수를 초과했습니다")
    return result
