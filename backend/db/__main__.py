"""DB 초기화:  python -m db          (테이블이 없을 때만)
           python -m db --reset  (모두 지우고 다시 생성 — 데이터가 사라집니다)"""
import logging
import sys

from core.config import get_settings
from db.connection import close_pool, init_db

logging.basicConfig(level=logging.INFO)
if not get_settings().database_url_is_set:
    sys.exit(".env 의 DATABASE_URL 을 먼저 입력해 주세요")
done = init_db(reset="--reset" in sys.argv)
print("schema.sql + seed.sql 적용 완료" if done else "이미 초기화되어 있습니다. 다시 만들려면 --reset 을 붙이세요")
close_pool()
