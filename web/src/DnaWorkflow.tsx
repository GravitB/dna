import { useEffect, useState } from "react";
import Helix3D from "./Helix";
import { marksFromSegments } from "./dna";
import { api, date, post } from "./api";
import type {
  Archive,
  CompareStrand,
  DecodeSession,
  DnaExport,
  Segment,
  Simulation,
  Verdict,
} from "./types";

const fileUrl = (id: string, path: string, download = false) =>
  `/api/jobs/${id}/files/${path.split("/").map(encodeURIComponent).join("/")}${download ? "?download=1" : ""}`;
const kb = (b?: number) => (b == null ? "" : `${(b / 1000).toFixed(1)} KB`);
const pct = (v?: number) => (v == null ? "—" : `${(v * 100).toFixed(2)}%`);
const PRE = "exports/pre_simulation.fasta";
const ZIP = "exports/clean_dna.zip";
const BUNDLE = "exports/recovery_bundle.json";
export const FLOW = [
  "Upload",
  "Encode",
  "Pre-Simulation FASTA",
  "Simulate",
  "Post-Simulation FASTA",
  "Decode",
  "Verify",
];

export function VerdictBadge({ v }: { v?: Verdict | null }) {
  if (!v) return null;
  return <span className={`badge verdict ${v.toLowerCase()}`}>{v}</span>;
}

function Stepper({ reached }: { reached: number }) {
  return (
    <ol className="workflow dna-flow" aria-label="DNA experiment progress">
      {FLOW.map((label, i) => (
        <li
          key={label}
          className={i < reached ? "complete" : ""}
          aria-current={i === reached ? "step" : undefined}
        >
          <b>{label}</b>
        </li>
      ))}
    </ol>
  );
}

// ---------------------------------------------------------------- archive page panel

export function DnaExperiment({ id, job }: { id: string; job: Archive }) {
  const [dna, setDna] = useState<DnaExport | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const load = () =>
    api(`/jobs/${id}/dna`)
      .then((d: DnaExport) => {
        if (!d?.export?.counts || !Array.isArray(d.simulations))
          throw new Error("The encoded DNA for this archive is not available yet.");
        setDna(d);
        setError("");
        setSelected((s) => s ?? d.simulations[d.simulations.length - 1]?.id ?? null);
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, [id, job.order?.order_files.length]);
  const running =
    dna?.simulations.some((s) => s.status === "running") ?? false;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [running]);
  if (error)
    return (
      <section className="dna-panel">
        <h2>DNA experiment</h2>
        <div className="error">{error}</div>
      </section>
    );
  if (!dna)
    return (
      <section className="dna-panel">
        <p role="status">Loading encoded DNA…</p>
      </section>
    );
  const sim = dna.simulations.find((s) => s.id === selected) || null;
  const decodes = dna.decodes.filter((d) => sim && d.simulation_id === sim.id);
  const lastDecode = decodes[decodes.length - 1];
  const completeSims = dna.simulations.filter((s) => s.status === "complete");
  const reached = lastDecode
    ? lastDecode.verdict === "PASS"
      ? 7
      : 6
    : completeSims.length
      ? 5
      : 3;
  return (
    <section className="dna-panel">
      <Stepper reached={reached} />
      <Step1 id={id} dna={dna} />
      <SimForm
        id={id}
        job={job}
        onStarted={(s) => {
          setSelected(s.id);
          load();
        }}
      />
      {dna.simulations.length > 0 && (
        <label>
          Simulation run
          <select
            value={selected || ""}
            onChange={(e) => setSelected(e.target.value)}
          >
            {[...dna.simulations].reverse().map((s) => (
              <option key={s.id} value={s.id}>
                {s.id} · seed {s.settings.seed} · {s.settings.tech}{" "}
                {s.settings.coverage}× · {s.status}
              </option>
            ))}
          </select>
        </label>
      )}
      {sim && <Step2 id={id} sim={sim} decodes={decodes} />}
      <KeyExport id={id} />
    </section>
  );
}

