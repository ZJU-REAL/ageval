import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { CatalogHead } from "@/components/page-head";
import { ListPager } from "@/components/list-pager";
import { UnderlineTabs } from "@/components/underline-tabs";
import { CommandStrip } from "@/components/command-strip";
import { FileSplitPanel } from "@/components/file-split-panel";
import { Markdown } from "@/components/markdown";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  SortableHead,
  sortRows,
  useTableSort,
} from "@/components/sortable-head";
import { TableColumnPicker } from "@/components/ui/table-column-picker";
import { useTableColumns } from "@/hooks/use-table-columns";
import { PillTabs } from "@/components/ui/pill-tabs";
import { VersionSwitcher } from "@/components/version-switcher";
import {
  decodeDatasetId,
  decodeFileContent,
  environmentFromOverlay,
  getPackageFile,
  hasSharedFiles,
  listAttempts,
  listPackageFiles,
  listPackageVersions,
  listSuites,
  pickPackageVersion,
  TASK_PAGE_SIZE,
  type FileItem,
  type PackageRelease,
  RegistryHttpError,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import {
  buildNestedTree,
  pathMatchesPrefixes,
  profileDocumentPaths,
  unionOverlayPrefixes,
  type TreeNode,
} from "@/lib/file-tree";
import { HarnessLabel } from "@/components/harness-label";
import { TruncateTip } from "@/components/hover-tip";
import { ModelLabel } from "@/components/model-label";
import {
  cn,
  displayLabelsFromOverlay,
  datasetRef,
  formatDate,
  formatScore,
  reasoningEffortFromOverlay,
} from "@/lib/utils";

type Tab = "readme" | "files" | "jobs";
type FilesScope = "local" | "shared" | "overlays";

const JOB_OPTIONAL_COLUMNS = [
  { id: "dataset", label: "Dataset" },
  { id: "environment", label: "Environment" },
  { id: "time", label: "Time" },
] as const;
const JOB_OPTIONAL_IDS = JOB_OPTIONAL_COLUMNS.map((col) => col.id);
const JOB_OPTIONAL_DEFAULT: typeof JOB_OPTIONAL_IDS = ["environment", "time"];

type TaskJobRow = {
  job_id: string;
  job_kind: "suite" | "attempt";
  status?: string | null;
  score?: number | null;
  agent_label?: string;
  model_label?: string;
  reasoning_effort?: string;
  environment?: string | null;
  created_at?: number | string;
  run_id?: string | null;
  has_attempt_content?: boolean;
  dataset_ref?: string | null;
};

function jobColumnValue(row: TaskJobRow, key: string): unknown {
  switch (key) {
    case "job_id":
      return row.job_id || "";
    case "dataset":
      return row.dataset_ref || "";
    case "status":
      return row.status || "";
    case "score":
      return row.score ?? null;
    case "agent_label":
      return row.agent_label || "";
    case "model_label":
      return row.model_label || "";
    case "environment":
      return row.environment || "";
    case "time": {
      return (
        Date.parse(String(row.created_at ?? "")) || Number(row.created_at) || 0
      );
    }
    default:
      return null;
  }
}

function compareTaskJobs(a: TaskJobRow, b: TaskJobRow): number {
  const left =
    Date.parse(String(a.created_at ?? "")) || Number(a.created_at) || 0;
  const right =
    Date.parse(String(b.created_at ?? "")) || Number(b.created_at) || 0;
  return right - left;
}

function FilesScopeSwitch({
  filesScope,
  onChange,
  localPresent,
  sharedPresent,
  overlaysPresent,
}: {
  filesScope: FilesScope;
  onChange: (next: FilesScope) => void;
  localPresent: boolean;
  sharedPresent: boolean;
  overlaysPresent: boolean;
}) {
  const items = [
    ...(localPresent ? ([{ id: "local" as const, label: "Local" }] as const) : []),
    ...(sharedPresent
      ? ([{ id: "shared" as const, label: "Shared" }] as const)
      : []),
    ...(overlaysPresent
      ? ([{ id: "overlays" as const, label: "Overlays" }] as const)
      : []),
  ];
  if (items.length < 2) return null;
  return (
    <PillTabs
      items={items}
      value={filesScope}
      onChange={onChange}
      ariaLabel="Files scope"
    />
  );
}

export function TaskDetailPage() {
  const { datasetId: rawId, taskId: rawTask } = useParams();
  const datasetId = decodeDatasetId(rawId || "");
  const taskId = decodeURIComponent(rawTask || "");
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  // Default tab: README (not Files)
  const tab = (search.get("tab") as Tab) || "readme";
  const requestedVersion = search.get("v");

  const [versions, setVersions] = useState<PackageRelease[]>([]);
  const [release, setRelease] = useState<PackageRelease | null>(null);
  const [fileItems, setFileItems] = useState<FileItem[]>([]);
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileNote, setFileNote] = useState<string | null>(null);
  const [treeLoading, setTreeLoading] = useState(false);
  const [fileLoading, setFileLoading] = useState(false);
  const [readmeLoading, setReadmeLoading] = useState(false);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [filesScope, setFilesScope] = useState<FilesScope>("local");
  const [overlayPrefixes, setOverlayPrefixes] = useState<string[]>([]);
  const [readme, setReadme] = useState<string | null>(null);
  const [jobs, setJobs] = useState<TaskJobRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [jobColumns, setJobColumns] = useTableColumns(
    "ageval.hub.columns.task-jobs",
    JOB_OPTIONAL_IDS,
    JOB_OPTIONAL_DEFAULT,
  );
  const jobSort = useTableSort("time", "desc");
  const token = getToken();
  const jobOffsetRaw = Number.parseInt(search.get("offset") || "0", 10);
  const jobOffset =
    tab === "jobs" && Number.isFinite(jobOffsetRaw) && jobOffsetRaw > 0
      ? jobOffsetRaw
      : 0;

  const localPrefix = `tasks/${taskId}`;
  const prefix =
    filesScope === "shared"
      ? "shared"
      : filesScope === "overlays"
        ? "overlays"
        : localPrefix;
  const sharedPresent = useMemo(() => hasSharedFiles(fileItems), [fileItems]);
  const localPresent = useMemo(
    () =>
      fileItems.some(
        (item) =>
          item.path === localPrefix || item.path.startsWith(`${localPrefix}/`),
      ),
    [fileItems, localPrefix],
  );
  const overlaysPresent = overlayPrefixes.length > 0;

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError(null);
      setReadmeLoading(true);
      setOverlayPrefixes([]);
      setFileItems([]);
      try {
        const listed = await listPackageVersions(datasetId, token);
        if (!listed.length) {
          throw new RegistryHttpError(404, "not_found", "package not found");
        }
        const latest = pickPackageVersion(listed, requestedVersion);
        if (!latest) {
          throw new RegistryHttpError(404, "not_found", "package not found");
        }
        if (cancelled) return;
        setVersions(listed);
        setRelease(latest);
        try {
          const r = await getPackageFile(
            datasetId,
            latest.package_digest,
            `${localPrefix}/README.md`,
            token,
          );
          if (!cancelled) setReadme(decodeFileContent(r));
        } catch {
          if (!cancelled) setReadme(null);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof RegistryHttpError) {
          setError(`${err.code}: ${err.message}`);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setReadmeLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [datasetId, taskId, token, localPrefix, requestedVersion]);

  useEffect(() => {
    if (!release || tab !== "files") return;
    let cancelled = false;
    setTreeLoading(true);
    listPackageFiles(datasetId, release.package_digest, token)
      .then((files) => {
        if (cancelled) return;
        setFileItems(files.items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof RegistryHttpError) {
          setError(`${err.code}: ${err.message}`);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
        setFileItems([]);
      })
      .finally(() => {
        if (!cancelled) setTreeLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId, release, token, tab, localPrefix]);

  useEffect(() => {
    if (!release || !fileItems.length) {
      setOverlayPrefixes([]);
      return;
    }
    const profilePaths = profileDocumentPaths(fileItems);
    if (!profilePaths.length) {
      setOverlayPrefixes([]);
      return;
    }
    let cancelled = false;
    Promise.all(
      profilePaths.map((path) =>
        getPackageFile(datasetId, release.package_digest, path, token)
          .then((file) => decodeFileContent(file) || "")
          .catch(() => ""),
      ),
    ).then((docs) => {
      if (!cancelled) setOverlayPrefixes(unionOverlayPrefixes(docs));
    });
    return () => {
      cancelled = true;
    };
  }, [datasetId, release, token, fileItems]);

  useEffect(() => {
    if (tab !== "jobs") return;
    let cancelled = false;
    setJobsLoading(true);
    Promise.all([
      listSuites(datasetId, token, { taskId }),
      listAttempts(datasetId, token, { taskId, standalone: true }),
    ])
      .then(([suites, attempts]) => {
        if (cancelled) return;
        const rows: typeof jobs = [];
        for (const s of suites) {
          const refs = s.task_refs || [];
          const hit = refs.find((r) => r.task_id === taskId);
          if (!hit) continue;
          const derived = displayLabelsFromOverlay(s.job_overlay);
          rows.push({
            job_id: s.suite_run_id,
            job_kind: "suite",
            status: hit.status,
            score: hit.score,
            agent_label: derived.agent || s.agent_label,
            model_label: derived.model || s.model_label,
            reasoning_effort: reasoningEffortFromOverlay(s.job_overlay),
            environment: environmentFromOverlay(s.job_overlay),
            created_at: s.created_at,
            run_id: hit.run_id ?? null,
            has_attempt_content: Boolean(hit.has_attempt_content),
            dataset_ref: datasetRef(s.dataset_id, s.dataset_version),
          });
        }
        for (const a of attempts) {
          rows.push({
            job_id: a.run_id,
            job_kind: "attempt",
            status: a.status,
            score: a.score ?? null,
            agent_label: a.agent_label,
            model_label: a.model_label,
            environment: a.environment || null,
            created_at: a.created_at,
            run_id: a.run_id,
            has_attempt_content: true,
            dataset_ref: datasetRef(a.dataset_id, a.dataset_version),
          });
        }
        rows.sort((left, right) => {
          const lt =
            Date.parse(String(left.created_at ?? "")) ||
            Number(left.created_at) ||
            0;
          const rt =
            Date.parse(String(right.created_at ?? "")) ||
            Number(right.created_at) ||
            0;
          return rt - lt;
        });
        setJobs(rows);
      })
      .catch(() => {
        if (!cancelled) setJobs([]);
      })
      .finally(() => {
        if (!cancelled) setJobsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId, taskId, token, tab]);

  // Rebuild tree when Local | Shared | Overlays scope changes.
  useEffect(() => {
    if (!fileItems.length) return;
    if (filesScope === "overlays") {
      const matched = fileItems.filter(
        (item) =>
          item.type !== "dir" && pathMatchesPrefixes(item.path, overlayPrefixes),
      );
      setTree(buildNestedTree(matched, "overlays"));
      const prefer =
        overlayPrefixes
          .map(
            (path) =>
              matched.find(
                (item) => item.path === path || item.path.startsWith(`${path}/`),
              ),
          )
          .find(Boolean) || matched[0];
      setSelectedPath(prefer?.path ?? null);
      setFileContent(null);
      setFileNote(null);
      return;
    }
    const nextPrefix = filesScope === "shared" ? "shared" : localPrefix;
    setTree(buildNestedTree(fileItems, nextPrefix));
    const prefer =
      filesScope === "shared"
        ? fileItems.find((e) => e.path === "shared/README.md") ||
          fileItems.find(
            (e) => e.type !== "dir" && e.path.startsWith("shared/"),
          )
        : fileItems.find((e) => e.path === `${localPrefix}/task.yaml`) ||
          fileItems.find((e) => e.path === `${localPrefix}/README.md`) ||
          fileItems.find(
            (e) => e.type !== "dir" && e.path.startsWith(localPrefix + "/"),
          );
    setSelectedPath(prefer?.path ?? null);
    setFileContent(null);
    setFileNote(null);
  }, [filesScope, fileItems, localPrefix, overlayPrefixes]);

  useEffect(() => {
    const available: FilesScope[] = [];
    if (localPresent) available.push("local");
    if (sharedPresent) available.push("shared");
    if (overlaysPresent) available.push("overlays");
    if (!available.length) {
      if (filesScope !== "local") setFilesScope("local");
      return;
    }
    if (!available.includes(filesScope)) setFilesScope(available[0]);
  }, [filesScope, localPresent, overlaysPresent, sharedPresent]);

  useEffect(() => {
    if (!release || !selectedPath) {
      setFileContent(null);
      return;
    }
    let cancelled = false;
    setFileLoading(true);
    setFileNote(null);
    getPackageFile(datasetId, release.package_digest, selectedPath, token)
      .then((f) => {
        if (cancelled) return;
        setFileContent(decodeFileContent(f));
        if (f.truncated) {
          const full = f.size ?? 0;
          const shown = (f.content || "").length;
          setFileNote(
            full > 0
              ? `Truncated preview: showing first ~${shown.toLocaleString()} of ${full.toLocaleString()} bytes (Hub preview cap).`
              : "Truncated preview (Hub preview size cap).",
          );
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
  }, [datasetId, filesScope, release, selectedPath, token]);

  const runCmd = useMemo(() => {
    if (!release) return `ageval run ${datasetId} --task ${taskId}`;
    return `ageval run ${datasetId}@${release.version} --task ${taskId}`;
  }, [datasetId, release, taskId]);

  function setTab(next: Tab) {
    const n = new URLSearchParams(search);
    if (next === "readme") n.delete("tab");
    else n.set("tab", next);
    if (next !== "jobs") n.delete("offset");
    setSearch(n, { replace: true });
  }

  function setJobOffset(next: number) {
    const n = new URLSearchParams(search);
    n.set("tab", "jobs");
    if (next <= 0) n.delete("offset");
    else n.set("offset", String(next));
    setSearch(n, { replace: true });
  }

  function setVersion(next: string) {
    const n = new URLSearchParams(search);
    n.set("v", next);
    setSearch(n, { replace: true });
  }

  useEffect(() => {
    if (
      jobSort.sortKey === "dataset" ||
      jobSort.sortKey === "environment" ||
      jobSort.sortKey === "time"
    ) {
      if (!jobColumns.includes(jobSort.sortKey)) {
        jobSort.setSortKey(null);
        jobSort.setSortDir(null);
      }
    }
  }, [jobColumns, jobSort.sortKey, jobSort.setSortKey, jobSort.setSortDir]);

  const sortedJobs = useMemo(
    () =>
      sortRows(
        jobs,
        jobSort.sortKey,
        jobSort.sortDir,
        jobColumnValue,
        compareTaskJobs,
      ),
    [jobs, jobSort.sortKey, jobSort.sortDir],
  );

  const pagedJobs = useMemo(
    () => sortedJobs.slice(jobOffset, jobOffset + TASK_PAGE_SIZE),
    [sortedJobs, jobOffset],
  );

  function onJobSort(key: string) {
    jobSort.onSort(key);
    if (jobOffset > 0) setJobOffset(0);
  }

  function jobHead(key: string, label: string) {
    return (
      <SortableHead
        label={label}
        active={jobSort.sortKey === key}
        dir={jobSort.sortKey === key ? jobSort.sortDir : null}
        onClick={() => onJobSort(key)}
      />
    );
  }

  const filesScopeSwitch =
    [localPresent, sharedPresent, overlaysPresent].filter(Boolean).length >= 2 ? (
      <FilesScopeSwitch
        filesScope={filesScope}
        onChange={setFilesScope}
        localPresent={localPresent}
        sharedPresent={sharedPresent}
        overlaysPresent={overlaysPresent}
      />
    ) : undefined;

  return (
    <>
      <CatalogHead
        title="Datasets"
        crumbs={[
          { label: "Datasets", href: "/datasets" },
          {
            label: datasetId,
            href: `/datasets/${encodeURIComponent(datasetId)}${
              requestedVersion ? `?v=${encodeURIComponent(requestedVersion)}` : ""
            }`,
          },
          { label: taskId },
        ]}
      />
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink">
            {taskId}
          </h1>
          <p className="text-xs text-mute mt-1">{datasetId}</p>
        </div>
        {versions.length > 0 ? (
          <VersionSwitcher
            versions={versions}
            value={release?.version || versions[0].version}
            onChange={setVersion}
          />
        ) : null}
      </div>

      <div className="mb-4 max-w-3xl">
        <CommandStrip command={runCmd} />
      </div>

      <UnderlineTabs
        className="mb-4"
        ariaLabel="Task sections"
        value={tab}
        onChange={setTab}
        items={[
          { id: "readme", label: "README" },
          { id: "files", label: "Files" },
          { id: "jobs", label: "Jobs" },
        ]}
      />

      {error ? (
        <p className="text-sm text-error mb-4">{error}</p>
      ) : null}

      {tab === "readme" ? (
        readmeLoading ? (
          <p className="text-sm text-mute">Loading README…</p>
        ) : readme ? (
          <Markdown source={readme} />
        ) : (
          <div className="blob-panel p-6 text-sm text-mute">
            No <code className="font-mono">tasks/{taskId}/README.md</code> —
            open the Files tab for <code className="font-mono">task.yaml</code>.
          </div>
        )
      ) : null}

      {tab === "files" ? (
        <FileSplitPanel
          tree={tree}
          treeLoading={treeLoading}
          selectedPath={selectedPath}
          onSelect={setSelectedPath}
          fileContent={
            filesScope === "shared" && !sharedPresent
              ? "This Dataset has no shared/ tree in the published package digest."
              : fileContent
          }
          fileLoading={fileLoading}
          fileNote={
            filesScope === "shared" && !sharedPresent
              ? "no shared/"
              : fileNote
          }
          rootPrefix={prefix}
          headerEnd={filesScopeSwitch}
        />
      ) : null}

      {tab === "jobs" ? (
        jobsLoading && jobs.length === 0 ? (
          <p className="text-sm text-mute">Loading jobs…</p>
        ) : jobs.length === 0 ? (
          <div className="blob-panel p-6 space-y-3">
            <p className="text-sm text-ink font-medium">No Jobs for this task</p>
            <p className="text-sm text-mute">
              Upload a standalone Attempt after{" "}
              <code className="font-mono">ageval run --task</code>, or a suite
              after a full dataset run. Add{" "}
              <code className="font-mono">--with-attempts</code> on suite upload
              when you want the row to open evidence.
            </p>
            <CommandStrip
              command={`ageval results upload <dataset-root> --run <attempt-id> --public`}
            />
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <p className="text-xs text-mute">
                Each row is a standalone Attempt or this task inside a suite run.
                Click a row with full evidence to open the detail view. Grey rows
                are summary-only. Click headers to sort.
              </p>
              <TableColumnPicker
                options={JOB_OPTIONAL_COLUMNS}
                value={jobColumns}
                onChange={setJobColumns}
                ariaLabel="Optional job columns"
              />
            </div>
            <div className="blob-panel overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>{jobHead("job_id", "Job")}</TableHead>
                    {jobColumns.includes("dataset") ? (
                      <TableHead>{jobHead("dataset", "Dataset")}</TableHead>
                    ) : null}
                    <TableHead>{jobHead("status", "Status")}</TableHead>
                    <TableHead>{jobHead("score", "Score")}</TableHead>
                    <TableHead>{jobHead("agent_label", "Harness")}</TableHead>
                    <TableHead>{jobHead("model_label", "Model")}</TableHead>
                    {jobColumns.includes("environment") ? (
                      <TableHead>
                        {jobHead("environment", "Environment")}
                      </TableHead>
                    ) : null}
                    {jobColumns.includes("time") ? (
                      <TableHead>{jobHead("time", "Time")}</TableHead>
                    ) : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pagedJobs.map((j) => {
                    const canOpen =
                      Boolean(j.has_attempt_content) && Boolean(j.run_id);
                    const evidenceHref =
                      canOpen && j.run_id
                        ? `/datasets/${encodeURIComponent(datasetId)}/tasks/${encodeURIComponent(taskId)}/attempts/${encodeURIComponent(j.run_id)}`
                        : null;
                    return (
                      <TableRow
                        key={`${j.job_kind}:${j.job_id}`}
                        className={cn(
                          canOpen && "cursor-pointer",
                          !canOpen && "opacity-70",
                        )}
                        onClick={(e) => {
                          if (!evidenceHref) return;
                          const el = e.target as HTMLElement;
                          if (el.closest("button, [role='button']")) return;
                          navigate(evidenceHref);
                        }}
                        onKeyDown={(e) => {
                          if (!evidenceHref) return;
                          const el = e.target as HTMLElement;
                          if (el.closest("button, [role='button']")) return;
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            navigate(evidenceHref);
                          }
                        }}
                        tabIndex={canOpen ? 0 : undefined}
                        role={canOpen ? "link" : undefined}
                      >
                        <TableCell>
                          <TruncateTip text={j.job_id} copyable />
                          {!canOpen ? (
                            <span className="ml-2 text-[11px] text-mute font-sans">
                              summary only
                            </span>
                          ) : null}
                        </TableCell>
                        {jobColumns.includes("dataset") ? (
                          <TableCell className="text-body">
                            {j.dataset_ref || "-"}
                          </TableCell>
                        ) : null}
                        <TableCell>
                          {j.status || "-"}
                        </TableCell>
                        <TableCell className="tabular-nums">
                          {formatScore(j.score)}
                        </TableCell>
                        <TableCell className="text-body">
                          <HarnessLabel value={j.agent_label} />
                        </TableCell>
                        <TableCell>
                          <ModelLabel
                            value={j.model_label}
                            effort={j.reasoning_effort}
                          />
                        </TableCell>
                        {jobColumns.includes("environment") ? (
                          <TableCell>
                            {j.environment || "-"}
                          </TableCell>
                        ) : null}
                        {jobColumns.includes("time") ? (
                          <TableCell className="text-mute tabular">
                            {j.created_at != null && j.created_at !== ""
                              ? formatDate(j.created_at)
                              : "-"}
                          </TableCell>
                        ) : null}
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
            <ListPager
              offset={jobOffset}
              limit={TASK_PAGE_SIZE}
              total={jobs.length}
              busy={jobsLoading}
              onOffset={setJobOffset}
            />
            {jobs.some((j) => !j.has_attempt_content) ? (
              <div className="rounded-[14px] border border-dashed border-hairline/70 bg-canvas p-4 space-y-2">
                <p className="text-sm text-body">
                  Some rows have summary only. Upload full Attempt trees to
                  enable the evidence browser:
                </p>
                <CommandStrip
                  command={`ageval results upload-suite <dataset-root> --suite-run <id> --with-attempts`}
                />
                <p className="text-xs text-mute">
                  Or backfill one run:{" "}
                  <code className="font-mono">
                    ageval results upload &lt;db&gt; --run &lt;run_id&gt;
                  </code>
                </p>
              </div>
            ) : null}
          </div>
        )
      ) : null}
    </>
  );
}
