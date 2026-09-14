import { useEffect, useMemo, useRef, useState } from "react";

import {
  FIRST_TAB_ORDER,
  normalizeTabId,
  TAB_ORDER,
  TREE_SCOPES,
  type TabId,
} from "@ageval/shared/components/trial/tabs";
import {
  fetchTrial,
  fetchTrialFile,
  fetchTrialObservation,
  fetchTrialTrajectory,
  fetchTrialTree,
  type Job,
  type TrajectoryStep,
  type TreeEntry,
  type Trial,
} from "@/lib/api";

export function useTrialDetail(jobId: string, taskId: string, runId: string) {
  const [trial, setTrial] = useState<Trial | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [siblingRunIds, setSiblingRunIds] = useState<string[]>([]);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [runCommand, setRunCommand] = useState("");
  const [prevId, setPrevId] = useState<string | null>(null);
  const [nextId, setNextId] = useState<string | null>(null);
  const [slotCurrentRunId, setSlotCurrentRunId] = useState<string | null>(null);
  const [slotCurrentStartedAt, setSlotCurrentStartedAt] = useState<string | null>(
    null,
  );
  const [slotPrevious, setSlotPrevious] = useState<
    Array<{
      run_id?: string | null;
      status?: string | null;
      started_at?: string | null;
      replaced_at?: string | null;
    }>
  >([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<TabId | null>(null);

  const [steps, setSteps] = useState<TrajectoryStep[]>([]);
  const [trajNote, setTrajNote] = useState<string | null>(null);
  const [trajLoading, setTrajLoading] = useState(false);
  const [observationSteps, setObservationSteps] = useState<TrajectoryStep[]>([]);
  const [obsNote, setObsNote] = useState<string | null>(null);
  const [obsLoading, setObsLoading] = useState(false);

  const [tree, setTree] = useState<TreeEntry[]>([]);
  const [treeGroups, setTreeGroups] = useState<
    Array<{ key: string; profile_id?: string | null; label?: string }> | null
  >(null);
  const [treeLoading, setTreeLoading] = useState(false);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileNote, setFileNote] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const trajFetchedRef = useRef(false);
  const obsFetchedRef = useRef(false);

  const availableTabs = useMemo(() => {
    const raw = (trial?.available_tabs || []) as string[];
    const normalized = raw.map(normalizeTabId);
    return TAB_ORDER.filter((t) => normalized.includes(t));
  }, [trial]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setActiveTab(null);
    setSteps([]);
    trajFetchedRef.current = false;
    obsFetchedRef.current = false;
    setTree([]);
    setSelectedPath(null);
    setFileContent(null);
    fetchTrial(jobId, taskId, runId)
      .then((data) => {
        if (cancelled) return;
        setTrial(data.trial);
        setJob(data.job || null);
        setSiblingRunIds(data.sibling_run_ids || []);
        setResult(data.result || null);
        setRunCommand(data.run_command || "");
        setPrevId(data.prev_run_id || null);
        setNextId(data.next_run_id || null);
        setSlotCurrentRunId(data.slot_current_run_id || null);
        setSlotCurrentStartedAt(data.slot_current_started_at || null);
        setSlotPrevious(data.slot_previous || []);
        setError(null);
        const tabs = (data.trial.available_tabs || []).map(normalizeTabId) as TabId[];
        const first = FIRST_TAB_ORDER.find((t) => tabs.includes(t)) || null;
        setActiveTab(first);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, taskId, runId]);

  useEffect(() => {
    if (!activeTab || !jobId || !taskId || !runId) return;
    let cancelled = false;

    if (activeTab === "trajectory") {
      if (trajFetchedRef.current) return;
      setTrajLoading(true);
      fetchTrialTrajectory(jobId, taskId, runId)
        .then((data) => {
          if (cancelled) return;
          setSteps(data.steps || []);
          trajFetchedRef.current = true;
          setTrajNote(data.note || null);
        })
        .catch((e: Error) => {
          if (!cancelled) setTrajNote(e.message);
        })
        .finally(() => {
          if (!cancelled) setTrajLoading(false);
        });
      return () => {
        cancelled = true;
      };
    }

    if (activeTab === "verifier") {
      if (!obsFetchedRef.current) {
        setObsLoading(true);
        fetchTrialObservation(jobId, taskId, runId)
          .then((data) => {
            if (cancelled) return;
            setObservationSteps(data.steps || []);
            obsFetchedRef.current = true;
            setObsNote(data.note || null);
          })
          .catch((e: Error) => {
            if (!cancelled) {
              setObservationSteps([]);
              setObsNote(e.message);
            }
          })
          .finally(() => {
            if (!cancelled) setObsLoading(false);
          });
      }
    }

    const scope = TREE_SCOPES[activeTab];
    if (!scope) return;
    setTreeLoading(true);
    setSelectedPath(null);
    setFileContent(null);
    setFileNote(null);
    setTreeGroups(null);
    fetchTrialTree(jobId, taskId, runId, scope)
      .then((data) => {
        if (cancelled) return;
        const files = (data.entries || []).filter((e) => e.type === "file");
        setTree(files);
        setTreeGroups(data.groups || null);
        // Auto-open a sensible default file
        const preferred =
          files.find((f) => f.name === "lock.json") ||
          files.find((f) => f.name === "result.json") ||
          files.find((f) => f.name.endsWith(".json")) ||
          files[0];
        if (preferred) {
          setSelectedPath(preferred.path);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setFileNote(e.message);
      })
      .finally(() => {
        if (!cancelled) setTreeLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, jobId, taskId, runId]);

  useEffect(() => {
    if (!selectedPath || !jobId || !taskId || !runId) return;
    let cancelled = false;
    setFileLoading(true);
    fetchTrialFile(jobId, taskId, runId, selectedPath)
      .then((data) => {
        if (cancelled) return;
        setFileContent(data.content ?? null);
        setFileNote(data.note || (data.truncated ? "truncated preview" : null));
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setFileContent(null);
          setFileNote(e.message);
        }
      })
      .finally(() => {
        if (!cancelled) setFileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedPath, jobId, taskId, runId]);

  return {
    trial,
    job,
    siblingRunIds,
    result,
    runCommand,
    prevId,
    nextId,
    slotCurrentRunId,
    slotCurrentStartedAt,
    slotPrevious,
    error,
    loading,
    activeTab,
    setActiveTab,
    availableTabs,
    steps,
    trajNote,
    trajLoading,
    observationSteps,
    obsNote,
    obsLoading,
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
