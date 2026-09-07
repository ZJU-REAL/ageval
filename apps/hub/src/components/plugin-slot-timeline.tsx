import { HoverTip } from "@/components/hover-tip";
import type { DeclaredSlot, PluginPreview } from "@/lib/api";

/** Host slot vocabulary from src/ageval/plugins/slots.py — exclusive + chain only. */
const SLOT_LEVEL: Record<string, number> = {
  environment: 0,
  before_environment: 0,
  after_environment_ready: 0,
  environment_setup: 0,
  after_environment: 0,
  before_run: 1,
  after_run: 1,
  executor: 2,
  before_agent_open: 2,
  after_agent_open: 2,
  before_agent_invoke: 2,
  after_agent_invoke: 2,
  before_agent_close: 2,
  after_agent_close: 2,
  normalize_agent_result: 2,
  before_evaluate: 3,
  after_evaluate: 3,
  trajectory_collect: 4,
  trajectory_enrich: 4,
  cleanup_report: 5,
};

export function declaredSlotsFromPreview(
  preview: PluginPreview | null,
): DeclaredSlot[] {
  const listed = preview?.declared;
  if (Array.isArray(listed) && listed.length) {
    return listed.map((d) => ({
      ...d,
      level: typeof d.level === "number" ? d.level : SLOT_LEVEL[d.id],
    }));
  }
  const out: DeclaredSlot[] = [];
  for (const id of preview?.slots?.exclusive || []) {
    out.push({ id, kind: "exclusive", level: SLOT_LEVEL[id] });
  }
  for (const id of preview?.slots?.chain || []) {
    out.push({ id, kind: "chain", level: SLOT_LEVEL[id] });
  }
  return out;
}

const LEVEL_LABELS = [
  "Environment",
  "Run",
  "Agent executor and session",
  "Evaluation",
  "Trajectory",
  "Cleanup",
] as const;

export function resolvePluginEntryPath(
  entry: string | undefined,
  files: string[],
): string {
  const fallback = files.includes("plugin.yaml")
    ? "plugin.yaml"
    : files.includes("ageval.plugin.yaml")
      ? "ageval.plugin.yaml"
      : files[0] || "plugin.yaml";
  if (!entry) return fallback;
  const mod = entry.split(":")[0]?.trim();
  if (!mod) return fallback;
  const rel = `${mod.replaceAll(".", "/")}.py`;
  const hit = files.find(
    (f) => f === rel || f.endsWith(`/${rel}`) || f.endsWith(rel),
  );
  return hit || fallback;
}

function declaredForLevel(declared: DeclaredSlot[], level: number): DeclaredSlot[] {
  return declared.filter((d) => d.level === level);
}

export function PluginSlotTimeline({
  declared,
  files,
  onOpenPath,
}: {
  declared: DeclaredSlot[];
  files: string[];
  onOpenPath: (path: string) => void;
}) {
  if (!declared.length) {
    return (
      <p className="text-sm text-mute">
        No slot preview available (open{" "}
        <span className="text-xs">plugin.yaml</span> in files).
      </p>
    );
  }

  return (
    <div className="blob-panel overflow-hidden">
      <ol className="divide-y divide-hairline">
        {LEVEL_LABELS.map((label, level) => {
          const slots = declaredForLevel(declared, level);
          const hit = slots.length > 0;
          return (
            <li
              key={level}
              className={
                hit
                  ? "flex items-center gap-3 px-3 py-2.5 text-ink bg-canvas-soft"
                  : "flex items-center gap-3 px-3 py-2.5 text-mute bg-canvas"
              }
            >
              <span className="text-[11px] w-6 shrink-0">
                L{level}
              </span>
              <span
                className={
                  hit
                    ? "h-2 w-2 rounded-full border border-mute bg-mute/70 shrink-0"
                    : "h-2 w-2 rounded-full border border-hairline-strong bg-transparent shrink-0"
                }
                aria-hidden
              />
              <span className="text-sm font-medium shrink-0">{label}</span>
              {hit ? (
                <span className="ml-auto flex min-w-0 flex-wrap justify-end gap-x-3 gap-y-1">
                  {slots.map((slot) => {
                    const path = resolvePluginEntryPath(slot.entry, files);
                    return (
                      <HoverTip
                        key={`${slot.kind}-${slot.id}`}
                        content={path}
                      >
                        <button
                          type="button"
                          onClick={() => onOpenPath(path)}
                          className="cursor-pointer text-xs text-ink underline-offset-2 hover:underline hover:decoration-mute"
                        >
                          {slot.id}
                        </button>
                      </HoverTip>
                    );
                  })}
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
