import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  CatalogScopeBar,
  DATASET_SCOPE_ITEMS,
  catalogListOpts,
  catalogScopeFromSearch,
  catalogScopeSearch,
  type CatalogScope,
} from "@/components/catalog-scope-bar";
import {
  DATASET_ORG_CHROME_ID,
  DATASET_ORG_PIN_SLOT_ID,
  DatasetOrgTables,
} from "@/components/dataset-org-tables";
import {
  CatalogEmpty,
  CatalogLoading,
} from "@/components/catalog-empty";
import { PageHead } from "@/components/page-head";
import { TableColumnPicker } from "@ageval/shared/components/ui/table-column-picker";
import { useTableColumns } from "@ageval/shared/hooks/use-table-columns";
import {
  isDatasetPackage,
  latestPackageByDataset,
  listOrgs,
  listPackages,
  packageDisplayTitle,
  type OrgRow,
  type PackageRelease,
  RegistryHttpError,
} from "@/lib/api";
import { getToken } from "@/lib/auth";

const DATASET_OPTIONAL_COLUMNS = [
  { id: "updated", label: "Updated" },
] as const;
const DATASET_OPTIONAL_IDS = DATASET_OPTIONAL_COLUMNS.map((col) => col.id);
const DATASET_OPTIONAL_DEFAULT: typeof DATASET_OPTIONAL_IDS = ["updated"];

export function DatasetsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const scope = catalogScopeFromSearch(searchParams, false);

  const [items, setItems] = useState<PackageRelease[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [columns, setColumns] = useTableColumns(
    "ageval.hub.columns.datasets",
    DATASET_OPTIONAL_IDS,
    DATASET_OPTIONAL_DEFAULT,
  );
  const [orgs, setOrgs] = useState<Map<string, OrgRow>>(new Map());
  const token = getToken();
  const needsAuth = scope === "orgs";

  useEffect(() => {
    if (needsAuth && !token) {
      setItems([]);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    listPackages(token, { packageKind: "dataset", ...catalogListOpts(scope) })
      .then((rows) => {
        if (cancelled) return;
        setItems(rows.filter(isDatasetPackage));
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof RegistryHttpError) {
          setError(`${err.code}: ${err.message}`);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
        setItems([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, scope, needsAuth]);

  useEffect(() => {
    if (!token) {
      setOrgs(new Map());
      return;
    }
    let cancelled = false;
    listOrgs(token)
      .then((rows) => {
        if (cancelled) return;
        setOrgs(new Map(rows.map((org) => [org.org_id, org])));
      })
      .catch(() => {
        if (!cancelled) setOrgs(new Map());
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const datasets = useMemo(() => {
    const latest = latestPackageByDataset(items);
    const q = query.trim().toLowerCase();
    if (!q) return latest;
    return latest.filter(
      (r) =>
        r.dataset_id.toLowerCase().includes(q) ||
        packageDisplayTitle(r.dataset_id, r.display_name)
          .toLowerCase()
          .includes(q) ||
        (r.org_id && r.org_id.toLowerCase().includes(q)),
    );
  }, [items, query]);

  function setScope(next: CatalogScope) {
    setSearchParams(catalogScopeSearch(next), { replace: true });
  }

  const chromeRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const chrome = chromeRef.current;
    const scroller = document.getElementById("main");
    if (!chrome || !scroller) return;
    const apply = () => {
      scroller.style.setProperty(
        "--datasets-stick-top",
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
      scroller.style.removeProperty("--datasets-stick-top");
    };
  }, []);

  return (
    <>
      <PageHead
        title={scope === "orgs" ? "Your datasets" : "Explore datasets"}
        sub={
          scope === "orgs"
            ? "Packages published by organizations you belong to."
            : "Public packages on this Registry."
        }
      />

      <div
        id={DATASET_ORG_CHROME_ID}
        ref={chromeRef}
        className="relative sticky top-0 z-20 flex flex-col -mx-4 -mt-5 bg-canvas px-4 pt-0 sm:-mx-6 sm:px-6"
      >
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-full h-24 bg-canvas"
        />
        <CatalogScopeBar
          variant="select"
          scope={scope}
          onScope={setScope}
          items={DATASET_SCOPE_ITEMS}
          query={query}
          onQuery={setQuery}
          searchLabel="Search datasets"
          searchPlaceholder="Search datasets…"
          end={
            <TableColumnPicker
              options={DATASET_OPTIONAL_COLUMNS}
              value={columns}
              onChange={setColumns}
              ariaLabel="Optional dataset columns"
            />
          }
          className="mb-3"
        />
        <div
          id={DATASET_ORG_PIN_SLOT_ID}
          className="bg-canvas pt-3 pb-3 empty:hidden"
        />
      </div>

      {scope === "orgs" && !token ? (
        <CatalogEmpty
          kind="dataset"
          scope={scope}
          signedIn={false}
          searching={false}
          onExplore={() => setScope("explore")}
          onClearSearch={() => setQuery("")}
        />
      ) : loading ? (
        <CatalogLoading kind="dataset" />
      ) : error ? (
        <div className="blob-panel p-4 text-sm text-body">
          <p className="text-error font-medium">Could not load packages</p>
          <p className="mt-1 text-xs">{error}</p>
        </div>
      ) : datasets.length === 0 ? (
        <CatalogEmpty
          kind="dataset"
          scope={scope}
          signedIn={Boolean(token)}
          searching={Boolean(query.trim())}
          onExplore={() => setScope("explore")}
          onClearSearch={() => setQuery("")}
        />
      ) : (
        <>
          <DatasetOrgTables
            rows={datasets}
            orgs={orgs}
            showUpdated={columns.includes("updated")}
          />
          <p className="mt-3 text-xs text-mute tabular-nums">
            {datasets.length} dataset{datasets.length === 1 ? "" : "s"}
          </p>
        </>
      )}
    </>
  );
}
