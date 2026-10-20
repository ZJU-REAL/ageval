import type { MouseEvent as ReactMouseEvent, KeyboardEvent as ReactKeyboardEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";

import { BreadcrumbNav } from "@ageval/shared/components/breadcrumb";
import { LoadingState } from "@ageval/shared/components/empty-state";
import { Shell } from "@/components/layout";
import { SuitePaceBoard } from "@/components/suite-pace-board";
import { SnapshotShareControl } from "@/components/snapshot-share";
import {
  nextSort,
  SortableHead,
  type SortDir,
} from "@ageval/shared/components/sortable-head";
import { Button } from "@ageval/shared/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@ageval/shared/components/ui/table";
import { FileSplitPanel } from "@ageval/shared/components/trial/file-split-panel";
import {
  fetchJob,
  fetchJobOverlayFile,
  fetchJobOverlays,
  setDatasetQuery,
  type Job,
  type JobPaceTask,
  type JobTaskPage,
  type TaskRow,
  type TreeEntry,
} from "@/lib/api";
import { jobsHome, taskHref, taskRunIds } from "@/lib/routes";
import { jobStillRunning, SUITE_POLL_MS } from "@/lib/suite-pace";
import { TruncateTip } from "@ageval/shared/components/hover-tip";
import { HarnessLabel } from "@ageval/shared/components/harness-label";
import { ModelLabel } from "@ageval/shared/components/model-label";
import { useDocumentTitle } from "@/lib/document-title";
import { ReasonSelect } from "@ageval/shared/components/reason-select";
import { reasonText } from "@ageval/shared/lib/reason";
import { formatScore } from "@ageval/shared/lib/utils";

const TASK_PAGE_SIZE = 50;

export function JobDetailPage() {
  const { datasetKey = "", jobId = "" } = useParams();
  setDatasetQuery(datasetKey);
  const navigate = useNavigate();
  useDocumentTitle(jobId || "Job");
  const [job, setJob] = useState<Job | null>(null);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [pace, setPace] = useState<JobPaceTask[]>([]);
  const [reasons, setReasons] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [pageSize, setPageSize] = useState(TASK_PAGE_SIZE);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [sortKey, setSortKey] = useState<string | null>("task_id");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [reason, setReason] = useState("all");
  const [page, setPage] = useState(1);
  const scopeKey = `${datasetKey}\0${jobId}`;
  const [scope, setScope] = useState(scopeKey);
  if (scope !== scopeKey) {
    setScope(scopeKey);
    setJob(null);
    setTasks([]);
    setPace([]);
    setReasons([]);
    setTotal(0);
    setError(null);
    setReady(false);
    setSortKey("task_id");
    setSortDir("asc");
    setReason("all");
    setPage(1);
  }
  const [overlayTree, setOverlayTree] = useState<TreeEntry[]>([]);
  const [overlayPath, setOverlayPath] = useState<string | null>(null);
  const [overlayContent, setOverlayContent] = useState<string | null>(null);
  const [overlayTreeLoading, setOverlayTreeLoading] = useState(false);
  const [overlayFileLoading, setOverlayFileLoading] = useState(false);
  const [overlayNote, setOverlayNote] = useState<string | null>(null);

  const taskPage = useMemo<JobTaskPage>(
    () => ({
      page,
      pageSize: TASK_PAGE_SIZE,
      reason,
      sort: sortKey,
      dir: sortDir,
    }),
    [page, reason, sortKey, sortDir],
  );

  const applyJob = useCallback((data: Awaited<ReturnType<typeof fetchJob>>) => {
    setJob(data.job);
    setTasks(data.tasks || []);
    setPace(data.pace || []);
    setReasons(data.reasons || []);
    setTotal(data.total ?? data.task_count ?? (data.tasks || []).length);
    setPageSize(data.page_size || TASK_PAGE_SIZE);
    const reported = data.page;
    if (typeof reported === "number") {
      setPage((current) => (reported !== current ? reported : current));
    }
    setError(null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchJob(jobId, taskPage)
      .then((data) => {
        if (!cancelled) applyJob(data);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetKey, jobId, taskPage, applyJob]);

  const chartTasks = pace.length > 0 ? pace : tasks;
  const suiteOpen =
    job?.source_kind !== "single" &&
    (jobStillRunning(job ?? {}) ||
      chartTasks.some((task) => {
        const status = (task.status || "").toUpperCase();
        return status === "PENDING" || status === "RUNNING" || status === "CANCELLING";
      }));

  useEffect(() => {
    if (!ready || !suiteOpen) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      fetchJob(jobId, taskPage)
        .then((data) => {
          if (!cancelled) applyJob(data);
        })
        .catch((e: Error) => {
          if (!cancelled) setError(e.message);
        });
    }, SUITE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [datasetKey, jobId, ready, suiteOpen, taskPage, applyJob]);

  const overlayPrefixes = job?.overlays ?? [];

  useEffect(() => {
    if (!overlayPrefixes.length) {
      setOverlayTree([]);
      setOverlayPath(null);
      setOverlayContent(null);
      setOverlayNote(null);
      return;
    }
    let cancelled = false;
    setOverlayTreeLoading(true);
    fetchJobOverlays(jobId)
      .then((data) => {
        if (cancelled) return;
        const items = data.items || [];
        setOverlayTree(items);
        setOverlayPath(items[0]?.path ?? null);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setOverlayTree([]);
          setOverlayNote(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) setOverlayTreeLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetKey, jobId, overlayPrefixes.length]);

  useEffect(() => {
    if (!overlayPath) {
      setOverlayContent(null);
      return;
    }
    let cancelled = false;
    setOverlayFileLoading(true);
    fetchJobOverlayFile(jobId, overlayPath)
      .then((data) => {
        if (cancelled) return;
        setOverlayContent(data.content);
        setOverlayNote(null);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setOverlayContent(null);
          setOverlayNote(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) setOverlayFileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetKey, jobId, overlayPath]);

  const reasonOptions =
    reason !== "all" && !reasons.includes(reason) ? [...reasons, reason] : reasons;

  function onSort(key: string) {
    const next = nextSort(sortKey, sortDir, key);
    setSortKey(next.dir ? next.key : null);
    setSortDir(next.dir);
    setPage(1);
  }

  function head(key: string, label: string) {
    return (
      <SortableHead
        label={label}
        active={sortKey === key}
        dir={sortKey === key ? sortDir : null}
        onClick={() => onSort(key)}
      />
    );
  }

  if (ready && !error && job?.source_kind === "single" && tasks.length === 1) {
    return <Navigate to={taskHref(datasetKey, jobId, tasks[0])} replace />;
  }

  return (
    <Shell>
      <div className="space-y-4">
        <BreadcrumbNav
          items={[
            { label: "Jobs", href: jobsHome(datasetKey) },
            { label: jobId, href: null },
          ]}
        />

        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">{jobId}</h1>
          {job && (
            <p className="text-xs text-mute mt-1 flex flex-wrap items-center gap-x-1.5">
              {job.agent_label ? <span>{job.agent_label}</span> : null}
              {job.model_label ? (
                <>
                  {job.agent_label ? <span aria-hidden>/</span> : null}
                  <ModelLabel
                    value={job.model_label}
                    effort={job.reasoning_effort}
                  />
                </>
              ) : null}
              {job.dataset_ref ? (
                <>
                  {job.agent_label || job.model_label ? (
                    <span aria-hidden>/</span>
                  ) : null}
                  <span>{job.dataset_ref}</span>
                </>
              ) : null}
            </p>
          )}
          </div>
          <div className="flex flex-wrap items-start justify-end gap-2">
            {job && job.source_kind !== "single" ? (
              <SnapshotShareControl jobId={jobId} />
            ) : null}
            <ReasonSelect
              value={reason}
              reasons={reasonOptions}
              onChange={(next) => {
                setReason(next);
                setPage(1);
              }}
            />
          </div>
        </div>

        {job && job.source_kind !== "single" && ready ? (
          <SuitePaceBoard
            tasks={chartTasks}
            onOpenTask={(taskId) => {
              const task = chartTasks.find((row) => row.task_id === taskId);
              if (!task) return;
              const status = (task.status || "").toUpperCase();
              if (status === "PENDING" || status === "RUNNING") return;
              navigate(taskHref(datasetKey, jobId, task));
            }}
          />
        ) : null}

        {!ready ? (
          <LoadingState label="Loading tasks" />
        ) : (
        <>
        <div className="blob-panel overflow-x-auto">
          <Table
            wrapClassName="overflow-visible"
            className="w-max min-w-full table-fixed border-separate border-spacing-0"
          >
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-[16rem] max-w-[16rem]">
                  {head("task_id", "Task")}
                </TableHead>
                <TableHead className="w-[12rem] max-w-[12rem]">
                  {head("agent_label", "Harness")}
                </TableHead>
                <TableHead className="w-[16rem] max-w-[16rem]">
                  {head("model_label", "Model")}
                </TableHead>
                <TableHead className="w-[8rem]">{head("score", "Avg Reward")}</TableHead>
                <TableHead className="w-[6rem]">Trials</TableHead>
                <TableHead className="w-[6rem]">Errors</TableHead>
                <TableHead className="w-[8rem]">Avg Duration</TableHead>
                <TableHead className="w-[16rem] max-w-[16rem]">Reason</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {error && (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-error py-10">
                    {error}
                  </TableCell>
                </TableRow>
              )}
              {!error && tasks.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="py-10 text-center text-mute">
                    No matches
                  </TableCell>
                </TableRow>
              ) : null}
              {!error &&
                tasks.map((t) => {
                  const statusUpper = (t.status || "").toUpperCase();
                  // Planned-but-unrun (and still-running) tasks have no
                  // attempt yet: placeholder rows, muted, navigate nowhere.
                  const isPlaceholder =
                    statusUpper === "PENDING" || statusUpper === "RUNNING";
                  const isErr = statusUpper === "ERROR" || Boolean(t.error);
                  const href = taskHref(datasetKey, jobId, t);
                  const trialCount = t.n ?? taskRunIds(t).length;
                  const navProps = isPlaceholder
                    ? {}
                    : {
                        tabIndex: 0,
                        role: "link" as const,
                        onClick: (e: ReactMouseEvent<HTMLTableRowElement>) => {
                          const el = e.target as HTMLElement;
                          if (el.closest("button, [role='button']")) return;
                          navigate(href);
                        },
                        onKeyDown: (e: ReactKeyboardEvent<HTMLTableRowElement>) => {
                          const el = e.target as HTMLElement;
                          if (el.closest("button, [role='button']")) return;
                          if (e.key === "Enter") {
                            navigate(href);
                          }
                        },
                      };
                  return (
                    <TableRow
                      key={t.task_id}
                      className={isPlaceholder ? "text-mute" : "cursor-pointer"}
                      aria-disabled={isPlaceholder || undefined}
                      {...navProps}
                    >
                      <TableCell className="max-w-[16rem] font-medium">
                        <TruncateTip
                          className="block w-full max-w-[16rem]"
                          text={t.task_id}
                          copyable
                        />
                      </TableCell>
                      <TableCell className="max-w-[12rem]">
                        <HarnessLabel
                          className="max-w-full"
                          value={isPlaceholder ? null : t.agent_label || job?.agent_label}
                        />
                      </TableCell>
                      <TableCell className="max-w-[16rem]">
                        <ModelLabel
                          className="max-w-full"
                          value={isPlaceholder ? null : t.model_label || job?.model_label}
                          effort={
                            isPlaceholder ? null : t.reasoning_effort || job?.reasoning_effort
                          }
                        />
                      </TableCell>
                      <TableCell className="tabular">
                        {isPlaceholder ? "-" : formatScore(t.score)}
                      </TableCell>
                      <TableCell className="tabular">
                        {isPlaceholder ? "-" : trialCount || 1}
                      </TableCell>
                      <TableCell className="tabular">
                        {isPlaceholder ? "-" : isErr || statusUpper === "ERROR" ? 1 : 0}
                      </TableCell>
                      <TableCell className="text-mute">
                        {isPlaceholder ? "-" : t.duration || "-"}
                      </TableCell>
                      <TableCell
                        className={
                          isPlaceholder
                            ? "max-w-[16rem] text-mute"
                            : reasonText(t) && statusUpper === "ERROR"
                              ? "max-w-[16rem] text-error"
                              : "max-w-[16rem] text-body"
                        }
                      >
                        <TruncateTip
                          className="block w-full max-w-[16rem]"
                          text={
                            isPlaceholder
                              ? statusUpper === "RUNNING"
                                ? "RUNNING"
                                : "PENDING"
                              : reasonText(t) || "-"
                          }
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
            </TableBody>
          </Table>
        </div>
        {total > pageSize ? (
          <div className="flex items-center justify-end gap-2">
            <span className="text-sm tabular-nums text-body">
              {total === 0 ? 0 : (page - 1) * pageSize + 1}-{Math.min(page * pageSize, total)}
              <span className="text-mute"> of {total}</span>
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              Previous
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={page * pageSize >= total}
              onClick={() => setPage((current) => current + 1)}
            >
              Next
            </Button>
          </div>
        ) : null}
        </>
        )}

        {overlayPrefixes.length ? (
          <section className="space-y-2">
            <h2 className="text-sm font-medium text-ink">Published files</h2>
            <p className="text-xs text-mute">
              Declared <code className="font-mono">overlays:</code> from this
              job binding. Files are read from the opened Dataset root.
            </p>
            <div className="blob-panel overflow-hidden">
              <FileSplitPanel
                tree={overlayTree}
                treeLoading={overlayTreeLoading}
                selectedPath={overlayPath}
                onSelect={setOverlayPath}
                fileContent={overlayContent}
                fileLoading={overlayFileLoading}
                fileNote={overlayNote}
              />
            </div>
          </section>
        ) : null}
      </div>
    </Shell>
  );
}
