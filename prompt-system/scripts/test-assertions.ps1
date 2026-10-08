# test-assertions.ps1
# Shared assertion helpers for the prompt-system static tests.
# Dot-source this file from a test script: `. "$PSScriptRoot\test-assertions.ps1"`.
# It performs no checks on its own and must not be run directly.

$script:TestFailures = @()

function Add-TestFailure {
    param([string]$Message)
    $script:TestFailures += $Message
}

function Assert-FileContains {
    param(
        [string]$Path,
        [string]$Pattern,
        [string]$Description
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Add-TestFailure "MISSING FILE: $Description ($Path)"
        return
    }
    $found = Select-String -Path $Path -Pattern $Pattern -SimpleMatch -Quiet
    if (-not $found) {
        Add-TestFailure "MISSING: $Description"
    }
}

function Assert-FileNotContains {
    param(
        [string]$Path,
        [string]$Pattern,
        [string]$Description
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Add-TestFailure "MISSING FILE: $Description ($Path)"
        return
    }
    $found = Select-String -Path $Path -Pattern $Pattern -SimpleMatch -Quiet
    if ($found) {
        Add-TestFailure "UNEXPECTED: $Description"
    }
}

function Assert-FileHasCount {
    param(
        [string]$Path,
        [string]$Pattern,
        [int]$Expected,
        [string]$Description
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Add-TestFailure "MISSING FILE: $Description ($Path)"
        return
    }
    $actual = @(Select-String -Path $Path -Pattern $Pattern -SimpleMatch).Count
    if ($actual -ne $Expected) {
        Add-TestFailure "COUNT: $Description (expected $Expected, found $actual)"
    }
}

function Assert-FileExists {
    param(
        [string]$Path,
        [string]$Description
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Add-TestFailure "MISSING FILE: $Description ($Path)"
    }
}

function Complete-TestRun {
    param([string]$SuiteName)

    if ($script:TestFailures.Count -eq 0) {
        Write-Host "PASS: $SuiteName" -ForegroundColor Green
        return 0
    }

    Write-Host "FAIL: $SuiteName" -ForegroundColor Red
    $script:TestFailures | ForEach-Object { Write-Host "  - $_" }
    return 1
}
