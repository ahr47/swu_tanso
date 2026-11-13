"""
테스트 공통 설정

- 기본: DB 없이 메모리 저장소로 테스트
- TEST_DATABASE_URL 을 주면 같은 테스트를 실제 PostgreSQL/PGlite 에서 실행
  (테스트 시작 시 DB 를 schema.sql + seed.sql 로 초기화하므로 개발·운영 DB 주소는 넣지 마세요)

    TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5433/postgres?sslmode=disable pytest -q
"""
import os

TEST_DB = os.getenv("TEST_DATABASE_URL")
if TEST_DB:
    os.environ.update({"DATABASE_URL": TEST_DB, "APP_ENV": "test", "DB_POOL_MIN": "1", "DB_POOL_MAX": "1"})


def pytest_configure(config):
    if TEST_DB:
        from db.connection import init_db

        init_db(reset=True)


def pytest_report_header(config):
    return f"storage: {'PostgreSQL (' + TEST_DB.split('@')[-1] + ')' if TEST_DB else 'memory'}"
