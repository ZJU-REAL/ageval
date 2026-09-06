import { Navigate, Route, Routes } from "react-router-dom";

import { AgentDetailPage } from "@/pages/AgentDetailPage";
import { AgentsPage } from "@/pages/AgentsPage";
import { AttemptEvidencePage } from "@/pages/AttemptEvidencePage";
import { DatasetDetailPage } from "@/pages/DatasetDetailPage";
import { DatasetsPage } from "@/pages/DatasetsPage";
import { HomePage } from "@/pages/HomePage";
import { InboxPage } from "@/pages/InboxPage";
import { LoginCallbackPage } from "@/pages/LoginCallbackPage";
import { LoginPage } from "@/pages/LoginPage";
import { OrganizationDetailPage } from "@/pages/OrganizationDetailPage";
import { OrganizationsPage } from "@/pages/OrganizationsPage";
import { ModelDetailPage } from "@/pages/ModelDetailPage";
import { ModelsPage } from "@/pages/ModelsPage";
import { PluginDetailPage } from "@/pages/PluginDetailPage";
import { PluginsPage } from "@/pages/PluginsPage";
import { SuiteDetailPage } from "@/pages/SuiteDetailPage";
import { TaskDetailPage } from "@/pages/TaskDetailPage";
import { UserPage } from "@/pages/UserPage";

/** Shared route table. Peek omits Inbox/login so the modal cannot nest those shells. */
export function HubRoutes({
  includeWorkspace = true,
}: {
  includeWorkspace?: boolean;
}) {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/datasets" replace />} />
      <Route path="/home" element={<HomePage />} />
      {includeWorkspace ? <Route path="/inbox" element={<InboxPage />} /> : null}
      <Route path="/datasets" element={<DatasetsPage />} />
      <Route path="/datasets/:datasetId" element={<DatasetDetailPage />} />
      <Route
        path="/datasets/:datasetId/suites/:suiteRunId"
        element={<SuiteDetailPage />}
      />
      <Route path="/datasets/:datasetId/tasks/:taskId" element={<TaskDetailPage />} />
      <Route
        path="/datasets/:datasetId/tasks/:taskId/attempts/:runId"
        element={<AttemptEvidencePage />}
      />
      <Route path="/plugins" element={<PluginsPage />} />
      <Route path="/plugins/:pluginId" element={<PluginDetailPage />} />
      <Route path="/agents" element={<AgentsPage />} />
      <Route path="/agents/:agentId" element={<AgentDetailPage />} />
      {/* Model focus is ?model= on the package page, not a nested route. */}
      <Route path="/models" element={<ModelsPage />} />
      <Route path="/models/:modelId" element={<ModelDetailPage />} />
      <Route path="/organizations" element={<OrganizationsPage />} />
      <Route path="/organizations/:orgId" element={<OrganizationDetailPage />} />
      <Route path="/users/:login" element={<UserPage />} />
      {includeWorkspace ? (
        <>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/login/callback" element={<LoginCallbackPage />} />
        </>
      ) : null}
      <Route path="*" element={<Navigate to="/datasets" replace />} />
    </Routes>
  );
}
