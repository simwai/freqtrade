# 07-protocols

Cross-cutting protocol details: artifact handling, prompt-system protection, pre-commit behavior, reading protocol, discovery protocol. These are protocol detail that PATCH, REVIEW, and PLAN consume. "PATCH rule" sections below are cross-phase constraints that apply when PATCH touches the relevant domain — the PATCH execution protocol lives in `06-misc.md`.

## Artifact handling

Artifacts are binary files, build outputs, generated content, and large generated documents that should not be edited directly. Reading such files follows the sanitized-read rule: never the full file content, only a summary or first/last N lines, and never the raw bytes if the file is a credential-bearing format. Writing such files: never via PATCH. Artifacts are generated, never hand-edited; if a hand-edited artifact exists in the working tree, it is recorded as `S-artifact` violation with the recommended mitigation being regeneration, not patching.

### What counts as an artifact

Categories and canonical examples:

- **OS and editor artifacts**: `.DS_Store`, `._*`, `.Spotlight-V100`, `.Trashes` (macOS), `Thumbs.db`, `ehthumbs.db`, `desktop.ini` (Windows), `.vscode/`, `.idea/`, `*.swp`, `*.swo`, `*~` (editors).
- **Secrets and credentials**: `.env`, `.env.*` (allow `.env.example`), `*.pem`, `*.key`, `*.p12`, `*.pfx`, any file in `secrets/` or `.secrets/`. Hard rule: if a file can contain credentials, it must be in `.gitignore`. Missing this is an H1 violation. Reading such files follows the sanitized-read rule below.
- **Dependency directories**: `node_modules/`, `.npm/`, `.yarn/`, `.venv/`, `venv/`, `env/`, `__pycache__/`, `*.pyc`, `*.pyo`, `dist/`, `build/`, `out/`, `.cache/`.
- **Test and coverage output**: `coverage/`, `.coverage`, `*.lcov`, `htmlcov/`, `junit.xml`, `test-results/`.
- **AI session artifacts**: `sessions/`, `chat-export/`, `*.session.txt`, `*.session.md`, `*.session.json`, raw session dumps, exported conversation files, prompt-drafting scratch files. Rule: never commit raw AI session output. Sessions are ephemeral context, not source of truth.
- **Tooling caches**: `.pre-commit-cache/`, `.mypy_cache/`, `.ruff_cache/`, `.pyrefly_cache/`, `.pytest_cache/`, `.turbo/`, `.next/`, `.nuxt/`, `.svelte-kit/`.
- **Scratch and WIP files**: `*.tmp`, `*.bak`, `*.orig`, `scratch/`, `todo.md`, `WIP.md` at repo root.
- **OS temp directory**: the only allowed throwaway location is the OS temp directory (`$env:TEMP` on Windows, `/tmp` on Unix). Do not create repo-local temp directories for scratch work; use the OS temp directory instead.

### Review rule

During REVIEW, flag any of the following as a soft-tier finding (S-artifact):

- A tracked file that belongs to one of the artifact categories above
- A missing or incomplete `.gitignore` that fails to exclude known artifact categories
- A `.gitignore` that uses overly broad patterns like `*` or `**` that may silently exclude source files
- A missing `.gitattributes` where files could carry mixed or platform-native line endings (S-gitattributes); recommend `* text=auto eol=lf`
- A `.gitattributes` that forces CRLF or omits a line-ending policy (S-gitattributes)

Flag any committed credential file as a hard-tier H1 violation. Treat it as a blocker.

### PLAN rule

When a fix plan touches build config, tooling, or environment setup, the plan must include a `.gitignore` audit step:

- Verify all artifact categories for the project's stack are excluded
- Verify `.env.example` exists if any `.env.*` files are gitignored
- Verify `node_modules/` or equivalent is excluded if a package manager is in use

### Artifact governance

When emitting a patch that adds or modifies tooling, scripts, or build config:

