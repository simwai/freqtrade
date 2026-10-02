# 05-impl-style

Implementation style core. Stack variants are in `prompt-system/stacks/STACK-<lang>.md`; pick the one matching the session's active language. Apply these defaults to every PATCH unless the target repo's `STYLE_POLICY.md` artifact or the INTAKE `Stack/Style:` field overrides them.

## General principles

- DRY
- KISS
- Composition over inheritance
- SOLID and CUPID where complexity justifies them
- Dependency injection over hidden construction. Use the stack's mandated DI container. Favor constructor injection; wire the composition root at the application entry point. Default to transient lifetime unless a clear singleton or scoped rationale exists.
- Single source of truth
- Early returns over deep nesting
- Big-O awareness for hot or scalable paths
- Security and type safety are first-class concerns

## Greenfield projects (new projects and new files)

When the target is a new project from scratch, or new files being added to a repo that has no existing source files, the defaults in this file ARE the project conventions until the user explicitly overrides them:

- the mandated stacks and helpers (see the per-stack sections)
- the error-handling idiom for the stack
- naming and file-naming rules (kebab-case, snake_case, PascalCase per stack)
- project structure (flat `src/`, split at 8 files, layer names)
- the code-decision ladder, comment policy, and logging palette

This is the one case where "defaults" are binding rather than advisory: a greenfield scaffold has no existing conventions to preserve, so the module defaults fill that role. A deviation from a greenfield default requires explicit user approval recorded in the INTAKE `Stack/Style:` field or the PLAN `Conventions:` field; an agent must never silently substitute its own generic conventions. The "strong defaults, not absolute laws" framing above continues to apply to existing codebases, where the local-convention policy governs.

## Local-convention policy

The decision between *preserve local convention* and *upgrade to house style* is a **per-project** choice, made once when the target project adopts the system. There is no per-file override.

- The decision is recorded in the target project's `STYLE_POLICY.md` artifact. Once recorded, the bot **must not** modify that artifact.
- If the artifact is missing or malformed in a target project, the bot runs the auto-trigger ask from `00-system.md` (which recommends `preserve-local` as option A) and proceeds with the result.
- If the user declines the ask or the ask cannot run, the bot defaults to `preserve-local` and emits a one-line note in the plan that the field is unset or invalid, so a human can correct it.
- The bot reads the project-level decision on every PATCH (loads `STYLE_POLICY.md`; the field is a single line in frontmatter). It applies the decision **uniformly across every touched file** in that project.
- When the decision is `upgrade-house-style`: the touched lines are upgraded; the plan's `Conventions:` field names the house-style rules being applied; an upgrade to a touched file is not a reformat of untouched code, only of the lines the change requires. The plan's `## Touched files` block notes any file whose existing style visibly differs from the house style (e.g., a vendored library), without making that file an exception to the policy.
- When the decision is `preserve-local`: the existing "preserve local conventions" rule applies.
- When creating or updating documentation (README, ADR, API docs, changelog, release notes), follow the repository's existing documentation conventions and tone, not only its Markdown lint configuration.
- Before creating a commit, inspect the repository's existing commit-message conventions (Conventional Commits, ticket or scope prefixes, subject length, body style) and follow them. If no convention is established, state the chosen format instead of inventing one silently.

Pass-assertion discipline: see `03-output-and-state.md` global rule. A claim that a local convention "looks fine" or "is consistent" is not evidence; the agent must name the inspected lines or cite the command that produced the conclusion.

## Error-handling idiom consistency (all stacks)

- The error-handling idiom that dominates a file or codebase wins. Before choosing how a new or changed code path reports failure, read the touched file and identify its established idiom: exit-code guards (`$LASTEXITCODE`), Result-style helpers, or exceptions.
- Do not introduce a different idiom for an operation the file already handles. A `try/catch` in an exit-code-guard script, or Result-wrapping in an exception-style codebase, is an idiom-consistency violation [H12].
- A deliberate idiom change requires explicit user approval before it enters a plan; without it, the change is a confirmed hard-tier finding [H12].
- The per-stack sections state preferred helpers, but the dominance rule overrides them when the file's established pattern differs.

## Design heuristics

- Prefer reusable abstractions only when repetition or a real variability axis exists.
- Use YAGNI for hypothetical features.
- Avoid registries or mappings that require manual sync when dynamic discovery is simpler and safer.
- Keep explicit lists when discovery would add needless complexity or reduce clarity.
- Consider one-off versus repeating cost before abstracting.

### Code-decision ladder

Before writing new code, stop at the first rung that holds:

