import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { EmptyState, LoadingState } from "@ageval/shared/components/empty-state";
import { FileSplitPanel } from "@ageval/shared/components/trial/file-split-panel";
import { FileText } from "lucide-react";
import { Shell } from "@/components/layout";
import { PageHead } from "@/components/page-head";
import {
  fetchAgent,
  fetchAgentFile,
  fetchAgentTree,
  fetchDataset,
  fetchDatasetFile,
  fetchDatasetTree,
  fetchPlugin,
  fetchPluginFile,
  fetchPluginTree,
  type PackageDetail,
  type PackageFile,
  type TreeEntry,
} from "@/lib/api";

type Loader = {
  detail: () => Promise<PackageDetail>;
  tree: () => Promise<{ entries: TreeEntry[] }>;
  file: (path: string) => Promise<PackageFile>;
};

function preferPath(detail: PackageDetail | null, entries: TreeEntry[]): string | null {
  const names = [detail?.readme, detail?.manifest, detail?.profiles].filter(
    (item): item is string => Boolean(item),
  );
  for (const name of names) {
    if (entries.some((entry) => entry.path === name && entry.type !== "dir")) return name;
  }
  const first = entries.find((entry) => entry.type !== "dir");
  return first?.path || null;
}

function PackageBrowser({ loader }: { loader: Loader }) {
  const [detail, setDetail] = useState<PackageDetail | null>(null);
  const [tree, setTree] = useState<TreeEntry[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [treeLoading, setTreeLoading] = useState(true);
  const [fileLoading, setFileLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setTreeLoading(true);
    setSelected(null);
    setContent(null);
    Promise.all([loader.detail(), loader.tree()])
      .then(([pkg, files]) => {
        if (cancelled) return;
        setDetail(pkg);
        setTree(files.entries || []);
        setSelected(preferPath(pkg, files.entries || []));
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
          setTreeLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [loader]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setFileLoading(true);
    loader
      .file(selected)
      .then((body) => {
        if (cancelled) return;
        setContent(body.content ?? null);
        setNote(body.note || (body.encoding === "redacted" ? "Content hidden." : null));
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setContent(null);
          setNote(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) setFileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [loader, selected]);

  const sub =
    detail?.source === "builtin"
      ? "Built in"
      : detail?.source === "installed"
        ? "Installed"
        : detail?.description || undefined;

  return (
    <Shell>
      <div className="flex flex-1 flex-col gap-4">
        <PageHead title={detail?.label || "Package"} sub={sub} />
        {loading ? (
          <LoadingState label="Loading package" />
        ) : error ? (
          <EmptyState icon={FileText} title="Could not open package" caption={error} />
        ) : (
          <div className="blob-panel overflow-hidden">
            <FileSplitPanel
              tree={tree}
              treeLoading={treeLoading}
              selectedPath={selected}
              onSelect={setSelected}
              fileContent={content}
              fileLoading={fileLoading}
              fileNote={note}
            />
          </div>
        )}
      </div>
    </Shell>
  );
}

export function DatasetPackagePage() {
  const { datasetKey = "" } = useParams();
  const loader = useMemo<Loader>(
    () => ({
      detail: () => fetchDataset(datasetKey),
      tree: () => fetchDatasetTree(datasetKey),
      file: (path) => fetchDatasetFile(datasetKey, path),
    }),
    [datasetKey],
  );
  return <PackageBrowser loader={loader} />;
}

export function CatalogPackagePage({ kind }: { kind: "plugin" | "agent" }) {
  const { source = "", packageId = "", version = "" } = useParams();
  const loader = useMemo<Loader>(() => {
    if (kind === "plugin") {
      return {
        detail: () => fetchPlugin(source, packageId, version),
        tree: () => fetchPluginTree(source, packageId, version),
        file: (path) => fetchPluginFile(source, packageId, version, path),
      };
    }
    return {
      detail: () => fetchAgent(source, packageId, version),
      tree: () => fetchAgentTree(source, packageId, version),
      file: (path) => fetchAgentFile(source, packageId, version, path),
    };
  }, [kind, source, packageId, version]);
  return <PackageBrowser loader={loader} />;
}
