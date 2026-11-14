import { useEffect, useRef, useState } from "react";
import type { Archive } from "./types";
import { parseDnaFasta, complement, type DnaStrand } from "./dna";

export default function DnaExplorer({ job }: { job: Archive }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="dna-explorer">
      <div className="section-heading">
        <div>
          <h2>Your records, written as DNA</h2>
          <p>Explore the actual DNA letters generated for this archive.</p>
        </div>
        <button
          disabled={!job.order}
          className={open ? "" : "primary"}
          onClick={() => setOpen(!open)}
          aria-expanded={open}
        >
          {open ? "Close DNA viewer" : "Explore your DNA"}
        </button>
      </div>
      {!job.order ? (
        <small>
          The DNA preview becomes available after you approve the simulated
          archive.
        </small>
      ) : open ? (
        <Explorer key={job.id} job={job} />
      ) : (
        <small>
          See a strand in 3D, inspect its letters, or download it for oxView.
        </small>
      )}
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
  const [closeup, setCloseup] = useState(true);
  const [start, setStart] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [rendererError, setRendererError] = useState("");
  const [ready, setReady] = useState(false);
  const [rendered, setRendered] = useState("");
  const [building, setBuilding] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [retry, setRetry] = useState(0);
  const frame = useRef<HTMLIFrameElement>(null);
  const pools = [...new Set(records.map((r) => r.pool))].sort((a, b) =>
    a === "MANIFEST" ? 1 : b === "MANIFEST" ? -1 : a.localeCompare(b),
  );
  const strands = records
    .filter((r) => r.pool === pool)
    .sort((a, b) => a.index - b.index);
  const current = strands[position];
  const visibleStart = closeup
    ? Math.min(start, Math.max(0, (current?.sequence.length || 0) - 30))
    : 0;
  const visibleLength = closeup
    ? Math.min(30, current?.sequence.length || 0)
    : current?.sequence.length || 0;
  const renderKey = current
    ? `${current.sequence}:${visibleStart}:${visibleLength}:${duplex}`
    : "";
  const send = (data: Record<string, unknown>) =>
    frame.current?.contentWindow?.postMessage(data, location.origin);
  useEffect(() => {
    if (!available.some((v) => v.vault_id === vault))
      setVault(available[0]?.vault_id || 0);
  }, [job.vaults.map((v) => `${v.vault_id}:${v.status}`).join(","), vault]);
  useEffect(() => {
    const abort = new AbortController();
    setReady(false);
    setRecords([]);
    setError("");
    setLoading(true);
    setPosition(0);
    setRendered("");
    if (!vault) {
      setLoading(false);
      return;
    }
    fetch(`/api/jobs/${job.id}/files/vaults/vault-${vault}/order.fasta`, {
      signal: abort.signal,
    })
      .then(async (r) => {
        if (!r.ok)
          throw new Error(
            "Could not load the saved DNA. Check this location and try again.",
          );
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
  useEffect(() => {
    const receive = (e: MessageEvent) => {
      if (
        e.origin !== location.origin ||
        e.source !== frame.current?.contentWindow ||
        !e.data
      )
        return;
      if (e.data.type === "lazarus-oxview-ready") {
        setReady(true);
        setRendererError("");
      }
      if (e.data.type === "lazarus-oxview-error") {
        setRendererError(
          "The 3D viewer could not render this strand. You can still inspect its exact sequence or download the FASTA file.",
        );
        setBuilding("");
      }
      if (
        e.data.type === "lazarus-oxview-rendered" &&
        e.data.requestId === renderKey &&
        e.data.sequence === current?.sequence &&
        e.data.start === visibleStart &&
        e.data.renderedSequence ===
          current?.sequence.slice(visibleStart, visibleStart + visibleLength)
      ) {
        setRendered(renderKey);
        setBuilding("");
      }
      if (
        e.data.type === "lazarus-oxview-building" &&
        e.data.requestId === renderKey
      )
        setBuilding(
          `Building the visual model: ${e.data.count} of ${e.data.total} bases`,
        );
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [current?.sequence, visibleStart, visibleLength, renderKey]);
  useEffect(() => {
    if (ready && current) {
      setRendered("");
      send({
        type: "lazarus-oxview-set",
        sequence: current.sequence,
        duplex,
        start: visibleStart,
        length: visibleLength,
        requestId: renderKey,
      });
    }
  }, [
    ready,
    current?.header,
    current?.sequence,
    duplex,
    visibleStart,
    visibleLength,
    renderKey,
  ]);
  useEffect(() => {
    setSelected(null);
    setStart(0);
  }, [current?.header]);
  useEffect(() => {
    if (rendered === renderKey && selected !== null)
      send({ type: "lazarus-oxview-select", index: selected });
  }, [rendered, selected, renderKey]);
  useEffect(() => {
    if (!current || ready) return;
    const timer = setTimeout(
      () =>
        setRendererError(
          "The 3D viewer has not loaded. You can still inspect or download the DNA sequence below.",
        ),
      15000,
    );
    return () => clearTimeout(timer);
  }, [!!current, ready]);
  function download() {
    if (!current) return;
    const blob = new Blob([`>${current.header}\n${current.sequence}\n`], {
      type: "text/plain",
    });
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
        No simulated location is available. The viewer only uses DNA from
        locations currently marked available.
      </div>
    );
  return (
    <div className="dna-body">
      <ol className="dna-journey" aria-label="How your file becomes DNA">
        <li>Selected records</li>
        <li>Encrypted data</li>
        <li className="active">DNA letters</li>
        <li>3D model</li>
      </ol>
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
                  {p === "MANIFEST"
                    ? "Archive instructions (manifest)"
                    : `Data group ${Number(p.replace("pool-", "")) + 1}`}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {loading && <p role="status">Loading DNA from the saved archive…</p>}
      {error && (
        <div role="alert" className="error">
          {error}
          <button onClick={() => setRetry(retry + 1)}>
            Try loading DNA again
          </button>
        </div>
      )}
      {current && (
        <>
          <div className="dna-strand-heading">
            <div>
              <strong>Encoded strand #{current.index + 1}</strong>
              <small>
                {current.sequence.length} bases ·{" "}
                {strands.length.toLocaleString()} strands available in this
                group at this location
              </small>
            </div>
            <div className="actions">
              <button
                disabled={position === 0}
                onClick={() => setPosition(position - 1)}
                aria-label="Previous DNA strand"
              >
                Previous
              </button>
              <label className="strand-number">
                Strand position
                <input
                  aria-label="Strand position"
                  type="number"
                  min="1"
                  max={strands.length}
                  value={position + 1}
                  onChange={(e) => {
                    const n = +e.target.value;
                    if (Number.isInteger(n) && n >= 1 && n <= strands.length)
                      setPosition(n - 1);
                  }}
                />
              </label>
              <button
                disabled={position === strands.length - 1}
                onClick={() => setPosition(position + 1)}
                aria-label="Next DNA strand"
              >
                Next
              </button>
            </div>
          </div>
          <div className="dna-view-range">
            <label>
              3D detail
              <select
                value={closeup ? "close" : "whole"}
                onChange={(e) => setCloseup(e.target.value === "close")}
              >
                <option value="close">Close-up of 30 bases</option>
                <option value="whole">Whole strand</option>
              </select>
            </label>
            {closeup && current.sequence.length > 30 && (
              <label>
                First base in view
                <input
                  type="range"
                  min="0"
                  max={current.sequence.length - 30}
                  value={visibleStart}
                  onChange={(e) => setStart(+e.target.value)}
                />
              </label>
            )}
            <span>
              Showing bases {visibleStart + 1}–{visibleStart + visibleLength} of{" "}
              {current.sequence.length}
            </span>
          </div>
          <div className="dna-stage">
            <iframe
              ref={frame}
              src={`${import.meta.env.BASE_URL}oxview/index.html`}
              title="3D DNA viewer powered by oxView"
              sandbox="allow-scripts allow-same-origin"
              onLoad={() => {
                setRendererError("");
              }}
            />
            <div className="dna-stage-label">
              Saved DNA bases · Idealized structure
            </div>
            {!ready && !rendererError && (
              <div className="dna-stage-status" role="status">
                Starting oxView…
              </div>
            )}
          </div>
          {rendererError && (
            <div role="alert" className="error">
              {rendererError}
              <button
                onClick={() => {
                  setReady(false);
                  setRendererError("");
                  if (frame.current) frame.current.src = `${import.meta.env.BASE_URL}oxview/index.html`;
                }}
              >
                Reload 3D viewer
              </button>
            </div>
          )}
          <div className="dna-toolbar">
            <div className="actions">
              <button
                disabled={!ready || !!rendererError}
                onClick={() =>
                  send({ type: "lazarus-oxview-control", action: "left" })
                }
                aria-label="Rotate DNA left"
              >
                Rotate left
              </button>
              <button
                disabled={!ready || !!rendererError}
                onClick={() =>
                  send({ type: "lazarus-oxview-control", action: "right" })
                }
                aria-label="Rotate DNA right"
              >
                Rotate right
              </button>
              <button
                disabled={!ready || !!rendererError}
                onClick={() =>
                  send({ type: "lazarus-oxview-control", action: "in" })
                }
              >
                Zoom in
              </button>
              <button
                disabled={!ready || !!rendererError}
                onClick={() =>
                  send({ type: "lazarus-oxview-control", action: "out" })
                }
              >
                Zoom out
              </button>
              <button
                disabled={!ready || !!rendererError}
                onClick={() =>
                  send({ type: "lazarus-oxview-control", action: "reset" })
                }
              >
                Reset view
              </button>
            </div>
            <button
              className="primary"
              disabled={!ready || !!rendererError}
              onClick={() =>
                send({
                  type: "lazarus-oxview-set",
                  sequence: current.sequence,
                  duplex,
                  animate: true,
                  start: visibleStart,
                  length: visibleLength,
                  requestId: renderKey,
                })
              }
            >
              Build strand visually
            </button>
          </div>
          <div role="status" className="dna-render-status">
            {building ||
              (rendered === renderKey
                ? "3D model matches these saved DNA bases."
                : ready
                  ? "Preparing the selected strand…"
                  : "Sequence available below while 3D loads.")}
          </div>
          <label className="dna-complement">
            <input
              type="checkbox"
              checked={duplex}
              onChange={(e) => setDuplex(e.target.checked)}
            />
            Show a generated complementary strand to illustrate a double helix
          </label>
          <p className="muted">
            Drag to rotate and scroll to zoom. The second strand is generated
            for the illustration; it is not an additional encoded archive
            strand.
          </p>
          <div className="dna-sequence-heading">
            <h3>
              Exact saved sequence <small>5′ to 3′ · {current.header}</small>
            </h3>
            <button onClick={download}>Download this strand (FASTA)</button>
          </div>
          <div className="dna-legend" aria-label="DNA base colors">
            {["A", "C", "G", "T"].map((base) => (
              <span key={base}>
                <i className={`base-${base}`} />
                {base}
              </span>
            ))}
          </div>
          <div className="dna-letters" aria-label="Saved DNA bases">
            {[...current.sequence].map((base, i) => (
              <button
                key={i}
                className={`base-${base}${selected === i ? " selected" : ""}`}
                aria-label={`Base ${i + 1}: ${base}`}
                aria-pressed={selected === i}
                onClick={() => {
                  setSelected(i);
                  if (
                    closeup &&
                    (i < visibleStart || i >= visibleStart + visibleLength)
                  )
                    setStart(
                      Math.max(
                        0,
                        Math.min(i - 14, current.sequence.length - 30),
                      ),
                    );
                  send({ type: "lazarus-oxview-select", index: i });
                }}
              >
                {base}
              </button>
            ))}
          </div>
          {duplex && (
            <details>
              <summary>Generated complement (3′ to 5′)</summary>
              <code className="dna-complement-text">
                {complement(current.sequence)}
              </code>
            </details>
          )}
          <p className="dna-note">
            A visual model of one short strand from your archive. It does not
            show physical DNA, predict its exact folded shape, or prove
            recovery. Viewing does not change your archive.{" "}
            <a href={`${import.meta.env.BASE_URL}oxview/README.md`} target="_blank" rel="noreferrer">
              Powered by oxView
            </a>{" "}
            ·{" "}
            <a href={`${import.meta.env.BASE_URL}oxview/LICENSE`} target="_blank" rel="noreferrer">
              GPL-3.0-or-later
            </a>
          </p>
        </>
      )}
    </div>
  );
}
