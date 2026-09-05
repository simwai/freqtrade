#!/usr/bin/env pwsh
# Sequential hyperopt + backtest runner for the 5 combo strategies.
#
# Runs hyperopt then a backtest with the best params (no overwrite of existing
# hyperopt results) per strategy, in this order:
#   1. ScreenerRank1RocVixAdLondon
#   2. ScreenerRank4RsiChopPvtNy
#   3. ScreenerDpoBbwpWick
#   4. ScreenerDpoEveningStar
#   5. ScreenerDpoShootingStar
#
# Each phase writes a timestamped log under user_data/hyperopt_logs/<strategy>/.
# Resumable: skip strategies whose BACKTEST_DONE marker is present.
#
# Hyperopt params (tuned for an overnight run, ~3-4h total):
#   -e 50            : 50 epochs (enough to converge on 6-12 hyperoptable params
#                      on a 1-month slice; 200 was infeasible in the current
#                      freqtrade backtest architecture because each epoch runs
#                      populate_indicators on the full pre-timerange frame
#                      per pair)
#   --spaces buy sell: optimize entry thresholds and SL/TP
#   --hyperopt-loss ShortTradeDurHyperOptLoss: balanced trade-frequency objective
#   -j -1            : use all CPU cores
#
# Backtest:
#   Uses the best epoch from the hyperopt result file and runs a single backtest
#   for sanity (writes to user_data/backtest_results/<strategy>-<ts>/).

$ErrorActionPreference = "Continue"

$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root

# Use the project venv (Python 3.11) - the system Python 3.10 fails on
# ``from datetime import UTC`` inside freqtrade.util.datetime_helpers.
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "Venv Python not found at $VenvPython. Create the venv first."
}

$Strategies = @(
    "ScreenerRank1RocVixAdLondon",
    "ScreenerRank4RsiChopPvtNy",
    "ScreenerDpoBbwpWick",
    "ScreenerDpoEveningStar",
    "ScreenerDpoShootingStar"
)

$HyperoptEpochs = 50
$Timeframe = "15m"
$HyperoptLoss = "ShortTradeDurHyperOptLoss"
# 1 month: ~2976 bars per pair, ~8930 total bars in the backtest loop after
# slicing. With 50 epochs x 3 pairs and 6-12 hyperoptable params per strategy,
# the full chain completes in ~3-4h. The longer 19-month timerange caused the
# freqtrade backtest loop to take >10 minutes per epoch (full pre-timerange
# frame runs populate_indicators every call).
$Timerange = "20240101-20240130"
$Pairs = @()                       # empty = all pairs in the data dir
$Jobs = -1                         # all CPU cores
# Per-phase ceilings. Hyperopt dominates the wall clock on a small timerange.
$HyperoptTimeoutMs = 4 * 60 * 60 * 1000  # 4h per strategy
$BacktestTimeoutMs = 30 * 60 * 1000       # 30m per strategy (backtest is fast)

$LogRoot = Join-Path $Root "user_data\hyperopt_logs"
if (-not (Test-Path -LiteralPath $LogRoot)) {
    New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
}

