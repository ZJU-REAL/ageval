import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Boxes } from "lucide-react";

import { CatalogScopeBar } from "@/components/catalog-scope-bar";
import { ModKeyHint } from "@/components/mod-key-hint";
import { EmptyState, LoadingState } from "@ageval/shared/components/empty-state";
import { MODALITY_TAB_META } from "@/components/modality-mark";
import { ModelLabTables, type ModelLabRow } from "@/components/model-lab-tables";
import { ModelSearchModal } from "@/components/model-search-modal";
import { PageHead } from "@/components/page-head";
import { UnderlineTabs } from "@ageval/shared/components/underline-tabs";
import { modKeyShortcut, useModKey } from "@/hooks/use-mod-key";
import { getToken } from "@/lib/auth";
import {
  appearancesByCanonical,
  collectModelAppearances,
} from "@/lib/model-appearances";
import {
  loadModelPin,
  matchesModalityTab,
  modalityTabFromSearch,
  modelModalities,
  type ModalityTab,
} from "@ageval/shared/lib/model-pin";

type ModelScope = "explore" | "performance";

const SCOPE_ITEMS = [
  { id: "explore" as const, label: "Explore All" },
  { id: "performance" as const, label: "With Performance" },
];

function scopeFromSearch(params: URLSearchParams): ModelScope {
  return params.get("performance") === "1" ? "performance" : "explore";
}

export function ModelsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const scope = scopeFromSearch(searchParams);
  const modality = modalityTabFromSearch(searchParams.get("mod"));
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const mod = useModKey();
  const token = getToken();
  const pin = loadModelPin();
  const [perfCanonicals, setPerfCanonicals] = useState<Set<string> | null>(null);
  const [loadingPerf, setLoadingPerf] = useState(false);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "f") {
        event.preventDefault();
        setSearchOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function writeFilters(nextScope: ModelScope, nextMod: ModalityTab) {
    const next: Record<string, string> = {};
    if (nextScope === "performance") next.performance = "1";
    if (nextMod !== "all") next.mod = nextMod;
    setSearchParams(next, { replace: true });
  }

  useEffect(() => {
    if (scope !== "performance") return;
    let cancelled = false;
    setLoadingPerf(true);
    void collectModelAppearances(token)
      .then((rows) => {
        if (cancelled) return;
        setPerfCanonicals(new Set(appearancesByCanonical(rows).keys()));
      })
      .catch(() => {
        if (!cancelled) setPerfCanonicals(new Set());
      })
      .finally(() => {
        if (!cancelled) setLoadingPerf(false);
      });
    return () => {
      cancelled = true;
    };
  }, [scope, token]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out: ModelLabRow[] = [];
    for (const [canonical, info] of Object.entries(pin.models)) {
      if (scope === "performance" && !perfCanonicals?.has(canonical)) continue;
      if (!matchesModalityTab(modelModalities(info), modality)) continue;
      const hay = `${canonical} ${info.name} ${info.family} ${info.lab}`.toLowerCase();
      if (q && !hay.includes(q)) continue;
      out.push({ overlay: canonical, canonical });
    }
    return out;
  }, [pin.models, query, scope, modality, perfCanonicals]);

  function setScope(next: ModelScope) {
    writeFilters(next, modality);
  }

  const emptyPin = Object.keys(pin.models).length === 0;
  const waiting = scope === "performance" && (loadingPerf || perfCanonicals === null);
  const chromeRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const chrome = chromeRef.current;
    const scroller = document.getElementById("main");
    if (!chrome || !scroller) return;
    const apply = () => {
      scroller.style.setProperty("--models-stick-top", `${chrome.offsetHeight}px`);
    };
    const ro = new ResizeObserver(apply);
    ro.observe(chrome);
    window.addEventListener("resize", apply);
    apply();
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", apply);
      scroller.style.removeProperty("--models-stick-top");
    };
  }, []);

  return (
    <>
      <PageHead
        title="Models"
        sub="Pinned encyclopedia. Overlay invoke ids stay as run; Hub joins a unique canonical when it can."
      />
      <div
        id="models-chrome"
        ref={chromeRef}
        className="relative sticky top-0 z-20 flex flex-col -mx-4 -mt-5 bg-canvas px-4 pt-0 sm:-mx-6 sm:px-6"
      >
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-full h-24 bg-canvas"
        />
        <CatalogScopeBar
          scope={scope}
          onScope={setScope}
          items={SCOPE_ITEMS}
          query={query}
          onQuery={setQuery}
          searchLabel="Search models"
          searchPlaceholder="Search models…"
          searchHint={<ModKeyHint keycap="F" />}
          searchKeyshortcuts={modKeyShortcut(mod, "F")}
          variant="select"
          className="mb-3"
        />
        <UnderlineTabs
          className="shrink-0"
          ariaLabel="Model modalities"
          items={MODALITY_TAB_META}
          value={modality}
          onChange={(next) => writeFilters(scope, next)}
        />
        <div id="models-lab-pin" className="bg-canvas pt-3 pb-3 empty:hidden" />
      </div>
      {emptyPin ? (
        <EmptyState
          icon={Boxes}
          glyph="models"
          title="No model pin"
          caption="Letter marks only until a maintainer syncs the snapshot."
        />
      ) : waiting ? (
        <LoadingState label="Loading models" />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Boxes}
          glyph="models"
          title={
            query.trim() || modality !== "all" ? "No models match" : "No models with Performance"
          }
          caption={
            query.trim() || modality !== "all"
              ? undefined
              : "Plaza collect and consented attach fill this filter."
          }
          action={
            query.trim() ? (
              <button
                type="button"
                className="text-sm text-link hover:text-link-deep"
                onClick={() => setQuery("")}
              >
                Clear search
              </button>
            ) : undefined
          }
        />
      ) : (
        <>
          <ModelLabTables rows={rows} />
          <p className="mt-3 text-xs text-mute tabular-nums">
            {rows.length} model{rows.length === 1 ? "" : "s"}
          </p>
        </>
      )}
      <ModelSearchModal open={searchOpen} onClose={() => setSearchOpen(false)} />
    </>
  );
}
