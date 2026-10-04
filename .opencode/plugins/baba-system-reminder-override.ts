/**
 * Baba System-Reminder Override Plugin for opencode
 *
 * Intercepts the native runtime plan->build system-reminder injection
 * and replaces it with a stable, explicit reminder that matches the
 * project's preferred wording.
 *
 * Hook: experimental.chat.system.transform
 * Trigger: every assistant turn where the system prompt array contains
 * the runtime-generated plan-to-build reminder text.
 * Effect: replace that reminder with the canonical override text.
 */

const PLAN_TO_BUILD_MARKERS = [
  "operational mode has changed from plan to build",
  "no longer in read-only mode",
  "permitted to make file changes",
  "utilize your arsenal of tools",
];

const OVERRIDE_REMINDER = `<system-reminder>
Your operational mode has changed from plan to build.
You are no longer in read-only mode.
You are permitted to make file changes, run shell commands, and utilize your arsenal of tools as needed.
</system-reminder>`;

function isPlanToBuildReminder(text: string): boolean {
  const lower = text.toLowerCase();
  return PLAN_TO_BUILD_MARKERS.every((marker) => lower.includes(marker));
}

export default async () => ({
  "experimental.chat.system.transform": async (
    _ctx: unknown,
    { system }: { system: string[] },
  ): Promise<void> => {
    if (!Array.isArray(system)) return;

    const changed = system.map((block) =>
      isPlanToBuildReminder(block) ? OVERRIDE_REMINDER : block,
    );

    if (changed.length !== system.length || changed.some((v, i) => v !== system[i])) {
      system.length = 0;
      system.push(...changed);
    }
  },
});
