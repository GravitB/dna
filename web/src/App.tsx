import { useEffect, useMemo, useRef, useState } from "react";
import {
  CartesianGrid, Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";

type Ev = { seq: number; type: string; ts: string; agent: string; data: any };
type Job = any;

const api = (p: string, init?: RequestInit) => fetch(`/api${p}`, init).then(async (r) => {
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
});

function useHash() {
  const [h, setH] = useState(location.hash);
  useEffect(() => {
    const f = () => setH(location.hash);
    addEventListener("hashchange", f);
    return () => removeEventListener("hashchange", f);
  }, []);
  return h;
}

export default function App() {
  const hash = useHash();
  const [health, setHealth] = useState<any>(null);
  useEffect(() => { api("/health").then(setHealth).catch(() => setHealth(null)); }, []);
  const jobId = hash.startsWith("#/job/") ? hash.slice(6).split("?")[0] : null;
  return (
    <>
      <div className="top">
        <a className="brand" href="#/" style={{ color: "inherit", textDecoration: "none" }}><span className="mark" />Lazarus</a>
        <span className="sub">AI DNA archivist for regulated enterprises</span>
        <span className="spacer" />
        {health && (health.llm
          ? <span className="pill ok">deep agent online · {String(health.model).replace("anthropic:", "")}</span>
          : <span className="pill warn">no ANTHROPIC_API_KEY · autopilot only</span>)}
      </div>
      <div className="wrap">{jobId ? <JobView id={jobId} /> : <Home llm={!!health?.llm} />}</div>
    </>
  );
}

/* ------------------------------------------------------------------ intake */

function Home({ llm }: { llm: boolean }) {
  const [company, setCompany] = useState("Northstar Bio");
  const [pol, setPol] = useState({ retention_years: 50, tech: "nanopore", coverage: 10, budget_usd: 50, target: 1, n_vaults: 3, notes: "" });
  const [useSamples, setUseSamples] = useState(true);
  const [files, setFiles] = useState<FileList | null>(null);
  const [mode, setMode] = useState(llm ? "agent" : "autopilot");
  const [samples, setSamples] = useState<any[]>([]);
  const [jobs, setJobs] = useState<any[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setMode(llm ? "agent" : "autopilot"); }, [llm]);
  useEffect(() => { api("/samples").then(setSamples); api("/jobs").then(setJobs); }, []);
  const set = (k: string, v: any) => setPol({ ...pol, [k]: v });

  async function submit() {
    setErr(""); setBusy(true);
    const fd = new FormData();
    fd.append("company", company);
    fd.append("policy", JSON.stringify(pol));
    fd.append("use_samples", String(useSamples));
    fd.append("mode", mode);
    if (files) Array.from(files).forEach((f) => fd.append("files", f));
    try {
      const r = await api("/jobs", { method: "POST", body: fd });
      location.hash = `#/job/${r.job_id}`;
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="grid">
      <div>
        <div className="card">
          <h2>New archive</h2>
          <label>Company</label>
          <input value={company} onChange={(e) => setCompany(e.target.value)} />
          <div className="row">
            <div><label>Retention (years)</label><input type="number" value={pol.retention_years} onChange={(e) => set("retention_years", +e.target.value)} /></div>
            <div><label>Read technology</label>
              <select value={pol.tech} onChange={(e) => set("tech", e.target.value)}><option value="nanopore">Nanopore</option><option value="illumina">Illumina</option></select></div>
          </div>
          <div className="row">
            <div><label>Planned reads / strand</label><input type="number" value={pol.coverage} onChange={(e) => set("coverage", +e.target.value)} /></div>
            <div><label>Vault sites</label><input type="number" min={1} max={6} value={pol.n_vaults} onChange={(e) => set("n_vaults", +e.target.value)} /></div>
          </div>
          <div className="row">
            <div><label>Write budget (USD, modeled)</label><input type="number" value={pol.budget_usd} onChange={(e) => set("budget_usd", +e.target.value)} /></div>
            <div><label>Recovery target</label>
              <select value={pol.target} onChange={(e) => set("target", +e.target.value)}><option value={1}>100% of trials</option><option value={0.9}>90% of trials</option></select></div>
          </div>
          <label>Notes for the agent</label>
          <textarea rows={2} value={pol.notes} placeholder="e.g. FDA 21 CFR Part 11 records, must survive loss of one site" onChange={(e) => set("notes", e.target.value)} />
          <label>Files</label>
          <div className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input type="checkbox" style={{ width: "auto" }} checked={useSamples} onChange={(e) => setUseSamples(e.target.checked)} />
            Include Northstar Bio sample files
          </div>
          {useSamples && <div className="small muted" style={{ margin: "4px 0 6px 24px" }}>{samples.map((s) => `${s.name} (${(s.bytes / 1000).toFixed(1)} KB)`).join(" · ")}</div>}
          <input type="file" multiple onChange={(e) => setFiles(e.target.files)} />
          <div className="small muted">Demo limit 200 KB total. Files are encrypted before encoding.</div>
          <label>Run mode</label>
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="agent" disabled={!llm}>Deep agent (LangChain deepagents + Claude)</option>
            <option value="autopilot">Autopilot (scripted recipe, no LLM)</option>
          </select>
          <div style={{ marginTop: 14 }}><button className="btn primary" disabled={busy} onClick={submit}>{busy ? "Starting…" : "Start archive"}</button></div>
          {err && <div className="pill bad" style={{ marginTop: 10 }}>{err}</div>}
        </div>
      </div>
      <div>
        <div className="card">
          <h2>What Lazarus does</h2>
          <ol style={{ margin: 0, paddingLeft: 18 }}>
            <li>Inventories your files and decides which belong in a DNA tier (cold, immutable, decades).</li>
            <li>Compresses and encrypts them (your key never goes into DNA).</li>
            <li>A codec-engineer agent runs real Erbgut DNA codec experiments to find the cheapest design that recovers the files.</li>
            <li>An adversary agent tries to break it: lost vault site, a different sequencer, double decay, fewer reads. Failures force a redesign.</li>
            <li>You approve the cost. Lazarus writes vendor-ready FASTA orders per vault, plus a DNA-encoded manifest that explains how to read everything else.</li>
            <li>Disaster drill: originals deleted. A recovery agent reads the vaults with Erbgut's CNN decoder and verifies every file by SHA-256.</li>
            <li>A compliance agent issues a Recoverability Certificate with full chain of custody.</li>
          </ol>
          <p className="small muted">DNA synthesis and sequencing are simulated with Erbgut's channel model, calibrated on real Nanopore reads. Storage decay and prices are modeled.</p>
        </div>
        <div className="card jobs">
          <h2>Previous runs</h2>
          {jobs.length === 0 && <div className="empty">None yet.</div>}
          {jobs.map((j) => <a key={j.id} href={`#/job/${j.id}`}>{j.company} <span className="muted small">· {j.id} · {j.status}</span></a>)}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ job view */

const STEPS = [
  ["Plan", ["inventory_files"]], ["Prepare", ["prepare_archive"]], ["Design", ["run_codec_sweep", "run_codec_experiment"]],
  ["Red team", ["stress_test"]], ["Approve", []], ["Order", ["place_synthesis_order"]], ["Disaster", ["destroy_primary"]],
  ["Recover", ["recover_archive"]], ["Certify", ["write_certificate"]],
] as const;

function useEvents(id: string) {
  const [evs, setEvs] = useState<Ev[]>([]);
  useEffect(() => {
    setEvs([]);
    let es: EventSource | null = null;
    let closed = false;
    api(`/jobs/${id}/eventlog`).then((log: Ev[]) => {
      if (closed) return;
      setEvs(log);
      if (location.hash.endsWith("?static")) return; // snapshot view, no live stream
      es = new EventSource(`/api/jobs/${id}/events?since=${log.length}`);
      es.onmessage = (m) => {
        const ev = JSON.parse(m.data);
        setEvs((a) => (a.length && a[a.length - 1].seq >= ev.seq ? a : [...a, ev]));
      };
    });
    return () => { closed = true; es?.close(); };
  }, [id]);
  return evs;
}

function JobView({ id }: { id: string }) {
  const evs = useEvents(id);
  const [job, setJob] = useState<Job | null>(null);
  const [destroyed, setDestroyed] = useState<Record<number, boolean>>({});
  const [drilling, setDrilling] = useState(false);
  useEffect(() => { api(`/jobs/${id}`).then(setJob); }, [id, evs.length]);

  const toolsSeen = useMemo(() => new Set(evs.filter((e) => e.type === "tool_result").map((e) => e.data.tool)), [evs]);
  const lastTool = [...evs].reverse().find((e) => e.type === "tool_call")?.data.tool;
  const interrupt = job?.pending;
  const todos = [...evs].reverse().find((e) => e.type === "plan")?.data.todos ?? [];
  const experiments = evs.filter((e) => e.type === "experiment_result").map((e) => e.data);
  const stress = evs.filter((e) => e.type === "stress_result").map((e) => e.data);
  const drills = evs.filter((e) => e.type === "drill_result").map((e) => e.data);
  const done = evs.find((e) => e.type === "done");
  const vaultStatus: Record<number, string> = {};
  evs.filter((e) => e.type === "vault_event").forEach((e) => { vaultStatus[e.data.vault_id] = e.data.status; });
  (job?.vaults ?? []).forEach((v: any) => { if (v.status === "destroyed") vaultStatus[v.vault_id] = "destroyed"; });

  const stepState = (i: number) => {
    const tl = STEPS[i][1] as readonly string[];
    if (i === 4) return interrupt?.tool === "place_synthesis_order" ? "now" : toolsSeen.has("place_synthesis_order") ? "done" : "";
    if (tl.some((t) => toolsSeen.has(t))) return tl.includes(lastTool as any) && !done ? "now" : "done";
    return tl.includes(lastTool as any) ? "now" : "";
  };

  async function destroyVault(v: number) {
    await api(`/jobs/${id}/vaults/${v}/destroy`, { method: "POST" });
    setDestroyed({ ...destroyed, [v]: true });
  }
  async function rerunDrill() {
    setDrilling(true);
    try { await api(`/jobs/${id}/drill`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ attempt: drills.length + 1 }) }); }
    finally { setDrilling(false); }
  }

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
        <h1 style={{ margin: 0, fontSize: 22 }}>{job?.company ?? "…"}</h1>
        <span className="pill acc">{job?.status}</span>
        {job?.mode === "autopilot" && <span className="pill warn">autopilot · scripted, no LLM</span>}
        <span className="muted small mono">{id}</span>
        <span className="spacer" style={{ flex: 1 }} />
        {done && <a className="btn primary" href={done.data.certificate_path} target="_blank" style={{ textDecoration: "none" }}>Open certificate</a>}
      </div>
      <div className="steps">{STEPS.map(([n], i) => <span key={n} className={`step ${stepState(i)}`}>{n}</span>)}</div>

      <div className="grid">
        <div>
          <div className="card">
            <h2>Agent plan</h2>
            {todos.length === 0 && <div className="empty">{job?.mode === "autopilot" ? "Autopilot follows a fixed recipe." : "Waiting for the agent to plan…"}</div>}
            {todos.map((t: any, i: number) => <div key={i} className={`todo ${t.status}`}><div className="box" /><span>{t.text}</span></div>)}
          </div>
          <div className="card">
            <h2>Agent timeline</h2>
            <Timeline evs={evs} />
          </div>
        </div>

        <div>
          <div className="card">
            <h2>Codec experiments · real Erbgut encode → simulated sequencing → decode</h2>
            <ExperimentChart rows={experiments} target={job?.policy?.target ?? 1} />
          </div>
          <div className="two" style={{ marginTop: 16 }}>
            <div className="card" style={{ marginTop: 0 }}>
              <h2>Adversary stress tests</h2>
              <StressTable rows={stress} />
            </div>
            <div className="card" style={{ marginTop: 0 }}>
              <h2>DNA vaults</h2>
              <Vaults n={job?.order?.settings?.n_vaults ?? 0} status={vaultStatus} order={job?.order} id={id} onDestroy={destroyVault} />
              {job?.order && (
                <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button className="btn" disabled={drilling || !toolsSeen.has("recover_archive")} onClick={rerunDrill}>
                    {drilling ? "Reading vaults…" : "Re-run recovery drill"}
                  </button>
                  <span className="small muted" style={{ alignSelf: "center" }}>Destroy a site, then re-run the drill.</span>
                </div>
              )}
            </div>
          </div>
          <div className="card" style={{ marginTop: 16 }}>
            <h2>Recovery drill · originals deleted, only DNA + bootstrap spec + KMS keys</h2>
            <Drills drills={drills} id={id} />
          </div>
        </div>
      </div>
      {interrupt && <Approval id={id} p={interrupt} />}
    </>
  );
}

