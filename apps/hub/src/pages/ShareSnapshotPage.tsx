import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { LoadingState } from "@ageval/shared/components/empty-state";
import { HarnessLabel } from "@ageval/shared/components/harness-label";
import { ModelLabel } from "@ageval/shared/components/model-label";
import { ScoreRing } from "@ageval/shared/components/score-ring";
import { UnderlineTabs } from "@ageval/shared/components/underline-tabs";
import { formatScore, reasoningEffortFromOverlay } from "@ageval/shared/lib/utils";

import { CatalogHead } from "@/components/page-head";
import { CodeFence } from "@/components/code-fence";
import { shortSuiteId } from "@/components/suite-inspector";
import { ScrollTable } from "@/components/scroll-table";
import { Input } from "@ageval/shared/components/ui/input";
import {
  environmentFromOverlay,
  getSnapshotShare,
  RegistryHttpError,
  type SnapshotShare,
} from "@/lib/api";
import { harnessHref, modelCatalogHref } from "@/lib/links";

type ShareTab = "jobs" | "profiles";

/**
 * Anonymous read of one snapshot. No catalog import, visibility, or listing.
 */
export function ShareSnapshotPage() {
  const { token: rawToken = "" } = useParams();
  const token = decodeURIComponent(rawToken);
  const navigate = useNavigate();
  const [share, setShare] = useState<SnapshotShare | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<ShareTab>("jobs");
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!token) {
      setError("missing snapshot");
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getSnapshotShare(token)
      .then((row) => {
        if (!cancelled) setShare(row);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setShare(null);
        if (err instanceof RegistryHttpError) {
          setError(err.status === 404 ? "This snapshot link is not available." : err.message);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const rows = useMemo(() => {
    const out: Array<{
      key: string;
      taskId: string;
      runId: string | null;
      status: string | null;
      score: number | null;
      open: boolean;
    }> = [];
    for (const ref of share?.task_refs || []) {
      const taskId = (ref.task_id || "").trim();
      if (!taskId) continue;
      const runId = (ref.run_id || "").trim() || null;
      out.push({
        key: `${taskId}:${runId || "none"}`,
        taskId,
        runId,
        status: ref.status ?? null,
        score: ref.score ?? null,
        open: Boolean(runId && ref.has_attempt_content),
      });
    }
    return out;
  }, [share]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((row) =>
      [row.taskId, row.status || "", row.runId || ""].join(" ").toLowerCase().includes(q),
    );
  }, [query, rows]);

  const datasetId = share?.dataset_id || "Snapshot";
  const overlayText = share?.job_overlay
    ? JSON.stringify(share.job_overlay, null, 2)
    : "";
  const pass =
    share?.pass_rate == null ? "—" : `${(Number(share.pass_rate) * 100).toFixed(1)}%`;

  return (
    <>
      <CatalogHead
        title="Snapshot"
        crumbs={
          share
            ? [
                { label: datasetId, href: null },
                { label: share.suite_run_id, href: null },
              ]
            : [{ label: token || "Snapshot", href: null }]
        }
      />
      <div className="space-y-5">
        {loading ? <LoadingState label="Loading snapshot" /> : null}
        {error ? <p className="text-sm text-error font-mono">{error}</p> : null}
        {!loading && !error && share ? (
          <>
            <div className="space-y-1">
              <h1 className="truncate font-mono text-2xl font-semibold tracking-tight text-ink">
                {share.suite_run_id}
              </h1>
              <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink">
                <HarnessLabel
                  value={share.agent_label || ""}
                  to={harnessHref(share.agent_label)}
                  empty="—"
                />
                <span className="text-mute" aria-hidden>
                  ·
                </span>
                <ModelLabel
                  value={share.model_label || ""}
                  effort={reasoningEffortFromOverlay(share.job_overlay)}
                  to={modelCatalogHref(share.model_label)}
                />
                {environmentFromOverlay(share.job_overlay) ? (
                  <>
                    <span className="text-mute" aria-hidden>
                      ·
                    </span>
                    <span className="text-body">
                      {environmentFromOverlay(share.job_overlay)}
                    </span>
                  </>
                ) : null}
              </div>
              <p className="text-xs text-mute">
                <span className="tabular-nums text-ink">{pass}</span>
                {" · mean "}
                <span className="tabular-nums text-ink">
                  {formatScore(share.mean_score)}
                </span>
                {" · "}
                <span className="font-mono">{shortSuiteId(share.suite_run_id)}</span>
              </p>
              <p className="text-sm text-body">
                Read-only snapshot. Opening this link does not publish the suite
                or list it on the leaderboard.
              </p>
            </div>
            <UnderlineTabs
              ariaLabel="Snapshot"
              items={[
                { id: "jobs", label: "Jobs" },
                { id: "profiles", label: "Profiles" },
              ]}
              value={tab}
              onChange={setTab}
            />
            {tab === "jobs" ? (
              rows.length === 0 ? (
                <p className="text-sm text-mute">No task results in this snapshot.</p>
              ) : (
                <div className="space-y-2">
                  <Input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search jobs…"
                    aria-label="Search jobs"
                    className="min-w-0 w-full max-w-sm focus-visible:border-hairline"
                  />
                  {filtered.length === 0 ? (
                    <p className="text-sm text-mute">No matching jobs</p>
                  ) : (
                    <ScrollTable
                      className="max-h-[min(70vh,40rem)]"
                      headers={["Task", "Status", "Score", "Attempt"]}
                      rows={filtered.map((row) => {
                        const href = row.open && row.runId
                          ? `/s/${encodeURIComponent(token)}/attempts/${encodeURIComponent(row.runId)}`
                          : null;
                        return {
                          key: row.key,
                          onClick: href ? () => navigate(href) : undefined,
                          muted: !href,
                          cells: [
                            <span key="task">{row.taskId}</span>,
                            row.status || "—",
                            <ScoreRing key="score" value={row.score}>
                              {formatScore(row.score)}
                            </ScoreRing>,
                            row.runId ? (
                              <span key="run" className="font-mono">
                                {shortSuiteId(row.runId)}
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
                  )}
                </div>
              )
            ) : overlayText ? (
              <CodeFence path="job_overlay.json" content={overlayText} />
            ) : (
              <p className="text-sm text-mute">No profiles in this snapshot.</p>
            )}
          </>
        ) : null}
      </div>
    </>
  );
}
