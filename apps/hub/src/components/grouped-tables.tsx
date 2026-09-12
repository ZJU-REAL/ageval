import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import {
  Table,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export type GroupedTableGroup = {
  id: string;
  head: (count: number) => ReactNode;
  count: number;
  /** Omit for a non-table body (waffle / Pareto). */
  columns?: ReactNode;
  colgroup?: ReactNode;
  body: ReactNode;
};

export function GroupedTables({
  chromeId,
  pinSlotId,
  groups,
}: {
  chromeId: string;
  pinSlotId: string;
  groups: GroupedTableGroup[];
}) {
  const idsKey = groups.map((g) => g.id).join("\n");
  const groupIds = useMemo(() => idsKey.split("\n"), [idsKey]);
  const headEls = useRef(new Map<string, HTMLElement>());
  const [pinned, setPinned] = useState<string | null>(null);
  const pinSlot =
    typeof document !== "undefined" ? document.getElementById(pinSlotId) : null;

  useEffect(() => {
    const chrome = document.getElementById(chromeId);
    const main = document.getElementById("main");
    if (!chrome || !main) return;
    const apply = () => {
      const line = chrome.getBoundingClientRect().bottom;
      let next: string | null = null;
      for (const id of groupIds) {
        const el = headEls.current.get(id);
        if (el && el.getBoundingClientRect().top <= line + 0.5) next = id;
      }
      setPinned(next);
    };
    main.addEventListener("scroll", apply, { passive: true });
    window.addEventListener("resize", apply);
    apply();
    return () => {
      main.removeEventListener("scroll", apply);
      window.removeEventListener("resize", apply);
    };
  }, [chromeId, groupIds]);

  const pinnedGroup = groups.find((g) => g.id === pinned);

  return (
    <div>
      {pinned && pinnedGroup && pinSlot
        ? createPortal(
            <PinnedGroupSwap
              id={pinned}
              count={pinnedGroup.count}
              order={groupIds}
              head={pinnedGroup.head}
            />,
            pinSlot,
          )
        : null}
      {groups.map((group, i) => (
        <GroupSection
          key={group.id}
          first={i === 0}
          pinned={pinned === group.id}
          onHead={(el) => {
            if (el) headEls.current.set(group.id, el);
            else headEls.current.delete(group.id);
          }}
          head={group.head(group.count)}
          columns={group.columns}
          colgroup={group.colgroup}
        >
          {group.body}
        </GroupSection>
      ))}
    </div>
  );
}

function PinnedGroupSwap({
  id,
  count,
  order,
  head,
}: {
  id: string;
  count: number;
  order: string[];
  head: (count: number) => ReactNode;
}) {
  const liveRef = useRef({ id, count });
  const [live, setLive] = useState({ id, count });
  const [exit, setExit] = useState<{ id: string; count: number } | null>(null);
  const [dir, setDir] = useState<1 | -1>(1);

  useEffect(() => {
    const prev = liveRef.current;
    if (prev.id === id) {
      liveRef.current = { id, count };
      setLive({ id, count });
      return;
    }
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const from = order.indexOf(prev.id);
    const to = order.indexOf(id);
    setDir(to >= from ? 1 : -1);
    if (!reduced) setExit(prev);
    liveRef.current = { id, count };
    setLive({ id, count });
    if (reduced) return;
    const t = window.setTimeout(() => setExit(null), 200);
    return () => window.clearTimeout(t);
  }, [id, count, order]);

  return (
    <div className="relative overflow-hidden">
      {exit ? (
        <div
          aria-hidden
          data-ageval-lab-out=""
          className="pointer-events-none absolute inset-x-0 top-0"
          style={{ ["--lab-dy" as string]: dir > 0 ? "-8px" : "8px" }}
        >
          {head(exit.count)}
        </div>
      ) : null}
      <div
        key={live.id}
        data-ageval-lab-in=""
        style={{ ["--lab-dy" as string]: dir > 0 ? "8px" : "-8px" }}
      >
        {head(live.count)}
      </div>
    </div>
  );
}

function GroupSection({
  first,
  head,
  pinned,
  onHead,
  columns,
  colgroup,
  children,
}: {
  first: boolean;
  head: ReactNode;
  pinned: boolean;
  onHead: (el: HTMLElement | null) => void;
  columns?: ReactNode;
  colgroup?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={first ? undefined : "mt-8"}>
      <div ref={onHead} className={pinned ? "invisible pb-2" : "pb-2"}>
        {head}
      </div>
      {columns ? (
        <div className="blob-panel">
          <Table
            wrapClassName="overflow-visible"
            className="border-separate border-spacing-0"
          >
            {colgroup}
            <TableHeader>
              <TableRow className="hover:bg-transparent">{columns}</TableRow>
            </TableHeader>
            {children}
          </Table>
        </div>
      ) : (
        children
      )}
    </section>
  );
}
