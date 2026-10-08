<#
.SYNOPSIS
    Round-trip regression test for the reference-pool manifest serializer.
.DESCRIPTION
    Writes a synthetic manifest to the OS temp directory, reads it back through
    Read-Manifest, re-serializes it with Write-Manifest, and asserts that every
    pool member and entry survives both directions.

    Run against the pre-fix parser this fails: Read-Manifest returned only the
    last item of the pool and entries lists, so a manifest with two members and
    two entries came back with one of each.

    Uses temp files only. Never reads or writes the real reference pool.
.EXAMPLE
    pwsh -NoProfile -File prompt-system/scripts/test-manifest-io.ps1
.EXAMPLE
    pwsh -NoProfile -File prompt-system/scripts/test-manifest-io.ps1 -ManifestIoPath C:\temp\legacy-io.ps1
#>

param(
    [string]$ManifestIoPath = (Join-Path $PSScriptRoot 'manifest-io.ps1')
)

$ErrorActionPreference = 'Stop'

$script:Failures = @()

function Add-Failure {
    param([string]$Message)
    $script:Failures += $Message
}

function Assert-Equal {
    param($Actual, $Expected, [string]$Because)
    if ($Actual -ne $Expected) {
        Add-Failure "expected [$Expected] but got [$Actual] -- $Because"
    }
}

function New-TempManifestPath {
    $name = "reference-pool-io-{0}.yaml" -f ([guid]::NewGuid().ToString('N'))
    return Join-Path ([System.IO.Path]::GetTempPath()) $name
}

if (-not (Test-Path -LiteralPath $ManifestIoPath -PathType Leaf)) {
    throw "manifest-io module not found at $ManifestIoPath"
}

. $ManifestIoPath

# Two members and two entries on purpose: a single-item manifest is the one case
# the old parser handled correctly, so a one-item fixture would not catch the bug.
$synthetic = @'
schema_version: "1.0"
pool:
  - id: "alpha-repo"
    type: "repo"
    handle: "alpha"
    repo: "alpha/alpha-repo"
    languages: [typescript]
    domains: [plugin-sdk]
    trust_level: "unvetted"
    added_at: "2026-01-01"
    why: "first member"
  - id: "beta-repo"
    type: "repo"
    handle: "beta"
    repo: "beta/beta-repo"
    languages: [python]
    domains: [error-handling]
    trust_level: "premium"
    added_at: "2026-01-02"
    why: "second member"
entries:
  - id: "alpha-repo-first"
    pool_id: "alpha-repo"
    repo: "alpha/alpha-repo"
    file_path: "src/first.ts"
    language: "typescript"
    commit: "1111111111111111111111111111111111111111"
    source_url: "https://github.com/alpha/alpha-repo/blob/main/src/first.ts"
    added_at: "2026-01-01"
    why: "first entry"
    primary_tags: [plugin, sdk]
    secondary_tags: []
  - id: "beta-repo-second"
    pool_id: "beta-repo"
    repo: "beta/beta-repo"
    file_path: "src/second.py"
    language: "python"
    commit: "2222222222222222222222222222222222222222"
    source_url: "https://github.com/beta/beta-repo/blob/main/src/second.py"
    added_at: "2026-01-02"
    why: "second entry"
    primary_tags: [error, handling]
    secondary_tags: [fuzz]
'@

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$sourcePath = New-TempManifestPath
$firstWritePath = New-TempManifestPath
$secondWritePath = New-TempManifestPath
$singlePath = New-TempManifestPath
$singleWritePath = New-TempManifestPath

