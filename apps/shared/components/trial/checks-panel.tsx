import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown, CircleAlert, CircleCheck, CircleX } from "lucide-react";

import { CodeHighlight } from "@ageval/shared/lib/code-highlight";
import { alignInScrollParent } from "@ageval/shared/lib/scroll-port";
import { cn } from "@ageval/shared/lib/utils";

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

export function isChecksPath(path: string | null | undefined): boolean {
  if (!path) return false;
  const name = path.split("/").filter(Boolean).pop() || "";
  return name === "checks.json";
}

export function parseChecksFile(
  path: string | null | undefined,
  content: string | null | undefined,
): EvaluationCheck[] | null {
  if (!isChecksPath(path) || content == null || !content.trim()) return null;
  try {
    const data = JSON.parse(content) as unknown;
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    const rec = data as { schema?: unknown; checks?: unknown };
    const schema = typeof rec.schema === "string" ? rec.schema : "";
    if (schema && !schema.startsWith("ageval.evaluation.checks/")) return null;
    if (!Array.isArray(rec.checks)) return null;
    const rows: EvaluationCheck[] = [];
    for (const item of rec.checks) {
      if (!item || typeof item !== "object" || Array.isArray(item)) continue;
      const row = item as Record<string, unknown>;
      if (typeof row.id !== "string" || !row.id.trim()) continue;
      rows.push({
        id: row.id,
        title: typeof row.title === "string" ? row.title : null,
        status: typeof row.status === "string" ? row.status : null,
        score:
          typeof row.score === "number" && Number.isFinite(row.score)
            ? row.score
            : null,
        script: typeof row.script === "string" ? row.script : null,
        environment: typeof row.environment === "string" ? row.environment : null,
        exit_code:
          typeof row.exit_code === "number" && Number.isInteger(row.exit_code)
            ? row.exit_code
            : null,
        stdout: typeof row.stdout === "string" ? row.stdout : null,
        stderr: typeof row.stderr === "string" ? row.stderr : null,
      });
    }
    return rows.length ? rows : null;
  } catch {
    return null;
  }
}

function packageScriptPath(script: string, taskId: string): string {
  const clean = script.trim().replace(/\\/g, "/");
  if (!clean || clean.startsWith("/") || clean.startsWith("~")) return "";
  const parts = clean.split("/");
  if (parts.some((part) => part === "" || part === "." || part === ".." || part === ".ageval")) {
    return "";
  }
  if (clean.startsWith("tasks/")) return clean;
  if (!taskId.trim()) return "";
  return `tasks/${taskId.trim()}/${clean}`;
}

/** First `evaluation_check(...)` whose first string argument equals `checkId`. */
function findEvaluationCheckRange(
  source: string,
  checkId: string,
): { start: number; end: number } | null {
  const id = checkId.trim();
  if (!id || !source) return null;
  const needle = "evaluation_check";
  let from = 0;
  while (from < source.length) {
    const idx = source.indexOf(needle, from);
    if (idx < 0) return null;
    let i = idx + needle.length;
    while (i < source.length && /\s/.test(source[i])) i += 1;
    if (source[i] !== "(") {
      from = idx + needle.length;
      continue;
    }
    const open = i;
    i += 1;
    while (i < source.length && /\s/.test(source[i])) i += 1;
    if (source.startsWith("check_id", i)) {
      i += "check_id".length;
      while (i < source.length && /\s/.test(source[i])) i += 1;
      if (source[i] === "=") {
        i += 1;
        while (i < source.length && /\s/.test(source[i])) i += 1;
      }
    }
    const quote = source[i];
    if (quote !== '"' && quote !== "'") {
      from = idx + needle.length;
      continue;
    }
    i += 1;
    let parsed = "";
    while (i < source.length && source[i] !== quote) {
      if (source[i] === "\\") {
        parsed += source[i + 1] ?? "";
        i += 2;
        continue;
      }
      parsed += source[i];
      i += 1;
    }
    if (parsed !== id) {
      from = idx + needle.length;
      continue;
    }
    let depth = 0;
    let end = open;
    let k = open;
    while (k < source.length) {
      const ch = source[k];
      if (ch === '"' || ch === "'") {
        const q = ch;
        k += 1;
        while (k < source.length && source[k] !== q) {
          if (source[k] === "\\") k += 1;
          k += 1;
        }
        k += 1;
        continue;
      }
      if (ch === "(") depth += 1;
      else if (ch === ")") {
        depth -= 1;
        if (depth === 0) {
          end = k;
          break;
        }
      }
      k += 1;
    }
    const startLine = source.slice(0, idx).split("\n").length;
    const endLine = source.slice(0, end + 1).split("\n").length;
    return { start: startLine, end: endLine };
  }
  return null;
}

