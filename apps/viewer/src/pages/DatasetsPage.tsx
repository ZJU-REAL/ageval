import { FolderOpen, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { EmptyState } from "@ageval/shared/components/empty-state";
import { Shell } from "@/components/layout";
import {
  STICKY_HEAD_UNDER_GROUP,
  StickyChrome,
} from "@/components/sticky-chrome";
import { useDocumentTitle } from "@/lib/document-title";
import { Input } from "@ageval/shared/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@ageval/shared/components/ui/table";
import type { DatasetItem } from "@/lib/api";
import { datasetPath } from "@/lib/routes";
import { useReadySession } from "@/lib/session";

function splitDatasetId(id: string): { org: string | null; name: string } {
  const slash = id.indexOf("/");
  if (slash <= 0 || slash === id.length - 1) return { org: null, name: id };
  return { org: id.slice(0, slash), name: id.slice(slash + 1) };
}

export function DatasetsPage() {
  const session = useReadySession();
  const navigate = useNavigate();
  useDocumentTitle("Datasets");
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return session.datasets;
    return session.datasets.filter((row) => {
      const { org, name } = splitDatasetId(row.dataset_id);
      const hay = [row.label, row.key, org, name, row.description || ""]
        .join(" ")
        .toLowerCase();
      return hay.includes(query);
    });
  }, [q, session.datasets]);
  const groups = useMemo(() => groupByOrg(rows), [rows]);

  return (
    <Shell>
      <div className="flex flex-1 flex-col">
        <StickyChrome>
          <div className="relative h-10 min-w-0 max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-mute" />
            <Input
              value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder="Search datasets"
              className="h-10 pl-9 focus-visible:border-hairline"
              aria-label="Search datasets"
            />
          </div>
        </StickyChrome>
        {session.datasets.length === 0 ? (
          <EmptyState
            icon={FolderOpen}
            title="No datasets"
            caption="Pass a dataset root, or a directory whose children are datasets."
          />
        ) : rows.length === 0 ? (
          <EmptyState icon={FolderOpen} title="No matches" caption="Try another name." />
        ) : (
          <div className="flex flex-col gap-8">
            {groups.map((group) => (
              <section key={group.org}>
                <h2 className="sticky top-[var(--viewer-stick-top,0px)] z-[15] flex h-9 items-center gap-2 bg-canvas text-base font-semibold text-ink">
                  <span className="min-w-0 truncate">{group.org}</span>
                  <span className="ml-auto text-xs font-normal text-mute tabular-nums">
                    {group.rows.length}
                  </span>
                </h2>
                <div className="blob-panel">
                  <Table
                    wrapClassName="overflow-visible"
                    className="border-separate border-spacing-0"
                  >
                    <TableHeader className={STICKY_HEAD_UNDER_GROUP}>
                      <TableRow className="hover:bg-transparent">
                        <TableHead>Package</TableHead>
                        <TableHead>Directory</TableHead>
                        <TableHead>Tasks</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {group.rows.map((row) => {
                        const { name } = splitDatasetId(row.dataset_id);
                        return (
                          <TableRow
                            key={row.key}
                            className="cursor-pointer"
                            tabIndex={0}
                            role="link"
                            onClick={() => navigate(datasetPath(row.key))}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") navigate(datasetPath(row.key));
                            }}
                          >
                            <TableCell className="text-ink">
                              {name}@{row.version}
                            </TableCell>
                            <TableCell className="text-body">{row.key}</TableCell>
                            <TableCell className="tabular">{row.task_count}</TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </Shell>
  );
}

function groupByOrg(rows: DatasetItem[]): { org: string; rows: DatasetItem[] }[] {
  const byOrg = new Map<string, DatasetItem[]>();
  for (const row of rows) {
    const org = splitDatasetId(row.dataset_id).org || row.dataset_id;
    const list = byOrg.get(org) ?? [];
    list.push(row);
    byOrg.set(org, list);
  }
  return [...byOrg.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([org, items]) => ({
      org,
      rows: [...items].sort((a, b) => a.dataset_id.localeCompare(b.dataset_id)),
    }));
}
