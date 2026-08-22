import {
  useEffect,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import {
  ArrowUpRight,
  BookOpen,
  Bot,
  Building2,
  Database,
  House,
  Inbox,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Puzzle,
  X,
} from "lucide-react";

import { GitHubIcon } from "@/components/github-icon";
import { HoverTip } from "@/components/hover-tip";
import { OfficialMark } from "@/components/official-mark";
import { OwlIcon } from "@/components/owl-icon";
import { PageHeadSlotProvider } from "@/components/page-head";
import { SignInButton } from "@/components/sign-in-button";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button, buttonVariants } from "@/components/ui/button";
import { Toaster } from "@/components/ui/toaster";
import { usePublicUser } from "@/hooks/use-public-user";
import {
  clearToken,
  getGithubAvatar,
  getGithubName,
  getGithubUser,
  getToken,
} from "@/lib/auth";
import { docsSiteUrl, githubRepoUrl } from "@/lib/public-links";
import { cn } from "@/lib/utils";

const SIDEBAR_COLLAPSED_KEY = "ageval-hub-sidebar-collapsed";

type Glyph = ComponentType<{ className?: string; strokeWidth?: number }>;

const navItemClass =
  "flex h-8 w-full items-center rounded-[6px] text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70";

function useDesktopNav(): boolean {
  const [desktop, setDesktop] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(min-width: 1024px)").matches,
  );
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const sync = () => setDesktop(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return desktop;
}

function useSidebarCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });

  function toggle() {
    setCollapsed((current) => {
      const next = !current;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }

  return [collapsed, toggle];
}

function SidebarLink({
  to,
  end,
  icon: Icon,
  label,
  onNavigate,
  collapsed,
}: {
  to: string;
  end?: boolean;
  icon: Glyph;
  label: string;
  onNavigate?: () => void;
  collapsed: boolean;
}) {
  if (collapsed) {
    return (
      <HoverTip content={label} side="right">
        <NavLink
          to={to}
          end={end}
          onClick={onNavigate}
          aria-label={label}
          className={cn(
            buttonVariants({ variant: "ghost", size: "icon" }),
            "aria-[current=page]:bg-canvas-soft aria-[current=page]:text-link",
          )}
        >
          <Icon className="h-4 w-4" strokeWidth={2.5} />
        </NavLink>
      </HoverTip>
    );
  }

  return (
    <NavLink
      to={to}
      end={end}
      onClick={onNavigate}
      aria-label={label}
      className={({ isActive }) =>
        cn(
          navItemClass,
          "gap-2 px-2",
          isActive
            ? "bg-canvas-soft text-link"
            : "text-body hover:bg-canvas-soft hover:text-ink",
        )
      }
    >
      {({ isActive }) => (
        <>
          <Icon
            className={cn("h-4 w-4 shrink-0", isActive ? "text-link" : "text-mute")}
            strokeWidth={2.5}
          />
          {label}
        </>
      )}
    </NavLink>
  );
}

function SidebarExternal({
  href,
  icon: Icon,
  label,
  collapsed,
}: {
  href: string;
  icon: Glyph;
  label: string;
  collapsed: boolean;
}) {
  if (collapsed) {
    return (
      <HoverTip content={label} side="right">
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          aria-label={label}
          className={buttonVariants({ variant: "ghost", size: "icon" })}
        >
          <Icon className="h-4 w-4 text-mute" strokeWidth={2.5} />
        </a>
      </HoverTip>
    );
  }

  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      aria-label={label}
      className={cn(navItemClass, "gap-2 px-2 text-body hover:bg-canvas-soft hover:text-ink")}
    >
      <Icon className="h-4 w-4 shrink-0 text-mute" strokeWidth={2.5} />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-mute" strokeWidth={2.5} />
    </a>
  );
}

function SidebarGroup({
  label,
  collapsed,
  children,
}: {
  label: string;
  collapsed: boolean;
  children: ReactNode;
}) {
  return (
    <div>
      {collapsed ? (
        <div
          className="mb-1 flex h-4 items-center px-2"
          aria-hidden
        >
          <div className="h-px w-full bg-hairline" />
        </div>
      ) : (
        <p className="mb-1 px-2 font-mono text-xs uppercase tracking-wide text-mute">
          {label}
        </p>
      )}
      <div
        className={cn("flex flex-col gap-0.5", collapsed && "items-center")}
      >
        {children}
      </div>
    </div>
  );
}

