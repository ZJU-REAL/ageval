import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { Settings } from "lucide-react";

import { BindingPreview } from "@/components/binding-preview";
import { LoadingState } from "@/components/empty-state";
import { BrandMark } from "@/components/brand-mark";
import { BuiltinMark } from "@/components/builtin-mark";
import { MarketplaceCounts } from "@/components/marketplace-counts";
import { CatalogHead } from "@/components/page-head";
import { PackageStarButton } from "@/components/star-toggle";
import { CommandStrip } from "@/components/command-strip";
import { DisplayNameEditor } from "@/components/display-name-editor";
import { EntityMarkControl } from "@/components/entity-mark-control";
import { entityHintFromPackage, markFromPackage } from "@/lib/brand-marks";
import { OfficialMark } from "@/components/official-mark";
import { FileSplitPanel } from "@/components/file-split-panel";
import { PackageOwnerOps } from "@/components/package-owner-ops";
import { suiteDetailPath } from "@/components/suite-inspector";
import { InlineMarkdown } from "@/components/markdown";
import { Chip } from "@/components/ui/chip";
import { ModelDirectory } from "@/components/model-directory";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/confirm-dialog";
import { UnderlineTabs } from "@/components/underline-tabs";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  getBuiltinPackageFile,
  getOrg,
  getPackageByDigest,
  getPackageFile,
  isBuiltinPackage,
  isDraftRelease,
  listBuiltinPackageFiles,
  listPackageFiles,
  listPackageVersions,
  listPackageVersionsWithPerformances,
  setPerformanceCollect,
  splitPackageId,
  updatePackageDisplayName,
  type AgentPerformance,
  type AgentPreview,
  type PackageRelease,
  type PerformanceCollect,
  type PerformanceCollectMode,
  RegistryHttpError,
} from "@/lib/api";
import {
  comparePerformances,
  groupAgentPerformances,
  performanceColumnValue,
} from "@/lib/agent-performances";
import { sortRows, useTableSort } from "@/components/sortable-head";
import { toast } from "@/components/ui/toast";
import { toastError } from "@/lib/toast-error";
import {
  bindingModel,
  formatAgentRunCommand,
  registeredModels,
} from "@/lib/agent-models";
import { performanceCanonical } from "@/lib/model-appearances";
import { joinOverlay, loadModelPin } from "@/lib/model-pin";
import { getToken } from "@/lib/auth";
import { buildNestedTree, type TreeNode } from "@/lib/file-tree";
import { ScoreRing } from "@/components/score-ring";
import { formatScore } from "@/lib/utils";

type AgentTab = "overview" | "performance" | "files";

function parseAgentTab(raw: string | null): AgentTab {
  if (raw === "performance" || raw === "files") return raw;
  return "overview";
}

function collectDraftFromMode(mode: PerformanceCollectMode): {
  auto: boolean;
  range: "official" | "official_and_personal";
} {
  if (mode === "off") return { auto: false, range: "official" };
  if (mode === "official_and_personal") {
    return { auto: true, range: "official_and_personal" };
  }
  return { auto: true, range: "official" };
}

function modeFromCollectDraft(draft: {
  auto: boolean;
  range: "official" | "official_and_personal";
}): PerformanceCollectMode {
  if (!draft.auto) return "off";
  return draft.range;
}

