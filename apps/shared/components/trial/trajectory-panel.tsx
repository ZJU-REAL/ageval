import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type MouseEvent,
  type ReactNode,
  type RefObject,
} from "react";
import {
  BotMessageSquare,
  Brain,
  Check,
  ChevronDown,
  Copy,
  Eye,
  FilePenLine,
  FileSearch,
  FoldVertical,
  LayoutGrid,
  MessageSquare,
  Shield,
  SquareTerminal,
  UnfoldVertical,
  User,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { HoverTip } from "@ageval/shared/components/hover-tip";
import { MarkdownBody } from "@ageval/shared/components/markdown";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ageval/shared/components/ui/select";
import type { TrajectoryStep } from "@ageval/shared/lib/trial-types";
import { CodeHighlight } from "@ageval/shared/lib/code-highlight";
import { findScrollParent } from "@ageval/shared/lib/scroll-port";
import { cn } from "@ageval/shared/lib/utils";

import { TrajectoryOutline } from "./trajectory-outline";
import { actorLabel, type ActorRow } from "./types";

type IconComp = ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

type StepMajor =
  | "user"
  | "agent"
  | "thought"
  | "tool_call"
  | "observation"
  | "terminal"
  | "permission"
  | "message";

type BodyKind = "markdown" | "json" | "text";

/* Per-major-type icon tone; reuses the shared categorical token palette. */
const STEP_TONE: Record<StepMajor, string> = {
  user: "text-link",
  agent: "text-nav-agents",
  thought: "text-warning",
  tool_call: "text-nav-plugins",
  observation: "text-nav-datasets",
  terminal: "text-nav-home",
  permission: "text-nav-inbox",
  message: "text-mute",
};

const KIND_FILTERS: {
  id: StepMajor;
  label: string;
  icon: LucideIcon;
}[] = [
  { id: "user", label: "User", icon: User },
  { id: "agent", label: "Agent", icon: BotMessageSquare },
  { id: "thought", label: "Thought", icon: Brain },
  { id: "tool_call", label: "Tools", icon: Wrench },
  { id: "observation", label: "Observation", icon: Eye },
  { id: "terminal", label: "Terminal", icon: SquareTerminal },
  { id: "permission", label: "Permission", icon: Shield },
  { id: "message", label: "Message", icon: MessageSquare },
];

export type TrajectoryKind = "all" | StepMajor;

const TRAJ_PORT_CLASS =
  "h-[70vh] overflow-y-auto pr-1 [overflow-anchor:none]";

function TrajectorySkeleton() {
  return (
    <div className="space-y-2" aria-hidden>
      {[0, 1, 2].map((i) => (
        <div key={i} className="blob-panel overflow-clip">
          <div className="border-b border-hairline bg-canvas px-3 pt-3 pb-1.5">
            <div className="h-3 w-24 rounded-[4px] bg-canvas-soft-2" />
          </div>
          <div className="space-y-2 px-4 py-2">
            <div className="h-3 w-[88%] rounded-[4px] bg-canvas-soft" />
            <div className="h-3 w-[64%] rounded-[4px] bg-canvas-soft" />
          </div>
        </div>
      ))}
    </div>
  );
}

/* Folded steps preview ~this many lines; the next half-line fades as a hint. */
const PREVIEW_LINES = 2.5;

/* Folded preview: height + a fade-out over the final half-line. */
const PREVIEW_FOLD: Record<BodyKind, string> = {
  json: "max-h-[50px] [mask-image:linear-gradient(to_bottom,black_40px,transparent_50px)]",
  markdown:
    "max-h-[60px] [mask-image:linear-gradient(to_bottom,black_48px,transparent_60px)]",
  text: "max-h-[50px] [mask-image:linear-gradient(to_bottom,black_40px,transparent_50px)]",
};

/** Sealed jsonl still has these; the panel does not draw the auto-approve pile. */
function isBatchAutoApprovePermission(step: TrajectoryStep): boolean {
  return (
    (step.type || "") === "permission_decision" &&
    step.policy === "batch_auto_approve"
  );
}

function classifyStep(s: TrajectoryStep): {
  major: StepMajor;
  role: string;
  label: string;
  isUser: boolean;
  isAsst: boolean;
  isThought: boolean;
  isToolCall: boolean;
  isObservation: boolean;
  isTerminal: boolean;
  isPermission: boolean;
} {
  const stepType = (s.type || "").toString();
  const isToolCall = stepType === "tool_call";
  const isObservation = stepType === "observation";
  const isPermission = stepType === "permission_decision";
  const role = (
    s.role ||
    (isToolCall
      ? "tool_call"
      : isObservation
        ? "observation"
        : isPermission
          ? "permission"
          : stepType || "event")
  ).toString();
  const isUser = role === "user";
  const isThought = (s.part || "").toString() === "thought";
  const isAsst = role === "assistant" && !isThought;
  const isTerminal = stepType === "terminal";
  const major: StepMajor = isUser
    ? "user"
    : isThought
      ? "thought"
      : isAsst
        ? "agent"
        : isObservation
          ? "observation"
          : isTerminal
            ? "terminal"
            : isPermission
              ? "permission"
              : isToolCall
                ? "tool_call"
                : "message";
  const label = isToolCall
    ? s.function_name || s.kind || s.title || "tool_call"
    : isObservation
      ? "observation"
      : isThought
        ? "thought"
        : isAsst
          ? "agent"
          : role;
  return {
    major,
    role,
    label,
    isUser,
    isAsst,
    isThought,
    isToolCall,
    isObservation,
    isTerminal,
    isPermission,
  };
}

export function TrajectoryKindFilter({
  steps,
  value,
  onChange,
}: {
  steps: TrajectoryStep[];
  value: TrajectoryKind;
  onChange: (next: TrajectoryKind) => void;
}) {
  const items = useMemo(() => {
    const found = new Set<StepMajor>();
    for (const step of steps) {
      if (isBatchAutoApprovePermission(step)) continue;
      found.add(classifyStep(step).major);
    }
    if (found.size < 2) return [];
    return [
      {
        id: "all" as const,
        label: "All",
        icon: LayoutGrid,
      },
      ...KIND_FILTERS.filter((item) => found.has(item.id)),
    ];
  }, [steps]);

  useEffect(() => {
    if (value !== "all" && !items.some((item) => item.id === value)) onChange("all");
  }, [items, onChange, value]);

  if (items.length === 0) return null;
  const selected = items.some((item) => item.id === value) ? value : "all";
  const current = items.find((item) => item.id === selected) ?? items[0];
  const CurrentIcon = current.icon;
  const tone = selected === "all" ? "text-mute" : STEP_TONE[selected];
  return (
    <div className="ml-auto shrink-0">
      <Select
        value={selected}
        onValueChange={(next) => {
          if (items.some((item) => item.id === next)) onChange(next as TrajectoryKind);
        }}
      >
        <SelectTrigger aria-label="Trajectory steps" className="h-9 w-auto min-w-[8.5rem]">
          <span className="inline-flex items-center gap-2">
            <CurrentIcon className={cn("size-3.5", tone)} aria-hidden />
            <SelectValue />
          </span>
        </SelectTrigger>
        <SelectContent className="w-max min-w-[var(--radix-select-trigger-width)]">
          {items.map((item) => {
            const Icon = item.icon;
            const itemTone = item.id === "all" ? "text-mute" : STEP_TONE[item.id];
            return (
              <SelectItem
                key={item.id}
                value={item.id}
                mono={false}
                leading={<Icon className={cn("size-3.5", itemTone)} aria-hidden />}
              >
                {item.label}
              </SelectItem>
            );
          })}
        </SelectContent>
      </Select>
    </div>
  );
}

function overflowsPreview(el: HTMLElement): boolean {
  const probe =
    el.firstElementChild instanceof HTMLElement ? el.firstElementChild : el;
  const lh = parseFloat(getComputedStyle(probe).lineHeight);
  const line = Number.isFinite(lh) && lh > 0 ? lh : 20;
  return el.scrollHeight > PREVIEW_LINES * line + 1;
}

function parsesAsJson(text: string): boolean {
  const t = text.trim();
  if (!t.startsWith("{") && !t.startsWith("[")) return false;
  try {
    const v: unknown = JSON.parse(t);
    return typeof v === "object" && v !== null;
  } catch {
    return false;
  }
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value;
}

function stepElapsedMs(s: {
  elapsed_ms?: number | null;
  metadata?: Record<string, unknown> | null;
}): number | null {
  const direct = asFiniteNumber(s.elapsed_ms);
  if (direct != null && direct >= 0) return direct;
  const lat = asFiniteNumber(s.metadata?.latency_ms);
  if (lat != null && lat >= 0) return lat;
  return null;
}

function formatElapsedMs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const totalS = ms / 1000;
  if (totalS < 10) return `${totalS.toFixed(1)}s`;
  if (totalS < 60) return `${Math.round(totalS)}s`;
  const minutes = Math.floor(totalS / 60);
  const seconds = Math.round(totalS - minutes * 60);
  if (seconds === 60) return `${minutes + 1}m`;
  return seconds ? `${minutes}m ${String(seconds).padStart(2, "0")}s` : `${minutes}m`;
}

function CopyBodyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  async function onCopy(e: MouseEvent<HTMLButtonElement>) {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      /* ignore */
    }
  }
  return (
    <HoverTip content={copied ? "Copied" : "Copy"}>
    <button
      type="button"
      onClick={onCopy}
      aria-label={copied ? "Copied" : "Copy step"}
      className="shrink-0 rounded-[4px] p-0.5 text-mute hover:bg-row-hover hover:text-ink"
    >
      {copied ? (
        <Check className="h-3.5 w-3.5" aria-hidden />
      ) : (
        <Copy className="h-3.5 w-3.5" aria-hidden />
      )}
    </button>
    </HoverTip>
  );
}

function stepBodyContent(body: string, kind: BodyKind) {
  if (kind === "json") {
    return (
      <pre className="m-0 overflow-x-auto font-mono text-[12px] leading-5">
        <CodeHighlight content={body} />
      </pre>
    );
  }
  if (kind === "markdown") {
    return <MarkdownBody source={body} />;
  }
  return (
    <pre className="m-0 whitespace-pre-wrap break-words font-mono text-[13px] leading-5 text-body">
      {body}
    </pre>
  );
}

function outlineText(s: TrajectoryStep): string {
  const { label, isToolCall } = classifyStep(s);
  if (isToolCall) {
    return (s.function_name || s.kind || s.title || label).toString().trim() || label;
  }
  const content = (s.content || "").replace(/\s+/g, " ").trim();
  return content || label;
}

