import { act, renderHook } from "@testing-library/react";

import { applyTheme, setThemePreference, useTheme } from "./theme";

describe("theme", () => {
  it("defaults to system and resolves to light when the OS is light", () => {
    expect(applyTheme()).toBe("light");
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("persists an explicit preference and toggles the html class", () => {
    setThemePreference("dark");
    expect(localStorage.getItem("eaa.theme")).toBe("dark");
    expect(document.documentElement).toHaveClass("dark");
    setThemePreference("light");
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("follows the OS when the preference is system", () => {
    const spy = vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      addEventListener() {},
      removeEventListener() {},
    } as unknown as MediaQueryList);
    expect(applyTheme("system")).toBe("dark");
    spy.mockRestore();
  });

  it("useTheme re-renders when the preference changes", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.preference).toBe("system");
    act(() => result.current.setPreference("dark"));
    expect(result.current.preference).toBe("dark");
  });

  it("ignores unknown stored values", () => {
    localStorage.setItem("eaa.theme", "neon");
    const { result } = renderHook(() => useTheme());
    expect(result.current.preference).toBe("system");
  });
});
