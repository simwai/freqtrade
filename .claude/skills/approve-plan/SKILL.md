---
description: Explicitly approve the current Baba PLAN and record approval + rewrite contract in session context. Use after reviewing a plan and before implementation.
argument-hint: [optional notes]
disable-model-invocation: true
---

The user is approving the current plan via $ARGUMENTS (optional notes).

Before acting:

1. Read the latest PLAN output from the conversation.
2. Load `prompt-system/03-output-and-state.md` (PLAN template + handoff contract) and `prompt-system/01-personas.md` `## Handoff contract`.

Then:

- If no complete PLAN and rewrite contract exist, emit `[PHASE: BLOCKED]` listing the missing fields.
- Otherwise record in conversation context:
  - Plan Approval.status = approved
  - Plan Approval.approved_at = now
  - Plan Approval.approved_plan_summary
  - Rewrite Contract fields (target, must_preserve, must_eliminate, forbidden_in_patch)
  - current_phase = PLAN (approved) or HANDOFF-ready
- Emit a short confirmation that the plan is approved and name the next agent (BabaDev) for PATCH.
- Do not patch in this command.
