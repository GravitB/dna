import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { complement } from "./dna";

/**
 * Idealized B-DNA built from an actual sequence.
 *
 * Geometry follows B-form averages: 10.5 bp per turn, 3.38 Å rise, phosphates ~9.4 Å from the
 * axis, and the second backbone offset by ~140° so the major and minor grooves appear. Purines
 * (A, G) are drawn longer than pyrimidines (C, T). Every rung is a letter from the FASTA; the
 * partner strand is the generated complement and is shown slightly muted.
 */

import type { Mark } from "./dna";
export type { Mark };

type Props = {
  /** Exact bases to draw. null draws an unlabeled backbone with neutral rungs (no sequence claimed). */
  sequence: string | null;
  duplex?: boolean;
  selected?: number | null;
  onSelect?: (index: number) => void;
  marks?: Mark[];
  /** Change this number to replay the build animation. */
  build?: number;
  /** Hero mode: no toolbar, no picking, gentle spin. */
  ambient?: boolean;
  label: string;
  placeholderLength?: number;
};

const RISE = 3.38;
const TWIST = (2 * Math.PI) / 10.5;
const R_P = 9.4; // phosphate radius
const R_S = 7.2; // sugar radius, where the base attaches
const GROOVE = (140 * Math.PI) / 180;
const PURINE = 0.56;
const GAP = 0.5; // hydrogen-bond gap between partner bases

const CSS_VARS = ["--A", "--C", "--G", "--T", "--helix-backbone", "--helix-backbone-2", "--helix-rung", "--sub", "--del", "--ins", "--ink"];

function readPalette() {
  const s = getComputedStyle(document.documentElement);
  const out: Record<string, THREE.Color> = {};
  for (const v of CSS_VARS) out[v] = new THREE.Color(s.getPropertyValue(v).trim() || "#888888");
  return out;
}

