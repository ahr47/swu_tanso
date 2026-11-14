#!/usr/bin/env bash
# 탄소줄이슈 로컬 실행 — 명령 하나로 DB + 백엔드 + 화면을 켭니다.
#
#   ./run.sh            실행 (브라우저가 자동으로 열림)
#   Ctrl+C              종료 (DB·서버 모두 꺼짐)
#
# 처음 한 번은 파이썬 패키지와 DB 프로그램(PGlite)을 내려받느라 1~2분 걸립니다 (인터넷 필요).
# 데이터는 backend/pgdata/ 에 저장되어 다시 켜도 남아 있습니다. 초기화하려면 그 폴더를 지우세요.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
API_PORT="${API_PORT:-8000}"
DB_PORT="${DB_PORT:-54329}"            # 이미 설치된 PostgreSQL(5432)과 겹치지 않게
PGLITE_VERSION="0.2.19"                 # @electric-sql/pglite-socket (검증한 버전)
PGLITE_DIR="$BACKEND/.pglite"
URL="http://127.0.0.1:$API_PORT"

say() { printf '\n\033[1;32m▶ %s\033[0m\n' "$1"; }
fail() { printf '\n\033[1;31m✖ %s\033[0m\n' "$1"; exit 1; }

port_open() {  # 포트가 열려 있으면 성공
  "$PYTHON" - "$1" <<'EOF'
import socket, sys
s = socket.socket()
s.settimeout(0.5)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
EOF
}

# --- 1. 준비물 확인 -----------------------------------------------------------
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PYTHON="$(command -v "$candidate")"
    break
  fi
done
[ -n "$PYTHON" ] || fail "Python 3.10 이상이 필요합니다. 맥: brew install python@3.12"
command -v node >/dev/null 2>&1 || fail "Node.js 20 이상이 필요합니다. 맥: brew install node"
node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' ||
  fail "Node.js 20 이상이 필요합니다 (현재 $(node --version)). 맥: brew upgrade node"
port_open "$API_PORT" && fail "$API_PORT 포트를 이미 다른 프로그램이 쓰고 있습니다. 켜 둔 서버를 끄거나 API_PORT=8001 ./run.sh 로 실행하세요."

# --- 2. 파이썬 가상환경·패키지 (requirements.txt 가 바뀔 때만 다시 설치) -------------
VENV="$BACKEND/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  say "파이썬 가상환경 만드는 중"
  "$PYTHON" -m venv "$VENV"
fi
REQ_HASH="$("$VENV/bin/python" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$BACKEND/requirements.txt")"
if [ "$(cat "$VENV/.requirements-hash" 2>/dev/null || true)" != "$REQ_HASH" ]; then
  say "파이썬 패키지 설치 중 (처음 한 번)"
  "$VENV/bin/python" -m pip install --quiet --upgrade pip
  "$VENV/bin/python" -m pip install --quiet -r "$BACKEND/requirements.txt"
  echo "$REQ_HASH" > "$VENV/.requirements-hash"
fi
PYTHON="$VENV/bin/python"

# --- 3. 설정 파일 (.env 가 없으면 예시에서 복사. AI 키는 여기에 직접 입력) -------------
if [ ! -f "$BACKEND/.env" ]; then
  cp "$BACKEND/.env.example" "$BACKEND/.env"
  say "backend/.env 를 만들었습니다 (AI 추천을 쓰려면 AI_API_KEY 에 OpenAI 키를 넣으세요)"
fi

# --- 4. 화면 데이터 빌드 ------------------------------------------------------------
say "화면 준비 중"
(cd "$FRONTEND" && node scripts/build.mjs >/dev/null)

# --- 5. DB 켜기 ---------------------------------------------------------------------
PIDS=()
cleanup() {
  trap - EXIT INT TERM HUP
  printf '\n종료하는 중...\n'
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "종료했습니다."
}
trap cleanup EXIT INT TERM HUP

if port_open "$DB_PORT"; then
  fail "DB 포트 $DB_PORT 를 이미 쓰고 있습니다. 이전 실행이 남아 있으면 터미널을 닫았다 다시 열거나 DB_PORT=54330 ./run.sh 로 실행하세요."
fi
PGLITE_BIN="$PGLITE_DIR/node_modules/@electric-sql/pglite-socket/dist/scripts/server.js"
if [ "$(cat "$PGLITE_DIR/.version" 2>/dev/null || true)" != "$PGLITE_VERSION" ] || [ ! -f "$PGLITE_BIN" ]; then
  say "DB 프로그램(PGlite) 설치 중 (처음 한 번)"
  mkdir -p "$PGLITE_DIR"
  npm install --silent --no-audit --no-fund --prefix "$PGLITE_DIR" "@electric-sql/pglite-socket@$PGLITE_VERSION" ||
    fail "PGlite 를 설치하지 못했습니다. 인터넷 연결을 확인하세요."
  echo "$PGLITE_VERSION" > "$PGLITE_DIR/.version"
fi
say "DB 켜는 중"
mkdir -p "$BACKEND/pgdata"
# node 를 직접 실행해야 종료할 때 DB 프로세스까지 확실히 꺼짐 (npx 를 쓰면 자식 프로세스가 남음)
node "$PGLITE_BIN" --db="$BACKEND/pgdata" --port="$DB_PORT" --host=127.0.0.1 > "$BACKEND/pgdata.log" 2>&1 &
PIDS+=("$!")
for _ in $(seq 1 180); do
  port_open "$DB_PORT" && break
  kill -0 "${PIDS[0]}" 2>/dev/null || fail "DB 를 켜지 못했습니다. backend/pgdata.log 를 확인하세요."
  sleep 1
done
port_open "$DB_PORT" || fail "DB 가 3분 안에 켜지지 않았습니다. backend/pgdata.log 를 확인하세요."

# --- 6. 백엔드(+화면) 켜기 -------------------------------------------------------------
say "서버 켜는 중"
export DATABASE_URL="postgresql://postgres@127.0.0.1:$DB_PORT/postgres?sslmode=disable"
export DB_POOL_MIN=1 DB_POOL_MAX=1      # PGlite 는 동시 연결 1개
(cd "$BACKEND" && exec "$PYTHON" -m uvicorn main:app --host 127.0.0.1 --port "$API_PORT" --log-level warning) &
PIDS+=("$!")
for _ in $(seq 1 60); do
  port_open "$API_PORT" && break
  kill -0 "${PIDS[1]}" 2>/dev/null || fail "서버를 켜지 못했습니다. 위 오류 메시지를 확인하세요."
  sleep 1
done
port_open "$API_PORT" || fail "서버가 1분 안에 켜지지 않았습니다."

printf '\n\033[1;32m✔ 실행 중입니다\033[0m\n'
printf '  화면     %s\n' "$URL"
printf '  API 문서 %s/docs\n' "$URL"
printf '  종료     이 창에서 Ctrl+C\n\n'
# 브라우저 자동 열기 (실패해도 서버는 계속 실행. 안 열리면 위 주소를 직접 여세요)
if [ "$(uname)" = "Darwin" ]; then open "$URL" || true
elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true; fi

wait "${PIDS[1]}"
