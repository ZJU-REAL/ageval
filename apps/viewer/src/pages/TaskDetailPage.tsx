import { useEffect, useMemo, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";

import { BreadcrumbNav } from "@ageval/shared/components/breadcrumb";
import { CommandStrip } from "@ageval/shared/components/command-strip";
import { LoadingState } from "@ageval/shared/components/empty-state";
import { Shell } from "@/components/layout";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@ageval/shared/components/ui/table";
import { fetchJobTask, setDatasetQuery, type Job, type TaskRow, type Trial } from "@/lib/api";
import { TruncateTip } from "@ageval/shared/components/hover-tip";
import { ModelLabel } from "@ageval/shared/components/model-label";
import { useDocumentTitle } from "@/lib/document-title";
import { jobPath, jobsHome, trialPath } from "@/lib/routes";
import { ErrorInfo } from "@ageval/shared/components/trial/error-info";
import { ReasonSelect } from "@ageval/shared/components/reason-select";
import { distinctReasons, reasonText } from "@ageval/shared/lib/reason";
import { cn, formatDate, formatScore } from "@ageval/shared/lib/utils";

export function TaskDetailPage() {
  const { datasetKey = "", jobId = "", taskId = "" } = useParams();
  setDatasetQuery(datasetKey);
  const navigate = useNavigate();
  useDocumentTitle(taskId || "Task");
  const [job, setJob] = useState<Job | null>(null);
  const [task, setTask] = useState<TaskRow | null>(null);
  const [trials, setTrials] = useState<Trial[]>([]);
  const [runCommand, setRunCommand] = useState<string>("");
  const [meta, setMeta] = useState({
    agent: "",
    model: "",
    dataset: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reason, setReason] = useState("all");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchJobTask(jobId, taskId)
      .then((data) => {
        if (cancelled) return;
        setJob(data.job);
        setTask(data.task);
        setTrials(data.trials || []);
        setRunCommand(data.run_command || "");
        setMeta({
          agent: data.agent_label || data.job.agent_label || "",
          model: data.model_label || data.job.model_label || "",
          dataset: data.dataset || data.job.source || "",
        });
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
  }, [datasetKey, jobId, taskId]);

  const reasons = useMemo(() => distinctReasons(trials, reasonText), [trials]);
  const visibleTrials = useMemo(
    () => (reason === "all" ? trials : trials.filter((row) => reasonText(row) === reason)),
    [trials, reason],
  );

  if (!loading && !error && trials.length === 1) {
    const rid = trials[0].run_id || trials[0].trial_id || task?.run_id || "";
    if (rid) {
      return <Navigate to={trialPath(datasetKey, jobId, taskId, rid)} replace />;
    }
  }

  return (
    <Shell>
      <div className="space-y-5">
        <BreadcrumbNav
          items={[
            { label: "Jobs", href: jobsHome(datasetKey) },
            { label: jobId, href: jobPath(datasetKey, jobId) },
            { label: taskId, href: null },
          ]}
        />

        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-ink">{taskId}</h1>
            <p className="text-xs text-mute mt-1 flex flex-wrap items-center gap-x-1.5">
              {meta.agent ? <span>{meta.agent}</span> : null}
              {meta.model ? (
                <>
                  {meta.agent ? <span aria-hidden>/</span> : null}
                  <ModelLabel
                    value={meta.model}
                    effort={job?.reasoning_effort}
                  />
                </>
              ) : null}
              {meta.dataset ? (
                <>
                  {meta.agent || meta.model ? <span aria-hidden>/</span> : null}
                  <span>{meta.dataset}</span>
                </>
              ) : null}
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-3">
            <ReasonSelect value={reason} reasons={reasons} onChange={setReason} />
            <p className="text-xs text-mute hidden md:block">
              j k navigate · Enter open · Esc go back
            </p>
          </div>
        </div>

        {runCommand ? <CommandStrip command={runCommand} /> : null}

        {loading && <LoadingState label="Loading trial details" />}
        {error && <p className="text-sm text-error">{error}</p>}

        {!loading && !error && (
          <div className="blob-panel overflow-x-auto">
            <Table
              wrapClassName="overflow-visible"
              className="w-max min-w-full table-fixed border-separate border-spacing-0"
            >
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-[16rem] max-w-[16rem]">Trial</TableHead>
                  <TableHead className="w-[8rem]">Reward</TableHead>
                  <TableHead className="w-[8rem]">Duration</TableHead>
                  <TableHead className="w-[11rem]">Started</TableHead>
                  <TableHead className="w-[16rem] max-w-[16rem]">Run id</TableHead>
                  <TableHead className="w-[8rem]">Status</TableHead>
                  <TableHead className="w-[16rem] max-w-[16rem]">Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleTrials.map((tr) => {
                  const bad =
                    (tr.status || "").toUpperCase() === "ERROR" ||
                    (tr.status || "").toUpperCase() === "FAIL";
                  const rid = tr.run_id || tr.trial_id || task?.run_id || "";
                  // Open when we have a run id (detail page handles missing evidence)
                  const openable = Boolean(rid);
                  return (
                    <TableRow
                      key={tr.trial_id || rid}
                      className={cn(openable && "cursor-pointer")}
                      onClick={(e) => {
                        if (!openable) return;
                        const el = e.target as HTMLElement;
                        if (el.closest("button, [role='button']")) return;
                        navigate(trialPath(datasetKey, jobId, taskId, rid));
                      }}
                      onKeyDown={(e) => {
                        if (!openable) return;
                        const el = e.target as HTMLElement;
                        if (el.closest("button, [role='button']")) return;
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          navigate(trialPath(datasetKey, jobId, taskId, rid));
                        }
                      }}
                      tabIndex={openable ? 0 : undefined}
                      role={openable ? "link" : undefined}
                    >
                      <TableCell className="max-w-[16rem] font-medium">
                        <TruncateTip
                          className="block w-full max-w-[16rem]"
                          text={tr.trial_id}
                          copyable
                        />
                        {tr.has_evidence ? (
                          <span className="ml-2 text-[11px] text-mute font-sans">
                            evidence
                          </span>
                        ) : null}
                      </TableCell>
                      <TableCell
                        className={
                          bad ? "text-error tabular" : "tabular"
                        }
                      >
                        {formatScore(tr.reward ?? tr.score)}
                      </TableCell>
                      <TableCell className="text-mute">
                        {tr.duration || "-"}
                      </TableCell>
                      <TableCell className="tabular text-body">
                        {formatDate(tr.started || job?.started)}
                      </TableCell>
                      <TableCell className="max-w-[16rem] text-mute">
                        <TruncateTip
                          className="block w-full max-w-[16rem]"
                          text={tr.run_id || task?.run_id || ""}
                          copyable
                        />
                      </TableCell>
                      <TableCell className={bad ? "text-error" : "text-body"}>
                        <span className="inline-flex items-center gap-1.5">
                          {tr.status || "-"}
                          {(tr.status || "").toUpperCase() === "ERROR" ? (
                            <ErrorInfo error={tr.error} />
                          ) : null}
                        </span>
                      </TableCell>
                      <TableCell
                        className={
                          reasonText(tr) && (tr.status || "").toUpperCase() === "ERROR"
                            ? "max-w-[16rem] text-error"
                            : "max-w-[16rem] text-body"
                        }
                      >
                        <TruncateTip
                          className="block w-full max-w-[16rem]"
                          text={reasonText(tr) || "-"}
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </Shell>
  );
}
