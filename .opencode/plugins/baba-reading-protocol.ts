/**
 * Reading Protocol Plugin for opencode
 *
 * Enforces complete reading before analysis output:
 * - Computes dependency closure (depth 3) when a target file is read
 * - Tracks file read status in Reading Plan
 * - Blocks analysis output when Reading Plan is incomplete
 *
 * Hooks:
 *   1. session.created  -> initialize reading state
 *   2. tool.execute.after (read) -> track reads, lazily initialize plan,
 *                                   verify completion
 *   3. session.deleted  -> cleanup
 */

interface ReadingPlanFile {
  path: string;
  status: "pending" | "complete" | "deferred";
}

interface ReadingPlan {
  scope: string;
  created_at: string;
  status:
    "in_progress" | "complete" | "partial-approved" | "skipped-greenfield";
  files: ReadingPlanFile[];
}

interface ReadingState {
  sessionId: string;
  plan: ReadingPlan | null;
  blocked: boolean;
  lastUnreadFiles: string[];
}

const readingStates = new Map<string, ReadingState>();

function getOrCreateState(sessionId: string): ReadingState {
  let state = readingStates.get(sessionId);
  if (!state) {
    state = {
      sessionId,
      plan: null,
      blocked: false,
      lastUnreadFiles: [],
    };
    readingStates.set(sessionId, state);
  }
  return state;
}

function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function computeImportClosure(
  directory: string,
  targetPath: string,
  maxDepth: number,
  maxCalls: number,
  $: any,
): Promise<string[]> {
  const excludedDirs = [
    "node_modules",
    "vendor",
    "prompt-system",
    "dist",
    "build",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
  ];
  const sourceExts = [
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".py",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
  ];
  const testPatterns = [".test.", ".spec.", "test_"];
  const closure = new Set<string>();
  const visited = new Set<string>();
  const queue: { path: string; depth: number }[] = [
    { path: targetPath, depth: 0 },
  ];
  let calls = 0;

  const isExcluded = (p: string) =>
    excludedDirs.some((d) => p.includes(`/${d}/`) || p.includes(`\\${d}\\`));

  const isSource = (p: string) => sourceExts.some((ext) => p.endsWith(ext));
  const isTest = (p: string) => testPatterns.some((t) => p.includes(t));

  const addIfSource = (p: string) => {
    if (isSource(p) && !isExcluded(p)) {
      closure.add(p);
    }
  };

  const resolveImport = (base: string, rawImport: string): string | null => {
    const trimmed = rawImport.replace(/['";]/g, "").trim();
    if (!trimmed || trimmed.startsWith(".") === false) return null;
    const baseDir = base.substring(
      0,
      base.lastIndexOf("/") >= 0
        ? base.lastIndexOf("/")
        : base.lastIndexOf("\\"),
    );
    const resolved = `${baseDir}/${trimmed}`;
    const withExt = sourceExts.find((ext) => resolved.endsWith(ext))
      ? resolved
      : `${resolved}.ts`;
    return withExt;
  };

  while (queue.length > 0 && calls < maxCalls) {
    const { path: current, depth } = queue.shift()!;
    if (visited.has(current)) continue;
    visited.add(current);
    addIfSource(current);
    if (depth >= maxDepth) continue;

    const absolutePath = `${directory}/${current}`;
    let content: string;
    try {
      content = await $`cat ${absolutePath}`.text();
    } catch {
      continue;
    }
    calls++;

    const importRegex = /import\s+.*?from\s+['"]([^'"]+)['"]/g;
    let match;
    while ((match = importRegex.exec(content)) !== null && calls < maxCalls) {
      const resolved = resolveImport(current, match[1]);
      if (resolved && !visited.has(resolved)) {
        queue.push({ path: resolved, depth: depth + 1 });
      }
    }

    const fileName = current.substring(
      current.lastIndexOf("/") >= 0
        ? current.lastIndexOf("/") + 1
        : current.length,
    );
    try {
      const out =
        await $`rg --no-heading --line-number "import\\s+.*?${escapeRegex(fileName)}" ${directory}`.text();
      const lines = out.trim().split("\n").filter(Boolean);
      for (const line of lines) {
        const rp = line.split(":")[0];
        if (!visited.has(rp) && isSource(rp)) {
          queue.push({ path: rp, depth: depth + 1 });
        }
      }
    } catch {
      // reverse lookup unavailable; continue without it
    }
    calls++;
  }

  for (const file of closure) {
    const base = file.replace(`${directory}/`, "");
    const baseName = base.endsWith(".ts") ? base.slice(0, -".ts".length) : base;
    const testFiles = sourceExts.flatMap((ext) => {
      const name = base.endsWith(ext) ? base.slice(0, -ext.length) : base;
      return [name + ".test" + ext, name + ".spec" + ext, "test_" + name + ext];
    });
    for (const tf of testFiles) {
      const testPath = `${directory}/${tf}`;
      try {
        await $`cat ${testPath}`.text();
        closure.add(tf);
      } catch {
        // test file does not exist, skip
      }
    }
  }

  return Array.from(closure);
}

export default async ({
  client,
  $,
  project,
  directory,
  worktree,
}: {
  client: any;
  $: any;
  project: any;
  directory: string;
  worktree: string;
}) => {
  return {
    event: async ({ event }: { event: any }) => {
      const sessionId = event.properties?.sessionID;
      if (!sessionId) return;

      const state = getOrCreateState(sessionId);

      if (event.type === "session.created") {
        state.plan = null;
        state.blocked = false;
        state.lastUnreadFiles = [];
        console.log(`[reading-protocol] Session created: ${sessionId}`);
        return;
      }

      if (event.type === "session.deleted") {
        readingStates.delete(sessionId);
        console.log(`[reading-protocol] Session deleted: ${sessionId}`);
        return;
      }
    },

    "tool.execute.after": async (
      input: { tool: string; sessionID: string; callID: string; args: any },
      output: any,
    ) => {
      const sessionId = input.sessionID;
      if (!sessionId || input.tool !== "read") return;

      const state = getOrCreateState(sessionId);
      const readPath = input.args?.filePath;
      if (!readPath) return;

      // Lazily initialize plan on first read using the read file as target
      if (!state.plan) {
        const relativeTarget = readPath.startsWith(directory)
          ? readPath.substring(directory.length + 1)
          : readPath;
        const files = await computeImportClosure(
          directory,
          relativeTarget,
          3,
          30,
          $,
        );
        state.plan = {
          scope: relativeTarget,
          created_at: new Date().toISOString(),
          status: "in_progress",
          files: files.map((f) => ({ path: f, status: "pending" })),
        };
        console.log(
          `[reading-protocol] Reading Plan created for ${sessionId}: ${files.length} files`,
        );
      }

      // Mark file as complete
      if (state.plan) {
        const fileEntry = state.plan.files.find((f) => f.path === readPath);
        if (fileEntry && fileEntry.status === "pending") {
          fileEntry.status = "complete";
          console.log(`[reading-protocol] Marked complete: ${readPath}`);
        }
      }

      if (
        state.plan &&
        state.plan.files.every((f) => f.status === "complete")
      ) {
        state.plan.status = "complete";
        state.blocked = false;
        state.lastUnreadFiles = [];
        console.log(
          `[reading-protocol] Reading Plan complete for ${sessionId}`,
        );
      }
    },
  };
};
