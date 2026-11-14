import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import StorageScale,{fitScales,WORLD_BYTES} from './StorageScale';
import {SCALE_REFERENCES,pickReference,referencePosition} from './scaleReferences';
afterEach(cleanup);
it('keeps reference stops within the requested paper-to-DNA zoom bounds',()=>{
 for(const bytes of [1,25144,1e12,WORLD_BYTES]) {
  const fits=fitScales(bytes,1);
  for(const ref of SCALE_REFERENCES){
   const position=referencePosition(ref.mm,fits.paper,fits.dna);
   if(position===null) continue;
   expect(position).toBeGreaterThanOrEqual(0);expect(position).toBeLessThanOrEqual(100);
   const ppm=Math.pow(10,Math.log10(fits.paper)+(Math.log10(fits.dna)-Math.log10(fits.paper))*position/100);
   expect(ref.mm*ppm).toBeGreaterThanOrEqual(.999);expect(ref.mm*ppm).toBeLessThanOrEqual(100.001);
  }
 }
});
it('chooses the same visible reference for panels at the same camera scale',()=>{
 for(const ppm of [.000001,.001,1,1000,100000]) {
  const r=pickReference(ppm);
  expect(r.mm*ppm).toBeGreaterThanOrEqual(1);
  expect(r.mm*ppm).toBeLessThanOrEqual(215);
 }
 render(<StorageScale/>);
 const labels=screen.getAllByText(/^Reference:/).map(e=>e.textContent);
 expect(labels).toHaveLength(3);expect(new Set(labels).size).toBe(1);
 fireEvent.click(screen.getByRole('button',{name:/Grain of sand/}));
 expect(screen.getAllByText(/^Reference: Grain of sand/)).toHaveLength(3);
 expect((screen.getByRole('slider') as HTMLInputElement).valueAsNumber).toBeGreaterThan(0);
});
it('keeps an explicitly chosen endpoint reference instead of silently replacing it',()=>{
 const {container}=render(<StorageScale/>);
 const cell=screen.getByRole('button',{name:/^Cell/});
 fireEvent.click(cell);
 expect(cell.getAttribute('aria-pressed')).toBe('true');
 expect(screen.getAllByText(/^Reference: Cell/)).toHaveLength(3);
 expect((screen.getByRole('slider') as HTMLInputElement).valueAsNumber).toBe(100);
 const refs=Array.from(container.querySelectorAll('.object-reference'));
 expect(refs).toHaveLength(3);
 for(const ref of refs) expect(Number(ref.getAttribute('data-reference-height'))).toBeLessThanOrEqual(100);
 fireEvent.keyDown(screen.getByRole('slider'),{key:'ArrowLeft'});
 fireEvent.change(screen.getByRole('slider'),{target:{value:'95'}});
 expect(cell.getAttribute('aria-pressed')).toBe('false');
});
