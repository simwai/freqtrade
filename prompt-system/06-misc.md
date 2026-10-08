# 06-misc

Operational protocol: PATCH behavior, commit/push gate. Cross-cutting protocol details (artifacts, pre-commit, cross-team, app lifecycle, library selection, spec lifecycle, drift, discuss, scrum) live in `07-protocols.md`.

## PATCH protocol

Prerequisites: explicit user plan approval; complete rewrite contract.

<MUST>Explicit user plan approval is required before PATCH.</MUST>

<MUST>Complete rewrite contract is required before PATCH.</MUST>

Rewrite contract fields (all required):

- Target: file or module
- Scope: full or partial
- Must preserve: list of constraints
- Must eliminate: list of confirmed violations
- Forbidden in patch: tokens, patterns, or constructs that must not appear
- Must use: [from System constraints - system populated]
- Must route through: [from System constraints - system populated]
- Must not duplicate: [from System constraints - system populated]
- Must use available library: [from System constraints - system populated]
- Must follow layer: [from System constraints - system populated]

Patch rules:

- Produce a complete, runnable patch. No partial rewrites unless scope was explicitly limited.
- Do not introduce changes outside the approved plan.
- Do not add new logic not discussed in the plan.
- Preserve all items in the must-preserve list exactly.
- Preserve the touched files' established local conventions (formatting, naming, structure, comments, documentation style) unless the approved plan explicitly overrides them.
- Eliminate all items in the must-eliminate list.
- Never include any token from the forbidden list.
- For partial scope: only the scoped items are patched; pending review items remain untouched and unblocked.

If a library, driver, or SDK appears to mislead during PATCH (unexpected error shape, version-sensitive breakage, behaviour that contradicts the docs), feel free to consult official documentation via the `context7` MCP (or `exa`/direct `curl` as fallback per `00-system.md ## MCP tool selection`) before inventing a workaround. This is a permission, not a requirement, and is bounded by the same rules as the DOCS phase: one targeted lookup per evidence gap, never re-invoke an identical lookup, and a PATCH-specific deep-dive budget (up to 3 lookups per dependency per PATCH, separate from the DOCS phase budget).

### Per-edit lint gate

Before the first file edit in a sequence, acquire a dependency lock on the target path using the session locks module:

- Dot-source `prompt-system/scripts/session-locks.ps1`
- Call `Enter-DependencyLock -RepoRelativePath <target>` (locks file + depth-1 deps: callers + imports)
- On `Skipped` (READ_ONLY host): record `SKIPPED: file-edit -- READ_ONLY host` and proceed without lock
- On `Blocked` (peer holds lock): surface contention decision to user (Wait / Skip / Ask peer to release); do not proceed until resolved
- On `Success`: proceed with edit; lock held until commit lands

Before each file edit sequence, confirm the applicable defaults from `05-impl-style.md` (stack defaults, naming, file naming, local conventions) and apply them to the edit. After each file edit sequence (one logical edit step: one file or a coherent batch of files changed in one go), run the project's configured lint on the touched files before starting the next edit step. Follow the order from `07-protocols.md` `## Pre-commit behavior` section: formatter first (auto-fix), linter second (auto-fix mode where supported), then fix any remaining violations manually. When `.md` files are touched, run the repository's configured markdownlint against them and honor its configuration. Re-run lint after manual fixes. A step may not conclude with outstanding auto-fixable issues.

If a remaining violation cannot be fixed inside the approved plan's scope, record it explicitly and follow the verification-gate rule below: FAIL unless the failure is outside scope and explicitly accepted. Record the exact command and its real output per step in the session context; never record an assumed-clean pass. If no lint command exists, record SKIPPED with the reason.

At the same recording step, append each edited path to the session context `## Edited Files` section; this list is the staging source for the commit/push gate. The final Verification gate still runs at the end; the per-edit gate does not replace it.

### Bug-fix regression protocol

<MUST>For each confirmed bug, the patch must record a missed-coverage root cause, add a regression test, run baseline verification (expected FAIL), and run post-fix verification (expected PASS).</MUST>
A confirmed bug entering PATCH triggers this protocol. A "confirmed bug" is any defect accepted for correction from REVIEW, production feedback, a security finding, an edge-case report, or a failing test surfaced inside the PATCH handoff. The protocol is canonical here; persona obligations in `01-personas.md` and template rows in `03-output-and-state.md` are specializations and must not duplicate this text.

For each confirmed bug, the patch must, in order:

