---
description: Look up a high-quality code reference from the curated global pool, or cache a new one.
---

Look up references from the global reference pool at `~/.config/opencode/reference-pool/`. If the pool is not initialized, run `prompt-system/scripts/init-reference-pool.ps1` first.

## Arguments

Parse `$ARGUMENTS` for these flags:

- `--language <lang>` - required for lookup, derived from the seed otherwise. Example: `typescript`, `python`, `java`, `csharp`
- `--domain <domain>` - required for lookup, derived from the seed otherwise. Example: `config-validation`, `error-handling`, `plugin-sdk`
- `--keywords <kw1,kw2>` - required for lookup. Comma-separated search keywords
- `--pool <pool-id>` - optional. Restrict results to a specific pool member
- `--trust-level <level>` - optional, cache mode only. One of `unvetted`, `standard`, `premium`. Defaults to `unvetted`
- `--add` - optional. Force cache mode
- `--lookup` - optional. Force retrieval mode and never write to the pool
- `--dry-run` - optional. Pass through to add-reference.ps1 / refresh-reference-pool.ps1
- `--refresh` - optional. Run the refresh script instead of lookup

## Seed URL

A GitHub URL anywhere in `$ARGUMENTS` is the **seed**: the file the user wants looked at.

Mode resolution, in order:

1. `--refresh` present -> refresh mode

2. `--lookup` present -> retrieval mode

3. `--add` present -> cache mode

4. A seed URL is present and `--keywords` is absent -> cache mode, then show the cached file

5. Otherwise -> retrieval mode

Cache-then-show is the default for a bare URL because the natural request is "look at this file", and a file that is not cached yet has nothing to retrieve. An explicit keyword query stays read-only, so a lookup never writes to the pool as a surprise.

In cache mode, derive `--language`, `--domain`, and `--keywords` from the seed when they are not supplied: language from the file extension, domain and keywords from what the file appears to be. State the values you derived. If the language cannot be inferred, ask with a `# Decision Needed` block rather than guessing.

## Cache mode

1. Run `prompt-system/scripts/add-reference.ps1` with the seed URL plus the resolved language, domain, keywords, and why-note, adding `--trust-level` when the user supplied it

2. Confirm what was added: pool member, entry ID, cached file path, commit

3. Then read the cached file from disk and present it with author, repo, trust level, why-added note, pool path, and full content

Do not invent a trust level. `unvetted` is the default and is the honest answer for a repo nobody has assessed; pass a higher level only when the user asks for it.

If `add-reference.ps1` reports `Entry already exists`, that is not a failure: the file is already cached at that commit. Report the existing entry ID, cached path, and commit, then read and present the cached file. Do not retry the add.

## Retrieval mode (default)

1. Load `prompt-system/scripts/retrieve-reference.ps1`

2. Call `Get-ReferencePoolMatches` with the parsed parameters

3. For each result returned:

   - Read the full cached file from disk: `~/.config/opencode/reference-pool/{language}/{author-repo}/{file-path}`

   - Include in your response: author, repo, trust level, why-added note, file path in pool, match score and reason, and the full file content

4. Return up to 3 matches, ranked by score

If no matches are found, say so plainly and suggest broadening the keywords or checking the pool manifest.

## Refresh mode

When `--refresh` is present:

1. Run `prompt-system/scripts/refresh-reference-pool.ps1`, passing `--dry-run` when that flag was given

2. Report how many entries were refreshed, skipped, or failed

Refresh rewrites the entire manifest from a full read, so a defect in the serializer would drop every entry but the last. If refresh reports that an entry is missing its language, stop and report it rather than working around it.

## Local files and snippets

For a local file or snippet with no seed URL:

1. Ask the user for the source GitHub URL if they want it cached with provenance

2. If they just want it stored locally, save it to `~/.config/opencode/reference-pool/{language}/{author-repo}/{filename}` and note that it lacks upstream provenance

## Rules

- Never fabricate pool entries or fake source URLs

- Always read the full cached file before presenting it as a reference

- If the pool is empty or uninitialized, say so and offer to run the init script

- The pool is user-global; do not commit it or push it anywhere

- Never hand-edit `.opencode/commands/code-ref.md`; it is generated from `adapters/opencode/commands/code-ref.md` by `generate-adapters.ps1`
