import os
import shutil
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from lazarus import crypto, dna, manifest, store, tools, vaults

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data" / "northstar_bio"


def test_seal_roundtrip_and_tamper():
    key = crypto.new_key()
    nonce, ct = crypto.seal(b"hello" * 100, key)
    assert crypto.unseal(nonce, ct, key) == b"hello" * 100
    bad = bytearray(ct); bad[5] ^= 1
    with pytest.raises(InvalidTag):
        crypto.unseal(nonce, bytes(bad), key)


def test_manifest_bootstrap_without_metadata():
    man = {"format": "lazarus-manifest-v1", "pools": {"pool-0000": {"n": 1}}, "files": {"a": {"sha256": "x" * 64}}}
    strands = manifest.encode_manifest(man)
    prof = dna.make_profile("nanopore", 50, 10)
    decoded = dna.decode_clusters(dna.sequence(strands, prof, 7), 110, "baseline")
    assert manifest.decode_manifest(decoded) == man  # only the fixed BOOTSTRAP spec was needed


def test_corrupted_strand_never_gives_wrong_bytes():
    data = os.urandom(3000)
    enc = dna.encode_bytes(data, dna.settings_from_dict({"redundancy": 0.5}))
    strands = list(enc.strands)
    strands[3] = strands[3][:50] + ("A" if strands[3][50] != "A" else "C") + strands[3][51:]
    out = dna.recover_bytes(strands, enc.meta)
    assert out is None or out == data


def _job(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path)
    jid = store.new_job("T", {"retention_years": 50, "tech": "nanopore", "coverage": 10, "budget_usd": 50, "target": 1.0, "n_vaults": 3})
    for f in SAMPLES.iterdir():
        shutil.copy(f, store.job_dir(jid) / "uploads" / f.name)
    return jid


def test_order_destroy_and_recover_from_two_of_three_vaults(tmp_path, monkeypatch):
    jid = _job(tmp_path, monkeypatch)
    tools.prepare_archive(job_id=jid, file_names=["ledger_FY2026.csv", "trial_NB042_consent.pdf"])
    order = tools.place_synthesis_order(job_id=jid, redundancy=1.6, coverage=10, n_vaults=3)
    assert (store.job_dir(jid) / "vaults/vault-1/order.fasta").exists() and order["manifest_strands"] > 0
    tools.destroy_primary(job_id=jid)
    assert vaults.destroy_vault(store.job_dir(jid), 2)
    r = tools.recover_archive(job_id=jid)
    if not r["all_verified"]:  # re-sequence deeper, as the recovery agent is told to
        r = tools.recover_archive(job_id=jid, attempt=1, coverage=15)
    assert r["vaults_available"] == [1, 3]
    assert r["all_verified"], (r["pools"], r["files"])
    restored = store.job_dir(jid) / "restored" / "ledger_FY2026.csv"
    assert restored.read_bytes() == (SAMPLES / "ledger_FY2026.csv").read_bytes()


def test_failed_drill_supersedes_certificate(tmp_path, monkeypatch):
    jid = _job(tmp_path, monkeypatch)
    d = store.job_dir(jid)
    (d / 'certificate.html').write_text('previous success')
    (d / 'restored' / 'old.pdf').write_bytes(b'old')
    store.update(jid, lambda j: j.update(status='certified', certificate='certificate.html'))
    result = tools.recover_archive(job_id=jid)
    assert not result['all_verified']
    assert store.load(jid)['status'] == 'recovery_failed'
    assert len(store.load(jid)['drills']) == 1
    assert not (d / 'certificate.html').exists()
    assert not (d / 'restored' / 'old.pdf').exists()


def test_primary_requires_order(tmp_path, monkeypatch):
    jid = _job(tmp_path, monkeypatch)
    assert 'error' in tools.destroy_primary(job_id=jid)
    assert any((store.job_dir(jid) / 'uploads').iterdir())
