$ErrorActionPreference = "Continue"

function Info($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!!] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  [XX] $m" -ForegroundColor Red }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Insurance Agent - Stop All" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$targetPorts = @(8080, 8000, 8081, 8082, 3000, 5173)
$killedAny = $false

# --- 1. Kill by known ports, but ONLY python/uvicorn processes ---
Write-Host "`n[1/3] Scanning common ports for python/uvicorn..." -ForegroundColor Cyan
foreach ($p in $targetPorts) {
    $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $ownPid = $c.OwningProcess
        if ($ownPid -le 4) { continue }  # skip system
        
        $proc = Get-Process -Id $ownPid -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        
        # Only kill python / uvicorn related, skip smartproxy / node / java / etc.
        $safeName = $proc.ProcessName
        $skip = $false
        foreach ($keyword in @("smartproxy", "node", "java", "chrome", "code", "idea", "php", "nginx")) {
            if ($safeName -like "*$keyword*") { $skip = $true; break }
        }
        if ($skip) { continue }
        
        Write-Host "  Killing PID=$ownPid ($safeName) on port $p..."
        Stop-Process -Id $ownPid -Force -ErrorAction SilentlyContinue
        $killedAny = $true
    }
}

if (-not $killedAny) {
    Info "No matching listeners found on common ports"
}

# --- 2. Kill all python processes whose command line contains uvicorn/agent.api ---
Write-Host "`n[2/3] Scanning python processes for uvicorn/agent.api..." -ForegroundColor Cyan
$pyProcs = Get-Process python -ErrorAction SilentlyContinue
$found = $false
foreach ($pp in $pyProcs) {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($pp.Id)" -ErrorAction SilentlyContinue).CommandLine
    } catch { $cmdLine = "" }
    if ($cmdLine -and ($cmdLine -match "uvicorn" -or $cmdLine -match "agent\.api")) {
        Write-Host "  Killing PID=$($pp.Id) ($($pp.ProcessName))"
        Stop-Process -Id $pp.Id -Force -ErrorAction SilentlyContinue
        $found = $true
        $killedAny = $true
    }
}
if (-not $found) {
    Info "No leftover python/uvicorn processes"
}

# --- 3. Wait + verify all target ports are now free ---
Write-Host "`n[3/3] Waiting 3s for ports to release..." -ForegroundColor Cyan
Start-Sleep -Seconds 3

Write-Host ""
Write-Host "  Port  Status" -ForegroundColor DarkGray
Write-Host "  ----  ------" -ForegroundColor DarkGray
$allFree = $true
foreach ($p in $targetPorts) {
    $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        $ownPid = ($conns | Select-Object -First 1).OwningProcess
        $proc = Get-Process -Id $ownPid -ErrorAction SilentlyContinue
        $procName = if ($proc) { $proc.ProcessName } else { "unknown" }
        Write-Host "  $p     BUSY (PID=$ownPid, $procName)" -ForegroundColor Yellow
        $allFree = $false
    } else {
        Write-Host "  $p     free" -ForegroundColor Green
    }
}

Write-Host ""
if ($allFree) {
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  All ports released. Done." -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
} else {
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host "  Some ports still BUSY (may be other apps). Done." -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Yellow
}
Write-Host ""
