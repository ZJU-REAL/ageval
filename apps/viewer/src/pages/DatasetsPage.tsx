import { FolderOpen, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { EmptyState } from "@ageval/shared/components/empty-state";
import { Shell } from "@/components/layout";
import { PageHead } from "@/components/page-head";
import { Input } from "@ageval/shared/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@ageval/shared/components/ui/table";
import { datasetPath } from "@/lib/routes";
import { useReadySession } from "@/lib/session";

export function DatasetsPage() {
  const session = useReadySession();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return session.datasets;
    return session.datasets.filter((row) => {
      const hay = [row.label, row.key, row.description || ""].join(" ").toLowerCase();
      return hay.includes(query);
    });
  }, [q, session.datasets]);

  return (
    <Shell>
      <div className="flex flex-1 flex-col gap-4">
        <PageHead
          title="Datasets"
          sub={
            session.datasets.length === 1
              ? "This viewer opened one package."
              : "Packages in the directory you opened."
          }
        />
        <div className="relative min-w-0">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-mute" />
          <Input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="Search datasets"
            className="h-10 pl-9 focus-visible:border-hairline"
            aria-label="Search datasets"
          />
        </div>
        {session.datasets.length === 0 ? (
          <EmptyState
            icon={FolderOpen}
            title="No datasets"
            caption="Pass a dataset root, or a directory whose children are datasets."
          />
        ) : rows.length === 0 ? (
          <EmptyState icon={FolderOpen} title="No matches" caption="Try another name." />
        ) : (
          <div className="blob-panel overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Package</TableHead>
                  <TableHead>Directory</TableHead>
                  <TableHead>Tasks</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
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
                    <TableCell className="text-ink">{row.label}</TableCell>
                    <TableCell className="text-body">{row.key}</TableCell>
                    <TableCell className="tabular">{row.task_count}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </Shell>
  );
}
