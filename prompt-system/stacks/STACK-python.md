# Stack: Python

- Write Pythonic, readable code with PEP 8 style.
- Assume Python 3.12 unless the project states otherwise.
- Type annotations on every function signature: parameters and return type. `Any` requires inline `# pyrefly: ignore` comment with a written reason.
- Modern type syntax: `list[int]`, `dict[str, int]`, `X | None` over `Optional[X]`, `from __future__ import annotations` only when needed for forward refs.
- New data classes default to `@dataclass(slots=True)` from `dataclasses`. Use `slots=False` only when inheritance conflicts (document why).
- Naming: snake_case for functions/variables/modules, PascalCase for classes, UPPER_SNAKE_CASE for constants.
- Imports: `from x import y` style; `__init__.py` re-exports; no wildcard imports.
- Errors: raise specific exceptions; chain with `raise NewError(...) from original`; never bare `except:` or `except Exception:` without re-raise. Result pattern (**Result4j**) is the default for recoverable errors; exceptions for truly exceptional/unrecoverable conditions only.
- Tests: pytest with `arrange-act-assert`; fixtures for setup; parametrize for input variation; no test interdependence.
- Async: `asyncio` over thread pools; `async def` only when I/O-bound and the codebase is async; never mix sync and async in the same call chain.
- Package management: tooling detection first in an existing project. In an existing Python project, detect the active toolchain from marker files before running any install/add/lint/test command and route every Python command through it:
  - `pdm` - `pdm.lock`, `[tool.pdm]` in `pyproject.toml`, or `.pdm-python` present: use `pdm install`, `pdm add`, `pdm run <cmd>`.
  - `poetry` - `poetry.lock` or `[tool.poetry]` in `pyproject.toml`: use `poetry install`, `poetry add`, `poetry run <cmd>`.
  - `uv` - `uv.lock` or `[tool.uv]` in `pyproject.toml`: use `uv sync`, `uv add`, `uv run <cmd>`.
  - bare venv - `.venv/`, `venv/`, or `env/` containing an interpreter: invoke that interpreter directly (`<venv>\Scripts\python.exe` on Windows, `<venv>/bin/python` elsewhere) instead of the system Python.
  - Precedence when multiple apply: a configured tool (lockfile or tool table) wins over a bare venv; between tools, `pdm` > `poetry` > `uv`.
  - Never mix tools in one project (no `pip install` beside poetry/uv/pdm, no `uv add` in a pdm project) and never fall back to the system interpreter while a detected environment exists.
- Greenfield default remains `pdm`. New projects use `pyproject.toml` exclusively (no `setup.py`/`setup.cfg`), virtualenv mode enabled, lockfile (`pdm.lock`) committed.
- PDM scripts defined under `[tool.pdm.scripts]`:
  - `lint` - `ruff check src`
  - `format` - `ruff format src`
  - `typecheck` - `pyrefly check`  (only if pyrefly is a declared dependency in `pyproject.toml`)
  - `test` - `pytest`
  - `dev` - `python -m src.index`
- Checks run through the detected runner regardless of tool: `lint` (`ruff check src`), `format` (`ruff format src`), `typecheck` (`pyrefly check` — **only if pyrefly is a declared dependency** in `pyproject.toml` under `[project].dependencies` or `[project].optional-dependencies`), `test` (`pytest`) - e.g., `pdm run test`, `poetry run pytest`, `uv run pytest`, or `<venv>\Scripts\python.exe -m pytest` for a bare venv.
- Tool role split (Pylance / Pyrefly / Ruff) so the three tools do not duplicate work or fight each other in the editor or CI:
  - **Pylance** is the language server / IntelliSense. Configure in the target repo's `.vscode/settings.json`: `python.languageServer: "Pylance"`, `python.analysis.typeCheckingMode: "strict"`. Do not enable Pylance's own type checker when Pyrefly is in use; Pyrefly is the single source of type errors.
  - **Pyrefly** is the type checker. Configure in `pyproject.toml [tool.pyrefly]`; CLI entry point is `pyrefly check`. **Only runs if pyrefly is a declared dependency** in `pyproject.toml` under `[project].dependencies` or `[project].optional-dependencies`. Run on save in the editor; full check in CI and pre-commit (when present).
  - **Ruff** is the lint + format + isort tool (single binary replaces flake8, black, and isort). Configure in `pyproject.toml [tool.ruff]` and `[tool.ruff.lint]` with a sensible default like `select = ["E", "F", "I", "W", "B", "UP"]`. Editor: `charliermarsh.ruff` extension, `[python].editor.defaultFormatter = "charliermarsh.ruff"`, `formatOnSave = true`, `editor.codeActionsOnSave.source.organizeImports = "explicit"` so Ruff handles isort without a separate extension.
  - **Recommended `.vscode/extensions.json`** `recommendations`: `ms-python.vscode-pylance`, `meta.pyrefly`, `charliermarsh.ruff`.
- Pyrefly is the type checker (not Pyright or mypy). Configured in `[tool.pyrefly]` in `pyproject.toml` with `strict = true`. Override noisy strict rules only with rationale. Per-file opt-out via `# pyrefly: ignore[rule]` with a one-line why comment. **Type-check gate only executes when pyrefly is a declared dependency.**
- DI container: **dependency-injector**. Favor constructor injection; wire the composition root at the application entry point. Default to transient lifetime unless a clear singleton or scoped rationale exists.
- Result pattern library: **Result4j** (`Result<T, E>`):
  - A project-level helper wraps a throwing expression into a `Result`:
  
    ```python
    from result import Result, Ok, Err
    from typing import Callable, TypeVar
    
    T = TypeVar("T")
    
    def safe(fn: Callable[[], T]) -> Result[T, Exception]:
        try:
            return Ok(fn())
        except Exception as e:
            return Err(e)
    ```
  
  - Usage: `result = safe(lambda: risky_op())` wraps a single expression.
  - Caller narrows with `if result.is_ok()` / `elif result.is_err()` or `match/case`.
  - **No `.map()`, `.and_then()`, `.or_else()`, `.inspect()`, `.match()` method chaining allowed.**
  - `.unwrap()` / `.unwrap_or()` only at boundary points where exiting the Result pattern into exception land.
  - Do not mix `Result4j` with another result library in the same project.
- Preferred typed library stack (fully typed, reduce manual code):
  - Validation/models: **Pydantic v2** for API boundaries; `@dataclass(slots=True)` for internal data.
  - HTTP: **httpx** (fully typed, async).
  - CLI: **typer** (typed via annotation inference).
  - ORM: **SQLAlchemy 2.0** with `Mapped[]` syntax.
  - Lint/format: **ruff** (single binary, replaces flake8/black/isort).
  - Testing: **pytest** + **pytest-asyncio**.
  - Prefer libs that ship `py.typed` marker or have typeshed stubs over untyped alternatives.
- Linting: `ruff` (lint + format) or `black + isort + flake8`; pre-commit hooks run them on save.
- Circular import detection: **pycycle**. Run in pre-commit (whole project) and CI. Install via `pdm add --dev pycycle` (preferred), `poetry add --dev pycycle`, or `uv add --dev pycycle`. Run with `pycycle --here --ignore .venv,venv,build,dist,tests,__pycache__`. Configure via `pyproject.toml [tool.pycycle]` if needed (exclude test files, allow specific patterns). Note: may miss cycles in `src/` layout projects — verify manually if output seems unreliable.