- Include `.gitignore` additions for any new artifact type the change introduces
- Do not add `*.log` blindly; only add if the project actually produces log files
- Do not add lock files to `.gitignore`; lock files (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`) must be committed, not ignored

### .gitignore authoring defaults

When writing or reviewing a `.gitignore`:

- Group by category with a comment header per group: OS first, editor second, secrets third, dependencies fourth, test output fifth, build output last
- Use negation (`!.env.example`) immediately after the pattern it overrides
- Never use a pattern so broad it could silently exclude source files
- One pattern per line; no trailing whitespace

### .gitattributes authoring defaults

The house preference is LF line endings for every repository, including on Windows. When writing or reviewing a `.gitattributes`:

- Place the file at the repo root
- Default content: `* text=auto eol=lf` (normalize all text files to LF on commit and checkout)
- Add explicit `binary` entries (`*.png binary`, `*.jpg binary`, `*.zip binary`, ...) for formats git's text detection can misclassify
- Never default to CRLF, even on Windows workstations

Spawn rule: when a plan or patch sets up a new repo or touches repo hygiene, spawn `.gitattributes` with `* text=auto eol=lf` when the repo lacks one. Extend the existing file in the same patch that normalizes line endings.

## Prompt-system protection

The `prompt-system/` folder and its files are the core system and must be protected from modification when the prompt-system is deployed to a project. These files define the agent's behavior, rules, and conventions; editing them corrupts the system for all projects using it.

### Hard rules

- The `prompt-system/` folder must never be edited as part of a project's work. Changes to the system go through a separate governance session.
- When deploying the prompt-system to a new project, the `prompt-system/` files are installed as read-only artifacts.
- Any automated tool or agent must not modify `prompt-system/` files during normal project work.
- The `prompt-system/` folder is excluded from project-level linting, formatting, and review rules.

### Enforcement

- `07-protocols.md` rule detection (H14-H40) must not fire against `prompt-system/` files. The system reads `STYLE_POLICY.md` for project-level exceptions and treats `prompt-system/` as an always-excluded directory.
- Pre-commit hooks must not include `prompt-system/` in their staged-file patterns.
- Discovery Protocol searches must exclude `prompt-system/` from the project source tree.

### Exception

- Updates to the prompt-system itself (new rules, rubric changes, style updates) are performed in a dedicated governance session and deployed via the sync mechanism (`sync.ps1`), not through normal project PATCH flows.

## Reading Protocol

Trigger: any session with a concrete target that requires analysis, review, plan, docs judgment, or discussion. Applies in every phase where analysis output is emitted, not only at phase transitions.

Relevance is defined mechanically. The agent does not decide what to read. The system computes a dependency closure and the agent must read every file in that closure before emitting analysis.

### Relevance = dependency closure to depth 3

A file IS in scope if ANY of:

- It is the target file
- It is imported by the target file (forward dependency)
- It imports the target file (reverse dependency)
- It is a transitive forward or reverse dependency to depth 3
- It is a test file for any file in the closure (matches `*.test.*`, `*.spec.*`, `test_*.*`)

Excluded by default: `node_modules/`, `vendor/`, `prompt-system/`, `dist/`, `build/`, `.git/`, `__pycache__/`, `.venv/`, `venv/`, and other artifact directories per `## Artifact handling`.

Greenfield targets (no existing source files): Reading Protocol is skipped.

### Enforcement rules

1. No analysis output in any phase without completing the relevant reads.
2. Incomplete reads produce `[PHASE: BLOCKED]`, not analysis.
3. The only exits from BLOCKED are: finish all pending reads, or obtain explicit user approval for partial scope.
4. The agent cannot claim a file read without an actual read.

### Partial scope

When the user approves partial scope:

- Deferred files are listed explicitly
- Analysis proceeds only on the read subset
- Deferred files remain pending and must be addressed before PATCH

## Discovery Protocol

Trigger: CHECKLIST init for any non-greenfield target.

Search budget: max 15 `rg`/`glob` invocations, max 100 hits.

Search scope excludes `prompt-system/` (core system, never part of project work). All other directories are searched.

### Mandatory searches

1. **Pattern search** - dominant idioms in target file:
   - Error types: `rg "(Error|Exception|ValidationError)" <target_file>`
   - Validation calls: `rg "(validate|check|verify|guard)" <target_file>`
   - Helper imports: `rg "import.*from.*(utils|helpers|services)" <target_file>`
   - DI patterns: `rg "(new |@Inject|@Injectable|container\.resolve)" <target_file>`

2. **Ownership trace** - who owns the concern:
   - Forward imports: `rg "import.*<target_module>" src/ --max-count 50`
   - Reverse imports: `rg "<target_module>" src/ --max-count 50`
   - Method calls: `rg "<concern_method>" src/ --max-count 50`

3. **Library scan** - available dependencies:
   - Read manifest: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`
   - Extract dependency names and versions

4. **Helper search** - existing utilities:
   - `rg "export.*<concern_type>" src/ --max-count 50`
   - `rg "function <concern_name>" src/ --max-count 50`

5-15. **Pattern-specific searches** based on discovered idioms (e.g., if validation pattern found, search for all validation utilities).

### Ownership resolution

- Count direct imports + method calls per module
- Owner = module with highest reference count
- Tie-breaker: module with oldest git touch (most established)
- Owner confidence: high (margin >2x), medium (margin 1.5x-2x), low (margin <1.5x)

### Rule detection

For each rule in `04-rubrics.md` H14-H40:

1. Check if rule applies to target file's context
2. If yes: add to rule triggers with evidence
3. If rule has auto-exception: evaluate exception conditions
4. If exception triggered: mark rule as `auto_excepted` with reason
5. If exception not triggered: mark rule as `active` (must be enforced)

### Architecture doc scanning

Scan for project architecture/style docs:

- `ARCHITECTURE.md`
- `ADR/` directory
- `docs/architecture/`
- `STYLE_POLICY.md`
- Module-level `README.md` files

Extract declared rules using pattern matching:

- "All validation MUST go through X" → `must_use: X`
- "Controllers must not contain business logic" → `layer_constraint: controller`
- "Use dependency injection" → `di_required: true`

### Output

The agent uses discovered constraints directly in PLAN (`Must use`, `Must not duplicate`, `Must route through`, `Must use available library`, `Must follow layer`). No persistent `system_evidence` artifact is written.

### Exception handling

System reads `STYLE_POLICY.md` for project-level rule exceptions:

- `rule_exceptions.H14: disabled|advisory|mandatory`
- `rule_exceptions.H15: disabled|advisory|mandatory`
- etc.

Project-level exceptions override system defaults. If a rule is disabled for the project, it does not fire. If set to advisory, it flags but doesn't block. If mandatory (default), it blocks on violation.

### Greenfield handling

For greenfield targets (no existing source files):

- Discovery runs on the project's `05-impl-style.md` defaults and stack conventions
- Declared conventions recorded as constraints
- No ownership resolution (no existing code to own the concern)
- No duplication detection (no existing utilities)
- Library scan still runs (from manifest)

## Pre-commit behavior

Pre-commit hooks (`.pre-commit-config.yaml`, `lefthook.yml`, `husky`) run the order below, and the PATCH per-edit lint gate must mirror it. This section is for PATCH and REVIEW when the touched code includes scripts, package config, CI/CD config, or tooling setup.

### What pre-commit hooks must cover

A well-configured pre-commit setup must run at minimum:

| Check | Purpose | Priority |
|---|---|---|
| Formatter | Auto-fix style before commit | First; always runs before lint |
| Linter | Catch code-quality issues after formatting | Second |
| `tsc --noEmit` | Catch TypeScript type errors before they reach CI | Third (TS projects only) |
| Test runner | Run fast unit tests only; no integration tests | Fourth |
| Secret scanner | Block credentials from entering the repo | Always present |
| File hygiene | Trailing whitespace, end-of-file newline, LF line endings, merge-conflict markers | Always present |

Not every project needs all of these. A project with no test suite should not have a failing test hook. Use judgment; flag absence only when the missing check has real risk.

### Formatter vs linter distinction

- The formatter must run first and must auto-fix (not just report). If the formatter exits non-zero, the linter must not run.
- The linter runs after the formatter and validates what the formatter cannot enforce.
- Never replace the formatter with the linter.
- When Markdown files are included in the staged scope, the linter should run markdownlint using the repository's existing configuration.
- Preferred formatter per stack: TypeScript/JS `prettier --write`, Python `ruff format` (preferred) or `black`, Go `gofmt -w` or `goimports`, Rust `cargo fmt`.

### Type checking (`tsc --noEmit`)

For TypeScript projects, always use `tsc --noEmit` explicitly. Do not use a generic `typecheck` script unless it is verified to call `tsc --noEmit` internally. Run with the project's existing `tsconfig.json`. Do not invent flags. If the project uses multiple `tsconfig` files (e.g. `tsconfig.build.json`), run against the strictest one that covers all source files. `tsc --noEmit` runs on the whole project, not just staged files. It belongs in a `pre-push` hook if it is slow (>15 seconds).

### How to detect the project's package manager and scripts

Before recommending a pre-commit setup, identify:

1. **Package manager** - look for `pnpm-lock.yaml` (pnpm), `yarn.lock` (yarn), `package.json` alone (npm), `pyproject.toml`/`setup.py` (Python), `go.mod` (Go), `Cargo.toml` (Rust).
2. **Existing scripts** - read `package.json` `scripts` section. Look for: `format`, `lint`, `typecheck`, `test`, `build`. For Python: look for `[tool.ruff]`, `[tool.pyrefly]`, `[tool.pytest.ini_options]` in `pyproject.toml`.
3. **Existing hook config** - check for `.pre-commit-config.yaml`, `.husky/`, `lint-staged` config in `package.json`.

If any of these exist, the recommendation must align with them. Do not suggest replacing an existing working setup.

### Hook tool preference

- **Node.js projects**: MUST use Husky + lint-staged. `.pre-commit-config.yaml` is not the preferred path for Node.js; use Husky unless the project already has a working pre-commit setup that must be preserved.
- **Python projects**: MUST use `.pre-commit-config.yaml` with local hooks. Husky is not the preferred path for Python.
- **CI pipelines**: `.github/workflows/*` and `.gitlab-ci.yml` are forbidden in managed repos. PLAN must not recommend CI pipelines; REVIEW flags their presence as a soft-tier `S-precommit` finding.

### REVIEW rule (pre-commit)

During REVIEW, flag the following:

- **No pre-commit hooks at all** - soft-tier finding (S-precommit). State: "No pre-commit hooks detected. Format and type errors will reach CI."
- **Hooks exist but skip formatter** - soft-tier. State which formatter the project uses and that it is not hooked.
- **Hooks exist but run linter before formatter** - soft-tier. Formatter must always precede linter.
- **TypeScript project with no `tsc --noEmit` hook** - soft-tier. Type errors reaching CI is a real cost. Flag it.
- **Hooks exist but skip secret scanner** - hard-tier H1 adjacent. Secret scanning on commit is the last line of defence before push. Flag it clearly.
- **Hook runs slow integration tests** - soft-tier. Pre-commit must stay fast (under ~30 seconds). Slow tests belong in CI or `pre-push` only.
- **Hook is present but broken** (exits non-zero on clean code, wrong path, wrong interpreter) - hard-tier. A broken hook is worse than no hook: developers bypass it.

### PLAN rule (pre-commit)

When a plan includes tooling or script changes:

- State which hooks will be added, removed, or modified
- State the expected runtime of the hook set (target: under 30s)
- Explicitly separate `pre-commit` hooks (fast: format, lint, tsc, fast unit tests) from `pre-push` hooks (slow: full test suite, heavy type checks)
- If the project has no hook setup, include a recommendation for one in the plan as an optional but strongly advised step

### Pre-commit governance

When patching or creating hook configuration:

- **For `.pre-commit-config.yaml`** (pre-commit framework): always pin hook versions (`rev: vX.Y.Z`); never use `latest` or a branch ref. Order: file hygiene -> secret scanner -> formatter -> linter -> type check -> tests. Set `pass_filenames: false` on hooks that operate on the whole project. Set `always_run: true` only when the hook must run even on non-matching files.
- **For `package.json` with `lint-staged` + `husky`**: `lint-staged` patterns must be specific; never `**/*` as the only pattern. The `pre-commit` husky hook must call `npx lint-staged`. In `lint-staged` config: formatter runs first, linter second, on staged files only. `tsc --noEmit` and test runner must operate on the whole project; run them as a separate `pre-push` hook if they are slow. Example lint-staged entry for TypeScript:

  ```json
  "*.{ts,tsx}": ["prettier --write", "eslint --fix"],
  "*.{ts,tsx,js,jsx}": ["bash -c 'tsc --noEmit'"]
  ```

- **For Python projects**: prefer `.pre-commit-config.yaml` with local hooks over custom shell scripts. Formatter: `ruff format` (runs first). Linter: `ruff check --fix` (runs second). Type check: `pyrefly check` with the project's existing config **only if pyrefly is a declared dependency** in `pyproject.toml`. Tests: `pytest -x -q` (fail fast, minimal output).

### Script opt-in marker

If any `.sh` or `.ps1` scripts exist in the repo that should run as hooks, they must declare their intent in the first 5 lines with one of these keywords: `pre-commit`, `format`, `lint`, `test`, `quality`. Scripts without this marker are not picked up as hook candidates.

### What not to do (pre-commit)

- Do not recommend running the full test suite on `pre-commit` for large projects. Suggest `pre-push` for slow tests instead.
- Do not suggest `--no-verify` as a workaround for a broken hook. Fix the hook.
- Do not add a formatter hook that modifies files without also staging those changes. Formatters should either auto-stage (`git add`) or run in check-only mode and fail loudly.
- Do not use a generic `typecheck` script label when `tsc --noEmit` is what is meant. Be explicit.

### A11y and SEO validation

For projects with frontend UI:

- Run axe-core or pa11y against changed pages/components when the change touches markup, templates, or component structure
- Run lighthouse CI or equivalent for SEO score when the change touches page-level content, meta tags, or routing
- A11y/SEO failures are soft-tier findings (S23-S26) unless they constitute an accessibility violation under applicable law (e.g., WCAG 2.1 AA required for public sector) - in which case they escalate to H-tier with legal risk noted
