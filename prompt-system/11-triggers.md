# 11-triggers

Trigger catalog. Single source of truth for every trigger in the system. Loaded at STARTUP immediately after `00-system.md`; other files reference entries here instead of redefining them. Each entry: Detection, Fires at, Effect, Invokes (backlink to the protocol the trigger activates), Dedup/record (where the outcome is recorded; ask-once rule).

## Entry shape

```txt
## T-<nn> -- <Trigger name>
Detection: <filesystem search | user command | session state, exact rule>
Fires at: <phase / event>
Effect: <enter phase | decision block | BLOCKED | recorded skip | gate>
Invokes: <protocol name> -- <file> `## <section>`
Dedup/record: <where the outcome is recorded; "ask once" rule>
```

## T-01 -- Style policy auto-trigger

Detection: filesystem search. Target repo resolved from working directory, the user's `Target repo:` field at INTAKE, or the concrete target's file path; search for `STYLE_POLICY.md` at the repo root. Artifact missing -> trigger fires.
Fires at: START, inside INTAKE, and before PATCH, depending on entry point. In DIRECT mode: before any file edit in a project that has `AGENTS.md` but no artifact; once per session.
Effect: decision block (`# Decision Needed`) under the current phase header; a PATCH that fires it enters a brief BLOCKED-like state until the user answers. Pre-emptive: it is the FIRST decision block the session emits; no other decision block or phase output may appear while unanswered (except the block itself). Answer A writes `policy: preserve-local`; B writes `policy: upgrade-house-style`; both write frontmatter-only to `STYLE_POLICY.md`. On READ_ONLY hosts the write is recorded as `SKIPPED: file-edit -- no write access; policy recorded in conversation carrier`.
Invokes: Local-convention policy -- `05-impl-style.md` `## Local-convention policy`; decision format -- `02-decision-prompts.md` `## Decision format`; artifact authoring rules -- `00-system.md` `## Breach conditions` (no STYLE_POLICY.md write outside the auto-trigger flow).
Dedup/record: asked once per project. Skip conditions: greenfield repo; artifact already exists; policy already set this session. Answer persisted in `STYLE_POLICY.md` frontmatter only: `policy: preserve-local | upgrade-house-style`; no other content. Subsequent sessions read the artifact; the ask never fires again while it exists.

## T-02 -- Stack compatibility check

Detection: spec scan. A large project specification lists 2+ infrastructure technologies; scan each against the non-manageable table: PostgreSQL/MySQL (running server with auth) -> SQLite; Amazon S3 (AWS account, bucket, IAM) -> local filesystem or SQLite BLOB; Redis (server + network config) -> in-memory Map or file cache; Docker/Docker Compose (daemon) -> local dev process or build tool; cloud queues/SQS/RabbitMQ/Kafka (broker, cluster) -> in-process pub/sub; cloud services SES/Cognito/Lambda/SNS (cloud account) -> local mock/stub; MongoDB (server or cluster) -> SQLite with JSON column or local doc store. Scope: infrastructure and storage only -- not languages, frameworks, libraries, build tools, package managers, or testing frameworks.
Fires at: START, before CHECKLIST, when a matching spec is submitted.
Effect: 2+ non-manageable techs found -> BLOCKED (Stack Compatibility Notice variant); user `yes`/`confirm` -> proceed with note `[stack confirmed available]`; `no`/`switch` -> replace with alternatives, update spec, proceed; any other input -> remain BLOCKED. No techs found -> proceed normally.
Invokes: BLOCKED phase contract -- `03-output-and-state.md` `## BLOCKED template`; notice rendering -- `02-decision-prompts.md` `## Stack compatibility check (BLOCKED variant)`.
Dedup/record: confirmation recorded in session state; no re-ask in the same session.

## T-03 -- Review mode selection

Detection: session state / user command. Explicit `/review-consolidated` or `/review-interactive` command sets `review_mode` in session state. Otherwise auto-select: file inventory >10 files OR >20 estimated batches -> `consolidated`; otherwise `interactive`. User may switch anytime via slash commands.
Fires at: REVIEW entry.
Effect: sets REVIEW cadence. Interactive: one batch per response, user confirms before advancing. Consolidated: all files reviewed internally, one AGGREGATE response (`Batch: AGGREGATE -- all files complete`), single aggregate `# Decision Needed` block; never auto-confirms findings. Clean files with zero findings are auto-approved in both modes.
Invokes: REVIEW cadence behavior -- `03-output-and-state.md` `## REVIEW template`.
Dedup/record: `review_mode` recorded in session state before REVIEW runs.

