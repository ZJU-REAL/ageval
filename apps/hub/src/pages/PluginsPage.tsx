import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { CatalogCardGrid } from "@/components/catalog-card";
import {
  CatalogScopeBar,
  MARKETPLACE_SCOPE_ITEMS,
  catalogScopeFromSearch,
  catalogScopeSearch,
  type CatalogScope,
} from "@/components/catalog-scope-bar";
import {
  CatalogEmpty,
  CatalogLoading,
} from "@/components/catalog-empty";
import { PageHead } from "@/components/page-head";
import { useCatalogList } from "@/hooks/use-catalog-list";
import { encodeDatasetId, latestPackageByDataset } from "@/lib/api";
import { getToken } from "@/lib/auth";

export function PluginsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const scope = catalogScopeFromSearch(searchParams);

  const [query, setQuery] = useState("");
  const token = getToken();
  const needsAuth = scope === "orgs" || scope === "favorites";
  const { items, error, loading } = useCatalogList(
    "plugin",
    scope,
    token,
    needsAuth,
  );

  const plugins = useMemo(() => {
    const latest = latestPackageByDataset(items);
    const q = query.trim().toLowerCase();
    if (!q) return latest;
    return latest.filter(
      (r) =>
        r.dataset_id.toLowerCase().includes(q) ||
        (r.org_id && r.org_id.toLowerCase().includes(q)) ||
        (r.plugin_preview?.description || "").toLowerCase().includes(q),
    );
  }, [items, query]);

  function setScope(next: CatalogScope) {
    setSearchParams(catalogScopeSearch(next), { replace: true });
  }

  function openPlugin(id: string) {
    navigate(`/plugins/${encodeDatasetId(id)}`);
  }

  const signedOut = (scope === "orgs" || scope === "favorites") && !token;

  return (
    <>
      <PageHead
        title="Plugin marketplace"
        sub={
          <>
            Browse <code className="font-mono text-xs">ageval.plugin/1</code>{" "}
            packages. Install is CLI-only (Recognition only — does not change
            profiles).
          </>
        }
      />

      <div className="flex min-h-0 flex-1 flex-col">
        <div className="shrink-0 pb-3">
          <CatalogScopeBar
            variant="select"
            scope={scope}
            onScope={setScope}
            items={MARKETPLACE_SCOPE_ITEMS}
            query={query}
            onQuery={setQuery}
            searchLabel="Search plugins"
            searchPlaceholder="Search plugins…"
            className="mb-0"
          />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {signedOut || loading || error || plugins.length === 0 ? (
        signedOut ? (
          <CatalogEmpty
            kind="plugin"
            scope={scope}
            signedIn={false}
            searching={false}
            onExplore={() => setScope("explore")}
            onClearSearch={() => setQuery("")}
          />
        ) : loading ? (
          <CatalogLoading kind="plugin" />
        ) : error ? (
          <div className="blob-panel p-4 text-sm text-body">
            <p className="text-error font-medium">Could not load plugins</p>
            <p className="mt-1 text-xs">{error}</p>
          </div>
        ) : (
          <CatalogEmpty
            kind="plugin"
            scope={scope}
            signedIn={Boolean(token)}
            searching={Boolean(query.trim())}
            onExplore={() => setScope("explore")}
            onClearSearch={() => setQuery("")}
          />
        )
      ) : (
        <>
          <CatalogCardGrid
            kind="plugin"
            rows={plugins}
            onOpen={openPlugin}
          />
          <p className="text-xs text-mute mt-3 tabular-nums">
            {plugins.length} plugin{plugins.length === 1 ? "" : "s"}
          </p>
        </>
        )}
        </div>
      </div>
    </>
  );
}
