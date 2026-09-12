import {
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import { Liquid } from "liquid-gooey";
import { Link, NavLink, useLocation } from "react-router-dom";
import {
  ArrowUpRight,
  BookOpen,
  Bot,
  Boxes,
  Building2,
  ChartColumn,
  Database,
  House,
  Inbox,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Puzzle,
  X,
} from "lucide-react";

import type { NavGlyph } from "@/components/empty-state";
import { GitHubIcon } from "@/components/github-icon";
import { HoverTip } from "@/components/hover-tip";
import { LiquidThumb, useTrackedRect } from "@/components/liquid-thumb";
import { MaintainerMark } from "@/components/maintainer-mark";
import { OfficialMark } from "@/components/official-mark";
import { OwlIcon } from "@/components/owl-icon";
import { PageHeadSlotProvider } from "@/components/page-head";
import { SignInButton } from "@/components/sign-in-button";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button, buttonVariants } from "@/components/ui/button";
import { Toaster } from "@/components/ui/toaster";
import { usePublicUser } from "@/hooks/use-public-user";
import { liquidGroup } from "@/lib/liquid";
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
  "flex h-9 w-full items-center rounded-[8px] text-sm motion-safe:transition-[color,background-color,font-weight] motion-safe:duration-200 motion-safe:ease-smooth focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-link/70";

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

function SidebarGlyph({
  icon: Icon,
  glyph,
}: {
  icon: Glyph;
  glyph: NavGlyph;
}) {
  return (
    <span data-nav-glyph={glyph} className="inline-flex shrink-0">
      <Icon className="h-4 w-4" />
    </span>
  );
}

function SidebarLink({
  to,
  end,
  icon,
  label,
  glyph,
  onNavigate,
  collapsed,
}: {
  to: string;
  end?: boolean;
  icon: Glyph;
  label: string;
  glyph: NavGlyph;
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
            "hover:bg-canvas/50 aria-[current=page]:bg-transparent aria-[current=page]:shadow-none",
          )}
        >
          <SidebarGlyph icon={icon} glyph={glyph} />
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
            ? "font-semibold text-ink"
            : "font-normal text-body hover:bg-canvas/50 hover:text-ink",
        )
      }
    >
      <SidebarGlyph icon={icon} glyph={glyph} />
      {label}
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
      className={cn(
        navItemClass,
        "gap-2 px-2 text-body hover:bg-canvas/50 hover:text-ink",
      )}
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
        <p className="mb-1 px-2 text-xs font-medium text-mute">
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
  const location = useLocation();
  const token = getToken();
  const github = githubRepoUrl();
  const docs = docsSiteUrl();
  const navRef = useRef<HTMLDivElement>(null);
  const { bar, ready } = useTrackedRect(
    navRef,
    '[aria-current="page"]',
    `${location.pathname}\0${collapsed}\0${token ?? ""}`,
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Liquid
        ref={navRef}
        {...liquidGroup}
        fill="var(--viewer-canvas)"
        filterPadding={32}
        role="navigation"
        className="relative flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-2 pb-3 pt-5"
      >
        <LiquidThumb bar={bar} ready={ready} />
        <SidebarGroup label="Catalog" collapsed={collapsed}>
          <SidebarLink
            to="/leaderboard"
            icon={ChartColumn}
            glyph="leaderboard"
            label="Leaderboard"
            onNavigate={onNavigate}
            collapsed={collapsed}
          />
          <SidebarLink
            to="/datasets"
            icon={Database}
            glyph="datasets"
            label="Datasets"
            onNavigate={onNavigate}
            collapsed={collapsed}
          />
          <SidebarLink
            to="/plugins"
            icon={Puzzle}
            glyph="plugins"
            label="Plugins"
            onNavigate={onNavigate}
            collapsed={collapsed}
          />
          <SidebarLink
            to="/agents"
            icon={Bot}
            glyph="agents"
            label="Agents"
            onNavigate={onNavigate}
            collapsed={collapsed}
          />
          <SidebarLink
            to="/models"
            icon={Boxes}
            glyph="models"
            label="Models"
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
                glyph="home"
                label="Home"
                onNavigate={onNavigate}
                collapsed={collapsed}
              />
              <SidebarLink
                to="/inbox"
                icon={Inbox}
                glyph="inbox"
                label="Inbox"
                onNavigate={onNavigate}
                collapsed={collapsed}
              />
            </>
          ) : null}
          <SidebarLink
            to="/organizations"
            icon={Building2}
            glyph="orgs"
            label="Organizations"
            onNavigate={onNavigate}
            collapsed={collapsed}
          />
        </SidebarGroup>
      </Liquid>
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
  const showMaintainer = Boolean(publicUser?.maintainer);

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
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[80] focus:rounded-[8px] focus:bg-link focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-on-accent"
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
            "flex shrink-0 flex-col overflow-hidden border-r border-hairline bg-canvas-soft",
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
          <header className="sticky top-0 z-30 flex h-[4.5rem] shrink-0 items-center gap-3 border-b border-hairline bg-canvas px-4 sm:px-6">
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
                        className="h-7 w-7 shrink-0 rounded-full bg-canvas-soft object-cover shadow-[var(--viewer-shadow-pop)]"
                      />
                    ) : null}
                    <span className="inline-flex min-w-0 items-center gap-1">
                      <span className="truncate text-sm text-body">
                        {displayName}
                      </span>
                      {showOfficial ? <OfficialMark kind="org" /> : null}
                      {showMaintainer ? <MaintainerMark /> : null}
                    </span>
                  </Link>
                ) : null}
                <HoverTip content="Sign out" side="bottom">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label="Sign out"
                    onClick={() => {
                      clearToken();
                      window.location.reload();
                    }}
                  >
                    <LogOut className="h-4 w-4" aria-hidden />
                  </Button>
                </HoverTip>
              </>
            ) : (
              <SignInButton />
            )}
          </header>
          <main
            id="main"
            tabIndex={-1}
            className="flex min-h-0 flex-1 flex-col overflow-auto bg-canvas px-4 pb-5 pt-5 sm:px-6"
          >
            <div className="flex min-w-0 w-full flex-1 flex-col xl:mx-auto xl:w-[80%]">
              {children}
            </div>
          </main>
        </div>
      </div>
      <Toaster />
    </PageHeadSlotProvider>
  );
}