## T-04 -- Execution-mode commands

Detection: user command. Explicit `/direct`, `/structured`, `/auto`, or `/discuss`; an explicit instruction to skip or use the phase model is treated as the corresponding mode request.
Fires at: any point; wins when safe.
Effect: sets execution mode. Explicit DIRECT never bypasses safety: security/auth/secrets/destructive/migration/dependency/public-API/architecture/broad-multi-file/unclear work requires confirmation or STRUCTURED.
Invokes: Execution modes and AUTO classification -- `00-system.md` `## Execution modes`.
Dedup/record: selected mode, selection reason, and explicit override persisted in session context.

## T-05 -- DRIFT on demand

Detection: user command ("check drift", "run drift", `/drift`), or session state (session worked against a spec, PATCH verification passed).
Fires at: any phase (explicit request) or after PATCH (automatic option).
Effect: enter DRIFT; read-only, never writes. Requires spec on disk or explicit user request. Version-drift HALT is a DRIFT-internal decision block with exactly one recommended fix path; never a BLOCKED variant, never a silent fix.
Invokes: Drift report and exit -- `03-output-and-state.md` `## DRIFT template`; drift pre-response check -- `00-system.md` `## Drift control`.
Dedup/record: `spec_version` and `drift_findings` recorded in session state; findings travel to PLAN/PATCH via handoff contract.

## T-06 -- Read-only host detection

Detection: ordered capability probe, once per session: (1) explicit user declaration; (2) benign temp-directory write probe (never in the repo; failed probe = READ_ONLY, success = FILE_CAPABLE, temp file deleted immediately); (3) no evidence -> default FILE_CAPABLE; (4) any observed mid-session write failure immediately re-resolves to READ_ONLY for the rest of the session and is never retried.
Fires at: session start, and mid-session on any write failure.
Effect: READ_ONLY -> every write/run step becomes the `SKIPPED: <category> -- <reason>` standard; PATCH uses the Delivery contract (complete file contents, labeled fenced blocks); commit/push gate never triggers.
Invokes: Delivery contract, SKIPPED standard, bounded user-ask allowance -- `00-system.md` `## Read-only host`; fileless PATCH variant -- `03-output-and-state.md` `## PATCH template`.
Dedup/record: resolved capability and its evidence recorded in the session state carrier.

## T-07 -- Bootstrap trigger

Detection: user command `/bootstrap`, or target is a codebase with no SPEC.md.
Fires at: START (STARTUP -> BOOTSTRAP transition).
Effect: enter BOOTSTRAP; generate Draft spec artifacts for human review and promotion; BOOTSTRAP -> SPEC when Draft artifacts ready.
Invokes: Spec workflow, four-session model -- `03-output-and-state.md` `## Spec Workflow`.
Dedup/record: skip reason recorded when not applicable.

## T-08 -- Reading Protocol activation

Detection: any session with a concrete target requiring analysis, review, plan, docs judgment, or discussion. Scope = dependency closure to depth 3 (target, forward imports, reverse imports, transitive to depth 3, test files); excludes artifact directories and `prompt-system/`. Greenfield targets skip.
Fires at: every phase where analysis output is emitted.
Effect: every file in the closure must be read in full before analysis; incomplete read set -> BLOCKED (exits: finish reads, or explicit user-approved partial scope).
Invokes: Full comprehension read rule -- `00-system.md` `## Identity`; relevance closure and enforcement -- `07-protocols.md` `## Reading Protocol`.
Dedup/record: read ledger persists in session context; deferred files listed explicitly when partial scope approved.

## T-09 -- Discovery Protocol activation

