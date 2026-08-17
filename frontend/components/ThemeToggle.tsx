"use client";

import { useEffect, useState } from "react";
import { useTheme } from "@/lib/theme-context";

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <button
        type="button"
        className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 dark:border-slate-600 dark:text-slate-300"
        aria-label="Toggle theme"
      >
        Theme
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={toggleTheme}
      className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
    >
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
