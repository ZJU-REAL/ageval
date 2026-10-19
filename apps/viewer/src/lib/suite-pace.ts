/** Suite pace: finished/total, and time left from recent task durations. */

export const SUITE_POLL_MS = 8000;
const RECENT = 8;

const OPEN = new Set(["PENDING", "RUNNING", "CANCELLING", "CANCELING"]);

export type PaceTask = {
  task_id: string;
  status?: string | null;
  duration_ms?: number | null;
  finished_at?: string | null;
};

export type PaceTone = "pass" | "fail" | "error" | "forecast";

export type PaceDot = {
  taskId: string;
  durationMs: number;
  /** Finish time. Forecast dots have none and sit after the last finish. */
  finishedAt: number | null;
  tone: PaceTone;
};

export type SuitePace = {
  done: number;
  total: number;
  running: number;
  remaining: number;
  meanMs: number | null;
  /** Average gap between the recent finishes, when at least two have stamps. */
  gapMs: number | null;
  etaMs: number | null;
  recentCount: number;
  /** Finished tasks that have a duration, oldest first. */
  dots: PaceDot[];
  /** Still-open tasks, height set to the recent average duration. */
  forecast: PaceDot[];
};

export function jobStillRunning(job: { status?: string | null }): boolean {
  const status = (job.status || "").toLowerCase();
  return status === "running" || status === "cancelling";
}

export function formatDurationMs(ms: number): string {
  const safe = Math.max(0, ms);
  if (safe < 1000) return `${Math.round(safe)}ms`;
  const totalS = safe / 1000;
  if (totalS < 10) return `${totalS.toFixed(1)}s`;
  if (totalS < 60) return `${Math.round(totalS)}s`;
  let minutes = Math.floor(totalS / 60);
  let seconds = Math.round(totalS - minutes * 60);
  if (seconds === 60) {
    minutes += 1;
    seconds = 0;
  }
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    const rem = minutes % 60;
    return rem ? `${hours}h ${rem}m` : `${hours}h`;
  }
  return seconds ? `${minutes}m ${String(seconds).padStart(2, "0")}s` : `${minutes}m`;
}

export function formatTimeLeft(pace: SuitePace): string {
  if (pace.total > 0 && pace.remaining === 0) return "Finished";
  if (pace.etaMs == null) return "-";
  return formatDurationMs(pace.etaMs);
}

export function timeLeftNote(pace: SuitePace): string {
  if (pace.total > 0 && pace.remaining === 0) return "Every task has finished.";
  if (pace.recentCount === 0 || pace.etaMs == null) {
    return "This shows up after a task finishes.";
  }
  const n = pace.recentCount;
  const finishes = n === 1 ? "finish" : "finishes";
  const open = pace.remaining === 1 ? "task is" : "tasks are";
  if (pace.gapMs != null) {
    return `The last ${n} ${finishes} landed ${formatDurationMs(pace.gapMs)} apart. ${pace.remaining} ${open} still open.`;
  }
  const mean = formatDurationMs(pace.meanMs ?? 0);
  if (pace.running > 1) {
    return `The last ${n} ${finishes} averaged ${mean}. ${pace.running} are running, and ${pace.remaining} ${open} still open.`;
  }
  return `The last ${n} ${finishes} averaged ${mean}. ${pace.remaining} ${open} still open.`;
}

function toneOf(status: string): PaceTone {
  if (status === "FAIL") return "fail";
  if (status === "ERROR") return "error";
  return "pass";
}

export function suitePace(tasks: PaceTask[]): SuitePace {
  let done = 0;
  let running = 0;
  const openIds: string[] = [];
  const samples: PaceDot[] = [];
  for (const task of tasks) {
    const status = (task.status || "").toUpperCase();
    if (OPEN.has(status)) {
      if (status === "RUNNING" || status === "CANCELLING" || status === "CANCELING") {
        running += 1;
      }
      openIds.push(task.task_id);
      continue;
    }
    done += 1;
    const ms = task.duration_ms;
    if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) continue;
    const parsed = task.finished_at ? Date.parse(task.finished_at) : Number.NaN;
    samples.push({
      taskId: task.task_id,
      durationMs: ms,
      finishedAt: Number.isFinite(parsed) ? parsed : null,
      tone: toneOf(status),
    });
  }

  const total = tasks.length;
  const remaining = Math.max(0, total - done);
  const dots = [...samples].sort((a, b) => {
    if (a.finishedAt == null && b.finishedAt == null) return 0;
    if (a.finishedAt == null) return 1;
    if (b.finishedAt == null) return -1;
    return a.finishedAt - b.finishedAt;
  });
  const recent = dots.slice(-RECENT);
  const meanMs = recent.length
    ? recent.reduce((sum, item) => sum + item.durationMs, 0) / recent.length
    : null;
  const timedRecent = recent.filter(
    (item): item is PaceDot & { finishedAt: number } => item.finishedAt != null,
  );
  const windowStart = timedRecent[0]?.finishedAt;
  const windowEnd = timedRecent[timedRecent.length - 1]?.finishedAt;
  const gapMs =
    timedRecent.length >= 2 && windowStart != null && windowEnd != null && windowEnd > windowStart
      ? (windowEnd - windowStart) / (timedRecent.length - 1)
      : null;

  let etaMs: number | null = null;
  if (remaining === 0) {
    etaMs = 0;
  } else if (gapMs != null) {
    etaMs = remaining * gapMs;
  } else if (meanMs != null) {
    etaMs = (remaining * meanMs) / Math.max(1, running);
  }

  const height = meanMs ?? gapMs;
  const forecast: PaceDot[] =
    remaining > 0 && height != null
      ? Array.from({ length: remaining }, (_, index) => ({
          taskId: openIds[index] || `open-${index + 1}`,
          durationMs: height,
          finishedAt: null,
          tone: "forecast" as const,
        }))
      : [];

  return {
    done,
    total,
    running,
    remaining,
    meanMs,
    gapMs,
    etaMs,
    recentCount: recent.length,
    dots,
    forecast,
  };
}