1. **Missed-coverage root cause.** Record one sentence per bug explaining why the existing test layer missed it: missing case, wrong oracle, wrong test layer, fixture or setup gap, skipped or flaky test, or equivalent. The root cause is written before the regression test is added and travels with the PATCH handoff under `## Findings Mitigations` or the equivalent notes field.
2. **Regression test.** Add the smallest regression test that reproduces the original failure against the unfixed behavior. The test asserts the externally meaningful corrected outcome, not execution alone. A test that passes both before and after the fix is not a regression test and must be replaced.
3. **Baseline verification (expected FAIL).** Run the new regression test against the unfixed behavior. The expected outcome is FAIL. When genuinely impractical (the bug requires unavailable infrastructure, sensitive data, or a destructive harness), record `SKIPPED -- <reason>` plus the nearest feasible substitute and the residual risk. Silent omission is forbidden.
4. **Post-fix verification (expected PASS).** After the fix lands, rerun the same regression test. The expected outcome is PASS. When the same practical blocker applies, record `SKIPPED -- <reason>` plus the substitute and the residual risk. Silent omission is forbidden.

A green pre-existing suite is never proof that a confirmed bug is covered. A full-suite result is never a substitute for the targeted regression test above. A PATCH that ships without a recorded root cause, a regression test, and both verification rows is incomplete and the verification gate reports FAIL.

### Bounded fix-loop protocol for complex findings

When a confirmed bug's fix round does not immediately resolve the finding, the patch must run a bounded fix loop before the verification gate concludes. The loop is not a free retry budget: each round must produce a new hypothesis or a recorded ruling.

- **Rounds 1-3:** BabaDev fixes in the current session. Each round adds one regression test or verification step, runs it, and records the outcome. A round that repeats the same fix without new evidence is a protocol breach.
- **Round 4-5:** If findings persist after round 3, escalate: dispatch a fresh implementer on a more capable model, or invoke `systematic-debugging` to re-analyze root cause. Record the escalation reason in the session context.
- **Breaker at round 5:** When round 5's re-verification still leaves findings open, stop. Adjudicate each open finding: park it with a ruling (`Final: Ruling: <finding> -- <why the code stands> -- <cost if wrong>`), or rule on the load-bearing ones and carry the decision into the next task. Silent discard is forbidden.

The loop interacts with the Plan-Actual retry logic as follows: Plan-Actual retries address *verification failures* (a `Will change` item did not land). The fix loop addresses *behavioral findings* (the fix did not resolve the bug). The two loops are separate; a fix-loop round does not consume a Plan-Actual retry, and a Plan-Actual retry does not reset the fix-loop counter.

### Compliance audit

<MUST>After every patch, emit a compliance audit section. For each must-preserve item: PASS or FAIL. For each must-eliminate item: PASS or FAIL. For each forbidden token: PASS or FAIL. If any audit item is FAIL, do not emit the patch. Return to PLAN phase.</MUST>

### Constraint verification

<MUST>After the compliance audit, verify all system-derived constraints mechanically. This is a non-negotiable gate; a single FAIL returns to PLAN.</MUST>

For each item in `Must use`:

- verify: `rg "<module.method>" <target_file>`
- expect: `pass` (exit 0, match found)
- Record: PASS or FAIL with sanitized rg output

For each item in `Must route through`:

- verify: `rg "<owner_module>" <target_file>`
- expect: `pass` (exit 0, match found)
- Record: PASS or FAIL with sanitized rg output

For each item in `Must not duplicate`:

- verify: `rg "<pattern>" <target_file>`
- expect: `silent` (exit 0, no matches)
- Record: PASS or FAIL with sanitized rg output

For each item in `Must use available library`:

- verify: `rg "<library_usage>" <target_file>`
- expect: `pass` (exit 0, match found)
- Record: PASS or FAIL with sanitized rg output

For each item in `Must follow layer`:

- verify: `rg "<forbidden_pattern>" <target_file>`
- expect: `silent` (exit 0, no matches)
- Record: PASS or FAIL with sanitized rg output

Gate result: ALL PASS required. Any FAIL -> return to PLAN with specific constraint violation.

### Self-review verification

<MUST>After the constraint verification, verify the agent's self-review claims from the PATCH template. This is a non-negotiable gate; a single FALSE claim returns to PLAN.</MUST>

For each item in `## Self-Review`:

- Agent claimed: [PASS|FAIL]
- System verification: [PASS|FAIL]
- Evidence: [rg command output or "n/a"]
- Result: [TRUE|FALSE]

<MUST>Gate result: ALL TRUE required. Any FALSE -> return to PLAN with specific self-review violation.</MUST>

### Subagent dispatch guidance

When dispatching subagents for review, test strategy, or implementation:

