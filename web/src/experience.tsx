import { useEffect, useState } from "react";
import type { Archive, Ev } from "./types";

export function Journey() {
  return <div className="journey" aria-label="How the archive works">
    <div><span>01 / UPLOAD</span><strong>Your original file</strong><p>A picture, a document, a record that matters.</p></div>
    <b aria-hidden="true">→</b>
    <div><span>02 / TEST</span><strong>A DNA archive</strong><p>Real encoding. Simulated aging and failures.</p></div>
    <b aria-hidden="true">→</b>
    <div><span>03 / RESTORE</span><strong>The same file, verified</strong><p>Recovered bytes checked against the original.</p></div>
  </div>;
}

export function FilePreview({name, src, file, large=false}: {name:string; src?:string; file?:File; large?:boolean}) {
  const [local, setLocal] = useState<string>();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!file || !/\.(png|jpe?g|webp)$/i.test(name)) return;
    const url = URL.createObjectURL(file); setLocal(url);
    return () => URL.revokeObjectURL(url);
  }, [file, name]);
  useEffect(() => setFailed(false), [src, local]);
  const image = /\.(png|jpe?g|webp)$/i.test(name);
  if (image && (local || src) && !failed)
    return <img className={large ? "file-preview large" : "file-preview"} src={local || src} alt={`${large ? "Recovered" : "Preview of"} ${name}`} onError={() => setFailed(true)} />;
  if (/\.pdf$/i.test(name) && src) return <a className="file-icon" href={src} target="_blank" rel="noreferrer">Preview PDF</a>;
  return <span className="file-icon" aria-label={failed ? "Preview unavailable" : "File"}>{failed ? "Preview unavailable" : name.split(".").pop()?.toUpperCase() || "FILE"}</span>;
}

export function ProgressInfo({job, events}: {job:Archive; events:Ev[]}) {
  const [now,setNow] = useState(Date.now());
  useEffect(() => { const t=setInterval(()=>setNow(Date.now()),1000);return ()=>clearInterval(t);},[]);
  const seconds=Math.max(0,Math.floor((now-Date.parse(job.created))/1000));
  const complete=events.filter(e=>["experiment_result","stress_result"].includes(e.type)).length;
  const failed=events.filter(e=>e.type==="stress_result" && !e.data.passed).slice(-1)[0];
  const latest=events.filter(e=>e.type==="tool_call").slice(-1)[0];
  return <div className="progress-info"><p>{Math.floor(seconds/60)}m {seconds%60}s elapsed · {complete} measured tests completed</p>
    {job.analysis_preset==="quick_demo" && <small>Quick picture demo · 3 trials per point · up to 4 designs. Small trial counts are demo evidence, not a reliability guarantee.</small>}
    {failed && latest && latest.seq>failed.seq && <p className="revision-note">An earlier design failed a resilience test. The agent is checking a revised design before approval.</p>}
    <small>You can leave this page and return. Analysis continues while the local service is running.</small>
  </div>;
}

export function DnaStory({job,id}: {job:Archive;id:string}) {
  const s=job.dna_summary;
  return <section className="dna-story"><div className="section-heading"><h2>Your file’s journey</h2><span className="badge">Simulated DNA storage</span></div>
    <Journey />
    {job.analysis_preset === "quick_demo" && <p className="muted">Quick demo · 3 trials per measured point · real encoding and recovery with simulated DNA conditions.</p>}
    {!job.originals_available && !!job.order && <p>Working originals have been removed. The recovery test reads the DNA archive and uses your separately stored encryption key.</p>}
    {s ? <><dl className="facts"><div><dt>Total DNA letters</dt><dd>{s.total_letters.toLocaleString()}</dd></div><div><dt>File data + recovery redundancy</dt><dd>{s.data_letters.toLocaleString()}</dd></div><div><dt>Recovery instructions, across locations</dt><dd>{s.manifest_letters.toLocaleString()}</dd></div></dl>
      <p>{s.data_strands.toLocaleString()} data strands + {s.manifest_strands.toLocaleString()} manifest strands. Your file spans many sequences.</p>
      <label>One actual data strand<code className="dna-sequence">{s.example}</code></label>
      <details><summary>Download DNA sequences</summary><p>FASTA is a text format containing strand names and DNA letters. A single strand cannot restore the whole file. Keep the complete archive and encryption key.</p>
        {job.order?.order_files.filter(p=>p.endsWith('.fasta')).map(p=><a className="dna-download" key={p} href={`/api/jobs/${id}/files/${p.split('/').map(encodeURIComponent).join('/')}`} download>DNA sequences — FASTA text · {p.split('/')[1]}</a>)}
      </details></> : <p>{job.order ? "DNA counts not available for this older archive." : "Your DNA sequence and letter counts will appear once the approved archive has been prepared."}</p>}
  </section>;
}