1. Does this need to exist at all? YAGNI; skip speculative features.
2. Already in this codebase? Reuse the helper, util, type, or pattern; look before you write.
3. Does the standard library do it? Use it.
4. Does a native platform feature cover it? Use it (CSS over JS, DB constraint over app code).
5. Does an already-installed dependency solve it? Use it; never add a new one for what a few lines can do. The mandated stacks are an explicitly requested project convention; the ladder governs unrequested additions only.
6. Can it be one line? One line.
7. Only then: the minimum code that works.

The ladder runs after full comprehension, never instead of it: read the task and the code it touches, trace the real flow end to end, then climb. Guardrails:

- Never let a rung simplify away input validation at trust boundaries, error handling that prevents data loss, security, or accessibility; those are protected by the hard-tier rubric.
- Bug fix = root cause, not symptom: grep the callers of the function you touch and fix the shared function once; one guard in the shared function is a smaller diff than a guard in every caller.
- The shortest working diff wins, but only once the problem is understood; the smallest change in the wrong place is a second bug, not laziness.

## Stepdown rule (S14)

Functions read top-to-bottom. Each function calls functions one level of abstraction below it. At the design level, this means each function should decompose into one level of abstraction below the function's primary responsibility; the example that follows illustrates this decomposition. A function whose first line is a high-level call (`fetchUser()`) and whose next line is a low-level call (`parseJwt(token)`) without a named intermediate is a stepdown violation. The body of every function should be readable as a single sentence at one level of abstraction; the supporting helpers carry the next level down. (Martin, *Clean Code* ch. 3 "One Level of Abstraction per Function" / ch. 11 "The Stepdown Rule".)

## Newspaper order (S15)

A file reads like a newspaper article: headline first, then increasingly fine-grained detail as you scroll. The public API sits at the top, private helpers follow, and the reader never has to scroll up to find a called function. A file that places a public function below the private helper it calls, or splits a related group of functions across the top and bottom, is a newspaper-order violation. (Martin, *Clean Code* ch. 5 "The Purpose of Formatting" / ch. 11 "The Newspaper Metaphor".)

## Flag arguments and output arguments (S16)

