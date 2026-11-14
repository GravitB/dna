import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import StorageScale,{footprint,largerThanDna,WORLD_BYTES,ratioLabel,fitScales,volumes,clipPolygon} from './StorageScale';
import type {Archive} from './types';
afterEach(cleanup);
it('compares equal information and copies using documented units',()=>{
 const f=footprint(1e12,1);
 expect(f.grams).toBeCloseTo(1e12/215e15,10);
 expect(f.driveShare).toBe(.05);
 expect(f.pages).toBe(666666667);
 expect(footprint(1e12,3).pages).toBe(f.pages*3);
 expect(footprint(-1,1).grams).toBe(0);
});
it('switches hypothetical scale without claiming measured savings',()=>{
 render(<StorageScale/>);
 fireEvent.click(screen.getByRole('button',{name:'1 PB'}));
 expect(screen.getByText('4.65 mg')).toBeTruthy();
 expect(screen.getByText(/not an uploaded archive/)).toBeTruthy();
 expect(screen.getByText(/do not measure data-center space/)).toBeTruthy();
 fireEvent.change(screen.getByLabelText('Copies of the information'),{target:{value:'3'}});
 expect(screen.getByText('13.95 mg')).toBeTruthy();
});
it('uses source bytes and separates actual DNA overhead from a research extrapolation',()=>{
 const job={sealed:{'a.png':{bytes:25144}},dna_summary:{total_letters:410190}} as unknown as Archive;
 render(<StorageScale job={job}/>);
 expect(screen.getByText('25.14 KB')).toBeTruthy();
 expect(screen.getByText('410,190 DNA letters')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'1 TB'}));
 expect(screen.getByText(/not an uploaded archive/)).toBeTruthy();
});

it('fits the selected file and bounds the slider at paper and DNA fits',()=>{
 const {container}=render(<StorageScale files={[{name:'small.bin',bytes:6000},{name:'all',bytes:48000}]}/>);
 const width=(kind:string)=>Number(container.querySelector(`.volume-${kind} .volume-solid rect`)!.getAttribute('width'));
 fireEvent.change(screen.getByLabelText('View uploaded item'),{target:{value:'file:small.bin'}});
 expect(screen.getByText(/6,000 exact source bytes/)).toBeTruthy();
 expect(width('paper')).toBeCloseTo(120,8);
 fireEvent.change(screen.getByLabelText('View uploaded item'),{target:{value:'file:all'}});
 expect(screen.getByText(/48,000 exact source bytes/)).toBeTruthy();
 expect(width('paper')).toBeCloseTo(120,8);
 const slider=screen.getByRole('slider',{name:'Shared magnification'}) as HTMLInputElement;
 expect(slider.min).toBe('0'); expect(slider.max).toBe('100');
 fireEvent.click(screen.getByRole('button',{name:'Fit DNA'}));
 expect(slider.value).toBe('100');
 expect(width('dna')).toBeCloseTo(120,8);
 fireEvent.click(screen.getByRole('button',{name:'Fit paper'}));
 expect(width('paper')).toBeCloseTo(120,8);
 expect(slider.value).toBe('0');
});
it('derives exact fit endpoints for tiny files and the world scenario',()=>{
 for(const bytes of [1,25144,1e12,WORLD_BYTES]) {
  const v=volumes(bytes,1), fits=fitScales(bytes,1);
  expect(Math.cbrt(v.paper)*fits.paper).toBeCloseTo(120,8);
  expect(Math.cbrt(v.dna)*fits.dna).toBeCloseTo(120,8);
  expect(fits.dna).toBeGreaterThan(fits.paper);
 }
});
it('shows the same physically scaled person in each comparison panel',()=>{
 const {container}=render(<StorageScale/>);
 const people=()=>Array.from(container.querySelectorAll('.person-reference')).map(g=>g.getAttribute('data-person-height'));
 expect(people()).toHaveLength(3);
 expect(new Set(people()).size).toBe(1);
 expect(screen.getAllByText(/1.7 m person/)).toHaveLength(4);
 const before=people()[0];
 fireEvent.click(screen.getByRole('button',{name:'Fit DNA'}));
 expect(people()[0]).not.toBe(before);
 expect(new Set(people()).size).toBe(1);
});

