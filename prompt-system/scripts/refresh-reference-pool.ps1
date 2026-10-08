<#
.SYNOPSIS
    Refreshes reference pool entries older than 1 month.
.DESCRIPTION
    Scans the manifest for entries whose added_at is older than the TTL,
    re-fetches them from GitHub, updates the cached files and manifest.
    Does not touch entries newer than the TTL.
#>

param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$script:POOL_ROOT = if ($env:USERPROFILE) {
    Join-Path $env:USERPROFILE '.config\opencode\reference-pool'
} else {
    Join-Path $env:HOME '.config\opencode\reference-pool'
}

$script:MANIFEST_PATH = Join-Path $script:POOL_ROOT 'manifest.yaml'
$script:MANIFEST_IO = Join-Path $PSScriptRoot 'manifest-io.ps1'
if (-not (Test-Path -LiteralPath $script:MANIFEST_IO -PathType Leaf)) {
    throw "manifest-io.ps1 not found at $script:MANIFEST_IO -- it ships beside this script in prompt-system/scripts/."
}
. $script:MANIFEST_IO
$script:TTL_DAYS = 30

function Test-PoolInitialized {
    if (-not (Test-Path -LiteralPath $script:POOL_ROOT -PathType Container)) {
        throw "Reference pool not initialized at $script:POOL_ROOT. Run init-reference-pool.ps1 first."
    }
    if (-not (Test-Path -LiteralPath $script:MANIFEST_PATH -PathType Leaf)) {
        throw "manifest.yaml not found at $script:MANIFEST_PATH"
    }
}

function Parse-GitHubUrl {
    param([string]$Url)
    
    if ($Url -match '^https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)$') {
        return @{
            Owner = $matches[1]
            Repo = $matches[2]
            Branch = $matches[3]
            Path = $matches[4]
            RawUrl = $Url
        }
    }
    
    if ($Url -match '^https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$') {
        $owner = $matches[1]
        $repo = $matches[2]
        $branch = $matches[3]
        $path = $matches[4]
        $rawUrl = "https://raw.githubusercontent.com/$owner/$repo/$branch/$path"
        return @{
            Owner = $owner
            Repo = $repo
            Branch = $branch
            Path = $path
            RawUrl = $rawUrl
        }
    }
    
    throw "Unsupported GitHub URL format: $Url"
}

function Get-CurrentCommit {
    param(
        [string]$Owner,
        [string]$Repo,
        [string]$Branch,
        [string]$Path
    )
    
    $apiUrl = "https://api.github.com/repos/$Owner/$Repo/commits?path=$Path&sha=$Branch&per_page=1"
    
    $headers = @{}
    $ghToken = $env:GITHUB_TOKEN
    if ($ghToken) {
        $headers['Authorization'] = "token $ghToken"
        $headers['User-Agent'] = 'reference-pool'
    }
    
    try {
        $response = Invoke-RestMethod -Uri $apiUrl -Headers $headers -Method Get -ErrorAction Stop
        if ($response -and $response.Count -gt 0) {
            return $response[0].sha
        }
    } catch {
        # Rate limit or network issue - skip this entry
    }
    return $null
}


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

Test-PoolInitialized

$manifest = Read-Manifest -Path $script:MANIFEST_PATH
if ($manifest.schema_version -ne '1.0') {
    throw "Unsupported manifest schema_version: $($manifest.schema_version). Expected 1.0."
}

$cutoff = (Get-Date).AddDays(-$script:TTL_DAYS)
$toRefresh = $manifest.entries | Where-Object {
    $added = [DateTime]::Parse($_.added_at)
    return $added -lt $cutoff
}

if ($toRefresh.Count -eq 0) {
    Write-Host "reference-pool: no entries older than $($script:TTL_DAYS) days" -ForegroundColor Green
    exit 0
}

# An entry written before the language field existed resolves its cache path
# against the pool root, scattering the file outside {language}/ and leaving the
# real cache stale. Fail before any fetch instead of writing to the wrong place.
$missingLanguage = @($toRefresh | Where-Object { -not $_.language })
if ($missingLanguage.Count -gt 0) {
    $ids = ($missingLanguage | ForEach-Object { $_.id }) -join ', '
    throw "entry language missing for: $ids -- backfill the language field in $script:MANIFEST_PATH before refreshing."
}

Write-Host "reference-pool: $($toRefresh.Count) entries to refresh" -ForegroundColor Cyan

$headers = @{}
$ghToken = $env:GITHUB_TOKEN
if ($ghToken) {
    $headers['Authorization'] = "token $ghToken"
    $headers['User-Agent'] = 'reference-pool'
}

$refreshed = 0
$failed = 0

foreach ($entry in $toRefresh) {
    $parsed = Parse-GitHubUrl -Url $entry.source_url
    
    Write-Host "  refreshing $($entry.id)..." -NoNewline
    
    if ($DryRun) {
        Write-Host " [DRY] would re-fetch commit $($parsed.Owner)/$($parsed.Repo)@$($parsed.Branch)" -ForegroundColor Yellow
        $refreshed++
        continue
    }
    
    $newCommit = Get-CurrentCommit -Owner $parsed.Owner -Repo $parsed.Repo -Branch $parsed.Branch -Path $parsed.Path
    
    if (-not $newCommit) {
        Write-Host " SKIP (could not resolve commit)" -ForegroundColor DarkYellow
        $failed++
        continue
    }
    
    if ($newCommit -eq $entry.commit) {
        Write-Host " SKIP (already at $newCommit)" -ForegroundColor DarkGray
        continue
    }
    
    try {
        $newContent = Invoke-WebRequest -Uri $parsed.RawUrl -UseBasicParsing -ErrorAction Stop | Select-Object -ExpandProperty Content
    } catch {
        Write-Host " FAIL (fetch error)" -ForegroundColor Red
        $failed++
        continue
    }
    
    # Update cached file
    $langDir = Join-Path $script:POOL_ROOT $entry.language
    $authorRepo = $entry.repo -replace '/', '-'
    $targetDir = Join-Path $langDir $authorRepo
    $sanitized = $entry.file_path -replace '^[\\/]+', '' -replace '/', '\'
    $targetPath = Join-Path $targetDir $sanitized
    
    $targetFileDir = Split-Path -Parent $targetPath
    if (-not (Test-Path -LiteralPath $targetFileDir -PathType Container)) {
        New-Item -ItemType Directory -Path $targetFileDir -Force | Out-Null
    }
    
    $newContent | Set-Content -LiteralPath $targetPath -Encoding UTF8 -NoNewline
    
    # Update manifest entry
    $entry.commit = $newCommit
    $entry.added_at = (Get-Date -Format 'yyyy-MM-dd')
    
    Write-Host " OK ($newCommit)" -ForegroundColor Green
    $refreshed++
    
    # Small delay to avoid rate limits
    Start-Sleep -Milliseconds 500
}

Write-Manifest -Path $script:MANIFEST_PATH -Manifest $manifest

Write-Host ""
Write-Host "reference-pool: refreshed $refreshed entries, $failed failed" -ForegroundColor Cyan