function Timeline({ evs }: { evs: Ev[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollTo({ top: ref.current.scrollHeight }); }, [evs.length]);
  const shown = evs.filter((e) => ["message", "delegate", "tool_call", "interrupt", "file_write"].includes(e.type));
  return (
    <div className="timeline" ref={ref}>
      {shown.length === 0 && <div className="empty">Starting…</div>}
      {shown.map((e) => {
        if (e.type === "tool_call") return (
          <div key={e.seq} className={`ev tool ${e.agent}`}>
            <span className="mono">▸ {e.data.tool}</span> <span className="mono">{fmtArgs(e.data.args)}</span>
          </div>);
        if (e.type === "delegate") return (
          <div key={e.seq} className={`ev ${e.data.subagent}`}>
            <div className={`who ${e.agent}`}>supervisor → {e.data.subagent}</div>
            <div className="txt small">{e.data.description}</div>
          </div>);
        if (e.type === "interrupt") return (
          <div key={e.seq} className="ev human"><div className="who human">awaiting human approval</div><div className="txt">{e.data.tool}</div></div>);
        if (e.type === "file_write") return (
          <div key={e.seq} className="ev supervisor"><div className="who supervisor">wrote {e.data.path}</div>
            <details><summary className="small muted">show</summary><div className="txt small">{e.data.content}</div></details></div>);
        return (
          <div key={e.seq} className={`ev ${e.agent}`}><div className={`who ${e.agent}`}>{e.agent}</div><div className="txt">{e.data.text}</div></div>);
      })}
    </div>
  );
}

