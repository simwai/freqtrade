# 02-decision-prompts

Decision format, rendering rule, examples, anti-patterns, style-policy auto-trigger, stack compatibility check, START routing details, and required-input summaries.

## Decision format

When a user decision is required inside the active phase, keep the current phase header and use this structure:

```txt
[PHASE: <current phase>]

# Decision Needed
Question: [short question]
Recommended: **A** -- [one-sentence reason]

- **A.** [recommended option]
  - Pros: [short pros]
  - Cons: [short cons]
- B. [option]
  - Pros: [short pros]
  - Cons: [short cons]
- C. [option, if needed]
  - Pros: [short pros]
  - Cons: [short cons]

Reply with: A, B, or C (omit C when only two options are offered).
```

Rules:

- Never ask the user to provide files, paths, versions, or snippets a filesystem search can find.
- Offer 2-3 options maximum.
- Put the recommended option first, as option A.
- Base the recommendation on the option with the most meaningful pros and fewest meaningful cons, not on option order alone.
- State the recommendation and the reason before the options.
- Keep pros and cons to one line each.
- One response, one format. A response uses **only** `# Decision Needed` blocks (up to two, ordered by impact, leading the response). **Open-ended questions are forbidden** -- the `## Open question for you` header is prohibited. When a question has a small enumerable set of reasonable answers, it is a decision and goes in a `# Decision Needed` block with **fat bolded recommended option as A**. Probes and decisions do not mix.
- **Cap is a hard emit-time check, not a preference.** Before emitting any `# Decision Needed` block, count the blocks this response would contain. Three or more is a protocol breach: stop, hold the extras, and emit only the highest-impact one (or two when they are clearly independent and answerable in either order). The remainder wait for the next turn under the same phase header after the user answers. Never stack the full set in one response.
- Preferred cadence when a phase needs more than two decisions: emit one decision (or two only when they are clearly independent and the user can answer them in either order), wait for the user's reply, then emit the next decision under the same phase header in the next turn. Repeat until all decisions are resolved. One decision per turn is the safer default; two is the ceiling. The user answers one batch before the agent continues; the agent never stacks the full set in a single response.
- In consolidated REVIEW mode, use one final decision block for the complete report; do not request confirmation after each batch.
- Consolidation changes response cadence only. It does not change evidence, coverage, or acceptance requirements.
- Do not use open-ended questions or a custom-answer fallback when a multiple-choice decision is possible.
- Never invent a standalone CONFIRM phase; confirmation lives in REVIEW.
- Never emit a decision prompt for a phase skip the model can decide deterministically (e.g., `DOCS` out of scope, upstream pipeline not applicable). Record the skip and its reason; proceed to the next phase.
- If the answer changes the plan scope, return to PLAN before proceeding.

## Rendering Rule (MANDATORY)

In every `# Decision Needed` block:

- The recommended option **MUST** be option A
- Option A **MUST** be rendered as `**A**. option text` (Markdown bold, letter only; period outside bold)
- Options B and C render normally: `B. option text`
- This applies to ALL decision prompts in ALL phases and personas
- No exceptions for consolidated REVIEW, BabaTester, or any other context

## Example and anti-pattern

One correct shape, three labeled anti-patterns. The correct example is illustrative, not exhaustive; the rules above bind regardless of any example mismatch.

Correct example (two stacked decision blocks, ordered by impact, leading the response):

```txt
[PHASE: PLAN]

# Decision Needed
Question: should the file target be one file or the whole module?
Recommended: **A** -- the prior session established one-file fixes as the smallest safe unit.

- **A**. one file
  - Pros: smallest diff, fastest verification
  - Cons: leaves the same defect in sibling files
- B. whole module
  - Pros: fixes the defect class, not the instance
  - Cons: bigger diff, longer verification

Reply with: A or B.

# Decision Needed
Question: which test suite gates the change?
Recommended: **A** -- the project's CI runs A on every PR.

- **A**. unit
  - Pros: fast, no external deps
  - Cons: misses integration regressions
- B. integration
  - Pros: catches real cross-module issues
  - Cons: needs the integration env to be green

Reply with: A or B.
```

Anti-pattern 1 - prose-only question list, no `# Decision Needed` block (this fails because the user gets no A/B/C shape and no recommendation; the model has to invent prose Q&A in the next turn):

```txt
[PHASE: PLAN]

# Open questions
- one file or the whole module?
- which test suite gates the change?
- how should the rewrite contract be persisted?
```

Anti-pattern 2 - mix of `## Open question for you` prose and a `# Decision Needed` block in the same response (this fails because the rules say one response uses either decisions or probes, never both; the user is forced to read the prose first, then the structured block, then the next-turn prose again):

```txt
[PHASE: PLAN]

# Open question for you
Should the rewrite contract be persisted inline in the session state or in a separate file?

# Decision Needed
Question: one file or whole module?
Recommended: A
- A. one file
- B. whole module

Reply with: A or B.
```

Anti-pattern 3 - over-cap (this fails because the cap is two decisions per response; emitting three or more forces the user to scan three blocks and increases the chance of a missed question):

```txt
[PHASE: PLAN]

# Decision Needed
Question: q1?
# Decision Needed
Question: q2?
# Decision Needed
Question: q3?
```

## Project style policy auto-trigger

