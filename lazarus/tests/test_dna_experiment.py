"""Pre-simulation FASTA -> damage simulation -> post-simulation FASTA -> independent decoding.

The decisive property (test E): decoding works from the exported reads, the portable recovery
bundle and a passphrase-protected key file alone, after the whole archive workspace is deleted.
"""

import hashlib
import json
import random
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lazarus import artifacts, clustering, decoder, dna, experiment, fasta, manifest, store, tools, vaults
from lazarus.api import app

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data" / "northstar_bio"
# Incompressible payload: tiny Fountain codes (a few chunks) have a large failure variance, which
# would make recoverable-damage tests depend on luck rather than on the pipeline.
TEXT = b"Lazarus test record. Final, immutable, must survive.\n" + random.Random(2026).randbytes(4000)
PASSPHRASE = "correct horse battery staple"
POLICY = {"retention_years": 50, "tech": "nanopore", "coverage": 10, "budget_usd": 50, "target": 1.0, "n_vaults": 3}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def ordered_job(files: dict[str, bytes], redundancy=1.0, n_vaults=3) -> str:
    jid = store.new_job("Experiment Co", {**POLICY, "n_vaults": n_vaults})
    for name, data in files.items():
        (store.job_dir(jid) / "uploads" / name).write_bytes(data)
    assert "error" not in tools.prepare_archive(job_id=jid, file_names=list(files))
    order = tools.place_synthesis_order(job_id=jid, redundancy=redundancy, coverage=10, n_vaults=n_vaults)
    assert "error" not in order, order
    return jid


def wait(client, url, done=("complete", "failed")):
    for _ in range(1200):
        doc = client.get(url).json()
        if doc.get("status") in done:
            return doc
        time.sleep(0.1)
    raise AssertionError(f"timeout waiting for {url}")


def simulate(client, jid, **settings):
    r = client.post(f"/api/jobs/{jid}/simulations", json=settings)
    assert r.status_code == 202, r.text
    sim = wait(client, f"/api/jobs/{jid}/simulations/{r.json()['id']}")
    assert sim["status"] == "complete", sim
    return sim


def keyfile(client, jid):
    r = client.post(f"/api/jobs/{jid}/recovery-keys", json={"passphrase": PASSPHRASE})
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers["content-disposition"]
    return r.content


def decode(client, files: dict, **form):
    payload = {k: (name, data) for k, (name, data) in files.items()}
    r = client.post("/api/decoder/sessions", data=form, files=payload)
    assert r.status_code == 202, r.text
    s = wait(client, f"/api/decoder/sessions/{r.json()['id']}")
    assert s["status"] == "complete", s
    report = client.get(f"/api/decoder/sessions/{s['id']}/files/report.json").json()
    return s, report


def recovered_bytes(client, session, name):
    entry = next(f for f in session["files"] if f["name"] == name)
    return client.get(f"/api/decoder/sessions/{session['id']}/files/recovered/{entry['index']}?download=1").content


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path / "jobs")
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------ phase 1: clean export


