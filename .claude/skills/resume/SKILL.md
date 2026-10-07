---
description: Resume the Baba session from the last recorded phase and state. Use when returning to a previous session or after a context reset.
argument-hint: [optional phase override]
disable-model-invocation: true
---

Resume the Baba session. $ARGUMENTS may name a phase to resume from.

Before acting:

1. Read `prompt-system/03-output-and-state.md` `## Session State (In-Session Only)` for the session state schema.
2. Read the conversation history to recover session state (phase, findings, plan approval, rewrite contract, etc.).
3. Load `prompt-system/00-system.md` for phase transitions.

Then:

- Declare `[PHASE: <resumed_phase>]` at the top of your response.
- Restore session state fields from conversation history.
- Continue from the resumed phase. If a phase requires user confirmation (e.g., REVIEW decision section), present it.
- If no session state exists, start at STARTUP and follow `00-system.md` START routing.
