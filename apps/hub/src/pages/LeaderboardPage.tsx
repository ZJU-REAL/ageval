import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Bot, Boxes, Database } from "lucide-react";
import { useSearchParams } from "react-router-dom";

import { BoardChartControls } from "@/components/board-chart-controls";
import { CatalogScopeBar } from "@/components/catalog-scope-bar";
import { CatalogEmpty, CatalogLoading } from "@/components/empty-state";
import { PageHead } from "@/components/page-head";
import { WaffleLegend } from "@/components/leaderboard-waffle";
import {
  PLAZA_CHROME_ID,
  PLAZA_PIN_SLOT_ID,
  PlazaAgentTables,
  PlazaDatasetTables,
  PlazaModelTables,
  plazaModelRowCount,
} from "@/components/plaza-tables";
import { UnderlineTabs } from "@/components/underline-tabs";
import {
  latestPackageByDataset,
  listOrgs,
  listPackages,
  listPerformances,
  listSuites,
  type AgentPerformance,
  type OrgRow,
  type PackageRelease,
  type SuiteRow,
  RegistryHttpError,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import {
  parseBoardChart,
  parseParetoAxis,
  type BoardChart,
  type ParetoAxis,
} from "@/lib/leaderboard-charts";

type PlazaView = "dataset" | "agent" | "model";

const VIEW_ITEMS = [
  { id: "dataset" as const, label: "Dataset", icon: Database, glyph: "datasets" as const },
  { id: "agent" as const, label: "Agent", icon: Bot, glyph: "agents" as const },
  { id: "model" as const, label: "Model", icon: Boxes, glyph: "models" as const },
];

function parseView(raw: string | null): PlazaView {
  if (raw === "agent" || raw === "model") return raw;
  return "dataset";
}

function formatErr(err: unknown): string {
  if (err instanceof RegistryHttpError) return `${err.code}: ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

export function LeaderboardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const view = parseView(searchParams.get("view"));
  const boardChart = parseBoardChart(searchParams.get("chart"));
  const paretoAxis = parseParetoAxis(searchParams.get("axis"));
  const [query, setQuery] = useState("");
  const [suites, setSuites] = useState<SuiteRow[]>([]);
  const [performances, setPerformances] = useState<AgentPerformance[]>([]);
  const [datasets, setDatasets] = useState<PackageRelease[]>([]);
  const [agents, setAgents] = useState<PackageRelease[]>([]);
  const [orgs, setOrgs] = useState<Map<string, OrgRow>>(new Map());
  const [boardError, setBoardError] = useState<string | null>(null);
  const [perfError, setPerfError] = useState<string | null>(null);
  const [boardLoading, setBoardLoading] = useState(true);
  const [perfLoading, setPerfLoading] = useState(false);
  const token = getToken();
  const chromeRef = useRef<HTMLDivElement>(null);
  const perfOnce = useRef(false);

  useEffect(() => {
    perfOnce.current = false;
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    setBoardLoading(true);
    Promise.all([
      listSuites(null, token, { board: true }),
      listPackages(token, { packageKind: "dataset", visibility: "public" }),
      token ? listOrgs(token).catch(() => [] as OrgRow[]) : Promise.resolve([] as OrgRow[]),
    ])
      .then(([board, datasetPacks, orgRows]) => {
        if (cancelled) return;
        setSuites(board);
        setDatasets(datasetPacks);
        setOrgs(new Map(orgRows.map((org) => [org.org_id, org])));
        setBoardError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setBoardError(formatErr(err));
        setSuites([]);
        setDatasets([]);
      })
      .finally(() => {
        if (!cancelled) setBoardLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (view === "dataset") return;
    if (perfOnce.current) return;
    let cancelled = false;
    setPerfLoading(true);
    Promise.all([
      listPerformances(token),
      listPackages(token, { packageKind: "agent", visibility: "public" }),
    ])
      .then(([rows, agentPacks]) => {
        if (cancelled) return;
        perfOnce.current = true;
        setPerformances(rows);
        setAgents(agentPacks);
        setPerfError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setPerfError(formatErr(err));
        setPerformances([]);
        setAgents([]);
      })
      .finally(() => {
        if (!cancelled) setPerfLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, view]);

  useLayoutEffect(() => {
    const chrome = chromeRef.current;
    const scroller = document.getElementById("main");
    if (!chrome || !scroller) return;
    const apply = () => {
      scroller.style.setProperty(
        "--leaderboard-stick-top",
        `${chrome.offsetHeight}px`,
      );
    };
    const ro = new ResizeObserver(apply);
    ro.observe(chrome);
    window.addEventListener("resize", apply);
    apply();
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", apply);
      scroller.style.removeProperty("--leaderboard-stick-top");
    };
  }, [view, boardChart, paretoAxis, boardLoading, perfLoading]);

  const q = query.trim().toLowerCase();
  const datasetPacks = useMemo(() => latestPackageByDataset(datasets), [datasets]);

  const visibleSuites = useMemo(() => {
    if (!q) return suites;
    return suites.filter((suite) => {
      const pack = datasetPacks.find((row) => row.dataset_id === suite.dataset_id);
      const hay = [
        suite.dataset_id,
        pack?.display_name,
        pack?.description,
        suite.agent_label,
        suite.model_label,
        ...(suite.agent_refs || []).map((ref) => ref.package_id),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [suites, datasetPacks, q]);

  const visiblePerformances = useMemo(() => {
    if (!q) return performances;
    return performances.filter((row) => {
      const hay = [row.package_id, row.dataset_id, row.role, row.model, row.canonical_model]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [performances, q]);

  const visibleCount =
    view === "dataset"
      ? visibleSuites.length
      : view === "agent"
        ? visiblePerformances.length
        : plazaModelRowCount(visiblePerformances);
  const loading = view === "dataset" ? boardLoading : perfLoading;
  const error = view === "dataset" ? boardError : perfError;

  function setView(next: PlazaView) {
    const n = new URLSearchParams(searchParams);
    if (next === "dataset") n.delete("view");
    else n.set("view", next);
    setSearchParams(n, { replace: true });
  }

  function setBoardChart(next: BoardChart) {
    const n = new URLSearchParams(searchParams);
    n.delete("view");
    if (next === "table") n.delete("chart");
    else n.set("chart", next);
    if (next !== "pareto") n.delete("axis");
    setSearchParams(n, { replace: true });
  }

  function setParetoAxis(next: ParetoAxis) {
    const n = new URLSearchParams(searchParams);
    n.delete("view");
    n.set("chart", "pareto");
    if (next === "cost") n.delete("axis");
    else n.set("axis", next);
    setSearchParams(n, { replace: true });
  }

  return (
    <>
      <PageHead
        title="Leaderboard"
        sub="Index of listed Dataset suites and Agent / Model Performance. Observational metrics only — not PASS, not comparable across datasets."
      />

      <div
        id={PLAZA_CHROME_ID}
        ref={chromeRef}
        className="relative sticky top-0 z-20 flex flex-col -mx-4 -mt-5 bg-canvas px-4 pt-0 sm:-mx-6 sm:px-6"
      >
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-full h-24 bg-canvas"
        />
        <CatalogScopeBar
          variant="search"
          query={query}
          onQuery={setQuery}
          searchLabel="Search leaderboard"
          searchPlaceholder="Search leaderboard…"
          className="mb-3"
        />
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <UnderlineTabs
            className="shrink-0"
            ariaLabel="Leaderboard view"
            items={VIEW_ITEMS}
            value={view}
            onChange={setView}
          />
          {view === "dataset" ? (
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <BoardChartControls
                chart={boardChart}
                axis={paretoAxis}
                onChart={setBoardChart}
                onAxis={setParetoAxis}
              />
            </div>
          ) : null}
        </div>
        <div
          id={PLAZA_PIN_SLOT_ID}
          className="bg-canvas pt-3 pb-3 empty:hidden"
        />
      </div>

      {loading ? (
        <CatalogLoading kind="leaderboard" />
      ) : error ? (
        <div className="blob-panel p-4 text-sm text-body">
          <p className="text-error font-medium">Could not load leaderboard</p>
          <p className="mt-1 text-xs">{error}</p>
        </div>
      ) : visibleCount === 0 ? (
        <CatalogEmpty
          kind="leaderboard"
          scope="explore"
          signedIn={Boolean(token)}
          searching={Boolean(q)}
          onExplore={() => setQuery("")}
          onClearSearch={() => setQuery("")}
        />
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-mute">
            <span>
              {view === "dataset" && boardChart === "waffle"
                ? "Each square is one trial. Click a square with uploaded Attempt evidence to open that job. Observational, not PASS, not comparable across datasets."
                : view === "dataset" && boardChart === "pareto"
                  ? "Pass rate versus suite cost, tokens, or time. Observational, not PASS, not comparable across datasets."
                  : "Observational metrics on each row — not PASS, not comparable across datasets · click headers to sort"}
            </span>
            {view === "dataset" && boardChart === "waffle" ? <WaffleLegend /> : null}
          </div>
          {view === "dataset" ? (
            <PlazaDatasetTables
              suites={visibleSuites}
              datasets={datasets}
              chart={boardChart}
              axis={paretoAxis}
            />
          ) : view === "agent" ? (
            <PlazaAgentTables
              rows={visiblePerformances}
              agents={agents}
              orgs={orgs}
            />
          ) : (
            <PlazaModelTables rows={visiblePerformances} />
          )}
        </>
      )}
    </>
  );
}