def test_clean_export_matches_vault_order_files(client):
    jid = ordered_job({"record.txt": TEXT})
    meta = client.get(f"/api/jobs/{jid}/dna").json()
    export = meta["export"]
    pre = client.get(f"/api/jobs/{jid}/files/{experiment.PRE_FASTA}?download=1")
    assert pre.status_code == 200 and "attachment" in pre.headers["content-disposition"]
    assert sha(pre.content) == export["files"][experiment.PRE_FASTA]["sha256"]
    # Byte-for-byte the concatenation of the approved vault files, with only a vault prefix added.
    expected = []
    for v in (1, 2, 3):
        text = (store.job_dir(jid) / f"vaults/vault-{v}/order.fasta").read_text()
        expected += [f">vault-{v}|{line[1:]}" if line.startswith(">") else line for line in text.splitlines()]
    assert pre.content.decode().splitlines() == expected
    c = export["counts"]
    assert c["sequences"] == len(expected) // 2 and c["strand_lengths"] == [110]
    assert c["total_nucleotides"] == 110 * c["sequences"]
    assert c["data_strands"] + 3 * c["manifest_strands_per_vault"] == c["sequences"]
    assert export["encoder_configuration"]["approved_settings"]["redundancy"] == 1.0
    # The ZIP contains every vault file and checksums that verify.
    import io, zipfile
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/jobs/{jid}/files/{experiment.CLEAN_ZIP}").content))
    for line in z.read("SHA256SUMS").decode().splitlines():
        digest, path = line.split("  ")
        arc = path.removeprefix("exports/")
        assert sha(z.read(arc)) == digest
    assert "vaults/vault-2/order.csv" in z.namelist()
    page = client.get(f"/api/jobs/{jid}/dna/sequences?limit=5&sample=pool-0000").json()
    assert page["sequences"][0]["sample"] == "pool-0000" and len(page["sequences"][0]["sequence"]) == 110
    # No key material in any public export.
    keys = [artifacts.get_key(jid, f["key_id"]) for f in store.load(jid)["sealed"].values()]
    for path in (experiment.PRE_FASTA, experiment.BUNDLE, experiment.EXPORT_META):
        body = artifacts.download(jid, path)
        for k in keys:
            assert k.hex().encode() not in body and k not in body


# ------------------------------------------------------------------ test A: perfect recovery


def test_a_clean_fasta_decodes_to_exact_bytes(client):
    jid = ordered_job({"record.txt": TEXT})
    clean = client.get(f"/api/jobs/{jid}/files/{experiment.PRE_FASTA}").content
    bundle = client.get(f"/api/jobs/{jid}/files/{experiment.BUNDLE}").content
    s, report = decode(client, {"fasta_file": ("pre_simulation.fasta", clean), "bundle_file": ("b.json", bundle),
                                "key_file": ("k.json", keyfile(client, jid))},
                       mode="independent_import", decoders="baseline", passphrase=PASSPHRASE)
    assert report["verdict"] == "PASS"
    assert report["recovery"]["manifest_recovered_from_dna"] is True
    assert recovered_bytes(client, s, "record.txt") == TEXT
    f = report["files"][0]
    assert f["expected_sha256"] == f["actual_sha256"] == sha(TEXT)


# ------------------------------------------------------------------ test B: recoverable damage


def test_b_moderate_damage_recovers_with_both_decoders(client):
    jid = ordered_job({"record.txt": TEXT})
    sim = simulate(client, jid, seed=11, coverage=10, storage_years=50)
    m = sim["metrics"]
    assert m["reads"] > m["clean_sequences"] and m["missing_sequences"] > 0  # real dropout happened
    rates = m["observed_error_rates_per_base"]
    assert 0.02 < rates["total"] < 0.12  # Nanopore-class errors, measured on the actual reads
    reads = client.get(f"/api/jobs/{jid}/files/{sim['files']['post_simulation_reads.fasta']['path']}").content
    fmt, records = fasta.parse(reads)
    assert fmt == "fasta" and len(records) == m["reads"]
    assert all(r.id.startswith("read_") and r.description.startswith("sample=") for r in records)
    assert "|" not in reads.decode().replace("sample=", "")  # no strand indices leak into decoder input
    s, report = decode(client, {"fasta_file": ("post_simulation_reads.fasta", reads)},
                       mode="existing_archive", archive_id=jid, decoders="both")
    assert report["verdict"] == "PASS", report["missing"]
    assert report["simulation"]["simulation_id"] == sim["id"]  # linked by checksum
    assert set(report["recovery"]["decoders"]) == {"baseline", "polish"}
    for d, v in report["recovery"]["decoders"].items():
        if v["available"]:
            assert v["verdict"] == "PASS", d
    assert recovered_bytes(client, s, "record.txt") == TEXT
    job = store.load(jid)
    assert job["decodes"][-1]["verdict"] == "PASS" and job["decodes"][-1]["simulation_id"] == sim["id"]
    html = client.get(f"/api/jobs/{jid}/files/decodes/{s['id']}/verification_report.html").text
    assert "PASS" in html and sim["id"] in html


# ------------------------------------------------------------------ test C: excessive damage


