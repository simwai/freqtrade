# test-rubric-id-integrity.ps1
# Asserts that every H-tier rubric id maps to exactly one title across the
# prompt-system and docs\refs, and that no file cites an H id that the
# registry omits.
#
# 04-rubrics.md is the sole authority for which H-number belongs to which rule.
# prompt-system/rules.md supplies detection and enforcement for the same ids and
# must never disagree about the title. A disagreement here is silent breakage:
# an agent asked to enforce "H33" may run the wrong rule.
#
# Exit 0 on pass, non-zero on fail.

$ErrorActionPrefs = 'Stop'
. "$PSScriptRoot\test-assertions.ps1"

$systemRoot = Join-Path $PSScriptRoot '..'

# The registry: definitions look like **H33 -- No Magic Values: fix introduces ...
# Two shapes exist. Most titles end at the first colon; H11 closes the bold run
# before its colon ("**H11 -- Runnable artifact (verdict-gate criterion).** The ..."),
# so stop at whichever comes first.
$registryPath = Join-Path $systemRoot '04-rubrics.md'
$registry = @{}
foreach ($m in [regex]::Matches([System.IO.File]::ReadAllText($registryPath), '(?m)^\*\*H(\d+) -- (.+?)\s*\*\*')) {
    $registry[[int]$m.Groups[1].Value] = $m.Groups[2].Value.Trim().TrimEnd('.')
}

Assert-FileExists -Path $registryPath -Description 'rubric registry (04-rubrics.md)'
Assert-FileHasCount -Path $registryPath -Pattern '**H' -Expected $registry.Count -Description 'registry definition count matches parsed definitions'

if ($registry.Count -eq 0) {
    Add-TestFailure 'REGISTRY EMPTY: no **H<n> -- <title>: definitions parsed from 04-rubrics.md'
    exit (Complete-TestRun -SuiteName 'rubric id integrity')
}

# H1-H12 are referenced by id across every file; H13-H38 carry the detail layer.
Assert-FileContains -Path $registryPath -Pattern '**H1 -- Security:' -Description 'H1 present in registry'
Assert-FileContains -Path $registryPath -Pattern '**H38 -- No Multi-Concept Files:' -Description 'H38 present in registry (no gap above it)'

# 1. The detail layer owns H13-H38 only; H1-H12 carry no rules.md section by design.
$detailPath = Join-Path $systemRoot 'rules.md'
Assert-FileExists -Path $detailPath -Description 'detail layer (rules.md)'

$detail = @{}
foreach ($m in [regex]::Matches([System.IO.File]::ReadAllText($detailPath), '(?m)^## H(\d+) -- (.+)$')) {
    $detail[[int]$m.Groups[1].Value] = $m.Groups[2].Value.Trim()
}

foreach ($id in ($detail.Keys | Sort-Object)) {
    if ($id -lt 13) {
        Add-TestFailure "OUT OF RANGE: rules.md defines H$id; the detail layer owns H13-H38 only"
        continue
    }
    if (-not $registry.ContainsKey($id)) {
        Add-TestFailure "ORPHAN IN DETAIL: rules.md defines H$id ($($detail[$id])) which 04-rubrics.md does not define"
    }
}

foreach ($id in ($registry.Keys | Sort-Object)) {
    if ($id -lt 13) { continue }
    if (-not $detail.ContainsKey($id)) {
        Add-TestFailure "MISSING IN DETAIL: H$id ($($registry[$id])) has no '## H$id -- ...' section in rules.md"
        continue
    }
    if ($detail[$id] -ne $registry[$id]) {
        Add-TestFailure "TITLE MISMATCH: H$id is '$($registry[$id])' in 04-rubrics.md but '$($detail[$id])' in rules.md"
    }
}

