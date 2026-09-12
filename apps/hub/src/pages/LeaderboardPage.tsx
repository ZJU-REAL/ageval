import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { CatalogScopeBar } from "@/components/catalog-scope-bar";
import { CatalogEmpty, CatalogLoading } from "@/components/empty-state";
import { PageHead } from "@/components/page-head";
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

type PlazaView = "dataset" | "agent" | "model";

const VIEW_ITEMS = [
  { id: "dataset" as const, label: "Dataset" },
  { id: "agent" as const, label: "Agent" },
  { id: "model" as const, label: "Model" },
];

function parseView(raw: string | null): PlazaView {
  if (raw === "agent" || raw === "model") return raw;
  return "dataset";
}

export function LeaderboardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const view = parseView(searchParams.get("view"));
  const [query, setQuery] = useState("");
  const [suites, setSuites] = useState<SuiteRow[]>([]);
  const [performances, setPerformances] = useState<AgentPerformance[]>([]);
  const [datasets, setDatasets] = useState<PackageRelease[]>([]);
  const [agents, setAgents] = useState<PackageRelease[]>([]);
  const [orgs, setOrgs] = useState<Map<string, OrgRow>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const token = getToken();
  const chromeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      listSuites(null, token, { board: true }),
      listPerformances(token),
      listPackages(token, { packageKind: "dataset", visibility: "public" }),
      listPackages(token, { packageKind: "agent", visibility: "public" }),
      token ? listOrgs(token).catch(() => [] as OrgRow[]) : Promise.resolve([] as OrgRow[]),
    ])
      .then(([board, rows, datasetPacks, agentPacks, orgRows]) => {
        if (cancelled) return;
        setSuites(board);
        setPerformances(rows);
        setDatasets(datasetPacks);
        setAgents(agentPacks);
        setOrgs(new Map(orgRows.map((org) => [org.org_id, org])));
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof RegistryHttpError) {
          setError(`${err.code}: ${err.message}`);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
        setSuites([]);
        setPerformances([]);
        setDatasets([]);
        setAgents([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

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
  }, [view, loading]);

  const q = query.trim().toLowerCase();
  const datasetPacks = useMemo(() => latestPackageByDataset(datasets), [datasets]);

  const visibleSuites = useMemo(() => {
    if (!q) return suites;
    return suites.filter((suite) => {
      const pack = datasetPacks.find((row) => row.dataset_id === suite.dataset_id);
      const hay = [
        suite.dataset_id,
        pack?.display_name,
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

  function setView(next: PlazaView) {
    const n = new URLSearchParams(searchParams);
    if (next === "dataset") n.delete("view");
    else n.set("view", next);
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
        <UnderlineTabs
          className="mb-3 shrink-0"
          ariaLabel="Leaderboard view"
          items={VIEW_ITEMS}
          value={view}
          onChange={setView}
        />
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
          <p className="mb-3 text-xs text-mute">
            Observational metrics on each row — not PASS, not comparable across
            datasets · click headers to sort
          </p>
          {view === "dataset" ? (
            <PlazaDatasetTables
              suites={visibleSuites}
              datasets={datasets}
              orgs={orgs}
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
