import type { Archive } from './types';

export type Trial = { scenario: string; n_recovered: number; n_trials: number; passed?: boolean; recovery_rate: number };
export type Comparison = { selected_id: string | null; trials: number; screening_trials?: number; safety_margin?: boolean; conditions: string; candidates: {
  candidate_id: string; kind: string; redundancy?: number; coverage?: number; cost: { write_usd: number; read_usd?: number; bases: number; within_budget: boolean };
  screening: { scenarios: Trial[]; passed: boolean } | null;
}[] };

const scenarioName = (key: string) => ({normal: 'Normal reading', simulator_b: 'Different reader', low_coverage: 'Fewer reads', decay_x2: 'Twice the aging period', vault_loss: 'One location lost'}[key] || key.replace(/_/g,' '));

export function LearnedArchive({ job, busy, action }: {job: Archive; busy: boolean; action: (path: string, body?: object) => void}) {
  const comparison = job.candidate_comparison;
  const learning = job.learning_state;
  const final = comparison?.selected_id ? job.candidates?.[comparison.selected_id]?.validation : undefined;
  if (!comparison && !learning) return null;
  return <section aria-label="Encoding evidence">
    <h2>Choosing your DNA design</h2>
    {learning && <div role="status"><p>{learning.message}</p><small>{learning.status === "not_requested" ? "Testing customer DNA; no fresh training requested." : `Learning: ${learning.status}.`} Erbgut trains sequence risk; the CNN reader stays fixed.</small>
      {learning.status === 'running' && <p><button disabled={busy} onClick={() => action('/learning/cancel')}>Cancel learning</button></p>}
      {['canceled','failed','interrupted'].includes(learning.status) && <p>Retry fresh learning or choose standard encoding in a revised archive. No learned design has been approved.</p>}
    </div>}
    {comparison && <>
      <p>These tests use your actual encrypted files. Selection uses training seeds; the selected design then faces a separate final test. {comparison.screening_trials || comparison.trials} selection trials and {comparison.trials} final trials per scenario are small, exploratory samples.</p>
      {comparison.safety_margin && <p>Reads and recovery data adjust automatically. Selection also tests a tougher shortage of reads (50% of the plan); the independent final test uses 60%. Reading costs may rise and are shown before approval.</p>}
      <div className="table-wrap"><table><thead><tr><th>Design</th><th>Modeled writing cost</th><th>Modeled recovery cost</th><th>DNA letters</th><th>Selection tests</th><th>Decision</th></tr></thead>
      <tbody>{comparison.candidates.map(c => <tr key={c.candidate_id}>
        <td>{c.kind === 'learned' ? 'Learned sequence selection' : 'Standard rules'}{c.redundancy != null && <small className="candidate-id">{Math.round(c.redundancy*100)}% extra recovery data</small>}{c.coverage != null && <small className="candidate-id">{c.coverage} reads per DNA piece</small>}<small className="candidate-id">{c.candidate_id.slice(0,12)}</small></td>
        <td>${c.cost.write_usd.toFixed(2)}</td><td>{c.cost.read_usd == null ? "Not recorded" : `$${c.cost.read_usd.toFixed(2)}`}</td><td>{c.cost.bases.toLocaleString()}</td>
        <td>{!c.cost.within_budget ? 'Over budget' : !c.screening ? 'Not tested' : <details><summary>{c.screening.scenarios.filter(r => r.recovery_rate >= job.policy.target).length}/{c.screening.scenarios.length} scenarios passed</summary>{c.screening.scenarios.map(r => <div key={r.scenario}>{scenarioName(r.scenario)}: {r.n_recovered}/{r.n_trials}</div>)}</details>}</td>
        <td>{comparison.selected_id === c.candidate_id ? final?.state === 'completed' ? final.passed ? 'Passed final validation' : 'Failed final validation' : 'Selected for final validation' : 'Comparison only'}</td>
      </tr>)}</tbody></table></div>
      <p>At each reading plan, standard and compatible learned designs use matched rules, redundancy, simulated conditions and seeds. Higher read counts use standard rules when no compatible learned model is available. A tie does not demonstrate an improvement. Learning uses Erbgut’s research implementation.</p>
      {final?.state === 'completed' && <div><h3>Independent final tests</h3><p>{final.passed ? 'The frozen selected design passed the policy target in this small sample.' : 'This design failed final validation and cannot be approved. Create a revised archive.'}</p>
        {final.scenarios.map(r => <p key={r.scenario}>{scenarioName(r.scenario)}: {r.n_recovered}/{r.n_trials} exact archive recoveries</p>)}</div>}
      {final?.state === 'running' && <p>Final validation has started. If the server interrupts it, create a revised archive; final trials cannot be re-rolled.</p>}
      {comparison.selected_id && <p>Frozen candidate: <code className="candidate-id">{comparison.selected_id}</code>. Approval writes these exact tested sequences.</p>}
      {!comparison.selected_id && <p className="error">Neither design met the target within budget. Create a revised archive with more reads or a larger modeled budget.</p>}
    </>}
  </section>;
}
