/**
 * Lock Enforcement Plugin for opencode
 *
 * Surfaces session-lock contention for two editing sessions sharing one checkout.
 *
 * Storage is the on-disk protocol owned by prompt-system/scripts/session-locks.ps1,
 * so locks taken here are visible to that module and to an operator inspecting
 * .session-locks/, and vice versa:
 *   <repo>/.session-locks/<relative-path>--with--dashes.lock/
 *       owner            session id that holds the lock
 *       acquired_at      ISO-8601 UTC timestamp
 *       dependencies.txt optional, one repo-relative path per line
 *
 * Acquisition uses mkdir, which throws EEXIST when the directory is already
 * present. That is the same exclusive primitive the PowerShell module gets
 * from [System.IO.Directory]::Move, so two sessions cannot both win the race.
 *
 * Why contention is blocked but an absent lock is not:
 * prompt-system/scripts/session-locks.ps1 states that enforcement belongs at
 * the commit gate rather than mid-edit, because a mid-edit block "can wedge the
 * very session that legitimately holds the lock". This plugin therefore does
 * exactly one blocking case -- another live session already holds the file --
 * which is the real conflict. Writing a file nobody has locked stays allowed
 * and is only recorded, so an agent that never took a lock is never trapped.
 *
 * A lock is never stolen. Contention is reported with the decision set the
 * caller has to make; the plugin does not pick for them.
 *
 * Inert on a READ_ONLY host (BABA_READ_ONLY=1).
 */

