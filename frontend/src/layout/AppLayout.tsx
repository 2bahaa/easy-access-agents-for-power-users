import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  Check,
  ChevronsLeft,
  ChevronsRight,
  ChevronsUpDown,
  LogOut,
  Menu,
  Monitor,
  Moon,
  Search,
  Settings,
  Sparkles,
  Sun,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";

import { useApprovals, useHealth } from "../api/queries";
import { Tooltip } from "../components/ui/Tooltip";
import { cn } from "../lib/cn";
import { useTheme, type ThemePreference } from "../lib/theme";
import { useAuth } from "../features/auth/auth-context";
import { initials } from "../lib/format";
import { CommandMenu } from "./CommandMenu";
import { NAV_GROUPS } from "./nav";

const COLLAPSE_KEY = "eaa.sidebar.collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

export function AppLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const pendingCount = useApprovals({ status: "pending" }).data?.length ?? 0;
  const location = useLocation();
  const [lastPath, setLastPath] = useState(location.pathname);
  if (location.pathname !== lastPath) {
    // Close the mobile menu after navigating.
    setLastPath(location.pathname);
    setMobileOpen(false);
  }

  const toggleCollapsed = useCallback(() => {
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        /* non-persistent is fine */
      }
      return !c;
    });
  }, []);

  // Global shortcuts: ⌘K / Ctrl+K palette, Ctrl+B toggles the sidebar.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      } else if (mod && e.key.toLowerCase() === "b") {
        e.preventDefault();
        toggleCollapsed();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleCollapsed]);

  // The rail (collapsed) applies only on desktop; the mobile drawer is always full width.
  const rail = collapsed && !mobileOpen;

  return (
    <div className="min-h-screen">
      {/* Mobile top bar */}
      <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b border-line bg-surface/85 px-4 backdrop-blur-md lg:hidden">
        <button
          type="button"
          aria-label={mobileOpen ? "Close menu" : "Open menu"}
          onClick={() => setMobileOpen((v) => !v)}
          className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-fg"
        >
          {mobileOpen ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
        <Brand />
        <button
          type="button"
          aria-label="Search"
          onClick={() => setPaletteOpen(true)}
          className="ml-auto rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-fg"
        >
          <Search className="size-5" />
        </button>
      </header>

      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 animate-fade-in bg-black/40 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside
        aria-label="Sidebar"
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-line bg-surface transition-[transform,width] duration-200 lg:translate-x-0",
          mobileOpen ? "translate-x-0 shadow-pop" : "-translate-x-full",
          rail && "lg:w-16",
        )}
      >
        <div className={cn("flex h-16 items-center px-5", rail && "lg:justify-center lg:px-0")}>
          <Brand compact={rail} />
        </div>

        <div className={cn("px-3 pb-2", rail && "lg:px-2")}>
          <SearchButton compact={rail} onClick={() => setPaletteOpen(true)} />
        </div>

        <nav aria-label="Main" className={cn("scrollbar-thin flex-1 overflow-y-auto px-3 py-1", rail && "lg:px-2")}>
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className="mb-3">
              <p
                className={cn(
                  "px-3 pt-2 pb-1.5 text-[11px] font-semibold tracking-wider text-subtle uppercase",
                  rail && "lg:sr-only",
                )}
              >
                {group.label}
              </p>
              <ul className="space-y-0.5">
                {group.items.map(({ to, label, icon: Icon }) => {
                  const link = (
                    <NavLink
                      to={to}
                      aria-label={rail ? label : undefined}
                      className={({ isActive }) =>
                        cn(
                          "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                          rail && "lg:justify-center lg:px-0",
                          isActive
                            ? "bg-brand-500/10 text-brand-700 dark:text-brand-400"
                            : "text-muted hover:bg-surface-2 hover:text-fg",
                        )
                      }
                    >
                      {({ isActive }) => (
                        <>
                          {isActive && (
                            <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-brand-500" />
                          )}
                          <Icon className="size-4 shrink-0" />
                          <span className={cn("flex-1", rail && "lg:hidden")}>{label}</span>
                          {to === "/approvals" && pendingCount > 0 && (
                            <span
                              aria-label={`${pendingCount} pending`}
                              className={cn(
                                "rounded-full bg-warning px-1.5 text-[10px] font-semibold text-white",
                                rail && "absolute top-1 right-1 lg:block",
                              )}
                            >
                              {pendingCount}
                            </span>
                          )}
                        </>
                      )}
                    </NavLink>
                  );
                  return (
                    <li key={to}>
                      {rail ? (
                        <Tooltip content={label} side="right">
                          {link}
                        </Tooltip>
                      ) : (
                        link
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <HealthPanel compact={rail} />

        <div className={cn("flex items-center gap-1 border-t border-line p-2", rail && "lg:flex-col")}>
          <UserMenu compact={rail} />
          <ThemeMenu />
          <button
            type="button"
            onClick={toggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar (Ctrl+B)" : "Collapse sidebar (Ctrl+B)"}
            className="hidden rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-fg lg:block"
          >
            {collapsed ? <ChevronsRight className="size-4" /> : <ChevronsLeft className="size-4" />}
          </button>
        </div>
      </aside>

      <main className={cn("transition-[padding] duration-200 lg:pl-64", collapsed && "lg:pl-16")}>
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-8 sm:py-8">
          <Outlet />
        </div>
      </main>

      {paletteOpen && <CommandMenu open={paletteOpen} onOpenChange={setPaletteOpen} />}
    </div>
  );
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <NavLink to="/overview" className="flex items-center gap-2.5" aria-label="Agent Studio home">
      <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-brand-600 text-white shadow-sm">
        <Sparkles className="size-4" />
      </span>
      <span className={cn("leading-tight", compact && "lg:hidden")}>
        <span className="block text-sm font-semibold tracking-tight">Agent Studio</span>
        <span className="block text-[11px] text-subtle">Easy Access Agents</span>
      </span>
    </NavLink>
  );
}

function SearchButton({ compact, onClick }: { compact: boolean; onClick: () => void }) {
  const isMac = typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Search (Ctrl+K)"
      className={cn(
        "flex w-full items-center gap-2 rounded-lg border border-line bg-surface-2/60 px-3 py-1.5 text-sm text-subtle transition-colors hover:border-line-strong hover:text-muted",
        compact && "lg:justify-center lg:px-0",
      )}
    >
      <Search className="size-4 shrink-0" />
      <span className={cn("flex-1 text-left", compact && "lg:hidden")}>Search…</span>
      <kbd className={cn("rounded border border-line px-1 font-mono text-[10px]", compact && "lg:hidden")}>
        {isMac ? "⌘K" : "Ctrl K"}
      </kbd>
    </button>
  );
}

const THEMES: Array<{ value: ThemePreference; label: string; icon: typeof Sun }> = [
  { value: "system", label: "System", icon: Monitor },
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
];

function ThemeMenu() {
  const { preference, setPreference } = useTheme();
  const Current = THEMES.find((t) => t.value === preference)?.icon ?? Monitor;
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          aria-label={`Theme: ${preference}`}
          className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-fg"
        >
          <Current className="size-4" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side="top"
          align="start"
          sideOffset={6}
          className="z-[60] min-w-36 animate-fade-in rounded-xl border border-line bg-surface p-1 shadow-pop"
        >
          {THEMES.map(({ value, label, icon: Icon }) => (
            <DropdownMenu.Item
              key={value}
              onSelect={() => setPreference(value)}
              className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-fg outline-none data-[highlighted]:bg-surface-2"
            >
              <Icon className="size-4 text-subtle" />
              <span className="flex-1">{label}</span>
              {preference === value && <Check className="size-3.5 text-brand-600" />}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

/** Account + workspace switcher. */
function UserMenu({ compact }: { compact: boolean }) {
  const { me, workspace, switchWorkspace, logout } = useAuth();
  const navigate = useNavigate();
  if (!me) return null;
  const label = me.user.name || me.user.email;
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          aria-label={`Account: ${label}, workspace ${workspace?.name ?? ""}`}
          className={cn(
            "flex min-w-0 flex-1 items-center gap-2 rounded-lg p-1.5 text-left hover:bg-surface-2",
            compact && "lg:flex-none",
          )}
        >
          <span className="grid size-7 shrink-0 place-items-center rounded-full bg-brand-500/15 text-[11px] font-semibold text-brand-700 dark:text-brand-400">
            {initials(label)}
          </span>
          <span className={cn("min-w-0 flex-1 leading-tight", compact && "lg:hidden")}>
            <span className="block truncate text-xs font-medium">{label}</span>
            <span className="block truncate text-[11px] text-subtle">{workspace?.name}</span>
          </span>
          <ChevronsUpDown className={cn("size-3.5 shrink-0 text-subtle", compact && "lg:hidden")} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side="top"
          align="start"
          sideOffset={6}
          className="z-[60] max-h-[70vh] min-w-60 animate-fade-in overflow-y-auto rounded-xl border border-line bg-surface p-1 shadow-pop"
        >
          <div className="px-2.5 py-2">
            <p className="truncate text-sm font-medium">{label}</p>
            <p className="truncate text-xs text-muted">{me.user.email}</p>
          </div>
          <DropdownMenu.Separator className="my-1 h-px bg-line" />
          {me.organizations.map((org) => (
            <DropdownMenu.Group key={org.id}>
              <DropdownMenu.Label className="px-2.5 pt-1.5 pb-1 text-[11px] font-semibold tracking-wider text-subtle uppercase">
                {org.name} · {org.role}
              </DropdownMenu.Label>
              {org.workspaces.map((w) => (
                <DropdownMenu.Item
                  key={w.id}
                  onSelect={() => w.id !== workspace?.id && void switchWorkspace(w.id)}
                  className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none data-[highlighted]:bg-surface-2"
                >
                  <span className="flex-1 truncate">{w.name}</span>
                  {w.id === workspace?.id && <Check className="size-3.5 text-brand-600" />}
                </DropdownMenu.Item>
              ))}
            </DropdownMenu.Group>
          ))}
          <DropdownMenu.Separator className="my-1 h-px bg-line" />
          <DropdownMenu.Item
            onSelect={() => void navigate("/settings")}
            className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none data-[highlighted]:bg-surface-2"
          >
            <Settings className="size-4 text-subtle" /> Organization settings
          </DropdownMenu.Item>
          <DropdownMenu.Item
            onSelect={() => void logout().then(() => navigate("/login"))}
            className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none data-[highlighted]:bg-surface-2"
          >
            <LogOut className="size-4 text-subtle" /> Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function HealthPanel({ compact }: { compact: boolean }) {
  const { data, isError, isPending } = useHealth();
  const api = isPending ? "pending" : isError ? "error" : "ok";
  const db = data?.database ?? (isError ? "error" : "pending");
  const ollama = data?.ollama ?? (isError ? "error" : "pending");
  const states = [api, db, ollama];
  const overall = states.includes("error") ? "error" : states.includes("pending") ? "pending" : "ok";
  return (
    <>
      {compact && (
        <div className="hidden justify-center py-2 lg:flex">
          <Tooltip content={`System ${overall === "ok" ? "online" : overall === "error" ? "degraded" : "checking"}`} side="right">
            <span tabIndex={0} className="p-2">
              <Dot state={overall} />
            </span>
          </Tooltip>
        </div>
      )}
      <div className={cn("m-3 rounded-xl border border-line bg-surface-2/60 p-3", compact && "lg:hidden")}>
        <p className="mb-2 text-[11px] font-semibold tracking-wider text-subtle uppercase">System status</p>
        <ul className="space-y-1.5 text-xs">
          <StatusRow label="API" state={api} />
          <StatusRow label="Database" state={db} />
          <StatusRow label="Ollama" state={ollama} />
        </ul>
      </div>
    </>
  );
}

function Dot({ state }: { state: string }) {
  return (
    <span
      className={cn(
        "block size-1.5 rounded-full",
        state === "ok" && "bg-success shadow-[0_0_0_3px] shadow-success/20",
        state === "error" && "bg-danger shadow-[0_0_0_3px] shadow-danger/20",
        state === "pending" && "animate-pulse bg-subtle",
      )}
    />
  );
}

function StatusRow({ label, state }: { label: string; state: string }) {
  const text = state === "ok" ? "Online" : state === "error" ? "Offline" : "Checking…";
  return (
    <li className="flex items-center justify-between" aria-label={`${label}: ${text}`}>
      <span className="text-muted">{label}</span>
      <span className="flex items-center gap-1.5 font-medium">
        <Dot state={state} />
        {text}
      </span>
    </li>
  );
}
