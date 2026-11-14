import StorageScale from "./StorageScale";
import { LearnedArchive } from "./LearnedArchive";
import DnaExplorer from "./DnaExplorer";
import { useEffect, useRef, useState } from "react";
import {
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type {
  Archive,
  ArchiveSummary,
  FileInfo,
  Policy,
  Ev,
  Pending,
} from "./types";
import { Journey, FilePreview, ProgressInfo, DnaStory } from "./experience";
import { api, date, post } from "./api";
import { DecoderPage, DnaExperiment } from "./DnaWorkflow";
import { ThemeToggle } from "./theme";
import Helix3D from "./Helix";
const money = (v?: number) =>
  v == null
    ? "Not recorded"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
      }).format(v);
const defaults: Policy = {
  retention_years: 50,
  budget_usd: 50,
  tech: "nanopore",
  coverage: 10,
  n_vaults: 3,
  target: 1,
  notes: "",
};
function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  return error ? (
    <div className="error" role="alert">
      {error} {retry && <button onClick={retry}>Try again</button>}
    </div>
  ) : null;
}
export default function App() {
  const [hash, setHash] = useState(location.hash);
  const [health, setHealth] = useState<{ llm: boolean } | null>(null);
  const [connection, setConnection] = useState("");
  const connect = () =>
    api("/health")
      .then((h) => {
        setHealth(h);
        setConnection("");
      })
      .catch(() => setConnection("Cannot connect to the archive service."));
  useEffect(() => {
    connect();
    const f = () => setHash(location.hash);
    addEventListener("hashchange", f);
    return () => removeEventListener("hashchange", f);
  }, []);
  const id = hash.startsWith("#/job/") ? hash.slice(6).split("?")[0] : null;
  const decoderPage = hash.startsWith("#/decoder");
  return (
    <>
      <header className="site-header">
        <div className="header-inner">
        <a className="brand" href="#/" aria-label="Lazarus home">
          <BrandMark />
          <span className="brand-text">
            Lazarus<span>Records that endure</span>
          </span>
        </a>
        <nav aria-label="Main navigation">
          <a
            aria-current={
              !id && !hash.startsWith("#/new") && !decoderPage
                ? "page"
                : undefined
            }
            href="#/"
          >
            Archives
          </a>
          <a href="#/new">New archive</a>
          <a aria-current={decoderPage ? "page" : undefined} href="#/decoder">
            DNA Decoder
          </a>
        </nav>
        <div className="header-end">
          <ThemeToggle />
        </div>
        </div>
      </header>
      <div className="notice">
        <span className="simulation">Simulation workspace</span>
        Test DNA archive designs and recovery. No physical DNA is produced or
        purchased.
      </div>
      <main>
        <ErrorBox error={connection} retry={connect} />
        <div className="page" key={hash.split("?")[0]}>
        {decoderPage ? (
          <DecoderPage key={hash} query={hash.split("?")[1] || ""} />
        ) : id ? (
          <ArchiveView key={id} id={id} />
        ) : hash.startsWith("#/new") ? (
          <Create
            key={hash}
            sample={hash.includes("sample")}
            llm={!!health?.llm}
          />
        ) : (
          <Archives />
        )}
        </div>
      </main>
      <footer>
        <div className="footer-inner">
          <span>Lazarus · DNA archive simulation</span>
          <span>Retention is a test input, not a legal recommendation.</span>
        </div>
      </footer>
    </>
  );
}
function Archives() {
  const [jobs, setJobs] = useState<ArchiveSummary[] | null>(null);
  const [error, setError] = useState("");
  const load = () =>
    api("/jobs")
      .then((j) => {
        setJobs(j);
        setError("");
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);
  return (
    <>
      <section className="hero">
        <div className="hero-copy">
          <span className="eyebrow">The DNA archive workspace</span>
          <h1>Keep important records <em>recoverable.</em></h1>
          <p>
            Turn a file into a tested DNA archive. Restore it and see proof that every byte came back.
          </p>
          <div className="actions">
            <a className="button primary" href="#/new">
              Archive my files
            </a>
            <a className="button" href="#/new?sample">
              Try a picture demo
            </a>
          </div>
        </div>
        <HeroHelix jobs={jobs} />
      </section>
      <Journey />
      <StorageScale />
      <ErrorBox error={error} retry={load} />
      {!jobs ? (
        <p role="status">Loading archives…</p>
      ) : !jobs.length ? (
        <section className="empty-state">
          <h2>Your first archive starts with your records.</h2>
          <p>
            Archive your files to test whether your records can be recovered.
          </p>
          <a className="button primary" href="#/new">
            Archive my files
          </a>
          <p>
            Or explore with fictional Northstar Bio records using “Try sample
            archive.”
          </p>
        </section>
      ) : (
        <div className="archive-cards">
          {jobs.map((j, i) => <a className="archive-card" key={j.id} href={`#/job/${j.id}`} style={{ "--i": i } as React.CSSProperties}>
            <span className={`badge ${j.presentation.verified && !j.presentation.needs_retest ? "success" : ""}`}>{j.presentation.label}</span>
            <h2>{j.name}</h2><p>{j.company}</p>
            <dl className="facts"><div><dt>Selected files</dt><dd>{j.file_count ?? "Not recorded"}</dd></div><div><dt>Simulated aging</dt><dd>{j.retention_years} years</dd></div></dl>
            <small>Latest test: {date(j.presentation.latest_test)}</small>
            <strong>{j.presentation.pending_action ? "Review your decision →" : j.presentation.verified ? "Open recovered files →" : "View progress and next step →"}</strong>
          </a>)}
        </div>
      )}
    </>
  );
}
function Create({ sample, llm }: { sample: boolean; llm: boolean }) {
  const revised = (() => {
    if (sample) return null;
    try {
      return JSON.parse(sessionStorage.getItem("archive-revision") || "null");
    } catch {
      return null;
    }
  })();
  const [step, setStep] = useState(0);
  const [name, setName] = useState(
    revised?.name || (sample ? "Northstar Bio records" : ""),
  );
  const [company, setCompany] = useState(
    revised?.company || (sample ? "Northstar Bio" : ""),
  );
  const [policy, setPolicy] = useState<Policy>(revised?.policy || (sample ? {...defaults, coverage:16} : defaults));
  const [encodingMode, setEncodingMode] = useState("evaluated");
  const [modelAvailable, setModelAvailable] = useState<boolean | null>(null);
  const [modelError, setModelError] = useState("");
  useEffect(() => {
    if (sample) return;
    let active = true;
    setModelAvailable(null);
    post("/encoding-options", policy).then(r => {if (active) {setModelAvailable(r.available); setModelError("");}}).catch(e => {if (active) setModelError(e.message);});
    return () => {active = false;};
  }, [sample, policy.tech, policy.retention_years, policy.coverage]);
  const [mode, setMode] = useState(llm ? "agent" : "autopilot");
  const [samples, setSamples] = useState<FileInfo[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [excluded, setExcluded] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setMode(llm ? "agent" : "autopilot");
  }, [llm]);
  const loadSamples = () =>
    api(sample ? "/samples?preset=quick_demo" : "/samples")
      .then(setSamples)
      .catch((e) => setError(e.message));
  useEffect(() => {
    if (sample) loadSamples();
  }, [sample]);
  const records: FileInfo[] = sample
    ? samples
    : files.map((f) => ({ name: f.name, bytes: f.size }));
  const selected = records.filter((f) => !excluded.includes(f.name));
  const total = records.reduce((n, f) => n + f.bytes, 0);
  const set = (key: keyof Policy, value: string | number) =>
    setPolicy((p) => ({ ...p, [key]: value }));
  function next() {
    setError("");
    if (step === 0 && !selected.length)
      return setError(
        "Select at least one file to archive.",
      );
    if (total > 200000)
      return setError(
        "The demo accepts up to 200 KB total. Choose fewer or smaller files.",
      );
    if (step === 1 && !sample && encodingMode === "evaluated" && !modelAvailable)
      return setError("No compatible evaluated model is available. Choose fresh learning or standard encoding.");
    if (
      step === 1 &&
      (!(policy.retention_years >= 0 && policy.retention_years <= 1000) ||
        policy.budget_usd <= 0 ||
        policy.coverage < 1 ||
        policy.coverage > 100 ||
        policy.n_vaults < 1 ||
        policy.n_vaults > 6)
    )
      return setError("Check the requirements and advanced settings.");
    setStep(step + 1);
  }
  async function submit() {
    setBusy(true);
    setError("");
    const fd = new FormData();
    fd.append("name", name.trim() || selected[0]?.name || "My archive");
    fd.append("company", company.trim() || "Personal workspace");
    fd.append("analysis_preset", sample ? "quick_demo" : "standard");
    fd.append("policy", JSON.stringify(policy));
    fd.append("mode", mode);
    fd.append("encoding_mode", sample ? "standard" : encodingMode);
    fd.append("use_samples", String(sample));
    fd.append("selected_files", JSON.stringify(selected.map((f) => f.name)));
    files.forEach((f) => fd.append("files", f));
    try {
      const r = await api("/jobs", { method: "POST", body: fd });
      sessionStorage.removeItem("archive-revision");
      location.hash = `#/job/${r.job_id}`;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <a href="#/" className="back">
        Back to archives
      </a>
      <div className="page-heading">
        <div>
          <h1>{sample ? "Try a picture demo" : "Archive your files"}</h1>
          <p>
            Choose your records and requirements. We’ll test the archive design
            before you approve it.
          </p>
        </div>
      </div>
      <ol className="wizard-steps">
        {["Records", "Requirements", "Review"].map((n, i) => (
          <li key={n} aria-current={i === step ? "step" : undefined}>
            <span>{i + 1}</span>
            {n}
          </li>
        ))}
      </ol>
      <div className="setup-layout">
        <section className="form-panel">
          <ErrorBox
            error={error}
            retry={sample && !samples.length ? loadSamples : undefined}
          />
          {step === 0 && (
            <>
              <h2>Which records need to last?</h2>
              <p>
                Choose final records that change infrequently. You decide
                exactly what enters this archive.
              </p>
              <label>
                Archive name (optional)
                <input
                  value={name}
                  placeholder="e.g. Clinical trial records, 2026"
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <label>
                Organization (optional)
                <input
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                />
              </label>
              {sample ? (
                <div className="info">
                  A small sample picture. Real encoding and recovery, with three trials per measured point. No company data is needed.
                </div>
              ) : (
                <label className="upload">
                  Choose records
                  <input
                    type="file"
                    multiple
                    onChange={(e) => {
                      const next = Array.from(e.target.files || []);
                      if (
                        new Set(next.map((f) => f.name)).size !== next.length
                      ) {
                        setError(
                          "Duplicate filenames. Rename the files before uploading.",
                        );
                        setFiles([]);
                      } else {
                        setFiles(next);
                        setExcluded([]);
                        setError("");
                      }
                    }}
                  />
                  <small>
                    Up to 200 KB total. Files are encrypted before DNA encoding.
                  </small>
                </label>
              )}
              {!sample && <p className="muted">Up to 200 KB total, including all selected uploads.</p>}
              {!!records.length && (
                <div className="record-list">
                  {records.map((f) => (
                    <label className="record" key={f.name}>
                      <FilePreview name={f.name} file={files.find(x => x.name === f.name)} src={sample ? `/api/samples/${encodeURIComponent(f.name)}/preview` : undefined} />
                      <input
                        type="checkbox"
                        checked={!excluded.includes(f.name)}
                        onChange={(e) =>
                          setExcluded(
                            e.target.checked
                              ? excluded.filter((n) => n !== f.name)
                              : [...excluded, f.name],
                          )
                        }
                      />
                      <span>
                        {f.name}
                        <small>
                          {(f.bytes / 1000).toFixed(1)} KB
                          {f.name.endsWith(".txt")
                            ? " · Check that this is a final record, not a working draft."
                            : ""}
                        </small>
                      </span>
                    </label>
                  ))}
                </div>
              )}
              <p className="muted">
                {selected.length} records selected ·{" "}
                {(selected.reduce((n, f) => n + f.bytes, 0) / 1000).toFixed(1)}{" "}
                KB selected
              </p>
            </>
          )}
          {step === 0 && selected.length > 0 && <StorageScale files={selected} />}
          {step === 1 && (
            <>
              <h2>What must this archive support?</h2>
              {!sample && <fieldset><legend>How should we design the archive?</legend>
                <label>Encoding approach<select value={encodingMode} onChange={e => setEncodingMode(e.target.value)}>
                  <option value="evaluated">Use an evaluated learned model</option>
                  <option value="fresh">Train a fresh learned model</option>
                  <option value="standard">Use standard DNA rules</option>
                </select></label>
                <p>{modelAvailable === null ? "Checking for a compatible model…" : modelAvailable ? "An evaluated model matches these reader and aging settings." : "No evaluated model matches these settings. Choose fresh learning or standard rules to continue."}</p>
                {modelError && <p className="error">{modelError}</p>}
                <small>Fresh learning runs real computation with a ten-minute limit and can be canceled. It compares learned and standard DNA on your files. All results are simulated; a learned design may not improve recovery.</small>
              </fieldset>}
              <div className="two">
                <label>
                  How many years should we simulate?
                  <select value={policy.retention_years} disabled={sample} onChange={e => set("retention_years", +e.target.value)}>
                    {[10,25,50,100].map(y => <option key={y} value={y}>{y} years</option>)}
                    {![10,25,50,100].includes(policy.retention_years) && <option value={policy.retention_years}>{policy.retention_years} years</option>}
                  </select>
                  <small>
                    We model aging over this period, then try recovery now. This is not a promise that physical DNA will last that long.
                  </small>
                </label>
                <label>
                  Modeled DNA writing budget (USD)
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={policy.budget_usd}
                    onChange={(e) => set("budget_usd", +e.target.value)}
                  />
                  <small>
                    This limits the simulated DNA design. Approving it purchases no storage. Gemini API usage is billed separately by your provider.
                  </small>
                </label>
              </div>
              <label>
                Business requirements (optional)
                <textarea
                  rows={3}
                  value={policy.notes}
                  onChange={(e) => set("notes", e.target.value)}
                  placeholder="e.g. Keep final trial records and test loss of one location."
                />
              </label>
              {sample && <p className="info">Picture demo: 50 simulated years, three locations, 16 reads per piece, three trials per point. Use “Archive my files” for custom settings.</p>}
              <details>
                <summary>Advanced settings</summary>
                <fieldset disabled={sample}>
                <p>The app tests technical designs against these settings.</p>
                <div className="two">
                  <label>
                    DNA reader
                    <select
                      value={policy.tech}
                      onChange={(e) => set("tech", e.target.value)}
                    >
                      <option value="nanopore">Nanopore</option>
                      <option value="illumina">Illumina</option>
                    </select>
                    <small>Simulated read technology and error pattern.</small>
                  </label>
                  <label>
                    Reads per DNA piece
                    <input
                      type="number"
                      min="1"
                      max="100"
                      value={policy.coverage}
                      onChange={(e) => set("coverage", +e.target.value)}
                    />
                    <small>
                      More reads can improve recovery and increase estimated
                      cost.
                    </small>
                  </label>
                  <label>
                    Storage locations
                    <input
                      type="number"
                      min="1"
                      max="6"
                      value={policy.n_vaults}
                      onChange={(e) => set("n_vaults", +e.target.value)}
                    />
                    <small>
                      Three is recommended to test losing a location.
                    </small>
                  </label>
                  <label>
                    Required trial success
                    <select
                      value={policy.target}
                      onChange={(e) => set("target", +e.target.value)}
                    >
                      <option value="1">All simulated trials</option>
                      <option value="0.9">90% of simulated trials</option>
                    </select>
                  </label>
                </div>
                </fieldset>
                <label>
                  Analysis method
                  <select
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                  >
                    <option disabled={!llm} value="agent">
                      AI-guided analysis
                    </option>
                    <option value="autopilot">Scripted analysis</option>
                  </select>
                  <small>
                    {llm
                      ? "AI-guided analysis can revise the design using measured results."
                      : "Scripted analysis is available. AI-guided analysis is not configured."}
                  </small>
                </label>
              </details>
            </>
          )}
          {step === 2 && (
            <>
              <h2>Review your archive request</h2>
              <dl className="facts">
                <div>
                  <dt>Archive</dt>
                  <dd>{name}</dd>
                </div>
                <div>
                  <dt>Organization</dt>
                  <dd>{company}</dd>
                </div>
                <div>
                  <dt>Retention</dt>
                  <dd>{policy.retention_years} years</dd>
                </div>
                <div>
                  <dt>Estimated budget</dt>
                  <dd>{money(policy.budget_usd)}</dd>
                </div>
                <div>
                  <dt>Analysis</dt>
                  <dd>{mode === "agent" ? "AI-guided" : "Scripted"}</dd>
                </div>
              </dl>
              <h3>Selected records ({selected.length})</h3>
              <ul>
                {selected.map((f) => (
                  <li key={f.name}>{f.name}</li>
                ))}
              </ul>
              {!!excluded.length && (
                <p className="muted">Excluded: {excluded.join(", ")}</p>
              )}
              {policy.notes && <p>{policy.notes}</p>}
              <div className="info">
                Analysis does not create physical DNA or purchase storage.
                You’ll review the proposed design before a simulated archive is
                prepared.
              </div>
            </>
          )}
          <div className="form-actions">
            {step > 0 && (
              <button
                disabled={busy}
                onClick={() => {
                  setStep(step - 1);
                  setError("");
                }}
              >
                Back
              </button>
            )}
            <button
              className="primary"
              disabled={busy}
              onClick={step < 2 ? next : submit}
            >
              {busy
                ? "Starting analysis…"
                : step < 2
                  ? "Continue"
                  : "Analyze archive"}
            </button>
          </div>
        </section>
        <aside>
          <h2>You define the requirements.</h2>
          <p>
            Lazarus tests how to encode and recover your records. You don’t need
            to choose a DNA encoding design.
          </p>
          <hr />
          <h3>What you’ll get</h3>
          <p>
            A proposed archive, an estimated cost, and measured recovery results
            for each selected file.
          </p>
          <h3>Two decisions stay with you</h3>
          <p>
            Approve the simulated archive, then approve a recovery test that
            removes this job’s working copies.
          </p>
        </aside>
      </div>
    </>
  );
}
function ArchiveView({ id }: { id: string }) {
  const [job, setJob] = useState<Archive | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [evs, setEvs] = useState<Ev[]>([]);
  const [loss, setLoss] = useState<number | null>(null);
  const [tab, setTabState] = useState<Tab | null>(() => {
    const t = new URLSearchParams(location.hash.split("?")[1] || "").get("tab");
    return TABS.some((x) => x.id === t) ? (t as Tab) : null;
  });
  const setTab = (t: Tab) => {
    setTabState(t);
    history.replaceState(null, "", `#/job/${id}?tab=${t}`);
  };
  const refresh = () =>
    api(`/jobs/${id}`)
      .then((j) => {
        setJob(j);
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [id]);
  useEffect(() => {
    let active = true;
    let es: EventSource | null = null;
    api(`/jobs/${id}/eventlog`)
      .then((log) => {
        if (!active) return;
        setEvs(log);
        es = new EventSource(`/api/jobs/${id}/events?since=${log.length}`);
        es.onmessage = (m) => {
          const ev = JSON.parse(m.data);
          setEvs((old) =>
            old.some((e) => e.seq === ev.seq) ? old : [...old, ev],
          );
        };
      })
      .catch(() => {});
    return () => {
      active = false;
      es?.close();
    };
  }, [id]);
  async function action(path: string, body = {}) {
    setBusy(true);
    setError("");
    try {
      await post(`/jobs/${id}${path}`, body);
      setLoss(null);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function revise() {
    if (!job) return;
    sessionStorage.setItem(
      "archive-revision",
      JSON.stringify({
        name: `${job.name || job.company} (revised)`,
        company: job.company,
        policy: job.policy,
      }),
    );
    location.hash = "#/new";
  }
  if (!job)
    return (
      <>
        <ErrorBox
          error={error}
          retry={() => {
            setError("");
            refresh();
          }}
        />
        <p>Loading archive…</p>
        <a href="#/">Back to archives</a>
      </>
    );
  const latest =
    job.status === "recovering" ? undefined : job.drills[job.drills.length - 1];
  const files =
    job.intake_files ||
    job.files.map((f) => ({
      ...f,
      included: job.selected_files
        ? job.selected_files.includes(f.name)
        : Object.keys(job.sealed).includes(f.name),
    }));
  const expected = job.selected_files || Object.keys(job.sealed);
  const p = job.presentation;
  const pending = job.pending;
  const phase = [
    "Requirements",
    "Analysis",
    "Review proposal",
    "Recovery test",
    "Results",
  ];
  const stage =
    p.phase === "review"
      ? 2
      : p.phase === "recovery"
        ? 3
        : p.phase === "results"
          ? 4
          : 1;
  const storage =
    job.storage?.backend === "supabase"
      ? job.storage.state === "saved"
        ? "Supabase"
        : job.storage.state === "failed"
          ? "Cloud save failed"
          : job.storage.state === "uploading"
            ? "Saving to Supabase…"
            : "Not saved to cloud yet"
      : "This computer";
  const active: Tab = tab || (latest ? "recovery" : "dna");
  const filesTable = (
    <section>
      <div className="section-heading">
        <h2>Your files</h2>
        <span>{expected.length || "Not recorded"} records</span>
      </div>
      <p className="muted">Each included file must be restored unchanged for the archive to pass recovery.</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Record</th>
              <th>Size</th>
              <th>Included</th>
            </tr>
          </thead>
          <tbody>
            {files.map((f) => (
              <tr key={f.name}>
                <td>
                  <div className="file-cell">
                    {f.included && job.originals_available && (
                      <FilePreview name={f.name} src={`/api/jobs/${id}/preview/${encodeURIComponent(f.name)}`} />
                    )}
                    <span>{f.name}</span>
                  </div>
                </td>
                <td>{(f.bytes / 1000).toFixed(1)} KB</td>
                <td>{f.included ? "Yes" : "Excluded by user"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
  const technical = (
    <section className="technical">
      <h2>How this design was chosen</h2>
      <p className="muted">
        {job.mode === "agent" ? "AI-guided analysis" : "Scripted analysis"} · every point is a measured simulation.
      </p>
      <h3>Codec experiments</h3>
      <ExperimentChart rows={job.experiments} target={job.policy.target} />
      <h3>Resilience experiments</h3>
      <StressTable rows={job.stress} final={job.order?.settings} />
      <details>
        <summary>Agent activity</summary>
        <Timeline evs={evs} />
      </details>
      {latest && (
        <details>
          <summary>Hashes and decoder evidence</summary>
          <pre>{JSON.stringify(latest, null, 2)}</pre>
        </details>
      )}
      {job.order && (
        <details>
          <summary>Synthesis files</summary>
          {job.order.order_files.map((f) => (
            <p key={f}>
              <a target="_blank" rel="noreferrer" href={`/api/jobs/${id}/files/${f}`}>
                {f}
              </a>
            </p>
          ))}
        </details>
      )}
    </section>
  );
  return (
    <>
      <a className="back" href="#/">
        Back to archives
      </a>
      <div className="archive-head">
        <div>
          <h1>{job.name || job.company}</h1>
          <p className="muted">
            {job.company} · Created {date(job.created)}
          </p>
        </div>
        <div className="actions">
          <span className={`badge ${p.verified && !p.needs_retest ? "success" : ""}`}>{p.label}</span>
          <button className="ghost small-button" onClick={revise}>
            Create revised archive
          </button>
        </div>
      </div>
      <dl className="summary">
        <div>
          <dt>Retention</dt>
          <dd>{job.policy.retention_years} years</dd>
        </div>
        <div>
          <dt>Modeled writing cost</dt>
          <dd>
            {money(job.order?.cost.write_usd || pending?.summary.write_usd)} <small>of {money(job.policy.budget_usd)} budget</small>
          </dd>
        </div>
        <div>
          <dt>Storage locations</dt>
          <dd>{job.order?.settings.n_vaults || job.policy.n_vaults}</dd>
        </div>
        <div>
          <dt>Saved on</dt>
          <dd>{storage}</dd>
        </div>
      </dl>
      {!job.order && (
        <ol className="workflow">
          {phase.map((label, i) => (
            <li key={label} aria-current={stage === i ? "step" : undefined} className={i < stage ? "complete" : ""}>
              {label}
            </li>
          ))}
        </ol>
      )}
      <ErrorBox
        error={error}
        retry={() => {
          setError("");
          refresh();
        }}
      />
      {job.error && (
        <div className="error">
          {job.error}
          <div>
            <button onClick={revise}>Create revised archive</button>
          </div>
        </div>
      )}
      <div className="archive-body">
        {(p.phase === "analysis" || job.status === "recovering") && (
          <section className="analysis-status" role="status">
            <span className="activity-dot" />
            <div>
              <h2>
                {job.status === "recovering"
                  ? "Restoring records and checking file integrity"
                  : "Testing a design for your records"}
              </h2>
              <p>{activity(evs)}</p>
              <ProgressInfo job={job} events={evs} />
              <small>Results will appear as tests complete. No decision is needed yet.</small>
            </div>
          </section>
        )}
        {pending && (
          <Approval
            key={`${pending.tool}:${evs.filter((e) => e.type === "interrupt").length}`}
            p={pending}
            busy={busy}
            decide={(d) => action("/approve", { decision: d })}
            correct={() => action("/approve", { decision: "edit", args: pending.summary.correction })}
          />
        )}
        {["attention"].includes(p.phase) && (
          <section>
            <h2>Your next step</h2>
            <p>
              Start a revised archive with these requirements. If storage locations exist, you can also run another
              recovery test.
            </p>
            <button onClick={revise}>Create revised archive</button>
          </section>
        )}
        {!job.order ? (
          <>
            <LearnedArchive job={job} busy={busy} action={action} />
            {filesTable}
            <details className="technical-toggle">
              <summary>How this design is being chosen</summary>
              {technical}
            </details>
          </>
        ) : (
          <>
            <Tabs active={active} onChange={setTab} />
            <div className="tab-panel" role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`} key={active}>
              {active === "recovery" && (
                <>
                  {p.needs_retest && (
                    <div className="info">
                      Available locations have changed since the latest recovery test. Run another test to check the
                      current archive.
                    </div>
                  )}
                  {latest ? (
                    <section className="results">
                      <div className="section-heading">
                        <div>
                          <h2 className={latest.all_verified ? "success-text" : "failure-text"}>
                            {latest.all_verified
                              ? "All selected files restored unchanged"
                              : latest.files.some((f) => f.sha256_match)
                                ? "Some files could not be restored"
                                : "Recovery test failed"}
                          </h2>
                          <p className="muted">
                            Tested {date(latest.tested_at)} · {latest.files.filter((f) => f.sha256_match).length} of{" "}
                            {expected.length || latest.files.length} records restored · {latest.vaults_available.length}{" "}
                            of {latest.n_vaults} locations available
                          </p>
                        </div>
                        {job.certificate && job.status !== "recovering" && (
                          <a
                            className="button small-button"
                            target="_blank"
                            rel="noreferrer"
                            href={`/api/jobs/${id}/files/${job.certificate}`}
                          >
                            View recovery report
                          </a>
                        )}
                      </div>
                      {latest.error && (
                        <div className="error">{latest.error}. Review available locations or create a revised archive.</div>
                      )}
                      <ul className="restored">
                        {expected.map((n) => {
                          const f = latest.files.find((f) => f.name === n);
                          const href = `/api/jobs/${id}/files/restored/${encodeURIComponent(n)}`;
                          return (
                            <li key={n} className={f?.sha256_match ? "ok" : "bad"}>
                              {f?.sha256_match ? (
                                <FilePreview
                                  name={n}
                                  src={`/api/jobs/${id}/preview/${encodeURIComponent(n)}?stage=restored&attempt=${job.drills.length}`}
                                />
                              ) : (
                                <span className="file-icon">—</span>
                              )}
                              <div className="restored-name">
                                <strong>{n}</strong>
                                <small>{f?.sha256_match ? "Restored unchanged · SHA-256 match" : f?.error || "Not restored"}</small>
                              </div>
                              {f?.sha256_match ? (
                                <div className="actions">
                                  <a href={href} target="_blank" rel="noreferrer">
                                    Open restored file
                                  </a>
                                  <a className="button small-button" download={n} href={href}>
                                    Download
                                  </a>
                                </div>
                              ) : (
                                <span className="muted">No verified file</span>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                      <p className="fine">
                        File integrity is checked against the original SHA-256 fingerprint. Simulation evidence is not
                        regulatory certification.
                      </p>
                    </section>
                  ) : (
                    <p className="muted">No recovery test has run yet.</p>
                  )}
                  {!job.pending && (
                    <section>
                      <h2>Recovery scenarios</h2>
                      <p className="muted">
                        Test again, or simulate losing a storage location. This affects only this simulated archive.
                      </p>
                      <div className="locations">
                        {job.vaults.map((v) => (
                          <div key={v.vault_id} className={v.status === "destroyed" ? "lost" : ""}>
                            <strong>Location {v.vault_id}</strong>
                            <span>{v.status === "destroyed" ? "Unavailable" : "Available"}</span>
                            <button
                              className="small-button"
                              disabled={busy || !job.finished || v.status === "destroyed" || job.status === "recovering"}
                              onClick={() => setLoss(v.vault_id)}
                            >
                              Simulate loss of location
                            </button>
                          </div>
                        ))}
                      </div>
                      {loss !== null && (
                        <div className="confirmation">
                          <h3>Simulate loss of location {loss}?</h3>
                          <p>This removes its simulated DNA order files. Recovery will use the remaining locations.</p>
                          <div className="actions">
                            <button disabled={busy} onClick={() => setLoss(null)}>
                              Cancel
                            </button>
                            <button className="danger" disabled={busy} onClick={() => action(`/vaults/${loss}/destroy`)}>
                              Confirm simulated loss
                            </button>
                          </div>
                        </div>
                      )}
                      <button
                        className="primary"
                        disabled={busy || !job.finished || job.status === "recovering"}
                        onClick={() => action("/drill", { attempt: job.drills.length })}
                      >
                        {busy || job.status === "recovering" ? "Recovery operation in progress…" : "Run another recovery test"}
                      </button>
                    </section>
                  )}
                </>
              )}
              {active === "dna" && (
                <>
                  <DnaStory job={job} id={id} />
                  <StorageScale job={job} />
                  <DnaExplorer job={job} />
                </>
              )}
              {active === "damage" && <DnaExperiment id={id} job={job} />}
              {active === "details" && (
                <>
                  <LearnedArchive job={job} busy={busy} action={action} />
                  {filesTable}
                  {technical}
                  {job.policy.notes && (
                    <section>
                      <h2>Your requirements</h2>
                      <p>{job.policy.notes}</p>
                    </section>
                  )}
                  <p className="fine">
                    Costs and storage conditions are modeled. Passing these trials does not guarantee future recovery.
                  </p>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </>
  );
}

type Tab = "recovery" | "dna" | "damage" | "details";
const TABS: { id: Tab; label: string }[] = [
  { id: "recovery", label: "Recovery" },
  { id: "dna", label: "DNA" },
  { id: "damage", label: "Damage test" },
  { id: "details", label: "Details" },
];
function Tabs({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  const move = (dir: number) => {
    const i = TABS.findIndex((t) => t.id === active);
    const next = TABS[(i + dir + TABS.length) % TABS.length].id;
    onChange(next);
    document.getElementById(`tab-${next}`)?.focus();
  };
  return (
    <div className="tabs" role="tablist" aria-label="Archive sections">
      {TABS.map((t) => (
        <button
          key={t.id}
          id={`tab-${t.id}`}
          role="tab"
          aria-selected={active === t.id}
          aria-controls={`panel-${t.id}`}
          tabIndex={active === t.id ? 0 : -1}
          onClick={() => onChange(t.id)}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight") move(1);
            if (e.key === "ArrowLeft") move(-1);
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

function activity(evs: Ev[]) {
  const last = [...evs].reverse().find((e) => e.type === "tool_call");
  if (!last) return "Preparing your archive analysis.";
  const names: Record<string, string> = {
    inventory_files: "Preparing your file: checking the selected records.",
    prepare_archive: "Compressing and encrypting your records.",
    prepare_learned_model: "Preparing the chosen encoding approach and model evidence.",
    compare_archive_candidates: "Comparing frozen standard and learned DNA on your files.",
    validate_archive_candidate: "Testing the selected DNA against independent failures.",
    run_codec_sweep: "Comparing designs using real codec experiments.",
    run_quick_design: "Comparing designs and testing failures. Three trials per point.",
    stress_test: "Testing failures: checking whether the archive can still be recovered.",
    place_synthesis_order: "Preparing the approved simulated archive.",
    recover_archive: "Restoring records and checking file integrity.",
    write_certificate: "Preparing your recovery report.",
  };
  return names[last.data.tool] || "Evaluating the archive design.";
}
function Approval({
  p,
  busy,
  decide,
  correct,
}: {
  correct: () => void;
  p: Pending;
  busy: boolean;
  decide: (d: string) => void;
}) {
  const order = p.tool === "place_synthesis_order";
  const shown = p.summary.can_approve ? p.summary : p.summary.correction_summary || p.summary;
  const shownArgs = p.summary.correction_summary ? p.summary.correction || p.args : p.args;
  return (
    <section className="approval">
      <span className="badge">Your decision</span>
      <h2>
        {order ? "Review the proposed archive" : "Run the recovery test?"}
      </h2>
      {order ? (
        <>
          <p>
            Review the estimated cost and measured resilience before preparing
            this simulated archive.
          </p>
          <dl className="facts">
            <div>
              <dt>Modeled writing cost</dt>
              <dd>{money(shown.write_usd)}</dd>
            </div>
            <div>
              <dt>Modeled cost per recovery test</dt>
              <dd>{money(shown.read_usd)}</dd>
            </div>
            <div>
              <dt>Storage locations</dt>
              <dd>{String(shownArgs.n_vaults || 3)}</dd>
            </div>
          </dl>
          {p.args.candidate_id && <p>Exact tested candidate: <code className="candidate-id">{String(p.args.candidate_id)}</code>. These measurements use a small exploratory trial count.</p>}
          <table>
            <thead>
              <tr>
                <th>Resilience test</th>
                <th>Successful trials</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {shown.evidence?.map((e) => (
                <tr key={e.scenario}>
                  <td>{e.label}</td>
                  <td>
                    {e.trials == null
                      ? "Not tested"
                      : `${e.recovered} / ${e.trials}`}
                  </td>
                  <td>
                    {e.state === "passed"
                      ? "Passed"
                      : e.state === "failed"
                        ? "Failed"
                        : "Not tested for this design"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {p.summary.correction && <div className="info">The AI proposed different settings. The results above describe the measured alternative that passed the required tests. <button disabled={busy} onClick={correct}>Use tested settings and approve</button></div>}
          {!p.summary.can_approve && !p.summary.correction && (
            <div className="error">
              This proposal needs passing tests for the selected design within
              budget. Reject it to revise the requirements.
            </div>
          )}
          <p>
            These are modeled DNA costs; Gemini API charges are separate. Simulation results do not guarantee future recovery. No purchase
            will be made.
          </p>
        </>
      ) : (
        <p>
          This deletes this job’s uploaded and staging copies, then attempts to
          rebuild your selected records from simulated DNA. Files elsewhere on
          your computer remain untouched.
        </p>
      )}
      <div className="actions">
        <button
          className="primary"
          disabled={busy || (order && !p.summary.can_approve)}
          onClick={() => decide("approve")}
        >
          {busy
            ? "Saving decision…"
            : order
              ? "Approve simulated archive"
              : "Run recovery test"}
        </button>
        <button disabled={busy} onClick={() => decide("reject")}>
          {order ? "Reject proposal" : "Skip recovery test"}
        </button>
      </div>
    </section>
  );
}
function Timeline({ evs }: { evs: Ev[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [evs.length]);
  const shown = evs.filter((e) =>
    ["message", "delegate", "tool_call", "interrupt", "file_write"].includes(
      e.type,
    ),
  );
  return (
    <div className="timeline" ref={ref}>
      {shown.length === 0 && <div className="empty">Starting…</div>}
      {shown.map((e) => {
        if (e.type === "tool_call")
          return (
            <div key={e.seq} className={`ev tool ${e.agent}`}>
              <span className="mono">▸ {e.data.tool}</span>{" "}
              <span className="mono">{fmtArgs(e.data.args)}</span>
            </div>
          );
        if (e.type === "delegate")
          return (
            <div key={e.seq} className={`ev ${e.data.subagent}`}>
              <div className={`who ${e.agent}`}>
                supervisor → {e.data.subagent}
              </div>
              <div className="txt small">{e.data.description}</div>
            </div>
          );
        if (e.type === "interrupt")
          return (
            <div key={e.seq} className="ev human">
              <div className="who human">awaiting human approval</div>
              <div className="txt">{e.data.tool}</div>
            </div>
          );
        if (e.type === "file_write")
          return (
            <div key={e.seq} className="ev supervisor">
              <div className="who supervisor">wrote {e.data.path}</div>
              <details>
                <summary className="small muted">show</summary>
                <div className="txt small">{e.data.content}</div>
              </details>
            </div>
          );
        return (
          <div key={e.seq} className={`ev ${e.agent}`}>
            <div className={`who ${e.agent}`}>{e.agent}</div>
            <div className="txt">{e.data.text}</div>
          </div>
        );
      })}
    </div>
  );
}

function fmtArgs(a: any) {
  if (!a) return "";
  return Object.entries(a)
    .filter(([k]) => k !== "job_id")
    .map(
      ([k, v]) =>
        `${k}=${Array.isArray(v) ? `[${v.join(",")}]` : typeof v === "string" && v.length > 40 ? v.slice(0, 40) + "…" : v}`,
    )
    .join(" ");
}

const COLORS = [
  "#0f7b6c",
  "#2c5ccf",
  "#c2362b",
  "#a86400",
  "#7b3fbf",
  "#3a8f3a",
];

function ExperimentChart({ rows, target }: { rows: any[]; target: number }) {
  if (!rows.length) return <div className="empty">No experiments yet.</div>;
  const groups: Record<string, any[]> = {};
  rows.forEach((r) => {
    const k = `${r.settings.coverage} reads · ${r.decoder === "polish" ? "CNN" : "baseline"}`;
    (groups[k] ||= []).push({
      x: r.settings.redundancy,
      y: Math.round(r.recovery_rate * 100),
      n: r.n_trials,
      cost: r.write_usd,
      acc: r.strand_accuracy,
    });
  });
  const best = rows
    .filter((r) => r.recovery_rate >= target)
    .sort((a, b) => a.write_usd - b.write_usd)[0];
  return (
    <>
      <ResponsiveContainer width="100%" height={260}>
        <ScatterChart margin={{ top: 10, right: 16, bottom: 18, left: -10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
          <XAxis
            type="number"
            dataKey="x"
            name="redundancy"
            domain={[0, "auto"]}
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            label={{
              value: "redundancy (extra strands)",
              position: "insideBottom",
              offset: -4,
              fill: "var(--muted)",
              fontSize: 12,
            }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name="recovered"
            unit="%"
            domain={[0, 100]}
            tick={{ fill: "var(--muted)", fontSize: 12 }}
          />
          <ZAxis type="number" dataKey="n" range={[60, 160]} name="trials" />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            contentStyle={{
              background: "var(--panel)",
              border: "1px solid var(--line)",
              borderRadius: 8,
            }}
            formatter={(v: any, n: any) => [v, n]}
          />
          <Legend
            verticalAlign="top"
            wrapperStyle={{ fontSize: 12, paddingBottom: 6 }}
          />
          {Object.entries(groups).map(([k, d], i) => (
            <Scatter
              key={k}
              name={k}
              data={d}
              fill={COLORS[i % COLORS.length]}
              isAnimationActive={false}
            />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
      <div className="small muted">
        {rows.length} experiment points · each point = file recovered exactly in
        N independent simulated sequencing runs.
        {best && (
          <>
            {" "}
            Cheapest point meeting target:{" "}
            <b style={{ color: "var(--text)" }}>
              redundancy {best.settings.redundancy}, {best.settings.coverage}{" "}
              reads
            </b>{" "}
            ({best.n_recovered}/{best.n_trials}, {best.bits_per_base}{" "}
            bits/base).
          </>
        )}
      </div>
    </>
  );
}

function StressTable({ rows, final }: { rows: any[]; final?: { redundancy?: number } }) {
  if (!rows.length)
    return <div className="empty">The adversary has not attacked yet.</div>;
  const mine = final?.redundancy != null ? rows.filter((r) => r.settings.redundancy === final.redundancy) : [];
  if (mine.length && mine.length < rows.length)
    return (
      <>
        <p className="muted small">Final design (redundancy {final!.redundancy})</p>
        <StressRows rows={mine} />
        <details>
          <summary>Show all {rows.length} experiments, including earlier designs</summary>
          <StressRows rows={rows} />
        </details>
      </>
    );
  return <StressRows rows={rows} />;
}

function StressRows({ rows }: { rows: any[] }) {
  const label: Record<string, string> = {
    vault_loss: "Lose 1 vault site",
    simulator_b: "Different sequencer (Sim B)",
    decay_x2: "Twice the storage time",
    low_coverage: "60% of planned reads",
  };
  return (
    <table>
      <thead>
        <tr>
          <th>Attack</th>
          <th>Design</th>
          <th>Recovered</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td>{label[r.scenario] ?? r.scenario}</td>
            <td className="mono">
              r={r.settings.redundancy} · {r.settings.coverage}x
            </td>
            <td>
              {r.n_recovered}/{r.n_trials}
            </td>
            <td>
              <span className={`pill ${r.passed ? "ok" : "bad"}`}>
                {r.passed ? "survived" : "broke"}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function BrandMark() {
  // Two strands crossing twice, with rungs in the four base colors.
  return (
    <svg className="brand-mark" viewBox="0 0 28 28" width="28" height="28" aria-hidden="true">
      <path d="M8 2c0 6 12 6 12 12S8 20 8 26" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M20 2c0 6-12 6-12 12s12 6 12 12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" opacity=".55" />
      <rect x="10" y="6.2" width="8" height="2" rx="1" fill="var(--A)" />
      <rect x="10" y="19.8" width="8" height="2" rx="1" fill="var(--C)" />
      <rect x="11.5" y="10.4" width="5" height="1.8" rx=".9" fill="var(--G)" />
      <rect x="11.5" y="15.8" width="5" height="1.8" rx=".9" fill="var(--T)" />
    </svg>
  );
}

/** A real encoded strand from the newest archive that has one; otherwise an unlabeled backbone. */
function HeroHelix({ jobs }: { jobs: ArchiveSummary[] | null }) {
  const [strand, setStrand] = useState<{ seq: string; name: string } | null>(null);
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!jobs) return;
    let active = true;
    (async () => {
      for (const j of jobs.slice(0, 4)) {
        try {
          const full: Archive = await api(`/jobs/${j.id}`);
          const seq = full.dna_summary?.example;
          if (seq && /^[ACGT]+$/.test(seq)) {
            if (active) setStrand({ seq: seq.slice(0, 44), name: j.name || j.company });
            break;
          }
        } catch {
          /* try the next archive */
        }
      }
      if (active) setDone(true);
    })();
    return () => {
      active = false;
    };
  }, [jobs?.map((j) => j.id).join(",")]);
  return (
    <figure className="hero-figure">
      <Helix3D
        ambient
        sequence={strand?.seq ?? null}
        placeholderLength={44}
        label={strand ? `Rotating 3D model of an encoded strand from ${strand.name}` : "Rotating DNA backbone"}
      />
      <figcaption>
        {strand ? (
          <>
            <span className="mono">{strand.seq.slice(0, 24)}…</span>
            First 44 bases of a strand from <b>{strand.name}</b>
          </>
        ) : done ? (
          "Backbone only. Archive a file to see its real bases here."
        ) : (
          " "
        )}
      </figcaption>
    </figure>
  );
}
