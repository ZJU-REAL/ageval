import { useEffect, useMemo, useState, type ReactNode } from "react";

import { FileSplitPanel } from "@/components/file-split-panel";
import {
  decodeFileContent,
  getPackageFile,
  listPackageFiles,
  resolveAgentPackageDigest,
  splitJobOverlaySources,
  RegistryHttpError,
  type FileItem,
  type SuiteRow,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import { PillTabs } from "@ageval/shared/components/ui/pill-tabs";
import { buildNestedTree, pathMatchesPrefixes } from "@ageval/shared/lib/file-tree";

/** Package-file preview limited to a binding's declared ``overlays:`` prefixes. */
export function OverlayFilePanel({
  datasetId,
  packageDigest,
  prefixes,
  headerEnd,
}: {
  datasetId: string;
  packageDigest: string;
  prefixes: string[];
  headerEnd?: ReactNode;
}) {
  const token = getToken();
  const overlayKey = prefixes.join("\n");
  const prefixList = useMemo(
    () => overlayKey.split("\n").filter(Boolean),
    [overlayKey],
  );
  const [fileItems, setFileItems] = useState<FileItem[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [fileNote, setFileNote] = useState<string | null>(null);

  const canPreview = Boolean(datasetId && packageDigest && overlayKey);

  useEffect(() => {
    if (!canPreview) {
      setFileItems([]);
      setSelectedPath(null);
      setFileContent(null);
      setFileNote(null);
      setTreeLoading(false);
      return;
    }
    let cancelled = false;
    setTreeLoading(true);
    setFileNote(null);
    listPackageFiles(datasetId, packageDigest, token)
      .then((files) => {
        if (cancelled) return;
        const matched = files.items.filter(
          (item) => item.type !== "dir" && pathMatchesPrefixes(item.path, prefixList),
        );
        setFileItems(matched);
        const prefer =
          prefixList
            .map((prefix) =>
              matched.find(
                (item) => item.path === prefix || item.path.startsWith(`${prefix}/`),
              ),
            )
            .find(Boolean) || matched[0];
        setSelectedPath(prefer?.path ?? null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setFileItems([]);
        setSelectedPath(null);
        if (err instanceof RegistryHttpError) {
          setFileNote(`${err.code}: ${err.message}`);
        } else {
          setFileNote(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setTreeLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [canPreview, datasetId, overlayKey, packageDigest, prefixList, token]);

  const tree = useMemo(
    () => (canPreview ? buildNestedTree(fileItems, "overlays") : []),
    [canPreview, fileItems],
  );

  useEffect(() => {
    if (!canPreview || !selectedPath) {
      setFileContent(null);
      return;
    }
    let cancelled = false;
    setFileLoading(true);
    getPackageFile(datasetId, packageDigest, selectedPath, token)
      .then((file) => {
        if (cancelled) return;
        try {
          setFileContent(decodeFileContent(file));
          setFileNote(null);
        } catch {
          setFileContent(null);
          setFileNote("Could not decode file content.");
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setFileContent(null);
        if (err instanceof RegistryHttpError) {
          setFileNote(`${err.code}: ${err.message}`);
        } else {
          setFileNote(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setFileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [canPreview, datasetId, packageDigest, selectedPath, token]);

  if (!canPreview) return null;

  return (
    <FileSplitPanel
      tree={tree}
      treeLoading={treeLoading}
      selectedPath={selectedPath}
      onSelect={setSelectedPath}
      fileContent={fileContent}
      fileLoading={fileLoading}
      fileNote={fileNote}
      rootPrefix="overlays"
      headerEnd={headerEnd}
    />
  );
}

type OverlaySource = {
  key: string;
  label: string;
  packageId: string;
  digest: string;
  prefixes: string[];
};

/** Dataset overlays (no agent_ref) and Agent-package overlays, tabbed like Local/Shared. */
export function JobOverlayPreview({
  overlay,
  datasetId,
  datasetDigest,
}: {
  overlay: SuiteRow["job_overlay"] | null | undefined;
  datasetId: string;
  datasetDigest: string;
}) {
  const token = getToken();
  const split = useMemo(() => splitJobOverlaySources(overlay), [overlay]);
  const [agentDigests, setAgentDigests] = useState<Record<string, string>>({});
  const [scope, setScope] = useState<string | null>(null);

  const agentKey = split.agents.map((a) => a.ref).join("\n");
  useEffect(() => {
    let cancelled = false;
    if (!split.agents.length) {
      setAgentDigests({});
      return;
    }
    void Promise.all(
      split.agents.map(async (agent) => {
        const resolved = await resolveAgentPackageDigest(agent.ref, token);
        return [agent.packageId, resolved?.digest || ""] as const;
      }),
    ).then((rows) => {
      if (cancelled) return;
      const next: Record<string, string> = {};
      for (const [id, digest] of rows) {
        if (digest) next[id] = digest;
      }
      setAgentDigests(next);
    });
    return () => {
      cancelled = true;
    };
  }, [agentKey, token, split.agents]);

  const sources = useMemo(() => {
    const out: OverlaySource[] = [];
    if (split.jobPrefixes.length && datasetId && datasetDigest) {
      out.push({
        key: "job",
        label: "Job",
        packageId: datasetId,
        digest: datasetDigest,
        prefixes: split.jobPrefixes,
      });
    }
    const oneAgent = split.agents.length === 1;
    for (const agent of split.agents) {
      const digest = agentDigests[agent.packageId];
      if (!digest) continue;
      const leaf = agent.packageId.includes("/")
        ? agent.packageId.slice(agent.packageId.lastIndexOf("/") + 1)
        : agent.packageId;
      out.push({
        key: agent.packageId,
        label: oneAgent ? "Agent" : leaf,
        packageId: agent.packageId,
        digest,
        prefixes: agent.prefixes,
      });
    }
    return out;
  }, [agentDigests, datasetDigest, datasetId, split]);

  useEffect(() => {
    if (!sources.length) {
      setScope(null);
      return;
    }
    if (!scope || !sources.some((s) => s.key === scope)) {
      setScope(sources[0].key);
    }
  }, [scope, sources]);

  const active = sources.find((s) => s.key === scope) ?? sources[0];
  if (!active) return null;

  return (
    <div className="space-y-2">
      {sources.length > 1 ? (
        <PillTabs
          items={sources.map((src) => ({ id: src.key, label: src.label }))}
          value={active.key}
          onChange={setScope}
          ariaLabel="Overlay source"
        />
      ) : (
        <p className="text-xs text-mute">
          {active.key === "job"
            ? "Overlays from this job's Dataset package."
            : "Overlays from the bound Agent package."}
        </p>
      )}
      <OverlayFilePanel
        datasetId={active.packageId}
        packageDigest={active.digest}
        prefixes={active.prefixes}
      />
    </div>
  );
}
