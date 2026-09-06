import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createPortal } from "react-dom";

import { BrandMark } from "@/components/brand-mark";
import { BuiltinMark } from "@/components/builtin-mark";
import { CodeFence } from "@/components/code-fence";
import { TruncateTip } from "@/components/hover-tip";
import { ModelLabel } from "@/components/model-label";
import { OverlayRootProvider } from "@/components/overlay-root";
import { JobOverlayPreview } from "@/components/overlay-file-panel";
import { ResultOwnerOps } from "@/components/result-owner-ops";
import { ScoreRing } from "@/components/score-ring";
import { ScrollTable } from "@/components/scroll-table";
import { Button } from "@/components/ui/button";
import { UnderlineTabs } from "@/components/underline-tabs";
import {
  encodeDatasetId,
  environmentFromOverlay,
  overlayAgentProfiles,
  pluginsUsedBySuite,
  type PackageRelease,
  type SuiteRow,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import { resolveMechanismMark } from "@/lib/brand-marks";
import {
  displayLabelsFromOverlay,
  formatScore,
  reasoningEffortFromOverlay,
} from "@/lib/utils";

type SuiteInspectorTab = "profiles" | "plugin" | "jobs" | "share";

/** Compact suite id for cells; full id in title. System ids are bare 8-hex. */
export function shortSuiteId(id: string): string {
  const raw = id.trim();
  if (/^[0-9a-f]+$/i.test(raw)) {
    return raw.length <= 8 ? raw : raw.slice(0, 8);
  }
  if (raw.length <= 12) return raw;
  return `${raw.slice(0, 10)}…`;
}

function jobOverlayToProfilesYaml(overlay: SuiteRow["job_overlay"]): string {
  const profiles = overlayAgentProfiles(overlay);
  const environment = environmentFromOverlay(overlay);
  if (!environment && !Object.keys(profiles).length) {
    return "# no job_overlay on this suite\n";
  }
  const lines: string[] = ["format: ageval.profiles/1"];
  if (environment) lines.push(`environment: ${environment}`);
  lines.push("agent_profiles:");
  const roles = Object.keys(profiles).sort();
  if (roles.length === 0) {
    lines.push("  {}");
    return lines.join("\n") + "\n";
  }
  for (const role of roles) {
    const b = profiles[role];
    if (!b || typeof b !== "object") continue;
    lines.push(`  ${role}:`);
    if (b.executor != null) lines.push(`    executor: ${String(b.executor)}`);
    if (b.options && typeof b.options === "object" && b.options.entry != null) {
      lines.push("    options:");
      lines.push(`      entry: ${String(b.options.entry)}`);
    }
    if (b.model != null) lines.push(`    model: ${String(b.model)}`);
    if (b.base_url != null) lines.push(`    base_url: ${String(b.base_url)}`);
    if (b.api_key != null) lines.push(`    api_key: ${String(b.api_key)}`);
    const overlays = Array.isArray(b.overlays) ? b.overlays.filter(Boolean) : [];
    if (overlays.length) {
      lines.push("    overlays:");
      for (const path of overlays) {
        lines.push(`      - ${String(path)}`);
      }
    }
  }
  return lines.join("\n") + "\n";
}

function suiteJobRows(suite: SuiteRow): Array<{
  key: string;
  taskId: string;
  runId: string | null;
  status: string | null;
  score: number | null;
  hasAttempt: boolean;
}> {
  const rows: Array<{
    key: string;
    taskId: string;
    runId: string | null;
    status: string | null;
    score: number | null;
    hasAttempt: boolean;
  }> = [];
  for (const ref of suite.task_refs || []) {
    const taskId = (ref.task_id || "").trim();
    if (!taskId) continue;
    const ids =
      Array.isArray(ref.attempt_run_ids) && ref.attempt_run_ids.length
        ? ref.attempt_run_ids.filter((id): id is string => Boolean(id))
        : ref.run_id
          ? [ref.run_id]
          : [];
    if (ids.length === 0) {
      rows.push({
        key: `${suite.suite_run_id}:${taskId}:none`,
        taskId,
        runId: null,
        status: ref.status ?? null,
        score: ref.score ?? null,
        hasAttempt: false,
      });
      continue;
    }
    for (const runId of ids) {
      rows.push({
        key: `${suite.suite_run_id}:${taskId}:${runId}`,
        taskId,
        runId,
        status: ref.status ?? null,
        score: ref.score ?? null,
        hasAttempt: Boolean(ref.has_attempt_content) && Boolean(runId),
      });
    }
  }
  return rows;
}

function SuiteJobsList({
  suite,
  datasetId,
  onOpen,
}: {
  suite: SuiteRow;
  datasetId: string;
  onOpen: (href: string) => void;
}) {
  const rows = suiteJobRows(suite);
  if (rows.length === 0) {
    return (
      <p className="text-sm text-mute">
        No task results on this suite. Upload with{" "}
        <code className="font-mono">ageval results upload-suite</code>.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-mute">
        Each row is this suite&apos;s result for one task. Click a row with
        uploaded Attempt evidence to open the same job detail as Task Jobs.
      </p>
      <ScrollTable
        headers={["Task", "Status", "Score", "Attempt"]}
        rows={rows.map((j) => {
          const href =
            j.hasAttempt && j.runId
              ? `/datasets/${encodeDatasetId(datasetId)}/tasks/${encodeURIComponent(j.taskId)}/attempts/${encodeURIComponent(j.runId)}`
              : null;
          return {
            key: j.key,
            onClick: href ? () => onOpen(href) : undefined,
            muted: !href,
            cells: [
              <span key="t">{j.taskId}</span>,
              j.status || "—",
              <ScoreRing key="score" value={j.score}>
                {formatScore(j.score)}
              </ScoreRing>,
              j.runId ? (
                <span key="r">
                  {shortSuiteId(j.runId)}
                  {!href ? (
                    <span className="ml-2 font-sans text-[11px] text-mute">
                      summary only
                    </span>
                  ) : null}
                </span>
              ) : (
                "—"
              ),
            ],
          };
        })}
      />
    </div>
  );
}

export function SuiteInspector({
  suite,
  datasetId,
  overlayDigest,
  pluginCatalog,
  orgId,
  canManage,
  onClose,
  onSuiteUpdated,
  onSuiteDeleted,
  canDetachPerformance = false,
  onRemovePerformance,
}: {
  suite: SuiteRow;
  datasetId: string;
  overlayDigest?: string;
  pluginCatalog: PackageRelease[];
  orgId?: string | null;
  canManage: boolean;
  onClose: () => void;
  onSuiteUpdated?: (suiteRunId: string, patch: Partial<SuiteRow>) => void;
  onSuiteDeleted?: (suiteRunId: string) => void;
  canDetachPerformance?: boolean;
  onRemovePerformance?: () => void;
}) {
  const navigate = useNavigate();
  const [tab, setTab] = useState<SuiteInspectorTab>("profiles");
  const [dialogEl, setDialogEl] = useState<HTMLElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    setTab("profiles");
  }, [suite.suite_run_id]);

  useEffect(() => {
    if (tab === "share" && !canManage) setTab("profiles");
  }, [tab, canManage]);

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      const dialogs = document.querySelectorAll('[role="dialog"]');
      const top = dialogs[dialogs.length - 1];
      if (top && top !== panelRef.current) return;
      onCloseRef.current();
    }
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  if (typeof document === "undefined") return null;

  const m = suite.metrics || {};
  const nTasks =
    typeof m.n_tasks === "number"
      ? m.n_tasks
      : Array.isArray(suite.task_refs)
        ? suite.task_refs.length
        : null;
  const nPass = typeof m.n_pass === "number" ? m.n_pass : null;
  const derived = displayLabelsFromOverlay(suite.job_overlay);
  const agentText = derived.agent || suite.agent_label || "";
  const modelText = derived.model || suite.model_label || "";
  const environment = environmentFromOverlay(suite.job_overlay) || "";
  const environmentKey = resolveMechanismMark(environment);
  const yamlText = jobOverlayToProfilesYaml(suite.job_overlay);
  const plugins = pluginsUsedBySuite(suite, pluginCatalog, orgId);
  const rehydrateScript = [
    "# Export this suite's job binding as profiles.yaml (locators only; no secrets)",
    `ageval results export-profiles ${suite.suite_run_id} --out profiles.from-suite.yaml`,
    "",
    "# Re-run with that binding (fill Dataset .env locally for credentials)",
    "ageval run <dataset-root> --profiles profiles.from-suite.yaml",
    "",
  ].join("\n");
  const title = [agentText || "Suite", modelText].filter(Boolean).join(" · ");
  const tabItems: { id: SuiteInspectorTab; label: string }[] = [
    { id: "profiles", label: "Profiles" },
    { id: "plugin", label: "Plugin" },
    { id: "jobs", label: "Jobs" },
  ];
  if (canManage) tabItems.push({ id: "share", label: "Share" });

  return createPortal(
    <div
      data-ageval-scrim=""
      className="fixed inset-0 z-[60] flex items-center justify-center p-3 sm:p-6 bg-ink/40"
      role="presentation"
      onClick={onClose}
    >
      <div
        ref={(node) => {
          panelRef.current = node;
          setDialogEl(node);
        }}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        data-ageval-pop=""
        className="flex h-[min(64vh,32rem)] w-[min(48rem,calc(100vw-1.5rem))] flex-col overflow-visible rounded-[14px] border border-hairline bg-canvas shadow-[var(--viewer-shadow-pop)]"
        onClick={(event) => event.stopPropagation()}
      >
        <OverlayRootProvider value={dialogEl}>
          <div className="shrink-0 border-b border-hairline px-4 pt-3">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink">
                  {environmentKey ? (
                    <BrandMark
                      mark={{ kind: "catalog", id: environmentKey }}
                      size={16}
                    />
                  ) : null}
                  {agentText ? (
                    <TruncateTip text={agentText} />
                  ) : (
                    <span className="text-mute">—</span>
                  )}
                  <span className="text-mute" aria-hidden>
                    ·
                  </span>
                  <ModelLabel
                    value={modelText}
                    effort={reasoningEffortFromOverlay(suite.job_overlay)}
                  />
                  {environment ? (
                    <>
                      <span className="text-mute" aria-hidden>
                        ·
                      </span>
                      <span className="text-body">{environment}</span>
                    </>
                  ) : null}
                </div>
                <div className="text-xs text-mute">
                  <span className="tabular-nums text-ink">
                    {suite.pass_rate == null
                      ? "—"
                      : `${(Number(suite.pass_rate) * 100).toFixed(1)}%`}
                  </span>
                  {" · mean "}
                  <span className="tabular-nums text-ink">
                    {formatScore(suite.mean_score)}
                  </span>
                  {nPass != null && nTasks != null ? (
                    <>
                      {" · "}
                      <span className="tabular-nums text-ink">
                        {nPass}/{nTasks}
                      </span>
                    </>
                  ) : nTasks != null ? (
                    <>
                      {" · "}
                      <span className="tabular-nums text-ink">{nTasks}</span>
                      {" tasks"}
                    </>
                  ) : null}
                  {" · "}
                  <TruncateTip
                    text={shortSuiteId(suite.suite_run_id)}
                    copyValue={suite.suite_run_id}
                    copyable
                  />
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-0.5">
                {canManage || canDetachPerformance ? (
                  <ResultOwnerOps
                    kind="suite"
                    resultId={suite.suite_run_id}
                    visibility={suite.visibility}
                    complete={suite.complete}
                    boundKind={suite.bound_kind}
                    boardListed={suite.board_listed}
                    jobOverlay={suite.job_overlay}
                    canManage={canManage}
                    canDetachPerformance={canDetachPerformance}
                    onRemovePerformance={onRemovePerformance}
                    variant="delete"
                    token={getToken()}
                    onDeleted={() => {
                      onClose();
                      onSuiteDeleted?.(suite.suite_run_id);
                    }}
                  />
                ) : null}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label="Close"
                  onClick={onClose}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </div>
            <UnderlineTabs
              className="mt-2"
              size="sm"
              ariaLabel="Suite details"
              value={tab}
              onChange={setTab}
              items={tabItems}
            />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {tab === "profiles" ? (
              <div className="space-y-3">
                <CodeFence
                  path="profiles.yaml"
                  content={yamlText}
                  maxHeightClass="max-h-56"
                />
                <CodeFence
                  path="rehydrate.sh"
                  content={rehydrateScript}
                  maxHeightClass="max-h-40"
                />
                <JobOverlayPreview
                  overlay={suite.job_overlay}
                  datasetId={datasetId}
                  datasetDigest={overlayDigest || ""}
                />
              </div>
            ) : tab === "plugin" ? (
              <div className="space-y-2">
                {plugins.length === 0 ? (
                  <p className="text-sm text-mute">
                    No plugins recorded for this job.
                  </p>
                ) : (
                  <ul className="divide-y divide-hairline rounded-[14px] border border-hairline bg-canvas">
                    {plugins.map((p) => {
                      const bundled = pluginCatalog.some(
                        (row) =>
                          row.dataset_id === p.plugin_id && row.builtin,
                      );
                      return (
                        <li key={p.plugin_id}>
                          <Link
                            to={`/plugins/${encodeDatasetId(p.plugin_id)}`}
                            className="flex items-center justify-between gap-3 px-3 py-2 text-sm hover:bg-row-hover"
                          >
                            <span className="inline-flex min-w-0 items-center gap-1.5 text-link hover:text-link-deep">
                              {p.plugin_id}
                              {bundled ? <BuiltinMark /> : null}
                            </span>
                            <span className="text-xs text-mute">
                              {bundled
                                ? "bundled"
                                : p.version
                                  ? `v${p.version}`
                                  : "marketplace"}
                            </span>
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            ) : tab === "share" ? (
              <div className="space-y-4">
                <p className="text-xs text-mute">
                  Who can see this suite, and whether it is listed.
                </p>
                <ResultOwnerOps
                  kind="suite"
                  resultId={suite.suite_run_id}
                  visibility={suite.visibility}
                  complete={suite.complete}
                  boundKind={suite.bound_kind}
                  boardListed={suite.board_listed}
                  jobOverlay={suite.job_overlay}
                  canManage
                  variant="panel"
                  token={getToken()}
                  onVisibility={(next) =>
                    onSuiteUpdated?.(suite.suite_run_id, {
                      visibility: next,
                    })
                  }
                  onAttached={(row) =>
                    onSuiteUpdated?.(suite.suite_run_id, row)
                  }
                />
              </div>
            ) : (
              <SuiteJobsList
                suite={suite}
                datasetId={datasetId}
                onOpen={(href) => {
                  onClose();
                  navigate(href);
                }}
              />
            )}
          </div>
        </OverlayRootProvider>
      </div>
    </div>,
    document.body,
  );
}