A boolean flag argument almost always means the function does two things; split it. An output argument (a function that mutates an argument passed by reference) is a hidden side effect; return a value instead. The only acceptable uses are integration with APIs that require a mutable handle (rare) and fluent builders that return `this` (handled by S17's exception). (Martin, *Clean Code* ch. 3 / ch. 8 "Function Arguments" - Flag Arguments and Output Arguments.)

## Tell, don't ask - Law of Demeter (S17)

A method should not reach through another object to access its parts. `customer.wallet.balance.currency` exposes the wallet's internals; the behavior belongs on the wallet, called from the customer. Tell the wallet to do something; don't ask the wallet for its balance and decide yourself. A chain of more than one dot is a Demeter violation unless the chain is a fluent-builder return value or a known data-transfer object. (Martin, *Clean Code* ch. 6 / ch. 12 "Objects and Data Structures".)

## Minimal verification floor

- Non-trivial new logic (a branch, a loop, a parser, a money/security path) leaves one runnable check behind; the smallest thing that fails if the logic breaks: an assert-based self-check or one small test file. No test frameworks, fixtures, or per-function suites unless asked.
- Trivial one-liners need no test; YAGNI applies to tests too.
- This floor never replaces the per-edit lint gate or the project checks; it is the minimum, not the ceiling.

## Project structure

- Start new projects with a flat `src/` directory.
- When any directory exceeds 8 files, split by layer (`controllers/`, `services/`, `repositories/`, `middleware/`, etc.).
- Do not split preemptively.
- Keep configuration and tooling files at the repository root (`tsconfig.json`, `pyproject.toml`, `opencode.jsonc`, `.markdownlint.jsonc`), not inside `src/`; keep reusable scripts in a root-level `scripts/`.
- Keep tests beside the code they cover using the stack's test suffix, or in a top-level `tests/` mirroring `src/` when the project prefers separation; pick one convention per project.
- Use kebab-case for directory names (`user-profile/`, `api-gateway/`).
- For frontend `src/` splits, use the standard layer names `components/`, `composables/` (or `hooks/`), `stores/`, `views/`, and `utils/`; do not create a directory for a single file.

## Comments

*Reference: Robert C. Martin, Clean Code -- chapter 4 (1st ed., 2008) / chapter 5 (2nd ed., 2025). The categories below are Martin's, with stack-specific markers added on top.*

**Content over prefix.** The rule is what the comment says, not what character starts it. Prefix follows the language (`//` in TS/JS/Java/Pine, `#` in Python/PowerShell/Bash, `--` in SQL/Lua/Haskell -- automatic, not policed here). Stack sections do not re-state the prefix; this is the only place the prefix is mentioned.

**Why, not what.** Never restate the next line of code. Never write `// increment counter` above `i++`. Comments that fail this rule are an S10 finding at review time and a per-edit-lint-gate failure at patch time.

**Good comments - categories that earn a comment (Martin ch. 4 / ch. 5):**

- **Legal comments** -- copyright, license, or authorship headers required by a contract. Place once at the top of the file; never duplicate.
- **Informative comments** -- provide basic information that the language cannot express (e.g., the regex pattern's meaning, the byte order of a packed struct). Prefer a named constant over a comment when the constant carries the same information.
- **Explanation of intent** -- why a block of code exists, not what it does. The agent must answer "what would the next reader re-derive without this comment?" in one sentence. Write as a plain sentence, no marker prefix.
- **Clarification** -- translate an obscure argument or return value into something readable. Use only when the alternative is worse than the comment (e.g., a standard-library call whose return value is genuinely confusing).
- **Warning of consequences** -- flag a non-obvious failure mode the caller would otherwise miss. Write as a plain sentence, no marker prefix.
- **TODO comments** -- actions the author intends to take later, with an owner and a target. Format: `// TODO(<owner>): <what> -- <why deferred>`. A TODO without an owner is disallowed by default.
- **Amplification** -- make an otherwise subtle line of code louder. Use sparingly; if the code needs amplification, refactor it first.
- **Public-API docstrings** -- public-API docstrings are required for any function, class, or module that crosses a package or service boundary. Private/internal code does not get a docstring; the name carries the meaning.

**Bad comments - categories that violate this rule (Martin ch. 4 / ch. 5):**

- **Redundant or duplicative** -- restates the next line of code in prose, or says exactly what the code already expresses (e.g., `// set user to null` above `user = null`). The code is the source of truth. Always delete.
- **Misleading or wrong** -- says one thing while the code does another. Worse than no comment. Delete and fix the code or the comment.
- **Noise or formatting abuse** -- restates the obvious in a noisy way, uses loud markers (`////////////////////////////////////////////`), ASCII art separators, `// ==== Section ====`, `// ----- HEYO -----`, or `// some random label` headers. Use section breaks or extract-method instead.
- **Process artifacts** -- change logs at file top ("added by X on Y"), attributions (`// Added by Simon`), mandated comments required by process not code ("this function exists"), journal comments. Use git, not comments.
- **Dead or commented-out code** -- dead code left as a comment, commented-out code blocks. Delete; git has the history.
- **Structural violations** -- function headers (block comment at top of every function), docstrings on private/internal code, closing-brace comments (`// } end of while`), position markers (`// ACTIONS` at arbitrary columns). Use section breaks or extract-method.
- **Nonlocal or excessive context** -- references system-wide context without a link ("corresponds to issue #1234"), multi-paragraph essays, HTML/markup in comments (`// <b>important</b>`, Markdown/reST markup). Plain prose only; cite URLs inline. Exception: documentation generation libraries explicitly configured in the project.
- **TODO without owner** -- `// TODO: fix this` with no owner and no target. Disallowed by default; explicit user approval in the plan is required to use. Format: `// TODO(<owner>): <what> -- <why deferred>`.

Deliberate simplifications that cut a real corner with a known ceiling (global lock, O(n^2) scan, naive heuristic) are marked with a `simplify:` comment naming the ceiling and the upgrade path, e.g. `# simplify: global lock -- per-account locks if throughput matters`.

## Markdown defaults

- When creating or updating `.md` files, follow the repository's Markdown style and any existing markdownlint configuration, such as `.markdownlint.jsonc`.
- Run the repository's configured Markdown linter for changed Markdown files when available. Do not invent a lint command when no project check exists.
- Do not disable Markdown rules inline or in configuration unless the exception is explicitly required and documented.

## Naming

Names must reveal intent, usage, and role. Reference: Robert C. Martin, *Clean Code* chapter 2 (1st ed., 2008) / chapter 4 (2nd ed., 2025) -- "Meaningful Names." Apply the rules there as the house style. The project-specific markers that follow are how this system names the same ideas: classes are nouns (`UserService`); functions are verbs (`calculateTotal`); booleans read like facts (`isAdmin`, `hasPermission`, `canRetry`); in TypeScript class code, prefer underscore-prefixed private fields as a default house style.

## File naming

- Name every file after its primary concept or export; a file exporting several unrelated helpers should split.
- Default to kebab-case filenames unless the stack section says otherwise: `user-service.ts`, `pre-commit-config.yaml`, `architecture.md`. This matches this repository's own system and doc naming.
- TypeScript / JavaScript: kebab-case for **all** files - modules, hooks, components, utilities, and tests (`user-service.ts`, `use-user-profile.ts`, `user-profile.tsx`, `user-repository.ts`, `user-service.test.ts`). PascalCase governs identifiers inside a file (the exported component/class name), not the filename.
- Python: snake_case modules per PEP 8 (`user_service.py`); tests use the `test_` prefix (`test_user_service.py`).
- Java: PascalCase class files matching the public class name per Google Java Style (`UserService.java`); tests use `*Test.java` / `*IT.java`.
- Frontend: kebab-case filenames for components and everything else (Vue SFCs `user-profile.vue`, React `user-profile.tsx`, assets, composables/hooks, tests); the component is identified by its exported PascalCase identifier, not the filename.
- Avoid file names that differ only by case (`user-service.ts` vs `UserService.ts`); they collide on case-insensitive filesystems and break cross-platform checkouts.
- Keep extensions explicit in filenames and imports; extensionless filenames are reserved for executable scripts.

## File Separation

Each distinct concept gets its own file. Do not combine multiple concepts into a single file.

- One class per file. A file must contain at most one class definition.
- Errors are their own files. Each error type or error category gets its own file.
- Types and interfaces are their own files. Each type or interface gets its own file.
- Schemas are their own files. Each schema definition gets its own file.
- A file exporting several unrelated helpers should split (per `## File naming`).

These rules apply across all stacks. A file that mixes classes, types, or interfaces violates this rule even if the combined file is shorter or more convenient.

## Security defaults

- Sanitize untrusted input and output where relevant.
- Use parameterized queries / prepared statements for data access.
- Prefer explicit validation at boundaries.

## Logging defaults

- Use semantic color mapping: **red family** (error/fatal), **yellow/orange** (warn), **blue/green** (info/success), **gray/dim** (debug/trace).
- Avoid pairing red and green as the only distinction (colorblind accessibility).
- Prefer 16-color ANSI (bright variants) over 8-color for terminal contrast.
- Use 256-color or true-color only when the logger and terminal both support it.
- House palettes are Catppuccin Mocha and Dracula. Prefer Mocha unless the project already uses Dracula.

### Catppuccin Mocha

| Level | Color | Hex | ANSI 256 |
|---|---|---|---|
| ERROR | Red | #f38ba8 | 203 |
| WARN | Peach / Yellow | #fab387 / #f9e2af | 215 / 221 |
| INFO | Sapphire / Blue | #74c7ec / #89b4fa | 81 / 110 |
| DEBUG | Lavender | #b4befe | 183 |
| TRACE | Overlay1 / Surface2 | #7f849c / #585b70 | 102 / 59 |

### Dracula

| Level | Color | Hex | ANSI 256 |
|---|---|---|---|
| ERROR | Red | #ff5555 | 203 |
| WARN | Orange / Yellow | #ffb86c / #f1fa8c | 215 / 221 |
| INFO | Cyan / Green | #8be9fd / #50fa7b | 81 / 119 |
| DEBUG | Purple | #bd93f9 | 141 |
| TRACE | Comment (dim) | #6272a4 | 60 |

- Logging still follows H1 (no secrets), H7 (no untrusted stack traces or internal paths), and S8 (no missing, excessive, or misleading statements).

## Command-line and workflow defaults

- Suggest PowerShell commands first when the project is Windows-centric; invoke in this order: `pwsh` 7.6 first, then Windows PowerShell 5.1, then `cmd`, then `bash`. Default to `pwsh` 7.6 unless the project is pinned to Windows PowerShell 5.1.
- Use `rg` (ripgrep) for content search.
- Use regex for multi-file replacements when appropriate.
- Do not generate files or execute commands unless explicitly asked, except during PATCH verification and the per-edit lint gate, where running project checks (lint, typecheck, tests) is required.

## Testing coordination

- If BabaTester provides binding test evidence, treat it as part of the implementation contract.
- If BabaTester provides strong hints, usually honor or adapt them with rationale.
- If BabaTester provides weak hints, defer them explicitly rather than silently dropping them.
- Only output test ideas as a simple should-list unless the user explicitly asks for test code or BabaTester already owns the test-authoring handoff.

## Style floor

The defaults above are a floor, not a ceiling. They never replace the per-edit lint gate or the project checks; they are the minimum, not the maximum. The project style policy in `STYLE_POLICY.md` (`preserve-local` or `upgrade-house-style`) controls how the floor interacts with the file's existing style.
