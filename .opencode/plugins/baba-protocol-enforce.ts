/**
 * Protocol Enforcement Plugin for opencode
 *
 * Enforces cross-cutting protocols at phase transitions:
 * - Artifact handling (gitignore, .gitattributes)
 * - Pre-commit behavior
 * - Cross-team requirements
 * - Library selection
 * - Spec lifecycle / DRIFT
 *
 * Phase transitions are detected via phase-detect.ts, which parses
 * assistant message text for [PHASE: X] headers. opencode session
 * metadata does not carry phase information.
 */

import {
  getCurrentPhase,
  updatePhaseFromMessages,
} from "../lib/baba-phase-detect";
import { access, readFile } from "node:fs/promises";

async function fileExists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

interface ProtocolState {
  sessionId: string;
  currentPhase: string;
  specVersion: string | null;
  hasSpec: boolean;
  editedFiles: string[];
  protocolsChecked: Set<string>;
  planVersion: number; // 1 = PLAN v1 start, 2 = post-reload
}

const protocolStates = new Map<string, ProtocolState>();

const PHASE_TRANSITIONS = {
  REVIEW: ["artifact-handling", "pre-commit"],
  PLAN: ["cross-team"],
  PATCH: [],
  DRIFT: ["spec-fileExists"],
  CHECKLIST: ["artifact-handling"],
};

const PROTOCOL_CHECKS = {
  "artifact-handling": async (
    directory: string,
    _editedFiles: string[],
    _state: any,
  ) => {
    const checks = [];
    const gitignorePath = `${directory}/.gitignore`;
    const hasGitignore = await fileExists(gitignorePath);
    if (!hasGitignore) {
      checks.push({
        protocol: "artifact-handling",
        passed: false,
        message: ".gitignore missing",
      });
    } else {
      const content = await readFile(gitignorePath, "utf-8");
      const required = [".playwright-mcp/"];
      for (const req of required) {
        if (!content.includes(req)) {
          checks.push({
            protocol: "artifact-handling",
            passed: false,
            message: `gitignore missing: ${req}`,
          });
        }
      }
    }
    const gitattributesPath = `${directory}/.gitattributes`;
    const hasGitattributes = await fileExists(gitattributesPath);
    if (!hasGitattributes) {
      checks.push({
        protocol: "gitattributes",
        passed: false,
        message: ".gitattributes missing (recommend: * text=auto eol=lf)",
      });
    }
    return checks;
  },

  "pre-commit": async (
    directory: string,
    _editedFiles: string[],
    _state: any,
  ) => {
    const checks = [];
    const precommitPath = `${directory}/.pre-commit-config.yaml`;
    const huskyPath = `${directory}/.husky/pre-commit`;
    const hasPrecommit = await fileExists(precommitPath);
    const hasHusky = await fileExists(huskyPath);
    if (!hasPrecommit && !hasHusky) {
      checks.push({
        protocol: "pre-commit",
        passed: false,
        message: "No pre-commit hooks configured (pre-commit or husky)",
      });
    } else {
      if (hasPrecommit) {
        const content = await readFile(precommitPath, "utf-8");
        const required = ["formatter", "linter", "secret"];
        for (const req of required) {
          if (!content.toLowerCase().includes(req)) {
            checks.push({
              protocol: "pre-commit",
              passed: false,
              message: `Pre-commit may lack ${req} hook`,
            });
          }
        }
      }
    }
    return checks;
  },

  "cross-team": async (
    directory: string,
    _editedFiles: string[],
    _state: any,
  ) => {
    const checks = [];
    const changesPath = `${directory}/CHANGES_REQUIRED.md`;
    const hasChanges = await fileExists(changesPath);
    if (hasChanges) {
      const content = await readFile(changesPath, "utf-8");
      const unresolved = content
        .split("## ")
        .filter(
          (s: string) => s.includes("Priority:") && !s.includes("Resolved:"),
        ).length;
      if (unresolved > 0) {
        checks.push({
          protocol: "cross-team",
          passed: false,
          message: `${unresolved} unresolved cross-team requirements in CHANGES_REQUIRED.md`,
        });
      }
    }
    return checks;
  },

  "spec-fileExists": async (
    directory: string,
    _editedFiles: string[],
    state: any,
  ) => {
    const checks = [];
    const specFile = `${directory}/SPEC.md`;
    const hasSpec = await fileExists(specFile);
    const specVersion = state.specVersion;
    if (!hasSpec || !specVersion) {
      checks.push({
        protocol: "spec",
        passed: false,
        message: "No SPEC.md or spec_version not set - DRIFT not applicable",
      });
    }
    return checks;
  },
};

