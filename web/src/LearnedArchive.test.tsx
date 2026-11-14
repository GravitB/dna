import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { LearnedArchive } from './LearnedArchive';
import type { Archive } from './types';
afterEach(cleanup);
it('shows measured customer comparison and trial limits', () => {
  const job={policy:{target:1},candidate_comparison:{selected_id:'learned-id',trials:3,candidates:[
    {candidate_id:'standard-id',kind:'standard',cost:{write_usd:13,bases:1000,within_budget:true},screening:{scenarios:[{scenario:'vault_loss',n_recovered:2,n_trials:3}],passed:false}},
    {candidate_id:'learned-id',kind:'learned',cost:{write_usd:13,bases:1000,within_budget:true},screening:{scenarios:[{scenario:'vault_loss',n_recovered:3,n_trials:3}],passed:true}},
  ]}} as unknown as Archive;
  render(<LearnedArchive job={job} busy={false} action={vi.fn()} />);
  expect(screen.getByText('One location lost: 2/3')).toBeTruthy();
  expect(screen.getByText('One location lost: 3/3')).toBeTruthy();
  expect(screen.getByText(/A tie does not demonstrate an improvement/)).toBeTruthy();
  expect(screen.getByText(/3 final trials per scenario/)).toBeTruthy();
});
it('provides cancellation and explains interrupted learning', () => {
  const action=vi.fn();
  const {rerender}=render(<LearnedArchive job={{learning_state:{status:'running',message:'Training risk model'}} as Archive} busy={false} action={action} />);
  fireEvent.click(screen.getByRole('button',{name:'Cancel learning'}));
  expect(action).toHaveBeenCalledWith('/learning/cancel');
  rerender(<LearnedArchive job={{learning_state:{status:'interrupted',message:'Server restarted'}} as Archive} busy={false} action={action} />);
  expect(screen.queryByRole('button',{name:'Cancel learning'})).toBeNull();
  expect(screen.getByText(/Retry fresh learning/)).toBeTruthy();
});
