"""DB 연결·트랜잭션 (백엔드1)

- 연결 풀은 서버 시작 시 open_pool(), 종료 시 close_pool()
- transaction(): 한 트랜잭션. 블록 안에서 부르는 저장소 함수는 모두 같은 연결을 씁니다.
- connection(): 트랜잭션 안이면 그 연결을, 밖이면 풀에서 잠깐 빌린 연결을 줍니다.
"""
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from core.config import get_settings

logger = logging.getLogger("db")
SQL_DIR = Path(__file__).parent / "sql"

_pool: Optional[ConnectionPool] = None
_current: ContextVar[Optional[psycopg.Connection]] = ContextVar("db_current_connection", default=None)


def open_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        # prepare_threshold=None: 서버 측 prepared statement 자동 생성 끔.
        # PGlite 는 모든 연결이 세션 하나를 공유해서 이름(_pg3_0)이 겹치는 문제가 있음. PostgreSQL 에서도 무해
        _pool = ConnectionPool(settings.database_url, min_size=settings.db_pool_min, max_size=settings.db_pool_max,
                               kwargs={"row_factory": dict_row, "prepare_threshold": None}, open=True)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    """한 트랜잭션. 예외가 나면 롤백, 정상 종료 시 커밋. 중첩 호출은 바깥 트랜잭션에 합류."""
    current = _current.get()
    if current is not None:
        yield current
        return
    with open_pool().connection() as conn:  # 블록이 끝나면 커밋(예외 시 롤백) 후 풀에 반환
        token = _current.set(conn)
        try:
            yield conn
        finally:
            _current.reset(token)


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    with transaction() as conn:
        yield conn


def in_transaction() -> bool:
    return _current.get() is not None


def run_sql_file(conn: psycopg.Connection, name: str) -> None:
    conn.execute((SQL_DIR / name).read_text(encoding="utf-8"))


def init_db(reset: bool = False) -> bool:
    """테이블이 없거나 reset=True 면 schema.sql + seed.sql 실행. 실행했으면 True"""
    with transaction() as conn:
        exists = conn.execute("SELECT to_regclass('public.items') IS NOT NULL AS ok").fetchone()["ok"]
        if exists and not reset:
            return False
        run_sql_file(conn, "schema.sql")
        run_sql_file(conn, "seed.sql")
    logger.info("DB 초기화 완료 (schema.sql + seed.sql)")
    return True
