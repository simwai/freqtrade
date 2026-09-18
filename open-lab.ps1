param(
    [int]$ApiPort = 8088,
    [int]$RpcPort = 8080,
    [string]$FrontendUrl = 'http://127.0.0.1:15000'
)

# --- Self-elevate to admin ---
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    try {
        Start-Process -FilePath 'powershell' -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -ApiPort $ApiPort -RpcPort $RpcPort -FrontendUrl `"$FrontendUrl`"" -Verb RunAs
        exit
    } catch {
        Write-Host "[open-lab] Admin elevation failed. Restart the script as Administrator." -ForegroundColor Red
        exit 1
    }
}

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Status($msg) {
    Write-Host "[open-lab] $msg" -ForegroundColor Cyan
}

function Stop-PortUser([int]$port, [string]$label) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { return }
    foreach ($c in $conns) {
        $pid = $c.OwningProcess
        if (-not $pid) { continue }
        $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        Write-Status "Stopping stale $label (PID $pid, $($proc.ProcessName)) on port $port ..."
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

# --- Ensure ports are free ---
Stop-PortUser -port $ApiPort -label 'analysis API'
Stop-PortUser -port $RpcPort -label 'RPC server'

# --- Backend 1: analysis/lab API server ---
Write-Status "Starting analysis API server on port $ApiPort ..."
Start-Process -FilePath 'python' -ArgumentList "user_data/scripts/api_server.py --port $ApiPort" -WorkingDirectory $Root

# --- Backend 2: freqtrade RPC/webserver ---
Write-Status "Starting RPC server on port $RpcPort ..."
$rpcProc = Start-Process -FilePath 'freqtrade' -ArgumentList "webserver --port $RpcPort" -WorkingDirectory $Root -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 3
if (-not $rpcProc -or $rpcProc.HasExited) {
    Write-Host "[open-lab] Failed to start RPC server via 'freqtrade webserver'. Trying 'python -m freqtrade webserver' ..." -ForegroundColor Yellow
    $rpcProc = Start-Process -FilePath 'python' -ArgumentList "-m freqtrade webserver --port $RpcPort" -WorkingDirectory $Root -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

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
Start-Process -FilePath 'cmd' -ArgumentList '/c', 'npm run dev' -WorkingDirectory $Root

# --- Browser ---
Write-Status "Opening browser ..."
Start-Process $FrontendUrl

Write-Host ""
Write-Host "[open-lab] Servers started in separate terminal windows." -ForegroundColor Green
Write-Host "[open-lab] Frontend:  $FrontendUrl" -ForegroundColor Green
Write-Host "[open-lab] API:      http://127.0.0.1:$ApiPort" -ForegroundColor Green
Write-Host "[open-lab] RPC:      http://127.0.0.1:$RpcPort" -ForegroundColor Green
Write-Host "[open-lab] Close this window when done." -ForegroundColor Yellow