function fmtArgs(a: any) {
  if (!a) return "";
  return Object.entries(a).filter(([k]) => k !== "job_id").map(([k, v]) => `${k}=${Array.isArray(v) ? `[${v.join(",")}]` : typeof v === "string" && v.length > 40 ? v.slice(0, 40) + "…" : v}`).join(" ");
}

const COLORS = ["#0f7b6c", "#2c5ccf", "#c2362b", "#a86400", "#7b3fbf", "#3a8f3a"];

function ExperimentChart({ rows, target }: { rows: any[]; target: number }) {
  if (!rows.length) return <div className="empty">No experiments yet.</div>;
  const groups: Record<string, any[]> = {};
  rows.forEach((r) => {
    const k = `${r.settings.coverage} reads · ${r.decoder === "polish" ? "CNN" : "baseline"}`;
    (groups[k] ||= []).push({ x: r.settings.redundancy, y: Math.round(r.recovery_rate * 100), n: r.n_trials, cost: r.write_usd, acc: r.strand_accuracy });
  });
  const best = rows.filter((r) => r.recovery_rate >= target).sort((a, b) => a.write_usd - b.write_usd)[0];
  return (
    <>
      <ResponsiveContainer width="100%" height={260}>
        <ScatterChart margin={{ top: 10, right: 16, bottom: 18, left: -10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
          <XAxis type="number" dataKey="x" name="redundancy" domain={[0, "auto"]} tick={{ fill: "var(--muted)", fontSize: 12 }}
            label={{ value: "redundancy (extra strands)", position: "insideBottom", offset: -4, fill: "var(--muted)", fontSize: 12 }} />
          <YAxis type="number" dataKey="y" name="recovered" unit="%" domain={[0, 100]} tick={{ fill: "var(--muted)", fontSize: 12 }} />
          <ZAxis type="number" dataKey="n" range={[60, 160]} name="trials" />
          <Tooltip cursor={{ strokeDasharray: "3 3" }} contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8 }}
            formatter={(v: any, n: any) => [v, n]} />
          <Legend verticalAlign="top" wrapperStyle={{ fontSize: 12, paddingBottom: 6 }} />
          {Object.entries(groups).map(([k, d], i) => <Scatter key={k} name={k} data={d} fill={COLORS[i % COLORS.length]} isAnimationActive={false} />)}
        </ScatterChart>
      </ResponsiveContainer>
      <div className="small muted">
        {rows.length} experiment points · each point = file recovered exactly in N independent simulated sequencing runs.
        {best && <> Cheapest point meeting target: <b style={{ color: "var(--text)" }}>redundancy {best.settings.redundancy}, {best.settings.coverage} reads</b> ({best.n_recovered}/{best.n_trials}, {best.bits_per_base} bits/base).</>}
      </div>
    </>
  );
}

