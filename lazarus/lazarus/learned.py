"""Cancelable learned encoding, matched customer trials and frozen approval candidates."""
from __future__ import annotations
import json
import subprocess
import sys
import threading
import time
import uuid
from . import artifacts, candidates, dna, model_registry, store

_lock = threading.Lock()
_active = {}


def cancel(job_id):
    with _lock:
        item = _active.get(job_id)
        if not item:
            raise ValueError('No learning experiment is running')
        item['cancel'].set()
        if item.get('process') and item['process'].poll() is None:
            item['process'].terminate()
    update(job_id, status='canceling', message='Stopping the learning worker. No design has been approved.')


def update(job_id, **state):
    store.update(job_id, lambda j: j.setdefault('learning_state', {'status': 'not_requested'}).update(state, updated=store.now()))
    store.emit(job_id, 'learning_progress', 'codec-researcher', state)


def train(job_id):
    with _lock:
        if job_id in _active:
            raise ValueError('Learning is already running')
        item = {'cancel': threading.Event()}
        _active[job_id] = item
    root = store.job_dir(job_id) / 'learning' / uuid.uuid4().hex
    root.mkdir(parents=True)
    request = root / 'request.json'
    policy = store.load(job_id)['policy']
    request.write_text(json.dumps({'profile': dna.profile_to_dict(dna.make_profile(policy['tech'], policy['retention_years'], policy['coverage']))}))
    update(job_id, status='running', started=store.now(), message='Starting fresh learning', experiment=root.name)
    try:
        with (root / 'worker.log').open('w') as log:
            proc = subprocess.Popen([sys.executable, '-m', 'lazarus.learned_worker', str(request.resolve()), str(root.resolve())], stdout=log, stderr=log)
            with _lock:
                item['process'] = proc
            deadline, last = time.monotonic() + 600, None
            while proc.poll() is None:
                if item['cancel'].is_set() or time.monotonic() >= deadline:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    break
                progress = root / 'progress.json'
                if progress.exists():
                    value = progress.read_text()
                    if value != last:
                        update(job_id, message=json.loads(value)['stage'])
                        last = value
                item['cancel'].wait(0.25)
        if item['cancel'].is_set():
            update(job_id, status='canceled', message='Learning canceled. Choose standard encoding or retry fresh learning.')
            return None
        if proc.returncode != 0 or not (root / 'report.json').exists():
            update(job_id, status='failed', message='Training failed or exceeded ten minutes. Inspect the worker log, retry, or use standard encoding.')
            return None
        import torch
        from dna_codec.risk import RiskModel
        payload = torch.load(root / 'risk.pt', map_location='cpu', weights_only=True)
        model = RiskModel._from_payload(payload, device='cpu')
        row = model_registry.register(job_id, model, json.loads((root / 'report.json').read_text()))
        update(job_id, status='completed', message='Model evaluated; customer archive tests are still required.', model_id=row['id'])
        return row
    except Exception:
        update(job_id, status='failed', message='Learning could not finish. Retry or use standard encoding.')
        raise
    finally:
        with _lock:
            _active.pop(job_id, None)
        for path in root.iterdir():
            if path.is_file():
                artifacts.publish(job_id, path.relative_to(store.job_dir(job_id)).as_posix(), path.read_bytes())


def compare(job_id, redundancy=0.8, trials=3):
    job = store.load(job_id)
    if job.get('order'):
        raise ValueError('This archive already has an approved order')
    if job.get('candidate_comparison'):
        return job['candidate_comparison']
    if redundancy not in (0.8, 1.2, 1.6, 2.0) or not isinstance(trials, int) or not 1 <= trials <= 20:
        raise ValueError('Use bounded redundancy 0.8, 1.2, 1.6 or 2.0 and 1–20 exploratory trials')
    mode = job.get('encoding_mode', 'standard')
    row = None
    if mode == 'fresh':
        row = job.get('prepared_model') or train(job_id)
        if row is None:
            return {'error': 'Fresh learning did not complete. Retry or explicitly choose standard encoding.'}
    elif mode == 'evaluated':
        row = model_registry.find(job['policy'])
        if row is None:
            return {'error': 'No evaluated model matches this reader, aging period and decoder. Choose fresh learning or standard encoding.'}
    model = model_registry.load(row, job['policy']) if row else None
    screened, winner = [], None
    # Revise using train seeds only. Each learned/standard pair has matched conditions.
    for red in (r for r in (0.8, 1.2, 1.6, 2.0) if r >= redundancy):
        settings = dna.EncoderSettings(redundancy=red)
        ids = [candidates.create(job_id, settings)['id']]
        if row:
            ids.append(candidates.create(job_id, settings, model, row)['id'])
        pair = []
        for cid in ids:
            kind = 'learned' if candidates.load(job_id, cid)['model'] else 'standard'
            update(job_id, message=f'Testing frozen {kind} customer DNA with {red:g} redundancy')
            costs = candidates.cost(job_id, cid)
            report = candidates.validate(job_id, cid, trials=trials, heldout=False) if costs['within_budget'] else None
            pair.append({'candidate_id': cid, 'kind': kind, 'redundancy': red, 'cost': costs, 'screening': report})
        screened.extend(pair)
        eligible = [r for r in pair if r['screening'] and r['screening']['passed']]
        if eligible:
            winner = min(eligible, key=lambda r: (r['cost']['bases'], r['kind'] != 'learned'))
            break
        if not any(r['cost']['within_budget'] for r in pair):
            break
        store.emit(job_id, 'message', 'codec-engineer', {'text': f'The {red:g} redundancy designs did not pass selection tests. Testing the next bounded design; final held-out seeds remain unused.'})
    result = {'candidates': screened, 'selected_id': winner['candidate_id'] if winner else None,
              'conditions': 'Matched ciphertext, redundancy, rules, decoder, channel and trial seeds; exploratory.',
              'trials': trials, 'selection_partition': 'train', 'model': model_registry.summary(row)}
    store.update(job_id, lambda j: j.update(candidate_comparison=result))
    store.emit(job_id, 'candidate_comparison', 'codec-engineer', result)
    return result


def finalize(job_id):
    result = store.load(job_id).get('candidate_comparison')
    if not result or not result.get('selected_id'):
        return {'error': 'No within-budget candidate passed selection trials. Start a revised archive with more reads or redundancy.'}
    cid = result['selected_id']
    report = candidates.validate(job_id, cid, trials=result['trials'])
    if not report['passed']:
        return {'error': 'Selected candidate failed final held-out trials. No order can be approved. Start a revised archive; this final test cannot be re-rolled.', 'validation': report}
    return {'settings': candidates.proposal_args(job_id, cid), 'validation': report, 'cost': candidates.cost(job_id, cid)}
