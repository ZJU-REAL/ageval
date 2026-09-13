import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState, type ComponentType } from "react";

import { bindToast, type ToastInput, type ToastTone } from "@ageval/shared/components/ui/toast";
import { cn } from "@ageval/shared/lib/utils";

type ToastItem = ToastInput & { id: number };

const TONE: Record<
  ToastTone,
  { Icon: ComponentType<{ className?: string }>; icon: string; bg: string }
> = {
  ok: { Icon: CircleCheck, icon: "text-link", bg: "bg-link-soft" },
  tip: { Icon: Info, icon: "text-link", bg: "bg-link-soft" },
  warn: { Icon: TriangleAlert, icon: "text-warning", bg: "bg-warning-soft" },
  error: { Icon: CircleAlert, icon: "text-error", bg: "bg-error-soft" },
};

const LEAVE_MS = 200;
const MIN_RESUME_MS = 800;

let seed = 0;

function holdMs(item: ToastItem): number {
  const tone = item.tone ?? "ok";
  return item.duration ?? (tone === "error" || tone === "warn" ? 4800 : 2400);
}

function ToastCard({
  item,
  onGone,
}: {
  item: ToastItem;
  onGone: (id: number) => void;
}) {
  const [leaving, setLeaving] = useState(false);
  const remaining = useRef(holdMs(item));
  const armedAt = useRef(0);
  const paused = useRef(false);
  const hideTimer = useRef(0);
  const goneTimer = useRef(0);
  const onGoneRef = useRef(onGone);
  onGoneRef.current = onGone;

  function clearTimers() {
    window.clearTimeout(hideTimer.current);
    window.clearTimeout(goneTimer.current);
  }

  function arm(ms: number) {
    clearTimers();
    paused.current = false;
    remaining.current = ms;
    armedAt.current = Date.now();
    hideTimer.current = window.setTimeout(() => {
      setLeaving(true);
      goneTimer.current = window.setTimeout(() => onGoneRef.current(item.id), LEAVE_MS);
    }, ms);
  }

  useEffect(() => {
    arm(holdMs(item));
    return clearTimers;
  }, [item.id]);

  function pause() {
    if (paused.current) return;
    paused.current = true;
    clearTimers();
    if (leaving) setLeaving(false);
    remaining.current = Math.max(0, remaining.current - (Date.now() - armedAt.current));
  }

  function resume() {
    if (!paused.current) return;
    arm(Math.max(MIN_RESUME_MS, remaining.current));
  }

  const tone = item.tone ?? "ok";
  const { Icon, icon, bg } = TONE[tone];

  return (
    <div
      role={tone === "error" || tone === "warn" ? "alert" : "status"}
      data-ageval-toast=""
      data-leaving={leaving ? "" : undefined}
      onPointerEnter={pause}
      onPointerLeave={resume}
      className={cn(
        "pointer-events-auto flex max-w-sm items-start gap-2.5 rounded-[14px] px-3.5 py-2.5 shadow-[var(--viewer-shadow-pop)]",
        bg,
      )}
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", icon)} aria-hidden />
      <p className="min-w-0 text-sm text-pretty text-body">{item.message}</p>
    </div>
  );
}

export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    bindToast((input) => {
      const id = ++seed;
      setItems((prev) => [...prev.slice(-2), { ...input, id }]);
    });
    return () => bindToast(null);
  }, []);

  if (items.length === 0) return null;

  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-6 z-[60] flex flex-col items-center gap-2 px-4"
      aria-live="polite"
      aria-relevant="additions"
    >
      {items.map((item) => (
        <ToastCard
          key={item.id}
          item={item}
          onGone={(id) => setItems((prev) => prev.filter((row) => row.id !== id))}
        />
      ))}
    </div>
  );
}