foreach ($Strategy in $Strategies) {
    $StratLogDir = Join-Path $LogRoot $Strategy
    if (-not (Test-Path -LiteralPath $StratLogDir)) {
        New-Item -ItemType Directory -Path $StratLogDir -Force | Out-Null
    }
    $Ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $HyperoptLog = Join-Path $StratLogDir "hyperopt_$Ts.log"
    $BacktestLog = Join-Path $StratLogDir "backtest_$Ts.log"
    $DoneMarker = Join-Path $StratLogDir "BACKTEST_DONE"

    if (Test-Path -LiteralPath $DoneMarker) {
        Write-Host "[$Strategy] BACKTEST_DONE marker present at $DoneMarker - skipping."
        continue
    }

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "[$Strategy] starting hyperopt ($HyperoptEpochs epochs) at $Ts"
    Write-Host "  log: $HyperoptLog"
    Write-Host "============================================================"

    $LogFile = Join-Path $StratLogDir "freqtrade_$Ts.log"
    $HyperoptArgs = @(
        "-m", "freqtrade", "hyperopt",
        "-c", "config_screener_test.json",
        "--strategy", $Strategy,
        "--strategy-path", "user_data\strategies",
        "-i", $Timeframe,
        "--timerange", $Timerange,
        "--hyperopt-loss", $HyperoptLoss,
        "--spaces", "buy", "sell",
        "-e", "$HyperoptEpochs",
        "-j", "$Jobs",
        "--userdir", "user_data",
        "--random-state", "42",
        "--logfile", $LogFile
    )
    if ($Pairs.Count -gt 0) {
        $HyperoptArgs += @("--pairs") + $Pairs
    }

    $HyperoptStart = Get-Date
    $HyperoptProc = Start-Process -FilePath $VenvPython -ArgumentList $HyperoptArgs `
        -RedirectStandardOutput $HyperoptLog -RedirectStandardError "$HyperoptLog.err" `
        -NoNewWindow -PassThru
    Write-Host "  pid=$($HyperoptProc.Id) - waiting for hyperopt to finish..."

    $Exited = $HyperoptProc.WaitForExit($HyperoptTimeoutMs)
    if (-not $Exited) {
        Write-Warning "[$Strategy] hyperopt still running after 4h - leaving for next resume"
        continue
    }
    $HyperoptEnd = Get-Date
    $HyperoptElapsed = $HyperoptEnd - $HyperoptStart
    Write-Host "[$Strategy] hyperopt exited with code $($HyperoptProc.ExitCode) after $([int]$HyperoptElapsed.TotalMinutes) min"

    if ($HyperoptProc.ExitCode -ne 0) {
        Write-Warning "[$Strategy] hyperopt failed - skipping backtest. See $HyperoptLog.err"
        continue
    }

    # Find the latest hyperopt result file
    $ResultDir = Join-Path $Root "user_data\strategies"
    $ResultFile = Get-ChildItem -LiteralPath $ResultDir -Filter "${Strategy}_hyperopt_results-*.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $ResultFile) {
        Write-Warning "[$Strategy] no hyperopt result file found - skipping backtest"
        continue
    }
    $ResultPath = $ResultFile.FullName
    Write-Host "[$Strategy] using result file: $ResultPath"

    # Run a backtest with the best epoch
    Write-Host "[$Strategy] starting backtest with best params"
    $LogFile = Join-Path $StratLogDir "freqtrade_bt_$Ts.log"
    $BacktestArgs = @(
        "-m", "freqtrade", "backtesting",
        "-c", "config_screener_test.json",
        "--strategy", $Strategy,
        "--strategy-path", "user_data\strategies",
        "-i", $Timeframe,
        "--timerange", $Timerange,
        "--userdir", "user_data",
        "--export", "trades",
        "--logfile", $LogFile
    )
    if ($Pairs.Count -gt 0) {
        $BacktestArgs += @("--pairs") + $Pairs
    }

    $BacktestStart = Get-Date
    $BacktestProc = Start-Process -FilePath $VenvPython -ArgumentList $BacktestArgs `
        -RedirectStandardOutput $BacktestLog -RedirectStandardError "$BacktestLog.err" `
        -NoNewWindow -PassThru
    $BacktestDone = $BacktestProc.WaitForExit($BacktestTimeoutMs)
    $BacktestEnd = Get-Date
    $BacktestElapsed = $BacktestEnd - $BacktestStart
    if (-not $BacktestDone) {
        Write-Warning "[$Strategy] backtest still running after 30m - leaving for next resume"
        continue
    }
    Write-Host "[$Strategy] backtest exited with code $($BacktestProc.ExitCode) after $([int]$BacktestElapsed.TotalMinutes) min"

    if ($BacktestProc.ExitCode -eq 0) {
        Set-Content -LiteralPath $DoneMarker -Value "Hyperopt=$HyperoptLog;Backtest=$BacktestLog;Result=$ResultPath;Ts=$Ts"

        # Update the Kelly fractions report after each successful backtest.
        Write-Host "[$Strategy] updating Kelly report"
        $KellyArgs = @("-m", "user_data.scripts.kelly_report")
        $KellyLog = Join-Path $StratLogDir "kelly_$Ts.log"
        $KellyProc = Start-Process -FilePath $VenvPython -ArgumentList $KellyArgs `
            -RedirectStandardOutput $KellyLog -RedirectStandardError "$KellyLog.err" `
            -NoNewWindow -PassThru
        $KellyProc.WaitForExit(600000) | Out-Null
        if ($KellyProc.ExitCode -ne 0) {
            Write-Warning "[$Strategy] kelly report step failed - see $KellyLog.err"
        }
    } else {
        Write-Warning "[$Strategy] backtest failed - see $BacktestLog.err"
    }
}

Write-Host ""
Write-Host "All strategies processed. Logs: $LogRoot"
Write-Host "Kelly report: $LogRoot\kelly_report.md"
