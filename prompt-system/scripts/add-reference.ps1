<#
.SYNOPSIS
    Adds a reference file to the global reference pool.
.DESCRIPTION
    Fetches a file from GitHub, pins it to a specific commit (default: current
    HEAD), saves it to the pool, and appends a manifest entry. Auto-creates pool
    members for new authors/repos. Designed for both CLI and programmatic use.
#>

param(
    [Parameter(Mandatory)][string]$Url,
    [string]$Commit,
    [Parameter(Mandatory)][string]$Language,
    [Parameter(Mandatory)][string]$Domain,
    [Parameter(Mandatory)][string]$Keywords,
    [string]$Why,
    [string]$PoolWhy,
    [ValidateSet('unvetted', 'standard', 'premium')][string]$TrustLevel = 'unvetted',
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
    
    # Supports:
    # https://github.com/owner/repo/blob/branch/path/to/file
    # https://raw.githubusercontent.com/owner/repo/branch/path/to/file
    
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
    
    throw "Unsupported GitHub URL format: $Url. Expected github.com/blob/... or raw.githubusercontent.com/..."
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
        # If API fails (rate limit, unauthenticated), fall back to empty commit
        # and let the caller know via the result object.
    }
    return $null
}

function Get-PoolMember {
    param(
        [string]$Owner,
        [string]$Repo,
        [hashtable]$Manifest
    )
    
    foreach ($member in $Manifest.pool) {
        $isAuthor = ($member.type -eq 'author' -and $member.handle -eq $Owner)
        $isRepo = ($member.type -eq 'repo' -and $member.repo -eq "$Owner/$Repo")
        if ($isAuthor -or $isRepo) {
            return $member
        }
    }
    return $null
}

function New-PoolMember {
    param(
        [string]$Id,
        [string]$Type,
        [string]$Handle,
        [string]$Repo,
        [string[]]$Languages,
        [string[]]$Domains,
        [string]$TrustLevel,
        [string]$Why
    )
    
    return [ordered]@{
        id = $Id
        type = $Type
        handle = $Handle
        repo = $Repo
        languages = $Languages
        domains = $Domains
        trust_level = $TrustLevel
        added_at = (Get-Date -Format 'yyyy-MM-dd')
        why = $Why
    }
}

function New-Entry {
    param(
        [string]$Id,
        [string]$PoolId,
        [string]$Repo,
        [string]$FilePath,
        [string]$Language,
        [string]$Commit,
        [string]$SourceUrl,
        [string]$AddedAt,
        [string]$Why,
        [string[]]$PrimaryTags,
        [string[]]$SecondaryTags,
        [hashtable]$SynonymMap
    )
    
    $entry = [ordered]@{
        id = $Id
        pool_id = $PoolId
        repo = $Repo
        file_path = $FilePath
        language = $Language
        commit = $Commit
        source_url = $SourceUrl
        added_at = $AddedAt
        why = $Why
        primary_tags = $PrimaryTags
        secondary_tags = $SecondaryTags
    }
    
    if ($SynonymMap -and $SynonymMap.Count -gt 0) {
        $entry['synonym_map'] = $SynonymMap
    }
    
    return $entry
}

function Save-FileToPool {
    param(
        [string]$Language,
        [string]$AuthorRepo,
        [string]$FilePath,
        [string]$Content
    )
    
    $langDir = Join-Path $script:POOL_ROOT $Language
    if (-not (Test-Path -LiteralPath $langDir -PathType Container)) {
        New-Item -ItemType Directory -Path $langDir -Force | Out-Null
    }
    
    $targetDir = Join-Path $langDir $AuthorRepo
    if (-not (Test-Path -LiteralPath $targetDir -PathType Container)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }
    
    # Sanitize file path: remove leading slashes, normalize separators
    $sanitized = $FilePath -replace '^[\\/]+', '' -replace '/', '\'
    $targetPath = Join-Path $targetDir $sanitized
    
    $targetFileDir = Split-Path -Parent $targetPath
    if (-not (Test-Path -LiteralPath $targetFileDir -PathType Container)) {
        New-Item -ItemType Directory -Path $targetFileDir -Force | Out-Null
    }
    
    $Content | Set-Content -LiteralPath $targetPath -Encoding UTF8 -NoNewline
    return $targetPath
}


function Find-DuplicateEntry {
    param(
        [hashtable]$Manifest,
        [string]$Repo,
        [string]$FilePath,
        [string]$Commit
    )
    
    foreach ($entry in $Manifest.entries) {
        if ($entry.repo -eq $Repo -and $entry.file_path -eq $FilePath) {
            return $entry
        }
    }
    return $null
}

function New-EntryId {
    param([string]$PoolId, [string]$FilePath)
    
    $sanitized = $PoolId -replace '[^a-z0-9-]', '-'
    $fileSanitized = ($FilePath -replace '[^a-z0-9-]', '-' -replace '-+', '-').Trim('-')
    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    return "$sanitized-$fileSanitized-$timestamp"
}

# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

Test-PoolInitialized

$parsedUrl = Parse-GitHubUrl -Url $Url