import { type Plugin, tool } from "@opencode-ai/plugin";
import { mkdir, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const WRITE_TOOLS = new Set(["write", "edit", "patch"]);

/** Matches $script:LockTtlMinutes in session-locks.ps1. */
const LOCK_TTL_MINUTES = 30;

function isReadOnlyHost(): boolean {
  const flag = process.env.BABA_READ_ONLY;
  return flag === "1" || flag === "true";
}

function getLockRoot(repoRoot: string): string {
  return resolve(repoRoot, ".session-locks");
}

/** Mirrors ConvertTo-FlatName: strip leading ./ or /, then separators become --. */
function toFlatName(repoRelativePath: string): string {
  return repoRelativePath
    .replace(/\\/g, "/")
    .replace(/^[./]+/, "")
    .replace(/[/\\]/g, "--");
}

function toRepoRelative(path: string, repoRoot: string): string {
  const normalized = path.replace(/\\/g, "/");
  const root = repoRoot.replace(/\\/g, "/").replace(/\/+$/, "");
  if (normalized.startsWith(root + "/")) return normalized.slice(root.length + 1);
  if (/^[a-zA-Z]:\//.test(normalized)) return normalized.replace(/^\/?[a-zA-Z]:\//, "");
  return normalized.replace(/^\/+/, "").replace(/^\.\//, "");
}

interface LockInfo {
  owner: string | null;
  acquiredAt: string | null;
  dependencies: string[];
}

/** Mirrors Test-LockLive: liveness from acquired_at only, never directory mtime. */
function isLive(info: LockInfo): boolean {
  if (!info.acquiredAt) return false;
  const acquired = Date.parse(info.acquiredAt);
  if (Number.isNaN(acquired)) return false;
  return Date.now() - acquired < LOCK_TTL_MINUTES * 60_000;
}

async function readLockInfo(lockPath: string): Promise<LockInfo> {
  const info: LockInfo = { owner: null, acquiredAt: null, dependencies: [] };
  try {
    info.owner = (await readFile(resolve(lockPath, "owner"), "utf-8")).trim();
  } catch {
    /* absent owner file */
  }
  try {
    info.acquiredAt = (await readFile(resolve(lockPath, "acquired_at"), "utf-8")).trim();
  } catch {
    /* absent timestamp */
  }
  try {
    const raw = await readFile(resolve(lockPath, "dependencies.txt"), "utf-8");
    info.dependencies = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  } catch {
    /* optional file */
  }
  return info;
}

interface LockEntry {
  lockPath: string;
  info: LockInfo;
}

async function readLiveLocks(repoRoot: string): Promise<LockEntry[]> {
  const root = getLockRoot(repoRoot);
  let names: string[];
  try {
    names = await readdir(root);
  } catch {
    return [];
  }

  const live: LockEntry[] = [];

  for (const name of names) {
    if (!name.endsWith(".lock")) continue;
    const lockPath = resolve(root, name);
    try {
      const s = await stat(lockPath);
      if (!s.isDirectory()) continue;
    } catch {
      continue;
    }

    const info = await readLockInfo(lockPath);
    if (!isLive(info)) {
      // Abandoned: reap it so a crashed session cannot block a path forever.
      try {
        await rm(lockPath, { recursive: true, force: true });
      } catch {
        /* best effort */
      }
      continue;
    }
    live.push({ lockPath, info });
  }

  return live;
}

interface Contention {
  held: boolean;
  owner: string;
  lockPath: string;
  dependencies: string[];
}

/**
 * Contention for a path is found two ways:
 *   1. directly -- the lock path is deterministic from the relative path, so
 *      there is exactly one candidate to check. The directory name carries no
 *      owner, so the name must not be parsed to recover the path.
 *   2. transitively -- a live lock whose dependencies.txt lists this path.
 */
async function findContention(
  repoRoot: string,
  sessionId: string,
  filePath: string,
): Promise<Contention | null> {
  const repoPath = toRepoRelative(filePath, repoRoot);
  const live = await readLiveLocks(repoRoot);
  const target = resolve(repoRoot, repoPath);

  const directPath = resolve(getLockRoot(repoRoot), `${toFlatName(repoPath)}.lock`);
  const direct = live.find((entry) => entry.lockPath === directPath);
  if (direct) {
    if (direct.info.owner === sessionId) return null;
    return {
      held: true,
      owner: direct.info.owner ?? "unknown",
      lockPath: direct.lockPath,
      dependencies: direct.info.dependencies,
    };
  }

  for (const entry of live) {
    if (entry.info.owner === sessionId) continue;
    const covers = entry.info.dependencies.some((dep) => {
      try {
        return resolve(repoRoot, dep) === target;
      } catch {
        return false;
      }
    });
    if (!covers) continue;
    return {
      held: true,
      owner: entry.info.owner ?? "unknown",
      lockPath: entry.lockPath,
      dependencies: entry.info.dependencies,
    };
  }

  return null;
}

interface AcquireOutcome {
  Success: boolean;
  FlatName?: string;
  Blocked?: boolean;
  Owner?: string;
  Decision?: string[];
  error?: string;
}

async function acquireFileLock(
  repoRoot: string,
  sessionId: string,
  filePath: string,
  dependencies: string[],
): Promise<AcquireOutcome> {
  const repoPath = toRepoRelative(filePath, repoRoot);
  const flat = toFlatName(repoPath);
  const lockPath = resolve(getLockRoot(repoRoot), `${flat}.lock`);

  try {
    await mkdir(resolve(lockPath, ".."), { recursive: true });
  } catch (err: any) {
    return { Success: false, error: `cannot prepare lock root: ${err?.message ?? String(err)}` };
  }

  // EEXIST is the exclusive signal: another session already holds this path.
  try {
    await mkdir(lockPath);
  } catch (err: any) {
    if (err?.code !== "EEXIST") {
      return { Success: false, error: `cannot create lock: ${err?.message ?? String(err)}` };
    }
    const existing = await readLockInfo(lockPath);
    if (isLive(existing)) {
      return {
        Success: false,
        Blocked: true,
        Owner: existing.owner ?? "unknown",
        Decision: [
          "wait -- the other session is still editing this file",
          "coordinate -- hand the edit to that session",
          "release -- confirm the other session is idle, then release its lock",
        ],
      };
    }
    // Abandoned lock: reclaim it.
    await rm(lockPath, { recursive: true, force: true }).catch(() => {});
    await mkdir(lockPath);
  }

  try {
    await writeFile(resolve(lockPath, "owner"), sessionId, "utf-8");
    await writeFile(resolve(lockPath, "acquired_at"), new Date().toISOString(), "utf-8");
    if (dependencies.length > 0) {
      await writeFile(resolve(lockPath, "dependencies.txt"), dependencies.join("\n"), "utf-8");
    }
  } catch (err: any) {
    await rm(lockPath, { recursive: true, force: true }).catch(() => {});
    return { Success: false, error: `cannot write lock metadata: ${err?.message ?? String(err)}` };
  }

  return { Success: true, FlatName: `${flat}.lock` };
}

async function releaseFileLock(repoRoot: string, filePath: string): Promise<{ Success: boolean; Reason?: string }> {
  const lockPath = resolve(getLockRoot(repoRoot), `${toFlatName(toRepoRelative(filePath, repoRoot))}.lock`);
  try {
    await rm(lockPath, { recursive: true, force: true });
  } catch (err: any) {
    return { Success: false, Reason: `cannot remove lock: ${err?.message ?? String(err)}` };
  }
  return { Success: true };
}

const LockEnforcePlugin: Plugin = async ({ client, directory }: any) => {
  return {
    "tool.execute.before": async (input: { tool: string; sessionID?: string }, output: { args: any }) => {
      if (!WRITE_TOOLS.has(input.tool)) return;
      if (isReadOnlyHost()) return;

      // The session id lives on the hook input. The previous implementation read
      // it from output.args, where write args are only { filePath }, so the hook
      // never fired at all.
      const sessionId = input.sessionID;
      if (!sessionId) return;

      const filePath = output.args?.filePath ?? output.args?.path;
      if (!filePath) return;

      const contention = await findContention(directory, sessionId, filePath);

      if (!contention) return;

      const deps = contention.dependencies.length ? ` (covers ${contention.dependencies.join(", ")})` : "";
      throw new Error(
        `[LOCK CONTENTION] Write blocked: another live session holds "${filePath}".\n` +
          `Owner: ${contention.owner}${deps}\n` +
          `Lock: ${contention.lockPath}\n` +
          `This lock is never stolen automatically. Options:\n` +
          `  - wait for that session to finish and release its lock\n` +
          `  - coordinate and hand this edit to the other session\n` +
          `  - confirm the other session is idle, then remove the lock directory yourself`,
      );
    },

    tool: {
      acquire_lock: tool({
        description:
          "Acquire a session file lock for a file. Locks live in .session-locks/ and are shared with " +
          "prompt-system/scripts/session-locks.ps1, so both surfaces see the same locks.",
        args: {
          filePath: tool.schema.string().describe("Absolute or repo-relative path to lock"),
          dependencies: tool.schema
            .array(tool.schema.string())
            .optional()
            .describe("Additional repo-relative paths this lock should cover."),
        },
        async execute(args: any, context: any) {
          const sessionId = context?.sessionID;
          if (!sessionId) return "Error: session ID required";
          if (isReadOnlyHost()) return "Lock acquisition skipped: READ_ONLY host";

          const result = await acquireFileLock(directory, sessionId, args.filePath, args.dependencies ?? []);
          if (result.error) return `Lock check failed: ${result.error}`;
          if (result.Success) return `Lock acquired: ${args.filePath} (${result.FlatName})`;

          const decision = result.Decision ? `\nOptions: ${result.Decision.join(", ")}` : "";
          return `Failed to acquire lock for ${args.filePath}${result.Owner ? ` (held by ${result.Owner})` : ""}${decision}`;
        },
      }),

      release_lock: tool({
        description: "Release a session file lock after editing is complete.",
        args: {
          filePath: tool.schema.string().describe("Absolute or repo-relative path to unlock"),
        },
        async execute(args: any) {
          if (isReadOnlyHost()) return "Lock release skipped: READ_ONLY host";
          const result = await releaseFileLock(directory, args.filePath);
          return result.Success ? `Lock released: ${args.filePath}` : `Failed to release lock: ${result.Reason}`;
        },
      }),

      check_lock: tool({
        description: "Report which live session, if any, holds a lock on a file.",
        args: {
          filePath: tool.schema.string().describe("Absolute or repo-relative path to check"),
        },
        async execute(args: any, context: any) {
          const sessionId = context?.sessionID;
          if (!sessionId) return "Error: session ID required";
          if (isReadOnlyHost()) return "Lock check skipped: READ_ONLY host";

          const contention = await findContention(directory, sessionId, args.filePath);
          if (!contention) return `No live lock on ${args.filePath}`;
          return `${args.filePath} is locked by ${contention.owner} (${contention.lockPath})`;
        },
      }),
    },
  };
};

export default LockEnforcePlugin;