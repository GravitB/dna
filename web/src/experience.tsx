import { useEffect, useState } from "react";
import type { Archive, Ev } from "./types";

export function Journey() {
  return <ol className="journey" aria-label="How the archive works">
    <li><span>01 · Upload</span><strong>Your original file</strong><p>A picture, a document, a record that matters.</p></li>
    <li><span>02 · Test</span><strong>A DNA archive</strong><p>Real encoding. Simulated aging and failures.</p></li>
    <li><span>03 · Restore</span><strong>The same file, verified</strong><p>Recovered bytes checked against the original.</p></li>
  </ol>;
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
  const complete=events.reduce((n,e)=>n+(["experiment_result","stress_result"].includes(e.type) ? 1 : e.type === "candidate_result" ? e.data.scenarios?.length || 0 : 0),0);
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
  const fastas=job.order?.order_files.filter(p=>p.endsWith('.fasta')) || [];
  if (!s) return <p className="muted">{job.order ? "DNA counts are not available for this older archive." : "Your DNA sequence and letter counts will appear once the approved archive has been prepared."}</p>;
  return <section className="dna-story">
    <dl className="summary">
      <div><dt>DNA letters</dt><dd>{s.total_letters.toLocaleString()}</dd></div>
      <div><dt>Data strands</dt><dd>{s.data_strands.toLocaleString()}</dd></div>
      <div><dt>Manifest strands</dt><dd>{s.manifest_strands.toLocaleString()}</dd></div>
      <div><dt>Saved FASTA</dt><dd className="links">{fastas.map(p=><a key={p} href={`/api/jobs/${id}/files/${p.split('/').map(encodeURIComponent).join('/')}`} download>DNA sequences · {p.split('/')[1]}</a>)}</dd></div>
    </dl>
    {!job.originals_available && !!job.order && <p className="fine">Working originals have been removed. The recovery test reads the DNA archive and uses your separately stored encryption key.</p>}
    <details className="hidden-example"><summary>Example data strand as text</summary><code className="dna-sequence">{s.example}</code></details>
  </section>;
}
