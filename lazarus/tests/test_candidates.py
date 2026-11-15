import hashlib
import numpy as np
import pytest
from lazarus import candidates, dna, store


def prepared(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'JOBS_DIR', tmp_path)
    jid = store.new_job('Candidate test', {'tech': 'nanopore'})
    payload = b'customer ciphertext' * 20
    (store.job_dir(jid) / 'staging/pool-0000.bin').write_bytes(payload)
    store.update(jid, lambda j: j.update(pools={'pool-0000': {}},
        sealed={'file.txt': {'sha256': hashlib.sha256(payload).hexdigest(), 'nonce': 'nonce'}}))
    return jid, payload


def test_frozen_learned_candidate_roundtrip(monkeypatch, tmp_path):
    jid, payload = prepared(monkeypatch, tmp_path)
    calls = []
    def scorer(strands):
        calls.append(len(strands))
        return np.array([s.count('A') / len(s) for s in strands])
    settings = dna.EncoderSettings(redundancy=1.0, constrain_seed=False, seed_bases=12)
    summary = candidates.create(jid, settings, scorer, {'sha256': 'model-test'})
    frozen = candidates.load(jid, summary['id'])
    pool = frozen['pools']['pool-0000']
    assert calls
    assert dna.meta_from_dict(pool['meta']).settings == settings
    assert dna.recover_bytes(pool['strands'], dna.meta_from_dict(pool['meta'])) == payload
    path = store.job_dir(jid) / summary['path']
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='checksum'):
        candidates.load(jid, summary['id'])


def test_candidate_rejects_changed_inputs(monkeypatch, tmp_path):
    jid, _ = prepared(monkeypatch, tmp_path)
    summary = candidates.create(jid, dna.EncoderSettings(redundancy=1.0))
    store.update(jid, lambda j: j['policy'].update(tech='illumina'))
    with pytest.raises(ValueError, match='inputs'):
        candidates.load(jid, summary['id'])


def test_manifest_check_pools_every_surviving_location_copy():
    """Each location stores its own manifest copy; selection must read them like the recovery drill
    does (pool decoded strands until the manifest decodes), not judge the archive on one copy."""
    from lazarus import candidates, manifest
    man = {"format": "lazarus-manifest-v1", "pools": {"pool-0000": {"n": 1}}, "files": {"a": {"sha256": "x" * 64}}}
    strands = manifest.encode_manifest(man)

    class ThirdPerCopy:  # copy k only yields every third strand, starting at k; error-free reads
        @staticmethod
        def simulate(s, profile, seed):
            k = (seed - 100 - 17) // 7919
            return [[x] if i % 3 == k else [] for i, x in enumerate(s)]

    assert not candidates.manifest_recovered(strands, man, ThirdPerCopy, None, 100, 1)
    assert candidates.manifest_recovered(strands, man, ThirdPerCopy, None, 100, 3)
    assert candidates.surviving_copies(3, "normal") == 3
    assert candidates.surviving_copies(3, "vault_loss") == 2
    assert candidates.surviving_copies(1, "vault_loss") == 1
