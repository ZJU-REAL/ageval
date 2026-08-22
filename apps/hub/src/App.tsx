import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { Shell } from "@/components/layout";
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
import { PluginDetailPage } from "@/pages/PluginDetailPage";
import { PluginsPage } from "@/pages/PluginsPage";
import { TaskDetailPage } from "@/pages/TaskDetailPage";
import { UserPage } from "@/pages/UserPage";

export default function App() {
  return (
    <BrowserRouter>
      <Shell>
        <Routes>
          <Route path="/" element={<Navigate to="/datasets" replace />} />
          <Route path="/home" element={<HomePage />} />
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/datasets" element={<DatasetsPage />} />
          <Route path="/datasets/:datasetId" element={<DatasetDetailPage />} />
          <Route
            path="/datasets/:datasetId/tasks/:taskId"
            element={<TaskDetailPage />}
          />
          <Route
            path="/datasets/:datasetId/tasks/:taskId/attempts/:runId"
            element={<AttemptEvidencePage />}
          />
          <Route path="/plugins" element={<PluginsPage />} />
          <Route path="/plugins/:pluginId" element={<PluginDetailPage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/agents/:agentId" element={<AgentDetailPage />} />
          <Route path="/organizations" element={<OrganizationsPage />} />
          <Route
            path="/organizations/:orgId"
            element={<OrganizationDetailPage />}
          />
          <Route path="/users/:login" element={<UserPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/login/callback" element={<LoginCallbackPage />} />
          <Route path="*" element={<Navigate to="/datasets" replace />} />
        </Routes>
      </Shell>
    </BrowserRouter>
  );
}
