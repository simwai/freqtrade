# 10-doc-style

Documentation Style — loaded on `.md` edits. These conventions apply to all `.md` files in `docs/`. Enforced via `STYLE_POLICY.md` and the pre-commit hook.

## File Naming

All documentation files in `docs/` use **UPPER_SNAKE_CASE** with `.md` extension.

- File names must be all uppercase with underscores separating words
- Every file ends with `.md`
- Acronyms stay uppercase (e.g., `TRELLO_INTEGRATION.md`, not `Trello_Integration.md`)
- The `project-management/` root directory retains kebab-case for backward compatibility

## Glossary

The canonical glossary lives at **`docs/GLOSSARY.md`**. Maintained manually; updated when new terminology enters the system.

## Auto-Generated Table of Contents

TOCs are automatically generated via the `markdown-toc` pre-commit hook.

- **Coverage**: All `docs/**/*.md` files
- **Excluded**: `docs/GLOSSARY.md` and `docs/REFERENCE/` (manually maintained)
- **Depth**: Up to 3 heading levels (`--maxdepth=3`)
- **First H1**: Not used as TOC anchor (`--no-first-h1`)
- **Runs**: On every `git commit` via pre-commit

## Mermaid Diagrams

All diagrams use **GitHub-flavored Mermaid** syntax inside fenced code blocks.

- Every mermaid block starts with `%%{init: {'theme': 'dark'}}%%`
- **Primary color**: `#6B21A8` (Dark Purple)
- **Accent color**: `#06B6D4` (Cyan)
- **Background**: Dark transparent (GitHub dark mode renders automatically)
- Use `graph TD` (top-down) or `graph LR` (left-to-right) as appropriate
- Colors applied via `style` or `classDef` when needed:
  ```mermaid
  %%{init: {'theme': 'dark'}}%%
  classDef purple fill:#6B21A8,stroke:#7C3AED,color:#fff;
  classDef cyan fill:#06B6D4,stroke:#22D3EE,color:#000;
  ```

## SVG Images

SVG images follow a **dark purple + cyan cyberpunk** aesthetic.

| Role | Color | Hex |
|---|---|---|
| Primary | Dark Purple | `#6B21A8` |
| Primary Light | Purple | `#7C3AED` |
| Accent | Cyan | `#06B6D4` |
| Accent Light | Cyan Light | `#22D3EE` |
| Background | Dark | `#0F0A1A` |
| Text | Light | `#E2E8F0` |
| Border | Purple Dim | `#4C1D95` |

- All SVG files use the dark purple + cyan palette
- Background is dark (`#0F0A1A` or transparent)
- Strokes and fills use the palette colors above
- Text uses light color (`#E2E8F0`) for contrast
- SVGs should be self-contained (no external dependencies)

## Markdown Linting

All `.md` files are linted via `.markdownlint.jsonc`.

| Rule | Setting | Purpose |
|---|---|---|
| MD013 | `line_length: 1000` | Long lines allowed for code blocks |
| MD041 | `false` | First heading can be after frontmatter/tags |
| MD024 | `siblings_only: true` | Duplicate headings allowed across sections |
| MD033 | `false` | Inline HTML tags allowed (protocol markers) |
| MD060 | `false` | Table column alignment not enforced |
| MD012 | `false` | Multiple blank lines at EOF allowed |
