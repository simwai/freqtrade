---
description: Close the current session and run a final evaluation via /subtask to baba-reviewer.
---

Close the current session. Records close metadata in the session context (conversation carrier), then spawns a `/subtask` to `baba-reviewer` for a structured session evaluation.

Before acting:

1. Read the session context from the conversation carrier (resolved per `prompt-system/03-output-and-state.md` `## Session State (In-Session Only)`).
2. Read `prompt-system/07-protocols.md` `## App lifecycle` `### Close-session protocol` for the full close flow.
3. Determine `closed_by`: "user request" for explicit `/close` or natural language, "automatic" for post-commit/push auto-close.

Then:

- Record `closed_at` (ISO-8601 UTC), `closed_by`, `mode_at_close`, `final_commit` (from `## Commit/Push Gate` if present), `working_tree`, and `note` in the `## Session Close` section of the session context (conversation carrier).
- If the session made edits and a commit was recorded, announce automatic close and skip the evaluation unless the user explicitly requests it.
- If the session made no edits, or the user invoked `/close` explicitly, spawn a `/subtask` to `baba-reviewer` with the evaluation prompt from `prompt-system/03-output-and-state.md` `## Session evaluation prompt`.
- Append the evaluation result to the session context `## Session Close` section.
- Announce close to the user: session ID, final commit (if any), evaluation verdict (PASS/FAIL/SKIPPED), and one-line summary.
