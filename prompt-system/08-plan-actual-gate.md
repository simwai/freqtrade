# 08-plan-actual-gate

Plan-Versus-Actual Gate verification protocol. Extracted from `06-misc.md` for clarity and testability.

## Plan-Versus-Actual Gate

A user-approved plan lists `Will change` items; this gate runs after staging and before the commit/push ask, and confirms that each item actually landed in the staged working tree. The gate is the answer to "the plan said X, Y, Z - did all three really make it in?" A miss is not a soft warning; it is a hard gate. The commit is refused until the gap is fixed or the user re-plans.

The runner MUST execute each verify command automatically after staging and before the commit/push ask; emitting the command text without running it is a gate FAIL.

### Source of truth

The approved plan's `Will change` list, persisted in the session context as `## Plan Approval -- approved_will_change` records. Each record has the shape `{id, change, verify, expect}`. The gate never re-parses the PLAN response at commit time; it uses the persisted, user-approved form. A record with no `verify` field is a coverage gap and is recorded as `SKIPPED: <id> -- no verify command` and counts as a miss.

### `expect` vocabulary

The `expect` field on each `Will change` item is one of:

| Value          | Pass criterion                                 |
| -------------- | ---------------------------------------------- |
| `pass`         | exit code 0                                    |
| `fail`         | exit code non-zero                             |
| `exit:N`       | exit code exactly N                            |
| `regex:<pat>`  | exit 0 and a regex match against stdout        |
| `contains:` | exit 0 and the literal text appears in stdout  |
| `silent`       | exit 0 AND stdout is empty AND stderr is empty |

Any `expect` field that does not match one of the six shapes is recorded as `FAIL -- malformed expect: <field>` and the gate is RED. The plan author cannot pass garbage.

One `Will change` record carries exactly one `verify` and one `expect` pair. A change that needs both an absence check and a presence check is expressed as two records that share the finding id with distinct suffixes (for example `[finding_id]-absent` and `[finding_id]-present`), not as two pairs inside one record.

### Absence checks use `expect: fail`

`silent` is the narrowest value in the vocabulary: it demands exit 0 **and** empty stdout **and** empty stderr. It describes a command that ran successfully and produced nothing, which is not what a search does when it finds nothing.

`rg` exits 0 when it finds a match and exits 1 when it finds none. So `verify: rg "pattern" [file]` with `expect: silent` fails in both states: a match gives exit 0 with non-empty stdout, and no match gives exit 1. An absence check is therefore `expect: fail`:

| Intent                                | verify           | expect        |
| ------------------------------------- | ---------------- | ------------- |
| The bad pattern is gone               | `rg "pattern" f` | `fail`        |
| The good pattern is present            | `rg "good" f`    | `pass`        |
| The command emits nothing but succeeds | any zero-exit    | `silent`      |

Verify commands must also stay portable across the project's shells. `||` is not a valid operator in Windows PowerShell 5.1, which is the shell this repository's tooling runs under; express alternation inside a single `rg` pattern (`rg "a|b" [file]`) rather than chaining commands.

### Run semantics

- Run all items in declared order on the working tree (post-staging, pre-commit).
- Each command runs in a fresh subprocess with a per-item timeout (`verify_timeout_seconds`, default 30, overridable per plan). A timeout kills the subprocess, captures whatever stdout was buffered, and records `FAIL -- timeout after Ns`. Timeout is a hard FAIL.
- Capture stdout and stderr in full, separately. Sanitize both with the credential sanitizer before recording evidence in the PATCH `## Plan-Actual` block. The unsanitized output remains in the gate's own buffer for the verdict; only the recorded evidence is sanitized. No byte cap, no synthetic digest: if the read or write tool itself truncates, mark `truncated: <reason>`; otherwise the full sanitized output is the evidence.
- The verify command string itself is capped at 2 KiB. Anything longer is rejected with `FAIL -- verify command exceeds 2 KiB` and never runs.

### Trust boundary

The Plan-Versus-Actual Gate executes commands drawn from the user-approved plan. The commands are NOT a sandbox: they have the same filesystem, network, and credential access as the rest of PATCH. The gate MUST NOT execute commands the user did not approve, and MUST NOT execute commands whose presence in the plan was not part of the user-approved `approved_will_change` records.

### Idempotence and mutation denylist

Verify commands MUST be idempotent; they read the working tree and may be re-run on retry. The gate applies a small denylist at runtime and rejects mutation-shaped commands with `FAIL -- command mutates state` (no execution):

- `git (commit|push|reset|clean|checkout --|restore|stash)\b`
- `(npm|pnpm|yarn|pip) install\b`
- `curl -X (POST|PUT|DELETE|PATCH)\b`

