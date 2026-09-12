import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  GroupedTables,
  type GroupedTableGroup,
} from "@/components/grouped-tables";
import { LabGroupHead } from "@/components/lab-group-head";
import { ModalityMarks } from "@/components/modality-mark";
import {
  SortableHead,
  compareValues,
  nextSort,
  type SortDir,
} from "@/components/sortable-head";
import {
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from "@/components/ui/table";
import { encodeDatasetId } from "@/lib/api";
import { INTERNAL_LINK_CLASS } from "@/lib/links";
import {
  compactTokens,
  directoryPrice,
  fmtPrice,
  loadModelPin,
  modalityBadges,
  modelModalities,
} from "@/lib/model-pin";

export type ModelLabRow = {
  overlay: string;
  canonical: string | null;
};

const CELL_MUTE = "whitespace-nowrap text-sm text-mute tabular-nums";
const CELL_INK = "whitespace-nowrap text-sm text-ink tabular-nums";

/** Shared across every lab table so columns line up. */
const COLS = (
  <colgroup>
    <col className="w-[44%]" />
    <col className="w-[14%]" />
    <col className="w-[12%]" />
    <col className="w-[12%]" />
    <col className="w-[18%]" />
  </colgroup>
);

const STICKY_TH = "sticky z-10 bg-canvas-soft top-[var(--models-stick-top,0px)]";

export function ModelLabTables({ rows }: { rows: ModelLabRow[] }) {
  const pin = loadModelPin();
  const [sortKey, setSortKey] = useState<string | null>("released");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function onSort(key: string) {
    const next = nextSort(sortKey, sortDir, key);
    setSortKey(next.dir ? next.key : null);
    setSortDir(next.dir);
  }

  function head(key: string, label: string) {
    return (
      <SortableHead
        label={label}
        active={sortKey === key}
        dir={sortKey === key ? sortDir : null}
        onClick={() => onSort(key)}
      />
    );
  }

  const labs = useMemo(() => {
    const map = new Map<string, ModelLabRow[]>();
    for (const row of rows) {
      const lab = row.canonical ? (pin.models[row.canonical]?.lab ?? "") : "";
      const list = map.get(lab) ?? [];
      list.push(row);
      map.set(lab, list);
    }
    return [...map.entries()].sort(([a], [b]) =>
      (pin.labs[a]?.name || a).localeCompare(pin.labs[b]?.name || b),
    );
  }, [rows, pin]);

  const infoOf = (row: ModelLabRow) =>
    row.canonical ? pin.models[row.canonical] : undefined;

  function fallback(a: ModelLabRow, b: ModelLabRow): number {
    const ai = infoOf(a);
    const bi = infoOf(b);
    const cmp = compareValues(ai?.release_date || null, bi?.release_date || null, "desc");
    if (cmp !== 0) return cmp;
    return (ai?.name || a.overlay).localeCompare(bi?.name || b.overlay);
  }

  function sortValue(row: ModelLabRow, key: string): string | number | null {
    const info = infoOf(row);
    if (!info) return null;
    if (key === "model") return info.name || row.overlay;
    if (key === "released") return info.release_date || null;
    if (key === "context") return info.context;
    if (key === "output") return info.output;
    if (key === "price") {
      const price = row.canonical ? directoryPrice(row.canonical, row.canonical, pin) : null;
      return price ? price.input : null;
    }
    return null;
  }

  function sortItems(items: ModelLabRow[]): ModelLabRow[] {
    const sorted = [...items];
    if (sortKey && sortDir) {
      sorted.sort((a, b) => {
        const cmp = compareValues(sortValue(a, sortKey), sortValue(b, sortKey), sortDir);
        return cmp !== 0 ? cmp : fallback(a, b);
      });
    } else {
      sorted.sort(fallback);
    }
    return sorted;
  }

  const groups: GroupedTableGroup[] = labs.map(([lab, items]) => {
    const sorted = sortItems(items);
    const id = lab || "unmatched";
    const name = pin.labs[lab]?.name || lab || "Unmatched";
    return {
      id,
      count: sorted.length,
      head: (count: number) => <LabGroupHead lab={lab} name={name} count={count} />,
      columns: (
        <>
          <TableHead className={STICKY_TH}>{head("model", "Model")}</TableHead>
          <TableHead className={STICKY_TH}>{head("released", "Released")}</TableHead>
          <TableHead className={STICKY_TH}>{head("context", "Context")}</TableHead>
          <TableHead className={STICKY_TH}>{head("output", "Output")}</TableHead>
          <TableHead className={STICKY_TH}>{head("price", "Price / MTok")}</TableHead>
        </>
      ),
      colgroup: COLS,
      body: (
        <TableBody>
          {sorted.map((row) => {
            const info = infoOf(row);
            const badges = info ? modalityBadges(modelModalities(info)) : [];
            const price = row.canonical
              ? directoryPrice(row.canonical, row.canonical, pin)
              : null;
            return (
              <TableRow key={row.overlay}>
                <TableCell className="whitespace-normal overflow-visible">
                  <span className="flex min-w-0 flex-col items-start gap-0.5">
                    <span className="flex min-w-0 flex-wrap items-center gap-2">
                      {row.canonical ? (
                        <Link
                          to={`/models/${encodeDatasetId(row.canonical)}`}
                          className={`shrink-0 font-medium ${INTERNAL_LINK_CLASS}`}
                        >
                          {info?.name || row.overlay}
                        </Link>
                      ) : (
                        <span className="shrink-0 font-medium text-ink">
                          {row.overlay}
                        </span>
                      )}
                      {badges.length ? <ModalityMarks kinds={badges} /> : null}
                    </span>
                    <span className="max-w-full truncate text-[13px] text-mute">
                      {row.canonical || row.overlay}
                    </span>
                  </span>
                </TableCell>
                <TableCell className={CELL_MUTE}>
                  {info?.release_date || "—"}
                </TableCell>
                <TableCell
                  className={CELL_INK}
                  title={
                    info?.context != null
                      ? `${info.context.toLocaleString()} tok`
                      : undefined
                  }
                >
                  {info?.context != null ? compactTokens(info.context) : "—"}
                </TableCell>
                <TableCell
                  className={CELL_MUTE}
                  title={
                    info?.output != null
                      ? `${info.output.toLocaleString()} tok`
                      : undefined
                  }
                >
                  {info?.output != null ? compactTokens(info.output) : "—"}
                </TableCell>
                <TableCell
                  className={CELL_MUTE}
                  title={price ? `pin snapshot · ${price.provider}` : undefined}
                >
                  {price
                    ? `$${fmtPrice(price.input)} / $${fmtPrice(price.output)}`
                    : "—"}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      ),
    };
  });

  return (
    <GroupedTables chromeId="models-chrome" pinSlotId="models-lab-pin" groups={groups} />
  );
}
