# NFI guard robustness sweep driver - runs the approved 24-run matrix
# sequentially and detached; progress lands in user_data\logs, a .done
# marker appears after the final run. Analysis reads result zips directly.

$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$py = Join-Path $repo '.venv\Scripts\python.exe'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$log = "user_data\logs\nfi_sweep_$stamp.log"

$runs = @(
  @{ s = 'NostalgiaForInfinityX7';        tr = '20240301-20240701' },
  @{ s = 'NostalgiaForInfinityX7Guarded'; tr = '20240301-20240701' },
  @{ s = 'NostalgiaForInfinityX7';        tr = '20240701-20241101' },
  @{ s = 'NostalgiaForInfinityX7Guarded'; tr = '20240701-20241101' }
)
foreach ($w in '20241201-20250301','20250301-20250601','20250601-20250901','20260501-20260827') {
  foreach ($v in 'NFIX7GuardedCat15','NFIX7GuardedCat25','NFIX7GuardedCat30','NFIX7GuardedAge10','NFIX7GuardedAge21') {
    $runs += @{ s = $v; tr = $w }
  }
}

$i = 0
foreach ($r in $runs) {
  $i++
  "=== RUN $i/$($runs.Count): $($r.s) | $($r.tr) | start $(Get-Date -Format HH:mm:ss) ===" |
    Tee-Object -FilePath $log -Append
  & $py -m freqtrade backtesting `
      --config user_data\config_nfi_test_usdc.json `
      --strategy $r.s `
      --timerange $r.tr `
      --userdir user_data --cache none *>> $log
  "exit=$LASTEXITCODE" | Tee-Object -FilePath $log -Append
}

"DONE $stamp" | Set-Content "user_data\logs\nfi_sweep_$stamp.done"
