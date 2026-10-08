# test-cross-reference-integrity.ps1
# Asserts that every `file.md` `## Anchor` citation inside the deployed
# prompt-system resolves to a heading that actually exists in the named file.
#
# A citation to a missing anchor is silent breakage: the agent follows the
# pointer, finds nothing, and either invents the rule or skips the protocol.
# Six such dangling citations shipped for the session-evaluation prompt alone.
#
# Scope: prompt-system\ and AGENTS.md, the surface AGENTS.md deploys.
# Exit 0 on pass, non-zero on fail.

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\test-assertions.ps1"

$systemRoot = Join-Path $PSScriptRoot '..'
$repoRoot = (Resolve-Path (Join-Path $systemRoot '..')).Path

function Get-NormalizedHeadings {
    param([string]$Path)

    $set = New-Object 'System.Collections.Generic.HashSet[string]'
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $set }
    foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
        if ($line -match '^(#{1,6})\s+(.*)$') {
            $text = $Matches[2] -replace '`', ''
            [void]$set.Add($text.Trim().ToLowerInvariant())
        }
    }
    return $set
}

# Citations routinely name a readable prefix of a longer heading
# (`## T-01` for `## T-01 -- Project style policy auto-trigger`), so a citation
# resolves on an exact match or on a word-boundary prefix of a real heading.
function Test-AnchorResolves {
    param([System.Collections.Generic.HashSet[string]]$Headings, [string]$Anchor)

    foreach ($heading in $Headings) {
        if ($heading -eq $Anchor) { return $true }
        if ($heading.StartsWith($Anchor)) {
            $next = $heading.Substring($Anchor.Length, 1)
            if ($next -match '[\s\-\(\):]') { return $true }
        }
    }
    return $false
}

function Resolve-CitedFile {
    param([string]$Cited)

    $candidates = @()
    if ($Cited -match '/') {
        $candidates += Join-Path $repoRoot ($Cited -replace '/', '\')
    } else {
        $candidates += (Join-Path $systemRoot $Cited)
        $candidates += (Join-Path $repoRoot $Cited)
    }
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c -PathType Leaf) { return $c }
    }
    return $null
}

$headingCache = @{}
$checked = 0
$citationPattern = [regex]'`([A-Za-z0-9_.\-/]+\.md)`\s+`#{2,4}\s+([^`]+)`'

$files = @(Get-ChildItem -Path $systemRoot -Recurse -Filter '*.md' -File)

# AGENTS.md ships alongside prompt-system\, but the suite must stay runnable from a
# partial copy of the tree, so treat it as optional rather than a hard dependency.
$agentsPath = Join-Path $repoRoot 'AGENTS.md'
if (Test-Path -LiteralPath $agentsPath -PathType Leaf) {
    $files += Get-Item $agentsPath
}

# docs\ is scanned too. It carries `file.md` + `## Anchor` citations that are just as
# load-bearing -- a dangling one in docs\ is exactly how `## Loop protection` stayed
# referenced by four files, including two inside prompt-system\, while the section
# itself did not exist anywhere.
$docsRoot = Join-Path $repoRoot 'docs'
if (Test-Path -LiteralPath $docsRoot -PathType Container) {
    $files += @(Get-ChildItem -Path $docsRoot -Recurse -Filter '*.md' -File)
}

foreach ($file in $files) {
    $rel = $file.FullName.Substring($repoRoot.Length).TrimStart('\', '/')
    $text = [System.IO.File]::ReadAllText($file.FullName)

    foreach ($m in $citationPattern.Matches($text)) {
        $citedFile = $m.Groups[1].Value
        $anchor = ($m.Groups[2].Value -replace '`', '').Trim().ToLowerInvariant()
        $checked++

        $resolved = Resolve-CitedFile -Cited $citedFile
        if (-not $resolved) {
            Add-TestFailure "UNRESOLVED FILE: $rel cites ``$citedFile`` which exists in neither prompt-system\ nor the repo root"
            continue
        }

        if (-not $headingCache.ContainsKey($resolved)) {
            $headingCache[$resolved] = Get-NormalizedHeadings -Path $resolved
        }
        if (-not (Test-AnchorResolves -Headings $headingCache[$resolved] -Anchor $anchor)) {
            $targetRel = $resolved.Substring($repoRoot.Length).TrimStart('\', '/')
            Add-TestFailure "DANGLING ANCHOR: $rel cites ``$citedFile`` ``$anchor`` but $targetRel has no such heading"
        }
    }
}

# ── Bare-anchor audit (advisory, non-blocking) ──────────────────────────────
# A backticked `## Anchor` with no preceding `file.md` is ambiguous: it may mean
# this file, another system file, or a session-context field (`## Edited Files`,
# `## Plan Approval`) that is not a heading anywhere. Those session-state fields
# make this check far too noisy to gate on, so it reports and does not fail.
#
# It exists because a phantom section is otherwise invisible: `## Loop protection`
# was cited four times, resolved nowhere, and the blocking pass above could not see
# it -- two of those citations are self-references with no `file.md` token to pair.
$barePattern = [regex]'`#{2,4}\s+([^`]+)`'
$allHeadings = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($file in $files) {
    if (-not $headingCache.ContainsKey($file.FullName)) {
        $headingCache[$file.FullName] = Get-NormalizedHeadings -Path $file.FullName
    }
    foreach ($h in $headingCache[$file.FullName]) { [void]$allHeadings.Add($h) }
}

$orphans = New-Object System.Collections.Generic.List[string]
foreach ($file in $files) {
    $text = [System.IO.File]::ReadAllText($file.FullName)
    $own = $headingCache[$file.FullName]
    foreach ($m in $barePattern.Matches($text)) {
        $anchor = ($m.Groups[1].Value -replace '`', '').Trim().ToLowerInvariant()
        if (Test-AnchorResolves -Headings $own -Anchor $anchor) { continue }
        if (Test-AnchorResolves -Headings $allHeadings -Anchor $anchor) { continue }
        $orphans.Add("$($file.Name) -> ``$anchor``")
    }
}

if ($orphans.Count -gt 0) {
    Write-Warning "  $($orphans.Count) bare ``## anchor`` citations resolve to no heading in any scanned file."
    Write-Warning "  These are advisory only -- session-context fields such as ``## Edited Files`` are not headings."
    $orphans | Sort-Object -Unique | Select-Object -First 20 | ForEach-Object { Write-Warning "    $_" }
    if ($orphans.Count -gt 20) { Write-Warning "    ... and $($orphans.Count - 20) more" }
}

Write-Host "  checked $checked file+anchor citations across $($files.Count) files ($($orphans.Count) advisory bare-anchor orphans)"
exit (Complete-TestRun -SuiteName 'cross-reference integrity')