async function checkProtocols(state: ProtocolState, directory: string) {
  const requiredProtocols =
    PHASE_TRANSITIONS[state.currentPhase as keyof typeof PHASE_TRANSITIONS] ||
    [];
  const allChecks = [];

  for (const protocol of requiredProtocols) {
    if (state.protocolsChecked.has(protocol)) continue;
    const checkFn = PROTOCOL_CHECKS[protocol as keyof typeof PROTOCOL_CHECKS];
    if (checkFn) {
      const checks = await checkFn(directory, state.editedFiles, state);
      allChecks.push(...checks);
      state.protocolsChecked.add(protocol);
    }
  }

  return allChecks;
}

// Credential sanitization helpers (H1 compliance)
function sanitizeGitPushOutput(output: string): string {
  return output
    .replace(/^To\s+https?:\/\/\S+$/gm, "To <url>")
    .replace(/oauth2:[^@\s]+@/g, "oauth2:<token>@")
    .replace(/x-access-token:[^@\s]+@/g, "x-access-token:<token>@")
    .replace(/https?:\/\/[^@\s]+@/g, "https://<redacted>@");
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
    "tool.execute.before": async (
      input: { tool: string; sessionID: string; callID: string },
      output: { args: any },
    ) => {
      if (input.tool !== "bash") return;

      const cmd = String(output.args?.command || "").trim();

      // 1. git remote -v / get-url → block via tokenized shell matching,
      //    so `cd /repo && git remote -v` and `git remote -v | cat` cannot evade.
      if (/(^|[;&|]\s*)git\b[^;&|]*\bremote\b[^;&|]*\s-v\b/.test(cmd)) {
        output.args.command = "git remote";
        return;
      }
      if (/(^|[;&|]\s*)git\b[^;&|]*\bremote\b[^;&|]*\bget-url\b/.test(cmd)) {
        throw new Error(
          "H1: `git remote get-url` is blocked -- remote URLs embed OAuth2/PAT tokens. " +
            "Use `git remote` (names only). If you need to verify a URL shape, ask the user.",
        );
      }
    },

    "tool.execute.after": async (
      input: { tool: string; args: any },
      output: { output: string },
    ) => {
      if (input.tool !== "bash") return;

      const cmd = (input.args?.command || "").trim();
      let out = output.output || "";

      // Sanitize git push output
      if (/^(|[;&|]\s*)git\b[^;&|]*\bpush\b/.test(cmd)) {
        out = sanitizeGitPushOutput(out);
      }

      output.output = out;
    },

    event: async ({ event }: { event: any }) => {
      const sessionId = event.properties?.sessionID;
      if (!sessionId) return;

      let state = protocolStates.get(sessionId);
      if (!state) {
        state = {
          sessionId,
          currentPhase: "STARTUP",
          specVersion: null,
          hasSpec: false,
          editedFiles: [],
          protocolsChecked: new Set(),
          planVersion: 1,
        };
        protocolStates.set(sessionId, state);
      }

      if (event.type === "session.created") {
        state.currentPhase = "STARTUP";
        state.protocolsChecked.clear();
        state.planVersion = 1;
        console.log(
          `[protocol-enforce] Session ${sessionId} created, phase: STARTUP`,
        );
        return;
      }

      if (event.type === "session.deleted") {
        protocolStates.delete(sessionId);
        console.log(`[protocol-enforce] Session ${sessionId} deleted`);
        return;
      }
    },

    "experimental.chat.messages.transform": async (
      input: any,
      output: { messages: any[] },
    ) => {
      const sessionId = input.sessionID ?? input.session_id;
      if (!sessionId) return;

      const state = protocolStates.get(sessionId);
      if (!state) return;

      updatePhaseFromMessages(sessionId, output.messages);

      const newPhase = getCurrentPhase(sessionId);
      if (!newPhase || newPhase === state.currentPhase) return;

      const previousPhase = state.currentPhase;
      state.currentPhase = newPhase;
      state.protocolsChecked.clear();

      console.log(
        `[protocol-enforce] Session ${sessionId} phase transition: ${previousPhase} -> ${newPhase}`,
      );

      // Signal PLAN v1 start at REVIEW → PLAN transition
      if (previousPhase === "REVIEW" && newPhase === "PLAN") {
        state.planVersion = 1;
        console.log(
          "[protocol-enforce] REVIEW→PLAN: planVersion=1 (prompt-system-loader will bump to 2)",
        );
      }

      const checks = await checkProtocols(state, directory);
      const failed = checks.filter((c) => !c.passed);

      if (failed.length > 0) {
        console.log(
          `[protocol-enforce] Protocol checks failed for ${newPhase}:`,
          failed.map((f) => `${f.protocol}: ${f.message}`).join(", "),
        );
      }
    },
  };
};
