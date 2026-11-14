# 탄소줄이슈 로컬 실행 (Windows) — start.bat 을 더블클릭하면 이 파일이 실행됩니다.
#   직접 실행: powershell -ExecutionPolicy Bypass -File run.ps1
#   종료: 이 창에서 Ctrl+C (또는 창 닫기)
# 처음 한 번은 파이썬 패키지와 DB 프로그램(PGlite)을 내려받느라 1~2분 걸립니다 (인터넷 필요).
# 데이터는 backend\pgdata 에 저장되어 다시 켜도 남아 있습니다. 초기화하려면 그 폴더를 지우세요.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$ApiPort = if ($env:API_PORT) { [int]$env:API_PORT } else { 8000 }
$DbPort = if ($env:DB_PORT) { [int]$env:DB_PORT } else { 54329 }   # 이미 설치된 PostgreSQL(5432)과 겹치지 않게
$PgliteVersion = '0.2.19'                                             # @electric-sql/pglite-socket (검증한 버전)
$Url = "http://127.0.0.1:$ApiPort"

function Say($Message) { Write-Host "`n> $Message" -ForegroundColor Green }
function Fail($Message) {
    Write-Host "`n[오류] $Message" -ForegroundColor Red
    exit 1
}
function Test-Port($Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { $client.Connect('127.0.0.1', $Port); return $true } catch { return $false } finally { $client.Close() }
}

# --- 1. 준비물 확인 -------------------------------------------------------------
$PyExe = $null; $PyArgs = @()
foreach ($candidate in @('py -3.13', 'py -3.12', 'py -3.11', 'py -3.10', 'python', 'python3')) {
    $parts = $candidate -split ' '
    $exe = $parts[0]; $rest = @($parts | Select-Object -Skip 1)
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    try { & $exe @rest -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null } catch { continue }
    if ($LASTEXITCODE -eq 0) { $PyExe = $exe; $PyArgs = $rest; break }
}
if (-not $PyExe) { Fail 'Python 3.10 이상이 필요합니다. https://www.python.org/downloads/ 에서 설치하고, 설치 화면의 "Add python.exe to PATH" 를 꼭 체크하세요.' }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail 'Node.js 20 이상이 필요합니다. https://nodejs.org 에서 LTS 버전을 설치하세요.' }
node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 20 ? 0 : 1)"
if ($LASTEXITCODE -ne 0) { Fail "Node.js 20 이상이 필요합니다 (현재 $(node --version)). https://nodejs.org 에서 LTS 버전을 설치하세요." }
if (Test-Port $ApiPort) { Fail "$ApiPort 포트를 이미 다른 프로그램이 쓰고 있습니다. 켜 둔 서버 창을 닫고 다시 실행하세요." }

# --- 2. 파이썬 가상환경·패키지 (requirements.txt 가 바뀔 때만 다시 설치) ----------------
$Venv = Join-Path $Backend '.venv'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $VenvPy)) {
    Say '파이썬 가상환경 만드는 중'
    & $PyExe @PyArgs -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail '파이썬 가상환경을 만들지 못했습니다.' }
}
$Req = Join-Path $Backend 'requirements.txt'
$HashFile = Join-Path $Venv '.requirements-hash'
$ReqHash = (Get-FileHash $Req -Algorithm SHA256).Hash
$OldHash = if (Test-Path $HashFile) { (Get-Content $HashFile -Raw).Trim() } else { '' }
if ($OldHash -ne $ReqHash) {
    Say '파이썬 패키지 설치 중 (처음 한 번)'
    & $VenvPy -m pip install --quiet --upgrade pip
    & $VenvPy -m pip install --quiet -r $Req
    if ($LASTEXITCODE -ne 0) { Fail '파이썬 패키지를 설치하지 못했습니다. 인터넷 연결을 확인하세요.' }
    Set-Content -Path $HashFile -Value $ReqHash -Encoding ASCII
}

# --- 3. 설정 파일 (.env 가 없으면 예시에서 복사. AI 키는 여기에 직접 입력) ---------------
$EnvFile = Join-Path $Backend '.env'
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Backend '.env.example') $EnvFile
    Say 'backend\.env 를 만들었습니다 (AI 추천을 쓰려면 AI_API_KEY 에 OpenAI 키를 넣으세요)'
}

