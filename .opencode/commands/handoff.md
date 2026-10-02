---
description: Emit a complete Baba persona handoff contract and record it in session context.
---

Create a persona handoff. $ARGUMENTS may name the receiving persona and any notes.

Before acting:

1. Read `prompt-system/01-personas.md` `## Handoff contract`.
2. Read the session context from the conversation carrier (resolved per `prompt-system/03-output-and-state.md` `## Session State (In-Session Only)`).
3. Gather target, accepted violations, preserve constraints, approved plan, rewrite contract, and tester fields from session context and conversation.

Then:

- Emit the exact HANDOFF template from `prompt-system/01-personas.md` `## Handoff contract`.
- If any required field for the receiver is missing, emit `[PHASE: BLOCKED]` with the missing fields only.
- On success, record the handoff payload in the session context (conversation carrier) and stop. Do not begin the receiver's work in the same response unless the user also asked to switch persona.
