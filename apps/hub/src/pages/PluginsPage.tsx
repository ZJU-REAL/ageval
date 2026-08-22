import { Puzzle } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { CatalogCardGrid, CatalogCardSkeleton } from "@/components/catalog-card";
import {
  CatalogScopeBar,
  MARKETPLACE_SCOPE_ITEMS,
  catalogScopeFromSearch,
  catalogScopeSearch,
  type CatalogScope,
} from "@/components/catalog-scope-bar";
import { PageHead } from "@/components/page-head";
import { SignInLink } from "@/components/sign-in-button";
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

  return (
    <>
      <PageHead
        title="Plugin marketplace"
        sub={
          <>
            Browse <span className="font-mono text-xs">ageval.plugin/1</span>{" "}
            packages. Install is CLI-only (Recognition only — does not change
            profiles).
          </>
        }
      />

      <CatalogScopeBar
        scope={scope}
        onScope={setScope}
        items={MARKETPLACE_SCOPE_ITEMS}
        query={query}
        onQuery={setQuery}
        searchLabel="Search plugins"
        searchPlaceholder="Search plugins…"
      />

      {(scope === "orgs" || scope === "favorites") && !token ? (
        <div className="rounded-[8px] border border-hairline bg-canvas-soft p-6 text-sm text-body">
          <p className="font-medium text-ink">
            {scope === "favorites"
              ? "Sign in to see starred plugins"
              : "Sign in to see org plugins"}
          </p>
          <p className="mt-1 text-mute">
            <SignInLink /> to list{" "}
            {scope === "favorites"
              ? "plugins you starred"
              : "plugins from your organizations"}
            . Public plugins are under{" "}
            <button
              type="button"
              className="underline underline-offset-2"
              onClick={() => setScope("explore")}
            >
              Explore
            </button>
            .
          </p>
        </div>
      ) : loading ? (
        <CatalogCardSkeleton />
      ) : error ? (
        <div className="rounded-[8px] border border-hairline bg-canvas-soft p-4 text-sm text-body">
          <p className="text-error font-medium">Could not load plugins</p>
          <p className="mt-1 font-mono text-xs">{error}</p>
        </div>
      ) : (
        <>
          {plugins.length === 0 ? (
            <div className="rounded-[8px] border border-dashed border-hairline bg-canvas-soft p-10 text-center text-sm text-body">
              <div className="flex justify-center mb-4">
                <div className="flex h-16 w-16 items-center justify-center rounded-[12px] bg-canvas border border-hairline text-mute">
                  <Puzzle className="h-8 w-8" strokeWidth={1.5} aria-hidden />
                </div>
              </div>
              <p className="font-medium text-ink">No plugins found</p>
              <p className="mt-1 text-mute max-w-md mx-auto">
                {scope === "orgs"
                  ? "No plugin packages from your organizations yet. Publish with ageval plugin publish <path> --org <id>."
                  : scope === "favorites"
                    ? "No starred plugins yet. Star a plugin from its page."
                    : "No public plugin packages on this Registry yet."}
              </p>
            </div>
          ) : (
            <CatalogCardGrid
              kind="plugin"
              rows={plugins}
              onOpen={openPlugin}
            />
          )}
          <p className="text-xs text-mute mt-3 tabular-nums">
            {plugins.length} plugin{plugins.length === 1 ? "" : "s"}
          </p>
        </>
      )}
    </>
  );
}
