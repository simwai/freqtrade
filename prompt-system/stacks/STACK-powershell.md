# Stack: PowerShell

- Runtime: pwsh 7.6. Never author for Windows PowerShell 5.1.
- Approved verbs (`Get-`, `Set-`, `New-`, `Remove-`, `Test-`, `Start-`, `Stop-`); `Update-` only when no approved verb fits and the deviation is documented.
- Cmdlet naming: singular noun, not plural; parameter names hyphenated (`-Path`, not `-FilePath`).
- Error handling: `$ErrorActionPreference = 'Stop'` at the top of scripts; `try/catch/finally`; never silently `continue` on a non-zero exit code.
- Native commands (git, robocopy, rg) report failure through `$LASTEXITCODE`, not exceptions: by default a non-zero exit code sets `$?` to `$false` but does not generate an error and does not trigger `catch`/`trap`.
- pwsh 7.3 (experimental) / 7.4 (stable) adds `$PSNativeCommandUseErrorActionPreference`, default `$false`. With `$true` and `$ErrorActionPreference='Stop'`, a non-zero exit code becomes a catchable script-terminating error (`NativeCommandExitException`). Whether `try/catch` fires around a native call is configuration-dependent; check both variables before relying on it; never assume.
- Prefer guard-and-return: run the command, check `$LASTEXITCODE`, write a warning, return. It is version-proof and setting-proof, and matches the dominating idiom of this repo's scripts (see the comment in `sync.ps1` `Update-GitTarget`).
- Beware informational exit codes: robocopy uses 1-7 for success outcomes; test `-ge 8` as `sync.ps1` does.
- Use `try/catch/finally` for cmdlet terminating errors and for cleanup that must run when a terminating error occurs (`finally` always runs). Under guard-and-return, restore env-var guards immediately after the guarded call; no `finally` is needed because nothing throws on that path.
- Since pwsh 7.2, `2>&1`-redirected native stderr is no longer affected by `$ErrorActionPreference`; the 5.1-era "stderr becomes terminating under Stop" hazard does not apply to pwsh.
- Output: `Write-Host` for user-facing messages, `Write-Output` (or implicit) for pipeline data, `Write-Verbose` for diagnostics. Never `Write-Host` for data the caller needs to consume.
- Modules: `Export-ModuleMember` for explicit public surface; `using module` (not `Import-Module` inline) when the module is a class library.
- Tests: Pester with `Describe`/`Context`/`It`; `Should -Be` / `Should -Throw` / `Should -Invoke`; mock with `Mock`.
- Project structure:
  - `.psd1` manifest + `.psm1` module; `public/` for exported functions, `private/` for helpers
  - `param()` blocks at the top; `begin`/`process`/`end` for pipeline input
  - `[CmdletBinding(SupportsShouldProcess)]` + `$PSCmdlet.ShouldProcess()` for state-changing cmdlets
  - Comment-based help `<# .SYNOPSIS ... #>` for public functions
