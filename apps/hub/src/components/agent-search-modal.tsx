import { useEffect, useMemo, useRef, useState } from "react";

import { AgentItem } from "@/components/agent-item";
import { SearchPalette } from "@/components/search-palette";
import {
  isBuiltinPackage,
  latestPackageByDataset,
  listPackages,
  type PackageRelease,
} from "@/lib/api";

const MAX_RESULTS = 50;

export function attachSpecFromPackage(row: PackageRelease): string {
  const id = (row.dataset_id || "").trim();
  if (!id) return "";
  if (isBuiltinPackage(row)) return id;
  const version = (row.version || "").trim();
  return version ? `${id}@${version}` : id;
}

/** Search palette over published / builtin agent packages. */
export function AgentSearchModal({
  open,
  onClose,
  onPick,
  token,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (spec: string, row: PackageRelease) => void;
  token: string | null;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [catalog, setCatalog] = useState<PackageRelease[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    listPackages(token, { packageKind: "agent" })
      .then((items) => {
        if (!cancelled) setCatalog(latestPackageByDataset(items));
      })
      .catch(() => {
        if (!cancelled) setCatalog([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, token]);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const rows = useMemo(() => {
    if (!open) return [];
    const q = query.trim().toLowerCase();
    const out = catalog.filter((row) => {
      if (!q) return true;
      const hay =
        `${row.dataset_id} ${row.display_name || ""} ${row.org_id || ""} ${row.agent_preview?.label || ""}`.toLowerCase();
      return hay.includes(q);
    });
    return out.slice(0, MAX_RESULTS);
  }, [open, query, catalog]);

  const current = Math.min(active, Math.max(0, rows.length - 1));

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
        const spec = attachSpecFromPackage(row);
        if (spec) onPick(spec, row);
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, rows, active, onClose, onPick]);

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-index="${current}"]`,
    );
    el?.scrollIntoView({ block: "nearest" });
  }, [current]);

  return (
    <SearchPalette
      open={open}
      onClose={onClose}
      label="Search agents"
      query={query}
      onQuery={(next) => {
        setQuery(next);
        setActive(0);
      }}
      placeholder="Search agents…"
      countLabel={
        open
          ? `${rows.length} result${rows.length === 1 ? "" : "s"}`
          : undefined
      }
      inputRef={inputRef}
      listRef={listRef}
      empty={
        rows.length === 0 ? (
          <p className="px-3 py-6 text-sm text-mute">No agents match</p>
        ) : null
      }
    >
      {rows.map((row, i) => (
        <AgentItem
          key={row.dataset_id}
          row={row}
          selected={i === current}
          index={i}
          onClick={() => {
            const spec = attachSpecFromPackage(row);
            if (spec) onPick(spec, row);
            onClose();
          }}
          onMouseEnter={() => setActive(i)}
        />
      ))}
    </SearchPalette>
  );
}
