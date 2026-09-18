"use client";

import { useEffect, useState } from "react";
import { MoonIcon, SunIcon } from "./Icons";

const STORAGE_KEY = "labtutor:theme";
type Theme = "dark" | "light";

/** Mirrors the inline script in app/layout.tsx that sets this before
 * first paint -- this component just needs to read that same result so
 * its icon matches on mount, then keeps both in sync on click. */
function currentTheme(): Theme {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

export function ThemeToggle() {
  // Dark is the default rendered on the server; synced to the real
  // value (which may be "light", from a saved preference) once mounted.
  const [theme, setTheme] = useState<Theme>("dark");

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
      style={{ display: "flex", alignItems: "center", gap: "6px" }}
    >
      {theme === "dark" ? <SunIcon size={14} /> : <MoonIcon size={14} />}
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
