---
description: Emit a complete Baba persona handoff contract and record it in session context. Use when transferring work between personas (e.g., Sensei → Dev, Scrum → Sensei).
argument-hint: [receiving_persona] [optional notes]
disable-model-invocation: true
---

Create a persona handoff. $ARGUMENTS may name the receiving persona and any notes.

Before acting:

1. Read `prompt-system/01-personas.md` `## Handoff contract`.
2. Read the conversation history for session state.
3. Gather target, accepted violations, preserve constraints, approved plan, rewrite contract, and tester fields from session state and conversation.

Then:

- Emit the exact HANDOFF template from `prompt-system/01-personas.md` `## Handoff contract`.
- If any required field for the receiver is missing, emit `[PHASE: BLOCKED]` with the missing fields only.
- On success, record the handoff payload in conversation context and stop. Do not begin the receiver's work in the same response unless the user also asked to switch persona.
