import type { ComponentType, HTMLAttributes, ReactNode } from "react";
import { Bot, ChartColumn, Database, Puzzle } from "lucide-react";

import type { CatalogScope } from "@/components/catalog-scope-bar";
import { CommandStrip } from "@/components/command-strip";
import { SignInButton } from "@/components/sign-in-button";
import { ThinkingLogo } from "@/components/thinking-logo";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type NavGlyph =
  | "home"
  | "datasets"
  | "leaderboard"
  | "plugins"
  | "agents"
  | "models"
  | "inbox"
  | "orgs";

type Glyph = ComponentType<{ className?: string; strokeWidth?: number }>;

const GLYPH_TEXT: Record<NavGlyph, string> = {
  home: "text-nav-home",
  datasets: "text-nav-datasets",
  leaderboard: "text-nav-leaderboard",
  plugins: "text-nav-plugins",
  agents: "text-nav-agents",
  models: "text-nav-models",
  inbox: "text-nav-inbox",
  orgs: "text-nav-orgs",
};

const stackClass =
  "flex min-h-[20rem] flex-1 flex-col items-center px-4 text-center";

function OpticalStack({
  children,
  className,
  ...rest
}: {
  children: ReactNode;
  className?: string;
} & HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn(stackClass, className)} {...rest}>
      <div className="min-h-0 flex-1" aria-hidden />
      <div className="flex flex-col items-center">{children}</div>
      <div className="min-h-0 flex-[1.6]" aria-hidden />
    </div>
  );
}

export function LoadingState({ label }: { label: string }) {
  return (
    <OpticalStack role="status" aria-live="polite" aria-busy="true">
      <ThinkingLogo size={96} />
      <p className="mt-4 text-sm text-body">{label}</p>
    </OpticalStack>
  );
}

export function EmptyState({
  icon: Icon,
  glyph,
  title,
  caption,
  action,
  className,
}: {
  icon: Glyph;
  glyph?: NavGlyph;
  title: string;
  caption?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <OpticalStack className={className} role="status">
      <Icon
        className={cn("h-12 w-12", glyph ? GLYPH_TEXT[glyph] : "text-mute")}
        strokeWidth={1.5}
        aria-hidden
      />
      <p className="mt-4 text-sm font-medium text-ink">{title}</p>
      {action ? (
        <div className="mt-4 max-w-lg">{action}</div>
      ) : caption ? (
        <p className="mt-1 max-w-md text-sm text-body">{caption}</p>
      ) : null}
    </OpticalStack>
  );
}

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
