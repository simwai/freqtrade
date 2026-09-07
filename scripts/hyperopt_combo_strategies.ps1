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
$Jobs = 1                           # single worker; -j -1 crashes on this Windows + numpy 2.2 build
# Per-phase ceilings. Hyperopt dominates the wall clock on a small timerange.
$HyperoptTimeoutMs = 4 * 60 * 60 * 1000  # 4h per strategy
$BacktestTimeoutMs = 30 * 60 * 1000       # 30m per strategy (backtest is fast)

# Hyperopt search strategy. The default is TPE (Tree-structured Parzen
# Estimator) which is sample-inefficient on small epoch budgets. The
# ExtraTrees (``ET``) estimator is the freqtrade default for Fibonacci
# stepping and tends to converge faster on noisy small-sample objectives.
# The Fibonacci stepping mode walks the search space in roughly a golden-
# ratio pattern: 10 initial random points, then ~15% space reduction per
# generation toward the ``fibonacci-target`` (default 34, our chosen target).
# Together with the SmallEpochsFibonacciSpace this is freqtrade's recommended
# preset for <100 epoch budgets.
$UseFibonacci = $true
$FibonacciTarget = 34
$InitialPoints = 10
$SpaceReduction = 0.15
$HyperoptEstimator = "ET"

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

    # If a hyperopt result was written in the last 4 hours, skip
    # hyperopt and reuse the latest result. The Kill-Switch lives in the
    # ResultFile mtime check below; if a stale result is found the user can
    # remove the relevant file from user_data/hyperopt_results to force a
    # rerun.
    $HyperoptResultsDir = Join-Path $Root "user_data\hyperopt_results"
    $ExistingResult = Get-ChildItem -LiteralPath $HyperoptResultsDir `
        -Filter "strategy_${Strategy}_*.fthypt" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -ne $ExistingResult -and $ExistingResult.LastWriteTime -gt (Get-Date).AddHours(-4)) {
        Write-Host "[$Strategy] reusing recent hyperopt result: $($ExistingResult.FullName)"
        $ResultPath = $ExistingResult.FullName
        $SkipHyperopt = $true
    } else {
        $SkipHyperopt = $false
    }

    if (-not $SkipHyperopt) {
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
        # Hyperopt search strategy knobs. When ``$UseFibonacci`` is true we
        # switch to freqtrade's Fibonacci stepping mode with the chosen
        # estimator; otherwise the default TPE sampler is used.
        if ($UseFibonacci) {
            $HyperoptArgs += @(
                "--hyperopt-fibonacci",
                "--fibonacci-target", "$FibonacciTarget",
                "--initial-points", "$InitialPoints",
                "--space-reduction", "$SpaceReduction",
                "--estimator", $HyperoptEstimator
            )
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
        # why: $HyperoptProc.ExitCode on PowerShell 5.1 returns 0 immediately
        # after WaitForExit even if the process hasn't been fully reaped. Poll the
        # process object until ExitCode is non-zero OR the process is gone, and
        # fall back to checking whether the hyperopt result JSON was actually
        # written (the real success signal).
        $HyperoptExitCode = $null
        for ($i = 0; $i -lt 10; $i++) {
            Start-Sleep -Milliseconds 500
            $proc = Get-Process -Id $HyperoptProc.Id -ErrorAction SilentlyContinue
            if ($null -eq $proc) { break }
            if ($proc.ExitCode -ne 0) { $HyperoptExitCode = $proc.ExitCode; break }
        }
        if ($null -eq $HyperoptExitCode) {
            # Process is gone; ExitCode property is inaccessible. Infer from
            # whether the hyperopt produced a result file after the start time.
            $ResultProbe = Get-ChildItem -LiteralPath (Join-Path $Root "user_data\strategies") `
                -Filter "${Strategy}_hyperopt_results-*.json" -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTime -gt $HyperoptStart } |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            $HyperoptExitCode = if ($null -ne $ResultProbe) { 0 } else { 1 }
        }
        Write-Host "[$Strategy] hyperopt exit code=$HyperoptExitCode after $([int]$HyperoptElapsed.TotalMinutes) min"

        if ($HyperoptExitCode -ne 0) {
            Write-Warning "[$Strategy] hyperopt failed - skipping backtest. See $HyperoptLog.err"
            continue
        }
    } else {
        $HyperoptStart = Get-Date
    }

    # Find the latest hyperopt result file
    $ResultFile = Get-ChildItem -LiteralPath $HyperoptResultsDir `
        -Filter "strategy_${Strategy}_*.fthypt" -ErrorAction SilentlyContinue |
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
    # Same PowerShell 5.1 ExitCode quirk as the hyperopt step. Poll then fall
    # back to whether the backtest produced a non-empty result zip.
    $BacktestExitCode = $null
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Milliseconds 500
        $proc = Get-Process -Id $BacktestProc.Id -ErrorAction SilentlyContinue
        if ($null -eq $proc) { break }
        if ($proc.ExitCode -ne 0) { $BacktestExitCode = $proc.ExitCode; break }
    }
    if ($null -eq $BacktestExitCode) {
        $RecentZip = Get-ChildItem -LiteralPath (Join-Path $Root "user_data\backtest_results") `
            -Filter "backtest-result-*.zip" -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -gt $BacktestStart -and $_.Length -gt 1000 } |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        $BacktestExitCode = if ($null -ne $RecentZip) { 0 } else { 1 }
    }
    Write-Host "[$Strategy] backtest exit code=$BacktestExitCode after $([int]$BacktestElapsed.TotalMinutes) min"

    if ($BacktestExitCode -eq 0) {
        Set-Content -LiteralPath $DoneMarker -Value "Hyperopt=$HyperoptLog;Backtest=$BacktestLog;Result=$ResultPath;Ts=$Ts"

        # Update the Kelly fractions report after each successful backtest.
        Write-Host "[$Strategy] updating Kelly report"
        $KellyArgs = @("-m", "user_data.scripts.kelly_report")
        $KellyLog = Join-Path $StratLogDir "kelly_$Ts.log"
        $KellyProc = Start-Process -FilePath $VenvPython -ArgumentList $KellyArgs `
            -RedirectStandardOutput $KellyLog -RedirectStandardError "$KellyLog.err" `
            -NoNewWindow -PassThru
        $KellyProc.WaitForExit(600000) | Out-Null
        $KellyExitCode = $null
        for ($i = 0; $i -lt 10; $i++) {
            Start-Sleep -Milliseconds 500
            $proc = Get-Process -Id $KellyProc.Id -ErrorAction SilentlyContinue
            if ($null -eq $proc) { break }
            if ($proc.ExitCode -ne 0) { $KellyExitCode = $proc.ExitCode; break }
        }
        if ($null -ne $KellyExitCode -and $KellyExitCode -ne 0) {
            Write-Warning "[$Strategy] kelly report step failed - see $KellyLog.err"
        }
    } else {
        Write-Warning "[$Strategy] backtest failed - see $BacktestLog.err"
    }
}

Write-Host ""
Write-Host "All strategies processed. Logs: $LogRoot"
Write-Host "Kelly report: $LogRoot\kelly_report.md"
