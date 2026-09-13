import { useLayoutEffect, useRef, useState } from "react";

import { UnderlineTabs } from "@ageval/shared/components/underline-tabs";
import { revealTallPanel } from "@ageval/shared/lib/scroll-port";
import type { TrajectoryStep, TreeEntry, Trial } from "@ageval/shared/lib/trial-types";

import { FileSplitPanel } from "./file-split-panel";
import { TAB_LABELS, type TabId } from "./tabs";
import { TrajectoryPanel } from "./trajectory-panel";

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
}) {
  const verifierSteps = observationSteps || [];
  const showVerifierTrajectory =
    activeTab === "verifier" && (obsLoading || verifierSteps.length > 0);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [revealGen, setRevealGen] = useState(0);

  useLayoutEffect(() => {
    if (revealGen === 0) return;
    const pending =
      (activeTab === "trajectory" && trajLoading) ||
      (activeTab === "verifier" && !!obsLoading) ||
      (activeTab != null &&
        activeTab !== "trajectory" &&
        !showVerifierTrajectory &&
        treeLoading);
    if (pending) return;
    const panel = panelRef.current;
    if (!panel) return;
    revealTallPanel(panel);
  }, [
    revealGen,
    activeTab,
    trajLoading,
    obsLoading,
    treeLoading,
    showVerifierTrajectory,
  ]);

  if (availableTabs.length === 0) {
    return (
      <p className="text-sm text-mute">
        No evidence tabs for this uploaded Attempt archive.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {activeTab ? (
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
      ) : null}

      {activeTab === "trajectory" && (
        <TrajectoryPanel
          loading={trajLoading}
          steps={steps}
          note={trajNote}
          result={result}
          actors={actors}
          panelRef={panelRef}
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

      {activeTab && activeTab !== "trajectory" && !showVerifierTrajectory && (
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
