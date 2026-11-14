/* Shared visual pieces for the business workspace: icons, the drifting DNA
 * letter field from the homepage, animated numbers, status pills, the phase
 * track, scroll reveal and the header scroll bar. Everything here degrades to a
 * static render when motion is reduced or the browser APIs are missing (tests). */
import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { Presentation } from "./types";

const reducedMotion = () =>
  typeof window !== "undefined" &&
  !!window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;

/* ------------------------------------------------------------------ icons */

type IconProps = { size?: number };
const svg = (size: number, body: ReactNode) => (
  <svg
    className="icon"
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.7"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    {body}
  </svg>
);

export const IconFile = ({ size = 24 }: IconProps) =>
  svg(size, <>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5" />
    <path d="M12 17v-6M9.5 13.5 12 11l2.5 2.5" />
  </>);

export const IconHelix = ({ size = 24 }: IconProps) =>
  svg(size, <>
    <path d="M6 3c0 6 12 6 12 12s-12 0-12 6" />
    <path d="M18 3c0 6-12 6-12 12s12 0 12 6" opacity=".55" />
    <path d="M8 6h8M7.5 18h9M9.5 9.5h5M9.5 14.5h5" strokeWidth="1.4" />
  </>);

export const IconShield = ({ size = 24 }: IconProps) =>
  svg(size, <>
    <path d="M12 3 5 6v5.5c0 4.4 3 8 7 9.5 4-1.5 7-5.1 7-9.5V6z" />
    <path d="m9 12 2.2 2.2L15.5 10" />
  </>);

export const IconVault = ({ size = 24 }: IconProps) =>
  svg(size, <>
    <rect x="3.5" y="4" width="17" height="16" rx="2.5" />
    <circle cx="12" cy="12" r="3.2" />
    <path d="M12 8.8V7M12 17v-1.8M15.2 12H17M7 12h1.8" />
  </>);

export const IconCheck = ({ size = 24 }: IconProps) =>
  svg(size, <path d="m5 12.5 4.5 4.5L19 7.5" />);

export const IconAlert = ({ size = 24 }: IconProps) =>
  svg(size, <>
    <path d="M12 8v5" />
    <path d="M12 16.5v.01" />
    <path d="M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
  </>);

export const IconArrow = ({ size = 18 }: IconProps) =>
  svg(size, <path d="M5 12h14M13 6l6 6-6 6" />);

export const IconBack = ({ size = 16 }: IconProps) =>
  svg(size, <path d="M19 12H5M11 6l-6 6 6 6" />);

export const IconUpload = ({ size = 28 }: IconProps) =>
  svg(size, <>
    <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    <path d="M12 4v11M7.5 8.5 12 4l4.5 4.5" />
  </>);

export const IconClock = ({ size = 24 }: IconProps) =>
  svg(size, <>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 2" />
  </>);

export const IconCoins = ({ size = 24 }: IconProps) =>
  svg(size, <>
    <ellipse cx="12" cy="6.5" rx="7" ry="2.8" />
    <path d="M5 6.5v5c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-5" />
    <path d="M5 11.5v5c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-5" />
  </>);

export const IconUser = ({ size = 24 }: IconProps) =>
  svg(size, <>
    <circle cx="12" cy="8" r="3.6" />
    <path d="M4.5 20c1.2-3.6 4-5.5 7.5-5.5s6.3 1.9 7.5 5.5" />
  </>);

export const IconCloud = ({ size = 24 }: IconProps) =>
  svg(size, <path d="M7 18.5h10.5a4 4 0 0 0 .6-7.95A6 6 0 0 0 6.6 9.1 4.75 4.75 0 0 0 7 18.5z" />);

export const IconLaptop = ({ size = 24 }: IconProps) =>
  svg(size, <>
    <rect x="4.5" y="5" width="15" height="10.5" rx="1.6" />
    <path d="M2.5 19h19" />
  </>);

/* --------------------------------------------------- the drifting letters */

/* Deterministic positions, so the field does not jump between renders. */
function field(count: number, seed: number) {
  let s = seed;
  const rnd = () => ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648);
  return Array.from({ length: count }, () => ({
    ch: "ACGT"[Math.floor(rnd() * 4)],
    x: rnd() * 100,
    y: rnd() * 100,
    size: 11 + Math.round(rnd() * 20),
    r: Math.round(rnd() * 70 - 35),
    o: 0.18 + rnd() * 0.42,
    z: 0.3 + rnd() * 1.4,
    d: -rnd() * 12,
    t: 9 + rnd() * 9,
  }));
}

export function DnaField({ count = 34, seed = 7 }: { count?: number; seed?: number }) {
  const items = useMemo(() => field(count, seed), [count, seed]);
  return (
    <div className="dna-field" aria-hidden="true">
      {items.map((it, i) => (
        <span
          key={i}
          style={{
            left: `${it.x}%`,
            top: `${it.y}%`,
            fontSize: it.size,
            opacity: it.o,
            animationDelay: `${it.d}s`,
            animationDuration: `${it.t}s`,
            ["--r" as string]: `${it.r}deg`,
            ["--z" as string]: it.z,
          } as CSSProperties}
        >
          <i>{it.ch}</i>
        </span>
      ))}
    </div>
  );
}

