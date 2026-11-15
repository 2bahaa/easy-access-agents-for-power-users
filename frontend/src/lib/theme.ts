import { useCallback, useEffect, useSyncExternalStore } from "react";

export type ThemePreference = "system" | "light" | "dark";

const STORAGE_KEY = "eaa.theme";
const listeners = new Set<() => void>();

function readPreference(): ThemePreference {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* storage unavailable (private mode): fall back to system */
  }
  return "system";
}

function systemPrefersDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

/** Resolve a preference to the concrete theme and apply it to <html>. */
export function applyTheme(pref: ThemePreference = readPreference()): "light" | "dark" {
  const resolved = pref === "system" ? (systemPrefersDark() ? "dark" : "light") : pref;
  document.documentElement.classList.toggle("dark", resolved === "dark");
  return resolved;
}

export function setThemePreference(pref: ThemePreference): void {
  try {
    localStorage.setItem(STORAGE_KEY, pref);
  } catch {
    /* non-persistent is fine */
  }
  applyTheme(pref);
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Current theme preference plus a setter; keeps "system" in sync with OS changes. */
export function useTheme() {
  const preference = useSyncExternalStore(subscribe, readPreference, () => "system" as const);

  useEffect(() => {
    if (preference !== "system" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [preference]);

  const setPreference = useCallback((p: ThemePreference) => setThemePreference(p), []);
  return { preference, setPreference };
}