try {
    [System.IO.File]::WriteAllText($sourcePath, $synthetic, $utf8NoBom)

    $parsed = Read-Manifest -Path $sourcePath

    Assert-Equal -Actual $parsed.schema_version -Expected '1.0' -Because 'schema_version must survive the read'
    Assert-Equal -Actual @($parsed.pool).Count -Expected 2 -Because 'both pool members must survive the read'
    Assert-Equal -Actual @($parsed.entries).Count -Expected 2 -Because 'both entries must survive the read'

    $poolIds = @($parsed.pool | ForEach-Object { $_.id })
    if ($poolIds -notcontains 'alpha-repo') {
        Add-Failure "pool member 'alpha-repo' is missing -- the parser dropped every item but the last"
    }

    $entryIds = @($parsed.entries | ForEach-Object { $_.id })
    if ($entryIds -notcontains 'alpha-repo-first') {
        Add-Failure "entry 'alpha-repo-first' is missing -- the parser dropped every item but the last"
    }

    $firstEntry = @($parsed.entries | Where-Object { $_.id -eq 'alpha-repo-first' })[0]
    if ($null -ne $firstEntry) {
        Assert-Equal -Actual $firstEntry.language -Expected 'typescript' -Because 'entry language must be parsed so refresh can resolve its cache directory'
        Assert-Equal -Actual @($firstEntry.secondary_tags).Count -Expected 0 -Because 'an empty secondary_tags list must parse as an empty array, not the string "[]"'
        Assert-Equal -Actual @($firstEntry.primary_tags).Count -Expected 2 -Because 'primary_tags must parse as a two-element array'
    }

    Write-Manifest -Path $firstWritePath -Manifest $parsed
    $reparsed = Read-Manifest -Path $firstWritePath

    Assert-Equal -Actual @($reparsed.pool).Count -Expected 2 -Because 'both pool members must survive the write'
    Assert-Equal -Actual @($reparsed.entries).Count -Expected 2 -Because 'both entries must survive the write'
    Assert-Equal -Actual @($reparsed.entries | Where-Object { $_.id -eq 'alpha-repo-first' })[0].language -Expected 'typescript' -Because 'entry language must be re-emitted by Write-Manifest'

    Write-Manifest -Path $secondWritePath -Manifest $reparsed
    $firstBytes = [System.IO.File]::ReadAllText($firstWritePath)
    $secondBytes = [System.IO.File]::ReadAllText($secondWritePath)
    Assert-Equal -Actual $secondBytes -Expected $firstBytes -Because 'serialization must be idempotent, so an empty list cannot regrow brackets on every write'

    # A one-member, one-entry manifest is the single case the old parser handled
    # correctly, so it survives it and can prove the empty-list defect on its own:
    # secondary_tags round-tripped as the string "[]" and regrew to "[[]]".
    $single = @'
schema_version: "1.0"
pool:
  - id: "solo-repo"
    type: "repo"
    handle: "solo"
    repo: "solo/solo-repo"
    languages: [typescript]
    domains: [type-safety]
    trust_level: "unvetted"
    added_at: "2026-01-03"
    why: "only member"
entries:
  - id: "solo-repo-only"
    pool_id: "solo-repo"
    repo: "solo/solo-repo"
    file_path: "index.d.ts"
    language: "typescript"
    commit: "3333333333333333333333333333333333333333"
    source_url: "https://github.com/solo/solo-repo/blob/main/index.d.ts"
    added_at: "2026-01-03"
    why: "only entry"
    primary_tags: [types, utility]
    secondary_tags: []
'@

    [System.IO.File]::WriteAllText($singlePath, $single, $utf8NoBom)
    $soloParsed = Read-Manifest -Path $singlePath
    $soloEntry = @($soloParsed.entries)[0]

    if ($null -eq $soloEntry) {
        Add-Failure "the single-entry manifest produced no entry -- the parser cannot read a one-item list"
    } else {
        Assert-Equal -Actual @($soloEntry.secondary_tags).Count -Expected 0 -Because 'secondary_tags: [] must parse as an empty array, not the string "[]"'

        Write-Manifest -Path $singleWritePath -Manifest $soloParsed
        $written = [System.IO.File]::ReadAllText($singleWritePath)
        if ($written -match '\[\[\]\]') {
            Add-Failure 'an empty secondary_tags list regrew to "[[]]" on write'
        }
    }
}
finally {
    foreach ($path in @($sourcePath, $firstWritePath, $secondWritePath, $singlePath, $singleWritePath)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        }
    }
}

if ($script:Failures.Count -gt 0) {
    foreach ($failure in $script:Failures) {
        Write-Host "FAIL $failure" -ForegroundColor Red
    }
    Write-Host "test-manifest-io: $($script:Failures.Count) assertion(s) failed" -ForegroundColor Red
    exit 1
}

Write-Host "test-manifest-io: manifest round-trip intact (2 members, 2 entries, idempotent serialization)" -ForegroundColor Green
exit 0