# Determine commit
$commit = $Commit
if (-not $commit) {
    $commit = Get-CurrentCommit -Owner $parsedUrl.Owner -Repo $parsedUrl.Repo -Branch $parsedUrl.Branch -Path $parsedUrl.Path
    if (-not $commit) {
        Write-Warning "Could not resolve commit SHA for $Url. Using 'unknown' as fallback."
        $commit = 'unknown'
    }
}

# Fetch file content
try {
    $fileContent = Invoke-WebRequest -Uri $parsedUrl.RawUrl -UseBasicParsing -ErrorAction Stop | Select-Object -ExpandProperty Content
} catch {
    throw "Failed to fetch $($parsedUrl.RawUrl): $_"
}

# Read manifest
$manifest = Read-Manifest -Path $script:MANIFEST_PATH
if ($manifest.schema_version -ne '1.0') {
    throw "Unsupported manifest schema_version: $($manifest.schema_version). Expected 1.0."
}

# Determine or create pool member
$existingMember = Get-PoolMember -Owner $parsedUrl.Owner -Repo $parsedUrl.Repo -Manifest $manifest
$poolId = $null
$poolMemberCreated = $false

if ($existingMember) {
    $poolId = $existingMember.id
} else {
    $poolId = "$($parsedUrl.Owner)-$($parsedUrl.Repo)"
    $poolId = $poolId.ToLower().Replace('/', '-').Replace('.', '-')
    
    $memberWhy = $PoolWhy
    if (-not $memberWhy) {
        $memberWhy = "Auto-created from $Url"
    }
    
    $newMember = New-PoolMember `
        -Id $poolId `
        -Type 'repo' `
        -Handle $parsedUrl.Owner `
        -Repo "$($parsedUrl.Owner)/$($parsedUrl.Repo)" `
        -Languages @($Language) `
        -Domains @($Domain) `
        -TrustLevel $TrustLevel `
        -Why $memberWhy
    
    $manifest.pool += $newMember
    $poolMemberCreated = $true
}

# Check for duplicate entry (same repo + file_path)
$duplicate = Find-DuplicateEntry -Manifest $manifest -Repo "$($parsedUrl.Owner)/$($parsedUrl.Repo)" -FilePath $parsedUrl.Path -Commit $commit
$entryId = New-EntryId -PoolId $poolId -FilePath $parsedUrl.Path
$authorRepo = "$($parsedUrl.Owner)-$($parsedUrl.Repo)"

if ($duplicate) {
    if ($duplicate.commit -eq $commit) {
        # Same file, same commit: refuse
        throw "Entry already exists: $($duplicate.id) (repo=$($duplicate.repo), file=$($duplicate.file_path), commit=$commit)"
    }
    
    # Same file, different commit: override with newer version
    $duplicate.commit = $commit
    $duplicate.added_at = (Get-Date -Format 'yyyy-MM-dd')
    $duplicate.why = $Why
    # Entries written before the language field existed need it backfilled, or
    # refresh rebuilds their cache path against the pool root.
    $duplicate.language = $Language
    $duplicate.primary_tags = ($Keywords -split ',').Trim()
    $duplicate.secondary_tags = @()
    
    # Update cached file
    Save-FileToPool -Language $Language -AuthorRepo $authorRepo -FilePath $parsedUrl.Path -Content $fileContent
    
    if ($DryRun) {
        Write-Host "[DRY] Would update entry $($duplicate.id) with commit $commit" -ForegroundColor Yellow
        return
    }
    
    Write-Manifest -Path $script:MANIFEST_PATH -Manifest $manifest
    Write-Host "reference-pool: updated entry $($duplicate.id) to commit $commit" -ForegroundColor Green
    return
}

# New entry
$tags = ($Keywords -split ',').Trim()
$primaryTags = $tags
$secondaryTags = @()

$synonymMap = @{}
$entry = New-Entry `
    -Id $entryId `
    -PoolId $poolId `
    -Repo "$($parsedUrl.Owner)/$($parsedUrl.Repo)" `
    -FilePath $parsedUrl.Path `
    -Language $Language `
    -Commit $commit `
    -SourceUrl $Url `
    -AddedAt (Get-Date -Format 'yyyy-MM-dd') `
    -Why $Why `
    -PrimaryTags $primaryTags `
    -SecondaryTags $secondaryTags `
    -SynonymMap $synonymMap

$manifest.entries += $entry

# Save cached file
$poolPath = Save-FileToPool -Language $Language -AuthorRepo $authorRepo -FilePath $parsedUrl.Path -Content $fileContent

if ($DryRun) {
    Write-Host "[DRY] Would add entry $entryId" -ForegroundColor Yellow
    Write-Host "  Pool: $poolId" -ForegroundColor Gray
    Write-Host "  File: $poolPath" -ForegroundColor Gray
    Write-Host "  Commit: $commit" -ForegroundColor Gray
    return
}

Write-Manifest -Path $script:MANIFEST_PATH -Manifest $manifest
Write-Host "reference-pool: added $entryId" -ForegroundColor Green
Write-Host "  Pool: $poolId $(if ($poolMemberCreated) {'(new)'} else {'(existing)'})" -ForegroundColor Gray
Write-Host "  File: $poolPath" -ForegroundColor Gray
Write-Host "  Commit: $commit" -ForegroundColor Gray
