"""Build the Long-Term Recovery Package for an approved archive (server side).

The package must let someone rebuild the archive decades from now with no Lazarus server, database,
job id lookup or cached original. Everything it needs is copied in; nothing refers back to this
server. It contains no unwrapped key and never the organization master key.

    package.json                     format, archive id, revision, key custody, contents
    README.md                        archive-specific recovery guide (human readable)
    SHA256SUMS                       digest of every other member (verified on import)
    archive/manifest.json            the bootstrap manifest (identical to the copy written in DNA)
    archive/files.json               names, sizes, SHA-256, key ids, nonces, stream offsets
    archive/layout.json              pools, stream layout, vault placement
    encoding/encoding.json           codec, per-pool settings, Fountain parameters, constraints, versions
    encryption/encryption.json       algorithms and how to supply keys
    encryption/wrapped_keys.json     organization archives: data keys wrapped under the master key
    sequencing/sample_sheet.csv      physical sample id -> vault, pool (for demultiplexed lab reads)
    sequencing/SEQUENCING.md         how to sequence, demultiplex and name read files
    spec/BOOTSTRAP.md                one-page manifest decoding spec
    spec/RECOVERY_PACKAGE.md         this format, field by field
    synthesis/pre_simulation.fasta   approved clean design (what would be synthesized)
    synthesis/vault-N/order.fasta|csv   per-vault orders, unchanged
    synthesis/samples/<sample>.fasta one file per physical sample
    synthesis/REQUIREMENTS.md        manufacturing assumptions and what must be validated first
    decoder/                         offline decoder source, lockfile, install and build steps
"""

from __future__ import annotations

import csv
import importlib.metadata as md
import io
import json
import os
import platform
from pathlib import Path

import dnacodec

from . import artifacts, experiment, fasta, manifest, package_format, store
from dnacodec import encoder as codec

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
DECODER_MODULES = ("__init__.py", "crypto.py", "dna.py", "fasta.py", "clustering.py", "manifest.py",
                   "decoder.py", "orgkeys.py", "package_format.py", "offline_decode.py")
LOCKED = ("numpy", "rapidfuzz", "zstandard", "cryptography", "cffi", "pycparser")
DECODER_VERSION = "1.0.0"
ERBGUT_REPO = "https://github.com/timarnoldev/hackmit2026.git"
ERBGUT_COMMIT = "556924ab285980c5523a93871474ec773d32b7d9"  # same pin as scripts/get_erbgut.sh


def path_for(revision: int) -> str:
    return f"exports/recovery_package/r{revision:03d}.zip"


def _versions() -> dict[str, str]:
    out = {}
    for p in LOCKED + ("dnacodec", "torch"):
        try:
            out[p] = md.version(p)
        except md.PackageNotFoundError:
            pass
    return out


def bundle_codec_source() -> bool:
    """Erbgut has no license file, so its source is not redistributed by default (see README,
    Credits). Packages always pin it by commit and per-file SHA-256; set
    LAZARUS_BUNDLE_CODEC_SOURCE=1 once redistribution is permitted to make packages self-contained."""
    return os.environ.get("LAZARUS_BUNDLE_CODEC_SOURCE") == "1"


def codec_lock() -> dict:
    codec_dir = Path(dnacodec.__file__).resolve().parent
    files = {p.relative_to(codec_dir).as_posix(): package_format.sha256(p.read_bytes())
             for p in sorted(codec_dir.rglob("*.py")) if "__pycache__" not in p.parts}
    return {"format": "lazarus-codec-lock-v1", "name": "dnacodec (Erbgut, HackMIT 2026)",
            "source": ERBGUT_REPO, "commit": ERBGUT_COMMIT, "version": _versions().get("dnacodec"),
            "files": files, "bundled": bundle_codec_source(),
            "note": "Erbgut's repository has no license file; its source is bundled only with permission. "
                    "Fetch it at this commit and verify every file against these SHA-256 digests."}


