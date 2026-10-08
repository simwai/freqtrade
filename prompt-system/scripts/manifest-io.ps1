<#
.SYNOPSIS
    Single owner of reference-pool manifest serialization.
.DESCRIPTION
    Read-Manifest and Write-Manifest for the global reference pool manifest.
    Every pool script routes manifest IO through this module so the schema has
    exactly one implementation; the parser used to be duplicated verbatim in
    three scripts, which is how a single defect could ship three times over.
#>

function Read-Manifest {
    param([string]$Path)

    $content = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if (-not $content) { return @{ schema_version = ''; pool = @(); entries = @() } }

    # Minimal YAML parser for our specific schema. Supports:
    # - Top-level scalar: key: "value"
    # - List of scalars: key: [a, b, c]
    # - List of mappings: key: [ { k: v }, { k: v } ]
    # - Nested mappings with 2-space indent
    # Does NOT support multi-line strings, anchors, or complex YAML.

    $lines = $content -split "`n"
    $result = @{ schema_version = ''; pool = @(); entries = @() }
    $currentSection = ''
    $inList = $false
    $currentItem = @{}
    $listKey = ''
    $nestDepth = 0
    $nestKey = ''
    $listKeys = @('pool', 'entries')

    foreach ($line in $lines) {
        if ($line -match '^\s*#') { continue }
        if ($line -match '^\s*$') { continue }

        # Top-level section: key: value or key: [items]
        if ($line -match '^([a-z_]+):\s*(.*)$') {
            $key = $matches[1]
            $value = $matches[2].Trim()

            if ($currentSection -and $inList -and $currentItem.Count -gt 0) {
                if ($listKey -eq 'pool') { $result.pool += $currentItem }
                elseif ($listKey -eq 'entries') { $result.entries += $currentItem }
                $currentItem = @{}
            }
            $inList = $false
            $nestDepth = 0

            if ($value -eq '[' -or $value -match '^\[.*\]$') {
                # Inline list (single line)
                if ($value -eq '[]') {
                    $items = @()
                } elseif ($value -match '^\[(.+)\]$') {
                    $inner = $matches[1]
                    $items = $inner -split ',\s*' | ForEach-Object { $_.Trim().Trim('"', "'") }
                } else {
                    # Start of multi-line list
                    $inList = $true
                    $listKey = $key
                    $currentSection = $key
                    continue
                }
                if ($key -eq 'languages' -or $key -eq 'domains' -or $key -eq 'primary_tags' -or $key -eq 'secondary_tags') {
                    $currentItem[$key] = $items
                } elseif ($key -eq 'synonym_map') {
                    # skip inline synonym_map; handled below in block mode
                } else {
                    $result[$key] = $items
                }
            } elseif ($value -match '^-') {
                # Start of list item
                $inList = $true
                $listKey = $key
                $currentSection = $key
                $itemValue = $value.TrimStart('-').Trim()
                if ($itemValue) {
                    $currentItem = @{ $key = $itemValue }
                } else {
                    $currentItem = @{}
                }
            } elseif ($value -eq '' -and $listKeys -contains $key) {
                # Empty value for a known list key = start of multi-line list
                $inList = $true
                $listKey = $key
                $currentSection = $key
                $currentItem = @{}
            } else {
                $result[$key] = $value.Trim('"', "'")
                if ($key -eq 'schema_version') { $result.schema_version = $result[$key] }
                $currentSection = $key
            }
            continue
        }

        # Nested list item:   - key: value
        # Matched before the top-level item branch below: a nested entry belongs
        # to the item currently being built, so treating it as a new item would
        # truncate that item.
        if ($line -match '^\s+-\s+([a-z_]+):\s*(.*)$' -and $nestDepth -gt 0) {
            $k = $matches[1]
            $v = $matches[2].Trim().Trim('"', "'")
            if ($currentItem.ContainsKey($nestKey)) {
                $currentItem[$nestKey] += @{ $k = $v }
            }
            continue
        }

        # List item continuation: - value
        if ($line -match '^\s*-\s+(.+)$' -and $inList) {
            $itemValue = $matches[1].Trim()

            # A new item begins here, so the previous one is complete. Without
            # this flush every item but the last is overwritten and the manifest
            # silently loses pool members and entries.
            if ($currentItem.Count -gt 0) {
                if ($listKey -eq 'pool') { $result.pool += $currentItem }
                elseif ($listKey -eq 'entries') { $result.entries += $currentItem }
                $currentItem = @{}
            }

            if ($itemValue -match '^([a-z_]+):\s*(.*)$') {
                $k = $matches[1]
                $v = $matches[2].Trim().Trim('"', "'")
                if ($v -eq '[') {
                    $nestDepth = 1
                    $nestKey = $k
                    $currentItem[$k] = @()
                } elseif ($v -match '^\d+$') {
                    $currentItem[$k] = [int]$v
                } else {
                    $currentItem[$k] = $v
                }
            } else {
                $currentItem[$currentSection] = $itemValue
            }
            continue
        }

        # Indented key: value inside list item
        if ($line -match '^\s+([a-z_]+):\s*(.*)$' -and $inList) {
            $k = $matches[1]
            $v = $matches[2].Trim()

            if ($v -eq '[') {
                $nestDepth = 1
                $nestKey = $k
                $currentItem[$k] = @()
            } elseif ($v -eq '[]') {
                $currentItem[$k] = @()
                $nestDepth = 0
                $nestKey = ''
            } elseif ($v -match '^\[(.+)\]$') {
                $items = $matches[1] -split ',\s*' | ForEach-Object { $_.Trim().Trim('"', "'") }
                $currentItem[$k] = $items
                $nestDepth = 0
                $nestKey = ''
            } elseif ($v -match '^-') {
                $currentItem[$k] = $v.TrimStart('-').Trim().Trim('"', "'")
            } else {
                $currentItem[$k] = $v.Trim('"', "'")
            }
            continue
        }

        # Nested list continuation inside synonym_map:   - key: [a, b]
        if ($line -match '^\s+-\s+([a-z_]+):\s*\[(.+)\]$' -and $inList) {
            $k = $matches[1]
            $items = $matches[2] -split ',\s*' | ForEach-Object { $_.Trim().Trim('"', "'") }
            if ($currentItem.ContainsKey($k)) {
                if ($currentItem[$k] -isnot [System.Collections.IList]) {
                    $currentItem[$k] = @($currentItem[$k])
                }
                $currentItem[$k] += $items
            } else {
                $currentItem[$k] = $items
            }
            continue
        }
    }

    # Flush last item
    if ($currentSection -and $inList -and $currentItem.Count -gt 0) {
        if ($listKey -eq 'pool') { $result.pool += $currentItem }
        elseif ($listKey -eq 'entries') { $result.entries += $currentItem }
    }

    return $result
}

