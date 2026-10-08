# test-self-review-protocol.ps1
# Static regression tests for the self-review protocol in 00-system.md
# Exit 0 on pass, non-zero on fail.

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\test-assertions.ps1"

$systemFile = Join-Path $PSScriptRoot "..\00-system.md"

# 1. Phase behavior: PLAN section present
Assert-FileContains -Path $systemFile -Pattern "## Phase behavior: PLAN" -Description "PLAN phase behavior section"

# 2. PLAN section mentions read-only
Assert-FileContains -Path $systemFile -Pattern "PLAN is read-only" -Description "PLAN read-only constraint"

# 3. PLAN section mentions zero exceptions
Assert-FileContains -Path $systemFile -Pattern "Zero exceptions" -Description "PLAN zero exceptions"

# 4. PLAN section mentions transition to PATCH requires approval
Assert-FileContains -Path $systemFile -Pattern "Transition to PATCH requires explicit user approval" -Description "PLAN transition gate"

# 5. Self-review protocol section present
Assert-FileContains -Path $systemFile -Pattern "## Self-review protocol" -Description "Self-review protocol section"

# 6. Self-review mentions DISCUSS, PATCH, REVIEW
Assert-FileContains -Path $systemFile -Pattern "DISCUSS, PATCH, and REVIEW" -Description "Self-review enabled phases"

# 7. Self-review mentions silent
Assert-FileContains -Path $systemFile -Pattern "This pass is silent" -Description "Self-review is silent"

# 8. Self-review mentions senior engineer perspective
Assert-FileContains -Path $systemFile -Pattern "senior engineer" -Description "Self-review perspective"

# 9. Self-review mentions auto-correct
Assert-FileContains -Path $systemFile -Pattern "Auto-correct" -Description "Self-review auto-correct dimension"

# 10. Self-review skip list includes CHECKLIST
Assert-FileContains -Path $systemFile -Pattern "Skip: CHECKLIST" -Description "Self-review skip list"

exit (Complete-TestRun -SuiteName 'self-review protocol static checks')