export function AgentDetailPage() {
  const { agentId: rawId } = useParams();
  const agentId = decodeDatasetId(rawId || "");
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedModel = (searchParams.get("model") || "").trim();
  const pageTab = parseAgentTab(searchParams.get("tab"));
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
  const [performances, setPerformances] = useState<AgentPerformance[]>([]);
  const [collect, setCollect] = useState<PerformanceCollect | null>(null);
  const [collectOpen, setCollectOpen] = useState(false);
  const [collectDraft, setCollectDraft] = useState({
    auto: true,
    range: "official" as "official" | "official_and_personal",
  });
  const [collectBusy, setCollectBusy] = useState(false);
  const [modelQuery, setModelQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setTreeLoading(true);
      setError(null);
      try {
        const listed = await listPackageVersionsWithPerformances(agentId, token, {
          packageKind: "agent",
        });
        const versions = listed.items;
        if (!versions.length) {
          throw new RegistryHttpError(404, "not_found", "agent not found");
        }
        setPerformances(listed.performances);
        setCollect(listed.performanceCollect);
        const latest = [...versions].sort(
          (a, b) => (b.created_at ?? 0) - (a.created_at ?? 0),
        )[0];
        if (cancelled) return;

        if (isBuiltinPackage(latest)) {
          setRelease(latest);
          setPreview(latest.agent_preview || null);
          setCanEditName(false);
          const files = await listBuiltinPackageFiles(agentId, token, {
            packageKind: "agent",
          });
          if (cancelled) return;
          const nested = buildNestedTree(files.items);
          setTree(nested);
          setFilePaths(files.items.filter((e) => e.type !== "dir").map((e) => e.path));
          const prefer =
            files.items.find((e) => e.path === "agent.yaml") ||
            files.items.find((e) => e.path === "README.md") ||
            files.items.find((e) => e.type !== "dir");
          if (prefer) setSelectedPath(prefer.path);
          return;
        }

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
        setPerformances([]);
        setCollect(null);
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
  const builtin = isBuiltinPackage(release);

  useEffect(() => {
    if (!selectedPath || (!builtin && !packageDigest)) {
      setFileContent(null);
      setFileNote(null);
      return;
    }
    let cancelled = false;
    setFileLoading(true);
    setFileNote(null);
    const pending = builtin
      ? getBuiltinPackageFile(agentId, selectedPath, token, {
          packageKind: "agent",
        })
      : getPackageFile(agentId, packageDigest || "", selectedPath, token);
    pending
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
  }, [agentId, packageDigest, selectedPath, token, builtin]);

  const installCmd = useMemo(() => {
    if (!release) return `ageval agent install ${agentId}@<version>`;
    return `ageval agent install ${agentId}@${release.version}`;
  }, [agentId, release]);

  const runCmd = useMemo(
    () =>
      formatAgentRunCommand(
        agentId,
        release?.version || "<version>",
        selectedModel,
        { builtin },
      ),
    [agentId, release, selectedModel, builtin],
  );

  const formatBadge =
    preview?.format || (release?.package_kind === "agent" ? "ageval.agent/1" : null);

  const packageParts = useMemo(() => splitPackageId(agentId), [agentId]);

  const binding = (preview?.binding || {}) as Record<string, unknown>;
  const hasBinding = Object.keys(binding).length > 0;
  const defaultModel = bindingModel(binding);
  const models = useMemo(
    () =>
      registeredModels(
        defaultModel,
        performances.map((row) => row.model),
        selectedModel,
      ),
    [performances, defaultModel, selectedModel],
  );
  const shownModels = useMemo(() => {
    const q = modelQuery.trim().toLowerCase();
    if (!q) return models;
    return models.filter((model) => model.toLowerCase().includes(q));
  }, [models, modelQuery]);

  const agentHref = useCallback(
    (next?: { model?: string | null; tab?: AgentTab }) => {
      const n = new URLSearchParams();
      const model = next && "model" in next ? next.model : selectedModel;
      const tab = next?.tab ?? pageTab;
      const m = (model || "").trim();
      if (m) n.set("model", m);
      if (tab !== "overview") n.set("tab", tab);
      const qs = n.toString();
      return `/agents/${encodeDatasetId(agentId)}${qs ? `?${qs}` : ""}`;
    },
    [agentId, pageTab, selectedModel],
  );

  const directoryRows = useMemo(() => {
    const pin = loadModelPin();
    return shownModels.map((model) => {
      const related = performances.filter((row) => (row.model || "").trim() === model);
      const stored = related.map((row) => performanceCanonical(row)).find(Boolean);
      return {
        overlay: model,
        canonical: stored || joinOverlay(model, pin).canonical,
        selected: model === selectedModel,
        isDefault: model === defaultModel,
        href: agentHref({
          model: model === selectedModel ? null : model,
        }),
      };
    });
  }, [shownModels, performances, selectedModel, defaultModel, agentHref]);
  const visiblePerformances = useMemo(() => {
    if (!selectedModel) return performances;
    return performances.filter(
      (row) => (row.model || "").trim() === selectedModel,
    );
  }, [performances, selectedModel]);

  function setTab(next: AgentTab) {
    const n = new URLSearchParams(searchParams);
    if (next === "overview") n.delete("tab");
    else n.set("tab", next);
    setSearchParams(n, { replace: true });
  }

  function openOverlayPath(declared: string) {
    const prefix = declared.endsWith("/") ? declared : `${declared}/`;
    const resolved =
      filePaths.find((p) => p === declared) ||
      filePaths.find((p) => p.startsWith(prefix)) ||
      declared;
    setSelectedPath(resolved);
    setTab("files");
  }

  const performanceGroups = useMemo(
    () =>
      groupAgentPerformances(visiblePerformances, {
        builtin,
        selectedModel,
      }),
    [visiblePerformances, builtin, selectedModel],
  );
  const performanceSort = useTableSort("pass_rate", "desc");
  const sortedPerformanceGroups = useMemo(
    () =>
      performanceGroups.map((group) => ({
        ...group,
        rows: sortRows(
          group.rows,
          performanceSort.sortKey,
          performanceSort.sortDir,
          performanceColumnValue,
          comparePerformances,
        ),
      })),
    [
      performanceGroups,
      performanceSort.sortKey,
      performanceSort.sortDir,
    ],
  );

  function openCollect() {
    const mode = collect?.mode || "official";
    setCollectDraft(collectDraftFromMode(mode));
    setCollectOpen(true);
  }

  function openPerformance(row: AgentPerformance) {
    if (!row.dataset_id || !row.suite_run_id) return;
    navigate(
      suiteDetailPath(row.dataset_id, row.suite_run_id, {
        agent: agentId,
        role: row.role,
      }),
    );
  }

  async function saveCollect() {
    if (!token) return;
    setCollectBusy(true);
    try {
      const next = await setPerformanceCollect(
        agentId,
        modeFromCollectDraft(collectDraft),
        token,
      );
      setCollect(next);
      setCollectOpen(false);
      setReloadAt((n) => n + 1);
      toast("Performance collection saved");
    } catch (err) {
      toastError(err);
    } finally {
      setCollectBusy(false);
    }
  }

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
              canEdit={Boolean(token && canEditName && release && !builtin)}
              headingClassName="text-xl font-semibold tracking-tight text-ink"
              beforeTitle={
                builtin && release ? (
                  <BrandMark mark={markFromPackage(release)} size={24} />
                ) : release ? (
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
              afterTitle={
                builtin ? (
                  <BuiltinMark />
                ) : release?.official ? (
                  <OfficialMark />
                ) : null
              }
              onSave={async (next) => {
                const updated = await updatePackageDisplayName(agentId, next, token);
                setRelease((prev) =>
                  prev ? { ...prev, display_name: updated.display_name || next } : prev,
                );
              }}
            />
            {formatBadge ? (
              <Chip size="sm" className="font-medium">
                {formatBadge}
              </Chip>
            ) : null}
          </div>
          {release ? (
            <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-mute">
              <span>@{agentId}</span>
              {builtin ? null : (
                <>
                  <span aria-hidden>·</span>
                  <span>
                    {isDraftRelease(release) ? "draft" : `v${release.version}`}
                  </span>
                  <span aria-hidden>·</span>
                  <MarketplaceCounts
                    downloadCount={release.download_count}
                    favoriteCount={release.favorite_count}
                  />
                </>
              )}
              {release.org_id ? (
                <>
                  <span aria-hidden>·</span>
                  <span className="inline-flex items-center gap-1">
                    org{" "}
                    <Link
                      to={`/organizations/${encodeURIComponent(release.org_id)}`}
                      className="text-link hover:text-link-deep"
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
            {builtin && collect?.can_edit ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={openCollect}
              >
                <Settings className="h-4 w-4" aria-hidden />
                Collect
              </Button>
            ) : null}
            {!builtin ? (
              <>
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
              </>
            ) : null}
          </div>
        ) : null}
      </div>

      {loading && <LoadingState label="Loading agent" />}
      {error && (
        <div className="blob-panel p-4 text-sm">
          <p className="text-error font-medium">Could not load agent</p>
          <p className="mt-1 text-xs text-body">{error}</p>
          <p className="mt-3">
            <Link to="/agents" className="text-link hover:text-link-deep underline underline-offset-2">
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
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="shrink-0 text-sm font-medium text-ink">Model</h2>
              {models.length > 0 ? (
                <Input
                  value={modelQuery}
                  onChange={(e) => setModelQuery(e.target.value)}
                  placeholder="Search models…"
                  aria-label="Search models"
                  className="h-9 w-[min(100%,24rem)] max-w-sm focus-visible:border-hairline"
                />
              ) : null}
            </div>
            <p className="text-xs text-mute">
              {builtin
                ? "Models from collected Dataset Leaderboard runs of this harness. Selecting one is query state on this page, not a second package."
                : "Package default plus models that appeared on consented plaza suites. Selecting one is query state on this harness page, not a second package."}
            </p>
            {models.length === 0 ? (
              <p className="text-sm text-mute">
                No registered model yet. The package default is empty.
              </p>
            ) : shownModels.length === 0 ? (
              <p className="text-sm text-mute">
                No models match “{modelQuery.trim()}”.
              </p>
            ) : (
              <ModelDirectory rows={directoryRows} />
            )}
          </section>

          <section className="space-y-2">
            {builtin ? null : <CommandStrip command={installCmd} />}
            <CommandStrip command={runCmd} />
            <p className="text-xs text-mute">
              {builtin ? (
                <>
                  Ships with ageval; no install. Bind a run with{" "}
                  <span>--agent</span>. Optional <span>--model</span>{" "}
                  overrides this run&apos;s model.
                </>
              ) : (
                <>
                  Install writes only the local cache; the harness binds per run
                  via <span>--agent</span>. Optional <span>--model</span>{" "}
                  overrides this run&apos;s model. <span>agent_ref</span> is
                  provenance, not fingerprint identity.
                </>
              )}
            </p>
          </section>

          <UnderlineTabs
            ariaLabel="Agent sections"
            value={pageTab}
            onChange={setTab}
            items={[
              { id: "overview", label: "Overview" },
              { id: "performance", label: "Performance" },
              { id: "files", label: "Files" },
            ]}
          />

          {pageTab === "overview" ? (
            <section className="space-y-2">
              <h2 className="text-sm font-medium text-ink">Job binding</h2>
              {hasBinding ? (
                <BindingPreview
                  binding={binding}
                  runModel={selectedModel}
                  onOpenOverlay={openOverlayPath}
                />
              ) : (
                <p className="text-sm text-mute">
                  No binding preview available.
                </p>
              )}
            </section>
          ) : null}

          {pageTab === "performance" ? (
            <section className="space-y-3">
              <p className="text-xs text-mute">
                {builtin
                  ? "Leaderboard suites collected onto this card (official plaza by default; a Maintainer can change the range). Observational metrics only — PASS stays on the independent evaluator."
                  : "Official public complete release-bound suites with this Agent org’s consent (direct attach or an approved Performance request). Observational metrics only — PASS stays on the independent evaluator."}
                {sortedPerformanceGroups.length > 0
                  ? " · click headers to sort"
                  : null}
              </p>
              {sortedPerformanceGroups.length === 0 ? (
                <p className="text-sm text-mute">
                  {selectedModel
                    ? builtin
                      ? "No collected Performance for this model yet."
                      : "No consented Performance for this model yet."
                    : builtin
                      ? "No collected Performance yet. Upload a public complete suite on an official Dataset that ran this harness, or attach with Maintainer approval."
                      : (
                        <>
                          No Hub Performance yet. Attach a published{" "}
                          <span>org/name@version</span> as this
                          Agent’s org owner, or approve a Performance request.
                        </>
                      )}
                </p>
              ) : (
                sortedPerformanceGroups.map((group) => (
                  <div key={group.key} className="space-y-2">
                    {group.heading ? (
                      <h3 className="text-xs text-mute">{group.heading}</h3>
                    ) : null}
                    <div className="blob-panel overflow-hidden">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>
                              {performanceSort.head("dataset_id", "Dataset")}
                            </TableHead>
                            <TableHead>
                              {performanceSort.head("role", "Role")}
                            </TableHead>
                            <TableHead>
                              {performanceSort.head("model", "Model")}
                            </TableHead>
                            <TableHead>
                              {performanceSort.head("pass_rate", "Pass rate")}
                            </TableHead>
                            <TableHead>
                              {performanceSort.head("mean_score", "Mean")}
                            </TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {group.rows.map((row) => {
                            const key = `${row.suite_run_id}:${row.role}`;
                            return (
                              <TableRow
                                key={key}
                                className="cursor-pointer"
                                onClick={() => openPerformance(row)}
                              >
                                <TableCell>
                                  <Link
                                    to={`/datasets/${encodeDatasetId(row.dataset_id)}?tab=leaderboard`}
                                    className="text-link hover:text-link-deep hover:underline underline-offset-2"
                                    onClick={(event) => event.stopPropagation()}
                                  >
                                    {row.dataset_id}
                                  </Link>
                                </TableCell>
                                <TableCell>
                                  {row.role}
                                </TableCell>
                                <TableCell>
                                  {row.model || "—"}
                                </TableCell>
                                <TableCell className="tabular-nums">
                                  <ScoreRing value={row.pass_rate}>
                                    {formatScore(row.pass_rate)}
                                  </ScoreRing>
                                </TableCell>
                                <TableCell className="tabular-nums">
                                  <ScoreRing value={row.mean_score}>
                                    {formatScore(row.mean_score)}
                                  </ScoreRing>
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
          ) : null}

          {pageTab === "files" ? (
            <section className="space-y-2">
              <p className="text-xs text-mute">
                Read-only preview of this package, including any bundled{" "}
                <span>overlays/</span> files. Locator names
                only, never secret values.
              </p>
              <div className="blob-panel overflow-hidden">
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
          ) : null}
        </div>
      )}

      <Modal
        open={collectOpen}
        title="Performance collection"
        description="Choose whether this builtin agent auto-collects Dataset Leaderboard Performance. Off means only Maintainer attach or an approved request."
        onClose={() => setCollectOpen(false)}
      >
        <div className="space-y-4">
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={collectDraft.auto}
              onChange={(event) =>
                setCollectDraft((prev) => ({ ...prev, auto: event.target.checked }))
              }
            />
            Auto-collect from Dataset Leaderboards
          </label>
          <div className="space-y-1.5">
            <p className="text-xs text-mute">Range</p>
            <Select
              value={collectDraft.range}
              onValueChange={(value) =>
                setCollectDraft((prev) => ({
                  ...prev,
                  range: value as "official" | "official_and_personal",
                }))
              }
              disabled={!collectDraft.auto}
            >
              <SelectTrigger aria-label="Collection range" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="official" mono={false}>
                  Official datasets
                </SelectItem>
                <SelectItem value="official_and_personal" mono={false}>
                  Official and personal
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setCollectOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={collectBusy}
              onClick={() => void saveCollect()}
            >
              Save
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
