import type { ComponentType, HTMLAttributes, ReactNode } from "react";

import { ThinkingLogo } from "@ageval/shared/components/thinking-logo";
import { cn } from "@ageval/shared/lib/utils";

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