function StressTable({ rows }: { rows: any[] }) {
  if (!rows.length) return <div className="empty">The adversary has not attacked yet.</div>;
  const label: Record<string, string> = { vault_loss: "Lose 1 vault site", simulator_b: "Different sequencer (Sim B)", decay_x2: "Twice the storage time", low_coverage: "60% of planned reads" };
  return (
    <table>
      <thead><tr><th>Attack</th><th>Design</th><th>Recovered</th><th /></tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={i}><td>{label[r.scenario] ?? r.scenario}</td><td className="mono">r={r.settings.redundancy} · {r.settings.coverage}x</td>
          <td>{r.n_recovered}/{r.n_trials}</td><td><span className={`pill ${r.passed ? "ok" : "bad"}`}>{r.passed ? "survived" : "broke"}</span></td></tr>))}
      </tbody>
    </table>
  );
}

function Vaults({ n, status, order, id, onDestroy }: { n: number; status: Record<number, string>; order: any; id: string; onDestroy: (v: number) => void }) {
  if (!n) return <div className="empty">No order placed yet.</div>;
  return (
    <div className="vaults">
      {Array.from({ length: n }, (_, i) => i + 1).map((v) => {
        const s = status[v] ?? "healthy";
        return (
          <div key={v} className={`vault ${s}`}>
            <div className="name">Site {v}</div>
            <div className="helix">ACGTTAGCGTACCTGAGCTAGGCATCGA</div>
            <div className="small muted">{order ? `~${Math.round(order.data_strands / n)} data + ${order.manifest_strands} manifest strands` : ""}</div>
            <div style={{ display: "flex", gap: 6, marginTop: 8, alignItems: "center" }}>
              <span className={`pill ${s === "destroyed" ? "bad" : s === "reading" ? "warn" : "ok"}`}>{s}</span>
              {s !== "destroyed" && <button className="btn danger" style={{ padding: "2px 8px", fontSize: 12 }} onClick={() => onDestroy(v)}>destroy</button>}
            </div>
            {s !== "destroyed" && <a className="small" href={`/api/jobs/${id}/files/vaults/vault-${v}/order.fasta`} target="_blank">order.fasta</a>}
          </div>);
      })}
    </div>
  );
}

