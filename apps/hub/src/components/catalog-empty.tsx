import { Bot, ChartColumn, Database, Puzzle } from "lucide-react";
import type { ComponentType } from "react";

import type { CatalogScope } from "@/components/catalog-scope-bar";
import { CommandStrip } from "@ageval/shared/components/command-strip";
import {
  EmptyState,
  LoadingState,
  type NavGlyph,
} from "@ageval/shared/components/empty-state";
import { SignInButton } from "@/components/sign-in-button";
import { Button } from "@ageval/shared/components/ui/button";

type Glyph = ComponentType<{ className?: string; strokeWidth?: number }>;

type CatalogKind = "agent" | "plugin" | "dataset" | "leaderboard";

const KIND_ICON: Record<CatalogKind, Glyph> = {
  agent: Bot,
  plugin: Puzzle,
  dataset: Database,
  leaderboard: ChartColumn,
};

const KIND_GLYPH: Record<CatalogKind, NavGlyph> = {
  agent: "agents",
  plugin: "plugins",
  dataset: "datasets",
  leaderboard: "leaderboard",
};

const PUBLISH: Record<"agent" | "plugin" | "dataset", string> = {
  agent: "ageval agent publish <path> --org <id>",
  plugin: "ageval plugin publish <path> --org <id>",
  dataset: "ageval publish --org <id>",
};

const LOADING: Record<CatalogKind, string> = {
  agent: "Loading agents",
  plugin: "Loading plugins",
  dataset: "Loading datasets",
  leaderboard: "Loading leaderboard",
};

export function CatalogLoading({
  kind,
}: {
  kind: CatalogKind;
}) {
  return <LoadingState label={LOADING[kind]} />;
}

export function CatalogEmpty({
  kind,
  scope,
  signedIn,
  searching,
  onExplore,
  onClearSearch,
}: {
  kind: CatalogKind;
  scope: CatalogScope;
  signedIn: boolean;
  searching: boolean;
  onExplore: () => void;
  onClearSearch: () => void;
}) {
  const icon = KIND_ICON[kind];
  const glyph = KIND_GLYPH[kind];

  if (kind === "leaderboard") {
    if (searching) {
      return (
        <EmptyState
          icon={icon}
          glyph={glyph}
          title="No matches"
          action={
            <Button type="button" variant="outline" size="sm" onClick={onClearSearch}>
              Clear search
            </Button>
          }
        />
      );
    }
    return (
      <EmptyState
        icon={icon}
        glyph={glyph}
        title="No Leaderboard rows yet"
        caption="Listed suites and collected Performance appear here. Metrics are observational, not PASS, and not comparable across datasets."
      />
    );
  }

  if ((scope === "orgs" || scope === "favorites") && !signedIn) {
    return (
      <EmptyState
        icon={icon}
        glyph={glyph}
        title={
          scope === "favorites"
            ? "Sign in to see starred packages"
            : "Sign in to see org packages"
        }
        action={<SignInButton />}
      />
    );
  }

  if (searching) {
    return (
      <EmptyState
        icon={icon}
        glyph={glyph}
        title="No matches"
        action={
          <Button type="button" variant="outline" size="sm" onClick={onClearSearch}>
            Clear search
          </Button>
        }
      />
    );
  }

  if (scope === "favorites") {
    return (
      <EmptyState
        icon={icon}
        glyph={glyph}
        title="None starred yet"
        action={
          <Button type="button" variant="outline" size="sm" onClick={onExplore}>
            Explore
          </Button>
        }
      />
    );
  }

  if (scope === "orgs") {
    return (
      <EmptyState
        icon={icon}
        glyph={glyph}
        title="None published from your orgs"
        action={<CommandStrip command={PUBLISH[kind]} />}
      />
    );
  }

  return (
    <EmptyState
      icon={icon}
      glyph={glyph}
      title="No public packages on this Registry"
    />
  );
}
