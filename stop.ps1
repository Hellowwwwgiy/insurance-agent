$ErrorActionPreference = "Continue"

function Info($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!!] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  [XX] $m" -ForegroundColor Red }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Insurance Agent - Stop All" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# --- 1. Kill by known ports ---
Write-Host "`n[1/3] Killing listeners on common ports..." -ForegroundColor Cyan
$targetPorts = @(8080, 8000, 8081, 8082, 3000, 5173)
foreach ($p in $targetPorts) {
    $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $ownPid = $c.OwningProcess
        if ($ownPid -gt 4) {
            $proc = Get-Process -Id $ownPid -ErrorAction SilentlyContinue
            $procName = if ($proc) { $proc.ProcessName } else { "unknown" }
            Write-Host "  Killing PID=$ownPid ($procName) on port $p..."
            Stop-Process -Id $ownPid -Force -ErrorAction SilentlyContinue
        }
    }
}

# --- 2. Kill all python/uvicorn processes (safety net) ---
Write-Host "`n[2/3] Killing leftover python/uvicorn processes..." -ForegroundColor Cyan
$pyProcs = Get-Process python -ErrorAction SilentlyContinue
$found = $false
foreach ($pp in $pyProcs) {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($pp.Id)" -ErrorAction SilentlyContinue).CommandLine
    } catch { $cmdLine = "" }
    if ($cmdLine -and ($cmdLine -match "uvicorn" -or $cmdLine -match "agent.api")) {
        Write-Host "  Killing PID=$($pp.Id) ($($pp.ProcessName))"
        Stop-Process -Id $pp.Id -Force -ErrorAction SilentlyContinue
        $found = $true
    }
}
if (-not $found) {
    Info "No matching python/uvicorn processes found"
}

# --- 3. Wait + verify ports free ---
Write-Host "`n[3/3] Waiting for ports to release..." -ForegroundColor Cyan
Start-Sleep -Seconds 3

Write-Host ""
Write-Host "  Port  Status" -ForegroundColor DarkGray
Write-Host "  ----  ------" -ForegroundColor DarkGray
foreach ($p in $targetPorts) {
    $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        $ownPid = ($conns | Select-Object -First 1).OwningProcess
        Write-Host "  $p     BUSY (PID=$ownPid)" -ForegroundColor Yellow
    } else {
        Write-Host "  $p     free" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  All done." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