function Drills({ drills, id }: { drills: any[]; id: string }) {
  if (!drills.length) return <div className="empty">No drill yet. It runs after the order is placed and the primary copy is destroyed.</div>;
  const d = drills[drills.length - 1];
  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
        <span className={`verdict ${d.all_verified ? "ok" : "bad"}`}>{d.all_verified ? "All files restored · SHA-256 verified" : "Recovery incomplete"}</span>
        <span className="muted small">sites read: {d.vaults_available?.join(", ")} of {d.n_vaults} · {d.coverage} reads/strand · attempt {d.attempt} · {d.seconds}s · drill #{drills.length}</span>
      </div>
      {d.error && <div className="pill bad">{d.error}</div>}
      <table style={{ marginTop: 10 }}>
        <thead><tr><th>File</th><th>SHA-256</th><th>Baseline decoder alone</th><th>CNN decoder alone</th><th /></tr></thead>
        <tbody>{(d.files ?? []).map((f: any) => (
          <tr key={f.name}>
            <td>{f.name}</td>
            <td><span className={`pill ${f.sha256_match ? "ok" : "bad"}`}>{f.sha256_match ? "match" : "no match"}</span></td>
            <td><span className={`pill ${f.baseline_would_recover ? "ok" : "bad"}`}>{f.baseline_would_recover ? "recovers" : "fails"}</span></td>
            <td><span className={`pill ${f.polish_would_recover ? "ok" : "bad"}`}>{f.polish_would_recover ? "recovers" : "fails"}</span></td>
            <td>{f.sha256_match && <a className="small" href={`/api/jobs/${id}/files/restored/${f.name}`} target="_blank">open</a>}</td>
          </tr>))}
        </tbody>
      </table>
      <details style={{ marginTop: 8 }}>
        <summary className="small muted">Per-pool strand accuracy (same reads, both decoders)</summary>
        <table><thead><tr><th>Pool</th><th>Strands present</th><th>Baseline exact</th><th>CNN exact</th></tr></thead>
          <tbody>{Object.entries(d.pools ?? {}).map(([k, p]: any) => (
            <tr key={k}><td className="mono">{k}</td><td>{p.strands_present}/{p.strands_written}</td>
              <td>{(p.baseline_strand_accuracy * 100).toFixed(1)}% {p.baseline_ok ? "✓" : "✗"}</td>
              <td>{(p.polish_strand_accuracy * 100).toFixed(1)}% {p.polish_ok ? "✓" : "✗"}</td></tr>))}
          </tbody></table>
      </details>
    </>
  );
}

