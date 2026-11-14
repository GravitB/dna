"""Real local acceptance run on bundled public samples; no LLM API calls.

cd lazarus && .venv/bin/python ../scripts/verify_learned_archive.py --encoding fresh
Results vary with encryption and simulations. Failed final evidence is never re-rolled.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lazarus'))
from lazarus import candidates, store, tools


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--encoding', choices=['fresh', 'evaluated', 'standard'], default='standard')
    parser.add_argument('--sample', choices=['picture_demo.png', 'lab_notebook_p17.png'], default='picture_demo.png')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    data = (root / 'sample_data/northstar_bio' / args.sample).read_bytes()
    policy = dict(tech='nanopore', retention_years=50, coverage=16, n_vaults=3, budget_usd=50, target=1., notes='Public bundled sample verification')
    jid = store.new_job('Learned archive verification', policy)
    store.update(jid, lambda j: j.update(encoding_mode=args.encoding, selected_files=[args.sample], name='Scripted learned archive verification'))
    (store.job_dir(jid) / 'uploads' / args.sample).write_bytes(data)
    print(json.dumps({'job_id': jid, 'mode': 'scripted verification; no LLM', 'input_sha256': hashlib.sha256(data).hexdigest()}), flush=True)
    tools.inventory_files(job_id=jid)
    for step in (lambda: tools.prepare_archive(job_id=jid, file_names=[args.sample]), lambda: tools.prepare_learned_model(job_id=jid)):
        result = step()
        if result.get('error'):
            print(json.dumps(result)); return 1
    comparison = tools.compare_archive_candidates(job_id=jid)
    if comparison.get('error'):
        print(json.dumps(comparison)); return 1
    final = tools.validate_archive_candidate(job_id=jid)
    if final.get('error'):
        print(json.dumps(final)); return 1
    order = tools.place_synthesis_order(job_id=jid, **final['settings'])
    if order.get('error'):
        print(json.dumps(order)); return 1
    frozen = candidates.load(jid, order['candidate_id'])
    from lazarus import vaults
    merged = {}
    for v in range(1, 4):
        for pid, seqs in vaults.read_vault(store.job_dir(jid), v).items():
            merged.setdefault(pid, {}).update(seqs)
    assert all([merged[pid][i] for i in range(len(pool['strands']))] == pool['strands'] for pid, pool in frozen['pools'].items())
    result = tools.destroy_primary(job_id=jid)
    if result.get('error'):
        print(json.dumps(result)); return 1
    drill = tools.recover_archive(job_id=jid)
    restored = store.job_dir(jid) / 'restored' / args.sample
    verified = drill['all_verified'] and restored.read_bytes() == data
    tools.write_certificate(job_id=jid, summary='Scripted acceptance check: real codec computation, exact frozen FASTA identity, deleted job working copies and hash-checked recovery. Exploratory simulation, not an LLM run.')
    print(json.dumps({'job_id': jid, 'candidate_id': order['candidate_id'], 'verified': verified, 'dna_summary': store.load(jid)['dna_summary'], 'validation': final['validation']}))
    return 0 if verified else 1


if __name__ == '__main__':
    raise SystemExit(main())
