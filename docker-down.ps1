$ErrorActionPreference = "Continue"

function Info($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!!] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  [XX] $m" -ForegroundColor Red }

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Insurance Agent - Docker One-Click Down" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# --- 1. Check docker compose available ---
Write-Host "`n[1/3] Checking docker compose..." -ForegroundColor Cyan
try {
    docker compose version 2>&1 | Out-Null
} catch {
    Fail "docker compose not available"
    exit 1
}
Info "docker compose ready"

# --- 2. docker compose down ---
Write-Host "`n[2/3] docker compose down..." -ForegroundColor Cyan
$clean = $args -contains "--clean" -or $args -contains "-c"
if ($clean) {
    Warn "--clean mode: removing volumes too (DB data will be lost)"
    docker compose down -v --remove-orphans 2>&1
} else {
    docker compose down --remove-orphans 2>&1
}

if ($LASTEXITCODE -ne 0) {
    Warn "docker compose down returned non-zero (may already be stopped)"
} else {
    Info "Containers stopped"
}

# --- 3. Verify ports ---
Write-Host "`n[3/3] Verifying ports 8080 / 5432..." -ForegroundColor Cyan
Start-Sleep -Seconds 2
$allFree = $true
foreach ($p in @(8080, 5432)) {
    $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        Write-Host "  Port $p still BUSY (may be local uvicorn — run stop.bat too)" -ForegroundColor Yellow
        $allFree = $false
    } else {
        Write-Host "  Port $p free" -ForegroundColor Green
    }
}

Write-Host ""
if ($clean) {
    Info "All containers + volumes removed."
} else {
    Info "All containers stopped. Volumes kept (DB data preserved)."
    Write-Host "  Tip: docker-down.bat --clean  to also remove volumes" -ForegroundColor DarkGray
}
Write-Host ""
