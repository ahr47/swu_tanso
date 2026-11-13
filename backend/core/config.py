"""
환경변수·공통 설정 (백엔드2)

.env 파일 또는 환경변수에서 값을 읽습니다. 값이 없으면 아래 기본값을 씁니다.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

# 아직 발급받지 않은 키·주소 자리 표시용 텍스트
PLACEHOLDER_PREFIX = "여기에_"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "탄소줄이슈 API"
    app_env: str = "local"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # 배출계수 버전 (클라이언트는 보내지 않음)
    current_factor_version: str = "v1.0-2026-10"

    # DB (백엔드1). 자리 표시 텍스트 그대로면 메모리 저장소로 동작
    database_url: str = "여기에_DB_연결_주소_입력"
    db_pool_min: int = 1
    db_pool_max: int = 5          # PGlite 소켓 서버는 동시 연결 1개 -> 1
    db_auto_init: bool = True     # 테이블이 없으면 서버 시작 시 schema.sql + seed.sql 실행

    # AI (백엔드4)
    ai_api_key: str = "여기에_AI_API_키_입력"  # OpenAI API 키
    ai_model: str = "gpt-6.1-sol"
    ai_timeout_seconds: float = 30
    ai_max_retries: int = 1
    ai_max_recommendations: int = 5

    @property
    def cors_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def ai_api_key_is_set(self) -> bool:
        """AI API 키가 실제로 입력됐는지 (자리 표시 텍스트면 False)"""
        return bool(self.ai_api_key) and not self.ai_api_key.startswith(PLACEHOLDER_PREFIX)

    @property
    def database_url_is_set(self) -> bool:
        return bool(self.database_url) and not self.database_url.startswith(PLACEHOLDER_PREFIX)


@lru_cache
def get_settings() -> Settings:
    return Settings()
