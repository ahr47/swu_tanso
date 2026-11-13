"""
FastAPI 실행 (백엔드2)

실행:  uvicorn main:app --reload      (backend 폴더에서)
문서:  http://127.0.0.1:8000/docs
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.errors import register_error_handlers
from db import connection as db
from routes import analyze, compare, events, items, recommend

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """DATABASE_URL 이 있으면 연결 풀을 열고, 테이블이 없으면 schema.sql + seed.sql 실행"""
    if settings.database_url_is_set:
        db.open_pool()
        if settings.db_auto_init:
            db.init_db()
    yield
    db.close_pool()


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="API 필드명세서 v02 기준. DATABASE_URL 이 비어 있으면 메모리 저장소로 동작합니다.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

for module in (items, events, analyze, recommend, compare):
    app.include_router(module.router, prefix="/api")


@app.get("/health", tags=["0. 상태 확인"], summary="서버 상태 확인")
def health():
    return {
        "status": "ok",
        "factor_version": settings.current_factor_version,
        "ai_api_key_set": settings.ai_api_key_is_set,
        "database_url_set": settings.database_url_is_set,
        "database": _database_status(),
    }


def _database_status() -> str:
    if not settings.database_url_is_set:
        return "memory"
    try:
        with db.connection() as conn:
            conn.execute("SELECT 1")
        return "ok"
    except Exception:  # noqa: BLE001
        logging.getLogger("db").exception("DB 연결 확인 실패")
        return "error"