/* Pointer parallax for a hero: sets --mx / --my in [-1, 1] on the element. */
export function useParallax<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || reducedMotion()) return;
    let raf = 0;
    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const mx = ((e.clientX - r.left) / r.width) * 2 - 1;
      const my = ((e.clientY - r.top) / r.height) * 2 - 1;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        el.style.setProperty("--mx", mx.toFixed(3));
        el.style.setProperty("--my", my.toFixed(3));
      });
    };
    const leave = () => {
      el.style.setProperty("--mx", "0");
      el.style.setProperty("--my", "0");
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", leave);
    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerleave", leave);
    };
  }, []);
  return ref;
}

/* ------------------------------------------------------- animated numbers */

/* Counts up from zero the first time the number scrolls into view, then
 * eases between values. Without IntersectionObserver or with reduced motion it
 * simply shows the value. */
export function CountUp({ value, format = (n: number) => Math.round(n).toLocaleString() }: { value: number; format?: (n: number) => string; duration?: number }) {
  return <span className="count">{format(value)}</span>;
}

/* --------------------------------------------------------- status + phase */

export type Tone = "ok" | "warn" | "bad" | "busy" | "info";

export function toneOf(p: Presentation): Tone {
  if (p.pending_action) return "warn";
  if (p.phase === "attention") return "bad";
  if (p.needs_retest) return "warn";
  if (p.phase === "results") return p.verified ? "ok" : "bad";
  if (p.phase === "analysis" || /progress/i.test(p.label)) return "busy";
  return "info";
}

export function StatusPill({ p, large = false }: { p: Presentation; large?: boolean }) {
  const t = toneOf(p);
  return (
    <span className={`status-pill tone-${t}${large ? " large" : ""}`}>
      <i aria-hidden="true" />
      {p.label}
    </span>
  );
}

export const PHASES = [
  { label: "Requirements", hint: "Your policy" },
  { label: "Analysis", hint: "Designs tested" },
  { label: "Review proposal", hint: "Your decision" },
  { label: "Recovery test", hint: "Rebuilt from DNA" },
  { label: "Results", hint: "Byte-exact proof" },
];

export const phaseIndex = (phase: string) =>
  phase === "review" ? 2 : phase === "recovery" ? 3 : phase === "results" ? 4 : 1;

/* A compact five-segment track for archive cards. */
export function PhaseTrack({ p }: { p: Presentation }) {
  const at = phaseIndex(p.phase);
  const t = toneOf(p);
  const allDone = p.phase === "results" && t === "ok";
  return (
    <div className={`phase-track tone-${t}`}>
      <ol aria-hidden="true">
        {PHASES.map((ph, i) => (
          <li
            key={ph.label}
            title={ph.label}
            className={allDone || i < at ? "done" : i === at ? "current" : ""}
          />
        ))}
      </ol>
      <span>
        Step {at + 1} of {PHASES.length} · {PHASES[at].label}
      </span>
    </div>
  );
}

/* ------------------------------------------------------ DNA letter strand */

/* Coloured letters for sighted readers; assistive tech reads one string. */
export function Strand({ seq, max = 0 }: { seq: string; max?: number }) {
  const s = max ? seq.slice(0, max) : seq;
  return (
    <span className="strand-letters">
      <span className="sr-only">{s}</span>
      <span aria-hidden="true">
        {Array.from(s).map((c, i) => (
          <b key={i} className={`nt nt-${c}`}>
            {c}
          </b>
        ))}
        {max > 0 && seq.length > max && <em>…</em>}
      </span>
    </span>
  );
}

/* An indeterminate "reading DNA" bar for work in progress. */
export function DnaScanner() {
  const letters = useMemo(() => field(64, 11).map((f) => f.ch).join(""), []);
  return (
    <div className="dna-scanner" aria-hidden="true">
      <div className="dna-scanner-track">
        <Strand seq={letters + letters} />
      </div>
      <i className="dna-scanner-beam" />
    </div>
  );
}

/* ------------------------------------------- page-level motion and chrome */

/* Sections fade up as they scroll into view. Skipped when motion is reduced
 * or IntersectionObserver is unavailable, so content is never hidden. */
export function useReveal() {
  useEffect(() => {
    const main = document.querySelector("main");
    if (!main || typeof IntersectionObserver === "undefined" || reducedMotion())
      return;
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (!e.isIntersecting) return;
          (e.target as HTMLElement).dataset.reveal = "in";
          io.unobserve(e.target);
        }),
      { rootMargin: "0px 0px -6% 0px", threshold: 0.04 },
    );
    const scan = () =>
      main
        .querySelectorAll<HTMLElement>(
          "section:not([data-reveal]), .reveal:not([data-reveal])",
        )
        .forEach((el) => {
          el.dataset.reveal = "pending";
          io.observe(el);
        });
    scan();
    const mo = new MutationObserver(scan);
    mo.observe(main, { childList: true, subtree: true });
    return () => {
      io.disconnect();
      mo.disconnect();
    };
  }, []);
}

/* Writes page scroll progress to --scroll on <html> for the header bar. */
export function useScrollProgress() {
  useEffect(() => {
    const root = document.documentElement;
    const update = () => {
      const max = root.scrollHeight - window.innerHeight;
      root.style.setProperty(
        "--scroll",
        String(max > 0 ? Math.min(1, window.scrollY / max) : 0),
      );
    };
    update();
    addEventListener("scroll", update, { passive: true });
    addEventListener("resize", update);
    return () => {
      removeEventListener("scroll", update);
      removeEventListener("resize", update);
    };
  }, []);
}