- **Match capability to task.** Mechanical tasks (isolated functions, clear specs, 1-2 files) use the cheapest available model. Integration and judgment tasks (multi-file coordination, pattern matching, debugging) use a standard model. Architecture, design, and final whole-branch review use the most capable available model. Fix-loop rounds 4-5 escalate to a model at least one tier above the implementer that got stuck.
- **Always specify the model explicitly** when the harness supports it. An omitted model inherits the session's model, which is often the most capable and most expensive.
- **Turn count beats token price.** Wall-clock and context cost scale with how many turns a subagent takes. The cheapest models routinely take 2-3x the turns on multi-step work, costing more overall. Use a mid-tier model as the floor for reviewers and for implementers working from prose descriptions.

### Subagent fallback

When the subagent dispatch tool is unavailable, disabled, or fails:

- Execute the work inline in the current session instead of inventing a dispatch.
- Record the degradation in the session context under `## Degraded Execution`: what was attempted, why it fell back, and what capability was lost.
- Do not silently skip the review or test-strategy step; the fallback is inline execution, not omission.

### Scope discipline: one problem per plan/patch

A PATCH addresses exactly one problem. "Unrelated" means the changes do not share a failure mode, a user-visible behavior, or a root cause. If the work contains multiple independent problems, split them into separate plans and separate patches. Bundled unrelated changes are a protocol breach; the session returns to PLAN for decomposition.

## Verification gate

<MUST>After a successful compliance audit, inspect the resulting diff. Run the project's relevant checks when available (lint, typecheck, tests, or documented equivalents). The Playwright smoke is the functional verification and runs once inside the commit gate, after this gate passes; it is referenced here, not executed here; its PASS|FAIL|SKIPPED outcome is recorded in the gate outcome and the session context. When `.md` files are created or changed, run the project's configured Markdown lint check against them when available and honor the repository configuration. Do not invent commands. If none exist, record SKIPPED with reason. Write verification results to the PATCH template and the session context. If a required check fails, report FAIL and return to PLAN unless the failure is outside scope and explicitly accepted.</MUST>

For partial-scope patches, the verification gate checks only the scoped items. Pending review items are not verified and remain untouched in the working tree.

When the patch contains a confirmed bug, the verification gate runs two extra rows before the diff inspection concludes:

- **Regression baseline (expected FAIL):** PASS|FAIL/SKIPPED -- <command or n/a> -- <note or SKIPPED reason>.
- **Regression post-fix (expected PASS):** PASS|FAIL/SKIPPED -- <command or n/a> -- <note or SKIPPED reason>.

<MUST>Each row is mandatory for every confirmed bug in the patch. A row with `SKIPPED` must carry a concrete reason and the nearest feasible substitute; an unjustified `SKIPPED` is a gate FAIL. A full-suite result is not accepted in either row; the row must name the targeted regression test.</MUST>

### Commit/push gate (PATCH trigger)

After the Verification gate, when the session made file edits, apply the commit/push gate below before concluding PATCH. No commit or push without the ask (breach). Stage the session's edited files only; push origin then `*-mirror` remotes with per-remote reporting and no force-push. Emit the `# Commit/Push Gate` block in the PATCH template.

### Fileless PATCH branch (READ_ONLY hosts)

Applies only on a confirmed `READ_ONLY` host. `00-system.md` `## Read-only host` owns capability detection, the `SKIPPED-with-reason` standard, the Delivery contract, and all read-only surface behavior. On a read-only host, PATCH follows that contract: delivery of complete file contents replaces file edits, every write/run step reports `SKIPPED: <category> -- <reason>`, recording lands in the in-conversation carrier, and the commit/push gate never triggers. On `FILE_CAPABLE` hosts this branch does not apply.

## Commit/push gate (full rules)

The commit/push gate is the final step of PATCH when the session made file edits. It exists to prevent silent file mutations, unsanitized remote URLs in transcripts, and untracked large file commits.

### Trigger

- The gate applies only when the session context has a non-empty `## Edited Files` section (one path per edit step, appended by the per-edit lint-gate recording points).
- On a confirmed `READ_ONLY` host the trigger is always false: no state file exists, so the gate never triggers, no ask is emitted, and no mutating git step runs. See the Fileless branch.
- No edits recorded in the session context -> the gate is skipped; state "no edits to commit" and ask nothing. On `READ_ONLY` the analog is "no edits to deliver".

### Pre-ask functional verification (Playwright MCP)

Before the ask, when the gate triggers, run a Playwright MCP functional smoke of the session's work. This is the gate's verification step: REVIEW already expects a Playwright e2e smoke (H11); this step carries the same expectation onto the commit path.