function Count({
  label,
  value,
  warn = false,
}: {
  label: string;
  value: number;
  warn?: boolean;
}) {
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className="text-xs text-mute">{label}</span>
      <span
        className={cn(
          "text-sm tabular-nums font-medium",
          warn && value > 0 ? "text-error" : "text-ink",
        )}
      >
        {value}
      </span>
    </span>
  );
}

function StatusIcon({ status }: { status: string | null | undefined }) {
  const value = (status || "").toUpperCase();
  if (value === "FAIL") {
    return <CircleX className="h-4 w-4 shrink-0 text-error" aria-label="fail" />;
  }
  if (value === "ERROR") {
    return (
      <CircleAlert className="h-4 w-4 shrink-0 text-warning" aria-label="error" />
    );
  }
  if (value === "PASS") {
    return (
      <CircleCheck className="h-4 w-4 shrink-0 text-nav-home" aria-label="pass" />
    );
  }
  return <span className="inline-block h-4 w-4 shrink-0" aria-hidden />;
}

function ScriptSource({
  path,
  content,
  checkId,
}: {
  path: string;
  content: string;
  checkId: string;
}) {
  const range = findEvaluationCheckRange(content, checkId);
  const lines = content.split("\n");
  const [flash, setFlash] = useState(true);
  const lineRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setFlash(true);
    const timer = window.setTimeout(() => setFlash(false), 1600);
    return () => window.clearTimeout(timer);
  }, [checkId, content]);

  useLayoutEffect(() => {
    const el = lineRef.current;
    if (!el) return;
    alignInScrollParent(el, "center");
    const frame = window.requestAnimationFrame(() => {
      alignInScrollParent(el, "center");
    });
    return () => window.cancelAnimationFrame(frame);
  }, [checkId, content, range?.start]);

  return (
    <div className="overflow-x-auto overflow-y-hidden bg-code-bg py-2">
      {lines.map((line, i) => {
        const n = i + 1;
        const hit = range != null && n >= range.start && n <= range.end;
        return (
          <div
            key={n}
            ref={hit && n === range.start ? lineRef : undefined}
            data-check-line={n}
            className={cn(
              "flex gap-3 px-3 font-mono text-[12px] leading-5",
              hit && flash ? "bg-link-soft" : hit ? "bg-canvas-soft" : null,
            )}
          >
            <span className="w-8 shrink-0 select-none text-right tabular-nums text-mute">
              {n}
            </span>
            <span className="min-w-0 flex-1 whitespace-pre">
              <CodeHighlight path={path} content={line.length ? line : " "} />
            </span>
          </div>
        );
      })}
    </div>
  );
}

type ScriptState = {
  path: string;
  content: string | null;
  note: string | null;
  loading: boolean;
};

/**
 * Harbor-style structured preview for evaluation/checks.json inside the
 * file-split right pane. Not a separate Verifier module.
 */
