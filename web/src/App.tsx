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
import { api, date, post } from "./api";
import { DecoderPage, DnaExperiment } from "./Dna";
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
      <header>
        <a className="brand" href="#/">
          Lazarus<span>Records that endure</span>
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
        <span className="simulation">Simulation workspace</span>
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
        Lazarus · DNA archive simulation{" "}
        <span>Retention is a test input, not a legal recommendation.</span>
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
      <div className="page-heading">
        <div>
          <h1>Your archives</h1>
          <p>
            Know what you’re retaining, what needs a decision, and what you can
            recover.
          </p>
        </div>
        <div className="actions">
          <a className="button" href="#/new?sample">
            Try sample archive
          </a>
          <a className="button primary" href="#/new">
            Create archive
          </a>
        </div>
      </div>
      <ErrorBox error={error} retry={load} />
      {!jobs ? (
        <p role="status">Loading archives…</p>
      ) : !jobs.length ? (
        <section className="empty-state">
          <h2>Your first archive starts with your records.</h2>
          <p>
            Create an archive to test whether your records can be recovered.
          </p>
          <a className="button primary" href="#/new">
            Create archive
          </a>
          <p>
            Or explore with fictional Northstar Bio records using “Try sample
            archive.”
          </p>
        </section>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Archive / organization</th>
                <th>Records</th>
                <th>Retention</th>
                <th>Latest recovery test</th>
                <th>Outcome / next action</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td>
                    <a className="archive-link" href={`#/job/${j.id}`}>
                      {j.name}
                    </a>
                    <small>{j.company}</small>
                  </td>
                  <td>{j.file_count ?? "Not recorded"}</td>
                  <td>{j.retention_years} years</td>
                  <td>{date(j.presentation.latest_test)}</td>
                  <td>
                    <span
                      className={`badge ${j.presentation.verified && !j.presentation.needs_retest ? "success" : ""}`}
                    >
                      {j.presentation.label}
                    </span>
                    {j.presentation.pending_action && (
                      <small>Waiting for your decision</small>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <section className="explanation">
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
  const [policy, setPolicy] = useState<Policy>(revised?.policy || defaults);
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
    api("/samples")
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
    if (step === 0 && (!name.trim() || !company.trim() || !selected.length))
      return setError(
        "Enter an archive name and organization, and select at least one record.",
      );
    if (total > 200000)
      return setError(
        "The demo accepts up to 200 KB total. Choose fewer or smaller files.",
      );
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
    fd.append("name", name);
    fd.append("company", company);
    fd.append("policy", JSON.stringify(policy));
    fd.append("mode", mode);
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
          <h1>{sample ? "Try a sample archive" : "Create an archive"}</h1>
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
                Archive name
                <input
                  value={name}
                  placeholder="e.g. Clinical trial records, 2026"
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <label>
                Organization
                <input
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                />
              </label>
              {sample ? (
                <div className="info">
                  Fictional Northstar Bio sample records. No company data is
                  needed.
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
              {!!records.length && (
                <div className="record-list">
                  {records.map((f) => (
                    <label className="record" key={f.name}>
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
          {step === 1 && (
            <>
              <h2>What must this archive support?</h2>
              <div className="two">
                <label>
                  Retention period (years)
                  <input
                    type="number"
                    min="0"
                    max="1000"
                    value={policy.retention_years}
                    onChange={(e) => set("retention_years", +e.target.value)}
                  />
                  <small>
                    The storage duration to simulate. Choose it using your
                    organization’s retention policy.
                  </small>
                </label>
                <label>
                  Estimated write budget (USD)
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={policy.budget_usd}
                    onChange={(e) => set("budget_usd", +e.target.value)}
                  />
                  <small>
                    A limit for the modeled archive design. No payment is taken.
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
              <details>
                <summary>Advanced settings</summary>
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
  return (
    <>
      <a className="back" href="#/">
        Back to archives
      </a>
      <div className="page-heading">
        <div>
          <h1>{job.name || job.company}</h1>
          <p>
            {job.company} · Created {date(job.created)}
          </p>
        </div>
        <span
          className={`badge ${p.verified && !p.needs_retest ? "success" : ""}`}
        >
          {p.label}
        </span>
      </div>
      <ol className="workflow">
        {phase.map((label, i) => (
          <li
            key={label}
            aria-current={stage === i ? "step" : undefined}
            className={i < stage ? "complete" : ""}
          >
            {label}
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
                <h2>
                  {job.status === "recovering"
                    ? "Restoring records and checking file integrity"
                    : "Testing a design for your records"}
                </h2>
                <p>{activity(evs)}</p>
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
            />
          )}
          <section>
            <div className="section-heading">
              <h2>Selected records</h2>
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
                      <td>{f.name}</td>
                      <td>{(f.bytes / 1000).toFixed(1)} KB</td>
                      <td>{f.included ? "Yes" : "Excluded by user"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
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
                {latest.files.filter((f) => f.sha256_match).length} of{" "}
                {expected.length || latest.files.length} records restored ·{" "}
                {latest.vaults_available.length} of {latest.n_vaults} locations
                available
              </p>
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
                            {f?.sha256_match
                              ? "Restored unchanged"
                              : f?.error || "Not restored"}
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
              <p className="muted">
                File integrity is checked against the original SHA-256
                fingerprint. Simulation evidence is not regulatory
                certification.
              </p>
            </section>
          )}
          {job.order && <DnaExperiment id={id} job={job} />}
          {job.order && !job.pending && (
            <section>
              <h2>Recovery scenarios</h2>
              <p>
                Test the archive again, or simulate losing a storage location.
                This affects only this simulated archive.
              </p>
              <div className="locations">
                {job.vaults.map((v) => (
                  <div key={v.vault_id}>
                    <strong>Location {v.vault_id}</strong>
                    <span>
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
            <summary>Technical details</summary>
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
                {job.order.order_files.map((f) => (
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
        <aside>
          <h2>Archive requirements</h2>
          <div className="info" role="status">
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
          <dl className="facts">
            <div>
              <dt>Retention period</dt>
              <dd>{job.policy.retention_years} years</dd>
            </div>
            <div>
              <dt>Estimated budget</dt>
              <dd>{money(job.policy.budget_usd)}</dd>
            </div>
            <div>
              <dt>Estimated write cost</dt>
              <dd>
                {money(job.order?.cost.write_usd || pending?.summary.write_usd)}
              </dd>
            </div>
            <div>
              <dt>Storage locations</dt>
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
    inventory_files: "Checking the selected records.",
    prepare_archive: "Compressing and encrypting your records.",
    run_codec_sweep: "Comparing archive designs.",
    stress_test: "Testing recovery under adverse conditions.",
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
}: {
  p: Pending;
  busy: boolean;
  decide: (d: string) => void;
}) {
  const order = p.tool === "place_synthesis_order";
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
              <dt>Estimated write cost</dt>
              <dd>{money(p.summary.write_usd)}</dd>
            </div>
            <div>
              <dt>Estimated cost per recovery test</dt>
              <dd>{money(p.summary.read_usd)}</dd>
            </div>
            <div>
              <dt>Storage locations</dt>
              <dd>{p.args.n_vaults || 3}</dd>
            </div>
          </dl>
          <table>
            <thead>
              <tr>
                <th>Resilience test</th>
                <th>Successful trials</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {p.summary.evidence?.map((e) => (
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
          {!p.summary.can_approve && (
            <div className="error">
              This proposal needs passing tests for the selected design within
              budget. Reject it to revise the requirements.
            </div>
          )}
          <p>
            Simulation results do not guarantee future recovery. No purchase
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
