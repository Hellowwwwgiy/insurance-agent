$ErrorActionPreference = "Stop"
$Port = 8080
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Info($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!!] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  [XX] $m" -ForegroundColor Red }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Insurance Agent - One-Click Launcher" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# --- 1. Check Python ---
Write-Host "`n[1/5] Checking Python..." -ForegroundColor Cyan
try {
    $pyVer = python --version 2>&1
    Info "Python $pyVer"
} catch {
    Fail "Python not found in PATH"
    exit 1
}

# --- 2. Check port ---
Write-Host "`n[2/5] Checking port $Port..." -ForegroundColor Cyan
$conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($conn) {
    $portPid = ($conn | Select-Object -First 1).OwningProcess
    $pc = Get-Process -Id $portPid -ErrorAction SilentlyContinue
    if ($pc) {
        Warn "Port $Port used by PID=$portPid ($($pc.ProcessName)), killing..."
        Stop-Process -Id $portPid -Force
        Start-Sleep -Seconds 2
    }
}
Info "Port $Port free"

# --- 3. Start uvicorn ---
Write-Host "`n[3/5] Starting uvicorn agent.api:app..." -ForegroundColor Cyan
$outLog = Join-Path $Root ".uvicorn.out.log"
$errLog = Join-Path $Root ".uvicorn.err.log"
if (Test-Path $outLog) { Remove-Item $outLog -Force }
if (Test-Path $errLog) { Remove-Item $errLog -Force }

$uvicornProc = Start-Process -FilePath python `
    -ArgumentList "-m","uvicorn","agent.api:app","--host","0.0.0.0","--port","$Port" `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
    -PassThru

Info "Uvicorn PID=$($uvicornProc.Id)"

# --- 4. Wait for health ---
Write-Host "`n[4/5] Waiting for /health (max 30s)..." -ForegroundColor Cyan
$ready = $false
for ($i = 1; $i -le 30; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
    Write-Host -NoNewline "  ... $i`r"
}
Write-Host ""

if (-not $ready) {
    Fail "Service failed to start within 30s"
    Write-Host "--- STDOUT ---" -ForegroundColor Red
    if (Test-Path $outLog) { Get-Content $outLog -Tail 20 }
    Write-Host "--- STDERR ---" -ForegroundColor Red
    if (Test-Path $errLog) { Get-Content $errLog -Tail 20 }
    exit 1
}
Info "Service ready!"

# --- 5. Open browser ---
Write-Host "`n[5/5] Opening browser..." -ForegroundColor Cyan
Start-Process "http://localhost:$Port"
Start-Sleep -Milliseconds 300
Start-Process "http://localhost:$Port/metrics"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  DONE!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "`n  Chat UI:    http://localhost:$Port"
Write-Host "  Metrics:    http://localhost:$Port/metrics"
Write-Host "  PID:        $($uvicornProc.Id)"
Write-Host "`n  Press Ctrl+C to stop, or run stop.bat" -ForegroundColor DarkGray
Write-Host ""

# --- Block until Ctrl+C ---
try {
    while ($true) {
        Start-Sleep -Seconds 1
        if ($uvicornProc.HasExited) {
            Warn "Uvicorn exited (code=$($uvicornProc.ExitCode))"
            break
        }
    }
} finally {
    if (-not $uvicornProc.HasExited) {
        Stop-Process -Id $uvicornProc.Id -Force -ErrorAction SilentlyContinue
    }
    Info "Stopped."
}