function stepIcon(opts: {
  isUser: boolean;
  isAsst: boolean;
  isThought: boolean;
  isToolCall: boolean;
  isObservation: boolean;
  isTerminal: boolean;
  isPermission: boolean;
  kind?: string | null;
  functionName?: string | null;
}): IconComp {
  if (opts.isUser) return User;
  if (opts.isThought) return Brain;
  if (opts.isAsst) return BotMessageSquare;
  if (opts.isObservation) return Eye;
  if (opts.isTerminal) return SquareTerminal;
  if (opts.isPermission) return Shield;
  if (opts.isToolCall) {
    const k = (opts.kind || opts.functionName || "").toLowerCase();
    if (k === "execute" || k === "bash" || k === "shell") return SquareTerminal;
    if (k === "read" || k === "search" || k === "fetch") return FileSearch;
    if (k === "edit" || k === "write" || k === "delete" || k === "move")
      return FilePenLine;
    return Wrench;
  }
  return MessageSquare;
}

function StepItem({
  s,
  stepId,
  hideTurnIndex,
  allExpanded,
  expandGen,
}: {
  s: TrajectoryStep;
  stepId: string;
  hideTurnIndex: boolean;
  allExpanded: boolean;
  expandGen: number;
}) {
  const liRef = useRef<HTMLLIElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const repositionRef = useRef(false);
  const [overflows, setOverflows] = useState(false);
  const [open, setOpen] = useState(true);

  const {
    major,
    label,
    isUser,
    isAsst,
    isThought,
    isToolCall,
    isObservation,
    isTerminal,
    isPermission,
  } = classifyStep(s);
  const Icon = stepIcon({
    isUser,
    isAsst,
    isThought,
    isToolCall,
    isObservation,
    isTerminal,
    isPermission,
    kind: s.kind,
    functionName: s.function_name,
  });
  const toolArgsEmpty =
    s.args == null ||
    (typeof s.args === "object" &&
      !Array.isArray(s.args) &&
      Object.keys(s.args).length === 0);
  let body: string | null =
    s.content ||
    (isToolCall && !toolArgsEmpty
      ? typeof s.args === "string"
        ? s.args
        : JSON.stringify(s.args, null, 2)
      : null) ||
    (isToolCall && s.title ? s.title : null) ||
    (isObservation && s.raw_output != null
      ? typeof s.raw_output === "string"
        ? s.raw_output
        : JSON.stringify(s.raw_output, null, 2)
      : null);

  // permission / terminal: synthesize body from structured fields when needed
  if (!body && isPermission) {
    const bits = [
      s.policy != null && s.policy !== "" ? `policy=${s.policy}` : null,
      s.outcome != null && s.outcome !== "" ? `outcome=${s.outcome}` : null,
      s.option_id != null && s.option_id !== ""
        ? `option_id=${s.option_id}`
        : null,
    ].filter(Boolean) as string[];
    body = bits.length ? bits.join(" · ") : null;
  }
  if (!body && isTerminal) {
    const bits: string[] = [];
    if (s.ok === true) bits.push("ok");
    else if (s.ok === false) bits.push("not ok");
    if (s.stop_reason) bits.push(`stop=${s.stop_reason}`);
    if (s.error) bits.push(`error=${String(s.error)}`);
    if (s.metadata && typeof s.metadata === "object") {
      const meta = s.metadata;
      const metaBits = (
        [
          "executor_kind",
          "acp_entry_id",
          "actual_model",
          "locked_model",
          "protocol_version",
        ] as const
      )
        .filter((k) => meta[k] != null && meta[k] !== "")
        .map((k) => `${k}=${String(meta[k])}`);
      if (metaBits.length) bits.push(metaBits.join(" "));
    }
    body = bits.length ? bits.join(" · ") : null;
  }
  // Text bodies render as markdown; structured tool/observation
  // payloads render as highlighted JSON code blocks; the synthesized
  // permission/terminal summaries stay plain.
  const bodyKind: BodyKind = !body
    ? "text"
    : isTerminal || isPermission
      ? "text"
      : isToolCall || isObservation
        ? parsesAsJson(body)
          ? "json"
          : "text"
        : "markdown";
  // Success is the common case for folded tool/observation rows; only
  // surface non-success status (failed / error / cancelled / …).
  const statusRaw = typeof s.status === "string" ? s.status.trim() : "";
  const statusLower = statusRaw.toLowerCase();
  const showStatus =
    Boolean(statusRaw) &&
    !["completed", "complete", "success", "ok", "done"].includes(statusLower);

  useLayoutEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const check = () => setOverflows(overflowsPreview(el));
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
    // Re-check when the fold branch swaps so the observer re-measures.
  }, [body, bodyKind, overflows]);

  useEffect(() => {
    if (!overflows || expandGen === 0) return;
    setOpen(allExpanded);
  }, [overflows, allExpanded, expandGen]);

  // Collapse/expand while this header is stuck: after the DOM shrinks (or the
  // body grows above the viewport), put the block's top back at the top of
  // the scrollport so the view stays on the block being operated on.
  function toggleOpen() {
    const li = liRef.current;
    if (li) {
      const scroller = findScrollParent(li);
      const offset =
        parseFloat(getComputedStyle(scroller).getPropertyValue("--traj-invoke-h")) ||
        0;
      const delta =
        li.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
      if (delta < offset - 1) repositionRef.current = true;
    }
    setOpen((v) => !v);
  }

  useLayoutEffect(() => {
    if (!repositionRef.current) return;
    repositionRef.current = false;
    const li = liRef.current;
    if (!li) return;
    const scroller = findScrollParent(li);
    const offset =
      parseFloat(getComputedStyle(scroller).getPropertyValue("--traj-invoke-h")) ||
      0;
    const target =
      li.getBoundingClientRect().top -
      scroller.getBoundingClientRect().top +
      scroller.scrollTop -
      offset;
    scroller.scrollTop = Math.max(0, target);
  }, [open]);

  const collapsed = overflows && !open;

  return (
    <li
      ref={liRef}
      data-traj-step={stepId}
      className={cn("blob-panel overflow-clip", isObservation && "bg-canvas-soft/40")}
    >
      <div
        className={cn(
          "sticky top-[var(--traj-invoke-h,0px)] z-10 rounded-t-lg border-b border-hairline bg-canvas px-3 pt-3 pb-1.5 text-xs",
        )}
      >
        <div className="flex items-start gap-3">
          <div className="flex flex-wrap items-center gap-2 min-w-0">
            <span className="inline-flex items-center gap-1.5 font-semibold uppercase tracking-wide text-ink">
              <Icon
                className={cn("h-3.5 w-3.5 shrink-0", STEP_TONE[major])}
                aria-hidden
              />
              {label}
            </span>
            {!hideTurnIndex && s.turn_index != null ? (
              <span className="text-mute font-normal normal-case tracking-normal">
                turn {s.turn_index}
              </span>
            ) : null}
            {s.kind && isToolCall && s.kind !== label ? (
              <span className="rounded bg-canvas-soft border border-hairline px-1.5 py-0 text-[11px] text-mute font-normal normal-case tracking-normal">
                {s.kind}
              </span>
            ) : null}
          </div>
          <div className="ml-auto flex flex-col items-end gap-0.5 min-w-0 max-w-[min(100%,36rem)] text-right text-mute font-normal normal-case tracking-normal">
            {showStatus ? (
              <span
                className={cn(
                  statusLower.includes("fail") ||
                    statusLower.includes("error") ||
                    statusLower.includes("cancel")
                    ? "text-error"
                    : undefined,
                )}
              >
                {statusRaw}
              </span>
            ) : null}
            {s.stop_reason ? <span>{s.stop_reason}</span> : null}
            {s.ok === false ? <span className="text-error">not ok</span> : null}
            {(() => {
              const elapsed = stepElapsedMs(s);
              return elapsed != null ? (
                <HoverTip content="duration (observational)">
                  <span>{formatElapsedMs(elapsed)}</span>
                </HoverTip>
              ) : null;
            })()}
          </div>
          {body && overflows ? (
            <HoverTip content={open ? "Collapse" : "Expand"}>
              <button
                type="button"
                onClick={toggleOpen}
                aria-expanded={open}
                aria-label={open ? "Collapse step" : "Expand step"}
                className="shrink-0 rounded-[4px] p-0.5 text-mute hover:bg-row-hover hover:text-ink"
              >
                <ChevronDown
                  className={cn(
                    "h-3.5 w-3.5",
                    "motion-safe:transition-transform motion-safe:duration-200 motion-safe:ease-smooth",
                    open && "rotate-180",
                  )}
                  aria-hidden
                />
              </button>
            </HoverTip>
          ) : null}
          {body ? <CopyBodyButton text={body} /> : null}
        </div>
      </div>
      {body ? (
        <div className="px-4 py-2">
          <div
            className={cn(
              collapsed && "overflow-hidden",
              collapsed && PREVIEW_FOLD[bodyKind],
            )}
          >
            <div ref={contentRef}>{stepBodyContent(body, bodyKind)}</div>
          </div>
        </div>
      ) : !isTerminal ? (
        s.error ? (
          <p className="px-4 py-2 text-sm text-error">{String(s.error)}</p>
        ) : isPermission ? (
          <p className="px-4 py-2 text-sm text-mute">
            permission (no decision fields)
          </p>
        ) : isToolCall || isObservation ? (
          <p className="px-4 py-2 text-sm text-mute">
            {isToolCall ? "tool call (no args)" : "observation (empty)"}
          </p>
        ) : null
      ) : null}
    </li>
  );
}

