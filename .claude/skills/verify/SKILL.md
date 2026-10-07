---
description: Run verification gates after a patch or before finishing implementation work. Use after PATCH to inspect diff, run project checks, and apply the commit/push gate.
argument-hint: [optional focus area]
disable-model-invocation: true
---

Run verification after a patch or before finishing implementation work.

Before acting:

1. Read `prompt-system/03-output-and-state.md` for the Verification section template.
2. Read `prompt-system/06-misc.md` for the commit/push gate rules.
3. Inspect `git status` and `git diff`.
4. Detect available project checks from package scripts, Makefile, pyproject, or docs (lint, typecheck, test).

Then:

- Summarize the diff at a high level.
- Run the smallest relevant check set. Do not invent commands.
- When the repo declares a web-app entry point, invoke the Playwright MCP server for a functional smoke (navigate + click key flows) before the commit/push gate; a failed smoke is a hard-gate failure.
- When the session made file edits, apply the commit/push gate from `prompt-system/06-misc.md` `## Commit/push gate` before finishing.
- Emit results under the current phase header (usually PATCH) using the Verification section from `prompt-system/03-output-and-state.md`.