def _decoder_files() -> dict[str, bytes]:
    here = Path(__file__).resolve().parent
    files = {f"decoder/lazarus/{m}": (here / m).read_bytes() for m in DECODER_MODULES}
    files["decoder/lazarus/__init__.py"] = b'"""Lazarus offline decoder (subset of the Lazarus package)."""\n'
    lock = codec_lock()
    files["decoder/dnacodec.lock.json"] = json.dumps(lock, indent=2).encode()
    if lock["bundled"]:
        codec_dir = Path(dnacodec.__file__).resolve().parent
        for rel in lock["files"]:
            files[f"decoder/dnacodec/{rel}"] = (codec_dir / rel).read_bytes()
    v = _versions()
    pins = "".join(f"{p}=={v[p]}\n" for p in LOCKED if p in v)
    files["decoder/requirements.lock"] = (
        f"# Exact versions the decoder was built and tested with (Python {platform.python_version()}).\n"
        "# Optional CNN decoder: torch==" + v.get("torch", "unavailable") + " plus checkpoints/polish/polish.pt "
        "(not included).\n" + pins).encode()
    deps = ",\n".join(f'    "{p}=={v[p]}"' for p in ("numpy", "rapidfuzz", "zstandard", "cryptography") if p in v)
    files["decoder/pyproject.toml"] = f"""[project]
name = "lazarus-decoder"
version = "{DECODER_VERSION}"
description = "Offline decoder for Lazarus DNA archives ({package_format.FORMAT})"
requires-python = ">=3.11"
dependencies = [
{deps}
]

[project.scripts]
lazarus-decode = "lazarus.offline_decode:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = {'["lazarus", "dnacodec"]' if lock["bundled"] else '["lazarus"]'}
""".encode()
    codec_text = (
        "The codec source is included in `dnacodec/` (pinned in `dnacodec.lock.json`)." if lock["bundled"] else
        "The codec is **not included** (its authors have not published a license yet). Fetch it at the\n"
        "pinned commit and put its `dnacodec/` folder next to `lazarus/` here (or install it into the venv):\n\n"
        f"```\ngit clone {ERBGUT_REPO} erbgut && git -C erbgut checkout {ERBGUT_COMMIT}\n"
        "cp -r erbgut/dnacodec ./dnacodec\n```\n\n"
        "`dnacodec.lock.json` lists the SHA-256 of every codec file; the decoder checks the codec it runs\n"
        "against it and reports any difference.")
    files["decoder/INSTALL.md"] = f"""# Lazarus offline decoder {DECODER_VERSION}

Needs Python 3.11 or newer. No network access, account or Lazarus server is used while decoding.

## Run from this folder (no install)

```
python -m venv .venv
.venv/bin/pip install -r requirements.lock          # Windows: .venv\\Scripts\\pip
.venv/bin/python -m lazarus.offline_decode --help
```

## Or install the command

```
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps .
lazarus-decode --help
```

## The DNA codec (Erbgut `dnacodec`)

{codec_text}

## Reproducible build

`requirements.lock` pins the exact dependency versions this decoder was tested with. The decoder
source (`lazarus/`) is included verbatim; its SHA-256 digests are in the package's SHA256SUMS, and
the codec (version {v.get('dnacodec', '?')}) is pinned by commit and per-file digests. If a pinned
dependency is no longer installable, any version that passes the package self-test below is acceptable:

```
python -m lazarus.offline_decode --self-test --recovery-package ../{package_format.FILENAME}
```

The optional CNN consensus decoder (Erbgut PolishDecoder) needs PyTorch and a model checkpoint that
is not shipped. The majority-vote decoder (`--decoder baseline`) needs neither and is the default.
""".encode()
    return files


