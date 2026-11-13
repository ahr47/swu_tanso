"""
FastAPI 실행 (백엔드2)

실행:  uvicorn main:app --reload      (backend 폴더에서)
문서:  http://127.0.0.1:8000/docs
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.errors import register_error_handlers
from routes import analyze, compare, events, items, recommend

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="API 필드명세서 v02 기준. 계산(백엔드3)·AI(백엔드4) 연결 완료, DB 는 services/adapters.py 의 메모리 저장소로 동작합니다.",
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
    }