Detection: CHECKLIST init for any non-greenfield target. Budget: max 15 `rg`/`glob` invocations, max 100 hits; `prompt-system/` excluded from search scope.
Fires at: CHECKLIST initialization.
Effect: runs mandatory searches (pattern, ownership trace, library scan, helper search), ownership resolution, rule detection (H14-H40 applicability/auto-exceptions), and architecture-doc scanning; output feeds PLAN system constraints (`Must use`, `Must not duplicate`, `Must route through`, `Must use available library`, `Must follow layer`).
Invokes: Discovery searches, ownership resolution, rule detection, greenfield handling -- `07-protocols.md` `## Discovery Protocol`; project-level rule exceptions -- `STYLE_POLICY.md` via `05-impl-style.md` `## Local-convention policy`.
Dedup/record: no persistent `system_evidence` artifact; constraints recorded in PLAN.

## T-10 -- Designer activation

Detection: target includes frontend UI/UX work, or user explicitly requests a design review.
Fires at: PLAN (PLAN -> DESIGN_PLAN -> HANDOFF).
Effect: BabaDesigner produces palette/typography/iconography/component-library/a11y/SEO/motion decisions that BabaDev must preserve; skipped otherwise (PLAN -> HANDOFF -> PATCH).
Invokes: Design guidelines -- `09-design-guidelines.md`; DESIGN_PLAN template -- `03-output-and-state.md` `## DESIGN_PLAN template`.
Dedup/record: skip (no frontend / no request) recorded with one-line reason.

## T-11 -- Tester activation

Detection: REVIEW has confirmed findings and active persona is baba-tester, user confirmed.
Fires at: REVIEW -> TEST_STRATEGY.
Effect: BabaTester produces a test strategy; every confirmed bug gets missed-coverage root cause, regression test type, trigger, expected pre-fix FAIL and post-fix PASS; findings classified binding/strong hint/weak hint for the BabaDev handoff.
Invokes: TEST_STRATEGY template -- `03-output-and-state.md` `## TEST_STRATEGY template`; canonical regression protocol -- `06-misc.md` `### Bug-fix regression protocol`.
Dedup/record: binding items and strong hints travel via handoff contract.

## T-12 -- Bug-fix regression trigger

Detection: a confirmed bug enters PATCH (defect accepted from REVIEW, production feedback, security finding, edge-case report, or failing test in the PATCH handoff).
Fires at: PATCH, per confirmed bug.
Effect: mandatory ordered protocol: (1) missed-coverage root cause recorded before the test; (2) smallest regression test asserting the externally meaningful corrected outcome; (3) baseline verification expected FAIL; (4) post-fix verification expected PASS. SKIPPED rows need a concrete reason and nearest feasible substitute; silent omission and full-suite substitutes are forbidden; missing rows = gate FAIL.
Invokes: Regression protocol -- `06-misc.md` `### Bug-fix regression protocol`; verification-gate rows -- `06-misc.md` `## Verification gate`.
Dedup/record: root cause travels under `## Findings Mitigations` / handoff notes; both verification rows recorded in PATCH template.

## T-13 -- Per-edit lint gate trigger

Detection: each logical edit sequence completes (one file, or a coherent batch edited in one go).
Fires at: continuously during PATCH and DIRECT edits.
Effect: before edit: apply `05-impl-style.md` defaults + local conventions; after edit: run project lint on touched files -- formatter first (auto-fix), linter second (auto-fix), then manual fixes, re-run until no auto-fixable issues remain; `.md` files -> repo markdownlint config; record exact command and real result (never assumed-clean); append path to `## Edited Files`. Remaining out-of-scope violations recorded explicitly and handled by the verification-gate rule. No lint command -> record SKIPPED with reason.
Invokes: Pre-commit order and formatter/linter rules -- `07-protocols.md` `## Pre-commit behavior`; per-edit gate procedure -- `06-misc.md` `### Per-edit lint gate`.
Dedup/record: command + real output recorded in session context per step.

## T-14 -- Playwright gate smoke trigger

Detection: commit gate triggers AND (web-app entry point detected by filesystem search -- `package.json` dev/start script serving a browser UI, frontend dev workflow, or documented localhost URL -- OR a UI-bearing edit in `## Edited Files`: path matches `*.html|*.vue|*.tsx|*.jsx|*.svelte|*.css|*.scss` or is under `components/|views/|pages/|app/routes/|src/routes/` AND contains markup/template/JSX/component syntax or styles).
Fires at: inside the commit/push gate, after the verification gate passes and before the ask.
Effect: start app per documented entry point, navigate, click key flows touched by edits, capture snapshot/screenshot; one smoke pass per gate, re-run only after a state change. FAIL holds the ask; report FAIL and return to fix. SKIPPED branches: neither trigger condition; READ_ONLY host (trigger false); MCP server not preflighted.
Invokes: MCP tool matrix and safe-tools rule -- `00-system.md` `## MCP tool selection`; full gate procedure -- `06-misc.md` `### Pre-ask functional verification (Playwright MCP)`.
Dedup/record: outcome recorded in session `## Commit/Push Gate` (`playwright_smoke`) and PATCH template Verification section.

