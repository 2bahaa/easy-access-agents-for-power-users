import { Bot, BookOpen, Menu, Sparkles, Wrench, X } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";

import { useHealth } from "../api/queries";
import { cn } from "../lib/cn";

const NAV = [
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/skills", label: "Skills", icon: BookOpen },
  { to: "/tools", label: "Tools", icon: Wrench },
];

export function AppLayout() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const [lastPath, setLastPath] = useState(location.pathname);
  if (location.pathname !== lastPath) {
    // Close the mobile menu after navigating.
    setLastPath(location.pathname);
    setOpen(false);
  }

  return (
    <div className="min-h-screen">
      {/* Mobile top bar */}
      <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b border-line bg-surface/85 px-4 backdrop-blur-md lg:hidden">
        <button
          type="button"
          aria-label={open ? "Close menu" : "Open menu"}
          onClick={() => setOpen((v) => !v)}
          className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-fg"
        >
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
        <Brand />
      </header>

      {open && (
        <div
          className="fixed inset-0 z-40 animate-fade-in bg-black/40 lg:hidden"
          onClick={() => setOpen(false)}
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-line bg-surface transition-transform duration-200 lg:translate-x-0",
          open ? "translate-x-0 shadow-pop" : "-translate-x-full",
        )}
      >
        <div className="flex h-16 items-center px-5">
          <Brand />
        </div>
        <nav aria-label="Main" className="flex-1 space-y-1 px-3 py-2">
          <p className="px-3 pt-2 pb-2 text-[11px] font-semibold tracking-wider text-subtle uppercase">
            Studio
          </p>
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "group relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-brand-500/10 text-brand-700 dark:text-brand-400"
                    : "text-muted hover:bg-surface-2 hover:text-fg",
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-gradient-to-b from-brand-500 to-accent-500" />
                  )}
                  <Icon className="size-4" />
                  {label}
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <HealthPanel />
      </aside>

      <main className="lg:pl-64">
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-8 sm:py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function Brand() {
  return (
    <NavLink to="/agents" className="flex items-center gap-2.5">
      <span className="grid size-8 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-accent-500 text-white shadow-md shadow-brand-500/30">
        <Sparkles className="size-4" />
      </span>
      <span className="leading-tight">
        <span className="block text-sm font-semibold tracking-tight">Agent Studio</span>
        <span className="block text-[11px] text-subtle">Easy Access Agents</span>
      </span>
    </NavLink>
  );
}

function HealthPanel() {
  const { data, isError, isPending } = useHealth();
  const api = isPending ? "pending" : isError ? "error" : "ok";
  const db = data?.database ?? (isError ? "error" : "pending");
  const ollama = data?.ollama ?? (isError ? "error" : "pending");
  return (
    <div className="m-3 rounded-xl border border-line bg-surface-2/60 p-3">
      <p className="mb-2 text-[11px] font-semibold tracking-wider text-subtle uppercase">
        System status
      </p>
      <ul className="space-y-1.5 text-xs">
        <StatusRow label="API" state={api} />
        <StatusRow label="Database" state={db} />
        <StatusRow label="Ollama" state={ollama} />
      </ul>
    </div>
  );
}

function StatusRow({ label, state }: { label: string; state: string }) {
  const text = state === "ok" ? "Online" : state === "error" ? "Offline" : "Checking…";
  return (
    <li className="flex items-center justify-between" aria-label={`${label}: ${text}`}>
      <span className="text-muted">{label}</span>
      <span className="flex items-center gap-1.5 font-medium">
        <span
          className={cn(
            "size-1.5 rounded-full",
            state === "ok" && "bg-emerald-500 shadow-[0_0_0_3px] shadow-emerald-500/20",
            state === "error" && "bg-red-500 shadow-[0_0_0_3px] shadow-red-500/20",
            state === "pending" && "animate-pulse bg-subtle",
          )}
        />
        {text}
      </span>
    </li>
  );
}
