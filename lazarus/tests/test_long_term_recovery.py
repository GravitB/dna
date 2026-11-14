"""Organization master keys, Long-Term Recovery Packages and the offline decoder (tests A–I).

The decisive property (test C): a fresh process that has only the sequencing reads, the Recovery
Package and the organization's master key backup recovers byte-exact files after every server-side
trace of the archive (uploads, keys, job state, vaults, exports, the organization record) is gone.
"""

import csv
import gzip
import hashlib
import io
import json
import os
import random
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lazarus import artifacts, decoder, experiment, fasta, offline_decode, orgkeys, orgs, package_format, store, tools
from lazarus.api import app

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data" / "northstar_bio"
PASS_A = "hospital archive passphrase 2026"
PASS_B = "another org entirely, 1999!"
POLICY = {"retention_years": 50, "tech": "nanopore", "coverage": 10, "budget_usd": 50, "target": 1.0, "n_vaults": 3}


def blob(seed: int, n: int = 3000) -> bytes:
    """Incompressible record: keeps Fountain codes large enough that recovery is not a coin flip."""
    return f"record {seed}\n".encode() + random.Random(seed).randbytes(n)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path / "jobs")
    with TestClient(app) as c:
        yield c


def new_org(client, name="Mercy General Hospital"):
    r = client.post("/api/orgs", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["org"]["id"], r.json()["access_token"]


def backup(client, org_id, token, passphrase=PASS_A, scope="all"):
    r = client.post(f"/api/orgs/{org_id}/master-key/backup", headers={"X-Lazarus-Org-Token": token},
                    json={"passphrase": passphrase, "confirm_passphrase": passphrase, "acknowledge": True,
                          "scope": scope})
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers["content-disposition"]
    return r.content


def archive(files: dict[str, bytes], org_id: str | None = None, redundancy: float = 1.0) -> str:
    jid = store.new_job("Mercy General Hospital", POLICY)
    if org_id:
        store.update(jid, lambda j: j.update(org_id=org_id))
    for name, data in files.items():
        (store.job_dir(jid) / "uploads" / name).write_bytes(data)
    assert "error" not in tools.prepare_archive(job_id=jid, file_names=list(files))
    order = tools.place_synthesis_order(job_id=jid, redundancy=redundancy, coverage=10, n_vaults=3)
    assert "error" not in order, order
    return jid


def package(client, jid, token=None) -> bytes:
    h = {"X-Lazarus-Org-Token": token} if token else {}
    r = client.post(f"/api/jobs/{jid}/recovery-package", headers=h)
    assert r.status_code == 200, r.text
    r = client.get(f"/api/jobs/{jid}/recovery-package", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].startswith("attachment")
    return r.content


def wait(client, url):
    for _ in range(1500):
        doc = client.get(url).json()
        if doc.get("status") in ("complete", "failed"):
            return doc
        time.sleep(0.1)
    raise AssertionError(f"timeout waiting for {url}")


def simulate(client, jid, **settings):
    r = client.post(f"/api/jobs/{jid}/simulations", json=settings)
    assert r.status_code == 202, r.text
    sim = wait(client, f"/api/jobs/{jid}/simulations/{r.json()['id']}")
    assert sim["status"] == "complete", sim
    return sim


def sim_file(jid, sim, name):
    reads_path = sim["files"]["post_simulation_reads.fasta"]["path"]
    return artifacts.download(jid, reads_path.rsplit("/", 1)[0] + "/" + name)


def offline(tmp_path, monkeypatch, pkg: bytes, reads: list[str], *, master=None, keyfile=None, passphrase=PASS_A,
            extra=(), name="run"):
    """Run the offline CLI in-process (fast path). Test C runs it as a separate fresh process."""
    d = tmp_path / name
    d.mkdir()
    (d / "package.zip").write_bytes(pkg)
    args = ["--recovery-package", str(d / "package.zip"), "--output", str(d / "out"), "--passphrase-env", "LZ_PASS"]
    if master is not None:
        (d / "master.json").write_bytes(master)
        args += ["--master-key", str(d / "master.json")]
    if keyfile is not None:
        (d / "keys.json").write_bytes(keyfile)
        args += ["--keyfile", str(d / "keys.json")]
    for r in reads:
        args += ["--reads", r]
    monkeypatch.setenv("LZ_PASS", passphrase)
    code = offline_decode.main(args + list(extra))
    report = None
    if (d / "out" / "verification_report.json").exists():
        report = json.loads((d / "out" / "verification_report.json").read_text())
    return code, report, d / "out" / "recovered"


def write_clean(tmp_path, pkg: bytes, name: str) -> str:
    p = tmp_path / name
    p.write_bytes(package_format.read(pkg).files["synthesis/pre_simulation.fasta"])
    return str(p)


# ------------------------------------------------------------------ test A


def test_a_one_org_three_archives_one_master_key(client, tmp_path, monkeypatch):
    org_id, token = new_org(client)
    master = backup(client, org_id, token)
    picture = (SAMPLES / "picture_demo.png").read_bytes()
    contents = [{"discharge_summary.txt": blob(1)}, {"consent.pdf": (SAMPLES / "trial_NB042_consent.pdf").read_bytes(),
                                                      "scan.bin": blob(2)}, {"xray_note.txt": blob(3) + picture}]
    jids = [archive(c, org_id) for c in contents]
    docs = [store.load(j)["key_management"] for j in jids]
    assert {d["mode"] for d in docs} == {"organization"} and {d["org_id"] for d in docs} == {org_id}
    assert len({d["kek_fingerprint"] for d in docs}) == 1  # one master key protects all three
    deks = [orgs.unwrap_for_archive(d) for d in docs]
    all_keys = [k for d in deks for k in d.values()]
    assert len(all_keys) == 4 and len(set(all_keys)) == 4  # every file has its own data key
    for j in jids:  # no raw data key stored next to an organization archive
        assert not list((store.job_dir(j) / "kms").iterdir())
    kek = orgs.keyring(org_id)[1]
    for j, c in zip(jids, contents):
        pkg = package(client, j, token)
        body = b"".join(package_format.read(pkg).files.values())
        for k in [kek, *deks[jids.index(j)].values()]:
            for form in (k, k.hex().encode(), orgkeys.b64(k).encode()):
                assert form not in body  # neither the master key nor a data key appears unwrapped
        code, report, out = offline(tmp_path, monkeypatch, pkg, [write_clean(tmp_path, pkg, f"{j}.fasta")],
                                    master=master, extra=["--evidence", "clean"], name=j)
        assert code == 0 and report["verdict"] == "PASS", report
        for name, data in c.items():
            assert (out / name).read_bytes() == data
        assert report["recovery"]["key_source"].startswith("organization master key backup")


# ------------------------------------------------------------------ test B


def test_b_archive_created_after_backup_uses_same_master_key(client, tmp_path, monkeypatch):
    org_id, token = new_org(client)
    master = backup(client, org_id, token)  # exported once, before the archive exists
    later = archive({"2027_audit.txt": blob(7)}, org_id)
    pkg = package(client, later, token)
    assert package_format.read(pkg).encryption["kek_version"] == 1
    code, report, out = offline(tmp_path, monkeypatch, pkg, [write_clean(tmp_path, pkg, "later.fasta")], master=master)
    assert code == 0 and (out / "2027_audit.txt").read_bytes() == blob(7)


# ------------------------------------------------------------------ test C (mandatory)


def test_c_complete_server_independence_fresh_process(client, tmp_path):
    """The package is self-contained: the fresh process runs the decoder and the codec copied out of it."""
    org_id, token = new_org(client)
    master = backup(client, org_id, token)
    original = blob(11, 4000)
    jid = archive({"patient_record.txt": original}, org_id)
    sim = simulate(client, jid, seed=31, coverage=10, storage_years=50)
    reads = artifacts.download(jid, sim["files"]["post_simulation_reads.fasta"]["path"])
    pkg = package(client, jid, token)

    # 2076: Lazarus is gone. Only what the hospital kept leaves this point.
    kept = tmp_path / "hospital_safe"
    kept.mkdir()
    (kept / "reads.fasta").write_bytes(reads)
    (kept / package_format.FILENAME).write_bytes(pkg)
    (kept / "master.json").write_bytes(master)
    shutil.rmtree(store.JOBS_DIR)  # uploads, kms, job state, vaults, exports, simulations, _orgs: all gone
    assert not store.JOBS_DIR.exists()
    with zipfile.ZipFile(kept / package_format.FILENAME) as z:
        for n in z.namelist():
            if n.startswith("decoder/"):
                z.extract(n, tmp_path / "fresh")
    dec_dir = tmp_path / "fresh" / "decoder"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LAZARUS", "SUPABASE", "PYTHON"))}
    env.update(LZ_PASS=PASS_A, LAZARUS_JOBS_DIR=str(tmp_path / "must-not-exist"))
    out = tmp_path / "recovered_2076"
    proc = subprocess.run(
        [sys.executable, "-E", "-s", "-m", "lazarus.offline_decode",
         "--recovery-package", str(kept / package_format.FILENAME), "--reads", str(kept / "reads.fasta"),
         "--master-key", str(kept / "master.json"), "--passphrase-env", "LZ_PASS", "--evidence", "simulated",
         "--output", str(out)],
        cwd=dec_dir, env=env, capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((out / "verification_report.json").read_text())
    assert report["verdict"] == "PASS"
    assert (out / "recovered" / "patient_record.txt").read_bytes() == original
    assert sha((out / "recovered" / "patient_record.txt").read_bytes()) == sha(original)
    # The code that ran is the copy shipped in the package, not this repository.
    src = Path(report["archive"]["recovery_package"]["decoder_source"]).resolve()
    assert dec_dir.resolve() in src.parents
    codec = report["archive"]["recovery_package"]["codec"]
    assert codec["status"] == "matches pinned codec", codec
    assert dec_dir.resolve() in Path(codec["path"]).resolve().parents
    assert report["recovery"]["manifest_source"] == "dna"
    assert not (tmp_path / "must-not-exist").exists() and not store.JOBS_DIR.exists()


# ------------------------------------------------------------------ test D


def test_d_wrong_or_missing_master_key_never_decrypts(client, tmp_path, monkeypatch):
    org_a, tok_a = new_org(client, "Org A")
    org_b, tok_b = new_org(client, "Org B")
    master_a, master_b = backup(client, org_a, tok_a), backup(client, org_b, tok_b, PASS_B)
    jid = archive({"secret.txt": blob(21)}, org_a)
    pkg = package(client, jid, tok_a)
    reads = write_clean(tmp_path, pkg, "clean.fasta")
    code, report, _ = offline(tmp_path, monkeypatch, pkg, [reads], master=master_b, passphrase=PASS_B, name="b")
    assert code == 3 and report is None  # other organization's key: refused before decoding
    code, report, _ = offline(tmp_path, monkeypatch, pkg, [reads], master=master_a, passphrase="wrong passphrase!!",
                              name="pw")
    assert code == 3 and report is None
    # A master key with the right org id and version but different bytes fails the fingerprint check.
    impostor = orgkeys.make_backup(org_a, "Org A", {1: orgkeys.new_kek()}, PASS_A, "2026")
    code, report, _ = offline(tmp_path, monkeypatch, pkg, [reads], master=impostor, name="imp")
    assert code == 3 and report is None
    # Tampering with a wrapped key is caught by the package checksums and, beneath them, by GCM.
    doc = package_format.read(pkg).wrapped_keys
    k = next(iter(doc["keys"]))
    raw = bytearray(orgkeys.unb64(doc["keys"][k]["wrapped"]))
    raw[0] ^= 1
    doc["keys"][k]["wrapped"] = orgkeys.b64(bytes(raw))
    with pytest.raises(orgkeys.KeyError_):
        orgkeys.unwrap_keys(doc, orgs.keyring(org_a))
    # No key at all: the decoder stops; it never borrows a server-side key.
    code, report, _ = offline(tmp_path, monkeypatch, pkg, [reads], name="none")
    assert code != 0 and report is None
    # Web Mode B with the wrong backup is rejected too.
    r = client.post("/api/decoder/sessions", data={"mode": "independent_import", "passphrase": PASS_B},
                    files={"fasta_file": ("c.fasta", Path(reads).read_bytes()),
                           "package_file": ("p.zip", pkg), "master_key_file": ("m.json", master_b)})
    assert r.status_code == 400 and "organization" in r.json()["detail"]
    # Authorization: org B's token cannot touch org A's keys or packages.
    assert client.get(f"/api/orgs/{org_a}", headers={"X-Lazarus-Org-Token": tok_b}).status_code == 403
    assert client.get(f"/api/jobs/{jid}/recovery-package", headers={"X-Lazarus-Org-Token": tok_b}).status_code == 403
    assert client.get(f"/api/jobs/{jid}/recovery-package").status_code == 403
    path = store.load(jid)["recovery_package"]["path"]
    assert client.get(f"/api/jobs/{jid}/files/{path}").status_code == 404
    assert client.post(f"/api/jobs/{jid}/recovery-keys", json={"passphrase": PASS_A}).status_code == 403
    assert "wrapped_keys" not in client.get(f"/api/jobs/{jid}").json()["key_management"]


# ------------------------------------------------------------------ test E


def test_e_legacy_archive_keyfile_still_works_and_migrates(client, tmp_path, monkeypatch):
    legacy = archive({"ledger.csv": blob(31)})
    assert store.load(legacy).get("key_management") is None
    old_pkg = package(client, legacy)
    assert package_format.read(old_pkg).encryption["mode"] == "legacy-keyfile"
    keyfile = client.post(f"/api/jobs/{legacy}/recovery-keys", json={"passphrase": PASS_A}).content
    reads = write_clean(tmp_path, old_pkg, "legacy.fasta")
    code, report, out = offline(tmp_path, monkeypatch, old_pkg, [reads], keyfile=keyfile, name="legacy")
    assert code == 0 and (out / "ledger.csv").read_bytes() == blob(31)

    org_id, token = new_org(client)
    master = backup(client, org_id, token)
    assert legacy in [a["id"] for a in client.get(f"/api/orgs/{org_id}/legacy-archives",
                                                  headers={"X-Lazarus-Org-Token": token}).json()]
    legacy_keys = {f["key_id"]: artifacts.get_key(legacy, f["key_id"]) for f in store.load(legacy)["sealed"].values()}
    r = client.post(f"/api/orgs/{org_id}/migrate", headers={"X-Lazarus-Org-Token": token},
                    json={"archive_id": legacy})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["verification"] == "PASS" and res["legacy_keys_deleted"] is False
    km = store.load(legacy)["key_management"]
    assert km["mode"] == "organization" and km["migration_verified"]["verdict"] == "PASS"
    assert all((store.job_dir(legacy) / "kms" / f"{k}.key").exists() for k in legacy_keys)  # kept
    assert orgs.unwrap_for_archive(km) == legacy_keys  # same data keys: no DNA re-encoding
    new_pkg = client.get(f"/api/jobs/{legacy}/recovery-package", headers={"X-Lazarus-Org-Token": token}).content
    assert package_format.read(new_pkg).info["revision"] == 2
    code, report, out = offline(tmp_path, monkeypatch, new_pkg, [reads], master=master, name="migrated")
    assert code == 0 and (out / "ledger.csv").read_bytes() == blob(31)
    # The pre-migration package plus the old key file still work.
    code, _, _ = offline(tmp_path, monkeypatch, old_pkg, [reads], keyfile=keyfile, name="legacy-again")
    assert code == 0
    # A second migration is refused; the archive now needs the org token for key exports.
    assert client.post(f"/api/orgs/{org_id}/migrate", headers={"X-Lazarus-Org-Token": token},
                       json={"archive_id": legacy}).status_code == 409


# ------------------------------------------------------------------ test F


def test_f_rotation_rewraps_without_breaking_old_packages(client, tmp_path, monkeypatch):
    org_id, token = new_org(client)
    master_v1 = backup(client, org_id, token)
    jid = archive({"chart.txt": blob(41)}, org_id)
    pkg_v1 = package(client, jid, token)
    reads = write_clean(tmp_path, pkg_v1, "clean.fasta")
    deks_before = orgs.unwrap_for_archive(store.load(jid)["key_management"])

    r = client.post(f"/api/orgs/{org_id}/master-key/rotate", headers={"X-Lazarus-Org-Token": token},
                    json={"confirm": True})
    assert r.status_code == 200, r.text
    assert r.json()["to_version"] == 2 and r.json()["archives_rewrapped"] == [jid]
    km = store.load(jid)["key_management"]
    assert km["kek_version"] == 2 and orgs.unwrap_for_archive(km) == deks_before
    assert client.get(f"/api/orgs/{org_id}", headers={"X-Lazarus-Org-Token": token}).json()["backup_current"] is False
    pkg_v2 = client.get(f"/api/jobs/{jid}/recovery-package", headers={"X-Lazarus-Org-Token": token}).content
    assert package_format.read(pkg_v2).encryption["kek_version"] == 2

    # Old package + old backup: still recoverable.
    code, _, out = offline(tmp_path, monkeypatch, pkg_v1, [reads], master=master_v1, name="old")
    assert code == 0 and (out / "chart.txt").read_bytes() == blob(41)
    # New package + old backup: refused with an explanation, never a silent success.
    with pytest.raises(orgkeys.KeyError_, match="version 2"):
        orgkeys.unwrap_keys(package_format.read(pkg_v2).wrapped_keys, orgkeys.open_backup(master_v1, PASS_A)[1])
    code, report, _ = offline(tmp_path, monkeypatch, pkg_v2, [reads], master=master_v1, name="mismatch")
    assert code == 3 and report is None
    # A new backup of all versions opens both packages; a current-only backup opens only the new one.
    master_all = backup(client, org_id, token)
    master_cur = backup(client, org_id, token, scope="current")
    for n, (p, m, ok) in enumerate([(pkg_v2, master_all, 0), (pkg_v1, master_all, 0), (pkg_v2, master_cur, 0),
                                    (pkg_v1, master_cur, 3)]):
        code, _, _ = offline(tmp_path, monkeypatch, p, [reads], master=m, name=f"combo{n}")
        assert code == ok, n
    # The server still unwraps for drills and decodes after rotation.
    assert artifacts.get_key(jid, next(iter(deks_before))) == deks_before[next(iter(deks_before))]


# ------------------------------------------------------------------ test G


def test_g_real_image_through_simulated_damage(client, tmp_path, monkeypatch):
    org_id, token = new_org(client)
    master = backup(client, org_id, token)
    image = (SAMPLES / "lab_notebook_p17.png").read_bytes()
    assert image[:8] == b"\x89PNG\r\n\x1a\n"
    jid = archive({"lab_notebook_p17.png": image}, org_id)
    sim = simulate(client, jid, seed=77, coverage=12, storage_years=50)
    assert sim["metrics"]["missing_sequences"] > 0 and sim["metrics"]["observed_error_rates_per_base"]["total"] > 0.02
    reads = tmp_path / "damaged.fasta"
    reads.write_bytes(artifacts.download(jid, sim["files"]["post_simulation_reads.fasta"]["path"]))
    pkg = package(client, jid, token)
    shutil.rmtree(store.JOBS_DIR)
    code, report, out = offline(tmp_path, monkeypatch, pkg, [str(reads)], master=master,
                                extra=["--evidence", "simulated"])
    assert code == 0, report and report["missing"]
    got = (out / "lab_notebook_p17.png").read_bytes()
    assert got == image and sha(got) == report["files"][0]["expected_sha256"]
    assert report["evidence"]["level"] == "simulated_reads" and report["evidence"]["physical_dna_validated"] is False


# ------------------------------------------------------------------ test H


def _qual(n: int, rng: random.Random, low: bool = False) -> str:
    return "".join(chr(33 + (rng.randint(2, 6) if low else rng.randint(18, 38))) for _ in range(n))


def test_h_lab_style_fastq_with_sample_sheet(client, tmp_path, monkeypatch):
    """Demultiplexed per-sample FASTQ(.gz) with instrument-style headers, qualities, reverse-strand
    reads, N calls and junk reads. No Lazarus labels in any read. Simulated, not a lab validation."""
    org_id, token = new_org(client)
    master = backup(client, org_id, token)
    original = blob(51, 3500)
    jid = archive({"pathology.txt": original}, org_id)
    sim = simulate(client, jid, seed=91, coverage=10, storage_years=20)
    reads = {r.id: r.sequence for r in fasta.parse(artifacts.download(jid, sim["files"]["post_simulation_reads.fasta"]["path"]))[1]}
    truth = list(csv.DictReader(io.StringIO(sim_file(jid, sim, "ground_truth.tsv").decode()), delimiter="\t"))
    pkg = package(client, jid, token)
    sheet_rows = list(csv.DictReader(io.StringIO(package_format.read(pkg).files["sequencing/sample_sheet.csv"].decode())))

    # The ground truth stands in for the physical separation of tubes (one tube per sample), which is
    # what demultiplexing recovers in a real lab. It is used only to lay out the input files.
    rng = random.Random(4)
    per_sample: dict[str, list] = {}
    for t in truth:
        v = int(t["source_sequence_id"].split("|")[0].removeprefix("vault-"))
        sid = f"{jid}-V{v}-{t['sample']}"
        seq = reads[t["read_id"]]
        if rng.random() < 0.35:
            seq = decoder.revcomp(seq)
        per_sample.setdefault(sid, []).append(seq)
    lab = tmp_path / "lab_delivery"
    lab.mkdir()
    lines = ["file,sample_id"]
    n_junk = n_n = 0
    for i, row in enumerate(sheet_rows):
        sid = row["sample_id"]
        recs = []
        for j, seq in enumerate(per_sample.get(sid, [])):
            if rng.random() < 0.02:
                k = rng.randrange(len(seq))
                seq, n_n = seq[:k] + "N" + seq[k + 1:], n_n + 1
            recs.append((f"M04812:77:000000000-L4Z2R:1:{1101 + j % 7}:{rng.randint(1000, 29000)}:{rng.randint(1000, 29000)} 1:N:0:{i + 1}",
                         seq, _qual(len(seq), rng)))
        for _ in range(15):  # low-quality junk the facility did not filter
            junk = "".join(rng.choice("ACGT") for _ in range(110))
            recs.append((f"M04812:77:000000000-L4Z2R:1:2101:{rng.randint(1, 9999)}:1 1:N:0:{i + 1}", junk,
                         _qual(110, rng, low=True)))
            n_junk += 1
        rng.shuffle(recs)
        text = fasta.write_fastq(recs).encode()
        name = f"S{i + 1}_L001_R1_001.fastq" + (".gz" if i % 2 else "")
        (lab / name).write_bytes(gzip.compress(text) if i % 2 else text)
        lines.append(f"{name},{sid}")
    (lab / "samples.csv").write_text("\n".join(lines) + "\n")
    assert "sample=" not in "".join(p.read_bytes().decode("latin-1") for p in lab.glob("*.fastq"))

    code, report, out = offline(tmp_path, monkeypatch, pkg, [], master=master,
                                extra=["--reads-sheet", str(lab / "samples.csv")], name="lab")
    assert code == 0, (report or {}).get("missing")
    assert (out / "pathology.txt").read_bytes() == original
    inp = report["input"]
    assert inp["format"] == "fastq" and inp["unlabeled_records"] == 0
    assert inp["low_quality_reads_dropped"] >= n_junk * 0.9
    assert inp["ambiguous_base_reads_dropped"] == n_n > 0
    assert "filtering" in inp["quality_scores"] and "ignores per-base" in inp["quality_scores"]
    flipped = sum(p.get("reverse_complement_strands", 0) for p in report["recovery"]["decoders"]["baseline"]["pools"].values())
    assert flipped > 0
    assert report["evidence"] == {"level": "lab_format_reads", "text": decoder.EVIDENCE["lab_format_reads"],
                                  "physical_dna_validated": False}

    # Same reads pooled into one file with no sample information: an honest stop, not a guess.
    mixed = tmp_path / "mixed.fastq"
    mixed.write_text("".join(gzip.decompress(p.read_bytes()).decode() if p.suffix == ".gz" else p.read_text()
                             for p in sorted(lab.glob("*.fastq*"))))
    code, report, out = offline(tmp_path, monkeypatch, pkg, [str(mixed)], master=master, name="mixed")
    assert code == 1 and report["verdict"] == "INCOMPLETE"
    assert any("sample assignment" in m and "primers or barcodes" in m for m in report["missing"])
    assert not list(out.iterdir())


# ------------------------------------------------------------------ test I


def test_i_excessive_damage_is_an_honest_failure(client, tmp_path, monkeypatch):
    org_id, token = new_org(client)
    master = backup(client, org_id, token)
    jid = archive({"record.txt": blob(61)}, org_id, redundancy=0.3)
    sim = simulate(client, jid, seed=5, coverage=3, dropout_rate=0.6, sub_rate=0.12, ins_rate=0.06, del_rate=0.06)
    reads = tmp_path / "ruined.fasta"
    reads.write_bytes(artifacts.download(jid, sim["files"]["post_simulation_reads.fasta"]["path"]))
    pkg = package(client, jid, token)
    shutil.rmtree(store.JOBS_DIR)
    code, report, out = offline(tmp_path, monkeypatch, pkg, [str(reads)], master=master,
                                extra=["--evidence", "simulated"])
    assert code == 1 and report["verdict"] in ("FAIL", "INCOMPLETE", "PARTIAL")
    assert not any(f["verified"] for f in report["files"])
    assert not list(out.iterdir())  # nothing written that could be mistaken for a recovered file


# ------------------------------------------------------------------ package, onboarding, input safety


def test_package_contents_integrity_and_hostile_zips(client, tmp_path):
    org_id, token = new_org(client)
    backup(client, org_id, token)
    jid = archive({"note.txt": blob(71)}, org_id)
    pkg_bytes = package(client, jid, token)
    pkg = package_format.read(pkg_bytes)
    for required in ("README.md", "archive/manifest.json", "archive/files.json", "archive/layout.json",
                     "encoding/encoding.json", "encryption/encryption.json", "encryption/wrapped_keys.json",
                     "sequencing/sample_sheet.csv", "spec/BOOTSTRAP.md", "spec/RECOVERY_PACKAGE.md",
                     "synthesis/pre_simulation.fasta", "synthesis/REQUIREMENTS.md", "synthesis/vault-1/order.csv",
                     "decoder/lazarus/offline_decode.py", "decoder/dna_codec.lock.json", "decoder/dna_codec/encoder.py",
                     "decoder/requirements.lock", "decoder/INSTALL.md"):
        assert required in pkg.files, required
    lock = json.loads(pkg.files["decoder/dna_codec.lock.json"])
    assert lock["commit"] and "encoder.py" in lock["files"] and lock["bundled"] is True
    assert all(f"decoder/dna_codec/{rel}" in pkg.files for rel in lock["files"])
    info = pkg.info
    assert info["format"] == "lazarus-recovery-package-v1" and info["evidence"]["physical_dna_validated"] is False
    assert info["encryption"]["org_id"] == org_id and "Not validated against any synthesis provider" in \
        pkg.files["synthesis/REQUIREMENTS.md"].decode()
    for n in pkg.files:  # no reference back to server paths
        assert b"_orgs" not in pkg.files[n] and str(store.JOBS_DIR).encode() not in pkg.files[n]
    assert offline_decode.self_test(pkg) == 0
    # Tampered member -> rejected.
    z = zipfile.ZipFile(io.BytesIO(pkg_bytes))
    members = {n: z.read(n) for n in z.namelist() if n != "SHA256SUMS"}
    bad = dict(members)
    bad["archive/files.json"] = bad["archive/files.json"].replace(b'"bytes"', b'"bytez"')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for n, d in bad.items():
            out.writestr(n, d)
        out.writestr("SHA256SUMS", z.read("SHA256SUMS"))
    with pytest.raises(package_format.PackageError, match="Checksum mismatch"):
        package_format.read(buf.getvalue())
    # Path traversal / absolute names -> rejected before anything is read.
    for evil in ("../../etc/passwd", "/abs/file", "a/../../b", "C:\\x"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as out:
            out.writestr(evil, b"x")
            out.writestr("package.json", b"{}")
        with pytest.raises(package_format.PackageError):
            package_format.read(buf.getvalue())
    with pytest.raises(package_format.PackageError):
        package_format.read(b"not a zip")
    # Recovered file names cannot escape the output folder.
    assert decoder.safe_name("../../evil.sh") == "evil.sh" and decoder.safe_name("..\\..\\x") == "x"
    # Test independent recovery from the package (server side) works and is recorded.
    r = client.post(f"/api/jobs/{jid}/recovery-package/test", json={"source": "clean"},
                    headers={"X-Lazarus-Org-Token": token})
    assert r.status_code == 202, r.text
    s = wait(client, f"/api/decoder/sessions/{r.json()['id']}")
    assert s["verdict"] == "PASS", s
    rep = client.get(f"/api/decoder/sessions/{s['id']}/files/report.json").json()
    assert rep["evidence"]["level"] == "clean_design" and rep["recovery"]["key_source"].startswith("package wrapped keys")
    assert client.get(f"/api/jobs/{jid}/synthesis-requirements").status_code == 200


def test_org_onboarding_rules(client):
    org_id, token = new_org(client)
    info = client.get(f"/api/orgs/{org_id}", headers={"X-Lazarus-Org-Token": token}).json()
    assert info["current_version"] == 1 and info["backup_current"] is False and "token_sha256" not in info
    assert client.get(f"/api/orgs/{org_id}").status_code == 403
    form = {"policy": json.dumps(POLICY), "mode": "autopilot", "use_samples": "true", "org_id": org_id}
    assert client.post("/api/jobs", data=form).status_code == 403  # token required
    r = client.post("/api/jobs", data=form, headers={"X-Lazarus-Org-Token": token})
    assert r.status_code == 409 and "backup" in r.json()["detail"]  # no archives before a backup exists
    h = {"X-Lazarus-Org-Token": token}
    weak = client.post(f"/api/orgs/{org_id}/master-key/backup", headers=h,
                       json={"passphrase": "short", "confirm_passphrase": "short", "acknowledge": True})
    assert weak.status_code == 400
    unack = client.post(f"/api/orgs/{org_id}/master-key/backup", headers=h,
                        json={"passphrase": PASS_A, "confirm_passphrase": PASS_A})
    assert unack.status_code == 400
    data = backup(client, org_id, token)
    assert b"ciphertext" in data and orgs.keyring(org_id)[1] not in data
    doc = json.loads(data)
    assert doc["format"] == "lazarus-org-master-key-v1" and doc["versions"][0]["version"] == 1
    # Restore = verification on this server; on a fresh server it re-establishes the organization.
    r = client.post("/api/orgs/restore", data={"passphrase": PASS_A}, files={"backup_file": ("m.json", data)})
    assert r.status_code == 200 and r.json()["restored"] is False and r.json()["verified_versions"] == [1]
    assert client.post("/api/orgs/restore", data={"passphrase": "not the passphrase"},
                       files={"backup_file": ("m.json", data)}).status_code == 400
    shutil.rmtree(orgs.orgs_dir())
    r = client.post("/api/orgs/restore", data={"passphrase": PASS_A}, files={"backup_file": ("m.json", data)})
    assert r.status_code == 200 and r.json()["restored"] is True and r.json()["access_token"]
    assert orgs.public(orgs.load(org_id))["backup_current"] is True


def test_fastq_parser_lab_mode():
    good = "@r1 x\nACGTN\n+\nIIIII\n@r2\nacgt\n+\n!!!!\n"
    with pytest.raises(fasta.FastaError):
        fasta.parse(good)  # strict mode: N is not part of a clean design
    st = fasta.ReadStats()
    fmt, recs = fasta.parse(gzip.compress(good.encode()), lenient=True, stats=st)
    assert fmt == "fastq" and [r.sequence for r in recs] == ["ACGT"] and st.ambiguous_bases == 1
    assert recs[0].quality == "!!!!" and recs[0].mean_quality == 0
    with pytest.raises(fasta.FastaError, match="Phred"):
        fasta.parse("@r\nACGT\n+\nII\x7fI\n", lenient=True)
    with pytest.raises(fasta.FastaError):
        fasta.parse("@r\nAC1T\n+\nIIII\n", lenient=True)
