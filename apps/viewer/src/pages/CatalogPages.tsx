import { Bot, Puzzle, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { EmptyState, LoadingState } from "@ageval/shared/components/empty-state";
import { Shell } from "@/components/layout";
import { STICKY_HEAD, StickyChrome } from "@/components/sticky-chrome";
import { useDocumentTitle } from "@/lib/document-title";
import { Input } from "@ageval/shared/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ageval/shared/components/ui/select";
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

function plainDescription(text: string | null | undefined): string {
  return (text || "").replace(/\s+/g, " ").trim();
}

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
  const [source, setSource] = useState("all");
  const icon = kind === "plugins" ? Puzzle : Bot;
  useDocumentTitle(title);

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
    return rows.filter((row) => {
      if (source !== "all" && row.source !== source) return false;
      if (!query) return true;
      const hay = [row.label, row.id, row.description, sourceLabel(row.source)]
        .join(" ")
        .toLowerCase();
      return hay.includes(query);
    });
  }, [q, rows, source]);

  return (
    <Shell>
      <div className="flex flex-1 flex-col">
        <StickyChrome>
          <div className="flex h-10 flex-wrap items-center gap-2">
            <div className="relative h-10 min-w-0 w-full max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-mute" />
              <Input
                value={q}
                onChange={(event) => setQ(event.target.value)}
                placeholder={`Search ${title.toLowerCase()}`}
                className="h-10 pl-9 focus-visible:border-hairline"
                aria-label={`Search ${title.toLowerCase()}`}
              />
            </div>
            <Select value={source} onValueChange={setSource}>
              <SelectTrigger aria-label="Filter source" className="h-10">
                <SelectValue placeholder="All sources" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All sources</SelectItem>
                <SelectItem value="builtin">Built in</SelectItem>
                <SelectItem value="installed">Installed</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </StickyChrome>
        {loading ? (
          <LoadingState label={`Loading ${title.toLowerCase()}`} />
        ) : error ? (
          <EmptyState icon={icon} title={`Could not load ${title.toLowerCase()}`} caption={error} />
        ) : filtered.length === 0 ? (
          <EmptyState icon={icon} title="No matches" caption="Try another name." />
        ) : (
          <div className="blob-panel">
            <Table wrapClassName="overflow-visible" className="border-separate border-spacing-0">
              <TableHeader className={STICKY_HEAD}>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Name</TableHead>
                  <TableHead>Description</TableHead>
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
                    <TableCell className="max-w-[36rem] text-sm text-body">
                      <span className="line-clamp-2" title={plainDescription(row.description) || undefined}>
                        {plainDescription(row.description) || "-"}
                      </span>
                    </TableCell>
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
