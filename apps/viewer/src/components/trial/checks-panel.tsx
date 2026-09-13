import { useState, type RefObject } from "react";
import { ChevronDown, FileCode2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { CodeHighlight } from "@/lib/code-highlight";
import { cn } from "@/lib/utils";

export type EvaluationCheck = {
  id: string;
  title?: string | null;
  status?: string | null;
  score?: number | null;
  script?: string | null;
  environment?: string | null;
  exit_code?: number | null;
  stdout?: string | null;
  stderr?: string | null;
};

function packageScriptPath(script: string, taskId: string): string {
  const clean = script.trim().replace(/\\/g, "/").replace(/^\/+/, "");
  if (!clean || clean.split("/").includes("..")) return "";
  if (clean.startsWith("tasks/")) return clean;
  if (!taskId.trim()) return "";
  return `tasks/${taskId.trim()}/${clean}`;
}

function statusClass(status: string | null | undefined): string {
  const value = (status || "").toUpperCase();
  if (value === "FAIL" || value === "ERROR") return "text-error";
  return "text-ink";
}

export function ChecksPanel({
  loading,
  checks,
  note,
  taskId,
  loadScript,
  panelRef,
}: {
  loading: boolean;
  checks: EvaluationCheck[];
  note: string | null;
  taskId: string;
  loadScript?: (
    packagePath: string,
  ) => Promise<{ content: string | null; note?: string | null }>;
  panelRef?: RefObject<HTMLDivElement | null>;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [scriptPath, setScriptPath] = useState<string | null>(null);
  const [scriptContent, setScriptContent] = useState<string | null>(null);
  const [scriptNote, setScriptNote] = useState<string | null>(null);
  const [scriptLoading, setScriptLoading] = useState(false);

  async function viewScript(script: string) {
    const path = packageScriptPath(script, taskId) || script;
    setScriptPath(path);
    setScriptContent(null);
    setScriptNote(null);
    if (!loadScript) {
      setScriptNote(path);
      return;
    }
    setScriptLoading(true);
    try {
      const result = await loadScript(path);
      setScriptContent(result.content);
      setScriptNote(result.note ?? (result.content ? null : path));
    } catch (err) {
      setScriptContent(null);
      setScriptNote(err instanceof Error ? err.message : path);
    } finally {
      setScriptLoading(false);
    }
  }

  if (loading) {
    return (
      <div ref={panelRef} className="blob-panel p-4" aria-busy>
        <p className="text-sm text-mute">Loading checks…</p>
      </div>
    );
  }

  if (!checks.length) {
    return note ? <p className="text-sm text-mute">{note}</p> : null;
  }

  return (
    <div ref={panelRef} className="space-y-3">
      <div className="blob-panel overflow-hidden">
        <div className="border-b border-hairline bg-canvas px-3 py-2">
          <h2 className="text-sm font-medium text-ink">Checks</h2>
          <p className="text-xs text-mute">Observational. Not the Attempt verdict.</p>
        </div>
        <ul className="divide-y divide-hairline">
          {checks.map((check) => {
            const key = check.id;
            const open = openId === key;
            return (
              <li key={key}>
                <button
                  type="button"
                  onClick={() => setOpenId(open ? null : key)}
                  className={cn(
                    "flex w-full items-center gap-3 px-3 py-2.5 text-left",
                    "hover:bg-canvas-soft transition-colors duration-200 ease-smooth",
                  )}
                >
                  <ChevronDown
                    className={cn(
                      "h-4 w-4 shrink-0 text-mute transition-transform duration-200 ease-smooth",
                      open ? "rotate-0" : "-rotate-90",
                    )}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-[13px] text-ink">
                      {check.id}
                    </span>
                    {check.title ? (
                      <span className="block truncate text-xs text-mute">
                        {check.title}
                      </span>
                    ) : null}
                  </span>
                  <span
                    className={cn(
                      "text-sm font-medium tabular-nums",
                      statusClass(check.status),
                    )}
                  >
                    {check.status || "—"}
                  </span>
                  <span className="w-12 text-right text-sm tabular-nums text-body">
                    {typeof check.score === "number" ? check.score : "—"}
                  </span>
                </button>
                {open ? (
                  <div className="space-y-2 border-t border-hairline bg-canvas-soft/40 px-3 py-3">
                    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                      {check.environment ? (
                        <>
                          <dt className="text-mute">environment</dt>
                          <dd className="font-mono text-[13px] text-ink">
                            {check.environment}
                          </dd>
                        </>
                      ) : null}
                      {typeof check.exit_code === "number" ? (
                        <>
                          <dt className="text-mute">exit_code</dt>
                          <dd className="tabular-nums text-ink">{check.exit_code}</dd>
                        </>
                      ) : null}
                      {check.script ? (
                        <>
                          <dt className="text-mute">script</dt>
                          <dd className="min-w-0">
                            <span className="mr-2 font-mono text-[13px] text-ink break-all">
                              {packageScriptPath(check.script, taskId) || check.script}
                            </span>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2"
                              onClick={(event) => {
                                event.stopPropagation();
                                void viewScript(check.script || "");
                              }}
                            >
                              <FileCode2 className="h-3.5 w-3.5" aria-hidden />
                              View script
                            </Button>
                          </dd>
                        </>
                      ) : null}
                    </dl>
                    {check.stdout != null && check.stdout !== "" ? (
                      <div>
                        <div className="mb-1 text-xs text-mute">stdout</div>
                        <pre className="m-0 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-[8px] bg-code-bg p-3 font-mono text-[12px] leading-5 text-shell-plain">
                          {check.stdout}
                        </pre>
                      </div>
                    ) : null}
                    {check.stderr != null && check.stderr !== "" ? (
                      <div>
                        <div className="mb-1 text-xs text-mute">stderr</div>
                        <pre className="m-0 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-[8px] bg-code-bg p-3 font-mono text-[12px] leading-5 text-shell-plain">
                          {check.stderr}
                        </pre>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      </div>
      {scriptPath ? (
        <div className="blob-panel overflow-hidden">
          <div className="border-b border-hairline bg-canvas px-3 py-2 text-[12px] text-mute">
            <span className="font-mono text-ink">{scriptPath}</span>
          </div>
          {scriptLoading ? (
            <p className="p-3 text-sm text-mute">Loading script…</p>
          ) : (
            <>
              {scriptNote ? (
                <p className="px-3 pt-2 text-xs text-mute">{scriptNote}</p>
              ) : null}
              {scriptContent != null ? (
                <pre className="m-0 max-h-[40vh] overflow-auto whitespace-pre-wrap break-words bg-code-bg p-3 font-mono text-[12px] leading-5 text-shell-plain">
                  <code className="font-mono">
                    <CodeHighlight path={scriptPath} content={scriptContent} />
                  </code>
                </pre>
              ) : null}
            </>
          )}
        </div>
      ) : null}
      {note ? <p className="text-sm text-mute">{note}</p> : null}
    </div>
  );
}
