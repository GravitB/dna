import {SCALE_REFERENCES,pickReference,referencePosition,ReferenceGlyph} from "./scaleReferences";
import "./StorageScale.css";
import {memo,useId,useState} from 'react';
import type {Archive} from './types';

export const WORLD_BYTES = 218433e18;
const WORLD_SOURCE = 'https://www.idc.com/resource-center/definitions/what-are-the-global-datasphere-and-global-storagesphere/';
// Decimal units. These are explicit illustration assumptions, not facility measurements.
export function footprint(bytes:number,copies:number) {
  const b=Number.isFinite(bytes)?Math.max(0,bytes):0;
  return {grams:b*copies/215e15, driveShare:b*copies/20e12,
    pages:Math.ceil(Math.ceil(b/3)*4/2000)*copies};
}
const plainNumber=new Intl.NumberFormat('en',{maximumFractionDigits:2});
const compactNumber=new Intl.NumberFormat('en',{maximumFractionDigits:2,notation:'compact'});
const number=(n:number)=>n>=1e18?`${plainNumber.format(n/1e18)} quintillion`:n>=1e15?`${plainNumber.format(n/1e15)} quadrillion`:n>0&&n<.01?'<0.01':(n>=1e6?compactNumber:plainNumber).format(n);
const size=(b:number)=> b>=1e21?`${number(b/1e21)} ZB`:b>=1e18?`${number(b/1e18)} EB`:b>=1e15?`${number(b/1e15)} PB`:b>=1e12?`${number(b/1e12)} TB`:b>=1e9?`${number(b/1e9)} GB`:`${number(b/1000)} KB`;
export function volumes(bytes:number,copies:number) {
 const f=footprint(bytes,copies);
 return {paper:f.pages*210*297*.1, disk:f.driveShare*147*101.6*26.1, dna:f.grams*1000};
}
export function largerThanDna(bytes:number,copies:number) {
 const v=volumes(bytes,copies);
 return {paper:v.dna>0?v.paper/v.dna:0,disk:v.dna>0?v.disk/v.dna:0};
}
export function ratioLabel(n:number) {
 if (!n) return '—';
 for(const [unit,name] of [[1e18,'quintillion'],[1e15,'quadrillion'],[1e12,'trillion'],[1e9,'billion'],[1e6,'million'],[1e3,'thousand']] as const)
  if(n>=unit) return `${number(n/unit)} ${name}×`;
 return `${number(n)}×`;
}
export function fitScales(bytes:number,copies:number) {
 const v=volumes(bytes,copies);
 const paperEdge=Math.cbrt(v.paper), dnaEdge=Math.cbrt(v.dna);
 return {paper:120/Math.max(paperEdge,1e-12), dna:120/Math.max(dnaEdge||paperEdge,1e-12)};
}
const length=(mm:number)=>mm>=1e6?`${number(mm/1e6)} km`:mm>=1000?`${number(mm/1000)} m`:mm>=1?`${number(mm)} mm`:mm>=.001?`${number(mm*1000)} µm`:`${number(mm*1e6)} nm`;
type Point=[number,number];
// Clip in model code, so the browser never has to rasterize giant off-screen polygons.
export function clipPolygon(points:Point[],width=280,height=230):Point[] {
 let result=points;
 for(const [axis,bound,keepGreater] of [[0,0,true],[0,width,false],[1,0,true],[1,height,false]] as const) {
  const input=result; result=[];
  for(let i=0;i<input.length;i++) {
   const start=input[i],end=input[(i+1)%input.length];
   const inside=(p:Point)=>keepGreater?p[axis]>=bound:p[axis]<=bound;
   const a=inside(start),b=inside(end);
   if(a) result.push(start);
   if(a!==b) {
    const t=(bound-start[axis])/(end[axis]-start[axis]);
    const intersection:Point=[start[0]+t*(end[0]-start[0]),start[1]+t*(end[1]-start[1])];
    intersection[axis]=bound;
    result.push(intersection);
   }
  }
 }
 return result;
}
const Scene=memo(function Scene({kind,volume,pxPerMm,ruler,referenceId}:{referenceId?:string|null;kind:'paper'|'disk'|'dna';volume:number;pxPerMm:number;ruler:number}) {
 const gridId=useId();
 const personHeight=1700*pxPerMm;
 const reference=SCALE_REFERENCES.find(r=>r.id===referenceId)||pickReference(pxPerMm);
 const referenceHeight=reference.mm*pxPerMm;
 const edge=Math.cbrt(volume), side=edge*pxPerMm, x=36, y=215, depth=side*.22;
 const polygon=(points:Point[])=>clipPolygon(points).map(p=>p.join(',')).join(' ');
 const top=polygon([[x,y-side],[x+depth,y-side-depth],[x+side+depth,y-side-depth],[x+side,y-side]]);
 const right=polygon([[x+side,y],[x+side+depth,y-depth],[x+side+depth,y-side-depth],[x+side,y-side]]);
 const personVisible=personHeight>=1&&personHeight<=y;
 return <div className={`volume-scene volume-${kind}`}>
  <svg viewBox="0 0 280 270" role="img" aria-label={`${kind} volume-equivalent cube, edge ${length(edge)}; 1.7 meter person at the same scale`}>
   <defs><pattern id={gridId} width="20" height="20" patternUnits="userSpaceOnUse"><path d="M 20 0 L 0 0 0 20" fill="none" stroke="currentColor" opacity=".08"/></pattern></defs>
   <rect width="280" height="230" fill={`url(#${gridId})`}/>
   <path d="M 20 215 H 270" stroke="currentColor" opacity=".2"/>
   <g className="volume-solid" opacity={.18+.82*Math.min(1,120/Math.max(side,120))}>
    <rect x={x} y={Math.max(0,y-side)} width={Math.min(280-x,side)} height={Math.min(y,side)} fill="currentColor" opacity=".55"/>
    {top&&<polygon points={top} fill="currentColor" opacity=".85"/>}
    {right&&<polygon points={right} fill="currentColor" opacity=".35"/>}
   </g>
   {side>0&&side<1&&<g><path d={`M ${x-5} ${y} h 10 M ${x} ${y-5} v 10`} stroke="currentColor" strokeDasharray="1 2"/><text x="45" y="202" fill="currentColor" fontSize="9">Below one pixel</text></g>}
   {side*1.22>y&&<text x="24" y="18" fill="currentColor" fontSize="10">Cube continues beyond view ↑</text>}
   <g className="person-reference" data-person-height={personHeight} aria-hidden="true">
    {personVisible?<g transform={`translate(${reference.id==='person'?237:268} ${y}) scale(${personHeight})`} fill="currentColor" opacity=".65">
     <circle cx="0" cy="-.93" r=".07"/>
     <path d="M -.075 -.83 L .075 -.83 L .12 -.46 L .075 -.42 L .13 0 L .045 0 L 0 -.35 L -.045 0 L -.13 0 L -.075 -.42 L -.12 -.46 Z"/>
     <path d="M -.07 -.8 L -.12 -.8 L -.23 -.49 L -.18 -.46 L -.065 -.68 Z M .07 -.8 L .12 -.8 L .23 -.49 L .18 -.46 L .065 -.68 Z"/>
    </g>:personHeight<1?<path d="M 233 215 h 8" stroke="currentColor" strokeDasharray="1 2"/>:reference.id==='person'?<g><path d="M 242 210 V 42 m -5 5 l 5 -5 l 5 5" fill="none" stroke="currentColor" strokeDasharray="3 4" opacity=".55"/><text x="222" y="32" fill="currentColor" fontSize="9">1.7 m ↑</text></g>:null}
   </g>
   {reference.id!=='person'&&referenceHeight>=1&&referenceHeight<=100&&<g className="object-reference" data-reference={reference.id} data-reference-height={referenceHeight} transform={`translate(230 ${y}) scale(${referenceHeight})`} fill="currentColor" opacity=".8"><ReferenceGlyph kind={reference.kind}/></g>}
   <path d={`M 36 245 v 5 h ${ruler*pxPerMm} v -5`} stroke="currentColor" fill="none"/>
   <text x="36" y="266" fill="currentColor" fontSize="10">{length(ruler)} · shared ruler</text>
  </svg>
  <span className="object-reference-label">Reference: {reference.name} · {length(reference.mm)}</span>
  <span className="volume-dimension">Cube edge: {length(edge)}</span>
  <span className="human-reference">1.7 m person · {personHeight<1?'below one screen pixel':personHeight>y?'taller than the visible area':'shown at the same scale'}</span>
 </div>;
});
export default function StorageScale({job,files:uploaded}:{job?:Archive;files?:{name:string;bytes:number}[]}) {
 const [scenario,setScenario]=useState(1e12);
 const [copies,setCopies]=useState(1);
 const [actual,setActual]=useState(!!job||!!uploaded);
 const [selected,setSelected]=useState('all');
 const [zoom,setZoom]=useState(0);
 const [referenceId,setReferenceId]=useState<string|null>(null);

 const archiveFiles=job?Object.entries(job.sealed||{}).map(([name,v])=>({name,bytes:Number((v as {bytes?:number}).bytes)||0})):[];
 const items=uploaded|| (archiveFiles.length?archiveFiles:(job?.intake_files||job?.files||[]).filter(f=>f.included!==false));
 const item=items.find(f=>`file:${f.name}`===selected);
 const fileBytes=item?item.bytes:items.reduce((n,f)=>n+f.bytes,0);
 const bytes=actual?fileBytes:scenario;
 const v=volumes(bytes,copies);
 const ratios=largerThanDna(bytes,copies);
 const world=!actual&&scenario===WORLD_BYTES;
 const fits=fitScales(bytes,copies);
 const targetLogScale=Math.log10(fits.paper)+(Math.log10(fits.dna)-Math.log10(fits.paper))*zoom/100;
 const pxPerMm=Math.pow(10,targetLogScale);
 const ruler=Math.pow(10,Math.floor(Math.log10(90/pxPerMm)));
 const scene=(kind:'paper'|'disk'|'dna')=><Scene kind={kind} volume={v[kind]} pxPerMm={pxPerMm} ruler={ruler} referenceId={referenceId}/>;
 const f=footprint(bytes,copies);
 const mass=f.grams>=1e6?`${number(f.grams/1e6)} tonnes`:f.grams>=1000?`${number(f.grams/1000)} kg`:f.grams>0&&f.grams<1e-11?`${(f.grams*1e12).toPrecision(2)} pg`:f.grams<1e-6?`${number(f.grams*1e9)} ng`:f.grams<.001?`${number(f.grams*1e6)} µg`:f.grams<1?`${number(f.grams*1000)} mg`:`${number(f.grams)} g`;
 return <section className="storage-scale" aria-label="Storage footprint explorer">
  <div className="scale-heading"><div><span className="scale-eyebrow">FROM FILES TO PHYSICAL SPACE</span><h2>Small medium. <span>Extraordinary scale.</span></h2><p>See how much larger paper and drive-capacity equivalents are than modeled DNA material, for the exact file you choose.</p></div><span className="scale-model-tag">Size-driven estimate</span></div>
  <div className="scale-controls">
   {!!items.length&&<label>View uploaded item<select value={actual?(item?selected:'all'):'scenario'} onChange={e=>{setSelected(e.target.value);setActual(true);setZoom(0);setReferenceId(null);}}><option value="all">All uploaded files</option>{items.map(f=><option key={f.name} value={`file:${f.name}`}>{f.name} · {size(f.bytes)}</option>)}{!actual&&<option value="scenario" disabled>Hypothetical archive</option>}</select></label>}
   <div className="scale-presets" aria-label="Archive size">{[1e9,1e12,1e15].map(b=><button key={b} aria-pressed={!actual&&scenario===b} onClick={()=>{setActual(false);setScenario(b);setZoom(0);setReferenceId(null);}}>{size(b)}</button>)}</div>
   <button className="scale-world-button" aria-pressed={world} onClick={()=>{setActual(false);setScenario(WORLD_BYTES);setZoom(0);setReferenceId(null);}}><svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.8 3.8 5.8 3.8 9s-1.2 6.2-3.8 9c-2.6-2.8-3.8-5.8-3.8-9S9.4 5.8 12 3z"/></svg>World’s annual data</button>
   <label>Copies of the information<select value={copies} onChange={e=>{setCopies(+e.target.value);setReferenceId(null);}}>{[1,3].map(n=><option key={n} value={n}>{n} {n===1?'copy':'copies'}</option>)}</select></label>
  </div>
  <div className="scale-caption" aria-live="polite"><strong>{size(bytes)}</strong> of source data · {copies===1?'one copy':`${copies} copies`} · {actual?`${item?.name||'all uploaded files'} · ${bytes.toLocaleString()} exact source bytes`:'hypothetical scale exploration, not an uploaded archive'}</div>
  {world&&<div className="world-story">
    <div><span className="scale-eyebrow">A WORLD-SCALE THOUGHT EXPERIMENT</span><h3>A year of global data.<br/><span>A {length(Math.cbrt(v.dna))} cube of material.</span></h3><p><strong>{size(WORLD_BYTES)}</strong> is IDC’s June 2026 estimate of global data generated in 2025, including replication and consumption. It is not the total data stored worldwide.</p><div className="world-numbers"><div><strong>{mass}</strong><span>modeled DNA material</span></div><div><strong>{number(v.dna/1e9)} m³</strong><span>at assumed 1 g/cm³ density</span></div><div><strong>{length(Math.cbrt(v.dna))}</strong><span>volume-equivalent cube edge</span></div></div><p className="fine">{copies} {copies===1?'copy':'copies'} · Extrapolation only. Excludes packaging, physical replication, recovery overhead and lab infrastructure. <a href={WORLD_SOURCE} target="_blank" rel="noreferrer">IDC source ↗</a></p></div>
    <div className="world-cube"><Scene kind="dna" volume={v.dna} pxPerMm={.08} ruler={1000}/><span>Fixed reference: the ruler represents one meter.</span></div>
  </div>}
  <div className="scale-comparison-intro"><h3>Same data. Different volumes.</h3><p>“Larger” below refers to <strong>volume</strong>, not cube edge length. Estimates use the assumptions below.</p></div>
  <div className="volume-zoom"><button aria-pressed={zoom===0} onClick={()=>{setZoom(0);setReferenceId(null);}}>Fit paper</button><label>Paper → DNA<input type="range" min="0" max="100" step=".1" value={zoom} onChange={e=>{setZoom(Math.max(0,Math.min(100,+e.target.value)));setReferenceId(null);}} aria-label="Shared magnification" aria-valuetext={zoom===0?'Entire paper cube in view':zoom===100?'Entire DNA cube in view':`${number(zoom)}% from paper fit to DNA fit`}/></label><button aria-pressed={zoom===100} onClick={()=>{setZoom(100);setReferenceId(null);}}>Fit DNA</button><output>{number(pxPerMm/fits.paper)}×</output><span className="person-key">Person reference: 1.7 m, same scale in every panel</span></div>
  <div className="reference-guide"><div><strong>Jump to a familiar size</strong><span>Examples, not universal object sizes. Reference objects change as you zoom.</span></div><div className="reference-stops" aria-label="Reference object zoom stops">{SCALE_REFERENCES.map(r=>({r,position:referencePosition(r.mm,fits.paper,fits.dna)})).filter(({position})=>position!==null).map(({r,position})=><button key={r.id} aria-pressed={(referenceId||pickReference(pxPerMm).id)===r.id} onClick={()=>{setZoom(position!);setReferenceId(r.id);}}><span>{r.name}</span><small>{length(r.mm)}</small></button>)}</div></div>
  <p className="fine">Equal cube volume means equal modeled storage volume. The slider starts with the entire paper cube in view and ends with the entire DNA cube in view. Every panel and its 1.7 m person share the same linear scale; larger objects extend outside the view when zoomed.</p>
  <div className="scale-cards">
   <article className="scale-paper"><span className="scale-index">01 / PAPER</span><div className="volume-ratio"><strong>{ratioLabel(ratios.paper)}</strong><span>larger than DNA by modeled volume</span></div>{scene('paper')}<strong>{number(f.pages)}</strong><h3>printed pages</h3><p>{number(f.pages*.0001)} meters of stacked paper</p><small>Lossless text representation of file bytes. This is not a document’s normal print layout.</small></article>
   <article className="scale-disk"><span className="scale-index">02 / DRIVE CAPACITY</span><div className="volume-ratio"><strong>{ratioLabel(ratios.disk)}</strong><span>larger than DNA by modeled volume</span></div>{scene('disk')}<strong>{number(f.driveShare)}</strong><h3>20 TB drive equivalents</h3><p>{f.driveShare<1?`${number(f.driveShare*100)}% of one drive’s capacity`:`Capacity of ${number(f.driveShare)} full drives`}</p><small>Proportional share of a modeled drive’s volume, not a physically smaller drive. Rack, cooling and facility space are excluded.</small></article>
   <article className="scale-dna"><span className="scale-index">03 / DNA MATERIAL</span><div className="volume-ratio"><strong>1×</strong><span>the reference volume</span></div>{scene('dna')}<strong>{mass}</strong><h3>DNA material equivalent</h3><p>At a published 215 PB per gram benchmark</p><small>Research-density extrapolation, with assumed DNA material density of 1 g/cm³ to estimate volume. Not a measured lab sample.</small></article>
  </div>
  <div className="scale-takeaway"><span aria-hidden="true"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M6 4v9a3 3 0 0 0 3 3h10M15 12l4 4-4 4"/></svg></span><p><strong>A radically different storage medium.</strong> The selected file’s exact byte count drives these modeled volumes. They do not measure data-center space, energy, carbon or money saved.</p></div>
  {actual&&job?.dna_summary&&selected==='all'&&<p className="scale-actual">Measured in this archive: <strong>{job.dna_summary.total_letters.toLocaleString()} DNA letters</strong>, including recovery data and instructions. That overhead is not included in the research-density illustration above.</p>}
  <details><summary>See the assumptions behind the visuals</summary><p>One decimal TB is 10¹² bytes. Paper assumes Base64 (4 characters per 3 bytes), 2,000 characters per page, one-sided printing and 0.1 mm paper thickness. Digital storage assumes 20 TB per drive, modeled as 147 × 101.6 × 26.1 mm. Its allocated-volume equivalent scales with bytes; a real drive does not shrink with use. DNA volume assumes 1 g/cm³ material density, not measured solution concentration. Copy count applies equally to all three representations. The cubes show volume equivalents on an identical linear scale. They are not device shapes. Tiny quantities are left subpixel until you zoom in; crosshairs only mark their position.</p><p>DNA uses the 215 PB/g research benchmark reported by <a href="https://pubmed.ncbi.nlm.nih.gov/28254941/" target="_blank" rel="noreferrer">Erlich &amp; Zielinski, Science (2017)</a>. Packaging, carriers, synthesis yield, concentration, keys, redundancy and our manifest overhead are not modeled here. No physical DNA is produced.</p></details>
 </section>;
}