# --- 4. 화면 데이터 빌드 ------------------------------------------------------------
Say '화면 준비 중'
Push-Location $Frontend
try { node scripts/build.mjs | Out-Null } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { Fail '화면 파일을 만들지 못했습니다.' }

# --- 5. DB 프로그램 설치 (처음 한 번) -------------------------------------------------
$PgliteDir = Join-Path $Backend '.pglite'
$PgliteVersionFile = Join-Path $PgliteDir '.version'
$PgliteRel = '.pglite/node_modules/@electric-sql/pglite-socket/dist/scripts/server.js'
$OldPglite = if (Test-Path $PgliteVersionFile) { (Get-Content $PgliteVersionFile -Raw).Trim() } else { '' }
if ($OldPglite -ne $PgliteVersion -or -not (Test-Path (Join-Path $Backend $PgliteRel))) {
    Say 'DB 프로그램(PGlite) 설치 중 (처음 한 번)'
    New-Item -ItemType Directory -Force -Path $PgliteDir | Out-Null
    npm install --silent --no-audit --no-fund --prefix "$PgliteDir" "@electric-sql/pglite-socket@$PgliteVersion"
    if ($LASTEXITCODE -ne 0) { Fail 'PGlite 를 설치하지 못했습니다. 인터넷 연결을 확인하세요.' }
    Set-Content -Path $PgliteVersionFile -Value $PgliteVersion -Encoding ASCII
}
if (Test-Port $DbPort) { Fail "DB 포트 $DbPort 를 이미 쓰고 있습니다. 이전에 켠 서버 창을 모두 닫고 다시 실행하세요." }

$Db = $null; $Api = $null
try {
    # --- 6. DB 켜기 (경로에 공백·한글이 있어도 되게 backend 폴더 기준 상대 경로 사용) -------
    Say 'DB 켜는 중'
    New-Item -ItemType Directory -Force -Path (Join-Path $Backend 'pgdata') | Out-Null
    $Db = Start-Process -FilePath 'node' -ArgumentList @($PgliteRel, '--db=./pgdata', "--port=$DbPort", '--host=127.0.0.1') `
        -WorkingDirectory $Backend -NoNewWindow -PassThru `
        -RedirectStandardOutput (Join-Path $Backend 'pgdata.log') -RedirectStandardError (Join-Path $Backend 'pgdata.err.log')
    $ready = $false
    for ($i = 0; $i -lt 180; $i++) {
        if (Test-Port $DbPort) { $ready = $true; break }
        if ($Db.HasExited) { Fail 'DB 를 켜지 못했습니다. backend\pgdata.err.log 를 확인하세요.' }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { Fail 'DB 가 3분 안에 켜지지 않았습니다. backend\pgdata.err.log 를 확인하세요.' }

    # --- 7. 백엔드(+화면) 켜기 -----------------------------------------------------------
    Say '서버 켜는 중'
    $env:DATABASE_URL = "postgresql://postgres@127.0.0.1:$DbPort/postgres?sslmode=disable"
    $env:DB_POOL_MIN = '1'; $env:DB_POOL_MAX = '1'   # PGlite 는 동시 연결 1개
    $env:PYTHONUTF8 = '1'
    $Api = Start-Process -FilePath $VenvPy `
        -ArgumentList @('-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', "$ApiPort", '--log-level', 'warning') `
        -WorkingDirectory $Backend -NoNewWindow -PassThru
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Port $ApiPort) { $ready = $true; break }
        if ($Api.HasExited) { Fail '서버를 켜지 못했습니다. 위 오류 메시지를 확인하세요.' }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { Fail '서버가 1분 안에 켜지지 않았습니다.' }

    Write-Host "`n실행 중입니다" -ForegroundColor Green
    Write-Host "  화면     $Url"
    Write-Host "  API 문서 $Url/docs"
    Write-Host "  종료     이 창에서 Ctrl+C (또는 창 닫기)`n"
    try { Start-Process $Url } catch { Write-Host "브라우저에서 $Url 을 직접 열어주세요." }

    while (-not $Api.HasExited) { Start-Sleep -Seconds 1 }
}
finally {
    Write-Host "`n종료하는 중..."
    foreach ($p in @($Api, $Db)) {
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
    Write-Host '종료했습니다.'
}
