---
description: Enter a structured Baba phase (CHECKLIST, REVIEW, PLAN, PATCH, DISCUSS, DRIFT, etc.). Use when the user wants to enter a formal phase or when the current phase requires structured output.
argument-hint: [PHASE_NAME]
disable-model-invocation: true
---

You are in the Baba phase system. `$ARGUMENTS` names the structured phase to enter.

Valid phases: CHECKLIST, DOCS, REVIEW, PLAN, PATCH, DISCUSS, DRIFT, INTAKE, BACKLOG, SPRINT, TASK_PLAN, SPEC, BLOCKED, FAILURE.

Before acting:

1. Read `prompt-system/00-system.md` for phase order and transition rules.
2. Read the conversation history for session state.
3. Verify the requested phase transition is legal from the current phase.

Then:

- Declare `[PHASE: <name>]` at the top of your response.
- Output only that phase's template from `prompt-system/03-output-and-state.md`.
- Never skip forward — refuse and hold the current phase if the jump is invalid.
- Missing required input for the phase -> `[PHASE: BLOCKED]` and nothing else.
