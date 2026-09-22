import { Bot, Puzzle, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { EmptyState, LoadingState } from "@ageval/shared/components/empty-state";
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
import { fetchAgents, fetchPlugins, type CatalogItem } from "@/lib/api";
import { catalogPath } from "@/lib/routes";

function sourceLabel(source: string): string {
  if (source === "builtin") return "Built in";
  if (source === "installed") return "Installed";
  return source;
}

function CatalogTable({
  title,
  kind,
  load,
}: {
  title: string;
  kind: "plugins" | "agents";
  load: () => Promise<{ items: CatalogItem[] }>;
}) {
  const navigate = useNavigate();
  const [rows, setRows] = useState<CatalogItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const icon = kind === "plugins" ? Puzzle : Bot;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    load()
      .then((data) => {
        if (cancelled) return;
        setRows(data.items || []);
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return rows;
    return rows.filter((row) => {
      const hay = [row.label, row.id, row.version, sourceLabel(row.source)]
        .join(" ")
        .toLowerCase();
      return hay.includes(query);
    });
  }, [q, rows]);

  return (
    <Shell>
      <div className="flex flex-1 flex-col gap-4">
        <PageHead title={title} sub="Read-only. Built-in rows ship with this CLI." />
        <div className="relative min-w-0">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-mute" />
          <Input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder={`Search ${title.toLowerCase()}`}
            className="h-10 pl-9 focus-visible:border-hairline"
            aria-label={`Search ${title.toLowerCase()}`}
          />
        </div>
        {loading ? (
          <LoadingState label={`Loading ${title.toLowerCase()}`} />
        ) : error ? (
          <EmptyState icon={icon} title={`Could not load ${title.toLowerCase()}`} caption={error} />
        ) : filtered.length === 0 ? (
          <EmptyState icon={icon} title="No matches" caption="Try another name." />
        ) : (
          <div className="blob-panel overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Name</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Source</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((row) => (
                  <TableRow
                    key={`${row.source}:${row.id}:${row.version}`}
                    className="cursor-pointer"
                    tabIndex={0}
                    role="link"
                    onClick={() => navigate(catalogPath(kind, row.source, row.id, row.version))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        navigate(catalogPath(kind, row.source, row.id, row.version));
                      }
                    }}
                  >
                    <TableCell className="text-ink">{row.label || row.id}</TableCell>
                    <TableCell className="text-body">{row.version}</TableCell>
                    <TableCell className="text-body">{sourceLabel(row.source)}</TableCell>
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

export function PluginsPage() {
  return <CatalogTable title="Plugins" kind="plugins" load={fetchPlugins} />;
}

export function AgentsPage() {
  return <CatalogTable title="Agents" kind="agents" load={fetchAgents} />;
}
