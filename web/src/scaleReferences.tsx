export const SCALE_REFERENCES = [
  {id:'nano',name:'1 nm distance',mm:.000001,kind:'distance'},
  {id:'particle',name:'Particle',mm:.0001,kind:'particle'},
  {id:'cell',name:'Cell',mm:.01,kind:'cell'},
  {id:'hair',name:'Hair width',mm:.07,kind:'hair'},
  {id:'sand',name:'Grain of sand',mm:.5,kind:'sand'},
  {id:'coin',name:'Coin diameter',mm:25,kind:'coin'},
  {id:'phone',name:'Phone height',mm:150,kind:'phone'},
  {id:'person',name:'Person',mm:1700,kind:'person'},
  {id:'tree',name:'Tree height',mm:10000,kind:'tree'},
  {id:'building',name:'Building height',mm:100000,kind:'building'},
  {id:'mountain',name:'Mountain height',mm:1000000,kind:'mountain'},
  {id:'region',name:'10 km distance',mm:1e7,kind:'distance'},
  {id:'landscape',name:'100 km distance',mm:1e8,kind:'distance'},
] as const;
export type ScaleReference = typeof SCALE_REFERENCES[number];

export function referencePosition(mm:number,paperScale:number,dnaScale:number):number|null {
  const span=Math.log10(dnaScale)-Math.log10(paperScale);
  if(span<=0||!Number.isFinite(span)) return null;
  const position=(Math.log10(60/mm)-Math.log10(paperScale))/span*100;
  if(position>=0&&position<=100) return position;
  if(position<0&&mm*paperScale>=1&&mm*paperScale<=100) return 0;
  if(position>100&&mm*dnaScale>=1&&mm*dnaScale<=100) return 100;
  return null;
}
export function pickReference(pxPerMm:number):ScaleReference {
  const person=SCALE_REFERENCES.find(r=>r.id==='person')!;
  if(person.mm*pxPerMm>=20&&person.mm*pxPerMm<=215) return person;
  const visible=SCALE_REFERENCES.filter(r=>r.mm*pxPerMm>=1&&r.mm*pxPerMm<=100);
  const options=visible.length?visible:SCALE_REFERENCES;
  return options.reduce((best,r)=>Math.abs(Math.log10(r.mm*pxPerMm/60))<Math.abs(Math.log10(best.mm*pxPerMm/60))?r:best);
}
export function ReferenceGlyph({kind}:{kind:ScaleReference['kind']}) {
  switch(kind) {
    case 'distance': return <path d="M 0 0 V -1 M -.12 0 H .12 M -.12 -1 H .12" fill="none" stroke="currentColor" strokeWidth=".035"/>;
    case 'phone': return <g><rect x="-.25" y="-1" width=".5" height="1" rx=".06"/><rect x="-.2" y="-.89" width=".4" height=".73" rx=".02" fill="var(--surface)"/><circle cx="0" cy="-.08" r=".025" fill="var(--surface)"/></g>;
    case 'building': return <g><path d="M -.28 0 V -.92 H -.13 V -1 H .13 V -.92 H .28 V 0 Z"/>{[0,1,2,3,4].map(i=><g key={i} fill="var(--surface)"><rect x="-.17" y={-.82+i*.15} width=".11" height=".08"/><rect x=".06" y={-.82+i*.15} width=".11" height=".08"/></g>)}</g>;
    case 'tree': return <g><path d="M -.04 0 V -.43 H .04 V 0 Z"/><path d="M 0 -1 L -.3 -.64 H -.18 L -.4 -.31 H .4 L .18 -.64 H .3 Z"/></g>;
    case 'mountain': return <g><path d="M -.5 0 L 0 -1 L .5 0 Z"/><path d="M 0 -1 L -.13 -.74 L 0 -.8 L .11 -.75 Z" fill="var(--surface)"/></g>;
    case 'sand': return <path d="M -.33 -.86 L .17 -1 L .47 -.61 L .35 -.17 L -.05 0 L -.46 -.26 L -.49 -.61 Z"/>;
    case 'cell': return <g><circle cy="-.5" r=".5" opacity=".65"/><circle cx="-.06" cy="-.52" r=".17"/><circle cx=".26" cy="-.58" r=".045"/><circle cx="-.21" cy="-.25" r=".04"/></g>;
    case 'hair': return <g><circle cy="-.5" r=".5"/><circle cy="-.5" r=".32" fill="var(--surface)" opacity=".4"/></g>;
    case 'coin': return <g><circle cy="-.5" r=".5"/><circle cy="-.5" r=".37" fill="none" stroke="var(--surface)" strokeWidth=".025"/><path d="M 0 -.74 V -.26 M -.12 -.62 H .12 M -.12 -.4 H .12" fill="none" stroke="var(--surface)" strokeWidth=".035"/></g>;
    default: return <g><circle cy="-.5" r=".5" opacity=".65"/><circle cy="-.5" r=".17"/></g>;
  }
}
