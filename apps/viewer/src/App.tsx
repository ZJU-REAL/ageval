import { BrowserRouter, Navigate, Outlet, Route, Routes, useParams } from "react-router-dom";

import { Shell } from "@/components/layout";
import { EmptyState, LoadingState } from "@ageval/shared/components/empty-state";
import { ListChecks } from "lucide-react";
import { AgentsPage, PluginsPage } from "@/pages/CatalogPages";
import { DatasetPackagePage, CatalogPackagePage } from "@/pages/PackagePage";
import { DatasetsPage } from "@/pages/DatasetsPage";
import { JobDetailPage } from "@/pages/JobDetailPage";
import { JobsPage } from "@/pages/JobsPage";
import { TaskDetailPage } from "@/pages/TaskDetailPage";
import { TrialDetailPage } from "@/pages/TrialDetailPage";
import { jobPath, jobsHome, taskPath, trialPath } from "@/lib/routes";
import { SessionProvider } from "@/components/session-provider";
import { useReadySession, useSession } from "@/lib/session";

function RequireSession() {
  const { session, error } = useSession();
  if (error) {
    return (
      <Shell>
        <EmptyState icon={ListChecks} title="Could not open viewer" caption={error} />
      </Shell>
    );
  }
  if (!session) {
    return (
      <Shell>
        <LoadingState label="Loading viewer" />
      </Shell>
    );
  }
  return <Outlet />;
}

function HomeRedirect() {
  const session = useReadySession();
  if (session.datasets.length === 1) {
    return <Navigate to={jobsHome(session.datasets[0].key)} replace />;
  }
  return <Navigate to="/datasets" replace />;
}

function JobsIndex() {
  const session = useReadySession();
  if (session.datasets.length === 1) {
    return <Navigate to={jobsHome(session.datasets[0].key)} replace />;
  }
  return <JobsPage />;
}

function JobsEntry() {
  const { datasetKey = "" } = useParams();
  const session = useReadySession();
  if (session.datasets.some((item) => item.key === datasetKey)) {
    return <JobsPage />;
  }
  if (session.datasets.length === 1) {
    return <Navigate to={jobPath(session.datasets[0].key, datasetKey)} replace />;
  }
  return (
    <Shell>
      <EmptyState
        icon={ListChecks}
        title="Unknown dataset"
        caption="Open Datasets and pick a package."
      />
    </Shell>
  );
}

function LegacyTaskRedirect() {
  const { jobId = "", taskId = "", runId } = useParams();
  const session = useReadySession();
  if (session.datasets.length !== 1) {
    return (
      <Shell>
        <EmptyState
          icon={ListChecks}
          title="Pick a dataset"
          caption="This link does not name a dataset."
        />
      </Shell>
    );
  }
  const key = session.datasets[0].key;
  const to = runId
    ? trialPath(key, jobId, taskId, runId)
    : taskPath(key, jobId, taskId);
  return <Navigate to={to} replace />;
}

export default function App() {
  return (
    <SessionProvider>
      <BrowserRouter useTransitions={false}>
        {/* RR7 wraps location in startTransition by default; URL can move while the tree stays put. */}
        <Routes>
          <Route element={<RequireSession />}>
            <Route path="/" element={<HomeRedirect />} />
            <Route path="/datasets" element={<DatasetsPage />} />
            <Route path="/datasets/:datasetKey" element={<DatasetPackagePage />} />
            <Route path="/plugins" element={<PluginsPage />} />
            <Route
              path="/plugins/:source/:packageId/:version"
              element={<CatalogPackagePage kind="plugin" />}
            />
            <Route path="/agents" element={<AgentsPage />} />
            <Route
              path="/agents/:source/:packageId/:version"
              element={<CatalogPackagePage kind="agent" />}
            />
            <Route path="/jobs" element={<JobsIndex />} />
            <Route
              path="/jobs/:jobId/tasks/:taskId/trials/:runId"
              element={<LegacyTaskRedirect />}
            />
            <Route path="/jobs/:jobId/tasks/:taskId" element={<LegacyTaskRedirect />} />
            <Route
              path="/jobs/:datasetKey/:jobId/tasks/:taskId/trials/:runId"
              element={<TrialDetailPage />}
            />
            <Route
              path="/jobs/:datasetKey/:jobId/tasks/:taskId"
              element={<TaskDetailPage />}
            />
            <Route path="/jobs/:datasetKey/:jobId" element={<JobDetailPage />} />
            <Route path="/jobs/:datasetKey" element={<JobsEntry />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </SessionProvider>
  );
}
