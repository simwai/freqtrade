# opencode-autotitle (vendored build)

Vendored build output of [pawelma/opencode-autotitle](https://github.com/pawelma/opencode-autotitle).

- Upstream version: `0.1.3`

- Upstream commit: `40430fb`

- Build: `npm install && npm run build` (`tsc`) from a fresh clone

- License: MIT, see `LICENSE`

`index.js` is generated output and is never hand-edited. Line endings are
normalized to LF because `tsc` emits CRLF for the template literals it compiles
on Windows, and the repository `.gitattributes` (`* text=auto eol=lf`) does not
apply to the build on disk before it is committed.

## Why the entry point lives one directory up

`opencode-autotitle.js` in the parent `plugins/` directory is the only file
OpenCode loads. It re-exports just the plugin function. The upstream build also
exports its test helpers and `CHEAP_MODEL_PATTERNS` (an array of regexes), and
OpenCode's plugin loader iterates every module export and aborts the whole
plugin on the first non-callable one. Keeping the generated bundle in a
subdirectory is what stops OpenCode from loading it a second time and hitting
that error.

## Refreshing

1. Clone upstream at a new tag or commit.

2. Run `npm install && npm run build`.

3. Replace `index.js` with the new `dist/index.js`, normalized to LF.

4. Update the version and commit lines above, then confirm the plugin still
   loads with the shim in place:

   ```bash
   opencode debug info --print-logs --log-level DEBUG
   ```

   Expect `[autotitle] Module loaded` with no `failed to load plugin` line.