function SidebarNav({
  onNavigate,
  collapsed,
}: {
  onNavigate?: () => void;
  collapsed: boolean;
}) {
  const token = getToken();
  const github = githubRepoUrl();
  const docs = docsSiteUrl();

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <nav className="flex flex-1 flex-col gap-5 overflow-y-auto px-2 pb-3 pt-5">
        <SidebarGroup label="Catalog" collapsed={collapsed}>
          <SidebarLink
            to="/datasets"
            icon={Database}
            label="Datasets"
            onNavigate={onNavigate}
            collapsed={collapsed}
          />
          <SidebarLink
            to="/plugins"
            icon={Puzzle}
            label="Plugins"
            onNavigate={onNavigate}
            collapsed={collapsed}
          />
          <SidebarLink
            to="/agents"
            icon={Bot}
            label="Agents"
            onNavigate={onNavigate}
            collapsed={collapsed}
          />
        </SidebarGroup>
        <SidebarGroup label="Workspace" collapsed={collapsed}>
          {token ? (
            <>
              <SidebarLink
                to="/home"
                end
                icon={House}
                label="Home"
                onNavigate={onNavigate}
                collapsed={collapsed}
              />
              <SidebarLink
                to="/inbox"
                icon={Inbox}
                label="Inbox"
                onNavigate={onNavigate}
                collapsed={collapsed}
              />
            </>
          ) : null}
          <SidebarLink
            to="/organizations"
            icon={Building2}
            label="Organizations"
            onNavigate={onNavigate}
            collapsed={collapsed}
          />
        </SidebarGroup>
      </nav>
      {github || docs ? (
        <div className="mt-auto shrink-0 border-t border-hairline px-2 py-3">
          <div
            className={cn(
              "flex flex-col gap-0.5",
              collapsed && "items-center",
            )}
          >
            {github ? (
              <SidebarExternal
                href={github}
                icon={GitHubIcon}
                label="GitHub"
                collapsed={collapsed}
              />
            ) : null}
            {docs ? (
              <SidebarExternal
                href={docs}
                icon={BookOpen}
                label="Documentation"
                collapsed={collapsed}
              />
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function Shell({
  children,
  meta,
}: {
  children: ReactNode;
  meta?: ReactNode;
}) {
  const location = useLocation();
  const desktop = useDesktopNav();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, toggleCollapsed] = useSidebarCollapsed();
  const [headSlot, setHeadSlot] = useState<HTMLElement | null>(null);
  const sidebarOpen = desktop || mobileOpen;
  const rail = desktop && collapsed;
  const token = getToken();
  const githubUser = getGithubUser();
  const githubName = getGithubName();
  const githubAvatar = getGithubAvatar();
  const displayName = githubName || githubUser;
  const publicUser = usePublicUser(token ? githubUser : null);
  const showOfficial = Boolean(publicUser?.official);

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!mobileOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMobileOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [mobileOpen]);

  return (
    <PageHeadSlotProvider slot={headSlot}>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[80] focus:rounded-[6px] focus:bg-link focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-on-accent"
      >
        Skip to content
      </a>
      <div className="flex h-full min-h-full bg-canvas">
        {mobileOpen ? (
          <button
            type="button"
            aria-label="Close menu"
            className="fixed inset-0 z-40 bg-ink/40 lg:hidden"
            onClick={() => setMobileOpen(false)}
          />
        ) : null}

        <aside
          inert={!sidebarOpen ? true : undefined}
          aria-hidden={!sidebarOpen}
          className={cn(
            "flex shrink-0 flex-col overflow-hidden border-r border-hairline bg-canvas",
            "max-lg:fixed max-lg:inset-y-0 max-lg:left-0 max-lg:z-50 max-lg:w-56",
            "transition-[width] duration-200 ease-[cubic-bezier(0.22,1,0.36,1)]",
            mobileOpen ? "max-lg:translate-x-0" : "max-lg:-translate-x-full",
            rail ? "w-12" : "w-56",
          )}
        >
          <div
            className={cn(
              "flex h-[4.5rem] shrink-0 items-center border-b border-hairline",
              rail ? "justify-center px-0" : "gap-1 px-3",
            )}
          >
            {rail ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Expand sidebar"
                aria-expanded={false}
                onClick={toggleCollapsed}
              >
                <PanelLeftOpen className="h-4 w-4" />
              </Button>
            ) : (
              <>
                <div className="flex min-w-0 flex-1 items-center gap-1.5 px-1 font-semibold tracking-tight text-ink text-[15px]">
                  <OwlIcon className="h-6 w-6" />
                  AGEVAL
                  <span className="text-sm font-normal text-mute">hub</span>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="hidden shrink-0 lg:inline-flex"
                  aria-label="Collapse sidebar"
                  aria-expanded
                  onClick={toggleCollapsed}
                >
                  <PanelLeftClose className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="lg:hidden"
                  aria-label="Close menu"
                  onClick={() => setMobileOpen(false)}
                >
                  <X className="h-4 w-4" />
                </Button>
              </>
            )}
          </div>
          <SidebarNav
            onNavigate={() => setMobileOpen(false)}
            collapsed={rail}
          />
        </aside>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex h-[4.5rem] shrink-0 items-center gap-3 border-b border-hairline bg-canvas/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-canvas/80 sm:px-6">
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="lg:hidden"
              aria-label={mobileOpen ? "Close menu" : "Open menu"}
              aria-expanded={mobileOpen}
              onClick={() => setMobileOpen((open) => !open)}
            >
              <Menu className="h-4 w-4" />
            </Button>
            <div ref={setHeadSlot} className="min-w-0 flex-1" />
            {meta}
            <ThemeToggle />
            {token ? (
              <>
                {displayName ? (
                  <Link
                    to={
                      githubUser
                        ? `/users/${encodeURIComponent(githubUser)}`
                        : "/home"
                    }
                    className="hidden min-w-0 max-w-[14rem] items-center gap-2 hover:opacity-90 sm:inline-flex"
                  >
                    {githubAvatar || githubUser ? (
                      <img
                        src={
                          githubAvatar ||
                          `https://github.com/${encodeURIComponent(githubUser || "")}.png?size=64`
                        }
                        alt=""
                        width={28}
                        height={28}
                        className="h-7 w-7 shrink-0 rounded-full border border-hairline bg-canvas-soft object-cover"
                      />
                    ) : null}
                    <span className="inline-flex min-w-0 items-center gap-1">
                      <span className="truncate text-sm text-body">
                        {displayName}
                      </span>
                      {showOfficial ? <OfficialMark kind="org" /> : null}
                    </span>
                  </Link>
                ) : null}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    clearToken();
                    window.location.reload();
                  }}
                >
                  Sign out
                </Button>
              </>
            ) : (
              <SignInButton />
            )}
          </header>
          <main
            id="main"
            tabIndex={-1}
            className="min-h-0 flex-1 overflow-auto px-4 pb-5 pt-5 sm:px-6"
          >
            {children}
          </main>
        </div>
      </div>
      <Toaster />
    </PageHeadSlotProvider>
  );
}
