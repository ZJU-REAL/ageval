import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { ThemeToggle } from "@ageval/shared/components/theme-toggle";
import { OwlIcon } from "@ageval/shared/components/owl-icon";
import { Toaster } from "@ageval/shared/components/ui/toaster";

export function Shell({
  children,
  meta,
}: {
  children: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <div className="min-h-full flex flex-col bg-canvas">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[80] focus:rounded-[8px] focus:bg-link focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-on-accent"
      >
        Skip to content
      </a>
      <header className="h-14 border-b border-hairline bg-canvas-soft flex items-center px-6 gap-4 shrink-0">
        <Link
          to="/"
          className="flex items-center gap-1.5 font-semibold tracking-tight text-ink text-[15px]"
        >
          <OwlIcon className="h-6 w-6" />
          AGEVAL
        </Link>
        <span className="text-mute text-sm">viewer</span>
        <div className="flex-1" />
        {meta}
        <ThemeToggle />
      </header>
      <main
        id="main"
        tabIndex={-1}
        className="flex flex-1 w-full flex-col px-6 py-5"
      >
        <div className="flex min-w-0 w-full flex-1 flex-col xl:mx-auto xl:w-[80%]">
          {children}
        </div>
      </main>
      <Toaster />
    </div>
  );
}
