import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ModelItem } from "@/components/model-item";
import { SearchPalette } from "@/components/search-palette";
import { encodeDatasetId } from "@/lib/api";
import { loadModelPin } from "@ageval/shared/lib/model-pin";

const MAX_RESULTS = 50;

/** Cmd/Ctrl+F palette over the model pin. `onPick` selects instead of navigating. */
export function ModelSearchModal({
  open,
  onClose,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  onPick?: (canonical: string) => void;
}) {
  const navigate = useNavigate();
  const pin = loadModelPin();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const rows = useMemo(() => {
    if (!open) return [];
    const q = query.trim().toLowerCase();
    const out: {
      canonical: string;
      info: (typeof pin.models)[string];
    }[] = [];
    for (const [canonical, info] of Object.entries(pin.models)) {
      const hay =
        `${canonical} ${info.name} ${info.family} ${info.lab} ${info.description}`.toLowerCase();
      if (q && !hay.includes(q)) continue;
      out.push({ canonical, info });
    }
    return out.slice(0, MAX_RESULTS);
  }, [open, query, pin]);

  const current = Math.min(active, Math.max(0, rows.length - 1));

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive((a) => Math.min(a + 1, rows.length - 1));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive((a) => Math.max(a - 1, 0));
      } else if (event.key === "Enter") {
        const row = rows[Math.min(active, Math.max(0, rows.length - 1))];
        if (!row) return;
        event.preventDefault();
        if (onPick) {
          onPick(row.canonical);
          onClose();
        } else {
          onClose();
          navigate(`/models/${encodeDatasetId(row.canonical)}`);
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, rows, active, onClose, navigate, onPick]);

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-index="${current}"]`,
    );
    el?.scrollIntoView({ block: "nearest" });
  }, [current]);

  function choose(canonical: string) {
    if (onPick) {
      onPick(canonical);
      onClose();
      return;
    }
    onClose();
    navigate(`/models/${encodeDatasetId(canonical)}`);
  }

  return (
    <SearchPalette
      open={open}
      onClose={onClose}
      label="Search models"
      query={query}
      onQuery={(next) => {
        setQuery(next);
        setActive(0);
      }}
      placeholder="Search models…"
      countLabel={
        open
          ? `${rows.length} result${rows.length === 1 ? "" : "s"}`
          : undefined
      }
      inputRef={inputRef}
      listRef={listRef}
      empty={
        rows.length === 0 ? (
          <p className="px-3 py-6 text-sm text-mute">No models match</p>
        ) : null
      }
    >
      {rows.map((row, i) => (
        <ModelItem
          key={row.canonical}
          canonical={row.canonical}
          overlay={row.canonical}
          selected={i === current}
          title={row.info.description}
          role="option"
          aria-selected={i === current}
          data-index={i}
          onClick={() => choose(row.canonical)}
          onMouseEnter={() => setActive(i)}
        />
      ))}
    </SearchPalette>
  );
}
