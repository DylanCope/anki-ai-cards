"use client";

import {
  createContext,
  useContext,
  useSyncExternalStore,
  type ReactNode,
} from "react";

type Theme = "light" | "dark";

const THEME_STORAGE_KEY = "anki-ai-cards-theme";

type Listener = () => void;
let listeners: Listener[] = [];

// A tiny external store (DOM class + localStorage) read via
// useSyncExternalStore rather than mirrored into React state through an
// effect — the `<html>` class is already the source of truth (set pre-
// hydration by layout.tsx's anti-flash script), so this just subscribes to
// it instead of duplicating it into a `useState` that could drift or need a
// setState-in-effect on mount.
function getSnapshot(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

// Matches the anti-flash script's fallback default; real value takes over
// immediately after hydration via useSyncExternalStore, with no console
// warning for the one-frame mismatch (this is what the hook is for).
function getServerSnapshot(): Theme {
  return "dark";
}

function subscribe(listener: Listener): () => void {
  listeners.push(listener);
  return () => {
    listeners = listeners.filter((l) => l !== listener);
  };
}

function setTheme(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
  window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  listeners.forEach((listener) => listener());
}

type ThemeContextValue = {
  theme: Theme;
  toggleTheme: () => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const toggleTheme = () => {
    setTheme(theme === "dark" ? "light" : "dark");
  };

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}