# 2. No file in prompt-system\ or docs\refs\ may cite an H id the registry omits.
#    docs\refs\ is scanned deliberately: it is where a divergent rubric copy
#    would survive, because the registry-vs-detail checks above only read
#    prompt-system\ files.
$repoRoot = (Resolve-Path (Join-Path $systemRoot '..')).Path
$docsRefs = Join-Path $repoRoot 'docs\refs'

$scanFiles = @(Get-ChildItem -Path $systemRoot -Recurse -Filter '*.md' -File)
if (Test-Path -LiteralPath $docsRefs -PathType Container) {
    $scanFiles += @(Get-ChildItem -Path $docsRefs -Filter '*.md' -File)
}

$scanned = 0
foreach ($file in $scanFiles) {
    $scanned++
    $text = [System.IO.File]::ReadAllText($file.FullName)
    foreach ($m in [regex]::Matches($text, '(?<![A-Za-z0-9])H(\d+)(?![0-9])')) {
        $cited = [int]$m.Groups[1].Value
        if ($cited -le 0 -or $cited -gt 200) { continue }
        if (-not $registry.ContainsKey($cited)) {
            $rel = $file.FullName.Substring($repoRoot.Length).TrimStart('\', '/')
            Add-TestFailure "UNDEFINED CITATION: $rel cites H$cited, which 04-rubrics.md does not define"
        }
    }
}

Write-Host "  scanned $scanned markdown files under prompt-system\ and docs\refs\"

# 3. Semantic keyword check for .opencode/**/*.ts plugin files.
#    When a .ts file cites an H id, the surrounding comment or string must
#    contain at least one keyword from the H id's title. This catches
#    copy-pasted or misapplied rubric citations in plugin code.
$opencodeRoot = Join-Path $repoRoot '.opencode'
if (Test-Path -LiteralPath $opencodeRoot -PathType Container) {
    $tsFiles = Get-ChildItem -Path $opencodeRoot -Recurse -Filter '*.ts' -File | Where-Object {
        $_.FullName -notmatch '\\node_modules\\'
    }
    $tsScanned = 0
    foreach ($file in $tsFiles) {
        $tsScanned++
        $text = [System.IO.File]::ReadAllText($file.FullName)
        foreach ($m in [regex]::Matches($text, '(?<![A-Za-z0-9])H(\d+)(?![0-9])')) {
            $cited = [int]$m.Groups[1].Value
            if ($cited -le 0 -or $cited -gt 200) { continue }
            if (-not $registry.ContainsKey($cited)) { continue }
            $title = $registry[$cited]
            # Extract candidate keywords: words longer than 3 chars from the title
            $keywords = ($title -replace '[^a-zA-Z\s]', '').Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries) |
                Where-Object { $_.Length -gt 3 } |
                Select-Object -First 6
            if ($keywords.Count -eq 0) { continue }
            # Get context window around the citation (200 chars before + 200 after)
            $idx = $m.Index
            $start = [Math]::Max(0, $idx - 200)
            $len = [Math]::Min(400, $text.Length - $start)
            $context = $text.Substring($start, $len).ToLower()
            $found = $false
            foreach ($kw in $keywords) {
                $kwLower = $kw.ToLower()
                # Match the keyword itself or common singular/plural variants
                $variants = @($kwLower)
                if ($kwLower.EndsWith('s')) { $variants += $kwLower.Substring(0, $kwLower.Length - 1) }
                else { $variants += $kwLower + 's' }
                foreach ($variant in $variants) {
                    if ($context.Contains($variant)) {
                        $found = $true
                        break
                    }
                }
                if ($found) { break }
            }
            if (-not $found) {
                $rel = $file.FullName.Substring($repoRoot.Length).TrimStart('\', '/')
                Add-TestFailure "SEMANTIC CITATION: $rel cites H$cited but context lacks keywords from title: $($keywords -join ', ')"
            }
        }
    }
    Write-Host "  scanned $tsScanned .ts files under .opencode\ (semantic keyword check)"
}
exit (Complete-TestRun -SuiteName 'rubric id integrity')