function Step1({ id, dna }: { id: string; dna: DnaExport }) {
  const [inspect, setInspect] = useState(false);
  const c = dna.export.counts;
  const pre = dna.export.files[PRE];
  return (
    <div className="dna-step">
      <h3>Step 1 — Original Encoded DNA (Pre-Simulation)</h3>
      <div className="info">
        {dna.notice} This is the clean synthesis design (a potential
        manufacturing order), not sequencing data.
      </div>
      <dl className="summary">
        <div>
          <dt>DNA sequences</dt>
          <dd>{c.sequences.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Strand length</dt>
          <dd>{c.strand_lengths.join(", ")} nt</dd>
        </div>
        <div>
          <dt>Redundancy</dt>
          <dd>{c.redundancy}</dd>
        </div>
        <div>
          <dt>Mean GC</dt>
          <dd>{c.gc_mean != null ? pct(c.gc_mean) : "—"}</dd>
        </div>
      </dl>
      <p className="fine">
        {c.data_strands} data + {c.manifest_strands_per_vault} manifest strands per vault ·{" "}
        {c.total_nucleotides.toLocaleString()} nt · Erbgut DNA Fountain ·{" "}
        {Object.entries(dna.export.encoder_configuration.pools)
          .map(([p, m]) => `${p}: ${m.n_chunks} chunks`)
          .join(", ")}{" "}
        · exported {date(dna.export.created)}
        <br />
        <span className="hash">pre_simulation.fasta SHA-256 {pre?.sha256} ({kb(pre?.bytes)})</span>
      </p>
      <div className="actions">
        <a className="button primary" href={fileUrl(id, PRE, true)}>
          Download Pre-Simulation FASTA
        </a>
        <a className="button" href={fileUrl(id, ZIP, true)}>
          Download All Clean DNA Files
        </a>
        <button onClick={() => setInspect(!inspect)}>
          {inspect ? "Hide DNA Sequences" : "Inspect DNA Sequences"}
        </button>
        <a className="button" href={fileUrl(id, BUNDLE, true)}>
          Download recovery bundle
        </a>
      </div>
      {inspect && <SequenceTable id={id} />}
    </div>
  );
}

function SequenceTable({ id }: { id: string }) {
  const [page, setPage] = useState<any>(null);
  const [offset, setOffset] = useState(0);
  const [sample, setSample] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    api(
      `/jobs/${id}/dna/sequences?offset=${offset}&limit=25${sample ? `&sample=${encodeURIComponent(sample)}` : ""}`,
    )
      .then(setPage)
      .catch((e) => setError(e.message));
  }, [offset, sample]);
  if (error) return <div className="error">{error}</div>;
  if (!page) return <p role="status">Loading sequences…</p>;
  return (
    <div className="seq-inspect">
      <label>
        Pool
        <select
          value={sample}
          onChange={(e) => {
            setSample(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">All</option>
          {page.samples.map((s: string) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Identifier</th>
              <th>GC</th>
              <th>Sequence</th>
            </tr>
          </thead>
          <tbody>
            {page.sequences.map((s: any) => (
              <tr key={s.id}>
                <td className="mono small">{s.id}</td>
                <td>{pct(s.gc)}</td>
                <td className="mono dna-seq">{s.sequence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="actions">
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>
          Previous
        </button>
        <span className="muted">
          {offset + 1}–{Math.min(offset + 25, page.total)} of {page.total}
        </span>
        <button
          disabled={offset + 25 >= page.total}
          onClick={() => setOffset(offset + 25)}
        >
          Next
        </button>
      </div>
    </div>
  );
}

const numOrNull = (v: string) => (v === "" ? null : Number(v));

function SimForm({
  id,
  job,
  onStarted,
}: {
  id: string;
  job: Archive;
  onStarted: (s: Simulation) => void;
}) {
  const nV = job.order?.settings.n_vaults || 3;
  const [s, setS] = useState({
    tech: job.policy.tech || "nanopore",
    channel: "a",
    coverage: String((job.order?.settings as any)?.coverage ?? job.policy.coverage),
    storage_years: String(job.policy.retention_years),
    seed: String(Math.floor(Math.random() * 1e6)),
    sub_rate: "",
    ins_rate: "",
    del_rate: "",
    dropout_rate: "",
    lost_vaults: [] as number[],
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k: string, v: any) => setS((o) => ({ ...o, [k]: v }));
  async function run() {
    setBusy(true);
    setError("");
    try {
      const sim = await post(`/jobs/${id}/simulations`, {
        tech: s.tech,
        channel: s.channel,
        coverage: Number(s.coverage),
        storage_years: Number(s.storage_years),
        seed: Number(s.seed),
        sub_rate: numOrNull(s.sub_rate),
        ins_rate: numOrNull(s.ins_rate),
        del_rate: numOrNull(s.del_rate),
        dropout_rate: numOrNull(s.dropout_rate),
        lost_vaults: s.lost_vaults,
      });
      onStarted(sim);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="dna-step">
      <h3>Simulate storage and sequencing damage</h3>
      <p>
        Sends the exact Step 1 sequences through Erbgut’s channel simulator:
        substitutions, insertions, deletions, strand dropout and storage decay,
        with several noisy reads per strand. The same seed always gives the same
        reads.
      </p>
      {error && <div className="error">{error}</div>}
      <div className="three">
        <label>
          Sequencer profile
          <select value={s.tech} onChange={(e) => set("tech", e.target.value)}>
            <option value="nanopore">Nanopore (calibrated on real reads)</option>
            <option value="illumina">Illumina</option>
          </select>
        </label>
        <label>
          Reads per strand (coverage)
          <input
            type="number"
            min="1"
            max="100"
            value={s.coverage}
            onChange={(e) => set("coverage", e.target.value)}
          />
        </label>
        <label>
          Storage duration (years)
          <input
            type="number"
            min="0"
            max="1000"
            value={s.storage_years}
            onChange={(e) => set("storage_years", e.target.value)}
          />
        </label>
        <label>
          Random seed
          <input
            type="number"
            min="0"
            value={s.seed}
            onChange={(e) => set("seed", e.target.value)}
          />
        </label>
      </div>
      <details>
        <summary>Advanced damage settings</summary>
        <p className="muted small">
          Leave blank to use the profile’s calibrated value. Rates are per base
          (0–0.3); dropout is the strand loss fraction before storage decay.
        </p>
        <div className="three">
          {(
            [
              ["sub_rate", "Substitution rate"],
              ["ins_rate", "Insertion rate"],
              ["del_rate", "Deletion rate"],
              ["dropout_rate", "Base strand dropout"],
            ] as const
          ).map(([k, label]) => (
            <label key={k}>
              {label}
              <input
                type="number"
                step="0.001"
                min="0"
                placeholder="profile default"
                value={(s as any)[k]}
                onChange={(e) => set(k, e.target.value)}
              />
            </label>
          ))}
          <label>
            Simulator
            <select
              value={s.channel}
              onChange={(e) => set("channel", e.target.value)}
            >
              <option value="a">A — calibrated channel</option>
              <option value="b">B — structurally different (red team)</option>
            </select>
          </label>
        </div>
        <fieldset className="vault-loss">
          <legend>Lose storage locations entirely</legend>
          {Array.from({ length: nV }, (_, i) => i + 1).map((v) => (
            <label key={v} className="inline">
              <input
                type="checkbox"
                checked={s.lost_vaults.includes(v)}
                onChange={(e) =>
                  set(
                    "lost_vaults",
                    e.target.checked
                      ? [...s.lost_vaults, v]
                      : s.lost_vaults.filter((x) => x !== v),
                  )
                }
              />{" "}
              Vault {v}
            </label>
          ))}
        </fieldset>
      </details>
      <button className="primary" disabled={busy} onClick={run}>
        {busy ? "Starting simulation…" : "Run damage simulation"}
      </button>
    </div>
  );
}

function Step2({
  id,
  sim,
  decodes,
}: {
  id: string;
  sim: Simulation;
  decodes: { id: string; verdict: Verdict; files_verified: number; files: number }[];
}) {
  const [compare, setCompare] = useState(false);
  if (sim.status === "running")
    return (
      <div className="dna-step" role="status">
        <h3>Step 2 — Damaged DNA (Post-Simulation)</h3>
        <p>
          <span className="activity-dot" /> Simulating sequencing of {sim.id}…
        </p>
      </div>
    );
  if (sim.status === "failed")
    return (
      <div className="dna-step">
        <h3>Step 2 — Damaged DNA (Post-Simulation)</h3>
        <div className="error">Simulation failed: {sim.error}</div>
      </div>
    );
  const m = sim.metrics!;
  const r = m.observed_error_rates_per_base;
  const post = sim.files["post_simulation_reads.fasta"];
  const last = decodes[decodes.length - 1];
  return (
    <div className="dna-step">
      <h3>Step 2 — Damaged DNA (Post-Simulation)</h3>
      <div className="info warn">
        Simulated damage produced by Erbgut’s sequencing/storage model. These
        are not laboratory results, and one simulated trial does not prove
        long-term physical recoverability.
      </div>
      <dl className="summary">
        <div>
          <dt>Surviving sequences</dt>
          <dd>{m.surviving_sequences.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Missing sequences (dropout)</dt>
          <dd>
            {m.missing_sequences.toLocaleString()} ({pct(m.observed_dropout_rate)})
          </dd>
        </div>
        <div>
          <dt>Noisy reads</dt>
          <dd>
            {m.reads.toLocaleString()} · {m.mean_reads_per_surviving_sequence}
            ×
          </dd>
        </div>
        <div>
          <dt>Observed errors per base</dt>
          <dd className="small-dd">
            sub {pct(r.substitution)} · ins {pct(r.insertion)} · del{" "}
            {pct(r.deletion)}
          </dd>
        </div>
      </dl>
      <p className="fine">
        {m.clean_sequences.toLocaleString()} clean sequences · {m.exact_reads.toLocaleString()} exact and{" "}
        {m.malformed_or_chimeric_reads} malformed reads · seed {sim.settings.seed} · {sim.settings.tech} · simulator{" "}
        {sim.settings.channel.toUpperCase()} · {sim.settings.coverage}× ·{" "}
        {sim.settings.storage_years} years
        {sim.settings.lost_vaults.length
          ? ` · vaults lost: ${sim.settings.lost_vaults.join(", ")}`
          : ""}{" "}
        · {date(sim.created)}
        <br />
        <span className="hash">post_simulation_reads.fasta SHA-256 {post.sha256} ({kb(post.bytes)})</span>
      </p>
      <div className="actions">
        <a className="button" href={fileUrl(id, PRE, true)}>
          Download Pre-Simulation FASTA
        </a>
        <a className="button primary" href={fileUrl(id, post.path, true)}>
          Download Post-Simulation FASTA
        </a>
        <a
          className="button"
          href={fileUrl(id, sim.files["simulation_metadata.json"].path, true)}
        >
          Download Simulation Metadata
        </a>
        <button onClick={() => setCompare(!compare)}>
          {compare ? "Hide comparison" : "Compare Before vs. After"}
        </button>
      </div>
      <p className="fine">
        Ground truth (which read came from which strand) is kept in a separate{" "}
        <a href={fileUrl(id, sim.files["ground_truth.tsv"].path, true)}>
          simulator-only file
        </a>{" "}
        and is never given to the decoder.
      </p>
      {compare && <Compare id={id} simId={sim.id} verdict={last?.verdict} />}
      <h3>Step 3 — Decode and verify</h3>
      {last ? (
        <p>
          Latest independent decode: <VerdictBadge v={last.verdict} />{" "}
          {last.files_verified} of {last.files} files byte-exact.{" "}
          <a href={`#/decoder?session=${last.id}`}>Open result</a>
        </p>
      ) : (
        <p>Not decoded yet.</p>
      )}
      <a
        className="button primary"
        href={`#/decoder?archive=${encodeURIComponent(id)}&simulation=${encodeURIComponent(sim.id)}`}
      >
        Decode this FASTA in the DNA Decoder
      </a>
    </div>
  );
}

function Alignment({ segments }: { segments: Segment[] }) {
  const top: JSX.Element[] = [];
  const bottom: JSX.Element[] = [];
  segments.forEach((s, i) => {
    if (s.op === "equal") {
      top.push(<span key={i}>{s.clean}</span>);
      bottom.push(<span key={i}>{s.read}</span>);
    } else if (s.op === "replace") {
      top.push(<span key={i} className="d-sub">{s.clean}</span>);
      bottom.push(<span key={i} className="d-sub">{s.read}</span>);
    } else if (s.op === "delete") {
      top.push(<span key={i} className="d-del">{s.clean}</span>);
      bottom.push(<span key={i} className="d-del">{"-".repeat(s.clean.length)}</span>);
    } else {
      top.push(<span key={i} className="d-ins">{"-".repeat(s.read.length)}</span>);
      bottom.push(<span key={i} className="d-ins">{s.read}</span>);
    }
  });
  return (
    <div className="alignment">
      <div>
        <b>clean</b>
        <code>{top}</code>
      </div>
      <div>
        <b>read</b>
        <code>{bottom}</code>
      </div>
    </div>
  );
}

function Compare({ id, simId, verdict }: { id: string; simId: string; verdict?: Verdict }) {
  const [data, setData] = useState<{ strands: CompareStrand[] } | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<string | null>(null);
  useEffect(() => {
    api(`/jobs/${id}/simulations/${simId}/compare?limit=8`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [simId]);
  if (error) return <div className="error">{error}</div>;
  if (!data) return <p role="status">Aligning reads to their source strands…</p>;
  return (
    <div className="compare">
      <p className="legend">
        <span className="d-sub">substitution</span>{" "}
        <span className="d-ins">insertion</span>{" "}
        <span className="d-del">deletion</span> · Alignment uses the simulator’s
        ground truth, for display only. Recovery status:{" "}
        {verdict ? <VerdictBadge v={verdict} /> : "not decoded yet"}
      </p>
      {data.strands.map((s) => (
        <div key={s.id} className="strand">
          <div className="section-heading">
            <span className="mono">{s.id}</span>
            <span>
              {s.missing
                ? "Missing: no reads survived"
                : `${s.reads_total} reads (showing ${s.reads.length})`}
            </span>
          </div>
          {s.missing ? (
            <div className="alignment">
              <div>
                <b>clean</b>
                <code>{s.clean}</code>
              </div>
              <div>
                <b>read</b>
                <code className="d-del">— strand lost (dropout) —</code>
              </div>
            </div>
          ) : (
            s.reads.map((r) => {
              const key = `${s.id}/${r.read_id}`;
              const marks = marksFromSegments(r.segments);
              return (
                <div key={r.read_id} className="read-row">
                  <div className="read-head">
                    <small className="muted">
                      {r.read_id}: {r.substitutions} sub · {r.insertions} ins ·{" "}
                      {r.deletions} del{r.malformed ? " · malformed read" : ""}
                    </small>
                    {!!marks.length && (
                      <button className="ghost small-button" aria-expanded={view === key} onClick={() => setView(view === key ? null : key)}>
                        {view === key ? "Hide 3D damage" : "Show damage in 3D"}
                      </button>
                    )}
                  </div>
                  <Alignment segments={r.segments} />
                  {view === key && (
                    <div className="stage stage-compact">
                      <Helix3D
                        sequence={s.clean}
                        duplex={false}
                        marks={marks}
                        label={`3D model of clean strand ${s.id} with ${marks.length} damage sites from ${r.read_id}`}
                      />
                      <div className="stage-legend">
                        <span><i className="ring ring-sub" />substitution</span>
                        <span><i className="ring ring-ins" />insertion</span>
                        <span><i className="ring ring-del" />deletion</span>
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      ))}
    </div>
  );
}

function KeyExport({ id }: { id: string }) {
  const [pass, setPass] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  async function exportKeys() {
    setBusy(true);
    setMsg("");
    try {
      const r = await fetch(`/api/jobs/${id}/recovery-keys`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ passphrase: pass }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Export failed");
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `${id}.lazarus-keys.json`;
      a.click();
      URL.revokeObjectURL(url);
      setPass("");
      setMsg("Key file downloaded. Keep it and its passphrase separate from the DNA files.");
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="dna-step">
      <summary>Export keys for independent recovery</summary>
      <p>
        Encryption keys are never written to DNA or FASTA files. For a decode on
        another computer, export a key file protected by a passphrase (scrypt +
        AES-256-GCM).
      </p>
      <label>
        Passphrase (at least 10 characters)
        <input
          type="password"
          autoComplete="new-password"
          value={pass}
          onChange={(e) => setPass(e.target.value)}
        />
      </label>
      <button disabled={busy || pass.length < 10} onClick={exportKeys}>
        {busy ? "Encrypting…" : "Download protected key file"}
      </button>
      {msg && <p role="status">{msg}</p>}
    </details>
  );
}

// ---------------------------------------------------------------- decoder page

type Caps = {
  decoders: Record<string, { available: boolean; reason?: string; label: string }>;
  archives: { id: string; name: string; simulations: { id: string; created: string; seed: number }[] }[];
};

export function DecoderPage({ query }: { query: string }) {
  const q = new URLSearchParams(query);
  const [caps, setCaps] = useState<Caps | null>(null);
  const [mode, setMode] = useState(
    q.get("archive") || !q.get("session") ? "existing_archive" : "independent_import",
  );
  const [archive, setArchive] = useState(q.get("archive") || "");
  const [source, setSource] = useState(q.get("simulation") ? "simulation" : "upload");
  const [simulation, setSimulation] = useState(q.get("simulation") || "");
  const [keyMode, setKeyMode] = useState("archive");
  const [decoders, setDecoders] = useState("both");
  const [fastaFile, setFasta] = useState<File | null>(null);
  const [bundle, setBundle] = useState<File | null>(null);
  const [keyFile, setKeyFile] = useState<File | null>(null);
  const [simMeta, setSimMeta] = useState<File | null>(null);
  const [passphrase, setPassphrase] = useState("");
  const [session, setSession] = useState<DecodeSession | null>(null);
  const [sid, setSid] = useState(q.get("session") || "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<any[]>([]);
  useEffect(() => {
    api("/decoder/capabilities")
      .then((c: Caps) => {
        setCaps(c);
        if (!q.get("archive") && c.archives[0]) setArchive((a) => a || c.archives[0].id);
      })
      .catch((e) => setError(e.message));
    api("/decoder/sessions").then(setHistory).catch(() => {});
  }, []);
  useEffect(() => {
    if (!sid) return;
    let stop = false;
    const tick = () =>
      api(`/decoder/sessions/${sid}`)
        .then((s: DecodeSession) => {
          if (stop) return;
          setSession(s);
          if (s.status === "complete" || s.status === "failed") {
            stop = true;
            api("/decoder/sessions").then(setHistory).catch(() => {});
          }
        })
        .catch((e) => setError(e.message));
    tick();
    const t = setInterval(() => !stop && tick(), 1000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [sid]);
  const arch = caps?.archives.find((a) => a.id === archive);
  async function run() {
    setError("");
    setSession(null);
    const fd = new FormData();
    fd.append("mode", mode);
    fd.append("decoders", decoders);
    if (mode === "existing_archive") {
      if (!archive) return setError("Choose an archive.");
      fd.append("archive_id", archive);
      fd.append("source", source);
      if (source === "simulation") {
        if (!simulation) return setError("Choose a simulation run.");
        fd.append("simulation_id", simulation);
      }
      fd.append("key_mode", keyMode);
    } else {
      fd.append("key_mode", keyFile ? "keyfile" : "none");
      if (bundle) fd.append("bundle_file", bundle);
      if (simMeta) fd.append("simulation_metadata", simMeta);
    }
    if (source === "upload" || mode === "independent_import") {
      if (!fastaFile) return setError("Choose a FASTA or FASTQ file to decode.");
      fd.append("fasta_file", fastaFile);
    }
    if (keyFile && (mode === "independent_import" || keyMode === "keyfile")) {
      fd.append("key_file", keyFile);
      fd.append("passphrase", passphrase);
    }
    setBusy(true);
    try {
      const s = await api("/decoder/sessions", { method: "POST", body: fd });
      setPassphrase("");
      setSid(s.id);
      setSession(s);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const running = session && (session.status === "queued" || session.status === "running");
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="idx">Reads in · files out</p>
          <h1>DNA Decoder</h1>
          <p>
            Reconstruct files from DNA reads alone: clustering, consensus
            decoding, Fountain recovery, decryption and SHA-256 verification.
          </p>
        </div>
      </div>
      <div className="info">
        Works on digital FASTA/FASTQ files. Nothing here synthesizes or
        sequences physical DNA. The decoder never reads an archive’s original
        uploads or cached plaintext.
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="archive-layout">
        <section className="form-panel decoder-form">
          <fieldset className="mode">
            <legend>Recovery mode</legend>
            <label className="inline">
              <input
                type="radio"
                checked={mode === "existing_archive"}
                onChange={() => setMode("existing_archive")}
              />{" "}
              A — Existing Lazarus archive
            </label>
            <label className="inline">
              <input
                type="radio"
                checked={mode === "independent_import"}
                onChange={() => setMode("independent_import")}
              />{" "}
              B — Independent import (FASTA + recovery bundle + key file)
            </label>
          </fieldset>
          {mode === "existing_archive" ? (
            <>
              <label>
                Archive
                <select value={archive} onChange={(e) => setArchive(e.target.value)}>
                  <option value="">Choose an approved archive</option>
                  {caps?.archives.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} · {a.id}
                    </option>
                  ))}
                </select>
                <small>
                  Uses the archive’s approved metadata and its key store. Not its
                  uploaded originals.
                </small>
              </label>
              <label>
                Reads to decode
                <select value={source} onChange={(e) => setSource(e.target.value)}>
                  <option value="upload">Upload a FASTA/FASTQ file</option>
                  <option value="simulation">A post-simulation FASTA of this archive</option>
                  <option value="clean">The clean pre-simulation FASTA (control)</option>
                </select>
              </label>
              {source === "simulation" && (
                <label>
                  Simulation run
                  <select value={simulation} onChange={(e) => setSimulation(e.target.value)}>
                    <option value="">Choose a run</option>
                    {arch?.simulations.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.id} · seed {s.seed}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label>
                Decryption keys
                <select value={keyMode} onChange={(e) => setKeyMode(e.target.value)}>
                  <option value="archive">Archive key store</option>
                  <option value="keyfile">Upload a protected key file</option>
                  <option value="none">No keys (test missing-key handling)</option>
                </select>
              </label>
            </>
          ) : (
            <>
              <label className="upload">
                Recovery bundle (recovery_bundle.json, optional)
                <input
                  type="file"
                  accept=".json,application/json"
                  onChange={(e) => setBundle(e.target.files?.[0] || null)}
                />
                <small>
                  Non-secret metadata. The decoder reads the manifest from the
                  DNA itself first and uses the bundle to cross-check hashes.
                </small>
              </label>
              <label className="upload">
                Simulation metadata (optional)
                <input
                  type="file"
                  accept=".json,application/json"
                  onChange={(e) => setSimMeta(e.target.files?.[0] || null)}
                />
              </label>
            </>
          )}
          {(source === "upload" || mode === "independent_import") && (
            <label className="upload">
              FASTA or FASTQ reads
              <input
                type="file"
                accept=".fasta,.fa,.fna,.fastq,.fq,.txt"
                onChange={(e) => setFasta(e.target.files?.[0] || null)}
              />
              <small>
                Headers must carry the pool label (sample=pool-0000 or
                vault-N|pool|index). Up to 64 MB.
              </small>
            </label>
          )}
          {(mode === "independent_import" || keyMode === "keyfile") && (
            <>
              <label className="upload">
                Protected key file
                <input
                  type="file"
                  accept=".json,application/json"
                  onChange={(e) => setKeyFile(e.target.files?.[0] || null)}
                />
              </label>
              <label>
                Key file passphrase
                <input
                  type="password"
                  autoComplete="off"
                  value={passphrase}
                  onChange={(e) => setPassphrase(e.target.value)}
                />
                <small>Sent once over this connection; never stored or logged.</small>
              </label>
            </>
          )}
          <label>
            Consensus decoder
            <select value={decoders} onChange={(e) => setDecoders(e.target.value)}>
              <option value="both">Both, reported separately</option>
              <option value="baseline">Majority vote (baseline)</option>
              <option value="polish" disabled={caps ? !caps.decoders.polish.available : false}>
                Erbgut CNN PolishDecoder
                {caps && !caps.decoders.polish.available ? " (unavailable)" : ""}
              </option>
            </select>
          </label>
          <button className="primary" disabled={busy || !!running} onClick={run}>
            {busy ? "Uploading…" : running ? "Decoding…" : "Run Decoding"}
          </button>
        </section>
        <aside>
          <h2>Recent decodes</h2>
          {!history.length && <p className="muted">None yet.</p>}
          <ul className="history">
            {history.map((h) => (
              <li key={h.id}>
                <a href={`#/decoder?session=${h.id}`}>{h.fasta_name || h.id}</a>{" "}
                <VerdictBadge v={h.verdict} />
                <small>{date(h.created)}</small>
              </li>
            ))}
          </ul>
        </aside>
      </div>
      {session && <DecodeResult s={session} />}
    </>
  );
}

const STEP_LABEL: Record<string, string> = {
  parse: "Parse and validate reads",
  manifest: "Decode bootstrap manifest",
  pools: "Cluster reads, build consensus, Fountain-recover pools",
  files: "Decrypt, decompress, verify SHA-256",
};

function DecodeResult({ s }: { s: DecodeSession }) {
  const sum = s.summary;
  const base = `/api/decoder/sessions/${s.id}/files`;
  return (
    <section className="decode-result">
      <div className="section-heading">
        <h2>
          Recovery {s.status === "complete" ? "result" : "progress"}{" "}
          <VerdictBadge v={s.verdict} />
        </h2>
        <span className="mono">{s.id}</span>
      </div>
      <ol className="steps">
        {s.steps.map((st) => (
          <li key={st.step} className={st.status}>
            <b>{STEP_LABEL[st.step] || st.step}</b> — {st.detail}
          </li>
        ))}
        {(s.status === "queued" || s.status === "running") && (
          <li role="status">
            <span className="activity-dot" /> Working…
          </li>
        )}
      </ol>
      {s.status === "failed" && <div className="error">{s.error}</div>}
      {sum && (
        <>
          <p className={`verdict-text ${sum.verdict.toLowerCase()}`}>
            <b>{sum.verdict}</b> — {sum.verdict_text}
          </p>
          {sum.missing.map((m) => (
            <div key={m} className="error">
              Missing: {m}
            </div>
          ))}
          {sum.warnings.map((w) => (
            <div key={w} className="info">
              {w}
            </div>
          ))}
          <p className="muted small">
            Input {sum.input.filename} · {sum.input.format.toUpperCase()} ·{" "}
            {sum.input.records.toLocaleString()} records · manifest source:{" "}
            {sum.manifest_source || "unavailable"} ·{" "}
            {sum.simulation_id ? `simulation ${sum.simulation_id} · ` : ""}
            {sum.seconds}s
          </p>
          <h3>Decoders</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Decoder</th>
                  <th>Verdict</th>
                  <th>Manifest from DNA</th>
                  <th>Pools recovered</th>
                  <th>Time</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(sum.decoders).map(([d, v]) => (
                  <tr key={d}>
                    <td>{d === "polish" ? "CNN PolishDecoder" : "Majority vote"}</td>
                    {v.available === false ? (
                      <td colSpan={4}>Unavailable: {v.reason}</td>
                    ) : (
                      <>
                        <td>
                          <VerdictBadge v={v.verdict} />
                        </td>
                        <td>{v.manifest_recovered ? "Yes" : "No"}</td>
                        <td>
                          {v.pools_recovered} / {v.pools}
                        </td>
                        <td>{v.seconds}s</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>Files</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Result</th>
                  <th>Expected / actual SHA-256</th>
                  <th>Download</th>
                </tr>
              </thead>
              <tbody>
                {sum.files.map((f) => {
                  const stored = s.files.find((x) => x.name === f.name);
                  return (
                    <tr key={f.name}>
                      <td>{f.name}</td>
                      <td className={f.verified ? "success-text" : "failure-text"}>
                        {f.verified ? `Byte-exact (${f.decoder})` : f.reason || f.status}
                      </td>
                      <td className="mono hash">
                        {f.expected_sha256}
                        <br />
                        {f.actual_sha256 || "—"}
                      </td>
                      <td>
                        {stored ? (
                          <a href={`${base}/recovered/${stored.index}?download=1`}>
                            Download verified file
                          </a>
                        ) : (
                          "No verified file"
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="actions">
            <a className="button" target="_blank" rel="noreferrer" href={`${base}/report.html`}>
              View verification report
            </a>
            <a className="button" href={`${base}/report.json?download=1`}>
              Download report (JSON)
            </a>
            <a className="button" href={`${base}/report.html?download=1`}>
              Download report (HTML)
            </a>
          </div>
          <p className="muted small">
            One decoding trial. Success means reconstructed bytes match the
            expected SHA-256 exactly; it does not estimate reliability across
            repeated trials or prove physical DNA durability.
          </p>
        </>
      )}
    </section>
  );
}
