import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { JobDetailPage } from "@/pages/JobDetailPage";
import { JobsPage } from "@/pages/JobsPage";
import { TaskDetailPage } from "@/pages/TaskDetailPage";
import { TrialDetailPage } from "@/pages/TrialDetailPage";

export default function App() {
  return (
    <BrowserRouter useTransitions={false}>
      {/* RR7 wraps location in startTransition by default; URL can move while the tree stays put. */}
      <Routes>
        <Route path="/" element={<JobsPage />} />
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />
        <Route path="/jobs/:jobId/tasks/:taskId" element={<TaskDetailPage />} />
        <Route
          path="/jobs/:jobId/tasks/:taskId/trials/:runId"
          element={<TrialDetailPage />}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
