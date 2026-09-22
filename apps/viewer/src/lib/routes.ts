import type { Job, TaskRow } from "@/lib/api";

export function enc(value: string): string {
  return encodeURIComponent(value);
}

export function jobsHome(datasetKey: string): string {
  return `/jobs/${enc(datasetKey)}`;
}

export function jobPath(datasetKey: string, jobId: string): string {
  return `/jobs/${enc(datasetKey)}/${enc(jobId)}`;
}

export function taskPath(datasetKey: string, jobId: string, taskId: string): string {
  return `/jobs/${enc(datasetKey)}/${enc(jobId)}/tasks/${enc(taskId)}`;
}

export function trialPath(
  datasetKey: string,
  jobId: string,
  taskId: string,
  runId: string,
): string {
  return `/jobs/${enc(datasetKey)}/${enc(jobId)}/tasks/${enc(taskId)}/trials/${enc(runId)}`;
}

export function datasetPath(datasetKey: string): string {
  return `/datasets/${enc(datasetKey)}`;
}

export function catalogPath(
  kind: "plugins" | "agents",
  source: string,
  id: string,
  version: string,
): string {
  return `/${kind}/${enc(source)}/${enc(id)}/${enc(version)}`;
}

export function taskRunIds(task: Pick<TaskRow, "attempt_run_ids" | "run_id">): string[] {
  if (task.attempt_run_ids?.length) {
    return task.attempt_run_ids.filter(Boolean);
  }
  return task.run_id ? [task.run_id] : [];
}

export function jobDisplayName(job: Job): string {
  if (job.source_kind === "single") {
    return job.task_id || job.source || job.job_name;
  }
  return job.job_name;
}

/** Suite jobs open the task table; single-task jobs skip straight to the trial. */
export function jobHref(datasetKey: string, job: Job): string {
  if (job.source_kind === "single") {
    const taskId = job.task_id || job.source;
    const runId = job.run_id || job.job_id;
    if (taskId && runId) {
      return trialPath(datasetKey, job.job_id, taskId, runId);
    }
  }
  return jobPath(datasetKey, job.job_id);
}

/** One attempt → trial; k>1 → this job's filtered trial list. */
export function taskHref(datasetKey: string, jobId: string, task: TaskRow): string {
  const ids = taskRunIds(task);
  if (ids.length === 1) {
    return trialPath(datasetKey, jobId, task.task_id, ids[0]);
  }
  return taskPath(datasetKey, jobId, task.task_id);
}
