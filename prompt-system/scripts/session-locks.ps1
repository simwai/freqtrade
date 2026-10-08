<#
.SYNOPSIS
    Session file locks for two editing sessions sharing one checkout.
.DESCRIPTION
    One file, one writer. A session holds a lock on a path from its first write
    until the commit lands, so two sessions cannot silently bundle each other's
    uncommitted hunks into a single commit.

    Enforcement lives at the commit gate, not mid-edit. A mid-edit block can
    wedge the very session that legitimately holds the lock, and the commit is
    where the hunk-bundling hazard actually occurs. Contention is surfaced as
    data here and acted on by the caller.

    A lock is never auto-stolen. A contended path always returns the user-owned
    decision set; this module never picks for them.

    Session identity resolves from SESSION_ID, else a per-process generated id
    cached for the process lifetime so acquire/verify/release agree on one owner.

    Inert on a READ_ONLY host: every entry point returns Skipped instead of
    touching the filesystem.

    Every entry point accepts an explicit -RepoRoot so it can be exercised
    against a fixture. Only the default path consults git.
.EXAMPLE
    . session-locks.ps1
    $lock = Enter-FileLock -RepoRelativePath 'src/app.ts'
.NOTES
    Dot-source this file. Loading defines functions and performs no work; it is
    not meant to be executed directly.
#>

$ErrorActionPreference = 'Stop'

# A lock older than this is treated as abandoned. Liveness is read from the
# acquired_at file only; directory mtime is never consulted because ordinary
# tooling touches it.
$script:LockTtlMinutes = 30

# Import specifier extensions tried when a relative import carries none. Ordered
# so a real file beats a directory index.
$script:ImportExtensions = @('', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.py', '.ps1', '/index.ts', '/index.tsx', '/index.js')

# Cached so every entry point in one process reports the same owner. A per-call
# fallback would make acquire/verify/release disagree and misattribute a lock.
$script:CachedSessionId = $null

function Resolve-RepoRoot {
    param([string]$RepoRoot)
    if ($RepoRoot) { return $RepoRoot }
    $root = (& git rev-parse --show-toplevel 2>$null)
    if (-not $root) { throw 'Not in a git repository' }
    return $root
}

function Get-SessionId {
    if ($script:CachedSessionId) { return $script:CachedSessionId }
    if ($env:SESSION_ID) { $script:CachedSessionId = $env:SESSION_ID; return $script:CachedSessionId }
    $script:CachedSessionId = "session-$(Get-Date -Format 'yyyyMMddTHHmmss')-$PID-$((Get-Random -Minimum 1000 -Maximum 9999))"
    return $script:CachedSessionId
}

function Test-ReadOnlyHost {
    # Set by the agent from its session carrier when the host cannot write.
    if ($env:BABA_READ_ONLY -in @('1', 'true', 'yes')) { return $true }
    return $false
}

function Get-LockRoot {
    param([string]$RepoRoot)
    return Join-Path $RepoRoot '.session-locks'
}

# Path separators become -- so one lock directory can hold a full relative path.
function ConvertTo-FlatName {
    param([string]$RepoRelativePath)
    $normalized = $RepoRelativePath -replace '\\', '/'
    return ($normalized -replace '^[./]+', '') -replace '[/\\]', '--'
}

function Get-LockPath {
    param([string]$RepoRoot, [string]$FlatName)
    return Join-Path (Get-LockRoot $RepoRoot) "$FlatName.lock"
}

function Get-RepoRelativePath {
    param([string]$RepoRoot, [string]$AbsolutePath)
    $root = $RepoRoot.TrimEnd('\', '/')
    $full = [System.IO.Path]::GetFullPath($AbsolutePath)
    if ($full.Length -le $root.Length) { return $full }
    return ($full.Substring($root.Length + 1)) -replace '\\', '/'
}

# Stage the lock in a private directory and move it into place. Directory.Move
# fails when the destination exists, which makes it the atomic exclusive
# primitive here. [System.IO.Directory]::CreateDirectory is NOT exclusive -- it
# succeeds silently on an existing directory and would hand the same lock to two
# sessions.
function New-LockDirectoryAtomic {
    param([string]$LockPath, [string]$Owner, [string[]]$Dependencies)

    $parent = Split-Path -Parent $LockPath
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    $staging = "$LockPath.$PID.tmp"
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }

    New-Item -ItemType Directory -Path $staging | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $staging 'owner'), $Owner)
    [System.IO.File]::WriteAllText((Join-Path $staging 'acquired_at'), (Get-Date).ToUniversalTime().ToString('o'))
    if ($Dependencies -and $Dependencies.Count -gt 0) {
        [System.IO.File]::WriteAllLines((Join-Path $staging 'dependencies.txt'), $Dependencies)
    }

    try {
        [System.IO.Directory]::Move($staging, $LockPath)
    } catch {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
        throw
    }
}

