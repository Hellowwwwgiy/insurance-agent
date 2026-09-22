$ErrorActionPreference = "Stop"
$Port    = 8080
$DbPort  = 5432
$Root    = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Info($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!!] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  [XX] $m" -ForegroundColor Red }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Insurance Agent - Docker One-Click Up" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# --- 1. Check Docker daemon ---
Write-Host "`n[1/6] Checking Docker daemon..." -ForegroundColor Cyan
try {
    $dockerVer = docker version --format '{{.Server.Version}}' 2>&1
    Info "Docker $dockerVer"
} catch {
    Fail "Docker daemon not running. Please start Docker Desktop first."
    exit 1
}

# --- 2. Check docker compose ---
Write-Host "`n[2/6] Checking docker compose..." -ForegroundColor Cyan
try {
    $compVer = docker compose version 2>&1
    Info $compVer
} catch {
    Fail "docker compose not available. Install Docker Desktop with Compose V2."
    exit 1
}

# --- 3. Check .env (DEEPSEEK_API_KEY required) ---
Write-Host "`n[3/6] Checking .env..." -ForegroundColor Cyan
$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) {
    Warn ".env not found, copying from .env.example..."
    Copy-Item (Join-Path $Root ".env.example") $envFile -Force
    Warn "EDIT $envFile and set DEEPSEEK_API_KEY before re-running."
    # 继续：如果 API Key 没填，容器会起但 LLM 调用会失败，这个比直接退出好体验
}
$apiKey = $null
try {
    foreach ($line in Get-Content $envFile -ErrorAction SilentlyContinue) {
        if ($line -match '^\s*DEEPSEEK_API_KEY\s*=\s*(.+?)\s*$') { $apiKey = $Matches[1].Trim(); break }
    }
} catch {}
if (-not $apiKey -or $apiKey -like "*your-api-key*") {
    Warn "DEEPSEEK_API_KEY not set in .env — container will start but LLM calls will fail."
} else {
    Info "DEEPSEEK_API_KEY set (len=$($apiKey.Length))"
}

# --- 4. Check ports 8080 / 5432 ---
Write-Host "`n[4/6] Checking ports $Port and $DbPort..." -ForegroundColor Cyan
foreach ($p in @($Port, $DbPort)) {
    $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($conn -and $conn.Count -gt 0) {
        $portPid = ($conn | Select-Object -First 1).OwningProcess
        if ($portPid -gt 4) {
            $pc = Get-Process -Id $portPid -ErrorAction SilentlyContinue
            $name = if ($pc) { $pc.ProcessName } else { "unknown" }
            # 如果是 docker-compose 自己上次残留，让 docker compose down 处理
            $isDocker = $false
            try {
                $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$portPid" -EA SilentlyContinue).CommandLine
                if ($cmdLine -match "docker|com.docker") { $isDocker = $true }
            } catch {}
            if ($isDocker) {
                Warn "Port $p used by previous docker container (PID=$portPid), running docker compose down first..."
                docker compose down 2>&1 | Out-Null
                Start-Sleep 3
            } else {
                Fail "Port $p busy by PID=$portPid ($name). Stop it first (run stop.bat if it's the local uvicorn)."
                exit 1
            }
        }
    }
}
Info "Ports $Port and $DbPort free"

# --- 5. Build & start ---
Write-Host "`n[5/6] docker compose up -d --build (may take a few minutes)..." -ForegroundColor Cyan
docker compose up -d --build 2>&1

if ($LASTEXITCODE -ne 0) {
    Fail "docker compose up failed"
    Write-Host "--- logs ---" -ForegroundColor Red
    docker compose logs --tail=50 2>&1
    exit 1
}
Info "Containers started"

# --- 6. Wait for app health (DB init takes time, 60s window) ---
Write-Host "`n[6/6] Waiting for app /health (max 60s, DB seeding first)..." -ForegroundColor Cyan
$ready = $false
for ($i = 1; $i -le 60; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 1000
    Write-Host -NoNewline "  ... ${i}s`r"
}
Write-Host ""

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
docker compose ps 2>&1
Write-Host "============================================================" -ForegroundColor Cyan

if (-not $ready) {
    Warn "App not healthy within 60s — but containers are running. Check logs below:"
    Write-Host ""
    Write-Host "--- docker compose logs ---" -ForegroundColor Yellow
    docker compose logs --tail=30 app 2>&1
    Write-Host ""
} else {
    Info "Service ready!"
    Start-Process "http://localhost:$Port"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  DONE!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "`n  Chat UI:    http://localhost:$Port"
Write-Host "  Metrics:    http://localhost:$Port/metrics"
Write-Host "  API Docs:   http://localhost:$Port/docs"
Write-Host "  DB:         localhost:$DbPort  (user=insurance, db=insurance_db)"
Write-Host ""
Write-Host "  Stop:       docker-down.bat"
Write-Host "  Logs:       docker compose logs -f"
Write-Host ""