def _readme(job: dict, info: dict, man: dict, rows: list[dict]) -> str:
    enc = info["encryption"]
    org = enc["mode"] == "organization"
    files = "\n".join(f"| {n} | {f['bytes']:,} | `{f['sha256']}` |" for n, f in sorted(man["files"].items()))
    key_steps = (
        f"""You need your organization's **master key backup** (`lazarus-org-master-key-v1` file) that contains
**master-key version {enc['kek_version']}** (fingerprint `{enc['kek_fingerprint']}`), and its passphrase.
The data keys of this archive are in `encryption/wrapped_keys.json`, wrapped (AES-256-GCM) under that
master key. If your organization rotated its master key after this package was issued, either use the
backup that still holds version {enc['kek_version']}, or use the newer Recovery Package re-issued after
the rotation."""
        if org else
        """This archive uses a per-archive key file (`lazarus-keyfile-v1`) exported from Lazarus, protected by
a passphrase. You need that key file and its passphrase. (It can be migrated to organization key
management; an updated package is then issued.)""")
    return f"""# Lazarus Long-Term Recovery Package

Archive **{job.get('name') or job['company']}** · id `{job['id']}` · {job['company']}
Package revision {info['revision']} · created {info['created']} · format `{package_format.FORMAT}`

This package, the DNA (or sequencing reads of it) and your key are all you need to get the files
back. It does not depend on Lazarus' website, servers or database. It contains **no usable key**.

## The files in this archive

| File | Bytes | SHA-256 |
|---|---:|---|
{files}

Recovery counts only when every byte matches these SHA-256 digests.

## What you need

1. **Sequencing reads** of the DNA, as FASTA or FASTQ (gzip is fine), one file per physical sample
   from the sequencing facility's demultiplexing. Sample ids are in `sequencing/sample_sheet.csv`.
2. **This package** (`{package_format.FILENAME}`), unmodified (checked against `SHA256SUMS`).
3. **Your key**: {key_steps}

## Recover

```
cd decoder
python -m venv .venv && .venv/bin/pip install -r requirements.lock
.venv/bin/python -m lazarus.offline_decode \\
    --recovery-package ../{package_format.FILENAME} \\
    --reads-sheet my_lab_samples.csv \\
    {'--master-key organization-master-key.json' if org else '--keyfile archive.lazarus-keys.json'} \\
    --output ./recovered
```

`my_lab_samples.csv` has two columns, `file,sample_id`, one row per FASTQ the facility delivered,
using the sample ids from `sequencing/sample_sheet.csv`. Alternatively pass `--reads SAMPLE_ID=file.fastq.gz`
once per file. You are asked for the passphrase at a hidden prompt (or via `--passphrase-env NAME`).

The decoder writes the recovered files and `verification_report.json` / `.html`. It prints PASS only
if every file's SHA-256 matches. It never fills gaps with stored copies: there are none.

## Without this software

`spec/BOOTSTRAP.md` explains how to read the manifest from the DNA with one fixed published setting,
and `spec/RECOVERY_PACKAGE.md` documents every field here. A compatible reimplementation of the
Erbgut DNA Fountain decoder (`decoder/dnacodec/encoder.py`, `recover`) plus AES-256-GCM and zstd
is sufficient. Arbitrary DNA-storage software cannot read this format without implementing it.

## Physical samples

{len(rows)} physical samples: every vault holds a full manifest copy and an interleaved share of every
data pool. See `sequencing/SEQUENCING.md` and `synthesis/REQUIREMENTS.md`.

## Evidence level

Recovery of this archive has been tested on simulated reads only. No DNA was synthesized or sequenced
by Lazarus. Physical recovery must be validated by sequencing synthesized DNA of a known
Lazarus-encoded sample before relying on it.
"""


def _sequencing_md(rows: list[dict]) -> str:
    return f"""# Sequencing and sample identification

## The current physical design has no in-molecule identifiers

Strands are exactly the encoded sequences (see `encoding/encoding.json`): no PCR primer sites, no
barcodes, no adapters. Reads of different pools therefore **cannot be told apart by sequence**, and
the decoder will not guess. Pools are separated **physically**: each row of `sample_sheet.csv` is
meant to be its own container (oligo pool / tube) from synthesis onward, and is sequenced as its own
sample. The sequencing facility's demultiplexing (by its own sequencing barcodes, added during
library preparation) yields one read file per sample.

## Sample sheet

`sample_sheet.csv` columns: `sample_id, archive_id, vault, pool, role, strands, strand_length,
container, molecular_identifier`. {len(rows)} samples. Use `sample_id` as the sample name in the
facility's sample sheet so delivered files map back unambiguously.

## Delivering reads to the decoder

* One FASTA/FASTQ(.gz) per sample, plus a two-column CSV `file,sample_id`, or
* one file whose read headers carry `sample=<sample_id or pool>`.

Unassigned reads are reported and not used. If all reads are unassigned the decoder stops with an
explanation instead of producing a result.

## What sequencing must deliver

* Reads of the full {rows[0]['strand_length'] if rows else 110}-nt strand. Library-prep adapters must
  be trimmed by the facility (standard demultiplexing/trimming); the decoder does not trim adapters.
* Either orientation is fine (reverse-strand reads are recognised by the strand checksum).
* FASTQ qualities are used to drop reads with mean Phred below 7 (configurable); consensus ignores
  per-base qualities.
* Coverage: plan for at least the coverage this archive was tested with (see `package.json`).

## Planning primers or barcodes for future archives

Sequence-side pool identification (e.g. a distinct primer pair per pool, as in random-access DNA
storage) has to be designed into the strands **before synthesis**; it cannot be added to DNA that was
manufactured without it. This archive does not use it.
"""


