import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { BindingPreview } from "@/components/binding-preview";
import { MarketplaceCounts } from "@/components/marketplace-counts";
import { CatalogHead } from "@/components/page-head";
import { PackageStarButton } from "@/components/star-toggle";
import { CommandStrip } from "@/components/command-strip";
import { DisplayNameEditor } from "@/components/display-name-editor";
import { EntityMarkControl } from "@/components/entity-mark-control";
import { entityHintFromPackage } from "@/lib/brand-marks";
import { OfficialMark } from "@/components/official-mark";
import { FileSplitPanel } from "@/components/file-split-panel";
import { PackageOwnerOps } from "@/components/package-owner-ops";
import { InlineMarkdown } from "@/components/markdown";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  decodeDatasetId,
  decodeFileContent,
  encodeDatasetId,
  getOrg,
  getPackageByDigest,
  getPackageFile,
  isDraftRelease,
  listPackageFiles,
  listPackageVersions,
  listPackageVersionsWithAppearances,
  splitPackageId,
  updatePackageDisplayName,
  type AgentAppearance,
  type AgentPreview,
  type PackageRelease,
  RegistryHttpError,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import { buildNestedTree, type TreeNode } from "@/lib/file-tree";
import { formatScore } from "@/lib/utils";

export function AgentDetailPage() {
  const { agentId: rawId } = useParams();
  const agentId = decodeDatasetId(rawId || "");
  const token = getToken();
  const navigate = useNavigate();
  const [reloadAt, setReloadAt] = useState(0);

  const [release, setRelease] = useState<PackageRelease | null>(null);
  const [preview, setPreview] = useState<AgentPreview | null>(null);
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [filePaths, setFilePaths] = useState<string[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileNote, setFileNote] = useState<string | null>(null);
  const [treeLoading, setTreeLoading] = useState(true);
  const [fileLoading, setFileLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [canEditName, setCanEditName] = useState(false);
  const [appearances, setAppearances] = useState<AgentAppearance[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setTreeLoading(true);
      setError(null);
      try {
        const listed = await listPackageVersionsWithAppearances(agentId, token);
        const versions = listed.items;
        if (!versions.length) {
          throw new RegistryHttpError(404, "not_found", "agent not found");
        }
        setAppearances(listed.appearances);
        const latest = [...versions].sort(
          (a, b) => (b.created_at ?? 0) - (a.created_at ?? 0),
        )[0];
        if (cancelled) return;

        let meta: PackageRelease = latest;
        try {
          meta = await getPackageByDigest(agentId, latest.package_digest, token);
        } catch {
          /* list meta is enough for non-preview fields */
        }
        if (cancelled) return;

        if (meta.package_kind && meta.package_kind !== "agent") {
          throw new RegistryHttpError(
            404,
            "not_found",
            "not an agent package (use Datasets / Plugins for other kinds)",
          );
        }

        setRelease(meta);
        setPreview(meta.agent_preview || null);
        if (token && meta.org_id) {
          try {
            const org = await getOrg(meta.org_id, token);
            if (!cancelled) {
              setCanEditName((org.role || "").toLowerCase() === "owner");
            }
          } catch {
            if (!cancelled) setCanEditName(false);
          }
        } else if (!cancelled) {
          setCanEditName(false);
        }

        const files = await listPackageFiles(agentId, latest.package_digest, token);
        if (cancelled) return;
        const nested = buildNestedTree(files.items);
        setTree(nested);
        setFilePaths(files.items.filter((e) => e.type !== "dir").map((e) => e.path));
        const prefer =
          files.items.find((e) => e.path === "agent.yaml") ||
          files.items.find((e) => e.path === "README.md") ||
          files.items.find((e) => e.type !== "dir");
        if (prefer) setSelectedPath(prefer.path);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof RegistryHttpError) {
          setError(`${err.code}: ${err.message}`);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
        setRelease(null);
        setPreview(null);
        setTree([]);
        setFilePaths([]);
        setAppearances([]);
      } finally {
        if (!cancelled) {
          setLoading(false);
          setTreeLoading(false);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [agentId, token, reloadAt]);

  const packageDigest = release?.package_digest;

  useEffect(() => {
    if (!packageDigest || !selectedPath) {
      setFileContent(null);
      setFileNote(null);
      return;
    }
    let cancelled = false;
    setFileLoading(true);
    setFileNote(null);
    getPackageFile(agentId, packageDigest, selectedPath, token)
      .then((f) => {
        if (cancelled) return;
        try {
          setFileContent(decodeFileContent(f));
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
  }, [agentId, packageDigest, selectedPath, token]);

  const installCmd = useMemo(() => {
    if (!release) return `ageval agent install ${agentId}@<version>`;
    return `ageval agent install ${agentId}@${release.version}`;
  }, [agentId, release]);

  const runCmd = useMemo(() => {
    const ver = release?.version || "<version>";
    return `ageval run <dataset> --agent ${agentId}@${ver}`;
  }, [agentId, release]);

  const formatBadge =
    preview?.format || (release?.package_kind === "agent" ? "ageval.agent/1" : null);

  const packageParts = useMemo(() => splitPackageId(agentId), [agentId]);

  const binding = (preview?.binding || {}) as Record<string, unknown>;
  const hasBinding = Object.keys(binding).length > 0;

  function openOverlayPath(declared: string) {
    const prefix = declared.endsWith("/") ? declared : `${declared}/`;
    const resolved =
      filePaths.find((p) => p === declared) ||
      filePaths.find((p) => p.startsWith(prefix)) ||
      declared;
    setSelectedPath(resolved);
    document
      .getElementById("agent-files")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const appearancesByVersion = useMemo(() => {
    const groups = new Map<string, AgentAppearance[]>();
    for (const row of appearances) {
      const key = row.agent_version || "unknown";
      const list = groups.get(key) ?? [];
      list.push(row);
      groups.set(key, list);
    }
    return [...groups.entries()].sort(([a], [b]) => b.localeCompare(a));
  }, [appearances]);

  return (
    <>
      <CatalogHead
        title="Agent hub"
        crumbs={[
          { label: "Agent hub", href: "/agents" },
          { label: agentId || "…" },
        ]}
      />

      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <DisplayNameEditor
              value={
                release?.display_name?.trim() ||
                preview?.label?.trim() ||
                packageParts.name
              }
              prefix={packageParts.org ? `${packageParts.org}/` : null}
              canEdit={Boolean(token && canEditName && release)}
              headingClassName="text-xl font-semibold tracking-tight text-ink"
              beforeTitle={
                release ? (
                  <EntityMarkControl
                    hint={entityHintFromPackage({
                      ...release,
                      agent_preview: preview || release.agent_preview,
                    })}
                    packageId={agentId}
                    token={token}
                    canEdit={Boolean(token && canEditName)}
                    onUpdated={(patch) => {
                      setRelease((prev) =>
                        prev
                          ? {
                              ...prev,
                              icon_key: patch.icon_key,
                              icon_github: patch.icon_github,
                            }
                          : prev,
                      );
                    }}
                  />
                ) : null
              }
              afterTitle={release?.official ? <OfficialMark /> : null}
              onSave={async (next) => {
                const updated = await updatePackageDisplayName(agentId, next, token);
                setRelease((prev) =>
                  prev ? { ...prev, display_name: updated.display_name || next } : prev,
                );
              }}
            />
            {formatBadge ? (
              <span className="text-[11px] font-medium font-mono px-2 py-0.5 rounded border border-hairline bg-canvas-soft text-body">
                {formatBadge}
              </span>
            ) : null}
          </div>
          {release ? (
            <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm text-mute">
              <span className="font-mono">@{agentId}</span>
              <span aria-hidden>·</span>
              <span>
                {isDraftRelease(release) ? "draft" : `v${release.version}`}
              </span>
              <span aria-hidden>·</span>
              <MarketplaceCounts
                downloadCount={release.download_count}
                favoriteCount={release.favorite_count}
              />
              {release.org_id ? (
                <>
                  <span aria-hidden>·</span>
                  <span className="inline-flex items-center gap-1">
                    org{" "}
                    <Link
                      to={`/organizations/${encodeURIComponent(release.org_id)}`}
                      className="font-mono text-xs text-body hover:text-ink"
                    >
                      {release.org_id}
                    </Link>
                    {release.official ? <OfficialMark kind="org" /> : null}
                  </span>
                </>
              ) : null}
            </div>
          ) : null}
        </div>
        {release ? (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <PackageStarButton
              packageId={agentId}
              release={release}
              onUpdated={(next) => {
                setRelease((prev) =>
                  prev
                    ? {
                        ...prev,
                        favorited: next.favorited,
                        favorite_count: next.favorite_count,
                      }
                    : prev,
                );
              }}
            />
            <PackageOwnerOps
              packageId={agentId}
              release={release}
              canManage={canEditName}
              token={token}
              onUpdated={(next) => setRelease(next)}
              onDeleted={() => {
                void listPackageVersions(agentId, token).then((rows) => {
                  if (!rows.length) navigate("/agents");
                  else setReloadAt((n) => n + 1);
                });
              }}
              onReleased={() => setReloadAt((n) => n + 1)}
            />
          </div>
        ) : null}
      </div>

      {loading && <p className="text-sm text-mute">Loading…</p>}
      {error && (
        <div className="rounded-[8px] border border-hairline bg-canvas-soft p-4 text-sm">
          <p className="text-error font-medium">Could not load agent</p>
          <p className="mt-1 font-mono text-xs text-body">{error}</p>
          <p className="mt-3">
            <Link to="/agents" className="underline underline-offset-2 text-body">
              ← Back to Agent hub
            </Link>
          </p>
        </div>
      )}

      {!loading && !error && release && (
        <div className="space-y-6">
          {preview?.description ? (
            <InlineMarkdown source={preview.description} />
          ) : null}

          <section className="space-y-2">
            <h2 className="text-sm font-medium text-ink">Install &amp; run (CLI)</h2>
            <CommandStrip command={installCmd} />
            <CommandStrip command={runCmd} />
            <p className="text-xs text-mute">
              Install writes only the local cache; the binding applies per run via{" "}
              <span className="font-mono">--agent</span> and lands in the lock&apos;s
              job_overlay as <span className="font-mono">agent_ref</span> (provenance,
              not fingerprint identity).
            </p>
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-medium text-ink">Job binding</h2>
            {hasBinding ? (
              <BindingPreview binding={binding} onOpenOverlay={openOverlayPath} />
            ) : (
              <p className="text-sm text-mute">No binding preview available.</p>
            )}
          </section>

          <section className="space-y-3">
            <h2 className="text-sm font-medium text-ink">Appearances</h2>
            <p className="text-xs text-mute">
              Official public complete release-bound suites with this Agent org’s
              consent (direct attach or an approved appearance request).
              Observational metrics only — PASS stays on the independent evaluator.
            </p>
            {appearancesByVersion.length === 0 ? (
              <p className="text-sm text-mute">
                No Hub appearances yet. Attach a published{" "}
                <span className="font-mono">org/name@version</span> as this
                Agent’s org owner, or approve an appearance request.
              </p>
            ) : (
              appearancesByVersion.map(([version, rows]) => (
                <div key={version} className="space-y-2">
                  <h3 className="text-xs font-mono text-mute">v{version}</h3>
                  <div className="rounded-[8px] border border-hairline overflow-hidden">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Dataset</TableHead>
                          <TableHead>Role</TableHead>
                          <TableHead>Model</TableHead>
                          <TableHead className="text-right">Pass rate</TableHead>
                          <TableHead className="text-right">Mean</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {rows.map((row) => {
                          const key = `${row.suite_run_id}:${row.role}`;
                          return (
                            <TableRow key={key}>
                              <TableCell className="font-mono text-xs">
                                <Link
                                  to={`/datasets/${encodeDatasetId(row.dataset_id)}?tab=leaderboard&suite=${encodeURIComponent(row.suite_run_id)}`}
                                  onClick={(e) => e.stopPropagation()}
                                  className="hover:underline underline-offset-2"
                                >
                                  {row.dataset_id}
                                </Link>
                              </TableCell>
                              <TableCell className="font-mono text-xs">
                                {row.role}
                              </TableCell>
                              <TableCell className="font-mono text-xs">
                                {row.model || "—"}
                              </TableCell>
                              <TableCell className="text-right tabular-nums text-xs">
                                {formatScore(row.pass_rate)}
                              </TableCell>
                              <TableCell className="text-right tabular-nums text-xs">
                                {formatScore(row.mean_score)}
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              ))
            )}
          </section>

          <section id="agent-files" className="space-y-2">
            <h2 className="text-sm font-medium text-ink">Files</h2>
            <p className="text-xs text-mute">
              Read-only preview of this package, including any bundled{" "}
              <span className="font-mono">overlays/</span> files. Locator names
              only, never secret values.
            </p>
            <div className="rounded-[8px] border border-hairline overflow-hidden">
              <FileSplitPanel
                tree={tree}
                treeLoading={treeLoading}
                selectedPath={selectedPath}
                onSelect={setSelectedPath}
                fileContent={fileContent}
                fileLoading={fileLoading}
                fileNote={fileNote}
              />
            </div>
          </section>
        </div>
      )}
    </>
  );
}