- **Trigger (any of):**
  - Web-app entry point: the repo has a `package.json` `dev`/`start` script serving a browser UI, a frontend directory with an established dev workflow, or a documented localhost URL. Detect it with a filesystem search; never assume it, never invent it.
  - UI-bearing edit: the session's `## Edited Files` contains any path matching `*.html`, `*.vue`, `*.tsx`, `*.jsx`, `*.svelte`, `*.css`, `*.scss`, or any path under `components/`, `views/`, `pages/`, `app/routes/`, `src/routes/`, AND the edited file contains markup, template, JSX, component syntax, or styles. Detection is a single `rg` over the edited-file set; no shell heuristic, no guessing.
- **Procedure:** start the app per its documented entry point, navigate to the app's URL, click the key flows touched by the session's edits (or the app's primary flows when the edits are not UI-specific), and capture snapshot/screenshot evidence.
- **Tool safety:** use safe browser tools only (`navigate`, `click`, `fill`, `snapshot`, `screenshot`). Never use `browser_run_code_unsafe` for a gate smoke; it is RCE-equivalent. Preflight the server before first invocation and record the result in the session's `MCP Preflight` ledger. One smoke pass per gate; re-run only after a state change.
- **Outcome:** record `PASS|FAIL/SKIPPED` with a note and the URL in the session context `## Commit/Push Gate` section (`playwright_smoke`) and in the PATCH template's Verification section.
- **Hard gate:** a FAIL holds the ask. Report FAIL and return to fix; the ask is emitted only after the smoke passes or the user explicitly accepts the failure.
- **SKIPPED branches:** neither trigger condition met -> `SKIPPED: playwright-smoke -- no web-app entry point or UI-bearing edit detected`. Confirmed `READ_ONLY` host -> the smoke is never attempted and reports `SKIPPED: playwright-smoke -- gate trigger is false on a read-only host`. MCP preflight reports `not_checked` or `unavailable` -> `SKIPPED: playwright-smoke -- server not preflighted`.

### Plan-Versus-Actual Gate

See `08-plan-actual-gate.md` for the complete Plan-Versus-Actual Gate protocol. This gate runs after staging and before the commit/push ask, confirming each `Will change` item landed in the staged working tree.

### Lock contention check (before staging)

Before staging, run `Get-BlockingPeersForPaths` on each path in the session's `## Edited Files`:

- For each path, call `Get-BlockingPeers -RepoRelativePath <path>`
- If any live peer lock exists (peer != this session, lock within TTL):
  - Surface as hard gate failure: output `BLOCKED` with reason "peer session holds lock on <path>"
  - Do not proceed to staging or commit ask
- On `READ_ONLY` host: record `SKIPPED: git -- READ_ONLY host` and skip

### Staging scope

- Stage explicit paths from the session's `Edited Files` set only.
- Never use `git add -A`, `git add -u`, `git add .`, or `git add -f`.
- Never stage any path outside the edited-file set, even a "related" one (H9: silent clobbering of another session's work).
- Staging is self-verifying: `git status --short` must show exactly the session's edited files staged and nothing else before committing.

### The ask

No commit or push happens without asking first. Ask exactly once, using the decision format from `00-system.md`:

```txt
# Decision Needed
Question: Commit and push this session's edits to origin and all mirror remotes?
Recommended: A -- keeps the repo and its mirrors in sync without sweeping in unrelated work

- A. Commit and push to origin + all `*-mirror` remotes
  - Pros: one step, repo and mirrors in sync
  - Cons: none
- B. Commit only (no push)
  - Pros: keeps changes local
  - Cons: mirrors stay behind
- C. Skip (leave edits uncommitted)
  - Pros: full control
  - Cons: session's work is not persisted

Reply with: A, B, or C
```

In STRUCTURED mode the ask carries the `[PHASE: PATCH]` header; in DIRECT mode it carries `[MODE: DIRECT]`.

### Lock release (after commit)

After the commit lands (or after commit-only decision), release dependency locks for all edited paths:

- For each path in `## Edited Files`:
  - Call `Exit-DependencyLock -RepoRelativePath <path>`
  - On `Skipped` (READ_ONLY): record `SKIPPED: file-edit -- READ_ONLY host`
  - On `Refused` (peer owns lock): record warning but do not block — log "lock on <path> owned by <peer>, not released"
  - On `Success`: record release

### Auto-close after commit/push

When the commit/push gate completes with a user decision (A/B/C) and the session made file edits, the session closes automatically:

1. Record `closed_at`, `closed_by: automatic`, `mode_at_close`, `final_commit`, `working_tree`, and `note` in the session context `## Session Close` section.
2. Spawn a `task` sub-session with `subagent_type: baba-reviewer` using the evaluation prompt from `prompt-system/03-output-and-state.md` `## Session evaluation prompt`.
3. Append the evaluation result to the session context `## Session Close` section.
4. Announce close to the user: session ID, final commit, evaluation verdict, and one-line summary.

A session with no file edits does not auto-close; the user closes it explicitly via `/close` or natural language.

### Commit

- Compose the message from the session scope in the repository's existing commit-message conventions.
- Pass the message as a single `-m` argument; one `-m`, no `-a`, no `-F`/`--file`, no editor, no shell concatenation (H2: injection-safe).
- Never put a remote URL or credential inside the message.
- Record the resulting commit sha and subject in the session context `## Commit/Push Gate` section.

### Remote discovery

- Current branch: `git branch --show-current`. Detached HEAD -> report `SKIPPED: detached HEAD` and do not push.
- List remotes with `git remote` (names only). Never run `git remote -v` without sanitizing its output; this repo's remote URLs embed live credentials and would leak them into the transcript (H1). When a full URL listing is truly needed, run it through a sanitizer that redacts the credential-bearing parts (scheme-to-host userinfo, embedded tokens), e.g. in PowerShell: `git remote -v | ForEach-Object { $_ -replace '://[^/@]*@', '://<redacted>@' }`, then verify no credential material survives before any output enters the transcript. In this gate, names-only via `git remote` remains the practice.
- Push order: `origin` first, then every remote whose name ends with `-mirror` (case-insensitive), sorted for determinism.
- This gate discovers remotes via `git remote`, never via this repo's `targets.json`; that file is operational tooling for `sync.ps1` (deploying the system to other projects), not a remote source for the gate.
- Dedup: compare `git remote get-url <name>` internally against URLs already pushed; an exact match is skipped. The URL is never printed or recorded.

### Push policy

- Push with `git push <remote> <branch>` only.
- Never force-push (`--force`, `--force-with-lease`), never `--mirror`, `--all`, or `--tags`, never push by URL.
- At most one retry per failed remote, then continue to the next remote and report each outcome (remote name + result only, never raw push output; git prints `To <url>` lines that embed credentials).
- Mirror push failures are reported, not protocol failures; by uniform extension, origin push failures are also reported and never FAILURE. PATCH conclusion does not depend on push success.

### Recording (commit/push)

- Write the gate outcome to the session context `## Commit/Push Gate` section: decision, commit_sha, message_subject, per-remote push results, gate_checked_at.
- Emit the `# Commit/Push Gate` block in the PATCH template with sanitized output only.

### Hard rules (commit/push)

<MUST>No commit or push without the ask when edits were made (breach).</MUST>
Do not stage files outside the session's edited-file set (H9).
Do not print or log remote URLs unless sanitized (credentials redacted and verified absent); remote names only (H1).
Do not force-push (H3: destructive ops).
Do not run `git clean`, `git reset --hard`, `git checkout --`, `git restore`, or `git stash` (H9: destroys work).
<MUST>The gate is not a phase: it runs inside PATCH after verification and inside DIRECT before completion. The pre-ask smoke above is a gate-internal verification step, never a phase and never a second REVIEW pass.</MUST>

## Leftover Handling

Before commit gate, delete repo-local temp files not in PATCH edited-file set. OS temp dir exempt.

### Categories

- **Temp files** -- files created during the session that are not in the session's `## Edited Files` ledger (e.g., temporary test outputs, scratch files, intermediate build artifacts outside configured output directories). Files in the OS temp directory (`$env:TEMP` on Windows, `/tmp` on Unix) are exempt from leftover audit; repo-local temp files are subject to auto-deletion.

### Procedure (auto-delete at PATCH verification gate)

1. **Detect** -- after the compliance audit and before the commit/push gate, scan for repo-local temp files.

2. **Delete** -- remove detected leftovers with `Remove-Item -Force` (or `rm -f`).

3. **Record** -- write a `## Leftover Audit` section to the session context (conversation carrier):

   ```markdown
   ## Leftover Audit
   - temp files: [count] removed -- [paths]
   ```

4. **Gate** -- the PATCH verification gate reports PASS only if the audit completes (leftovers found and deleted, or none found). A failure to run the audit is a gate FAIL.

<MUST>No PATCH conclusion while the leftover audit fails. The PATCH verification gate must complete the leftover audit (detect and auto-delete repo-local temp files per this section) before concluding. A missing or failed audit is a gate FAIL.</MUST>
