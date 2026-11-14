import { Fragment, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { CountUp, IconCheck, IconFile, IconHelix, IconShield, Strand } from "./ui";
import type { Archive, Ev } from "./types";

const STEPS = [
  { k: "01", tag: "Upload", title: "Your original file", text: "A picture, a document, a record that matters.", icon: <IconFile size={26} /> },
  { k: "02", tag: "Test", title: "A DNA archive", text: "Real encoding. Simulated aging and failures.", icon: <IconHelix size={26} /> },
  { k: "03", tag: "Restore", title: "The same file, verified", text: "Recovered bytes checked against the original.", icon: <IconShield size={26} /> },
];

function FlowArrow() {
  return <li className="journey-arrow" aria-hidden="true">
    <svg viewBox="0 0 72 20" preserveAspectRatio="none">
      <line className="track" x1="2" y1="10" x2="62" y2="10" />
      <line className="flow" x1="2" y1="10" x2="62" y2="10" />
      <path className="head" d="M58 4 66 10 58 16" />
    </svg>
  </li>;
}

/* Three blocks joined by flowing arrows. Without `reached` the blocks light up
 * in turn, as an explainer; with it they show how far this archive has got. */
export function Journey({ reached }: { reached?: number } = {}) {
  const live = reached == null;
  return <ol className={`journey${live ? " journey--loop" : ""}`} aria-label="How the archive works">
    {STEPS.map((s, i) => <Fragment key={s.k}>
      {i > 0 && <FlowArrow />}
      <li className={live ? "" : i < reached! ? "done" : i === reached ? "current" : "todo"} style={{ ["--i" as string]: i } as CSSProperties}>
        <div className="journey-icon">{s.icon}{!live && i < reached! && <em className="journey-done"><IconCheck size={13} /></em>}</div>
        <span className="journey-tag">{s.k} / {s.tag.toUpperCase()}</span>
        <strong>{s.title}</strong>
        <p>{s.text}</p>
      </li>
    </Fragment>)}
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
  const lastDrill = job.drills?.[job.drills.length - 1];
  const reached = lastDrill?.all_verified ? 3 : job.order ? 2 : 1;
  return <section className="dna-story"><div className="section-heading"><h2>Your file’s journey</h2><span className="badge">Simulated DNA storage</span></div>
    <Journey reached={reached} />
    {job.analysis_preset === "quick_demo" && <p className="muted">Quick demo · 3 trials per measured point · real encoding and recovery with simulated DNA conditions.</p>}
    {!job.originals_available && !!job.order && <p>Working originals have been removed. The recovery test reads the DNA archive and uses your separately stored encryption key.</p>}
    {s ? <><dl className="facts stat-tiles"><div><dt>Total DNA letters</dt><dd><CountUp value={s.total_letters} /></dd></div><div><dt>File data + recovery redundancy</dt><dd><CountUp value={s.data_letters} /></dd></div><div><dt>Recovery instructions, across locations</dt><dd><CountUp value={s.manifest_letters} /></dd></div></dl>
      <p>{s.data_strands.toLocaleString()} data strands + {s.manifest_strands.toLocaleString()} manifest strands. Your file spans many sequences.</p>
      <label>One actual data strand<code className="dna-sequence"><Strand seq={s.example} /></code></label>
      <details><summary>Download DNA sequences</summary><p>FASTA is a text format containing strand names and DNA letters. A single strand cannot restore the whole file. Keep the complete archive and encryption key.</p>
        {job.order?.order_files.filter(p=>p.endsWith('.fasta')).map(p=><a className="dna-download" key={p} href={`/api/jobs/${id}/files/${p.split('/').map(encodeURIComponent).join('/')}`} download>DNA sequences — FASTA text · {p.split('/')[1]}</a>)}
      </details></> : <p>{job.order ? "DNA counts not available for this older archive." : "Your DNA sequence and letter counts will appear once the approved archive has been prepared."}</p>}
  </section>;
}