This is not a security boundary; it is a guard against accidental plan-author mistakes. BabaDev catches these at PLAN time and rewrites the verify command.

### Verdict aggregation

- All items PASS -> `GREEN`. Gate proceeds to the ask.
- Any item FAIL or SKIPPED -> `RED`. Trigger the auto-retry loop.

### Auto-retry loop

- A `RED` verdict emits a PATCH `## Plan-Actual` block with the FAIL list. BabaDev is given the FAIL list, the rewrite contract, and the must-eliminate list. The retry pass may ONLY make changes that target the failing items. No scope expansion. No new dependencies. No new files outside the FAIL list. No edits to a `Will change` item that already PASSED.
- After the fix pass, re-run the gate. All items PASS -> `GREEN`, proceed to the ask. Record `Retries: 1`.
- If still RED, one more fix pass (the 2nd retry), then escalate.
- On the 2nd retry still RED: emit `BLOCKED` with `Reason: plan-vs-actual gate failed after 2 retries; see the Plan-Actual block in PATCH for the FAIL list` and refuse to emit the commit/push ask. The session returns to PLAN with a specific gap report; the user re-plans the missing items.
- A scope violation (a new file in the diff that was not in the FAIL list, or any edit outside the FAIL list) bypasses the retry budget: the gate escalates to BLOCKED on the first violation, with `Reason: plan-vs-actual gate scope violation -- retry produced changes outside the FAIL list`. No third attempt.
- The retry counter is per PATCH execution (per plan approval), not per session. A fresh PLAN approval resets the counter.

### Staging interaction

The gate runs AFTER `git add` of the session's edited files and BEFORE the commit. The verify commands must observe the staged state. The ordering inside the commit/push gate is therefore: trigger -> Playwright smoke -> stage -> Plan-Versus-Actual Gate -> the ask.

### Skip conditions (Plan-Versus-Actual)

Record `SKIPPED: plan-actual -- <reason>`, never silently pass:

- No `Will change` items in the approved plan -> `SKIPPED: plan-actual -- no will-change items to verify` (YAGNI; trivial edits do not need a gate).
- Confirmed `READ_ONLY` host -> `SKIPPED: plan-actual -- gate trigger is false on a read-only host`.
- DIRECT mode runs the gate against the inline PATCH `## Will change` block when at least one `Will change` item exists, with `verify` fields best-effort (BabaDev writes one if it can, otherwise records `SKIPPED` per item). Same retry loop, same escalation.
- DIRECT mode with no `Will change` items -> `SKIPPED: plan-actual -- no will-change items to verify` (YAGNI; trivial edits do not need a gate).

### Recording (Plan-Versus-Actual)

- Append a per-run entry to `## Plan-Actual History` in the session context: `{retry_index, ran_at, fail_list, fix_summary, plan_actual_verdict, scope_violations}`. Append-only.
- Record one `plan_actual: GREEN|RED|SKIPPED -- <reason>` line in `## Commit/Push Gate`.
- The PATCH template's `## Plan-Actual` block carries the per-item evidence and a `History: <N> retries logged` footer.

### Hard rules (Plan-Versus-Actual)

- Never emit the commit/push ask while the gate is `RED`.
- Never let a `Will change` item pass without running its verify command and recording the sanitized output (no-assumed-passes rule).
- Never expand scope inside a retry pass; the rewrite contract still binds.
- A scope violation is a hard stop, not a soft fail; escalate to BLOCKED on the first violation.
- Never run a verify command longer than the configured timeout; timeout counts as `FAIL -- timeout`.
- Never cap stdout at an arbitrary byte limit; record the full sanitized output and only mark `truncated` if the read or write tool itself truncates.
- A verify command matching the mutation denylist never runs; record the denylist hit instead of executing.

### Anti-tautology note

A `Will change` item is structurally a tautology when its `verify` command exits 0 only when the change has NOT landed, or the `expect` field is the inverse of what the command actually probes. Examples:

- `verify: rg "TODO" newfile -- expect: silent` for a change that adds a TODO literal. `rg` exits 0 with output once the TODO landed and exits 1 with no output while it is absent; `silent` demands exit 0 *and* no output, so it fails in both states and proves nothing. Use `expect: pass`.
- `verify: rg "fix-me" file -- expect: pass` for a change that removes a `fix-me` marker (exits 1 when correctly removed, so `pass` can never be reached). Use `expect: fail`.

The gate cannot statically prove a tautology. The PATCH `## Plan-Actual` block makes the digest visible; the retry loop exposes the inversion within 2 cycles; the audit log (`## Plan-Actual History`) gives the user a paper trail.
