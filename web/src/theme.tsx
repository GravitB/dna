import { useEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "lazarus-theme";

function systemTheme(): Theme {
  return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function currentTheme(): Theme {
  const t = document.documentElement.dataset.theme;
  return t === "dark" || t === "light" ? t : systemTheme();
}

function stored(): Theme | null {
  try {
    const t = localStorage.getItem(KEY);
    return t === "dark" || t === "light" ? t : null;
  } catch {
    return null;
  }
}

export function setTheme(t: Theme) {
  document.documentElement.dataset.theme = t;
  try {
    localStorage.setItem(KEY, t);
  } catch {
    /* private mode: the choice lasts for this page only */
  }
  window.dispatchEvent(new CustomEvent("lazarus-theme", { detail: t }));
}

/** Re-renders when the theme changes (toggle, or the OS setting when the user never chose). */
export function useTheme(): Theme {
  const [theme, set] = useState<Theme>(() => currentTheme());
  useEffect(() => {
    const onToggle = () => set(currentTheme());
    const mq = typeof matchMedia === "function" ? matchMedia("(prefers-color-scheme: dark)") : null;
    const onSystem = () => {
      if (stored()) return;
      document.documentElement.dataset.theme = systemTheme();
      onToggle();
      window.dispatchEvent(new CustomEvent("lazarus-theme"));
    };
    window.addEventListener("lazarus-theme", onToggle);
    mq?.addEventListener?.("change", onSystem);
    return () => {
      window.removeEventListener("lazarus-theme", onToggle);
      mq?.removeEventListener?.("change", onSystem);
    };
  }, []);
  return theme;
}

export function ThemeToggle() {
  const theme = useTheme();
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="theme-toggle"
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode`}
      onClick={() => setTheme(next)}
    >
      <span className="theme-track" aria-hidden="true">
        <span className="theme-knob">
          {theme === "dark" ? (
            <svg viewBox="0 0 16 16" width="12" height="12">
              <path d="M11.6 10.9A5.6 5.6 0 0 1 5.1 4.4 5.6 5.6 0 1 0 11.6 10.9Z" fill="currentColor" />
            </svg>
          ) : (
            <svg viewBox="0 0 16 16" width="12" height="12">
              <circle cx="8" cy="8" r="3.2" fill="currentColor" />
              {[0, 45, 90, 135, 180, 225, 270, 315].map((a) => (
                <rect key={a} x="7.4" y="0.6" width="1.2" height="2.6" rx="0.6" fill="currentColor" transform={`rotate(${a} 8 8)`} />
              ))}
            </svg>
          )}
        </span>
      </span>
      <span className="theme-label">{theme === "dark" ? "Dark" : "Light"}</span>
    </button>
  );
}