function Read-LockInfo {
    param([string]$LockPath)
    $info = @{ Owner = $null; AcquiredAt = $null; Dependencies = @() }
    if (-not (Test-Path -LiteralPath $LockPath)) { return $info }

    $ownerPath = Join-Path $LockPath 'owner'
    if (Test-Path -LiteralPath $ownerPath) { $info.Owner = ([System.IO.File]::ReadAllText($ownerPath)).Trim() }

    $acquiredPath = Join-Path $LockPath 'acquired_at'
    if (Test-Path -LiteralPath $acquiredPath) { $info.AcquiredAt = [System.IO.File]::ReadAllText($acquiredPath) }

    $depsPath = Join-Path $LockPath 'dependencies.txt'
    if (Test-Path -LiteralPath $depsPath) {
        $info.Dependencies = @([System.IO.File]::ReadAllLines($depsPath) | Where-Object { $_.Trim() })
    }
    return $info
}

function Test-LockLive {
    param([string]$AcquiredAt, [int]$TtlMinutes = $script:LockTtlMinutes)
    if (-not $AcquiredAt) { return $false }
    try {
        $acquired = [DateTime]::Parse($AcquiredAt).ToUniversalTime()
    } catch {
        # An unparseable timestamp is treated as dead, not live: a corrupt clock
        # must not grant an abandoned lock an indefinite reprieve.
        return $false
    }
    return ((Get-Date).ToUniversalTime() - $acquired).TotalMinutes -lt $TtlMinutes
}