export function webglAvailable() {
  if (typeof window === "undefined" || typeof WebGLRenderingContext === "undefined") return false;
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

const reduced = () =>
  typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

type Scene = {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  group: THREE.Group;
  dispose: () => void;
};

export default function Helix3D(props: Props) {
  const { sequence, duplex = true, selected = null, onSelect, marks = [], build = 0, ambient = false, label } = props;
  const host = useRef<HTMLDivElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const world = useRef<Scene | null>(null);
  const model = useRef<ReturnType<typeof buildModel> | null>(null);
  const state = useRef({ spin: !reduced(), idleUntil: 0, buildStart: 0, focus: null as null | { from: THREE.Vector3; to: THREE.Vector3; camFrom: THREE.Vector3; camTo: THREE.Vector3; t0: number } });
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const [failed, setFailed] = useState(() => !webglAvailable());
  const [spinning, setSpinning] = useState(state.current.spin);
  const [hover, setHover] = useState<string>("");
  const seq = sequence ?? null;
  const n = seq ? seq.length : props.placeholderLength || 42;

  // --- one renderer per mounted viewer
  useEffect(() => {
    if (failed || !host.current) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch {
      setFailed(true);
      return;
    }
    const el = host.current;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.domElement.className = "helix-canvas";
    el.prepend(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(28, 1, 1, 5000);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.6));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(40, 80, 120);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xbcd2ff, 1.1);
    rim.position.set(-90, -40, -80);
    scene.add(rim);
    const group = new THREE.Group();
    scene.add(group);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.rotateSpeed = 0.7;
    controls.zoomSpeed = 0.9;
    controls.enablePan = !ambient;
    controls.enableZoom = !ambient;
    controls.enabled = !ambient;
    const pause = () => (state.current.idleUntil = performance.now() + 5000);
    controls.addEventListener("start", pause);

    const resize = () => {
      const w = el.clientWidth || 600;
      const h = el.clientHeight || 360;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);

    let visible = true;
    const io = new IntersectionObserver(([e]) => (visible = e.isIntersecting));
    io.observe(el);

    // picking
    const ray = new THREE.Raycaster();
    const ptr = new THREE.Vector2();
    let lastHover = -2;
    const pick = (ev: PointerEvent) => {
      const m = model.current;
      if (!m || ambient) return null;
      const r = renderer.domElement.getBoundingClientRect();
      ptr.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ptr, camera);
      const hits = ray.intersectObjects(m.pickables, false);
      const h = hits.find((x) => x.instanceId != null);
      if (!h) return null;
      const strand = (h.object as THREE.InstancedMesh).userData.strand as 1 | 2;
      return { index: m.order[strand][h.instanceId!], strand };
    };
    const move = (ev: PointerEvent) => {
      const p = pick(ev);
      const idx = p ? p.index * 2 + (p.strand - 1) : -1;
      renderer.domElement.style.cursor = p ? "pointer" : ambient ? "default" : "grab";
      if (tip.current) {
        const r = el.getBoundingClientRect();
        tip.current.style.transform = `translate(${ev.clientX - r.left + 14}px, ${ev.clientY - r.top + 14}px)`;
      }
      if (idx === lastHover) return;
      lastHover = idx;
      const s = model.current?.seq;
      if (!p || !s) return setHover("");
      const b = s[p.index];
      const c = complement(b);
      setHover(
        p.strand === 1
          ? `Base ${p.index + 1} · ${b} — pairs with ${c}`
          : `Generated partner of base ${p.index + 1} · ${c}`,
      );
    };
    let down = { x: 0, y: 0 };
    const pdown = (ev: PointerEvent) => (down = { x: ev.clientX, y: ev.clientY });
    const click = (ev: PointerEvent) => {
      if (Math.hypot(ev.clientX - down.x, ev.clientY - down.y) > 5) return;
      const p = pick(ev);
      if (p) onSelectRef.current?.(p.index);
    };
    const leave = () => {
      lastHover = -2;
      setHover("");
    };
    renderer.domElement.addEventListener("pointermove", move);
    renderer.domElement.addEventListener("pointerdown", pdown);
    renderer.domElement.addEventListener("pointerup", click);
    renderer.domElement.addEventListener("pointerleave", leave);

    const clock = new THREE.Clock();
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      if (!visible || document.hidden) return;
      const dt = Math.min(clock.getDelta(), 0.05);
      const now = performance.now();
      const st = state.current;
      if (st.spin && now > st.idleUntil) group.rotation.x += dt * (ambient ? 0.22 : 0.16);
      const m = model.current;
      if (m && st.buildStart) {
        const t = Math.min(1, (now - st.buildStart) / (900 + m.n * 9));
        m.setProgress(t);
        if (t >= 1) st.buildStart = 0;
      }
      if (st.focus) {
        const f = st.focus;
        const k = Math.min(1, (now - f.t0) / 650);
        const e = 1 - Math.pow(1 - k, 3);
        controls.target.lerpVectors(f.from, f.to, e);
        camera.position.lerpVectors(f.camFrom, f.camTo, e);
        if (k >= 1) st.focus = null;
      }
      controls.update();
      renderer.render(scene, camera);
    };
    tick();

    const onTheme = () => model.current?.recolor(readPalette());
    window.addEventListener("lazarus-theme", onTheme);

    world.current = {
      renderer,
      scene,
      camera,
      controls,
      group,
      dispose: () => {
        cancelAnimationFrame(raf);
        ro.disconnect();
        io.disconnect();
        window.removeEventListener("lazarus-theme", onTheme);
        controls.dispose();
        model.current?.dispose();
        model.current = null;
        renderer.dispose();
        renderer.domElement.remove();
      },
    };
    return () => {
      world.current?.dispose();
      world.current = null;
    };
  }, [failed, ambient]);

  // --- (re)build the molecule when the sequence or representation changes
  useEffect(() => {
    const w = world.current;
    if (!w) return;
    model.current?.dispose();
    const m = buildModel(seq, n, duplex, marks, readPalette());
    model.current = m;
    w.group.add(m.root);
    w.group.rotation.x = 0;
    fit(w, n);
    if (reduced()) m.setProgress(1);
    else {
      m.setProgress(0);
      state.current.buildStart = performance.now();
    }
  }, [failed, seq, n, duplex, build, JSON.stringify(marks)]);

  // --- selection: highlight and glide the camera to the pair
  useEffect(() => {
    const w = world.current;
    const m = model.current;
    if (!w || !m) return;
    m.select(selected);
    if (selected == null) return;
    const x = xOf(selected, n);
    const to = new THREE.Vector3(x, 0, 0);
    const offset = w.camera.position.clone().sub(w.controls.target).setLength(150);
    state.current.focus = {
      from: w.controls.target.clone(),
      to,
      camFrom: w.camera.position.clone(),
      camTo: to.clone().add(offset),
      t0: performance.now(),
    };
    state.current.idleUntil = performance.now() + 6000;
  }, [selected, seq, duplex]);

  const reset = () => {
    const w = world.current;
    if (!w) return;
    const target = w.controls.target.clone();
    const cam = w.camera.position.clone();
    fit(w, n);
    state.current.focus = { from: target, to: w.controls.target.clone(), camFrom: cam, camTo: w.camera.position.clone(), t0: performance.now() };
    w.controls.target.copy(target);
    w.camera.position.copy(cam);
  };
  const zoom = (f: number) => {
    const w = world.current;
    if (!w) return;
    const camTo = w.controls.target.clone().add(w.camera.position.clone().sub(w.controls.target).multiplyScalar(f));
    state.current.focus = { from: w.controls.target.clone(), to: w.controls.target.clone(), camFrom: w.camera.position.clone(), camTo, t0: performance.now() };
  };
  const toggleSpin = () => {
    state.current.spin = !state.current.spin;
    state.current.idleUntil = 0;
    setSpinning(state.current.spin);
  };

  if (failed)
    return (
      <div className={`helix helix-fallback${ambient ? " ambient" : ""}`} role="img" aria-label={label}>
        {!ambient && (
          <p>
            The 3D model needs WebGL, which this browser has turned off. The exact bases are listed
            below.
          </p>
        )}
      </div>
    );

  return (
    <div ref={host} className={`helix${ambient ? " ambient" : ""}`} role="img" aria-label={label}>
      {!ambient && (
        <>
          <div ref={tip} className={`helix-tip${hover ? " on" : ""}`} aria-hidden="true">
            {hover}
          </div>
          <div className="helix-tools">
            <button type="button" onClick={toggleSpin} aria-pressed={spinning} aria-label={spinning ? "Pause rotation" : "Resume rotation"}>
              {spinning ? (
                <svg viewBox="0 0 16 16" width="14" height="14"><rect x="4" y="3" width="2.6" height="10" rx="1" fill="currentColor" /><rect x="9.4" y="3" width="2.6" height="10" rx="1" fill="currentColor" /></svg>
              ) : (
                <svg viewBox="0 0 16 16" width="14" height="14"><path d="M5 3.2v9.6L13 8Z" fill="currentColor" /></svg>
              )}
            </button>
            <button type="button" onClick={() => zoom(0.7)} aria-label="Zoom in">
              <svg viewBox="0 0 16 16" width="14" height="14"><path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
            </button>
            <button type="button" onClick={() => zoom(1.4)} aria-label="Zoom out">
              <svg viewBox="0 0 16 16" width="14" height="14"><path d="M3 8h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
            </button>
            <button type="button" onClick={reset} aria-label="Reset view">
              <svg viewBox="0 0 16 16" width="14" height="14"><path d="M3.5 8a4.5 4.5 0 1 0 1.4-3.3M3.5 2.6v2.6h2.6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </button>
          </div>
        </>
      )}
    </div>
  );
}