function Approval({ id, p }: { id: string; p: any }) {
  const [busy, setBusy] = useState(false);
  const send = async (decision: string) => {
    setBusy(true);
    await api(`/jobs/${id}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision }) }).catch(() => {});
  };
  const s = p.summary || {};
  const order = p.tool === "place_synthesis_order";
  return (
    <div className="modal-back">
      <div className="modal">
        <h3>{order ? "Approve DNA synthesis order?" : "Start the disaster drill?"}</h3>
        <div className="muted small">The agent paused and needs a human decision (deepagents human-in-the-loop).</div>
        {order ? (
          <>
            <div className="kv">
              <div>Redundancy<b>{p.args.redundancy}</b></div>
              <div>Planned reads / strand<b>{p.args.coverage}</b></div>
              <div>Vault sites<b>{p.args.n_vaults ?? 3}</b></div>
              <div>Bases to synthesize<b>{s.bases?.toLocaleString()}</b></div>
              <div>Write cost (modeled)<b>${s.write_usd}</b></div>
              <div>Read cost per drill (modeled)<b>${s.read_usd}</b></div>
            </div>
            {s.within_budget === false && <div className="pill bad">Over budget (${s.budget_usd})</div>}
            {s.stress?.length > 0 && <div className="small" style={{ marginTop: 8 }}>
              Latest adversary results: {s.stress.map((x: any, i: number) => <span key={i} className={`pill ${x.passed ? "ok" : "bad"}`} style={{ margin: 2 }}>{x.scenario} r={x.redundancy}: {Math.round(x.recovery_rate * x.n_trials)}/{x.n_trials}</span>)}
            </div>}
            {p.args.design_notes && <p className="small">{p.args.design_notes}</p>}
          </>
        ) : (
          <p>This deletes the original uploads and every staging copy. Only the DNA vaults, the one-page bootstrap spec and your KMS keys remain. Then the recovery agent has to rebuild everything from DNA.</p>
        )}
        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <button className={`btn ${order ? "primary" : "danger"}`} disabled={busy} onClick={() => send("approve")}>{order ? "Approve order" : "Destroy primary data"}</button>
          <button className="btn" disabled={busy} onClick={() => send("reject")}>Reject</button>
        </div>
      </div>
    </div>
  );
}
