import { ListChecks, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { CommandStrip } from "@ageval/shared/components/command-strip";
import { DeleteJobDialog } from "@/components/delete-job-dialog";
import { EmptyState, LoadingState } from "@ageval/shared/components/empty-state";
import { JobCheck } from "@/components/job-check";
import { JobNoteDialog } from "@/components/job-note-dialog";
import { JobRowActions } from "@/components/job-row-actions";
import { Shell } from "@/components/layout";
import { PageHead } from "@/components/page-head";
import {
  compareValues,
  nextSort,
  SortableHead,
  type SortDir,
} from "@ageval/shared/components/sortable-head";
import { Input } from "@ageval/shared/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ageval/shared/components/ui/select";
import { Button } from "@ageval/shared/components/ui/button";
import { TableColumnPicker } from "@ageval/shared/components/ui/table-column-picker";
import { useTableColumns } from "@ageval/shared/hooks/use-table-columns";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@ageval/shared/components/ui/table";
import { fetchJobs, setDatasetQuery, type Job } from "@/lib/api";
import {
  emptyJobPref,
  loadJobPrefs,
  saveJobPrefs,
  type JobPref,
} from "@/lib/job-prefs";
import { jobDisplayName, jobHref, jobsHome } from "@/lib/routes";
import { useReadySession } from "@/lib/session";
import { TruncateTip } from "@ageval/shared/components/hover-tip";
import { HarnessLabel } from "@ageval/shared/components/harness-label";
import { ModelLabel } from "@ageval/shared/components/model-label";
import { formatDate, formatModelLabel, formatScore, formatTrials } from "@ageval/shared/lib/utils";

type SortKey =
  | "job_name"
  | "agent_label"
  | "model_label"
  | "result"
  | "environment"
  | "started"
  | "trials_total";

const JOB_OPTIONAL_COLUMNS = [
  { id: "environment", label: "Environment" },
  { id: "started", label: "Started" },
  { id: "duration", label: "Duration" },
  { id: "trials_total", label: "Trials" },
] as const;
const JOB_OPTIONAL_IDS = JOB_OPTIONAL_COLUMNS.map((col) => col.id);
const JOB_OPTIONAL_DEFAULT: typeof JOB_OPTIONAL_IDS = [
  "environment",
  "started",
];

export function JobsPage() {
  const navigate = useNavigate();
  const { datasetKey: routeKey = "" } = useParams();
  const session = useReadySession();
  const datasetKey = session.datasets.some((item) => item.key === routeKey) ? routeKey : "";
  setDatasetQuery(datasetKey || null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [datasetId, setDatasetId] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("all");
  const [source, setSource] = useState("all");
  const [agent, setAgent] = useState("all");
  const [model, setModel] = useState("all");
  const [sortKey, setSortKey] = useState<string | null>("started");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [pendingDelete, setPendingDelete] = useState<Job[] | null>(null);
  const [pendingNote, setPendingNote] = useState<Job | null>(null);
  const [prefs, setPrefs] = useState<Record<string, JobPref>>({});
  const [selected, setSelected] = useState<Record<string, true>>({});
  const [reloadToken, setReloadToken] = useState(0);
  const [columns, setColumns] = useTableColumns(
    "ageval.viewer.columns.jobs",
    JOB_OPTIONAL_IDS,
    JOB_OPTIONAL_DEFAULT,
  );

  useEffect(() => {
    if (!datasetKey) {
      setJobs([]);
      setDatasetId("");
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchJobs()
      .then((data) => {
        if (cancelled) return;
        setJobs(data.items || []);
        setDatasetId(data.dataset_id || "");
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
  }, [datasetKey, reloadToken]);

  useEffect(() => {
    setPrefs(loadJobPrefs(datasetId));
  }, [datasetId]);

  const writePrefs = useCallback(
    (next: Record<string, JobPref>) => {
      setPrefs(next);
      saveJobPrefs(datasetId, next);
    },
    [datasetId],
  );

  function prefFor(jobId: string): JobPref {
    return prefs[jobId] || emptyJobPref();
  }

  function patchPref(jobId: string, patch: Partial<JobPref>) {
    const merged: JobPref = { ...prefFor(jobId), ...patch };
    const next = { ...prefs };
    if (!merged.pinned && !merged.note.trim()) {
      delete next[jobId];
    } else {
      next[jobId] = merged;
    }
    writePrefs(next);
  }

  const kinds = useMemo(
    () =>
      Array.from(
        new Set(
          jobs.map((j) => (j.source_kind === "single" ? "single" : "suite")),
        ),
      ).sort(),
    [jobs],
  );
  const sources = useMemo(
    () =>
      Array.from(
        new Set(
          jobs
            .filter((j) => j.source_kind === "single")
            .map((j) => j.task_id || "")
            .filter(Boolean),
        ),
      ).sort(),
    [jobs],
  );
  const showSourceFilter = kind !== "suite" && sources.length > 0;
  const agents = useMemo(
    () =>
      Array.from(new Set(jobs.map((j) => j.agent_label).filter(Boolean) as string[])).sort(),
    [jobs],
  );
  const models = useMemo(
    () =>
      Array.from(new Set(jobs.map((j) => j.model_label).filter(Boolean) as string[])).sort(),
    [jobs],
  );

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    let rows = jobs.filter((j) => {
      const rowKind = j.source_kind === "single" ? "single" : "suite";
      if (kind !== "all" && rowKind !== kind) return false;
      if (showSourceFilter && source !== "all" && (j.task_id || "") !== source) {
        return false;
      }
      if (agent !== "all" && (j.agent_label || "") !== agent) return false;
      if (model !== "all" && (j.model_label || "") !== model) return false;
      if (!query) return true;
      const hay = [
        jobDisplayName(j),
        j.job_name,
        j.source,
        j.source_kind,
        j.dataset_ref,
        j.job_id,
        j.task_id,
        j.agent_label,
        j.model_label,
        j.environment,
        prefs[j.job_id]?.note,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(query);
    });
    rows = [...rows].sort((a, b) => {
      const pin = Number(Boolean(prefs[b.job_id]?.pinned)) - Number(Boolean(prefs[a.job_id]?.pinned));
      if (pin !== 0) return pin;
      if (!sortKey || !sortDir) return 0;
      const key = sortKey as SortKey;
      const av =
        key === "result"
          ? (a.mean_score ?? a.result)
          : key === "trials_total"
            ? a.trials_total
            : key === "job_name"
              ? jobDisplayName(a)
              : a[key];
      const bv =
        key === "result"
          ? (b.mean_score ?? b.result)
          : key === "trials_total"
            ? b.trials_total
            : key === "job_name"
              ? jobDisplayName(b)
              : b[key];
      return compareValues(av, bv, sortDir);
    });
    return rows;
  }, [jobs, q, kind, source, showSourceFilter, agent, model, sortKey, sortDir, prefs]);

  const selectedVisible = filtered.filter((j) => selected[j.job_id]);
  const selectedCount = selectedVisible.length;
  const allVisibleSelected =
    filtered.length > 0 && selectedVisible.length === filtered.length;
  const someVisibleSelected = selectedVisible.length > 0 && !allVisibleSelected;

  function toggleOne(jobId: string, next: boolean) {
    setSelected((prev) => {
      const copy = { ...prev };
      if (next) copy[jobId] = true;
      else delete copy[jobId];
      return copy;
    });
  }

  function toggleAllVisible(next: boolean) {
    setSelected((prev) => {
      const copy = { ...prev };
      for (const job of filtered) {
        if (next) copy[job.job_id] = true;
        else delete copy[job.job_id];
      }
      return copy;
    });
  }

  useEffect(() => {
    if (
      sortKey === "environment" ||
      sortKey === "started" ||
      sortKey === "trials_total"
    ) {
      if (!columns.includes(sortKey)) {
        setSortKey(columns.includes("started") ? "started" : "job_name");
        setSortDir("desc");
      }
    }
  }, [columns, sortKey]);

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

  const duplicateLabels = useMemo(() => {
    const seen = new Set<string>();
    const dup = new Set<string>();
    for (const item of session.datasets) {
      if (seen.has(item.label)) dup.add(item.label);
      seen.add(item.label);
    }
    return dup;
  }, [session.datasets]);

  return (
    <Shell>
      <div className="flex flex-1 flex-col gap-4">
        <PageHead title="Jobs" />
        <div className="flex items-center gap-2">
          <div className="relative min-w-0 flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-mute" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search for jobs..."
              className="pl-9 h-10 focus-visible:border-hairline"
              aria-label="Search jobs"
            />
          </div>
          <TableColumnPicker
            options={JOB_OPTIONAL_COLUMNS}
            value={columns}
            onChange={setColumns}
            ariaLabel="Optional job columns"
          />
        </div>

        <div className="flex flex-wrap gap-2 items-center">
          {session.datasets.length > 0 ? (
            <Select
              value={datasetKey || undefined}
              onValueChange={(next) => navigate(jobsHome(next))}
            >
              <SelectTrigger aria-label="Dataset">
                <SelectValue placeholder="Dataset" />
              </SelectTrigger>
              <SelectContent>
                {session.datasets.map((item) => (
                  <SelectItem
                    key={item.key}
                    value={item.key}
                    mono={false}
                    trailing={duplicateLabels.has(item.label) ? item.key : undefined}
                  >
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null}
          <Select
            value={kind}
            onValueChange={(next) => {
              setKind(next);
              if (next === "suite") setSource("all");
            }}
          >
            <SelectTrigger aria-label="Filter kind">
              <SelectValue placeholder="All kinds" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All kinds</SelectItem>
              {kinds.map((k) => (
                <SelectItem key={k} value={k}>
                  {k === "single" ? "single" : "suite"}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {showSourceFilter ? (
            <Select value={source} onValueChange={setSource}>
              <SelectTrigger aria-label="Filter source">
                <SelectValue placeholder="All sources" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All sources</SelectItem>
                {sources.map((s) => (
                  <SelectItem key={s} value={s}>
                    {s}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null}
          <Select value={agent} onValueChange={setAgent}>
            <SelectTrigger aria-label="Filter harnesses">
              <SelectValue placeholder="All harnesses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All harnesses</SelectItem>
              {agents.map((a) => (
                <SelectItem key={a} value={a}>
                  {a}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={model} onValueChange={setModel}>
            <SelectTrigger aria-label="Filter models">
              <SelectValue placeholder="All models" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All models</SelectItem>
              {models.map((m) => (
                <SelectItem key={m} value={m}>
                  {formatModelLabel(m).text}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex-1" />
          {selectedCount > 0 ? (
            <Button
              type="button"
              variant="dangerOutline"
              size="sm"
              onClick={() => {
                const rows = filtered.filter((j) => selected[j.job_id]);
                if (rows.length) setPendingDelete(rows);
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete {selectedCount}
            </Button>
          ) : (
            <span className="text-xs text-mute">
              {filtered.length} job{filtered.length === 1 ? "" : "s"}
            </span>
          )}
        </div>

        {!datasetKey && !loading ? (
          <EmptyState
            icon={ListChecks}
            title={session.datasets.length === 0 ? "No datasets" : "Pick a dataset"}
            caption={
              session.datasets.length === 0
                ? "Jobs stay on one package."
                : "Choose a package to see its jobs."
            }
          />
        ) : loading ? (
          <LoadingState label="Loading jobs" />
        ) : error ? (
          <div className="blob-panel bg-canvas-soft p-4 text-sm">
            <p className="text-error font-medium">Could not load jobs</p>
            <p className="mt-1 text-xs text-body">{error}</p>
          </div>
        ) : jobs.length === 0 ? (
          <EmptyState
            icon={ListChecks}
            title="No jobs yet"
            action={<CommandStrip command="ageval run <dataset>" />}
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={ListChecks}
            title="No matches"
            action={
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setQ("");
                  setKind("all");
                  setSource("all");
                  setAgent("all");
                  setModel("all");
                }}
              >
                Clear search
              </Button>
            }
          />
        ) : (
          <div className="blob-panel overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-8 pr-0">
                  <JobCheck
                    checked={allVisibleSelected}
                    indeterminate={someVisibleSelected}
                    label="Select all jobs"
                    onChange={toggleAllVisible}
                  />
                </TableHead>
                <TableHead>{head("job_name", "Job Name")}</TableHead>
                <TableHead>Dataset</TableHead>
                <TableHead>{head("agent_label", "Harness")}</TableHead>
                <TableHead>{head("model_label", "Models")}</TableHead>
                <TableHead>{head("result", "Result")}</TableHead>
                {columns.includes("environment") ? (
                  <TableHead>{head("environment", "Environment")}</TableHead>
                ) : null}
                {columns.includes("started") ? (
                  <TableHead>{head("started", "Started")}</TableHead>
                ) : null}
                {columns.includes("duration") ? (
                  <TableHead>Duration</TableHead>
                ) : null}
                {columns.includes("trials_total") ? (
                  <TableHead>{head("trials_total", "Trials")}</TableHead>
                ) : null}
                <TableHead className="w-7 pl-0 pr-2">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((job) => (
                  <TableRow
                    key={job.job_id}
                    className="group cursor-pointer"
                    onClick={(e) => {
                      const el = e.target as HTMLElement;
                      if (
                        el.closest(
                          "input, button, [role='button'], [role='menu'], [role='menuitem']",
                        )
                      ) {
                        return;
                      }
                      navigate(jobHref(datasetKey, job));
                    }}
                    onKeyDown={(e) => {
                      const el = e.target as HTMLElement;
                      if (el.closest("input, button, [role='button']")) return;
                      if (e.key === "Enter") {
                        navigate(jobHref(datasetKey, job));
                      }
                    }}
                    tabIndex={0}
                    role="link"
                  >
                    <TableCell className="w-8 pr-0">
                      <JobCheck
                        checked={Boolean(selected[job.job_id])}
                        label={`Select ${jobDisplayName(job)}`}
                        onChange={(next) => toggleOne(job.job_id, next)}
                      />
                    </TableCell>
                    <TableCell className="font-medium max-w-[16rem]">
                      <TruncateTip text={jobDisplayName(job)} copyable />
                    </TableCell>
                    <TableCell className="text-body max-w-[16rem]">
                      <TruncateTip text={job.dataset_ref || ""} copyable />
                    </TableCell>
                    <TableCell className="max-w-[14rem]">
                      <HarnessLabel
                        value={job.agent_label}
                        className="block truncate"
                      />
                    </TableCell>
                    <TableCell className="max-w-[18rem]">
                      <ModelLabel
                        value={job.model_label}
                        effort={job.reasoning_effort}
                        className="truncate"
                      />
                    </TableCell>
                    <TableCell className="tabular">
                      {formatScore(job.mean_score ?? job.result)}
                    </TableCell>
                    {columns.includes("environment") ? (
                      <TableCell>{job.environment || "-"}</TableCell>
                    ) : null}
                    {columns.includes("started") ? (
                      <TableCell className="tabular text-body">
                        {formatDate(job.started)}
                      </TableCell>
                    ) : null}
                    {columns.includes("duration") ? (
                      <TableCell className="text-mute">
                        {job.duration || "-"}
                      </TableCell>
                    ) : null}
                    {columns.includes("trials_total") ? (
                      <TableCell className="tabular">
                        {formatTrials(job.trials_done, job.trials_total)}
                      </TableCell>
                    ) : null}
                    <TableCell className="w-7 pl-0 pr-2 text-right">
                      <JobRowActions
                        job={job}
                        pref={prefFor(job.job_id)}
                        onPin={() =>
                          patchPref(job.job_id, {
                            pinned: !prefFor(job.job_id).pinned,
                          })
                        }
                        onNote={() => setPendingNote(job)}
                        onDelete={() => setPendingDelete([job])}
                      />
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
          </div>
        )}
      </div>
      {pendingNote ? (
        <JobNoteDialog
          job={pendingNote}
          initialNote={prefFor(pendingNote.job_id).note}
          onClose={() => setPendingNote(null)}
          onSave={(note) => {
            patchPref(pendingNote.job_id, { note });
            setPendingNote(null);
          }}
        />
      ) : null}
      {pendingDelete ? (
        <DeleteJobDialog
          jobs={pendingDelete}
          onClose={() => setPendingDelete(null)}
          onDeleted={(jobIds) => {
            const nextPrefs = { ...prefs };
            const nextSelected = { ...selected };
            for (const id of jobIds) {
              delete nextPrefs[id];
              delete nextSelected[id];
            }
            writePrefs(nextPrefs);
            setSelected(nextSelected);
            setPendingDelete(null);
            setReloadToken((n) => n + 1);
          }}
        />
      ) : null}
    </Shell>
  );
}