const xOf = (i: number, n: number) => (i - (n - 1) / 2) * RISE;

/**
 * Three-quarter view: the 5′ end sits close to the camera and the strand recedes into depth,
 * so a whole 110-nt strand fits while the nearest base pairs stay large enough to read.
 */
function fit(w: Scene, n: number) {
  const len = Math.max(n * RISE, 60);
  const vfov = (w.camera.fov * Math.PI) / 180;
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * w.camera.aspect);
  const flat = Math.max(len / 2 / Math.tan(hfov / 2), (R_P * 2.6) / Math.tan(vfov / 2)) * 1.04;
  const oblique = n > 24;
  const d = oblique ? flat * 0.76 : flat;
  const dir = oblique ? new THREE.Vector3(-0.62, 0.2, 1).normalize() : new THREE.Vector3(0, 0.16, 1).normalize();
  const target = new THREE.Vector3(oblique ? -len * 0.05 : 0, 0, 0);
  w.controls.target.copy(target);
  w.camera.position.copy(target).addScaledVector(dir, d);
  w.camera.near = Math.max(0.5, d / 200);
  w.camera.far = d * 12;
  w.camera.updateProjectionMatrix();
  w.controls.minDistance = 20;
  w.controls.maxDistance = flat * 2.4;
}

function buildModel(seq: string | null, n: number, duplex: boolean, marks: Mark[], pal: Record<string, THREE.Color>) {
  const root = new THREE.Group();
  const disposables: { dispose: () => void }[] = [];
  const keep = <T extends { dispose: () => void }>(x: T) => (disposables.push(x), x);

  const at = (i: number, r: number, strand: 1 | 2) => {
    const a = i * TWIST + (strand === 2 ? GROOVE : 0);
    return new THREE.Vector3(xOf(i, n), r * Math.cos(a), r * Math.sin(a));
  };

  // backbones: smooth tubes through the phosphates, revealed with drawRange during the build
  const tubes: THREE.Mesh[] = [];
  const backboneMats = [
    keep(new THREE.MeshStandardMaterial({ roughness: 0.38, metalness: 0.05 })),
    keep(new THREE.MeshStandardMaterial({ roughness: 0.45, metalness: 0.05 })),
  ];
  for (const strand of duplex ? ([1, 2] as const) : ([1] as const)) {
    const pts: THREE.Vector3[] = [];
    for (let i = -0.5; i <= n - 0.5 + 1e-6; i += 0.25) pts.push(at(i, R_P, strand));
    const curve = new THREE.CatmullRomCurve3(pts);
    const geo = keep(new THREE.TubeGeometry(curve, Math.max(64, n * 10), 0.62, 10, false));
    const mesh = new THREE.Mesh(geo, backboneMats[strand - 1]);
    mesh.userData.strand = strand;
    tubes.push(mesh);
    root.add(mesh);
  }

  // phosphates + sugars
  const sphere = keep(new THREE.SphereGeometry(1, 18, 12));
  const nodeMat = keep(new THREE.MeshStandardMaterial({ roughness: 0.3, metalness: 0.1 }));
  const strands = duplex ? 2 : 1;
  const nodes = new THREE.InstancedMesh(sphere, nodeMat, n * strands * 2);
  root.add(nodes);

  // bases
  const slab = keep(new RoundedBoxGeometry(1, 1, 1, 2, 0.18));
  const baseMats = [
    keep(new THREE.MeshStandardMaterial({ roughness: 0.42, metalness: 0.0 })),
    keep(new THREE.MeshStandardMaterial({ roughness: 0.55, metalness: 0.0, transparent: true, opacity: 0.92 })),
  ];
  const bases1 = new THREE.InstancedMesh(slab, baseMats[0], n);
  bases1.userData.strand = 1;
  const bases2 = duplex ? new THREE.InstancedMesh(slab, baseMats[1], n) : null;
  if (bases2) bases2.userData.strand = 2;
  root.add(bases1);
  if (bases2) root.add(bases2);

  // damage / selection rings
  const ring = keep(new THREE.TorusGeometry(R_P + 2.1, 0.32, 10, 64));
  const ringMats = {
    sub: keep(new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.9 })),
    del: keep(new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.75 })),
    ins: keep(new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.9 })),
    sel: keep(new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.95 })),
  };
  const markMeshes = marks
    .filter((m) => m.index >= 0 && m.index <= n)
    .map((m) => {
      const mesh = new THREE.Mesh(ring, ringMats[m.kind]);
      mesh.position.x = xOf(m.kind === "ins" ? m.index - 0.5 : m.index, n);
      mesh.rotation.y = Math.PI / 2;
      if (m.kind === "ins") mesh.scale.setScalar(0.82);
      root.add(mesh);
      return mesh;
    });
  const deleted = new Set(marks.filter((m) => m.kind === "del").map((m) => m.index));
  const selRing = new THREE.Mesh(ring, ringMats.sel);
  selRing.rotation.y = Math.PI / 2;
  selRing.scale.setScalar(1.12);
  selRing.visible = false;
  root.add(selRing);

  const order = { 1: [...Array(n).keys()], 2: [...Array(n).keys()] } as Record<1 | 2, number[]>;
  const m4 = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const sc = new THREE.Vector3();
  const xAxis = new THREE.Vector3(1, 0, 0);
  let selectedIdx: number | null = null;
  let progress = 1;

  const ease = (t: number) => {
    const c1 = 1.5;
    return t <= 0 ? 0 : t >= 1 ? 1 : 1 + (c1 + 1) * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
  };

  function layout() {
    const span = 0.18; // fraction of the timeline each base takes to settle
    let k = 0;
    for (let i = 0; i < n; i++) {
      const local = Math.max(0, Math.min(1, (progress * (1 + span) - (i / n)) / span));
      const grow = ease(local);
      const big = i === selectedIdx ? 1.18 : 1;
      const s1 = at(i, R_S, 1);
      const s2 = at(i, R_S, 2);
      const chord = s2.clone().sub(s1);
      const full = chord.length();
      const dir = chord.clone().normalize();
      const side = new THREE.Vector3().crossVectors(xAxis, dir);
      const basis = new THREE.Matrix4().makeBasis(xAxis, dir, side);
      q.setFromRotationMatrix(basis);
      const b = seq ? seq[i] : "";
      const purine = b === "A" || b === "G";
      const f1 = seq ? (purine ? PURINE : 1 - PURINE) : 0.5;
      const ghost = deleted.has(i) ? 0.35 : 1;
      // strand 1 base: from sugar toward partner
      const l1 = Math.max(0.01, (full * f1 - GAP / 2) * grow);
      const c1 = s1.clone().addScaledVector(dir, l1 / 2);
      sc.set(1.05 * big * ghost * Math.max(grow, 0.001), l1, 3.0 * big);
      m4.compose(c1, q, sc);
      bases1.setMatrixAt(i, m4);
      if (bases2) {
        const l2 = Math.max(0.01, (full * (1 - f1) - GAP / 2) * grow);
        const c2 = s2.clone().addScaledVector(dir, -l2 / 2);
        sc.set(1.05 * big * ghost * Math.max(grow, 0.001), l2, 3.0 * big);
        m4.compose(c2, q, sc);
        bases2.setMatrixAt(i, m4);
      }
      // phosphate + sugar per strand
      for (let s = 1 as 1 | 2; s <= strands; s = (s + 1) as 1 | 2) {
        const p = at(i, R_P, s);
        m4.compose(p, q.identity(), sc.setScalar(1.25 * grow + 0.0001));
        nodes.setMatrixAt(k++, m4);
        const g = at(i, R_S, s);
        m4.compose(g, q.identity(), sc.setScalar(0.9 * grow + 0.0001));
        nodes.setMatrixAt(k++, m4);
        q.setFromRotationMatrix(basis);
      }
    }
    bases1.instanceMatrix.needsUpdate = true;
    if (bases2) bases2.instanceMatrix.needsUpdate = true;
    nodes.instanceMatrix.needsUpdate = true;
    for (const t of tubes) {
      const geo = t.geometry as THREE.TubeGeometry;
      const total = geo.index ? geo.index.count : 0;
      geo.setDrawRange(0, Math.floor((total * Math.min(1, progress * 1.12)) / 6) * 6);
    }
    for (const mk of markMeshes) mk.visible = progress >= 1;
  }

  function recolor(p: Record<string, THREE.Color>) {
    backboneMats[0].color.copy(p["--helix-backbone"]);
    backboneMats[1].color.copy(p["--helix-backbone-2"]);
    nodeMat.color.copy(p["--helix-backbone"]);
    ringMats.sub.color.copy(p["--sub"]);
    ringMats.del.color.copy(p["--del"]);
    ringMats.ins.color.copy(p["--ins"]);
    ringMats.sel.color.copy(p["--ink"]);
    const rung = p["--helix-rung"];
    const mute = new THREE.Color(0x8a8f95);
    for (let i = 0; i < n; i++) {
      const b = seq ? seq[i] : "";
      bases1.setColorAt(i, seq ? p[`--${b}`] : rung);
      if (bases2) {
        const c = seq ? p[`--${complement(b)}`].clone().lerp(mute, 0.38) : rung;
        bases2.setColorAt(i, c);
      }
    }
    // node colors: phosphates slightly brighter than sugars
    let k = 0;
    const pc = p["--helix-backbone"].clone();
    const sc2 = p["--helix-backbone"].clone().lerp(rung, 0.45);
    for (let i = 0; i < n; i++)
      for (let s = 0; s < strands; s++) {
        nodes.setColorAt(k++, pc);
        nodes.setColorAt(k++, sc2);
      }
    for (const mesh of [bases1, bases2, nodes]) if (mesh?.instanceColor) mesh.instanceColor.needsUpdate = true;
  }

  recolor(pal);
  layout();

  return {
    root,
    n,
    seq,
    order,
    pickables: [bases1, ...(bases2 ? [bases2] : [])] as THREE.Object3D[],
    setProgress(t: number) {
      progress = t;
      layout();
    },
    select(i: number | null) {
      selectedIdx = i;
      selRing.visible = i != null;
      if (i != null) selRing.position.x = xOf(i, n);
      layout();
    },
    recolor,
    dispose() {
      root.removeFromParent();
      for (const d of disposables) d.dispose();
      for (const mesh of [bases1, bases2, nodes]) mesh?.dispose();
    },
  };
}

export { marksFromSegments } from "./dna";