def test_c_excessive_damage_never_reports_pass(client):
    jid = ordered_job({"record.txt": TEXT}, redundancy=0.3)
    sim = simulate(client, jid, seed=5, coverage=3, dropout_rate=0.6, sub_rate=0.12, ins_rate=0.06, del_rate=0.06)
    assert sim["metrics"]["observed_dropout_rate"] > 0.5, sim["metrics"]
    s, report = decode(client, {}, mode="existing_archive", archive_id=jid, source="simulation",
                       simulation_id=sim["id"], decoders="baseline")
    assert report["verdict"] in ("FAIL", "PARTIAL", "INCOMPLETE"), report
    assert report["verdict"] != "PASS" and not s["files"], report
    assert client.get(f"/api/decoder/sessions/{s['id']}/files/recovered/0").status_code == 404


# ------------------------------------------------------------------ test D: keys


def test_d_missing_or_wrong_key_is_incomplete_or_fail(client):
    jid = ordered_job({"record.txt": TEXT})
    clean = artifacts.download(jid, experiment.PRE_FASTA)
    bundle = artifacts.download(jid, experiment.BUNDLE)
    s, report = decode(client, {"fasta_file": ("pre.fasta", clean), "bundle_file": ("b.json", bundle)},
                       mode="independent_import", decoders="baseline")
    assert report["verdict"] == "INCOMPLETE"
    assert any("key kms-" in m for m in report["missing"])
    assert report["files"][0]["status"] == "key_missing"
    assert report["files"][0]["decoders"]["baseline"]["ciphertext_recovered"] is True
    assert not s["files"]
    # Wrong passphrase is rejected up front, never silently ignored.
    r = client.post("/api/decoder/sessions", data={"mode": "independent_import", "passphrase": "wrong passphrase!"},
                    files={"fasta_file": ("pre.fasta", clean), "key_file": ("k.json", keyfile(client, jid))})
    assert r.status_code == 400 and "passphrase" in r.json()["detail"]
    # A key file with the right ids but wrong keys: explicit decryption failure.
    kid = next(iter(store.load(jid)["sealed"].values()))["key_id"]
    bad = decoder.make_keyfile(jid, {kid: bytes(32)}, PASSPHRASE)
    s, report = decode(client, {"fasta_file": ("pre.fasta", clean), "key_file": ("k.json", bad)},
                       mode="independent_import", decoders="baseline", passphrase=PASSPHRASE)
    assert report["verdict"] == "FAIL" and report["files"][0]["status"] == "decryption_failed"
    # Mode A without archive keys.
    s, report = decode(client, {}, mode="existing_archive", archive_id=jid, source="clean", key_mode="none",
                       decoders="baseline")
    assert report["verdict"] == "INCOMPLETE"


# ------------------------------------------------------------------ test E: independent recovery


@pytest.mark.parametrize("with_bundle", [True, False])
def test_e_independent_recovery_after_workspace_is_gone(client, tmp_path, monkeypatch, with_bundle):
    jid = ordered_job({"record.txt": TEXT})
    sim = simulate(client, jid, seed=23, coverage=10, storage_years=50)
    reads = artifacts.download(jid, sim["files"]["post_simulation_reads.fasta"]["path"])
    meta = artifacts.download(jid, sim["files"]["simulation_metadata.json"]["path"])
    bundle = artifacts.download(jid, experiment.BUNDLE)
    keys = keyfile(client, jid)
    # Fresh computer: the entire workspace (uploads, staging, KMS, vaults, exports, simulations) is gone.
    shutil.rmtree(store.JOBS_DIR)
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path / "fresh-computer")
    store._events.clear()

    def forbidden(*a, **k):
        raise AssertionError("independent decoding touched archive storage")

    monkeypatch.setattr(artifacts, "get_key", forbidden)
    monkeypatch.setattr(artifacts, "download", forbidden)
    monkeypatch.setattr(store, "load", forbidden)
    monkeypatch.setattr(tools, "_pool_bytes", forbidden)
    files = {"fasta_file": ("post_simulation_reads.fasta", reads), "key_file": ("keys.json", keys),
             "simulation_metadata": ("simulation_metadata.json", meta)}
    if with_bundle:
        files["bundle_file"] = ("recovery_bundle.json", bundle)
    s, report = decode(client, files, mode="independent_import", decoders="baseline", passphrase=PASSPHRASE)
    assert report["verdict"] == "PASS", (report["missing"], report["warnings"])
    assert report["recovery"]["manifest_source"] == "dna"
    assert report["simulation"]["simulation_id"] == sim["id"]
    assert report["archive"]["archive_id"] == jid
    assert recovered_bytes(client, s, "record.txt") == TEXT  # compared with bytes held by the test only


