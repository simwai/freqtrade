---
description: Resume the prior Baba phase from TASKS.md and SPEC.md after interruption.
---

Resume the prior execution mode from the frozen spec and task list.

Before acting:

1. Read `SPEC.md` at repo root — verify `status: frozen` and note `version`.
2. Read `TASKS.md` at repo root — find the first unchecked task (`[ ]`) or the task marked in-progress.
3. Read `prompt-system/00-system.md` `## Execution modes` and `## Phase order`.

Then:

- If no `SPEC.md` or `status != frozen`: emit `[PHASE: BLOCKED]` — spec must be frozen to resume.
- If no `TASKS.md` or all tasks done: emit `[PHASE: BLOCKED]` — no task to resume.
- Let `task = first unchecked row in TASKS.md`.
- If `task` is a spec-session task (spec § 3.1): resume at `SPEC` phase (BabaSensei).
- If `task` is a spec-review task (spec § 3.2): resume at `REVIEW` phase (BabaReviewer reviewing SPEC.md).
- If `task` is a planning task (spec § 3.3): resume at `PLAN` phase (BabaSensei/BabaScrumMaster).
- If `task` is a build task (spec § 3.4): resume at `PATCH` phase (BabaDev) — read the task's Spec §, implement only that task.
- Determine execution mode: if the task can be described in one sentence and touches one file → `DIRECT`; else → `STRUCTURED`.
- Announce: `Resuming task #<id>: <task description>. Phase: <phase>.`
- Continue with that phase's template.

Cross-session persistence lives in `SPEC.md`, `TASKS.md`, and `EVALUATIONS.md` only.
