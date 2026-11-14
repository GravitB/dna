import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {FilePreview, DnaStory} from './experience';
import type {Archive} from './types';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});

describe('file-to-DNA evidence',()=>{
  it('cleans up browser previews and does not inline SVG or HTML',async()=>{
    const create=vi.fn(()=> 'blob:picture');const revoke=vi.fn();
    vi.stubGlobal('URL',{createObjectURL:create,revokeObjectURL:revoke});
    const file=new File(['image'],'photo.png',{type:'image/png'});
    const view=render(<FilePreview file={file} name={file.name}/>);
    await waitFor(()=>expect(screen.getByRole('img').getAttribute('src')).toBe('blob:picture'));
    view.rerender(<FilePreview file={new File(['<svg/>'],'unsafe.svg')} name="unsafe.svg"/>);
    expect(screen.queryByRole('img')).toBeNull();expect(revoke).toHaveBeenCalledWith('blob:picture');
    view.rerender(<FilePreview name="unsafe.html" src="/unsafe.html"/>);
    expect(screen.queryByRole('link')).toBeNull();expect(screen.queryByRole('img')).toBeNull();
  });
  it('reports unavailable previews instead of leaving a broken image',()=>{
    render(<FilePreview name="missing.png" src="/missing.png"/>);
    fireEvent.error(screen.getByRole('img'));
    expect(screen.getByLabelText('Preview unavailable')).toBeTruthy();
  });
  it('shows measured counts and actual strand while preserving encoded download paths',()=>{
    const job={originals_available:false,order:{order_files:['vaults/vault-1/order.fasta']},dna_summary:{total_letters:330,data_letters:220,manifest_letters:110,data_strands:2,manifest_strands:1,example:'ACGT'}} as Archive;
    render(<DnaStory job={job} id="demo"/>);
    expect(screen.getByText('330')).toBeTruthy();expect(screen.getByText('ACGT')).toBeTruthy();
    expect(screen.getByText(/Working originals have been removed/)).toBeTruthy();
    expect(screen.getByRole('link',{name:/DNA sequences/}).getAttribute('href')).toBe('/api/jobs/demo/files/vaults/vault-1/order.fasta');
  });
});
