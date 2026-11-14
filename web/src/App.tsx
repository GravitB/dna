import StorageScale from "./StorageScale";
import { LearnedArchive } from "./LearnedArchive";
import DnaExplorer from "./DnaExplorer";
import { useEffect, useRef, useState, type ReactNode } from "react";
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
import {
  CountUp,
  DnaField,
  DnaScanner,
  IconAlert,
  IconArrow,
  IconBack,
  IconCheck,
  IconClock,
  IconCloud,
  IconCoins,
  IconHelix,
  IconLaptop,
  IconShield,
  IconUpload,
  IconUser,
  IconVault,
  PHASES,
  PhaseTrack,
  StatusPill,
  phaseIndex,
  toneOf,
  useParallax,
  useReveal,
  useScrollProgress,
} from "./ui";
const shortDate = (v?: string | null) =>
  v
    ? new Date(v).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : "Not yet";
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
const fileSize = (bytes: number) => bytes < 1000 ? `${bytes} ${bytes === 1 ? "byte" : "bytes"}` : `${(bytes / 1000).toFixed(1)} KB`;
const testLabel = (key: string, fallback: string) => ({normal: "Normal reading", simulator_b: "Different DNA reader", low_coverage: "Fewer reads", decay_x2: "Twice the storage period", vault_loss: "Loss of one location"}[key] || fallback);
function OptionalDetails({ title, explanation, children }: { title: string; explanation: string; children: ReactNode }) {
  return <details className="optional-details"><summary>{title}<span>Optional · expand to explore</span></summary><div className="optional-details-body"><p className="optional-explanation">{explanation}</p>{children}</div></details>;
}
function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  return error ? (
    <div className="error" role="alert">
      {error} {retry && <button onClick={retry}>Try again</button>}
    </div>
  ) : null;
}
export default function App() {
  useReveal();
  useScrollProgress();
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
      <header>
        <a className="brand" href="#/">
          <img src={`${import.meta.env.BASE_URL}mark.svg`} alt="" width="28" height="28" />
          Lazarus<span>Business workspace</span>
        </a>
        <nav aria-label="Main navigation">
          <a href="/">Home</a>
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
        <span className="simulation">Simulation workspace</span>
        <div className="hdr-bar" aria-hidden="true">
          <i />
        </div>
      </header>
      <div className="notice">
        Test DNA archive designs and recovery. No physical DNA is produced or
        purchased.
      </div>
      <main>
        <ErrorBox error={connection} retry={connect} />
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
      </main>
      <footer>
        <div className="footer-brand">
          <img src={`${import.meta.env.BASE_URL}mark.svg`} alt="" width="22" height="22" />
          Lazarus · DNA archive simulation
        </div>
        <span>Retention is a test input, not a legal recommendation.</span>
      </footer>
    </>
  );
}
type Filter = "all" | "ok" | "action" | "active";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "ok", label: "Verified" },
  { key: "action", label: "Needs you" },
  { key: "active", label: "In progress" },
];
const inFilter = (j: ArchiveSummary, f: Filter) => {
  const t = toneOf(j.presentation);
  return f === "all"
    ? true
    : f === "ok"
      ? t === "ok"
      : f === "action"
        ? t === "warn" || t === "bad"
        : t === "busy" || t === "info";
};
function Archives() {
  const [jobs, setJobs] = useState<ArchiveSummary[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [deleted, setDeleted] = useState<ArchiveSummary | null>(null);
  const removeArchive = async (job: ArchiveSummary) => {
    if (!window.confirm(`Delete “${job.name}” from your archives? Its files will be retained for recovery. You can undo this action.`)) return;
    setDeleting(job.id);
    try {
      await api(`/jobs/${encodeURIComponent(job.id)}`, { method: "DELETE" });
      setJobs(current => current?.filter(j => j.id !== job.id) ?? null);
      setDeleted(job);
      setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not delete archive. Try again."); }
    finally { setDeleting(null); }
  };
  const undoDelete = async () => {
    if (!deleted) return;
    try {
      await post(`/jobs/${encodeURIComponent(deleted.id)}/restore`);
      setDeleted(null);
      load();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not restore archive. Try again."); }
  };

  const hero = useParallax<HTMLDivElement>();
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
  const all = jobs || [];
  const verified = all.filter((j) => toneOf(j.presentation) === "ok").length;
  const waiting = all.filter((j) => j.presentation.pending_action).length;
  const records = all.reduce((n, j) => n + (j.file_count || 0), 0);
  const shown = all.filter((j) => inFilter(j, filter));
  return (
    <>
      <div className="hero" ref={hero}>
        <DnaField />
        <div className="hero-copy">
          <p className="idx">01 · Business workspace</p>
          <h1 className="display">Keep important records recoverable.</h1>
          <p className="lead">
            Turn a file into a tested DNA archive. Restore it and see proof that every byte came back.
          </p>
          <div className="actions">
            <a className="button primary" href="#/new">
              Archive my files <IconArrow />
            </a>
            <a className="button ghost" href="#/new?sample">
              Try a picture demo
            </a>
          </div>
        </div>
        <div className="hero-card" aria-label="Workspace summary">
          <p className="cap-label">Recovery verified</p>
          <p className="big-num num-gain">
            {jobs ? <CountUp value={verified} /> : "–"}
            <span className="of">/{jobs ? all.length : "–"}</span>
          </p>
          <p className="muted">archives restored byte for byte from simulated DNA</p>
          <div className="meter" aria-hidden="true">
            <i style={{ width: `${all.length ? (verified / all.length) * 100 : 0}%` }} />
          </div>
          <dl className="mini-stats">
            <div>
              <dt>Records in DNA</dt>
              <dd>{jobs ? <CountUp value={records} /> : "–"}</dd>
            </div>
            <div>
              <dt>Awaiting your decision</dt>
              <dd className={waiting ? "num-warn" : ""}>{jobs ? <CountUp value={waiting} /> : "–"}</dd>
            </div>
          </dl>
        </div>
      </div>
      <Journey />
      <ErrorBox error={error} retry={load} />
      {!jobs ? (
        <div className="archive-cards" role="status" aria-label="Loading archives">
          {[0, 1, 2].map((i) => (
            <div className="archive-card skeleton" key={i} />
          ))}
        </div>
      ) : !jobs.length ? (
        <section className="empty-state">
          <div className="empty-icon">
            <IconHelix size={34} />
          </div>
          <h2>Your first archive starts with your records.</h2>
          <p>
            Archive your files to test whether your records can be recovered.
          </p>
          <a className="button primary" href="#/new">
            Archive my files <IconArrow />
          </a>
          <p className="muted">
            Or explore with fictional Northstar Bio records using “Try sample
            archive.”
          </p>
        </section>
      ) : (
        <section className="archives-section">
          <div className="list-head">
            <div>
              <p className="idx">02 · Archives</p>
              <h2>Your archives</h2>
            </div>
            <div className="segmented" role="group" aria-label="Filter archives">
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  aria-pressed={filter === f.key}
                  onClick={() => setFilter(f.key)}
                >
                  {f.label}
                  <span>{all.filter((j) => inFilter(j, f.key)).length}</span>
                </button>
              ))}
            </div>
          </div>
          {!shown.length && <p className="muted empty-filter">No archives in this view.</p>}
          {deleted && <div className="info" role="status">“{deleted.name}” deleted from the list. Files retained. <button onClick={undoDelete}>Undo delete</button></div>}
          <div className="archive-cards">
            {shown.map((j) => (
              <div className="archive-card-wrap" key={j.id}>
              <a className={`archive-card tone-${toneOf(j.presentation)}`} href={`#/job/${j.id}`}>
                <div className="card-top">
                  <StatusPill p={j.presentation} />
                  <time dateTime={j.created}>{shortDate(j.created)}</time>
                </div>
                <h3>{j.name}</h3>
                <p className="card-company">{j.company}</p>
                <PhaseTrack p={j.presentation} />
                <dl className="card-facts">
                  <div>
                    <dt>Records</dt>
                    <dd>{j.file_count ?? "–"}</dd>
                  </div>
                  <div>
                    <dt>Simulated aging</dt>
                    <dd>{j.retention_years} yr</dd>
                  </div>
                  <div>
                    <dt>Latest test</dt>
                    <dd>{shortDate(j.presentation.latest_test)}</dd>
                  </div>
                </dl>
                <span className="card-cta">
                  {j.presentation.pending_action
                    ? "Review your decision"
                    : j.presentation.verified
                      ? "Open recovered files"
                      : "View progress and next step"}
                  <IconArrow />
                </span>
              </a>
              <button className="archive-delete" aria-label={`Delete archive ${j.name}`} disabled={deleting === j.id} onClick={() => removeArchive(j)}>{deleting === j.id ? "Deleting…" : "Delete archive"}</button>
              </div>
            ))}
            <a className="archive-card new-card" href="#/new">
              <span className="new-plus" aria-hidden="true">+</span>
              <strong>Start a new archive</strong>
              <small>Upload records and set your requirements</small>
            </a>
          </div>
        </section>
      )}
      <OptionalDetails title="Compare storage sizes" explanation="An illustration of how much physical space the same data could occupy as paper, drive capacity, or DNA material. These are estimates, not measured savings."><StorageScale /></OptionalDetails>
      <section className="explanation">
        <div>
          <p className="idx">03 · How it works</p>
          <h2>From retention requirements to recovery evidence</h2>
          <p>
            Select records that must last. Lazarus tests a DNA archive design,
            asks you to review it, then checks whether each file can be restored
            unchanged.
          </p>
          <p>
            You stay in control of the selected records and both approval
            decisions. Costs and storage conditions are modeled.
          </p>
        </div>
        <ul className="assurances">
          <li>
            <span><IconUser /></span>
            <div><strong>You choose the records</strong><small>Only files you select are encrypted and encoded.</small></div>
          </li>
          <li>
            <span><IconShield /></span>
            <div><strong>Two decisions stay with you</strong><small>Approve the archive, then approve the recovery test.</small></div>
          </li>
          <li>
            <span><IconCoins /></span>
            <div><strong>Modeled, never purchased</strong><small>No physical DNA is ordered from this workspace.</small></div>
          </li>
        </ul>
      </section>
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
  const [dragging, setDragging] = useState(false);
  const firstStep = useRef(true);
  useEffect(() => {
    if (firstStep.current) {
      firstStep.current = false;
      return;
    }
    if (window.scrollY > 200 && !/jsdom/i.test(navigator.userAgent))
      window.scrollTo({ top: 0, behavior: "smooth" });
  }, [step]);
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
        <IconBack /> Back to archives
      </a>
      <div className="page-heading">
        <div>
          <p className="idx">{sample ? "Picture demo" : "New archive"}</p>
          <h1>{sample ? "Try a picture demo" : "Archive your files"}</h1>
          <p>
            Choose your records and requirements. We’ll test the archive design
            before you approve it.
          </p>
        </div>
      </div>
      <ol className="workflow wizard-steps" aria-label="Archive setup steps">
        {[
          ["Records", "What must last"],
          ["Requirements", "How long, what budget"],
          ["Review", "Check and start"],
        ].map(([n, hint], i) => {
          const body = (
            <>
              <b>{n}</b>
              <small>{hint}</small>
            </>
          );
          return (
            <li
              key={n}
              aria-current={i === step ? "step" : undefined}
              className={i < step ? "complete" : ""}
            >
              {i < step && !busy ? (
                <button
                  type="button"
                  className="step-link"
                  aria-label={`Go back to ${n}`}
                  onClick={() => {
                    setStep(i);
                    setError("");
                  }}
                >
                  {body}
                </button>
              ) : (
                body
              )}
            </li>
          );
        })}
      </ol>
      <div className="setup-layout">
        <section className="form-panel">
          <ErrorBox
            error={error}
            retry={sample && !samples.length ? loadSamples : undefined}
          />
          <p className="panel-step">Step {step + 1} of 3</p>
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
                <label
                  className={`upload${dragging ? " dragging" : ""}${files.length ? " has-files" : ""}`}
                  onDragEnter={() => setDragging(true)}
                  onDragLeave={() => setDragging(false)}
                  onDrop={() => setDragging(false)}
                >
                  <span className="upload-icon" aria-hidden="true">
                    <IconUpload />
                  </span>
                  <span className="upload-title">Choose records</span>
                  <span className="upload-hint" aria-hidden="true">
                    {files.length
                      ? `${files.length} file${files.length === 1 ? "" : "s"} ready · drop or click to replace`
                      : "Drop files here, or click to browse"}
                  </span>
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
                    <label
                      className={`record${excluded.includes(f.name) ? " off" : ""}`}
                      key={f.name}
                    >
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
                          {fileSize(f.bytes)}
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
          {step === 0 && selected.length > 0 && <OptionalDetails title="How small could these files be?" explanation="Explore estimated storage volumes for your selected files. This comparison does not change your archive settings."><StorageScale files={selected} /></OptionalDetails>}
          {step === 1 && (
            <>
              <h2>What must this archive support?</h2>
              {!sample && <fieldset><legend>How should we design the archive?</legend><p>Encoding means turning your file into DNA letters. Standard rules use fixed checks; learned models try to predict which sequences will be easier to recover.</p>
                <label>Design method<select value={encodingMode} onChange={e => setEncodingMode(e.target.value)}>
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
                  Simulated writing budget (USD)
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
                <summary>Advanced settings · reader and recovery controls</summary><p>These settings control how we simulate reading DNA and how much extra recovery data we add. You can keep the defaults.</p>
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
              <dl className="facts stat-tiles">
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
              <ul className="chip-list">
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
              {!busy && <IconArrow />}
            </button>
          </div>
        </section>
        <aside className="aside-card">
          <h2>You define the requirements.</h2>
          <p>
            Lazarus tests how to encode and recover your records. You don’t need
            to choose a DNA encoding design.
          </p>
          <ul className="assurances compact">
            <li>
              <span><IconHelix /></span>
              <div>
                <h3>What you’ll get</h3>
                <p>
                  A proposed archive, an estimated cost, and measured recovery results
                  for each selected file.
                </p>
              </div>
            </li>
            <li>
              <span><IconShield /></span>
              <div>
                <h3>Two decisions stay with you</h3>
                <p>
                  Approve the simulated archive, then approve a recovery test that
                  removes this job’s working copies.
                </p>
              </div>
            </li>
          </ul>
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
        <div className="loading-card" role="status">
          <DnaScanner />
          <p>Loading archive…</p>
        </div>
        <a className="back" href="#/">
          <IconBack /> Back to archives
        </a>
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
  const stage = phaseIndex(p.phase);
  const finishedOk = p.phase === "results" && toneOf(p) === "ok";
  const restoredCount = latest
    ? latest.files.filter((f) => f.sha256_match).length
    : 0;
  const expectedCount = expected.length || latest?.files.length || 0;
  return (
    <>
      <a className="back" href="#/">
        <IconBack /> Back to archives
      </a>
      <div className="page-heading">
        <div>
          <p className="idx">Archive · {job.company}</p>
          <h1>{job.name || job.company}</h1>
          <p>
            {job.company} · Created {date(job.created)}
          </p>
        </div>
        <StatusPill p={p} large />
      </div>
      <ol className={`workflow tone-${toneOf(p)}`} aria-label="Archive progress">
        {PHASES.map((ph, i) => (
          <li
            key={ph.label}
            aria-current={stage === i && !finishedOk ? "step" : undefined}
            className={i < stage || finishedOk ? "complete" : ""}
          >
            <b>{ph.label}</b>
            <small>{ph.hint}</small>
          </li>
        ))}
      </ol>
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
      <div className="archive-layout">
        <div>
          {(p.phase === "analysis" || job.status === "recovering") && (
            <section className="analysis-status" role="status">
              <span className="activity-dot" />
              <div>
                <DnaScanner />
                <h2>
                  {job.status === "recovering"
                    ? "Restoring records and checking file integrity"
                    : "Testing a design for your records"}
                </h2>
                <p>{activity(evs)}</p><ProgressInfo job={job} events={evs} />
                <small>
                  Results will appear as tests complete. No decision is needed
                  yet.
                </small>
              </div>
            </section>
          )}
          {pending && (
            <Approval
              key={`${pending.tool}:${evs.filter((e) => e.type === "interrupt").length}`}
              p={pending}
              busy={busy}
              decide={(d) => action("/approve", { decision: d })}
              correct={() => action("/approve", {decision: "edit", args: pending.summary.correction})}
            />
          )}
          <LearnedArchive job={job} busy={busy} action={action} />
          <DnaStory job={job} id={id} />
          <section>
            <div className="section-heading">
              <h2>Your files</h2>
              <span>{expected.length || "Not recorded"} records</span>
            </div>
            <p>
              Each included file must be restored unchanged for the archive to
              pass recovery.
            </p>
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
                      <td><div className="file-cell">{f.included && job.originals_available && <FilePreview name={f.name} src={`/api/jobs/${id}/preview/${encodeURIComponent(f.name)}`} />}<span>{f.name}</span></div></td>
                      <td>{fileSize(f.bytes)}</td>
                      <td>{f.included ? "Yes" : "Excluded by user"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <OptionalDetails title="Compare this archive’s storage size" explanation="Compare estimated physical volumes for the same file data. Packaging and laboratory overhead are excluded."><StorageScale job={job} /></OptionalDetails>
          <OptionalDetails title="Explore the DNA letters" explanation="Your file is encoded as sequences of A, C, G and T. This viewer shows those sequences as an illustrative 3D strand; no physical DNA is produced."><DnaExplorer job={job} /></OptionalDetails>
          {p.needs_retest && (
            <div className="info">
              Available locations have changed since the latest recovery test.
              Run another test to check the current archive.
            </div>
          )}
          {latest && (
            <section className="results">
              <div className="section-heading">
                <h2>Recovery evidence</h2>
                {job.certificate && job.status !== "recovering" && (
                  <div className="actions">
                    <a
                      className="button"
                      target="_blank"
                      rel="noreferrer"
                      href={`/api/jobs/${id}/files/${job.certificate}`}
                    >
                      View recovery report
                    </a>
                    <a
                      className="button"
                      download="recovery-report.html"
                      href={`/api/jobs/${id}/files/${job.certificate}`}
                    >
                      Download report
                    </a>
                  </div>
                )}
              </div>
              <div className={`verdict-banner ${latest.all_verified ? "ok" : "bad"}`}>
                <span className="verdict-icon" aria-hidden="true">
                  {latest.all_verified ? <IconCheck size={30} /> : <IconAlert size={28} />}
                </span>
                <div className="verdict-copy">
                  <h3
                    className={
                      latest.all_verified ? "success-text" : "failure-text"
                    }
                  >
                    {latest.all_verified
                      ? "All selected files restored unchanged"
                      : latest.files.some((f) => f.sha256_match)
                        ? "Some files could not be restored"
                        : "Recovery test failed"}
                  </h3>
                  <p>
                    Tested {date(latest.tested_at)} ·{" "}
                    {restoredCount} of{" "}
                    {expectedCount} records restored ·{" "}
                    {latest.vaults_available.length} of {latest.n_vaults} locations
                    available
                  </p>
                </div>
                <dl className="verdict-nums">
                  <div>
                    <dt>Records restored</dt>
                    <dd>
                      <CountUp value={restoredCount} />
                      <span className="of">/{expectedCount}</span>
                    </dd>
                  </div>
                  <div>
                    <dt>Locations read</dt>
                    <dd>
                      {latest.vaults_available.length}
                      <span className="of">/{latest.n_vaults}</span>
                    </dd>
                  </div>
                </dl>
              </div>
              {latest.error && (
                <div className="error">
                  {latest.error}. Review available locations or create a revised
                  archive.
                </div>
              )}
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Record</th>
                      <th>Recovery outcome</th>
                      <th>Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {expected.map((n) => {
                      const f = latest.files.find((f) => f.name === n);
                      return (
                        <tr key={n}>
                          <td>{n}</td>
                          <td>
                            <span className={`pill ${f?.sha256_match ? "ok" : "bad"}`}>
                              {f?.sha256_match
                                ? "Restored unchanged"
                                : f?.error || "Not restored"}
                            </span>
                          </td>
                          <td>
                            {f?.sha256_match ? (
                              <a
                                href={`/api/jobs/${id}/files/restored/${encodeURIComponent(n)}`}
                                target="_blank"
                                rel="noreferrer"
                              >
                                Open restored file
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
              {!latest.all_verified && <p className="info">The available locations did not restore every file. Try another recovery test below, or create a revised archive from your original files with more recovery data. Previously removed locations cannot be restored here.</p>}
              <div className="restored-gallery">{latest.files.filter(f => f.sha256_match).map(f => <article key={f.name}>
                <FilePreview large name={f.name} src={`/api/jobs/${id}/preview/${encodeURIComponent(f.name)}?stage=restored&attempt=${job.drills.length}`} />
                <h3>{f.name}</h3><span className="badge success">Restored unchanged · SHA-256 match</span>
                <p>{fileSize(files.find(x => x.name === f.name)?.bytes || 0)} · Exact file integrity verified</p>
                <a className="button primary" download={f.name} href={`/api/jobs/${id}/files/restored/${encodeURIComponent(f.name)}`}>Download restored file</a>
              </article>)}</div>
              <p className="muted">
                File integrity is checked against the original SHA-256
                fingerprint. Simulation evidence is not regulatory
                certification.
              </p>
            </section>
          )}
          {job.order && <OptionalDetails title="Try extra damage tests" explanation="An optional experiment: damage copies of the encoded sequences and see whether the file can still be recovered."><DnaExperiment id={id} job={job} /></OptionalDetails>}
          {job.order && !job.pending && (
            <section>
              <h2>Recovery scenarios</h2>
              <p>
                Test the archive again, or simulate losing a storage location.
                This affects only this simulated archive.
              </p>
              <div className="locations">
                {job.vaults.map((v) => (
                  <div
                    key={v.vault_id}
                    className={v.status === "destroyed" ? "down" : "up"}
                  >
                    <div className="loc-head">
                      <span className="loc-icon" aria-hidden="true">
                        <IconVault />
                      </span>
                      <strong>Location {v.vault_id}</strong>
                    </div>
                    <span className="loc-state">
                      {v.status === "destroyed" ? "Unavailable" : "Available"}
                    </span>
                    <button
                      disabled={
                        busy ||
                        !job.finished ||
                        v.status === "destroyed" ||
                        job.status === "recovering"
                      }
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
                  <p>
                    This removes its simulated DNA order files. Recovery will
                    use the remaining locations.
                  </p>
                  <div className="actions">
                    <button disabled={busy} onClick={() => setLoss(null)}>
                      Cancel
                    </button>
                    <button
                      className="danger"
                      disabled={busy}
                      onClick={() => action(`/vaults/${loss}/destroy`)}
                    >
                      Confirm simulated loss
                    </button>
                  </div>
                </div>
              )}
              <button
                disabled={busy || !job.finished || job.status === "recovering"}
                onClick={() => action("/drill", { attempt: job.drills.length })}
              >
                {busy || job.status === "recovering"
                  ? "Recovery operation in progress…"
                  : "Run another recovery test"}
              </button>
            </section>
          )}
          {["attention"].includes(p.phase) && (
            <section>
              <h2>Your next step</h2>
              <p>
                Start a revised archive with these requirements. If storage
                locations exist, you can also run another recovery test.
              </p>
              <button onClick={revise}>Create revised archive</button>
            </section>
          )}
          <details className="technical">
            <summary>Technical details · tests and AI activity</summary><p>Detailed measurements and the AI agent’s tool activity. You do not need these logs to approve or restore your archive.</p>
            <h3>Analysis method</h3>
            <p>
              {job.mode === "agent"
                ? "AI-guided analysis"
                : "Scripted analysis"}
            </p>
            <h3>Codec experiments</h3>
            <ExperimentChart
              rows={job.experiments}
              target={job.policy.target}
            />
            <h3>All resilience experiments (includes earlier designs)</h3>
            <StressTable rows={job.stress} />
            <h3>Agent activity</h3>
            <Timeline evs={evs} />

            {latest && (
              <>
                <h3>Hashes and decoder evidence</h3>
                <pre>{JSON.stringify(latest, null, 2)}</pre>
              </>
            )}
            {job.order && (
              <>
                <h3>Synthesis files</h3>
                {job.order.order_files.filter(f => !job.vaults?.some(v => v.status === "destroyed" && f.startsWith(`vaults/vault-${v.vault_id}/`))).map((f) => (
                  <p key={f}>
                    <a
                      target="_blank"
                      rel="noreferrer"
                      href={`/api/jobs/${id}/files/${f}`}
                    >
                      {f}
                    </a>
                  </p>
                ))}
              </>
            )}
          </details>
        </div>
        <aside className="aside-card">
          <h2>Archive requirements</h2>
          <div className="storage-chip" role="status">
            {job.storage?.backend === "supabase" ? <IconCloud size={18} /> : <IconLaptop size={18} />}
            {job.storage?.backend === "supabase"
              ? job.storage.state === "saved"
                ? "Saved to Supabase"
                : job.storage.state === "failed"
                  ? "Cloud save failed. Working copies were retained. Check the connection and create a revised archive to retry."
                  : job.storage.state === "uploading"
                    ? "Saving DNA files to Supabase…"
                    : "Cloud archive not saved yet"
              : "Stored on this computer"}
          </div>
          <dl className="facts aside-facts">
            <div>
              <dt><IconClock size={15} /> Retention period</dt>
              <dd>{job.policy.retention_years} years</dd>
            </div>
            <div>
              <dt><IconCoins size={15} /> Estimated budget</dt>
              <dd>{money(job.policy.budget_usd)}</dd>
            </div>
            <div>
              <dt><IconHelix size={15} /> Modeled writing cost</dt>
              <dd>
                {money(job.order?.cost.write_usd || pending?.summary.write_usd)}
              </dd>
            </div>
            <div>
              <dt><IconVault size={15} /> Storage locations</dt>
              <dd>{job.order?.settings.n_vaults || job.policy.n_vaults}</dd>
            </div>
          </dl>
          {job.policy.notes && <p>{job.policy.notes}</p>}
          <hr />
          <p>
            Costs and storage conditions are modeled. Passing these trials does
            not guarantee future recovery.
          </p>
          <button onClick={revise}>Create revised archive</button>
        </aside>
      </div>
    </>
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
      <span className="badge decision-badge">
        <i aria-hidden="true" /> Your decision
      </span>
      <h2>
        {order ? "Review the proposed archive" : "Run the recovery test?"}
      </h2>
      {order ? (
        <>
          <p>
            Review the estimated cost and measured resilience before preparing
            this simulated archive.
          </p>
          <dl className="facts stat-tiles">
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
          <div className="table-wrap">
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
                  <td>{testLabel(e.scenario, e.label)}</td>
                  <td>
                    {e.trials == null
                      ? "Not tested"
                      : `${e.recovered} / ${e.trials}`}
                  </td>
                  <td>
                    <span
                      className={`pill ${e.state === "passed" ? "ok" : e.state === "failed" ? "bad" : "na"}`}
                    >
                      {e.state === "passed"
                        ? "Passed"
                        : e.state === "failed"
                          ? "Failed"
                          : "Not tested for this design"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
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
          {!busy && <IconCheck size={18} />}
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

function StressTable({ rows }: { rows: any[] }) {
  if (!rows.length)
    return <div className="empty">The adversary has not attacked yet.</div>;
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
