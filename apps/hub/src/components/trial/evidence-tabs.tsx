import { useLayoutEffect, useRef, useState } from "react";

import { UnderlineTabs } from "@/components/underline-tabs";
import { revealTallPanel } from "@ageval/shared/scroll-port";
import type { TrajectoryStep, TreeEntry, Trial } from "@/lib/trial-types";

import { ChecksPanel, type EvaluationCheck } from "./checks-panel";
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
  checks,
  checksLoading,
  checksNote,
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
  checks?: EvaluationCheck[];
  checksLoading?: boolean;
  checksNote?: string | null;
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
}) {
  const verifierSteps = observationSteps || [];
  const verifierChecks = checks || [];
  const verifierTab = activeTab === "verifier";
  const showVerifierTrajectory = verifierTab && (obsLoading || verifierSteps.length > 0);
  const showVerifierChecks =
    verifierTab && (checksLoading || verifierChecks.length > 0);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [revealGen, setRevealGen] = useState(0);

  useLayoutEffect(() => {
    if (revealGen === 0) return;
    const pending =
      (activeTab === "trajectory" && trajLoading) ||
      (verifierTab && (!!obsLoading || !!checksLoading || treeLoading));
    if (pending) return;
    const panel = panelRef.current;
    if (!panel) return;
    revealTallPanel(panel);
  }, [
    revealGen,
    activeTab,
    trajLoading,
    obsLoading,
    checksLoading,
    treeLoading,
    verifierTab,
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

      {verifierTab && (
        <div className="space-y-3">
          {showVerifierChecks && (
            <ChecksPanel
              loading={!!checksLoading}
              checks={verifierChecks}
              note={checksNote ?? null}
              taskId={taskId || ""}
              loadScript={loadScript}
            />
          )}
          {showVerifierTrajectory && (
            <TrajectoryPanel
              loading={!!obsLoading}
              steps={verifierSteps}
              note={obsNote ?? null}
              result={result}
              actors={[]}
            />
          )}
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
          />
        </div>
      )}

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