function Remove-LockDirectory {
    param([string]$LockPath)
    if (Test-Path -LiteralPath $LockPath) {
        Remove-Item -LiteralPath $LockPath -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# ═══════════════════════════════════════════════════════════════════════════
# Dependency discovery
# ═══════════════════════════════════════════════════════════════════════════

# Resolves a relative import specifier to a concrete repo-relative path.
# Returns $null for bare specifiers (external packages) and for anything that
# does not land on a real file.
function Resolve-ImportSpecifier {
    param(
        [string]$RepoRoot,
        [string]$FromFileRelative,
        [string]$Specifier
    )

    if ([string]::IsNullOrWhiteSpace($Specifier)) { return $null }
    # Bare or scoped specifier -- a package, not a repo path.
    if ($Specifier -notmatch '^[./]') { return $null }

    $fromDir = Split-Path -Parent (Join-Path $RepoRoot $FromFileRelative)
    if (-not $fromDir) { $fromDir = $RepoRoot }

    foreach ($ext in $script:ImportExtensions) {
        $candidate = Join-Path $fromDir ($Specifier + $ext)
        try {
            $full = [System.IO.Path]::GetFullPath($candidate)
        } catch {
            continue
        }
        if (Test-Path -LiteralPath $full -PathType Leaf) {
            return Get-RepoRelativePath -RepoRoot $RepoRoot -AbsolutePath $full
        }
    }
    return $null
}

# Depth-1 dependency set for a path: files that import it (Importers) and files
# it imports (Imports).
#
# Specifiers are resolved to real paths rather than matched by leaf filename.
# The earlier revision fell back to a leaf-name regex, so src/a/index.ts and
# src/b/index.ts were reported as dependents of one another; resolving the
# specifier removes that false positive by construction.
function Get-DependencySet {
    param(
        [string]$RepoRoot,
        [string]$TargetFileRelative
    )

    $result = @{ Root = $null; Importers = @(); Imports = @() }
    if (-not (Get-Command rg -ErrorAction SilentlyContinue)) { return $result }

    $target = ($TargetFileRelative -replace '\\', '/')
    $result.Root = $target

    $rootFull = [System.IO.Path]::GetFullPath($RepoRoot)
    $quote = [char]39
    # \x22 stands in for a literal double quote: a raw " inside a native argument
    # breaks PowerShell 5.1 argument passing and kills the call with a regex
    # parse error.
    $pattern = "(?:from|import|require)\s*\(?\s*[$quote\x22]([^$quote\x22]+)[$quote\x22]"

    $rgArgs = @(
        '--no-heading', '-n', '-o',
        '--replace', '$1',
        '--glob', '*.ts',
        '--glob', '*.tsx',
        '--glob', '*.js',
        '--glob', '*.jsx',
        '--glob', '*.mjs',
        '--glob', '*.cjs',
        '--glob', '*.py',
        '--glob', '*.ps1',
        '--glob', '!node_modules/**',
        '--glob', '!.git/**',
        '--glob', '!dist/**',
        '--glob', '!build/**',
        '--glob', '!prompt-system/**',
        $pattern,
        $rootFull
    )

    $hits = & rg @rgArgs 2>$null
    if (-not $hits) { return $result }

    $importers = New-Object 'System.Collections.Generic.HashSet[string]'
    $imports = New-Object 'System.Collections.Generic.HashSet[string]'

    foreach ($hit in $hits) {
        # Format is path:line:specifier. Split from the RIGHT: on Windows the path
        # itself contains a colon (the drive letter), so a left-to-right split
        # truncates the path to "C" and every hit is discarded.
        $lastColon = $hit.LastIndexOf(':')
        if ($lastColon -lt 1) { continue }
        $prevColon = $hit.LastIndexOf(':', $lastColon - 1)
        if ($prevColon -lt 1) { continue }

        $fromAbsolute = $hit.Substring(0, $prevColon)
        $specifier = $hit.Substring($lastColon + 1).Trim()
        if (-not $specifier) { continue }
        if (-not (Test-Path -LiteralPath $fromAbsolute -PathType Leaf)) { continue }

        $fromRelative = Get-RepoRelativePath -RepoRoot $RepoRoot -AbsolutePath $fromAbsolute
        $resolved = Resolve-ImportSpecifier -RepoRoot $RepoRoot -FromFileRelative $fromRelative -Specifier $specifier

        if (-not $resolved) { continue }

        if ($resolved -eq $target) {
            [void]$importers.Add($fromRelative)
        } elseif ($fromRelative -eq $target) {
            [void]$imports.Add($resolved)
        }
    }

    $result.Importers = @($importers)
    $result.Imports = @($imports)
    return $result
}

# ═══════════════════════════════════════════════════════════════════════════
# Acquisition
# ═══════════════════════════════════════════════════════════════════════════

# The user-owned choice set returned on contention. This module never selects.
$script:ContentionDecision = @('Wait for the peer to release', 'Skip this path', 'Ask the peer to release')

function Enter-FileLock {
    param(
        [string]$RepoRelativePath,
        [string]$SessionId = (Get-SessionId),
        [int]$TtlMinutes = $script:LockTtlMinutes,
        [string]$RepoRoot
    )

    if (Test-ReadOnlyHost) { return @{ Success = $true; Skipped = $true; Reason = 'READ_ONLY host' } }

    $repoRoot = Resolve-RepoRoot $RepoRoot
    $flat = ConvertTo-FlatName $RepoRelativePath
    $lockPath = Get-LockPath -RepoRoot $repoRoot -FlatName $flat

    $covering = @(Get-BlockingPeers -RepoRoot $repoRoot -RepoRelativePath $RepoRelativePath -SessionId $SessionId -TtlMinutes $TtlMinutes)
    if ($covering.Count -gt 0) {
        return @{
            Success = $false
            Blocked = $true
            Path = $RepoRelativePath
            LockPath = $lockPath
            Peers = $covering
            Decision = $script:ContentionDecision
        }
    }

    try {
        New-LockDirectoryAtomic -LockPath $lockPath -Owner $SessionId
        return @{ Success = $true; Path = $RepoRelativePath; LockPath = $lockPath; Refreshed = $false }
    } catch {
        $info = Read-LockInfo $lockPath
        if ($info.Owner -eq $SessionId) {
            # Self-owned. Re-entering refreshes the timestamp so an actively used
            # lock cannot expire underneath a long PATCH.
            Remove-LockDirectory $lockPath
            New-LockDirectoryAtomic -LockPath $lockPath -Owner $SessionId
            return @{ Success = $true; Path = $RepoRelativePath; LockPath = $lockPath; Refreshed = $true }
        }

        # An expired lock is abandoned, and an abandoned lock must be reclaimable
        # or the TTL is decorative: detection would call it dead while
        # acquisition still refused. Removing one is not auto-stealing, because no
        # live session can be holding it.
        if (-not (Test-LockLive $info.AcquiredAt $TtlMinutes)) {
            Remove-LockDirectory $lockPath
            New-LockDirectoryAtomic -LockPath $lockPath -Owner $SessionId
            return @{ Success = $true; Path = $RepoRelativePath; LockPath = $lockPath; Reclaimed = $true; ReclaimedFrom = $info.Owner }
        }

        return @{
            Success = $false
            Blocked = $true
            Path = $RepoRelativePath
            LockPath = $lockPath
            Peers = @(@{
                Path = $RepoRelativePath
                Owner = $info.Owner
                AcquiredAt = $info.AcquiredAt
                Live = $true
                Type = 'PerFile'
            })
            Decision = $script:ContentionDecision
        }
    }
}

function Enter-DependencyLock {
    param(
        [string]$RepoRelativePath,
        [string]$SessionId = (Get-SessionId),
        [int]$TtlMinutes = $script:LockTtlMinutes,
        [string]$RepoRoot
    )

    if (Test-ReadOnlyHost) { return @{ Success = $true; Skipped = $true; Reason = 'READ_ONLY host' } }

    $repoRoot = Resolve-RepoRoot $RepoRoot
    $depSet = Get-DependencySet -RepoRoot $repoRoot -TargetFileRelative $RepoRelativePath
    $members = @(@($depSet.Root) + @($depSet.Importers) + @($depSet.Imports)) | Where-Object { $_ }

    $flat = ConvertTo-FlatName $RepoRelativePath
    $lockPath = Get-LockPath -RepoRoot $repoRoot -FlatName $flat

    # Plain array, not a generic List: the counts are single digits and @()
    # around a List[object] misbehaves inside a hashtable literal.
    $conflicts = @()
    foreach ($member in $members) {
        $memberLock = Get-LockPath -RepoRoot $repoRoot -FlatName (ConvertTo-FlatName $member)
        if (-not (Test-Path -LiteralPath $memberLock)) { continue }
        $info = Read-LockInfo $memberLock
        if ($info.Owner -eq $SessionId) { continue }
        if (Test-LockLive $info.AcquiredAt $TtlMinutes) {
            $conflicts += @{ Path = $member; Owner = $info.Owner; AcquiredAt = $info.AcquiredAt; Type = 'PerFile' }
        }
    }

    if (@($conflicts).Count -gt 0) {
        return @{
            Success = $false
            Blocked = $true
            Path = $RepoRelativePath
            LockPath = $lockPath
            Members = @($members)
            Peers = @($conflicts)
            Decision = $script:ContentionDecision
        }
    }

    try {
        New-LockDirectoryAtomic -LockPath $lockPath -Owner $SessionId -Dependencies $members
        return @{ Success = $true; Path = $RepoRelativePath; LockPath = $lockPath; Members = @($members) }
    } catch {
        $info = Read-LockInfo $lockPath
        return @{
            Success = $false
            Blocked = $true
            Path = $RepoRelativePath
            LockPath = $lockPath
            Members = @($members)
            Peers = @(@{ Path = $RepoRelativePath; Owner = $info.Owner; Type = 'PerFile' })
            Decision = $script:ContentionDecision
        }
    }
}

# ═══════════════════════════════════════════════════════════════════════════
# Release
# ═══════════════════════════════════════════════════════════════════════════

function Exit-FileLock {
    param(
        [string]$RepoRelativePath,
        [string]$SessionId = (Get-SessionId),
        [string]$RepoRoot
    )

    if (Test-ReadOnlyHost) { return @{ Success = $true; Skipped = $true; Reason = 'READ_ONLY host' } }

    $repoRoot = Resolve-RepoRoot $RepoRoot
    $lockPath = Get-LockPath -RepoRoot $repoRoot -FlatName (ConvertTo-FlatName $RepoRelativePath)

    if (-not (Test-Path -LiteralPath $lockPath)) {
        return @{ Success = $true; AlreadyReleased = $true; Path = $RepoRelativePath }
    }

    $info = Read-LockInfo $lockPath
    if ($info.Owner -ne $SessionId) {
        # Releasing a peer's lock would erase its ownership record while it is
        # still writing. Refused rather than repaired.
        return @{
            Success = $false
            Refused = $true
            Path = $RepoRelativePath
            Owner = $info.Owner
            Reason = 'lock is owned by another session'
        }
    }

    Remove-LockDirectory $lockPath
    return @{ Success = $true; Path = $RepoRelativePath }
}

function Exit-DependencyLock {
    param(
        [string]$RepoRelativePath,
        [string]$SessionId = (Get-SessionId),
        [string]$RepoRoot
    )
    return Exit-FileLock -RepoRelativePath $RepoRelativePath -SessionId $SessionId -RepoRoot $RepoRoot
}

# ═══════════════════════════════════════════════════════════════════════════
# Query -- the commit gate reads this
# ═══════════════════════════════════════════════════════════════════════════

# Every live peer lock touching a path: a per-file lock on it, or any live
# dependency lock whose member set covers it. Self-owned locks are excluded,
# which is what keeps the gate from blocking the session doing the committing.
function Get-BlockingPeers {
    param(
        [string]$RepoRoot,
        [string]$RepoRelativePath,
        [string]$SessionId = (Get-SessionId),
        [int]$TtlMinutes = $script:LockTtlMinutes
    )

    $peers = @()
    $lockRoot = Get-LockRoot $RepoRoot
    if (-not (Test-Path -LiteralPath $lockRoot)) { return $peers }

    $targetFlat = ConvertTo-FlatName $RepoRelativePath

    foreach ($dir in Get-ChildItem -LiteralPath $lockRoot -Directory -Filter '*.lock' -ErrorAction SilentlyContinue) {
        $info = Read-LockInfo $dir.FullName
        if ($info.Owner -eq $SessionId) { continue }
        if (-not (Test-LockLive $info.AcquiredAt $TtlMinutes)) { continue }

        # A lock sitting on the target path reports Dependency when it also carries a
        # member set, because the peer reserved related paths too and the caller
        # needs that scope to warn about a wider conflict.
        if ($dir.Name -eq "$targetFlat.lock") {
            $isDependencyScope = @($info.Dependencies).Count -gt 0
            $peers += @{
                Path = $RepoRelativePath
                Owner = $info.Owner
                AcquiredAt = $info.AcquiredAt
                Type = $(if ($isDependencyScope) { 'Dependency' } else { 'PerFile' })
                LockPath = $dir.FullName
                HeldFor = $RepoRelativePath
                Members = @($info.Dependencies)
            }
            continue
        }

        foreach ($member in $info.Dependencies) {
            if ((ConvertTo-FlatName $member) -eq $targetFlat) {
                $peers += @{
                    Path = $RepoRelativePath
                    Owner = $info.Owner
                    AcquiredAt = $info.AcquiredAt
                    Type = 'Dependency'
                    LockPath = $dir.FullName
                    HeldFor = $member
                }
                break
            }
        }
    }

    return @($peers)
}

# Batch form used by the commit gate. One entry per conflicting path, so the
# whole change set is reported in a single refusal rather than one path per
# round trip.
function Get-BlockingPeersForPaths {
    param(
        [string[]]$RepoRelativePaths,
        [string]$SessionId = (Get-SessionId),
        [int]$TtlMinutes = $script:LockTtlMinutes,
        [string]$RepoRoot
    )

    $repoRoot = Resolve-RepoRoot $RepoRoot
    $conflicts = @()
    foreach ($path in ($RepoRelativePaths | Where-Object { $_ })) {
        $peers = @(Get-BlockingPeers -RepoRoot $repoRoot -RepoRelativePath $path -SessionId $SessionId -TtlMinutes $TtlMinutes)
        if ($peers.Count -gt 0) {
            $conflicts += @{ Path = $path; Peers = $peers }
        }
    }
    return @($conflicts)
}

function Get-LockStatus {
    param(
        [string]$SessionId = (Get-SessionId),
        [int]$TtlMinutes = $script:LockTtlMinutes,
        [string]$RepoRoot
    )

    $repoRoot = Resolve-RepoRoot $RepoRoot
    $lockRoot = Get-LockRoot $repoRoot

    $locks = @()
    if (Test-Path -LiteralPath $lockRoot) {
        foreach ($dir in Get-ChildItem -LiteralPath $lockRoot -Directory -Filter '*.lock' -ErrorAction SilentlyContinue) {
            $info = Read-LockInfo $dir.FullName
            $locks += @{
                LockPath = $dir.FullName
                Owner = $info.Owner
                AcquiredAt = $info.AcquiredAt
                Live = (Test-LockLive $info.AcquiredAt $TtlMinutes)
                Members = @($info.Dependencies)
            }
        }
    }
    return @{ SessionId = $SessionId; LockRoot = $lockRoot; Locks = @($locks) }
}