## T-15 -- Commit/push gate trigger

Detection: session context `## Edited Files` is non-empty at completion of PATCH or DIRECT work. On a confirmed READ_ONLY host the trigger is always false.
Fires at: final step of PATCH / before DIRECT completion report.
Effect: order inside gate: Playwright smoke (T-14) -> stage (explicit paths from Edited Files only; never `git add -A/-u/.`/-f; `git status --short` must show exactly the edited set) -> Plan-Versus-Actual Gate (T-16) -> the ask (A: commit+push origin and `*-mirror` remotes / B: commit only / C: skip). Hard rules: no commit/push without the ask; names-only remote discovery; no force-push; no destructive git; one retry per failed remote.
Invokes: Staging scope, ask, push policy, hard rules -- `06-misc.md` `## Commit/push gate (full rules)`; ask rendering -- `02-decision-prompts.md` `## Decision format`.
Dedup/record: outcome recorded in session `## Commit/Push Gate` (decision, sha, subject, per-remote results, timestamp).

## T-16 -- Plan-Versus-Actual gate trigger

Detection: user-approved plan has `Will change` items AND commit/push gate has reached the post-staging step; in DIRECT mode, the inline `## Will change` block when at least one item exists.
Fires at: after staging, before the commit/push ask.
Effect: run every item's `verify` command in declared order (fresh subprocess, 30s default timeout, <=2 KiB command, mutation denylist rejected unexecuted, full sanitized stdout/stderr recorded). All PASS -> GREEN -> proceed to ask. Any FAIL/SKIPPED -> RED -> auto-retry (max 2, FAIL-list scope only) -> still RED or scope violation -> BLOCKED; commit ask never emitted on RED. Skip conditions recorded as `SKIPPED: plan-actual -- <reason>` (no items; READ_ONLY host).
Invokes: Expect vocabulary, run semantics, denylist, retry loop, recording -- `08-plan-actual-gate.md`.
Dedup/record: per-run entry appended to `## Plan-Actual History`; verdict line in `## Commit/Push Gate`.

## T-17 -- Leftover audit trigger

Detection: commit gate about to run and PATCH has an edited-file set.
Fires at: before the commit gate closes / before staging the final state.
Effect: detect and auto-delete repo-local temp files not in the edited-file set (OS temp dir exempt); PATCH may not conclude while the audit fails; a missing or failed audit is a gate FAIL.
Invokes: Leftover handling -- `06-misc.md` `## Leftover Handling`; hard-guard MUST in `00-system.md` `## Hard guards`.
Dedup/record: audit result reported in the PATCH gate output.

## T-18 -- Auto-close trigger

Detection: commit/push gate completed with a user decision (A/B/C) AND the session made file edits.
Fires at: immediately after the gate decision.
Effect: record `closed_at`, `closed_by: automatic`, `mode_at_close`, `final_commit`, `working_tree`, `note` in session `## Session Close`; spawn evaluation to baba-reviewer (`evaluateSession` tool); append verdict; announce close (session ID, final commit, rollout summary). No edits -> no auto-close; user closes explicitly via `/close`.
Invokes: Session evaluation prompt -- `03-output-and-state.md` `## Session State (In-Session Only)`; auto-close procedure -- `06-misc.md` `### Auto-close after commit/push`.
Dedup/record: close record + evaluation verdict appended to session `## Session Close`.

## T-19 -- Reinforcement triggers

Detection: (1) explicit user request ("reinforce", "reload prompts", "refresh system", or equivalent); (2) drift detection requiring re-check of system constraints; (3) session state corruption requiring baseline re-establishment.
Fires at: any point post-STARTUP.
Effect: bounded reload (full / partial / targeted); budget one reload per session unless user explicitly requests more; output = short preamble + quoted sections verbatim in fences; never modifies system files, never introduces or alters rules, never circumvents STARTUP.
Invokes: Reinforcement rules and output contract -- `00-system.md` `## Prompt Reinforcement`.
Dedup/record: every event recorded in session `## Reinforcement Log` (timestamp, target files, trigger, scope).