export function TrajectoryPanel({
  loading,
  steps,
  note,
  result,
  actors,
  panelRef,
  kind = "all",
}: {
  loading: boolean;
  steps: TrajectoryStep[];
  note: string | null;
  result: Record<string, unknown> | null;
  actors: ActorRow[];
  panelRef?: RefObject<HTMLDivElement | null>;
  kind?: TrajectoryKind;
}) {
  const visibleSteps = useMemo(
    () => steps.filter((s) => !isBatchAutoApprovePermission(s)),
    [steps],
  );
  const shownSteps = useMemo(() => {
    if (kind === "all") return visibleSteps;
    return visibleSteps.filter((s) => classifyStep(s).major === kind);
  }, [kind, visibleSteps]);
  const actorByPid = useMemo(() => {
    return new Map(
      actors.map((a) => [a.profile_id || `${a.role}-${a.agent}`, a]),
    );
  }, [actors]);
  const multiRole = useMemo(() => {
    const ids = new Set<string>();
    for (const s of shownSteps) {
      if (typeof s.profile_id === "string" && s.profile_id) ids.add(s.profile_id);
    }
    if (ids.size >= 2) return true;
    const actorIds = new Set(
      actors
        .map((a) => a.profile_id)
        .filter((p): p is string => typeof p === "string" && !!p),
    );
    return actorIds.size >= 2;
  }, [shownSteps, actors]);
  const invokes = useMemo(() => {
    type Block = {
      turn: number | null;
      profileId: string | null;
      steps: TrajectoryStep[];
    };
    const blocks: Block[] = [];
    for (const s of shownSteps) {
      const turn = typeof s.turn_index === "number" ? s.turn_index : null;
      const pid =
        typeof s.profile_id === "string" && s.profile_id ? s.profile_id : null;
      const last = blocks[blocks.length - 1];
      if (last && last.turn != null && last.turn === turn) {
        last.steps.push(s);
        if (!last.profileId && pid) last.profileId = pid;
        continue;
      }
      blocks.push({ turn, profileId: pid, steps: [s] });
    }
    return blocks;
  }, [shownSteps]);
  const showInvokeHeaders = multiRole && invokes.length >= 2;
  const [allExpanded, setAllExpanded] = useState(true);
  const [expandGen, setExpandGen] = useState(0);
  const [activeStepId, setActiveStepId] = useState<string | null>(null);
  const invokeHeaderRef = useRef<HTMLHeadingElement>(null);
  const trajScrollRef = useRef<HTMLDivElement>(null);
  const outlineItems = useMemo(
    () =>
      shownSteps.map((s, i) => {
        const flags = classifyStep(s);
        const text = outlineText(s);
        return {
          id: `traj-step-${i}`,
          text,
          icon: stepIcon({
            ...flags,
            kind: s.kind,
            functionName: s.function_name,
          }),
          tone: STEP_TONE[flags.major],
          weight: Math.max(1, text.length),
        };
      }),
    [shownSteps],
  );

  // Models-page pattern: measure the sticky chrome and expose its height as
  // a CSS variable so sub-headers stick flush beneath it at any wrap width.
  useLayoutEffect(() => {
    const header = invokeHeaderRef.current;
    const container = trajScrollRef.current;
    if (!showInvokeHeaders || !header || !container) return;
    const apply = () =>
      container.style.setProperty("--traj-invoke-h", `${header.offsetHeight}px`);
    const ro = new ResizeObserver(apply);
    ro.observe(header);
    apply();
    return () => {
      ro.disconnect();
      container.style.removeProperty("--traj-invoke-h");
    };
  }, [showInvokeHeaders, invokes]);

  useEffect(() => {
    const el = trajScrollRef.current;
    if (!el) return;
    el.scrollTop = 0;
  }, [kind]);

  useEffect(() => {
    const root = trajScrollRef.current;
    if (!root || outlineItems.length < 2) return;
    const nodes = [...root.querySelectorAll<HTMLElement>("[data-traj-step]")];
    if (!nodes.length) return;
    const visible = new Map<string, number>();
    const pick = () => {
      if (!visible.size) return;
      const top = [...visible.entries()].sort((a, b) => a[1] - b[1])[0];
      if (top) setActiveStepId(top[0]);
    };
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = entry.target.getAttribute("data-traj-step");
          if (!id) continue;
          if (entry.isIntersecting) visible.set(id, entry.boundingClientRect.top);
          else visible.delete(id);
        }
        pick();
      },
      { root, rootMargin: "0px 0px -70% 0px", threshold: [0, 0.25] },
    );
    for (const node of nodes) io.observe(node);
    setActiveStepId(outlineItems[0]?.id ?? null);
    return () => io.disconnect();
  }, [outlineItems]);

  function jumpToStep(id: string) {
    const root = trajScrollRef.current;
    const el = root?.querySelector<HTMLElement>(`[data-traj-step="${id}"]`);
    if (!root || !el) return;
    setActiveStepId(id);
    const offset =
      parseFloat(getComputedStyle(root).getPropertyValue("--traj-invoke-h")) || 0;
    const top =
      el.getBoundingClientRect().top -
      root.getBoundingClientRect().top +
      root.scrollTop -
      offset;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    root.scrollTo({ top: Math.max(0, top), behavior: reduced ? "auto" : "smooth" });
  }

  function withOutline(body: ReactNode) {
    if (outlineItems.length < 2) return body;
    return (
      <div className="relative lg:pr-10 xl:pr-0">
        {body}
        <div className="pointer-events-none absolute inset-y-0 right-0 z-30 hidden w-10 lg:block xl:left-full xl:right-auto xl:w-[12.5%] xl:pl-3">
          <div className="flex h-full items-start justify-end overflow-visible">
            <TrajectoryOutline
              items={outlineItems}
              activeId={activeStepId}
              onJump={jumpToStep}
            />
          </div>
        </div>
      </div>
    );
  }

  const scroller = (children: ReactNode) => (
    <div
      ref={(el) => {
        trajScrollRef.current = el;
        if (panelRef) panelRef.current = el;
      }}
      className={cn(
        TRAJ_PORT_CLASS,
        showInvokeHeaders && "space-y-4",
      )}
    >
      {children}
    </div>
  );

  if (loading && !visibleSteps.length) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-mute">
            Trajectory is observational only; independent evaluator owns PASS.
          </p>
          <span className="h-3.5 w-3.5 shrink-0" aria-hidden />
        </div>
        {scroller(
          <div role="status" aria-live="polite" aria-busy="true">
            <span className="sr-only">Loading trajectory</span>
            <TrajectorySkeleton />
          </div>,
        )}
      </div>
    );
  }
  if (!visibleSteps.length) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-mute">No trajectory.jsonl steps for this run.</p>
        {result ? (
          <pre className="text-[12px] font-mono bg-canvas-soft rounded-[12px] p-3 overflow-auto max-h-64">
            {JSON.stringify(result, null, 2)}
          </pre>
        ) : null}
      </div>
    );
  }

  function renderSteps(list: TrajectoryStep[], hideTurnIndex = false, start = 0) {
    return (
      <ol className="space-y-2">
        {list.map((s, i) => (
          <StepItem
            key={`${s.invocation || ""}-${s.line || i}-${start + i}`}
            s={s}
            stepId={`traj-step-${start + i}`}
            hideTurnIndex={hideTurnIndex}
            allExpanded={allExpanded}
            expandGen={expandGen}
          />
        ))}
      </ol>
    );
  }

  return (
    <div className="space-y-3">
      {note ? <p className="text-xs text-mute">{note}</p> : null}
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-mute">
          Trajectory is observational only; independent evaluator owns PASS.
        </p>
        <HoverTip content={allExpanded ? "Collapse all" : "Expand all"}>
        <button
          type="button"
          onClick={() => {
            setAllExpanded((v) => !v);
            setExpandGen((n) => n + 1);
          }}
          aria-label={allExpanded ? "Collapse all" : "Expand all"}
          className="shrink-0 rounded-[4px] p-0.5 text-mute hover:bg-row-hover hover:text-ink"
        >
          {allExpanded ? (
            <FoldVertical className="h-3.5 w-3.5" aria-hidden />
          ) : (
            <UnfoldVertical className="h-3.5 w-3.5" aria-hidden />
          )}
        </button>
        </HoverTip>
      </div>
      {shownSteps.length === 0 ? (
        <p className="text-sm text-mute">No steps in this view.</p>
      ) : showInvokeHeaders ? (
        withOutline(
          scroller(
            (() => {
              let cursor = 0;
              return invokes.map((block, i) => {
                const start = cursor;
                cursor += block.steps.length;
                const actor = block.profileId
                  ? actorByPid.get(block.profileId)
                  : undefined;
                const who = block.profileId
                  ? actorLabel(actor, block.profileId)
                  : null;
                const title =
                  block.turn != null
                    ? who
                      ? `invoke ${block.turn} · ${who}`
                      : `invoke ${block.turn}`
                    : who || "invoke";
                return (
                  <section key={`${block.turn ?? "x"}-${i}`} className="space-y-2">
                    <h3
                      ref={i === 0 ? invokeHeaderRef : undefined}
                      className="relative sticky top-0 z-20 bg-canvas py-1 text-xs font-medium text-ink"
                    >
                      {title}
                      <span className="text-mute font-normal ml-2">
                        {block.steps.length} step
                        {block.steps.length === 1 ? "" : "s"}
                      </span>
                    </h3>
                    {renderSteps(block.steps, true, start)}
                  </section>
                );
              });
            })(),
          ),
        )
      ) : (
        withOutline(scroller(renderSteps(shownSteps)))
      )}
    </div>
  );
}
