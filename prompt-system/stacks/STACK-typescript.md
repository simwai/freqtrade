# Stack: TypeScript / JavaScript

- Strict mode: `"strict": true` in `tsconfig.json`. `noImplicitAny`, `strictNullChecks`, `noUncheckedIndexedAccess`.
- `any` is forbidden; use `unknown` and narrow.
- `as` casts require a follow-up type guard or `// @ts-expect-error: <reason>` (binding) with a one-line reason.
- `null` vs `undefined`: prefer `undefined` for "not set" and `null` only when an API contract demands it.
- Async: `async/await` over `.then` chains; `Promise.all` for independent work; never fire-and-forget without a documented reason.
- Errors: typed error subclasses or discriminated unions; `try/catch` only around the failing call, not around the whole function; never `catch (e) {}`.
- Imports: `import { foo } from './foo'` over `import * as foo from './foo'`. `import type { Foo } from './foo'` for types.
- Exports: named exports over default exports except where the framework requires a default (React components, route handlers).
- React (when in scope): function components over class components; hooks at the top level, never in conditionals; props typed via interface or `type`; `useEffect` cleanup function for every subscription; no inline object/array literals in dependency arrays.
- Node (when in scope): `node:` prefix on built-in imports (`node:fs`, `node:path`); ESM by default; `process.exit` only at the top of the entry point.
- Prefer `for...of` over `forEach` for control-flow clarity.
- Avoid `reduce` by default; use it only if it is genuinely clearer than an explicit accumulator.
- Avoid awaiting inside loops unless sequential behavior is required.
- Use type guards when they materially improve safety or readability.
- Do not use unsafe assertions to silence the type system.
- For Node code, assume Node 20 and TS 5.x unless the project states otherwise.
- For the TypeScript ORM, prefer **TypeORM** using Repository pattern only (no Active Record). Decorator-style entity definition is the single enforced style. MikroORM is acknowledged as more type-safe and robust but production experience shows TypeORM makes fewer real-world problems for this team.
- DI container: **tsyringe**. Favor constructor injection; wire the composition root at the application entry point. Default to transient lifetime unless a clear singleton or scoped rationale exists.
- For error handling, prefer **super-result** (`simwai/super-result`) for Result-style explicit flows.
  - **Style: caller-handled, no chaining.** Use `if (result.ok)` / `if (result.err)` type narrowing.
  - `from(fn)` / `safe(fn)` wrap exactly one function call. The wrapped body must be a single expression; statement blocks inside the wrapper are forbidden.
  - `try/catch` is forbidden unless a `finally` block is also present. Do not use `try/catch` as a replacement for `from`.
  - `.catch()` on promises is forbidden. Do not convert Promise rejections via `.catch()`.
  - When the logic needs more than one statement, extract a named function or method and pass that as the single call: `from(async () => await fetchJson<RpcResponse>(url, body))`.
  - Do not use `.map()`, `.andThen()`, `.match()`, `.unwrapOr()` or other chaining methods on results.
- If `neverthrow` is already established in the codebase, continue using it; do not mix both.
- **Playwright async helpers**: wrap `waitForResponse` and similar async predicates with `from()` internally so callers receive `Result` directly. Example:

  ```ts
  async function waitForUserInfoResponse(page: Page, timeout: number): Promise<Result<void, Error>> {
    return from(async () => {
      await page.waitForResponse(
        (res) => res.url().includes('/rest/userinfo') && res.status() === 200,
        { timeout }
      )
      logger.debug('Library page ready (userinfo confirmed)')
    })
  }
  ```