# ------------------------------------------------------------------ test F: reproducibility


def test_f_same_seed_same_reads_and_results(client):
    jid = ordered_job({"record.txt": TEXT})
    a = simulate(client, jid, seed=99, coverage=8, storage_years=20)
    b = simulate(client, jid, seed=99, coverage=8, storage_years=20)
    c = simulate(client, jid, seed=100, coverage=8, storage_years=20)
    assert a["id"] != b["id"]
    for name in ("post_simulation_reads.fasta", "ground_truth.tsv", "input_snapshot.fasta"):
        assert a["files"][name]["sha256"] == b["files"][name]["sha256"]
    assert a["files"]["post_simulation_reads.fasta"]["sha256"] != c["files"]["post_simulation_reads.fasta"]["sha256"]
    assert a["metrics"] == b["metrics"]
    ma = json.loads(artifacts.download(jid, a["files"]["simulation_metadata.json"]["path"]))
    mb = json.loads(artifacts.download(jid, b["files"]["simulation_metadata.json"]["path"]))
    for m in (ma, mb):
        for volatile in ("simulation_id", "created", "seconds"):
            m.pop(volatile)
    assert ma == mb
    # Earlier runs are immutable: their files are untouched by later runs.
    assert sha(artifacts.download(jid, a["files"]["post_simulation_reads.fasta"]["path"])) == a["files"]["post_simulation_reads.fasta"]["sha256"]


# ------------------------------------------------------------------ test G: multiple real files


def test_g_pdf_image_and_text_each_verified(client):
    files = {n: (SAMPLES / n).read_bytes() for n in ("trial_NB042_consent.pdf", "lab_notebook_p17.png", "weekly_standup_notes.txt")}
    jid = ordered_job(files)
    sim = simulate(client, jid, seed=3, coverage=10, storage_years=50)
    s, report = decode(client, {}, mode="existing_archive", archive_id=jid, source="simulation",
                       simulation_id=sim["id"], decoders="baseline")
    assert report["verdict"] == "PASS", report["missing"]
    assert {f["name"] for f in report["files"]} == set(files)
    for name, data in files.items():
        f = next(x for x in report["files"] if x["name"] == name)
        assert f["verified"] and f["actual_sha256"] == sha(data)
        assert recovered_bytes(client, s, name) == data
    assert recovered_bytes(client, s, "lab_notebook_p17.png")[:8] == b"\x89PNG\r\n\x1a\n"


# ------------------------------------------------------------------ test H: regressions and safety


def test_h_simulation_never_touches_archive_artifacts_and_drill_still_works(client):
    jid = ordered_job({"record.txt": TEXT})
    d = store.job_dir(jid)
    before = {p: sha(p.read_bytes()) for p in (d / "vaults").rglob("*") if p.is_file()}
    before.update({p: sha(p.read_bytes()) for p in (d / "exports").rglob("*")})
    simulate(client, jid, seed=1, lost_vaults=[2])
    after = {p: sha(p.read_bytes()) for p in before}
    assert before == after
    tools.destroy_primary(job_id=jid)
    r = tools.recover_archive(job_id=jid)
    if not r["all_verified"]:
        r = tools.recover_archive(job_id=jid, attempt=1, coverage=15)
    assert r["all_verified"]


def test_h_lost_vault_reads_are_really_missing(client):
    jid = ordered_job({"record.txt": TEXT})
    sim = simulate(client, jid, seed=4, lost_vaults=[1])
    rows = artifacts.download(jid, sim["files"]["ground_truth.tsv"]["path"]).decode().splitlines()[1:]
    assert rows and not any(r.split("\t")[1].startswith("vault-1|") for r in rows)
    assert sim["metrics"]["missing_from_lost_vaults"] > 0


