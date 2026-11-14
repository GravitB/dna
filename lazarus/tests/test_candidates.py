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