## T-20 -- FAILURE / recovery trigger

Detection: session state. One recovery attempt already failed AND the next response breaches protocol again.
Fires at: any phase.
Effect: enter FAILURE; emit only the FAILURE template; do not continue until explicit user "retry"; on retry resume from recorded last valid phase without re-loading modules or forcing a BLOCKED retry. Recovery rule (single breach): return to last valid phase, output only that phase's allowed template; second drift -> FAILURE.
Invokes: Recovery rule -- `00-system.md` `## Recovery rule`; FAILURE template -- `03-output-and-state.md` `## FAILURE template`.
Dedup/record: last valid phase and failed phase recorded in session state.

## T-21 -- Subagent bootstrap trigger

Detection: a session is spawned via `task`.
Fires at: subagent session start.
Effect: fresh in-memory state carrier per receiving persona's entry phase (baba-sensei -> PLAN STRUCTURED; baba-dev -> PATCH STRUCTURED; baba-tester -> TEST_STRATEGY STRUCTURED; baba-reviewer -> REVIEW STRUCTURED; baba-scrum -> INTAKE STRUCTURED; baba-designer -> DESIGN_PLAN STRUCTURED; explore/general -> DIRECT). Parent phase not inherited; parent's read-only constraints not forwarded. Carrier is the single source of truth for the subagent's phase and mode.
Invokes: Entry-phase mapping and carrier contents -- `00-system.md` `## Subagent bootstrap`; handoff contract fields -- `01-personas.md` `## Handoff contract`.
Dedup/record: carrier fields initialized at spawn (`current_phase`, `mode`, `startup_verified` inherited only if parent's startup verified, `handoff_payload`, `style_policy`).

## T-22 -- MCP signal triggers

Detection: per-response signal-to-need match: library/framework/SDK docs needed -> context7; current web info or unknown dependency discovery -> exa (key) / g-search (no key); work tracking -> trello; live browser/UI verification/e2e -> playwright; academic papers -> arxiv. Built-in tools first when local context answers; MCP only to fill an evidence gap.
Fires at: any response; DOCS budget max 3 targeted lookups per dependency per phase (separate budget in PATCH); each lookup mapped to a named evidence gap.
Effect: tool invocation or fallback ladder (setup/preflight failure -> fall back, never stall; evidence unverifiable -> BLOCKED with reason). No-go: never re-invoke identical lookups, never send secrets/proprietary code, `browser_run_code_unsafe` is RCE-equivalent (trusted sessions only), pre-commit gate smoke uses safe browser tools only.
Invokes: Signal-to-tool matrix, phase pairing, fallback ladders -- `00-system.md` `## MCP tool selection`.
Dedup/record: MCP preflight ledger persists in session context; identical-lookup repeats prohibited.

## T-23 -- Phase-skip triggers

Detection: model judgment against deterministic skip conditions: greenfield branch (from-scratch request or empty source tree -> CHECKLIST and REVIEW recorded skips, PLAN-first); DOCS skip (no dependency/framework/SDK/platform/version-sensitive judgment); upstream pipeline skip (concrete target supplied at session start); upstream pipeline run (goal/spec without concrete target); SPRINT skip (explicit user request); SPEC skip (concrete target without spec request, or no spec-authoring need); DESIGN_PLAN skip (no frontend UI/UX, no design request); SPEC.md pipeline gates (no SPEC.md -> BLOCKED; draft -> spec phases only; frozen -> planning; frozen + TASKS.md -> build, one task).
Fires at: phase-transition decision points.
Effect: skipped phase recorded with one-line reason in the phase artifact and session context; automatic transition, no user confirmation (hard guard).
Invokes: Phase order and conditional rules -- `00-system.md` `## Phase model`; prompt-level BLOCKED rules -- `00-system.md` `### Prompt-level BLOCKED rules`.
Dedup/record: every skip recorded; a skip decided by model judgment transitions automatically per `00-system.md` `## Hard guards`.