def _requirements_md(job: dict, man: dict, rows: list[dict]) -> str:
    s = job["order"]["settings"]
    return f"""# Synthesis requirements and assumptions

**Not validated against any synthesis provider.** Check every item with the chosen provider before
ordering; Lazarus does not claim this design is manufacturable by every laboratory.

| Item | This archive |
|---|---|
| Strand length | {', '.join(str(n) for n in sorted({p['settings']['strand_length'] for p in man['pools'].values()} | {manifest.BOOTSTRAP.strand_length}))} nt |
| Alphabet | A, C, G, T only |
| GC content per strand | {'40–60 % (enforced by the encoder)' if s.get('gc_rule', True) else 'not constrained'} |
| Longest homopolymer | {'≤ 3 (enforced by the encoder)' if s.get('homopolymer_rule', True) else 'not constrained'} |
| Data strands | {job['order']['data_strands']:,} (spread over {s['n_vaults']} vaults) |
| Manifest strands | {job['order']['manifest_strands']} per vault (full copy in every vault) |
| Total nucleotides | {job['order']['total_bases']:,} |
| Physical samples | {len(rows)} (one container per vault × pool; see sequencing/sample_sheet.csv) |
| Primers / adapters | none included; add only if the provider's process requires it and the decoder is updated to trim them |
| Redundancy | {s['redundancy']} (Fountain overhead) |

Assumptions to confirm with the provider: oligo-pool synthesis at this length and error rate,
delivering each sample as a separate pool, storage format (dried, encapsulated, …), amplification
before sequencing, and minimum order size. Costs shown in Lazarus are modeled placeholders.

Files: `synthesis/pre_simulation.fasta` (all samples), `synthesis/samples/<sample_id>.fasta` (one per
container) and the per-vault `order.fasta` / `order.csv` that Lazarus generated.
"""


def _sample_rows(job: dict, records: list[fasta.Record]) -> tuple[list[dict], dict[str, list[tuple[str, str]]]]:
    counts: dict[tuple[int, str], list[tuple[str, str]]] = {}
    for r in records:
        v = fasta.vault_of_id(r.id)
        counts.setdefault((v, r.sample), []).append((r.id, r.sequence))
    rows, per_sample = [], {}
    for (v, pool), recs in sorted(counts.items(), key=lambda x: (x[0][0], x[0][1] != manifest.MANIFEST_POOL, x[0][1])):
        sid = f"{job['id']}-V{v}-{pool}"
        per_sample[sid] = recs
        rows.append({"sample_id": sid, "archive_id": job["id"], "vault": v, "pool": pool,
                     "role": "manifest" if pool == manifest.MANIFEST_POOL else "data",
                     "strands": len(recs), "strand_length": len(recs[0][1]),
                     "container": "separate oligo pool / tube", "molecular_identifier": "none"})
    return rows, per_sample


