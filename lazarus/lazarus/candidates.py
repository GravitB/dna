"""Content-addressed, frozen DNA candidates shared by validation and archive writing."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from . import artifacts, dna, store


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def create(job_id, settings, scorer=None, model_ref=None):
    """Encode selected encrypted pools once and persist an immutable candidate."""
    if scorer is not None and not model_ref:
        raise ValueError("Learned candidates require model provenance")
    job = store.load(job_id)
    if job.get("order") or not job["sealed"]:
        raise ValueError("Candidates require a prepared, uncommitted archive")
    pools = {}
    for pid in sorted(job["pools"]):
        data = (store.job_dir(job_id) / "staging" / f"{pid}.bin").read_bytes()
        from dna_codec.encoder import encode
        encoded = encode(data, settings, scorer=scorer)
        pools[pid] = {"strands": encoded.strands, "meta": dna.meta_to_dict(encoded.meta),
                      "payload_sha256": hashlib.sha256(data).hexdigest()}
    body = {"version": 1, "settings": asdict(settings), "model": model_ref,
            "archive_identity": {"company": job["company"], "created": job["created"]},
            "files": {name: f for name, f in sorted(job["sealed"].items())},
            "pool_offsets": {pid: p.get("offset") for pid, p in sorted(job["pools"].items())},
            "policy": job["policy"], "pools": pools,
            "decoder_sha256": hashlib.sha256(dna.POLISH_CHECKPOINT.read_bytes()).hexdigest()}
    data = _canonical(body)
    candidate_id = hashlib.sha256(data).hexdigest()
    path = f"candidates/{candidate_id}.json"
    artifacts.publish(job_id, path, data)
    summary = {"id": candidate_id, "path": path, "settings": asdict(settings),
               "model": model_ref, "created": store.now(), "state": "unvalidated"}
    store.update(job_id, lambda j: j.setdefault("candidates", {}).setdefault(candidate_id, summary))
    return summary


def load(job_id, candidate_id):
    """Verify content identity and that the candidate still belongs to the current files."""
    job = store.load(job_id)
    row = job.get("candidates", {}).get(candidate_id)
    if row is None:
        raise ValueError("Unknown codec candidate")
    data = artifacts.download(job_id, row["path"])
    if hashlib.sha256(data).hexdigest() != candidate_id:
        raise ValueError("Candidate checksum mismatch")
    candidate = json.loads(data)
    files = job["sealed"]
    if candidate.get("archive_identity") != {"company": job["company"], "created": job["created"]}:
        raise ValueError("Candidate no longer matches archive identity")
    offsets = {pid: p.get("offset") for pid, p in job["pools"].items()}
    if candidate.get("pool_offsets") != offsets or set(candidate['pools']) != set(job['pools']) or candidate["files"] != files or candidate["policy"] != job["policy"]:
        raise ValueError("Candidate no longer matches archive inputs")
    return candidate


def validate(job_id, candidate_id, trials=4, *, heldout=True):
    """Exercise frozen emitted strands; hold-out seeds are reserved for this final check."""
    from dna_codec.seeds import heldout_seeds, train_seed
    from dna_codec import simulator, simulator_b
    from dataclasses import replace
    candidate = load(job_id, candidate_id)
    policy = candidate['policy']
    existing = store.load(job_id)['candidates'][candidate_id].get('validation')
    if heldout and existing:
        if existing.get("state") == "running":
            raise ValueError("Final validation was interrupted or is already running. Do not re-roll final evidence; create a revised archive.")
        return existing  # Never re-roll final evidence to obtain a passing result.
    if not isinstance(trials, int) or not 1 <= trials <= 300:
        raise ValueError('trials must be 1–300')
    if heldout:
        def claim(j):
            if j['candidates'][candidate_id].get('validation'):
                raise ValueError('Final validation is already claimed; do not re-roll evidence')
            j['candidates'][candidate_id]['validation'] = {'state': 'running', 'candidate_id': candidate_id, 'started': store.now()}
        store.update(job_id, claim)
    profile = dna.make_profile(policy['tech'], policy['retention_years'], policy['coverage'])
    seeds = list(heldout_seeds(trials)) if heldout else [train_seed(45000 + i) for i in range(trials)]
    from . import manifest
    bootstrap_manifest = archive_manifest(store.load(job_id), candidate_id, candidate)
    bootstrap = manifest.encode_manifest(bootstrap_manifest)
    rows = []
    for scenario in ('normal', 'simulator_b', 'low_coverage', 'decay_x2', 'vault_loss'):
        channel = simulator_b if scenario == 'simulator_b' else simulator
        p = replace(profile, coverage_mean=profile.coverage_mean * 0.6) if scenario == 'low_coverage' else profile
        if scenario == 'decay_x2':
            p = replace(p, storage_years=p.storage_years * 2)
        successes = 0
        for seed in seeds:
            ok = True
            for pool in candidate['pools'].values():
                strands = pool['strands']
                clusters = channel.simulate(strands, p, seed)
                if scenario == 'vault_loss':
                    clusters = [[] if i % policy['n_vaults'] == 0 else c for i, c in enumerate(clusters)]
                meta = dna.meta_from_dict(pool['meta'])
                decoded = dna.decode_clusters(clusters, meta.settings.strand_length, 'polish')
                restored = dna.recover_bytes(decoded, meta)
                ok = ok and restored is not None and hashlib.sha256(restored).hexdigest() == pool['payload_sha256']
            ok = ok and manifest_recovered(bootstrap, bootstrap_manifest, channel, p, seed,
                                           surviving_copies(policy['n_vaults'], scenario))
            successes += bool(ok)
        rows.append({'scenario': scenario, 'n_trials': trials, 'n_recovered': successes,
                     'recovery_rate': successes / trials})
    report = {'state': 'completed', 'candidate_id': candidate_id, 'tested_at': store.now(), 'exploratory': trials < 300, 'seed_partition': 'heldout' if heldout else 'train',
              'scenarios': rows, 'passed': all(r['recovery_rate'] >= policy['target'] for r in rows)}
    evidence_path = f"candidate-evidence/{candidate_id}/{hashlib.sha256(_canonical(report)).hexdigest()}.json"
    artifacts.publish(job_id, evidence_path, _canonical(report))
    store.update(job_id, lambda j: j['candidates'][candidate_id].update(**{('validation' if heldout else 'screening'): report, ('validation_path' if heldout else 'screening_path'): evidence_path}))
    store.emit(job_id, 'candidate_result', 'adversary' if heldout else 'codec-engineer', report)
    return report


def surviving_copies(n_vaults, scenario):
    """Every location stores a full manifest copy; losing a location loses its copy."""
    return max(1, int(n_vaults) - (1 if scenario == 'vault_loss' else 0))


def manifest_recovered(bootstrap, expected, channel, profile, seed, copies):
    """Read the manifest the way the recovery drill does (tools.recovery_drill): sequence each
    surviving location's independent copy in turn and pool the decoded strands until the manifest
    decodes. Copy 0 keeps the original seed so single-location results are unchanged."""
    from . import manifest
    decoded = []
    for k in range(copies):
        clusters = channel.simulate(bootstrap, profile, seed + 17 + 7919 * k)
        decoded += dna.decode_clusters(clusters, manifest.BOOTSTRAP.strand_length, 'polish')
        if manifest.decode_manifest(decoded) == expected:
            return True
    return False


def proposal_args(job_id, candidate_id):
    c = load(job_id, candidate_id)
    s, p = c['settings'], c['policy']
    return dict(candidate_id=candidate_id, redundancy=s['redundancy'], strand_length=s['strand_length'],
                homopolymer_rule=s['max_homopolymer'] is not None, gc_rule=s['gc_min'] is not None and s['gc_max'] is not None,
                coverage=p['coverage'], n_vaults=p['n_vaults'], decoder='polish')


def archive_manifest(job, candidate_id, c):
    files = {n: {k: f[k] for k in ('key_id', 'nonce', 'sha256', 'bytes', 'pools', 'offset', 'cipher_bytes')}
             for n, f in job['sealed'].items()}
    model_ref = {k: c['model'][k] for k in ('id', 'job_id', 'source')} if c['model'] else None
    return {'format': 'lazarus-manifest-v1', 'company': job['company'], 'created': job['created'],
            'candidate_id': candidate_id, 'model': model_ref,
            'channel': {'tech': c['policy']['tech'], 'retention_years': c['policy']['retention_years'],
                        'planned_coverage': c['policy']['coverage'], 'recommended_decoder': 'polish'},
            'n_vaults': c['policy']['n_vaults'], 'crypto': 'zstd then AES-256-GCM, aad=lazarus-v1',
            'pools': {pid: {**p['meta'], 'offset': job['pools'][pid]['offset']} for pid, p in c['pools'].items()},
            'files': files, **_key_custody(job)}


def _key_custody(job):
    from .tools import key_custody
    return key_custody(job)


def cost(job_id, candidate_id):
    from . import manifest
    c = load(job_id, candidate_id)
    job = store.load(job_id)
    p = c['policy']
    bootstrap = manifest.encode_manifest(archive_manifest(job, candidate_id, c))
    bases = sum(len(s) for pool in c['pools'].values() for s in pool['strands']) + p['n_vaults'] * sum(map(len, bootstrap))
    count = sum(len(pool['strands']) for pool in c['pools'].values()) + p['n_vaults'] * len(bootstrap)
    profile = dna.make_profile(p['tech'], p['retention_years'], p['coverage'])
    write = bases * profile.synthesis_usd_per_base
    return {'candidate_id': candidate_id, 'bases': bases, 'write_usd': round(write, 2),
            'read_usd': round(count * p['coverage'] * profile.sequencing_usd_per_read, 2),
            'budget_usd': p['budget_usd'], 'within_budget': write <= p['budget_usd'], 'prices': 'modeled placeholders'}


def approval(job_id, args):
    cid = args['candidate_id']
    c = load(job_id, cid)
    expected = proposal_args(job_id, cid)
    job = store.load(job_id)
    matches = all(args.get(k, v) == v for k, v in expected.items()) and set(job['sealed']) == set(job.get('selected_files', job['sealed']))
    row = store.load(job_id)['candidates'][cid]
    report = row.get('validation', {})
    from . import model_registry
    decoder_matches = c.get('decoder_sha256') == model_registry.digest(dna.POLISH_CHECKPOINT.read_bytes())
    evidence_matches = False
    if row.get('validation_path'):
        evidence_matches = artifacts.download(job_id, row['validation_path']) == _canonical(report)
    costs = cost(job_id, cid)
    rows = [{'scenario': r['scenario'], 'label': r['scenario'].replace('_', ' '),
             'state': 'passed' if r['recovery_rate'] >= c['policy']['target'] else 'failed',
             'recovered': r['n_recovered'], 'trials': r['n_trials']} for r in report.get('scenarios', [])]
    return {**costs, 'evidence': rows, 'can_approve': bool(matches and decoder_matches and evidence_matches and report.get('passed')
            and report.get('candidate_id') == cid and len(rows) == 5 and costs['within_budget']),
            'exploratory': report.get('exploratory', True)}
