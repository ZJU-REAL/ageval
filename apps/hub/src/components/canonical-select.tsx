import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, Search } from "lucide-react";

import { ModelItem } from "@/components/model-item";
import { loadModelPin } from "@/lib/model-pin";
import { cn } from "@/lib/utils";

const NONE = "";
const MAX_RESULTS = 50;

type Row = {
  id: string;
  kind: "none" | "model" | "custom";
};

function haystack(id: string, name: string, lab: string, family: string): string {
  return `${id} ${name} ${lab} ${family}`.toLowerCase();
}

function PickRow({
  selected,
  active,
  onClick,
  onMouseEnter,
  children,
  index,
}: {
  selected: boolean;
  active: boolean;
  onClick: () => void;
  onMouseEnter: () => void;
  children: ReactNode;
  index: number;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      data-index={index}
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      className={cn(
        "flex w-full items-center gap-2 rounded-[10px] px-3 py-2 text-left text-sm",
        selected || active ? "bg-canvas-soft-2" : "hover:bg-canvas-soft",
      )}
    >
      {children}
    </button>
  );
}

export function CanonicalSelect({
  value,
  onChange,
  hits,
  allowEmpty,
  disabled,
  includePin,
  allowCustom = true,
  variant = "dropdown",
  label = "Model",
}: {
  value: string;
  onChange: (next: string) => void;
  hits: string[];
  allowEmpty?: boolean;
  disabled?: boolean;
  includePin?: boolean;
  /** Type a name / id that is not in the pin. */
  allowCustom?: boolean;
  /** `panel` = inline search + list (Share). `dropdown` = trigger (Inbox). */
  variant?: "dropdown" | "panel";
  label?: string;
}) {
  const pin = loadModelPin();
  const chosen = value.trim();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [pos, setPos] = useState<{
    top: number;
    left: number;
    width: number;
    maxH: number;
  } | null>(null);

  const catalog = useMemo(() => {
    const hitSet = new Set(hits.filter(Boolean));
    const ids: string[] = [];
    const seen = new Set<string>();
    const push = (id: string) => {
      const text = id.trim();
      if (!text || seen.has(text)) return;
      seen.add(text);
      ids.push(text);
    };
    for (const id of hits) push(id);
    if (includePin) {
      for (const id of Object.keys(pin.models).sort()) {
        if (!hitSet.has(id)) push(id);
      }
    }
    if (chosen && !seen.has(chosen) && chosen !== NONE) push(chosen);
    return ids;
  }, [hits, includePin, pin.models, chosen]);

  const { rows, hidden } = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matched: string[] = [];
    for (const id of catalog) {
      const info = pin.models[id];
      const hay = haystack(
        id,
        info?.name || "",
        info?.lab || "",
        info?.family || "",
      );
      if (q && !hay.includes(q)) continue;
      matched.push(id);
    }
    const chosenIdx = chosen ? matched.indexOf(chosen) : -1;
    if (chosenIdx >= MAX_RESULTS) {
      matched.splice(chosenIdx, 1);
      matched.unshift(chosen);
    }
    const shown = matched.slice(0, MAX_RESULTS);
    const out: Row[] = [];
    if (allowEmpty) out.push({ id: NONE, kind: "none" });
    for (const id of shown) out.push({ id, kind: "model" });
    const typed = query.trim();
    if (
      allowCustom &&
      typed &&
      !catalog.some((id) => id.toLowerCase() === typed.toLowerCase()) &&
      !Object.values(pin.models).some(
        (info) => (info?.name || "").toLowerCase() === typed.toLowerCase(),
      )
    ) {
      out.push({ id: typed, kind: "custom" });
    }
    return { rows: out, hidden: matched.length - shown.length };
  }, [allowCustom, allowEmpty, catalog, chosen, pin.models, query]);

  const current = Math.min(active, Math.max(0, rows.length - 1));
  const selectedLabel =
    chosen && pin.models[chosen]?.name
      ? pin.models[chosen].name
      : chosen || (allowEmpty ? "None" : "Model");

  function pick(id: string) {
    onChange(id);
    setQuery("");
    setOpen(false);
  }

  function place() {
    const el = triggerRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const width = Math.min(Math.max(r.width, 360), window.innerWidth - 16);
    const maxH = Math.min(320, window.innerHeight - 24);
    let top = r.bottom + 4;
    if (top + 160 > window.innerHeight) {
      top = Math.max(8, r.top - 4 - maxH);
    }
    const left = Math.min(Math.max(8, r.left), window.innerWidth - width - 8);
    setPos({ top, left, width, maxH });
  }

  const listOpen = variant === "panel" || open;

  useEffect(() => {
    if (variant !== "dropdown" || !open) return;
    place();
    const id = window.requestAnimationFrame(() => inputRef.current?.focus());
    function onDoc(event: MouseEvent) {
      const node = event.target as Node;
      if (triggerRef.current?.contains(node) || panelRef.current?.contains(node)) {
        return;
      }
      setOpen(false);
    }
    function onReposition() {
      place();
    }
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("resize", onReposition);
    window.addEventListener("scroll", onReposition, true);
    return () => {
      window.cancelAnimationFrame(id);
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("resize", onReposition);
      window.removeEventListener("scroll", onReposition, true);
    };
  }, [open, variant]);

  useEffect(() => {
    if (!listOpen) return;
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-index="${current}"]`,
    );
    el?.scrollIntoView({ block: "nearest" });
  }, [current, listOpen]);

  function onSearchKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((a) => Math.min(a + 1, rows.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const row = rows[current];
      if (row) pick(row.id);
    } else if (event.key === "Escape" && variant === "dropdown") {
      event.preventDefault();
      setOpen(false);
    }
  }

  const list = (
    <>
      <div className="flex shrink-0 items-center gap-2 border-b border-hairline px-3">
        <Search className="h-3.5 w-3.5 shrink-0 text-mute" aria-hidden />
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={onSearchKey}
          placeholder="Search or type a name…"
          aria-label={label}
          autoComplete="off"
          spellCheck={false}
          disabled={disabled}
          className="h-10 min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-mute"
        />
      </div>
      <div
        ref={listRef}
        role="listbox"
        aria-label={label}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-1"
        onWheel={(event) => event.stopPropagation()}
      >
        {rows.map((row, i) => {
          const selected = (row.id || "") === chosen;
          if (row.kind === "none") {
            return (
              <PickRow
                key="none"
                index={i}
                selected={selected}
                active={i === current}
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(NONE)}
              >
                <span className="text-mute">None</span>
                {selected ? (
                  <Check className="ml-auto h-3.5 w-3.5 text-link" aria-hidden />
                ) : null}
              </PickRow>
            );
          }
          if (row.kind === "custom") {
            return (
              <PickRow
                key={`custom:${row.id}`}
                index={i}
                selected={selected}
                active={i === current}
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(row.id)}
              >
                <span className="min-w-0">
                  Use{" "}
                  <span className="font-medium text-ink">{row.id}</span>
                </span>
              </PickRow>
            );
          }
          return (
            <ModelItem
              key={row.id}
              canonical={pin.models[row.id] ? row.id : undefined}
              overlay={row.id}
              selected={selected || i === current}
              meta="compact"
              role="option"
              aria-selected={selected}
              data-index={i}
              className="py-1.5"
              onMouseEnter={() => setActive(i)}
              onClick={() => pick(row.id)}
            />
          );
        })}
        {rows.length === 0 ? (
          <p className="px-3 py-6 text-sm text-mute">No models match</p>
        ) : null}
        {hidden > 0 ? (
          <p className="px-3 py-2 text-xs text-mute">
            {hidden} more. Type to narrow.
          </p>
        ) : null}
      </div>
    </>
  );

  if (variant === "panel") {
    return (
      <div
        className={cn(
          "flex max-h-[min(24rem,50vh)] flex-col overflow-hidden rounded-[12px] border border-hairline bg-canvas",
          disabled && "opacity-50",
        )}
      >
        {list}
      </div>
    );
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => {
          if (disabled) return;
          setOpen((next) => {
            const going = !next;
            if (going) {
              setQuery("");
              setActive(0);
            }
            return going;
          });
        }}
        className={cn(
          "group flex h-8 min-w-[12rem] max-w-[20rem] shrink-0 items-center justify-between gap-2 rounded-[8px] border border-hairline bg-canvas px-3 text-xs text-ink squish",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-link/70 disabled:cursor-not-allowed disabled:opacity-50",
        )}
      >
        <span className="min-w-0 truncate">{selectedLabel}</span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-mute motion-safe:transition-transform motion-safe:duration-200 motion-safe:ease-smooth",
            open && "rotate-180",
          )}
        />
      </button>
      {open && pos && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={panelRef}
              data-ageval-pop=""
              role="dialog"
              aria-label={label}
              className="fixed z-[80] flex flex-col overflow-hidden rounded-[12px] border border-hairline bg-canvas shadow-[var(--viewer-shadow-pop)]"
              style={{
                top: pos.top,
                left: pos.left,
                width: pos.width,
                maxHeight: pos.maxH,
              }}
              onClick={(event) => event.stopPropagation()}
            >
              {list}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
