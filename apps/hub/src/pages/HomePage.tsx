import { useEffect, useState, type ReactNode } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { CatalogCardGrid } from "@/components/catalog-card";
import { LoadingState } from "@/components/empty-state";
import { MaintainerMark } from "@/components/maintainer-mark";
import { OfficialMark } from "@/components/official-mark";
import { usePublicUser } from "@/hooks/use-public-user";
import { PageHead } from "@/components/page-head";
import { ScrollTable } from "@/components/scroll-table";
import {
  encodeDatasetId,
  environmentFromOverlay,
  latestPackageByDataset,
  listOrgs,
  listPackageFiles,
  listPackages,
  listSuites,
  taskIdsFromFiles,
  packageDisplayTitle,
  versionLabel,
  type OrgRow,
  type PackageRelease,
  type SuiteRow,
  RegistryHttpError,
} from "@/lib/api";
import { getGithubUser, getToken } from "@/lib/auth";
import { rememberReturnPath } from "@/lib/return-path";
import { datasetRef, formatDate } from "@/lib/utils";

type TaskRow = { datasetId: string; taskId: string };

export function HomePage() {
  const navigate = useNavigate();
  const token = getToken();
  const githubUser = getGithubUser();
  const publicUser = usePublicUser(token ? githubUser : null);

  const [jobs, setJobs] = useState<SuiteRow[]>([]);
  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [datasets, setDatasets] = useState<PackageRelease[]>([]);
  const [plugins, setPlugins] = useState<PackageRelease[]>([]);
  const [agents, setAgents] = useState<PackageRelease[]>([]);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [taskNote, setTaskNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      listSuites(null, token, { uploadedBy: "me" }),
      listOrgs(token),
      listPackages(token, { packageKind: "dataset", mine: true }),
      listPackages(token, { packageKind: "plugin", mine: true }),
      listPackages(token, { packageKind: "agent", mine: true }),
    ])
      .then(async ([suiteRows, orgRows, datasetRows, pluginRows, agentRows]) => {
        if (cancelled) return;
        const ds = latestPackageByDataset(datasetRows);
        const plugs = latestPackageByDataset(pluginRows);
        const ags = latestPackageByDataset(agentRows);
        setJobs(suiteRows);
        setOrgs(orgRows);
        setDatasets(ds);
        setPlugins(plugs);
        setAgents(ags);
        setTaskNote(null);
        setError(null);

        const listings = await Promise.all(
          ds.map(async (row) => {
            try {
              const files = await listPackageFiles(
                row.dataset_id,
                row.package_digest,
                token,
              );
              return {
                ok: true as const,
                datasetId: row.dataset_id,
                ids: taskIdsFromFiles(files.items),
              };
            } catch {
              return {
                ok: false as const,
                datasetId: row.dataset_id,
                ids: [] as string[],
              };
            }
          }),
        );
        const taskRows: TaskRow[] = [];
        const seen = new Set<string>();
        function addTask(datasetId: string, taskId: string) {
          const key = `${datasetId}/${taskId}`;
          if (seen.has(key)) return;
          seen.add(key);
          taskRows.push({ datasetId, taskId });
        }
        for (const listing of listings) {
          for (const tid of listing.ids) addTask(listing.datasetId, tid);
        }
        const maintainable = new Set(ds.map((d) => d.dataset_id));
        if (!taskRows.length) {
          for (const s of suiteRows) {
            if (!s.dataset_id || !maintainable.has(s.dataset_id)) continue;
            for (const ref of s.task_refs || []) {
              const tid = String(ref.task_id || "").trim();
              if (tid) addTask(s.dataset_id, tid);
            }
          }
        }
        const filesFailed = ds.length > 0 && listings.every((r) => !r.ok);
        if (!cancelled) {
          setTasks(taskRows);
          setTaskNote(
            filesFailed && !taskRows.length
              ? "Could not list task members from dataset files."
              : null,
          );
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof RegistryHttpError) {
          setError(`${err.code}: ${err.message}`);
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

  if (!token) {
    rememberReturnPath("/home");
    return <Navigate to="/login" replace />;
  }

  return (
    <>
      <PageHead
        title="Home"
        sub={
          <>
            {githubUser ? (
              <>
                Signed in as{" "}
                <span className="inline-flex items-center gap-1 align-middle">
                  <span className="text-xs">{githubUser}</span>
                  {orgs.some((o) => o.official) ? (
                    <OfficialMark kind="org" />
                  ) : null}
                  {publicUser?.maintainer ? <MaintainerMark /> : null}
                </span>
                {" · "}
              </>
            ) : null}
            Read-only lists. Publish, upload, and release stay on the CLI.
          </>
        }
      />

      {loading ? <LoadingState label="Loading home" /> : null}
      {error ? (
        <div className="blob-panel p-4 text-sm mb-4">
          <p className="text-error font-medium">Could not load home</p>
          <p className="mt-1 text-xs text-body">{error}</p>
        </div>
      ) : null}

      {!loading && !error ? (
        <div className="space-y-8">
          <HomeSection
            title="Organizations"
            hint="Membership only."
            empty="You do not belong to an organization yet."
            count={orgs.length}
          >
            {orgs.length ? (
              <ScrollTable
                headers={["Org", "Role"]}
                rows={orgs.map((o) => ({
                  key: o.org_id,
                  onClick: () =>
                    navigate(`/organizations/${encodeURIComponent(o.org_id)}`),
                  cells: [
                    <span key="id" className="inline-flex items-center gap-1.5 min-w-0">
                      <span>{o.org_id}</span>
                      {o.display_name ? (
                        <span className="text-xs text-mute">
                          {o.display_name}
                        </span>
                      ) : null}
                      {o.official ? <OfficialMark kind="org" /> : null}
                    </span>,
                    o.role || "—",
                  ],
                }))}
              />
            ) : null}
          </HomeSection>

          <HomeSection
            title="Datasets"
            hint="Datasets you can maintain (owner or collaborator)."
            empty="No maintainable datasets yet."
            count={datasets.length}
          >
            {datasets.length ? (
              <ScrollTable
                headers={["Dataset", "Version", "Visibility"]}
                rows={datasets.map((d) => ({
                  key: d.dataset_id,
                  onClick: () =>
                    navigate(`/datasets/${encodeDatasetId(d.dataset_id)}`),
                  cells: [
                    <span key="id" className="font-medium">
                      {packageDisplayTitle(d.dataset_id, d.display_name)}
                    </span>,
                    versionLabel(d),
                    d.visibility,
                  ],
                }))}
              />
            ) : null}
          </HomeSection>

          <HomeSection
            title="Tasks"
            hint="Members of datasets you can maintain."
            empty={
              taskNote || "No tasks in your maintainable datasets."
            }
            count={tasks.length}
          >
            {tasks.length ? (
              <ScrollTable
                headers={["Dataset", "Task"]}
                rows={tasks.map((t) => ({
                  key: `${t.datasetId}/${t.taskId}`,
                  onClick: () =>
                    navigate(
                      `/datasets/${encodeDatasetId(t.datasetId)}/tasks/${encodeURIComponent(t.taskId)}`,
                    ),
                  cells: [
                    <span key="db">
                      {t.datasetId}
                    </span>,
                    <span key="t">
                      {t.taskId}
                    </span>,
                  ],
                }))}
              />
            ) : null}
          </HomeSection>

          <HomeSection
            title="Plugins"
            hint="Plugin packages you uploaded."
            empty="No plugin packages uploaded by this account."
            count={plugins.length}
          >
            {plugins.length ? (
              <CatalogCardGrid
                kind="plugin"
                rows={plugins}
                onOpen={(id) => navigate(`/plugins/${encodeDatasetId(id)}`)}
              />
            ) : null}
          </HomeSection>

          <HomeSection
            title="Agents"
            hint="Agent packages you uploaded."
            empty="No agent packages uploaded by this account."
            count={agents.length}
          >
            {agents.length ? (
              <CatalogCardGrid
                kind="agent"
                rows={agents}
                onOpen={(id) => navigate(`/agents/${encodeDatasetId(id)}`)}
              />
            ) : null}
          </HomeSection>

          <HomeSection
            title="Jobs"
            hint="Suites you uploaded (uploaded_by), not every job in your orgs."
            empty="No suite uploads under this account yet."
            count={jobs.length}
          >
            {jobs.length ? (
              <ScrollTable
                headers={["Suite", "Dataset", "Environment", "Pass rate", "Uploaded"]}
                rows={jobs.map((s) => ({
                  key: s.suite_run_id,
                  onClick: () => {
                    if (!s.dataset_id) return;
                    navigate(
                      `/datasets/${encodeDatasetId(s.dataset_id)}/suites/${encodeURIComponent(s.suite_run_id)}`,
                    );
                  },
                  cells: [
                    <span key="id">
                      {s.suite_run_id}
                    </span>,
                    datasetRef(s.dataset_id, s.dataset_version) || "—",
                    <span key="env">
                      {environmentFromOverlay(s.job_overlay) || "—"}
                    </span>,
                    s.pass_rate == null
                      ? "—"
                      : `${(Number(s.pass_rate) * 100).toFixed(1)}%`,
                    formatDate(s.created_at),
                  ],
                }))}
              />
            ) : null}
          </HomeSection>
        </div>
      ) : null}
    </>
  );
}

function HomeSection({
  title,
  hint,
  empty,
  count,
  children,
}: {
  title: string;
  hint: string;
  empty: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium text-ink">{title}</h2>
        <span className="text-[11px] tabular-nums text-mute">{count}</span>
      </div>
      <p className="text-xs text-mute">{hint}</p>
      {count === 0 ? (
        <p className="text-sm text-mute rounded-[14px] border border-dashed border-hairline/70 bg-canvas px-3 py-4">
          {empty}
        </p>
      ) : (
        children
      )}
    </section>
  );
}