def build(job_id: str) -> dict:
    """Build (or re-issue) the package. Every call creates a new revision; earlier revisions stay
    downloadable and valid for the master-key version they were wrapped with."""
    job = store.load(job_id)
    if not job.get("order"):
        raise FileNotFoundError("The archive has not been approved yet")
    experiment.build_clean_export(job_id)
    job = store.load(job_id)
    bundle = json.loads(artifacts.download(job_id, experiment.BUNDLE))
    man = bundle["manifest"]
    pre = artifacts.download(job_id, experiment.PRE_FASTA)
    _, records = fasta.parse(pre)
    rows, per_sample = _sample_rows(job, records)
    km = job.get("key_management") or {}
    org = km.get("mode") == "organization"
    revision = (job.get("recovery_package") or {}).get("revision", 0) + 1
    versions = _versions()
    s = job["order"]["settings"]
    info = {
        "format": package_format.FORMAT,
        "schema_version": package_format.SCHEMA_VERSION,
        "archive_id": job_id,
        "archive_name": job.get("name") or job["company"],
        "company": job["company"],
        "created": store.now(),
        "revision": revision,
        "encryption": ({"mode": "organization", "org_id": km["org_id"], "kek_version": km["kek_version"],
                        "kek_fingerprint": km["kek_fingerprint"], "wrapped_keys": "encryption/wrapped_keys.json"}
                       if org else {"mode": "legacy-keyfile", "keys_included": False,
                                    "key_file_format": "lazarus-keyfile-v1"}),
        "dna": {"n_vaults": s["n_vaults"], "data_strands": job["order"]["data_strands"],
                "manifest_strands_per_vault": job["order"]["manifest_strands"],
                "planned_coverage": s.get("coverage"), "recommended_decoder": s.get("decoder"),
                "samples": len(rows)},
        "decoder": {"entry": "decoder/ (python -m lazarus.offline_decode)", "version": DECODER_VERSION},
        "evidence": {"physical_dna_validated": False,
                     "simulated_decodes": [{k: d.get(k) for k in ("id", "created", "verdict", "simulation_id")}
                                           for d in job.get("decodes", [])][-10:],
                     "latest_recovery_drill": ({k: job["drills"][-1].get(k) for k in ("tested_at", "all_verified")}
                                               if job.get("drills") else None)},
        "notice": "Contains no unwrapped encryption key and no organization master key.",
    }
    files_json = {"files": [{"name": n, **{k: f[k] for k in ("bytes", "sha256", "key_id", "nonce", "pools",
                                                               "offset", "cipher_bytes")}}
                            for n, f in sorted(man["files"].items())]}
    layout = {
        "stream": man.get("stream") or "pools concatenated in pool-id order form one stream; "
                                        "each file is stream[offset:offset+cipher_bytes]",
        "pools": {pid: {"offset": p.get("offset", 0), "n_bytes": p["n_bytes"], "n_chunks": p["n_chunks"],
                        "strands_written": int(-(-p["n_chunks"] * (1 + p["settings"]["redundancy"]) // 1))}
                  for pid, p in sorted(man["pools"].items())},
        "n_vaults": s["n_vaults"],
        "placement": "strand i of each data pool -> vault (i mod n_vaults) + 1; every vault holds the full manifest",
        "manifest_sample_label": manifest.MANIFEST_POOL,
    }
    encoding = {
        "codec": "Erbgut DNA Fountain (LT code), reference implementation decoder/dnacodec/encoder.py",
        "dnacodec_version": versions.get("dnacodec"),
        "bits_per_base": "2 (A=0, C=1, G=2, T=3)",
        "strand_layout": "seed (seed_bases) + payload; payload = chunk + CRC-16 (CRC-CCITT over seed+chunk), "
                         "XOR-whitened with a seed-derived mask",
        "file_framing": "4-byte CRC-32 prefix before chunking; recover() returns nothing rather than a wrong file",
        "fountain": {"degree_distribution": "robust soliton", "c": codec.SOLITON_C, "delta": codec.SOLITON_DELTA,
                     "seeds": "bijective scramble of a running counter", "decoding": "peeling, then GF(2) elimination"},
        "pools": {pid: {"settings": p["settings"], "n_bytes": p["n_bytes"], "n_chunks": p["n_chunks"]}
                  for pid, p in sorted(man["pools"].items())},
        "bootstrap_manifest": {**bundle["bootstrap"], "spec": "spec/BOOTSTRAP.md",
                               "framing": "b'LZM1' + 4-byte big-endian length + zstd(JSON) + zero padding"},
        "approved_settings": s,
        "consensus": {"baseline": "majority vote over clustered reads (dnacodec.baseline)",
                      "polish": "optional 1D CNN (dnacodec.model.polish), needs torch + checkpoint (not shipped)",
                      "clustering": "reference-free k-mer + edit distance (lazarus/clustering.py)"},
        "dependencies": versions,
        "python": platform.python_version(),
    }
    encryption = {
        "file_encryption": "zstd (level 19) compression, then AES-256-GCM with a unique 256-bit data key per "
                           "file, 96-bit nonce (archive/files.json), associated data b'lazarus-v1'",
        "custody": info["encryption"],
        "how_to_supply_keys": (
            "Unlock your organization master key backup (scrypt + AES-256-GCM, passphrase) and unwrap each data "
            "key in wrapped_keys.json with AES-256-GCM using the AAD described there."
            if org else "Open the passphrase-protected lazarus-keyfile-v1 exported for this archive."),
    }
    sheet = io.StringIO()
    w = csv.DictWriter(sheet, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    members: dict[str, bytes] = {
        "archive/manifest.json": json.dumps(man, indent=2, sort_keys=True).encode(),
        "archive/files.json": json.dumps(files_json, indent=2).encode(),
        "archive/layout.json": json.dumps(layout, indent=2).encode(),
        "encoding/encoding.json": json.dumps(encoding, indent=2, default=str).encode(),
        "encryption/encryption.json": json.dumps(encryption, indent=2).encode(),
        "sequencing/sample_sheet.csv": sheet.getvalue().encode(),
        "sequencing/SEQUENCING.md": _sequencing_md(rows).encode(),
        "spec/BOOTSTRAP.md": (DOCS / "BOOTSTRAP.md").read_bytes(),
        "spec/RECOVERY_PACKAGE.md": (DOCS / "RECOVERY_PACKAGE.md").read_bytes(),
        "synthesis/pre_simulation.fasta": pre,
        "synthesis/REQUIREMENTS.md": _requirements_md(job, man, rows).encode(),
        **{f"synthesis/samples/{sid}.fasta": fasta.write([(h, q) for h, q in recs]).encode()
           for sid, recs in per_sample.items()},
        **_decoder_files(),
    }
    for path in job["order"]["order_files"]:
        try:
            members[f"synthesis/{path.removeprefix('vaults/')}"] = artifacts.download(job_id, path)
        except FileNotFoundError:
            pass  # a simulated lost vault; its strands are still in pre_simulation.fasta
    if org:
        members["encryption/wrapped_keys.json"] = json.dumps(km["wrapped_keys"], indent=2).encode()
    info["contents"] = sorted(members) + ["README.md", "SHA256SUMS"]
    members["package.json"] = json.dumps(info, indent=2).encode()
    members["README.md"] = _readme(job, info, man, rows).encode()
    data = package_format.write(members)
    package_format.read(data)  # self-check: the package we hand out must pass our own import checks
    path = path_for(revision)
    artifacts.publish(job_id, path, data)
    artifacts.publish(job_id, "exports/synthesis_requirements.md", members["synthesis/REQUIREMENTS.md"])
    entry = {"revision": revision, "path": path, "sha256": package_format.sha256(data), "bytes": len(data),
             "created": info["created"], "encryption": info["encryption"]}
    store.update(job_id, lambda j: j.update(recovery_package={
        **entry, "history": ((j.get("recovery_package") or {}).get("history") or [])
        + [{k: entry[k] for k in ("revision", "sha256", "created")} | {"kek_version": info["encryption"].get("kek_version")}]}))
    return entry


def latest(job_id: str) -> tuple[bytes, dict]:
    job = store.load(job_id)
    rp = job.get("recovery_package")
    if not rp:
        raise FileNotFoundError("No Recovery Package has been created for this archive")
    from .persistence import get_cloud

    cloud = get_cloud()
    data = cloud.get_artifact(job_id, rp["path"]) if cloud else (store.job_dir(job_id) / rp["path"]).read_bytes()
    return data, rp
