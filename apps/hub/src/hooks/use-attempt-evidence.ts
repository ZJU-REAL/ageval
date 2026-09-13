import { useEffect, useMemo, useRef, useState } from "react";

import {
  availableTabsFromPaths,
  buildTrialMeta,
  firstTab,
  invDirFromTrajPath,
  CHECKS_REL,
  OBSERVATION_REL,
  parseChecksJson,
  parseTrajectoryJsonl,
  trajectoryRelPaths,
  scopeForTab,
  toArchivePath,
  toRelPath,
  treeEntriesForScope,
} from "@/lib/attempt-evidence";
import {
  decodeFileContent,
  getAttempt,
  getAttemptFile,
  listAttemptFiles,
  type AttemptMeta,
  RegistryHttpError,
} from "@/lib/api";
import type {
  Trial,
  TrajectoryStep,
  TreeEntry,
} from "@/lib/trial-types";
import {
  type TabId,
} from "@/components/trial/tabs";

async function readJsonFile(
  runId: string,
  relPath: string,
  token: string | null,
): Promise<Record<string, unknown>> {
  try {
    const f = await getAttemptFile(runId, toArchivePath(relPath, runId), token);
    const text = decodeFileContent(f);
    if (!text) return {};
    const data = JSON.parse(text) as unknown;
    return data && typeof data === "object" && !Array.isArray(data)
      ? (data as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

export function useAttemptEvidence(
  runId: string,
  taskId: string,
  token: string | null,
) {
  const [meta, setMeta] = useState<AttemptMeta | null>(null);
  const [trial, setTrial] = useState<Trial | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [relFiles, setRelFiles] = useState<
    Array<{ path: string; size?: number }>
  >([]);
  const [invProfileByDir, setInvProfileByDir] = useState<
    Map<string, string | null>
  >(() => new Map());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [activeTab, setActiveTab] = useState<TabId | null>(null);
  const [steps, setSteps] = useState<TrajectoryStep[]>([]);
  const [trajNote, setTrajNote] = useState<string | null>(null);
  const [trajLoading, setTrajLoading] = useState(false);
  const [observationSteps, setObservationSteps] = useState<TrajectoryStep[]>(
    [],
  );
  const [obsNote, setObsNote] = useState<string | null>(null);
  const [obsLoading, setObsLoading] = useState(false);
  const [checks, setChecks] = useState<
    ReturnType<typeof parseChecksJson>
  >([]);
  const [checksNote, setChecksNote] = useState<string | null>(null);
  const [checksLoading, setChecksLoading] = useState(false);

  const [tree, setTree] = useState<TreeEntry[]>([]);
  const [treeGroups, setTreeGroups] = useState<Array<{
    key: string;
    profile_id?: string | null;
    label?: string;
  }> | null>(null);
  const [treeLoading, setTreeLoading] = useState(false);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileNote, setFileNote] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const trajFetchedRef = useRef(false);
  const obsFetchedRef = useRef(false);
  const checksFetchedRef = useRef(false);

  const availableTabs = useMemo(
    () => availableTabsFromPaths(relFiles.map((f) => f.path)),
    [relFiles],
  );

  // Initial load: list files + key JSON + trial meta
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      setTrial(null);
      setMeta(null);
      setResult(null);
      setRelFiles([]);
      setActiveTab(null);
      setSteps([]);
      trajFetchedRef.current = false;
      obsFetchedRef.current = false;
      checksFetchedRef.current = false;
      setChecks([]);
      setChecksNote(null);
      setTree([]);
      setSelectedPath(null);
      setFileContent(null);
      try {
        const m = await getAttempt(runId, token);
        if (cancelled) return;
        setMeta(m);
        const files = await listAttemptFiles(runId, token);
        if (cancelled) return;
        const items = files.items || [];
        const rel: Array<{ path: string; size?: number }> = [];
        for (const it of items) {
          if (it.type === "dir") continue;
          const r = toRelPath(it.path, runId);
          if (r == null || r === "") continue;
          rel.push({ path: r, size: it.size });
        }
        setRelFiles(rel);
        const pathSet = new Set(rel.map((f) => f.path));

        const [resultJ, summaryJ, lockJ] = await Promise.all([
          pathSet.has("result.json")
            ? readJsonFile(runId, "result.json", token)
            : Promise.resolve({}),
          pathSet.has("summary.json")
            ? readJsonFile(runId, "summary.json", token)
            : Promise.resolve({}),
          pathSet.has("lock.json")
            ? readJsonFile(runId, "lock.json", token)
            : Promise.resolve({}),
        ]);
        if (cancelled) return;
        setResult(Object.keys(resultJ).length ? resultJ : null);

        // invocation metadata
        const invDirs = new Set<string>();
        for (const f of rel) {
          const m2 = f.path.match(/^agent\/invocations\/([^/]+)\//);
          if (m2) invDirs.add(m2[1]);
        }
        const invMetas: Array<{
          dirname: string;
          meta: Record<string, unknown>;
        }> = [];
        const profileMap = new Map<string, string | null>();
        await Promise.all(
          [...invDirs].sort().map(async (dirname) => {
            const metaPath = `agent/invocations/${dirname}/metadata.json`;
            if (!pathSet.has(metaPath)) {
              profileMap.set(dirname, null);
              return;
            }
            const meta = await readJsonFile(runId, metaPath, token);
            invMetas.push({ dirname, meta });
            const pid =
              typeof meta.profile_id === "string" ? meta.profile_id : null;
            profileMap.set(dirname, pid);
          }),
        );
        if (cancelled) return;
        setInvProfileByDir(profileMap);

        let trajectorySteps: TrajectoryStep[] = [];
        if (pathSet.has("trajectory.jsonl")) {
          try {
            const f = await getAttemptFile(
              runId,
              toArchivePath("trajectory.jsonl", runId),
              token,
            );
            if (cancelled) return;
            trajectorySteps = parseTrajectoryJsonl(decodeFileContent(f) || "");
          } catch {
            trajectorySteps = [];
          }
        }

        const t = buildTrialMeta({
          runId,
          taskId: taskId || m.task_id || "",
          relFiles: rel.map((f) => f.path),
          result: resultJ,
          summary: summaryJ,
          lock: lockJ,
          invMetas,
          trajectorySteps,
        });
        setTrial(t);
        const tabs = availableTabsFromPaths(rel.map((f) => f.path));
        setActiveTab(firstTab(tabs));
      } catch (err) {
        if (cancelled) return;
        if (err instanceof RegistryHttpError) {
          setError(`${err.code}: ${err.message}`);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [runId, taskId, token]);

  // Tab data: trajectory or scoped tree
  useEffect(() => {
    if (!activeTab || !runId) return;
    let cancelled = false;

    if (activeTab === "verifier") {
      const hasObs = relFiles.some((f) => f.path === OBSERVATION_REL);
      if (hasObs) {
        if (!obsFetchedRef.current) {
          setObsLoading(true);
          setObsNote(null);
          (async () => {
            try {
              const f = await getAttemptFile(
                runId,
                toArchivePath(OBSERVATION_REL, runId),
                token,
              );
              if (cancelled) return;
              const parsed = parseTrajectoryJsonl(decodeFileContent(f) || "");
              setObservationSteps(parsed);
              obsFetchedRef.current = true;
              setObsNote(null);
            } catch (e) {
              if (!cancelled) {
                setObservationSteps([]);
                setObsNote(e instanceof Error ? e.message : String(e));
              }
            } finally {
              if (!cancelled) setObsLoading(false);
            }
          })();
        }
      } else {
        setObservationSteps([]);
        setObsNote(null);
        setObsLoading(false);
      }
      const hasChecks = relFiles.some((f) => f.path === CHECKS_REL);
      if (hasChecks) {
        if (!checksFetchedRef.current) {
          setChecksLoading(true);
          setChecksNote(null);
          (async () => {
            try {
              const f = await getAttemptFile(
                runId,
                toArchivePath(CHECKS_REL, runId),
                token,
              );
              if (cancelled) return;
              setChecks(parseChecksJson(decodeFileContent(f) || ""));
              checksFetchedRef.current = true;
              setChecksNote(null);
            } catch (e) {
              if (!cancelled) {
                setChecks([]);
                setChecksNote(e instanceof Error ? e.message : String(e));
              }
            } finally {
              if (!cancelled) setChecksLoading(false);
            }
          })();
        }
      } else {
        setChecks([]);
        setChecksNote(null);
        setChecksLoading(false);
      }
    }

    if (activeTab === "trajectory") {
      if (trajFetchedRef.current) return;
      setTrajLoading(true);
      setTrajNote(null);
      (async () => {
        try {
          const trajPaths = trajectoryRelPaths(relFiles.map((f) => f.path));
          const all: TrajectoryStep[] = [];
          for (const rel of trajPaths) {
            if (all.length >= 2000) break;
            const dirname = invDirFromTrajPath(rel);
            const f = await getAttemptFile(
              runId,
              toArchivePath(rel, runId),
              token,
            );
            if (cancelled) return;
            const text = decodeFileContent(f) || "";
            const parsed = parseTrajectoryJsonl(text);
            const profile_id = dirname
              ? invProfileByDir.get(dirname) ?? null
              : null;
            for (const s of parsed) {
              if (all.length >= 2000) break;
              all.push({
                ...s,
                invocation: dirname || undefined,
                invocation_id: dirname || undefined,
                profile_id: profile_id || s.profile_id,
              });
            }
          }
          if (cancelled) return;
          setSteps(all);
          trajFetchedRef.current = true;
          setTrajNote(
            all.length ? null : "No trajectory.jsonl steps for this Attempt.",
          );
        } catch (e) {
          if (!cancelled) {
            setTrajNote(e instanceof Error ? e.message : String(e));
          }
        } finally {
          if (!cancelled) setTrajLoading(false);
        }
      })();
      return () => {
        cancelled = true;
      };
    }

    const scope = scopeForTab(activeTab);
    if (!scope) return;
    setTreeLoading(true);
    setSelectedPath(null);
    setFileContent(null);
    setFileNote(null);
    setTreeGroups(null);
    try {
      const { entries, groups } = treeEntriesForScope(
        relFiles,
        scope,
        invProfileByDir,
      );
      setTree(entries);
      setTreeGroups(groups);
      const preferred =
        entries.find((e) => e.name === "lock.json") ||
        entries.find((e) => e.name === "result.json") ||
        entries.find((e) => e.name.endsWith(".json")) ||
        entries[0];
      if (preferred) setSelectedPath(preferred.path);
    } catch (e) {
      setFileNote(e instanceof Error ? e.message : String(e));
    } finally {
      setTreeLoading(false);
    }
    return () => {
      cancelled = true;
    };
  }, [activeTab, runId, token, relFiles, invProfileByDir]);

  // File preview (rel path → archive path)
  useEffect(() => {
    if (!selectedPath || !runId) return;
    let cancelled = false;
    setFileLoading(true);
    setFileNote(null);
    getAttemptFile(runId, toArchivePath(selectedPath, runId), token)
      .then((f) => {
        if (cancelled) return;
        setFileContent(decodeFileContent(f));
        if (f.truncated) setFileNote("truncated");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setFileContent(null);
        if (err instanceof RegistryHttpError) {
          setFileNote(`${err.code}: ${err.message}`);
        } else {
          setFileNote(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setFileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedPath, runId, token]);

  const runCommand = useMemo(() => {
    const db = meta?.dataset_id;
    const t = trial?.task_id || taskId;
    if (db && t) return `ageval run ${db} --task ${t}`;
    if (t) return `ageval run <dataset> --task ${t}`;
    return "";
  }, [meta, trial, taskId]);

  return {
    meta,
    trial,
    result,
    runCommand,
    error,
    loading,
    activeTab,
    setActiveTab,
    availableTabs: availableTabs.length
      ? availableTabs
      : availableTabsFromPaths(relFiles.map((f) => f.path)),
    steps,
    trajNote,
    trajLoading,
    observationSteps,
    obsNote,
    obsLoading,
    checks,
    checksNote,
    checksLoading,
    tree,
    treeGroups,
    treeLoading,
    selectedPath,
    setSelectedPath,
    fileContent,
    fileNote,
    fileLoading,
  };
}