function Write-Manifest {
    param(
        [string]$Path,
        [hashtable]$Manifest
    )

    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.AppendLine("schema_version: `"$($Manifest.schema_version)`"")
    [void]$sb.AppendLine('pool:')

    foreach ($member in $Manifest.pool) {
        [void]$sb.AppendLine("  - id: `"$($member.id)`"")
        [void]$sb.AppendLine("    type: `"$($member.type)`"")
        [void]$sb.AppendLine("    handle: `"$($member.handle)`"")
        if ($member.repo) { [void]$sb.AppendLine("    repo: `"$($member.repo)`"") }
        [void]$sb.AppendLine("    languages: [$(($member.languages -join ', '))]")
        [void]$sb.AppendLine("    domains: [$(($member.domains -join ', '))]")
        [void]$sb.AppendLine("    trust_level: `"$($member.trust_level)`"")
        [void]$sb.AppendLine("    added_at: `"$($member.added_at)`"")
        [void]$sb.AppendLine("    why: `"$($member.why)`"")
    }

    [void]$sb.AppendLine('entries:')

    foreach ($entry in $Manifest.entries) {
        [void]$sb.AppendLine("  - id: `"$($entry.id)`"")
        [void]$sb.AppendLine("    pool_id: `"$($entry.pool_id)`"")
        [void]$sb.AppendLine("    repo: `"$($entry.repo)`"")
        [void]$sb.AppendLine("    file_path: `"$($entry.file_path)`"")
        # Entries carry their language because refresh rebuilds the cached-file
        # path from it; without the field the path collapses to the pool root.
        if ($entry.language) { [void]$sb.AppendLine("    language: `"$($entry.language)`"") }
        [void]$sb.AppendLine("    commit: `"$($entry.commit)`"")
        [void]$sb.AppendLine("    source_url: `"$($entry.source_url)`"")
        [void]$sb.AppendLine("    added_at: `"$($entry.added_at)`"")
        [void]$sb.AppendLine("    why: `"$($entry.why)`"")
        [void]$sb.AppendLine("    primary_tags: [$(($entry.primary_tags -join ', '))]")
        [void]$sb.AppendLine("    secondary_tags: [$(($entry.secondary_tags -join ', '))]")

        if ($entry.synonym_map -and $entry.synonym_map.Count -gt 0) {
            [void]$sb.AppendLine('    synonym_map:')
            foreach ($synKey in $entry.synonym_map.Keys) {
                $syns = $entry.synonym_map[$synKey]
                if ($syns -is [string]) { $syns = @($syns) }
                [void]$sb.AppendLine("      $synKey : [$($syns -join ', ')]")
            }
        }
    }

    $sb.ToString() | Set-Content -LiteralPath $Path -Encoding UTF8 -NoNewline
}
