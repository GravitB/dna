import { useEffect, useState } from "react";
import type { Archive } from "./types";
import { parseDnaFasta, type DnaStrand } from "./dna";
import Helix3D from "./Helix";

export default function DnaExplorer({ job }: { job: Archive }) {
  if (!job.order)
    return (
      <section className="dna-explorer">
        <h2>Your records, written as DNA</h2>
        <p className="muted">The DNA viewer opens after you approve the simulated archive.</p>
        <button disabled>Explore your DNA</button>
      </section>
    );
  return (
    <section className="dna-explorer">
      <Explorer key={job.id} job={job} />
    </section>
  );
}

function Explorer({ job }: { job: Archive }) {
  const available = job.vaults.filter((v) => v.status !== "destroyed");
  const [vault, setVault] = useState(available[0]?.vault_id || 0);
  const [records, setRecords] = useState<DnaStrand[]>([]);
  const [pool, setPool] = useState("");
  const [position, setPosition] = useState(0);
  const [duplex, setDuplex] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [retry, setRetry] = useState(0);
  const pools = [...new Set(records.map((r) => r.pool))].sort((a, b) =>
    a === "MANIFEST" ? 1 : b === "MANIFEST" ? -1 : a.localeCompare(b),
  );
  const strands = records.filter((r) => r.pool === pool).sort((a, b) => a.index - b.index);
  const current = strands[position];
  useEffect(() => {
    if (!available.some((v) => v.vault_id === vault)) setVault(available[0]?.vault_id || 0);
  }, [job.vaults.map((v) => `${v.vault_id}:${v.status}`).join(","), vault]);
  useEffect(() => {
    const abort = new AbortController();
    setRecords([]);
    setError("");
    setLoading(true);
    setPosition(0);
    if (!vault) {
      setLoading(false);
      return;
    }
    fetch(`/api/jobs/${job.id}/files/vaults/vault-${vault}/order.fasta`, { signal: abort.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error("Could not load the saved DNA. Check this location and try again.");
        return r.text();
      })
      .then((text) => {
        const r = parseDnaFasta(text);
        if (abort.signal.aborted) return;
        setRecords(r);
        setPool(r.find((s) => s.pool !== "MANIFEST")?.pool || r[0].pool);
        setLoading(false);
      })
      .catch((e) => {
        if (!abort.signal.aborted) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => abort.abort();
  }, [job.id, vault, retry]);
  useEffect(() => setSelected(null), [current?.header]);

  function download() {
    if (!current) return;
    const blob = new Blob([`>${current.header}\n${current.sequence}\n`], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${current.pool}-strand-${current.index + 1}.fasta`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  if (!available.length)
    return (
      <div className="info">
        No simulated location is available. The viewer only reads DNA from locations that are still
        available.
      </div>
    );
  return (
    <div className="dna-body">
      <div className="dna-controls">
        <label>
          Storage location
          <select value={vault} onChange={(e) => setVault(+e.target.value)}>
            {available.map((v) => (
              <option key={v.vault_id} value={v.vault_id}>
                Location {v.vault_id}
              </option>
            ))}
          </select>
        </label>
        {!!records.length && (
          <label>
            DNA group
            <select
              value={pool}
              onChange={(e) => {
                setPool(e.target.value);
                setPosition(0);
              }}
            >
              {pools.map((p) => (
                <option key={p} value={p}>
                  {p === "MANIFEST" ? "Archive instructions (manifest)" : `Data group ${Number(p.replace("pool-", "")) + 1}`}
                </option>
              ))}
            </select>
          </label>
        )}
        {current && (
          <div className="stepper" role="group" aria-label="Choose a strand">
            <button className="icon" disabled={position === 0} onClick={() => setPosition(position - 1)} aria-label="Previous DNA strand">
              ‹
            </button>
            <label className="strand-number">
              <span>Strand</span>
              <input
                aria-label="Strand position"
                type="number"
                min="1"
                max={strands.length}
                value={position + 1}
                onChange={(e) => {
                  const v = +e.target.value;
                  if (Number.isInteger(v) && v >= 1 && v <= strands.length) setPosition(v - 1);
                }}
              />
              <span className="of">of {strands.length.toLocaleString()}</span>
            </label>
            <button className="icon" disabled={position === strands.length - 1} onClick={() => setPosition(position + 1)} aria-label="Next DNA strand">
              ›
            </button>
          </div>
        )}
      </div>
      {loading && <div className="skeleton stage-skeleton" role="status">Loading DNA from the saved archive…</div>}
      {error && (
        <div role="alert" className="error">
          {error}
          <button onClick={() => setRetry(retry + 1)}>Try loading DNA again</button>
        </div>
      )}
      {current && (
        <>
          <div className="stage">
            <Helix3D
              sequence={current.sequence}
              duplex={duplex}
              selected={selected}
              onSelect={setSelected}
              label={`3D model of encoded strand ${current.index + 1}: ${current.sequence.length} bases`}
            />
            <div className="stage-caption">
              <strong>Encoded strand #{current.index + 1}</strong>
              <span className="mono">{current.header}</span>
              <span>
                {current.sequence.length} nt · GC {gc(current.sequence)}%
              </span>
            </div>
            <div className="stage-legend" aria-label="DNA base colors">
              {(["A", "C", "G", "T"] as const).map((b) => (
                <span key={b}>
                  <i className={`dot base-${b}`} />
                  {b}
                </span>
              ))}
            </div>
          </div>
          <div className="dna-toolbar">
            <label className="switch">
              <input type="checkbox" checked={duplex} onChange={(e) => setDuplex(e.target.checked)} />
              <span className="switch-track" aria-hidden="true" />
              Show a generated complementary strand to illustrate a double helix
            </label>
            <button className="ghost small-button" onClick={download}>Download this strand (FASTA)</button>
          </div>
          <h3 className="seq-heading">
            Exact saved sequence <small>5′ → 3′{selected != null && ` · base ${selected + 1} selected`}</small>
          </h3>
          <div className="dna-letters" aria-label="Saved DNA bases">
            {[...current.sequence].map((base, i) => (
              <button
                key={i}
                className={`base-${base}${selected === i ? " selected" : ""}${i % 10 === 9 ? " tenth" : ""}`}
                aria-label={`Base ${i + 1}: ${base}`}
                aria-pressed={selected === i}
                onClick={() => setSelected(selected === i ? null : i)}
              >
                {base}
              </button>
            ))}
          </div>
          <p className="fine">
            Idealized B-form model built from the exact saved bases. The partner strand is generated for the
            illustration. Not physical DNA, and viewing does not change your archive.
          </p>
        </>
      )}
    </div>
  );
}

function gc(sequence: string) {
  let n = 0;
  for (const b of sequence) if (b === "G" || b === "C") n++;
  return ((n / (sequence.length || 1)) * 100).toFixed(1);
}