def test_h_validation_and_paths(client):
    jid = ordered_job({"record.txt": TEXT})
    for body in ({"coverage": 0}, {"coverage": "x"}, {"tech": "sanger"}, {"lost_vaults": [9]}, {"sub_rate": 0.9}):
        assert client.post(f"/api/jobs/{jid}/simulations", json=body).status_code == 400
    bad = client.post("/api/decoder/sessions", data={"mode": "independent_import"},
                      files={"fasta_file": ("x.fasta", b">r1\nACGTNNXX\n")})
    assert bad.status_code == 400 and "Line 2" in bad.json()["detail"]
    assert client.post(f"/api/jobs/{jid}/recovery-keys", json={"passphrase": "short"}).status_code == 400
    from lazarus import persistence
    for path in ("simulations/../kms/x", "exports/../kms/a.key", "kms/x.key", "decodes\\x", "simulations//x"):
        with pytest.raises(ValueError):
            persistence.valid_path(path)
    assert client.get(f"/api/jobs/{jid}/files/simulations/sim-x/ground_truth.tsv").status_code == 404
    assert client.get(f"/api/jobs/{jid}/files/kms/x.key").status_code == 404
    for sid in ("dec-bad", "..%2F..%2Fetc"):
        assert client.get(f"/api/decoder/sessions/{sid}").status_code == 404
    with pytest.raises(FileNotFoundError):
        decoder.session_dir("../../etc")
    assert decoder.safe_name("../../evil\\x.png") == "x.png"
    events = json.dumps(store.events_since(jid, 0, 0))
    assert PASSPHRASE not in events and "kms" not in json.dumps(store.load(jid).get("simulations"))


def test_fasta_parser_rejects_bad_input_and_reads_fastq():
    for text, msg in ((">a\n", "no sequence"), ("ACGT\n", "header"), (">a\nACGU\n", "invalid character"),
                      (">\nACGT\n", "empty FASTA header")):
        with pytest.raises(fasta.FastaError, match=msg):
            fasta.parse(text)
    fmt, recs = fasta.parse("@r1 sample=pool-0000\nacgt\n+\nIIII\n")
    assert fmt == "fastq" and recs[0].sequence == "ACGT" and recs[0].sample == "pool-0000"
    assert fasta.sample_of("vault-2|MANIFEST|7") == "MANIFEST" and fasta.sample_of("read_1") is None


def test_clustering_recovers_strand_groups_without_labels():
    data = random.Random(1).randbytes(6000)
    enc = dna.encode_bytes(data, dna.settings_from_dict({"redundancy": 1.0}))
    clusters = dna.sequence(enc.strands, dna.make_profile("nanopore", 10, 8), 77)
    truth = {}
    for i, c in enumerate(clusters):
        for r in c:
            truth.setdefault(r, i)
    reads = [r for c in clusters for r in c]
    random.Random(0).shuffle(reads)
    found, stats = clustering.cluster_reads(reads, 110)
    pure = sum(len({truth[r] for r in c}) == 1 for c in found)
    assert pure / len(found) > 0.99
    assert abs(len(found) - sum(1 for c in clusters if c)) <= 0.02 * len(found)
    # As good as clustering with the simulator's hidden labels.
    blind = set(dna.decode_clusters(found, 110, "baseline")) & set(enc.strands)
    oracle = set(dna.decode_clusters([c for c in clusters if c], 110, "baseline")) & set(enc.strands)
    assert len(blind) >= 0.99 * len(oracle)
    assert dna.recover_bytes(list(blind), enc.meta) == data


def test_manifest_records_archive_id(client):
    jid = ordered_job({"record.txt": TEXT})
    bundle = json.loads(artifacts.download(jid, experiment.BUNDLE))
    assert bundle["manifest"]["archive_id"] == jid and bundle["keys_included"] is False
    assert bundle["manifest_sha256"] == sha(manifest.pack(bundle["manifest"]))
