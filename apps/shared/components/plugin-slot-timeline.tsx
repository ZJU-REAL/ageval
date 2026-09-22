import { HoverTip } from "@ageval/shared/components/hover-tip";

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

export type DeclaredSlot = {
  id: string;
  kind: "exclusive" | "chain";
  entry?: string;
  priority?: number;
  level?: number;
};

type SlotPreview = {
  slots?: {
    exclusive?: string[];
    chain?: string[];
  };
  declared?: DeclaredSlot[];
};

export function declaredSlotsFromPreview(preview: SlotPreview | null): DeclaredSlot[] {
  const listed = preview?.declared;
  if (Array.isArray(listed) && listed.length) {
    return listed.map((slot) => ({
      ...slot,
      level: typeof slot.level === "number" ? slot.level : SLOT_LEVEL[slot.id],
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

export function resolvePluginEntryPath(entry: string | undefined, files: string[]): string {
  const fallback = files.includes("plugin.yaml")
    ? "plugin.yaml"
    : files.includes("ageval.plugin.yaml")
      ? "ageval.plugin.yaml"
      : files[0] || "plugin.yaml";
  if (!entry) return fallback;
  const mod = entry.split(":")[0]?.trim();
  if (!mod) return fallback;
  const rel = `${mod.replaceAll(".", "/")}.py`;
  const hit = files.find((file) => file === rel || file.endsWith(`/${rel}`) || file.endsWith(rel));
  return hit || fallback;
}

function declaredForLevel(declared: DeclaredSlot[], level: number): DeclaredSlot[] {
  return declared.filter((slot) => slot.level === level);
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
        No slot preview available (open <span className="text-xs">plugin.yaml</span> in files).
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
                  ? "flex items-center gap-3 bg-canvas-soft px-3 py-2.5 text-ink"
                  : "flex items-center gap-3 bg-canvas px-3 py-2.5 text-mute"
              }
            >
              <span className="w-6 shrink-0 text-[11px]">L{level}</span>
              <span
                className={
                  hit
                    ? "h-2 w-2 shrink-0 rounded-full border border-mute bg-mute/70"
                    : "h-2 w-2 shrink-0 rounded-full border border-hairline-strong bg-transparent"
                }
                aria-hidden
              />
              <span className="shrink-0 text-sm font-medium">{label}</span>
              {hit ? (
                <span className="ml-auto flex min-w-0 flex-wrap justify-end gap-x-3 gap-y-1">
                  {slots.map((slot) => {
                    const path = resolvePluginEntryPath(slot.entry, files);
                    return (
                      <HoverTip key={`${slot.kind}-${slot.id}`} content={path}>
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
