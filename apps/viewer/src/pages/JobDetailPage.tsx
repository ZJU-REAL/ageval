import type { MouseEvent as ReactMouseEvent, KeyboardEvent as ReactKeyboardEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";

import { BreadcrumbNav } from "@ageval/shared/components/breadcrumb";
import { LoadingState } from "@ageval/shared/components/empty-state";
import { Shell } from "@/components/layout";
import {
  compareValues,
  nextSort,
  SortableHead,
  type SortDir,
} from "@ageval/shared/components/sortable-head";
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
  type TaskRow,
  type TreeEntry,
} from "@/lib/api";
import { jobsHome, taskHref, taskRunIds } from "@/lib/routes";
import { AxisLabel } from "@ageval/shared/components/axis-label";
import { TruncateTip } from "@ageval/shared/components/hover-tip";
import { ModelLabel } from "@ageval/shared/components/model-label";
import { useDocumentTitle } from "@/lib/document-title";
import { formatError, formatScore } from "@ageval/shared/lib/utils";

type SortKey = "task_id" | "agent_label" | "model_label" | "score" | "status";

export function JobDetailPage() {
  const { datasetKey = "", jobId = "" } = useParams();
  setDatasetQuery(datasetKey);
  const navigate = useNavigate();
  useDocumentTitle(jobId || "Job");
  const [job, setJob] = useState<Job | null>(null);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<string | null>("task_id");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [overlayTree, setOverlayTree] = useState<TreeEntry[]>([]);
  const [overlayPath, setOverlayPath] = useState<string | null>(null);
  const [overlayContent, setOverlayContent] = useState<string | null>(null);
  const [overlayTreeLoading, setOverlayTreeLoading] = useState(false);
  const [overlayFileLoading, setOverlayFileLoading] = useState(false);
  const [overlayNote, setOverlayNote] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchJob(jobId)
      .then((data) => {
        if (cancelled) return;
        setJob(data.job);
        setTasks(data.tasks || []);
        setError(null);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetKey, jobId]);

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

  const rows = useMemo(() => {
    if (!sortKey || !sortDir) return tasks;
    const key = sortKey as SortKey;
    return [...tasks].sort((a, b) => compareValues(a[key], b[key], sortDir));
  }, [tasks, sortKey, sortDir]);

  function onSort(key: string) {
    const next = nextSort(sortKey, sortDir, key);
    setSortKey(next.dir ? next.key : null);
    setSortDir(next.dir);
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

  if (!loading && !error && job?.source_kind === "single" && tasks.length === 1) {
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

        {loading ? (
          <LoadingState label="Loading tasks" />
        ) : (
        <div className="blob-panel overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>{head("task_id", "Task")}</TableHead>
                <TableHead>{head("agent_label", "Harness")}</TableHead>
                <TableHead>{head("model_label", "Model")}</TableHead>
                <TableHead>Dataset</TableHead>
                <TableHead>{head("score", "Avg Reward")}</TableHead>
                <TableHead>Trials</TableHead>
                <TableHead>Errors</TableHead>
                <TableHead>Avg Duration</TableHead>
                <TableHead>{head("status", "Exception")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {error && (
                <TableRow>
                  <TableCell colSpan={9} className="text-center text-error py-10">
                    {error}
                  </TableCell>
                </TableRow>
              )}
              {!loading &&
                !error &&
                rows.map((t) => {
                  const statusUpper = (t.status || "").toUpperCase();
                  // Planned-but-unrun (and still-running) tasks have no
                  // attempt yet: placeholder rows, muted, navigate nowhere.
                  const isPlaceholder =
                    statusUpper === "PENDING" || statusUpper === "RUNNING";
                  const errText = formatError(t.error);
                  const isErr = statusUpper === "ERROR" || Boolean(errText);
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
                      <TableCell className="font-medium max-w-[12rem]">
                        <TruncateTip text={t.task_id} copyable />
                      </TableCell>
                      <TableCell className="max-w-[14rem]">
                        <AxisLabel
                          value={isPlaceholder ? null : t.agent_label || job?.agent_label}
                          className="block truncate"
                        />
                      </TableCell>
                      <TableCell className="max-w-[18rem]">
                        <ModelLabel
                          value={isPlaceholder ? null : t.model_label || job?.model_label}
                          effort={
                            isPlaceholder ? null : t.reasoning_effort || job?.reasoning_effort
                          }
                          className="truncate"
                        />
                      </TableCell>
                      <TableCell className="text-body">
                        {t.dataset || job?.dataset_ref || "-"}
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
                          !isPlaceholder && (isErr || statusUpper === "FAIL")
                            ? "text-error"
                            : "text-mute"
                        }
                      >
                        {isPlaceholder
                          ? statusUpper === "RUNNING"
                            ? "RUNNING"
                            : "PENDING"
                          : errText ||
                            (statusUpper === "ERROR"
                              ? "ERROR"
                              : statusUpper === "FAIL"
                                ? "FAIL"
                                : "-")}
                      </TableCell>
                    </TableRow>
                  );
                })}
            </TableBody>
          </Table>
        </div>
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
