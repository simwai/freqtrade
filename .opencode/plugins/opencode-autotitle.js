// OpenCode's plugin loader iterates every module export and throws
// "Plugin export is not a function" on the first non-callable one. The upstream
// build also exports its test helpers plus CHEAP_MODEL_PATTERNS (an array of
// regexes), which aborts the whole plugin. Only the entry is re-exported here;
// the generated bundle lives in a subdirectory because the loader globs
// {plugin,plugins}/*.{ts,js} non-recursively and would otherwise load it twice.
import AutoTitle from "./opencode-autotitle-impl/index.js"

export default AutoTitle