export function ChecksFilePreview({
  checks,
  taskId,
  loadScript,
}: {
  checks: EvaluationCheck[];
  taskId: string;
  loadScript?: (
    packagePath: string,
  ) => Promise<{ content: string | null; note?: string | null }>;
}) {
  const failIds = checks
    .filter((c) => {
      const s = (c.status || "").toUpperCase();
      return s === "FAIL" || s === "ERROR";
    })
    .map((c) => c.id);
  const [openId, setOpenId] = useState<string | null>(failIds[0] ?? null);
  const [scripts, setScripts] = useState<Record<string, ScriptState>>({});
  const scriptsRef = useRef(scripts);
  scriptsRef.current = scripts;
  const loadScriptRef = useRef(loadScript);
  loadScriptRef.current = loadScript;
  const openScript = checks.find((c) => c.id === openId)?.script ?? "";

  const pass = checks.filter((c) => (c.status || "").toUpperCase() === "PASS").length;
  const fail = checks.filter((c) => (c.status || "").toUpperCase() === "FAIL").length;
  const error = checks.filter((c) => (c.status || "").toUpperCase() === "ERROR").length;

  useEffect(() => {
    if (!openId || !openScript) return;
    const path = packageScriptPath(openScript, taskId);
    const cacheKey = path || `${openId}:rejected`;
    if (!path) {
      setScripts((prev) => ({
        ...prev,
        [cacheKey]: {
          path: openScript,
          content: null,
          note: "script path rejected",
          loading: false,
        },
      }));
      return;
    }
    if (scriptsRef.current[cacheKey]?.content != null) return;
    const loader = loadScriptRef.current;
    if (!loader) {
      setScripts((prev) => ({
        ...prev,
        [cacheKey]: { path, content: null, note: path, loading: false },
      }));
      return;
    }
    let cancelled = false;
    setScripts((prev) => ({
      ...prev,
      [cacheKey]: {
        path,
        content: prev[cacheKey]?.content ?? null,
        note: null,
        loading: true,
      },
    }));
    void loader(path)
      .then((result) => {
        if (cancelled) return;
        setScripts((prev) => ({
          ...prev,
          [cacheKey]: {
            path,
            content: result.content,
            note: result.note ?? (result.content ? null : path),
            loading: false,
          },
        }));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setScripts((prev) => ({
          ...prev,
          [cacheKey]: {
            path,
            content: null,
            note: err instanceof Error ? err.message : path,
            loading: false,
          },
        }));
      });
    return () => {
      cancelled = true;
    };
  }, [openId, openScript, taskId]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-canvas">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-hairline px-3 py-2">
        <span className="font-mono text-sm text-body">checks/1</span>
        <div className="flex flex-wrap items-baseline gap-3">
          <Count label="Checks" value={checks.length} />
          <Count label="Pass" value={pass} />
          <Count label="Fail" value={fail} warn />
          <Count label="Error" value={error} warn />
        </div>
      </div>
      <ul className="min-h-0 flex-1 overflow-auto">
        {checks.map((check) => {
          const open = openId === check.id;
          const resolved = check.script
            ? packageScriptPath(check.script, taskId) || check.script
            : "";
          const cacheKey = packageScriptPath(check.script || "", taskId) || `${check.id}:rejected`;
          const scriptState = scripts[cacheKey];
          const stdout = check.stdout && check.stdout.length > 0 ? check.stdout : null;
          const stderr = check.stderr && check.stderr.length > 0 ? check.stderr : null;
          return (
            <li key={check.id} className="border-b border-hairline">
              <button
                type="button"
                onClick={() => setOpenId(open ? null : check.id)}
                className={cn(
                  "sticky top-0 z-10 flex w-full items-center gap-3 bg-canvas px-3 py-2.5 text-left",
                  "hover:bg-canvas-soft transition-colors duration-200 ease-smooth",
                  open && "border-b border-hairline",
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
                  <span className="block truncate font-mono text-sm text-ink">
                    {check.id}
                  </span>
                  {check.title ? (
                    <span className="block truncate text-sm text-mute">{check.title}</span>
                  ) : null}
                </span>
                <StatusIcon status={check.status} />
              </button>
              {open ? (
                <div className="border-t border-hairline bg-canvas">
                  {typeof check.exit_code === "number" || check.environment ? (
                    <div className="flex flex-wrap gap-x-6 gap-y-1 px-3 pt-3 text-sm">
                      {check.environment ? (
                        <span>
                          <span className="text-mute">environment </span>
                          <span className="font-mono text-ink">{check.environment}</span>
                        </span>
                      ) : null}
                      {typeof check.exit_code === "number" ? (
                        <span>
                          <span className="text-mute">exit </span>
                          <span className="tabular-nums text-ink">{check.exit_code}</span>
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                  {stdout ? (
                    <div className="px-3 pt-3">
                      <div className="mb-1 text-sm text-mute">Trace</div>
                      <pre className="m-0 overflow-auto whitespace-pre-wrap break-words rounded-[8px] bg-code-bg p-3 font-mono text-[12px] leading-5 text-shell-plain">
                        <code className="font-mono">
                          <CodeHighlight
                            path={resolved.endsWith(".py") ? resolved : "trace.txt"}
                            content={stdout}
                          />
                        </code>
                      </pre>
                    </div>
                  ) : null}
                  {stderr ? (
                    <div className="px-3 pt-3">
                      <div className="mb-1 text-sm text-mute">Stderr</div>
                      <pre className="m-0 overflow-auto whitespace-pre-wrap break-words rounded-[8px] bg-code-bg p-3 font-mono text-[12px] leading-5 text-shell-plain">
                        <code className="font-mono">
                          <CodeHighlight
                            path={resolved.endsWith(".py") ? resolved : "trace.txt"}
                            content={stderr}
                          />
                        </code>
                      </pre>
                    </div>
                  ) : null}
                  {check.script ? (
                    <div className="pt-3">
                      <div className="px-3 pb-1 font-mono text-sm text-mute">
                        {resolved}
                      </div>
                      {scriptState?.loading ? (
                        <p className="px-3 pb-3 text-sm text-mute">Loading script…</p>
                      ) : null}
                      {scriptState && !scriptState.loading && scriptState.note ? (
                        <p className="px-3 pb-3 text-xs text-mute">{scriptState.note}</p>
                      ) : null}
                      {scriptState?.content != null ? (
                        <ScriptSource
                          path={scriptState.path}
                          content={scriptState.content}
                          checkId={check.id}
                        />
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