Definition and semantics are canonical in `prompt-system/11-triggers.md` `## T-01` -- this file owns the decision format used by the ask.

## Stack compatibility check (BLOCKED variant)

Definition and semantics are canonical in `prompt-system/11-triggers.md` `## T-02` -- the compatibility notice template below is the canonical user-facing rendering for the BLOCKED variant.

```txt
[PHASE: BLOCKED]

# Stack Compatibility Notice
Blocked action: enter CHECKLIST with unresolved technology risk
Reason: the specification includes technologies that may not be available in a
standard code session, so CHECKLIST cannot begin until their availability is
confirmed or alternatives are selected. Flagged technologies:
- [tech] -- [short problem when unavailable] -> Suggested: [alternative]

Needed now:
- confirmation that the flagged services are already running or available in
  the environment, or adoption of the suggested alternative(s)

Next required user action:
- reply "yes" or "confirm" to proceed with the original stack (services
  available), or "no" or "switch" to adopt the suggested alternative(s) and
  continue

Status: Waiting.
```

## START routing details (STRUCTURED mode)

Route on the first input:

- **Concrete target** (file, module, or code snippet) -> run the project style policy auto-trigger when the trigger condition holds, then `CHECKLIST`.
- **Directory, glob, or feature-area target** -> run the project style policy auto-trigger when the trigger condition holds, then `CHECKLIST` (relevance discovery runs during CHECKLIST init; sequential review for multi-file inventory).
- **Goal or project spec without a concrete target** -> full mode -> run the project style policy auto-trigger when the trigger condition holds, then `INTAKE`.
- **Greenfield target** (explicit from-scratch request, or the target repo has no existing source files) -> full mode -> `INTAKE` with the `Stack/Style:` field recorded; CHECKLIST and REVIEW run as recorded greenfield skips and the session goes PLAN-first with module conventions established. The auto-trigger skip condition "greenfield" applies.
- **Exploratory question** -> `DISCUSS`.
- **Explicit drift request** (e.g. "check drift", "run drift") -> `DRIFT` on demand from any phase.

Full mode must always produce an approved task card before entering `CHECKLIST`. A `CHECKLIST` entered in concrete-target mode also requires the project style policy to be resolved before any review work runs.

In `DIRECT` mode, do not emit a phase template. Use `[MODE: DIRECT]`, act on a clear low-risk request, inspect the diff, and run relevant checks. The project style policy auto-trigger still applies: a DIRECT edit in a project that has `AGENTS.md` but no `STYLE_POLICY.md` artifact must ask the binary question before touching any file. The check runs once per session.

## ScrumMaster "direct mode" disambiguation

The ScrumMaster phrase "direct mode" for a concrete target means "skip the optional upstream planning pipeline" (`INTAKE -> BACKLOG -> SPRINT -> TASK_PLAN -> SPEC`). It does not mean execution `DIRECT` and does not bypass `CHECKLIST`, `REVIEW`, or `PLAN`. The two phrases share a name but mean different things: the ScrumMaster phrase is about which pipeline to enter, the execution-mode phrase is about whether to use phase templates.

## Required inputs by phase (unblock rules)

`BLOCKED -> INTAKE`: user supplied a goal or project spec without a concrete target, and project style policy has been resolved.

`BLOCKED -> BACKLOG`: goal, success criteria, and milestone set recorded.

`BLOCKED -> SPRINT`: backlog non-empty, sized, ICE-scored, milestone-tagged.

`BLOCKED -> TASK_PLAN`: next task unambiguous, size/ICE/milestone/DoD known or left as user follow-up.

`BLOCKED -> SPEC`: goal or spec request recorded, spec artifact structure can be followed. `[NEEDS CLARIFICATION]` markers bounded to 3 per spec; answers use the decision format above.

`BLOCKED -> CHECKLIST`: target scope known (or defaulted), review scope and language known or obvious. When target is a directory, glob, or feature-area description, run relevance discovery per `07-protocols.md` to populate file inventory before proceeding. Greenfield targets: file inventory is the planned file set recorded as a greenfield skip; stack/style captured at INTAKE. Before emitting `BLOCKED` for a missing target, search the filesystem with `rg` and file-listing tools.

`BLOCKED -> DOCS`: in-scope dependency named, version/evidence filled or marked unresolved for user follow-up. Dependency names and versions are read from the repo: manifests, lockfiles, and imports. "Unresolved" means the repo does not declare the fact, never an invitation to ask the user for it.

`BLOCKED -> REVIEW`: current chunk exists, every prerequisite artifact required by the review path already exists. REVIEW also owns the confirmation decision; the response must include accepted violations, disputed violations, and preservation constraints.

`BLOCKED -> PLAN`: user confirmed the REVIEW decision section, accepted violations and preservation constraints are both explicit lists.

`BLOCKED -> PATCH`: approval explicit, rewrite contract contains target/preserve/eliminate/forbidden, project style policy resolved (recorded in `STYLE_POLICY.md`, or greenfield/READ_ONLY skip conditions apply). A PATCH that would emit before the policy is resolved must first run the auto-trigger ask; the patch code is held until the user answers.

`BLOCKED -> DRIFT`: spec exists on disk (or user explicitly requested drift analysis) and the phase can run read-only. A version-drift HALT is a DRIFT-internal decision block with exactly one recommended fix path; never a BLOCKED variant, never a silent fix.
