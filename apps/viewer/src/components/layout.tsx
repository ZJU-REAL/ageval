import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { ThemeToggle } from "@ageval/shared/components/theme-toggle";
import { OwlIcon } from "@ageval/shared/components/owl-icon";
import { Toaster } from "@ageval/shared/components/ui/toaster";
import { useSession } from "@/lib/session";
import { jobsHome } from "@/lib/routes";
import { cn } from "@ageval/shared/lib/utils";

const DESTINATIONS = [
  { id: "datasets", label: "Datasets", match: "/datasets" },
  { id: "jobs", label: "Jobs", match: "/jobs" },
  { id: "agents", label: "Agents", match: "/agents" },
  { id: "plugins", label: "Plugins", match: "/plugins" },
] as const;

export function Shell({
  children,
  meta,
}: {
  children: ReactNode;
  meta?: ReactNode;
}) {
  const { pathname } = useLocation();
  const { session } = useSession();
  const firstDataset = session?.datasets[0];
  const hrefFor = (id: (typeof DESTINATIONS)[number]["id"]) => {
    if (id === "jobs") return firstDataset ? jobsHome(firstDataset.key) : "/jobs";
    if (id === "datasets") return "/datasets";
    if (id === "agents") return "/agents";
    return "/plugins";
  };

  return (
    <div className="flex h-dvh min-h-0 flex-col bg-canvas">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[80] focus:rounded-[8px] focus:bg-link focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-on-accent"
      >
        Skip to content
      </a>
      <header className="min-h-14 border-b border-hairline bg-canvas-soft flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 sm:px-6 shrink-0">
        <Link
          to="/"
          className="flex items-center gap-1.5 font-semibold tracking-tight text-ink text-[15px] rounded-[8px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70"
        >
          <OwlIcon className="h-6 w-6" />
          AGEVAL
        </Link>
        <nav className="flex flex-wrap items-center gap-1" aria-label="Viewer">
          {DESTINATIONS.map((item) => {
            const active =
              pathname === item.match || pathname.startsWith(`${item.match}/`);
            return (
              <Link
                key={item.id}
                to={hrefFor(item.id)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-[8px] px-2 py-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70",
                  active ? "font-medium text-ink" : "text-mute hover:text-ink",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="flex-1" />
        {meta}
        <ThemeToggle />
      </header>
      <main
        id="main"
        tabIndex={-1}
        className="flex min-h-0 w-full flex-1 flex-col overflow-auto bg-canvas px-4 pb-5 pt-5 sm:px-6"
      >
        <div className="flex min-h-0 min-w-0 w-full flex-1 flex-col xl:mx-auto xl:w-[80%]">
          {children}
        </div>
      </main>
      <Toaster />
    </div>
  );
}
