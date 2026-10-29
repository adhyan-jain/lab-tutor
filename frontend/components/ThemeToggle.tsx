"use client";

import { useEffect, useState } from "react";
import { MoonIcon, SunIcon } from "./Icons";

const STORAGE_KEY = "labtutor:theme";
type Theme = "dark" | "light";

/** The theme on screen: a saved choice (data-theme, set before first paint by
 * the inline script in app/layout.tsx) or, without one, the device setting. */
function currentTheme(): Theme {
  if (typeof document === "undefined") return "light";
  const set = document.documentElement.getAttribute("data-theme");
  if (set === "light" || set === "dark") return set;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeToggle() {
  // Synced to the real value once mounted (the server cannot know it).
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    setTheme(currentTheme());
  }, []);

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Private browsing / blocked storage -- the toggle still works
      // for this page view, it just won't persist across reloads.
    }
  };

  return (
    <button
      className="btn btn-secondary btn-sm"
      onClick={toggle}
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
    >
      {theme === "dark" ? <SunIcon size={14} /> : <MoonIcon size={14} />}
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
