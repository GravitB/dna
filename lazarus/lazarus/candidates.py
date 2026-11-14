"""Content-addressed, frozen DNA candidates shared by validation and archive writing."""
# HANDOFF: See ../../CONTINUE_HERE.md. Candidate approval/order/UI integration is unfinished.
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
        from dnacodec.encoder import encode
        encoded = encode(data, settings, scorer=scorer)
        pools[pid] = {"strands": encoded.strands, "meta": dna.meta_to_dict(encoded.meta),
                      "payload_sha256": hashlib.sha256(data).hexdigest()}
    body = {"version": 1, "settings": asdict(settings), "model": model_ref,
            "files": {name: {"sha256": f["sha256"], "nonce": f["nonce"]}
                      for name, f in sorted(job["sealed"].items())},
            "policy": job["policy"], "pools": pools}
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
    files = {name: {"sha256": f["sha256"], "nonce": f["nonce"]}
             for name, f in job["sealed"].items()}
    if candidate["files"] != files or candidate["policy"] != job["policy"]:
        raise ValueError("Candidate no longer matches archive inputs")
    return candidate


def validate(job_id, candidate_id, trials=4):
    """Exercise frozen emitted strands; hold-out seeds are reserved for this final check."""
    from dnacodec.seeds import heldout_seeds
    from dnacodec import simulator, simulator_b
    from dataclasses import replace
    candidate = load(job_id, candidate_id)
    policy = candidate['policy']
    if not isinstance(trials, int) or not 1 <= trials <= 300:
        raise ValueError('trials must be 1–300')
    profile = dna.make_profile(policy['tech'], policy['retention_years'], policy['coverage'])
    seeds = list(heldout_seeds(trials))
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
            successes += bool(ok)
        rows.append({'scenario': scenario, 'n_trials': trials, 'n_recovered': successes,
                     'recovery_rate': successes / trials})
    report = {'candidate_id': candidate_id, 'tested_at': store.now(), 'exploratory': trials < 300,
              'scenarios': rows, 'passed': all(r['recovery_rate'] >= policy['target'] for r in rows)}
    artifacts.publish(job_id, f"candidate-evidence/{candidate_id}/{hashlib.sha256(_canonical(report)).hexdigest()}.json", _canonical(report))
    store.update(job_id, lambda j: j['candidates'][candidate_id].update(validation=report))
    return report
