import { reasonText } from "@ageval/shared/lib/reason";
import type { Trial } from "@ageval/shared/lib/trial-types";
import { formatDate, formatScore } from "@ageval/shared/lib/utils";

import { Outcome } from "./outcome";

export function OutcomeStrip({ trial }: { trial: Trial }) {
  const status = (trial.status || "").toUpperCase();
  const reason = reasonText(trial);
  const bad = status === "ERROR" || status === "FAIL" || Boolean(trial.error);

  return (
    <>
      <div className="grid grid-cols-2 gap-3 blob-panel p-4 sm:grid-cols-4">
        <Outcome label="Status">
          <span className={bad ? "text-error font-medium" : "text-ink font-medium"}>
            {status || "-"}
          </span>
        </Outcome>
        <Outcome label="Score">
          <span className="font-mono tabular-nums">{formatScore(trial.score ?? trial.reward)}</span>
        </Outcome>
        <Outcome label="Started">
          <span className="font-mono tabular-nums text-body">{formatDate(trial.started)}</span>
        </Outcome>
        <Outcome label="Invocations">
          <span className="font-mono tabular-nums">
            {trial.agent_invocations != null ? trial.agent_invocations : "-"}
          </span>
        </Outcome>
      </div>
      {trial.note ? <p className="text-xs text-mute">{trial.note}</p> : null}
      {trial.extra && Object.keys(trial.extra).length > 0 ? (
        <details className="text-[11px] text-mute">
          <summary className="cursor-pointer select-none">extra</summary>
          <pre className="mt-1 m-0 whitespace-pre-wrap break-words font-mono text-[11px] leading-4 text-body">
            {JSON.stringify(trial.extra, null, 2)}
          </pre>
        </details>
      ) : null}
      {reason ? (
        <p
          className={
            status === "ERROR" || trial.error
              ? "text-sm text-error rounded-[14px] bg-error-soft/40 px-3 py-2"
              : "text-sm text-body rounded-[14px] bg-canvas-soft px-3 py-2"
          }
        >
          {reason}
        </p>
      ) : null}
    </>
  );
}
