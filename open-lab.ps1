param(
    [int]$ApiPort = 8088,
    [int]$RpcPort = 8080,
    [string]$FrontendUrl = 'http://127.0.0.1:15000'
)

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Status($msg) {
    Write-Host "[open-lab] $msg" -ForegroundColor Cyan
}

function Stop-PortUser([int]$port, [string]$label) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { return }
    foreach ($c in $conns) {
        $connPid = $c.OwningProcess
        if (-not $connPid) { continue }
        $proc = Get-Process -Id $connPid -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        Write-Status "Stopping stale $label (PID $connPid, $($proc.ProcessName)) on port $port ..."
        Stop-Process -Id $connPid -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

function Launch-ServiceWindow([string]$title, [string]$command) {
    $escapedCmd = $command -replace '"', '`"'
    $psCmd = "Write-Host '[open-lab] $title window started' -ForegroundColor Cyan; & $escapedCmd; Write-Host ''; Write-Host '[open-lab] $title stopped. Close this window to dismiss.' -ForegroundColor Yellow; Read-Host 'Press Enter to close'"
    Start-Process -FilePath 'powershell' -ArgumentList "-NoExit -NoProfile -Command $psCmd" -WorkingDirectory $Root
}

# --- Ensure ports are free ---
Stop-PortUser -port $ApiPort -label 'analysis API'
Stop-PortUser -port $RpcPort -label 'RPC server'

# --- Backend 1: analysis/lab API server ---
Write-Status "Starting analysis API server on port $ApiPort ..."
Launch-ServiceWindow -title 'Analysis API' -command "pdm run python user_data/scripts/api_server.py --port $ApiPort"

# --- Backend 2: RPC server (via api_server.py) ---
Write-Status "Starting RPC server on port $RpcPort ..."
Launch-ServiceWindow -title 'RPC Server' -command "pdm run python user_data/scripts/api_server.py --port $RpcPort"

# --- Wait for API ---
Write-Status "Waiting for analysis API ..."
$apiReady = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$ApiPort" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $apiReady = $true; break }
    } catch {}
}
if ($apiReady) {
    Write-Status "Analysis API up on http://127.0.0.1:$ApiPort"
} else {
    Write-Host "[open-lab] Analysis API did not respond in time." -ForegroundColor Yellow
}

Write-Status "Waiting for RPC server ..."
$rpcReady = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$RpcPort" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $rpcReady = $true; break }
    } catch {}
}
if ($rpcReady) {
    Write-Status "RPC server up on http://127.0.0.1:$RpcPort"
} else {
    Write-Host "[open-lab] RPC server did not respond in time. Check the terminal window." -ForegroundColor Yellow
}

# --- Frontend ---
Write-Status "Starting frontend dev server ..."
Launch-ServiceWindow -title 'Frontend Dev Server' -command "npm run dev"

# --- Browser ---
Write-Status "Opening browser ..."
Start-Process $FrontendUrl

Write-Host ""
Write-Host "[open-lab] Servers started in separate terminal windows." -ForegroundColor Green
Write-Host "[open-lab] Frontend:  $FrontendUrl" -ForegroundColor Green
Write-Host "[open-lab] API:      http://127.0.0.1:$ApiPort" -ForegroundColor Green
Write-Host "[open-lab] RPC:      http://127.0.0.1:$RpcPort" -ForegroundColor Green
Write-Host "[open-lab] Each service window will stay open until you close it manually." -ForegroundColor Yellow
