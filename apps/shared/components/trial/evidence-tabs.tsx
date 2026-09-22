import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { UnderlineTabs } from "@ageval/shared/components/underline-tabs";
import {
  alignInScrollParent,
  revealTallPanel,
} from "@ageval/shared/lib/scroll-port";
import type { TrajectoryStep, TreeEntry, Trial } from "@ageval/shared/lib/trial-types";
import { cn } from "@ageval/shared/lib/utils";

import { FileSplitPanel } from "./file-split-panel";
import { TAB_LABELS, type TabId } from "./tabs";
import {
  TrajectoryKindFilter,
  TrajectoryPanel,
  type TrajectoryKind,
} from "./trajectory-panel";

type VerifierSurface = "trajectory" | "files";

function treeHasFile(tree: TreeEntry[], name: string): boolean {
  return tree.some((entry) => {
    if (entry.type === "dir") return false;
    if (entry.name === name) return true;
    return entry.path === name || entry.path.endsWith(`/${name}`);
  });
}

function VerifierSurfaceToggle({
  value,
  onChange,
}: {
  value: VerifierSurface;
  onChange: (next: VerifierSurface) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Verifier surface"
      className="inline-flex shrink-0 items-center gap-0.5 rounded-[8px] border border-hairline p-0.5"
    >
      {(
        [
          ["trajectory", "Trajectory"],
          ["files", "Files"],
        ] as const
      ).map(([id, label]) => (
        <button
          key={id}
          type="button"
          aria-pressed={value === id}
          onClick={() => onChange(id)}
          className={cn(
            "rounded-[6px] px-2.5 py-1 text-sm transition-colors duration-200 ease-smooth",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70",
            value === id
              ? "bg-canvas-soft-2 text-ink"
              : "text-body hover:bg-canvas-soft",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export function EvidenceTabs({
  availableTabs,
  activeTab,
  onTabChange,
  trajLoading,
  steps,
  trajNote,
  observationSteps,
  obsLoading,
  obsNote,
  taskId,
  loadScript,
  result,
  actors,
  tree,
  treeLoading,
  selectedPath,
  onSelectPath,
  fileContent,
  fileLoading,
  fileNote,
  treeGroups,
  emptyNote = "No evidence tabs for this uploaded Attempt archive.",
}: {
  availableTabs: TabId[];
  activeTab: TabId | null;
  onTabChange: (tab: TabId) => void;
  trajLoading: boolean;
  steps: TrajectoryStep[];
  trajNote: string | null;
  observationSteps?: TrajectoryStep[];
  obsLoading?: boolean;
  obsNote?: string | null;
  taskId?: string;
  loadScript?: (
    packagePath: string,
  ) => Promise<{ content: string | null; note?: string | null }>;
  result: Record<string, unknown> | null;
  actors: NonNullable<Trial["actors"]>;
  tree: TreeEntry[];
  treeLoading: boolean;
  selectedPath: string | null;
  onSelectPath: (path: string) => void;
  fileContent: string | null;
  fileLoading: boolean;
  fileNote: string | null;
  treeGroups: Array<{
    key: string;
    profile_id?: string | null;
    label?: string;
  }> | null;
  emptyNote?: string;
}) {
  const verifierSteps = observationSteps || [];
  const verifierTab = activeTab === "verifier";
  const hasJudge =
    treeHasFile(tree, "observation.jsonl") || verifierSteps.length > 0;
  const hasChecks = treeHasFile(tree, "checks.json");
  const dualVerifier = hasJudge && hasChecks;
  const [surface, setSurface] = useState<VerifierSurface>("trajectory");
  const [kind, setKind] = useState<TrajectoryKind>("all");
  const showVerifierTrajectory = verifierTab && (dualVerifier ? surface === "trajectory" : hasJudge);
  const showVerifierFiles = verifierTab && (dualVerifier ? surface === "files" : !hasJudge);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [revealGen, setRevealGen] = useState(0);

  useEffect(() => {
    if (verifierTab) setSurface("trajectory");
  }, [verifierTab]);

  useEffect(() => {
    setKind("all");
  }, [steps]);

  useLayoutEffect(() => {
    if (revealGen === 0) return;
    const pending =
      (activeTab === "trajectory" && trajLoading) ||
      (showVerifierTrajectory && !!obsLoading) ||
      (showVerifierFiles && treeLoading);
    if (pending) return;
    const panel = panelRef.current;
    if (!panel) return;
    if (verifierTab) {
      alignInScrollParent(panel, "start");
      return;
    }
    revealTallPanel(panel);
  }, [
    revealGen,
    activeTab,
    trajLoading,
    obsLoading,
    treeLoading,
    verifierTab,
    showVerifierTrajectory,
    showVerifierFiles,
  ]);

  if (availableTabs.length === 0) {
    return (
      <p className="text-sm text-mute">{emptyNote}</p>
    );
  }

  const filesPanel = (
    <FileSplitPanel
      tree={tree}
      treeLoading={treeLoading}
      selectedPath={selectedPath}
      onSelect={onSelectPath}
      fileContent={fileContent}
      fileLoading={fileLoading}
      fileNote={fileNote}
      groupByProfile={false}
      actors={actors}
      apiGroups={treeGroups}
      panelRef={panelRef}
      taskId={taskId}
      loadScript={loadScript}
    />
  );

  return (
    <div className="space-y-3">
      {activeTab ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <UnderlineTabs
            ariaLabel="Evidence tabs"
            value={activeTab}
            onChange={(tab) => {
              onTabChange(tab);
              setRevealGen((n) => n + 1);
            }}
            items={availableTabs.map((tab) => ({
              id: tab,
              label: TAB_LABELS[tab],
            }))}
          />
          {activeTab === "trajectory" ? (
            <TrajectoryKindFilter steps={steps} value={kind} onChange={setKind} />
          ) : verifierTab && dualVerifier ? (
            <VerifierSurfaceToggle value={surface} onChange={setSurface} />
          ) : null}
        </div>
      ) : null}

      {activeTab === "trajectory" && (
        <TrajectoryPanel
          loading={trajLoading}
          steps={steps}
          note={trajNote}
          result={result}
          actors={actors}
          panelRef={panelRef}
          kind={kind}
        />
      )}

      {showVerifierTrajectory && (
        <TrajectoryPanel
          loading={!!obsLoading}
          steps={verifierSteps}
          note={obsNote ?? null}
          result={result}
          actors={[]}
          panelRef={panelRef}
        />
      )}

      {showVerifierFiles ? filesPanel : null}

      {activeTab && activeTab !== "trajectory" && activeTab !== "verifier" && (
        <FileSplitPanel
          tree={tree}
          treeLoading={treeLoading}
          selectedPath={selectedPath}
          onSelect={onSelectPath}
          fileContent={fileContent}
          fileLoading={fileLoading}
          fileNote={fileNote}
          groupByProfile={activeTab === "agent"}
          actors={actors}
          apiGroups={treeGroups}
          panelRef={panelRef}
        />
      )}
    </div>
  );
}