it('shows volume ratios rather than confusing them with edge-length ratios',()=>{
 const one=largerThanDna(1e12,1), three=largerThanDna(1e12,3);
 expect(one.disk).toBeCloseTo(4190443.74,2);
 expect(three.disk).toBeCloseTo(one.disk,6);
 expect(three.paper).toBeCloseTo(one.paper,0);
 expect(largerThanDna(0,1)).toEqual({paper:0,disk:0});
 render(<StorageScale/>);
 expect(screen.getByText(ratioLabel(one.disk))).toBeTruthy();
 expect(screen.getAllByText('larger than DNA by modeled volume')).toHaveLength(2);
});
it('uses a dated annual global-data estimate and keeps copies consistent',()=>{
 render(<StorageScale/>);
 fireEvent.click(screen.getByRole('button',{name:/World’s annual data/}));
 expect(WORLD_BYTES).toBe(218433e18);
 expect(screen.getByText(/not the total data stored worldwide/)).toBeTruthy();
 expect(screen.getByText('1.02 m³')).toBeTruthy();
 expect(screen.getByText('IDC source ↗').getAttribute('href')).toContain('idc.com');
 fireEvent.change(screen.getByLabelText('Copies of the information'),{target:{value:'3'}});
 expect(screen.getByText('3.05 m³')).toBeTruthy();
});

it('clips enormous off-screen faces before passing geometry to SVG',()=>{
 const polygon=clipPolygon([[-1e12,-1e12],[1e12,-1e12],[1e12,1e12],[-1e12,1e12]]);
 expect(polygon.length).toBeGreaterThan(2);
 for(const [x,y] of polygon){expect(x).toBeGreaterThanOrEqual(0);expect(x).toBeLessThanOrEqual(280);expect(y).toBeGreaterThanOrEqual(0);expect(y).toBeLessThanOrEqual(230);}
 expect(clipPolygon([[300,300],[400,300],[400,400]])).toEqual([]);
});
it('responds immediately to rapid slider reversals without leaving huge rendering primitives',()=>{
 const {container}=render(<StorageScale files={[{name:'tiny.txt',bytes:3}]}/>);
 const slider=screen.getByRole('slider',{name:'Shared magnification'}) as HTMLInputElement;
 for(const position of [100,0,99,1,50,100,0,100]){
  fireEvent.change(slider,{target:{value:String(position)}});
  expect(slider.value).toBe(String(position));
  for(const rect of Array.from(container.querySelectorAll('.volume-solid rect'))){
   expect(Number(rect.getAttribute('width'))).toBeLessThanOrEqual(280);
   expect(Number(rect.getAttribute('height'))).toBeLessThanOrEqual(230);
  }
  for(const polygon of Array.from(container.querySelectorAll('.volume-solid polygon'))){
   const points=polygon.getAttribute('points')!.split(' ').map(p=>p.split(',').map(Number));
   for(const [x,y] of points){expect(x).toBeGreaterThanOrEqual(-.000001);expect(x).toBeLessThanOrEqual(280.000001);expect(y).toBeGreaterThanOrEqual(-.000001);expect(y).toBeLessThanOrEqual(230.000001);}
  }
 }
 const dna=container.querySelector('.volume-dna .volume-solid rect')!;
 expect(Number(dna.getAttribute('width'))).toBeCloseTo(120,8);
 expect(screen.getAllByText(/taller than the visible area/)).toHaveLength(3);
});
it('changes source and copy count while zoomed without using the previous camera scale',()=>{
 const {container}=render(<StorageScale/>);
 fireEvent.click(screen.getByRole('button',{name:'Fit DNA'}));
 fireEvent.click(screen.getByRole('button',{name:/World’s annual data/}));
 expect((screen.getByRole('slider') as HTMLInputElement).value).toBe('0');
 expect(Number(container.querySelector('.scale-cards .volume-paper .volume-solid rect')!.getAttribute('width'))).toBeCloseTo(120,8);
 fireEvent.click(screen.getByRole('button',{name:'Fit DNA'}));
 fireEvent.change(screen.getByLabelText('Copies of the information'),{target:{value:'3'}});
 expect(Number(container.querySelector('.scale-cards .volume-dna .volume-solid rect')!.getAttribute('width'))).toBeCloseTo(120,8);
});
