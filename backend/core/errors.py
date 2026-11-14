"""
공통 API 오류 처리 (백엔드2)

명세서 v02 '에러 응답' 기준. 모든 오류는 아래 형식으로 내려갑니다.
    { "error": "INVALID_INPUT", "field": "items[1].width_m", "message": "..." }
"""
import logging
from enum import Enum
from typing import Any, Dict, Optional, Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("api.errors")


class ErrorCode(str, Enum):
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INVALID_INPUT = "INVALID_INPUT"
    NO_ITEMS = "NO_ITEMS"
    UNKNOWN_ITEM = "UNKNOWN_ITEM"
    DUPLICATE_ITEM = "DUPLICATE_ITEM"
    CONFLICTING_RECOMMENDATIONS = "CONFLICTING_RECOMMENDATIONS"
    EVENT_NOT_FOUND = "EVENT_NOT_FOUND"
    SCENARIO_NOT_FOUND = "SCENARIO_NOT_FOUND"
    STALE_DATA = "STALE_DATA"
    CONCURRENT_UPDATE = "CONCURRENT_UPDATE"
    CALC_NOT_AVAILABLE = "CALC_NOT_AVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"


STATUS_BY_CODE: Dict[ErrorCode, int] = {
    ErrorCode.INVALID_QUANTITY: 400,
    ErrorCode.INVALID_INPUT: 400,
    ErrorCode.NO_ITEMS: 400,
    ErrorCode.UNKNOWN_ITEM: 400,
    ErrorCode.DUPLICATE_ITEM: 400,
    ErrorCode.CONFLICTING_RECOMMENDATIONS: 400,
    ErrorCode.EVENT_NOT_FOUND: 404,
    ErrorCode.SCENARIO_NOT_FOUND: 404,
    ErrorCode.STALE_DATA: 409,
    ErrorCode.CONCURRENT_UPDATE: 409,
    ErrorCode.CALC_NOT_AVAILABLE: 422,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.AI_UNAVAILABLE: 503,
}

DEFAULT_MESSAGES: Dict[ErrorCode, str] = {
    ErrorCode.INVALID_QUANTITY: "수량을 확인해 주세요",
    ErrorCode.INVALID_INPUT: "입력값을 확인해 주세요",
    ErrorCode.NO_ITEMS: "품목을 1개 이상 추가해 주세요",
    ErrorCode.UNKNOWN_ITEM: "선택할 수 없는 품목입니다",
    ErrorCode.DUPLICATE_ITEM: "같은 품목이 두 번 이상 들어 있습니다",
    ErrorCode.CONFLICTING_RECOMMENDATIONS: "같은 품목의 추천은 하나만 적용할 수 있습니다",
    ErrorCode.EVENT_NOT_FOUND: "행사를 찾을 수 없습니다",
    ErrorCode.SCENARIO_NOT_FOUND: "시나리오를 찾을 수 없습니다",
    ErrorCode.STALE_DATA: "추천이 바뀌었습니다. 추천을 다시 불러와 주세요",
    ErrorCode.CONCURRENT_UPDATE: "동시에 수정되었습니다. 잠시 후 다시 시도해 주세요",
    ErrorCode.CALC_NOT_AVAILABLE: "계산할 수 없는 품목이 포함되어 있습니다",
    ErrorCode.INTERNAL_ERROR: "서버 오류가 발생했습니다",
    ErrorCode.AI_UNAVAILABLE: "AI 추천을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요",
}


class ApiError(Exception):
    """서비스 코드에서 raise ApiError(ErrorCode.XXX, ...) 로 사용합니다."""

    def __init__(self, code: ErrorCode, message: Optional[str] = None, field: Optional[str] = None):
        self.code = code
        self.message = message or DEFAULT_MESSAGES[code]
        self.field = field
        self.status_code = STATUS_BY_CODE[code]
        super().__init__(self.message)

    def to_body(self) -> Dict[str, Any]:
        return error_body(self.code, self.message, self.field)


def error_body(code: ErrorCode, message: str, field: Optional[str]) -> Dict[str, Any]:
    return {"error": code.value, "field": field, "message": message}


# ---------------------------------------------------------------------------
# DB 오류 → API 오류 변환 (백엔드1 repository 연결 후 사용)
# ---------------------------------------------------------------------------
# PostgreSQL SQLSTATE 코드
SQLSTATE_TO_ERROR: Dict[str, ErrorCode] = {
    "23503": ErrorCode.UNKNOWN_ITEM,       # FK 위반 (없는 item_id)
    "23505": ErrorCode.DUPLICATE_ITEM,     # UNIQUE 위반 (같은 품목 중복)
    "22003": ErrorCode.INVALID_QUANTITY,   # 숫자 범위 초과
    "40P01": ErrorCode.CONCURRENT_UPDATE,  # 교착
    "40001": ErrorCode.CONCURRENT_UPDATE,  # 직렬화 실패
}

# RAISE 의 DETAIL 코드 (백엔드1이 붙여주기로 한 코드. 확정되면 여기에 추가)
DB_DETAIL_TO_ERROR: Dict[str, ErrorCode] = {
    "E_INTEGER_UNIT": ErrorCode.INVALID_QUANTITY,
    "E_STALE_RECOMMENDATION": ErrorCode.STALE_DATA,
    "E_FACTOR_MISMATCH": ErrorCode.INTERNAL_ERROR,  # 서버가 값을 잘못 복사한 것
}


def map_db_error(sqlstate: Optional[str], detail: Optional[str] = None) -> ApiError:
    """DB 예외를 API 오류로 바꿉니다. DETAIL 코드를 SQLSTATE보다 먼저 봅니다."""
    if detail and detail in DB_DETAIL_TO_ERROR:
        return ApiError(DB_DETAIL_TO_ERROR[detail])
    if sqlstate and sqlstate in SQLSTATE_TO_ERROR:
        return ApiError(SQLSTATE_TO_ERROR[sqlstate])
    logger.error("처리되지 않은 DB 오류: sqlstate=%s detail=%s", sqlstate, detail)
    return ApiError(ErrorCode.INTERNAL_ERROR)


# ---------------------------------------------------------------------------
# FastAPI 에러 핸들러 등록
# ---------------------------------------------------------------------------
def _loc_to_field(loc: Sequence[Any]) -> Optional[str]:
    """('body', 'items', 1, 'width_m') → 'items[1].width_m'"""
    field = ""
    for part in loc:
        if part in ("body", "query", "path"):
            continue
        if isinstance(part, int):
            field += f"[{part}]"
        else:
            field += ("." if field else "") + str(part)
    return field or None


def _clean_message(message: str) -> str:
    # pydantic 의 "Value error, ..." 접두어 제거
    for prefix in ("Value error, ", "Assertion failed, "):
        if message.startswith(prefix):
            return message[len(prefix):]
    return message


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_body())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI 기본값(422) 대신 명세서대로 400 + 에러 코드로 내려줍니다.
        errors = exc.errors()
        first = errors[0] if errors else {}
        field = _loc_to_field(first.get("loc", ()))
        code = ErrorCode.INVALID_INPUT
        if field and field.split(".")[-1] == "quantity":
            code = ErrorCode.INVALID_QUANTITY
        message = _clean_message(str(first.get("msg", DEFAULT_MESSAGES[code])))
        return JSONResponse(status_code=STATUS_BY_CODE[code], content=error_body(code, message, field))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("처리되지 않은 서버 오류: %s %s", request.method, request.url.path)
        code = ErrorCode.INTERNAL_ERROR
        return JSONResponse(status_code=STATUS_BY_CODE[code], content=error_body(code, DEFAULT_MESSAGES[code], None))
