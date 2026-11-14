"""lazarus-decode: recover a Lazarus DNA archive offline.

Inputs: sequencing reads (FASTA/FASTQ, optionally gzip), the archive's Recovery Package, and either
the organization master key backup or the legacy per-archive key file. Passphrases are read from a
hidden prompt or an environment variable, never from the command line.

No network access, account, Lazarus server, database or original upload is used.

Exit codes: 0 PASS (every file's SHA-256 matches), 1 decoded but not PASS, 2 bad input or usage,
3 key problem (wrong key, wrong passphrase, wrong organization or master-key version).
"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import sys
from pathlib import Path

from . import decoder, manifest, orgkeys, package_format
from . import fasta


class UsageError(Exception):
    """Bad arguments or unusable input; exit code 2."""


def _passphrase(args, what: str) -> str:
    if args.passphrase_env:
        val = os.environ.get(args.passphrase_env)
        if val is None:
            raise UsageError(f"environment variable {args.passphrase_env} is not set")
        return val
    if not sys.stdin.isatty():
        raise UsageError(f"no terminal for the passphrase prompt; use --passphrase-env NAME")
    return getpass.getpass(f"Passphrase for {what}: ")


def _inputs(args) -> list[decoder.ReadInput]:
    out = []
    for spec in args.reads or []:
        sample, sep, path = spec.partition("=")
        if not sep or not sample or Path(spec).exists():
            sample, path = None, spec
        p = Path(path)
        out.append(decoder.ReadInput(p.name, p.read_bytes(), sample))
    if args.reads_sheet:
        sheet = Path(args.reads_sheet)
        with open(sheet, newline="", encoding="utf-8") as f:
            for n, row in enumerate(csv.DictReader(f), start=2):
                file, sid = (row.get("file") or "").strip(), (row.get("sample_id") or "").strip()
                if not file or not fasta.valid_label(sid):
                    raise UsageError(f"{sheet}:{n}: need columns file,sample_id with a valid sample id")
                p = (sheet.parent / file) if not Path(file).is_absolute() else Path(file)
                out.append(decoder.ReadInput(p.name, p.read_bytes(), sid))
    if not out:
        raise UsageError(f"give at least one --reads FILE or a --reads-sheet")
    return out


def _keys(args, pkg: package_format.Package) -> tuple[dict[str, bytes], str]:
    enc = pkg.encryption
    if args.master_key:
        if enc.get("mode") != "organization":
            raise decoder_key_error("This archive's keys are not under an organization master key; "
                                    "use --keyfile with its per-archive key file.")
        data = Path(args.master_key).read_bytes()
        info, ring = orgkeys.open_backup(data, _passphrase(args, "the organization master key backup"))
        if info["org_id"] != enc["org_id"]:
            raise decoder_key_error(f"The master key backup is for organization {info['org_id']}, but this "
                                    f"archive belongs to {enc['org_id']}.")
        keys = orgkeys.unwrap_keys(pkg.wrapped_keys, ring, org_id=enc["org_id"], archive_id=pkg.archive_id)
        return keys, f"organization master key backup (version {enc['kek_version']})"
    if args.keyfile:
        archive_id, keys = decoder.open_keyfile(Path(args.keyfile).read_bytes(),
                                                _passphrase(args, "the archive key file"))
        if archive_id != pkg.archive_id:
            raise decoder_key_error(f"The key file belongs to archive {archive_id}, not {pkg.archive_id}.")
        return keys, "legacy per-archive key file"
    raise UsageError(f"give --master-key (organization backup) or --keyfile (legacy key file)")


def decoder_key_error(msg: str) -> orgkeys.KeyError_:
    return orgkeys.KeyError_(msg)


def _write_outputs(out: Path, report: dict, recovered: dict[str, bytes], force: bool) -> list[Path]:
    rec_dir = out / "recovered"
    rec_dir.mkdir(parents=True, exist_ok=True)
    targets, used = [], set()
    for name in sorted(recovered):
        base = decoder.safe_name(name)  # strips directories: a package cannot direct writes elsewhere
        cand, i = base, 1
        while cand.lower() in used:
            cand, i = f"{i}_{base}", i + 1
        used.add(cand.lower())
        targets.append((rec_dir / cand, recovered[name]))
    for path in [p for p, _ in targets] + [out / "verification_report.json", out / "verification_report.html"]:
        if path.exists() and not force:
            raise UsageError(f"{path} already exists; choose an empty --output or pass --force")
    written = []
    for path, data in targets:
        path.write_bytes(data)
        written.append(path)
    (out / "verification_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "verification_report.html").write_text(decoder.render_html(report), encoding="utf-8")
    return written


def codec_check(pkg: package_format.Package) -> dict:
    """Compare the dnacodec this decoder imports with the package's pinned per-file digests."""
    raw = pkg.files.get("decoder/dnacodec.lock.json")
    if raw is None:
        return {"status": "no codec lock in package"}
    lock = json.loads(raw)
    import dnacodec

    d = Path(dnacodec.__file__).resolve().parent
    differs = [rel for rel, h in sorted(lock["files"].items())
               if not (d / rel).is_file() or package_format.sha256((d / rel).read_bytes()) != h]
    return {"status": "matches pinned codec" if not differs else "differs from pinned codec",
            "commit": lock.get("commit"), "source": lock.get("source"), "differs": differs[:20],
            "path": str(d)}


def self_test(pkg: package_format.Package) -> int:
    """Decode the manifest from the package's own clean manifest strands and compare it with
    archive/manifest.json. Proves the codec installation works; needs no key."""
    first = next(n for n in sorted(pkg.files) if n.startswith("synthesis/samples/") and n.endswith("-MANIFEST.fasta"))
    _, recs = fasta.parse(pkg.files[first])
    got = manifest.decode_manifest([r.sequence for r in recs])
    ok = got == pkg.manifest
    print(f"package checksums: OK ({len(pkg.files)} files)")
    cc = codec_check(pkg)
    print(f"codec: {cc['status']}" + (f" ({', '.join(cc['differs'])})" if cc.get("differs") else ""))
    print(f"manifest decoded from DNA ({first}): {'matches archive/manifest.json' if ok else 'MISMATCH'}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lazarus-decode", description=__doc__.split("\n\n")[0])
    ap.add_argument("--recovery-package", required=True, help="the archive's lazarus-recovery-package-v1.zip")
    ap.add_argument("--reads", action="append", metavar="[SAMPLE_ID=]FILE",
                    help="FASTA/FASTQ(.gz) of sequencing reads; prefix with a sample id to assign every read "
                         "in the file to that sample. Repeat for several files.")
    ap.add_argument("--reads-sheet", metavar="CSV", help="lab sample sheet with columns file,sample_id")
    ap.add_argument("--master-key", metavar="FILE", help="organization master key backup (lazarus-org-master-key-v1)")
    ap.add_argument("--keyfile", metavar="FILE", help="legacy per-archive key file (lazarus-keyfile-v1)")
    ap.add_argument("--passphrase-env", metavar="NAME", help="read the passphrase from this environment variable "
                                                             "instead of the hidden prompt")
    ap.add_argument("--output", metavar="DIR", help="where to write recovered files and the report")
    ap.add_argument("--decoder", choices=["baseline", "polish", "both"], default="baseline")
    ap.add_argument("--min-quality", type=float, default=decoder.DEFAULT_MIN_QUALITY,
                    help="drop FASTQ reads with a lower mean Phred score (default %(default)s; 0 keeps all)")
    ap.add_argument("--evidence", choices=["lab", "simulated", "clean"], default="lab",
                    help="what the reads are, for the report (default: lab-format reads)")
    ap.add_argument("--force", action="store_true", help="overwrite files in --output")
    ap.add_argument("--self-test", action="store_true", help="check the package and the codec installation only")
    args = ap.parse_args(argv)

    try:
        pkg = package_format.read(Path(args.recovery_package).read_bytes())
    except (OSError, package_format.PackageError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.self_test:
        return self_test(pkg)
    if not args.output:
        print("error: --output is required", file=sys.stderr)
        return 2
    try:
        inputs = _inputs(args)
        keys, key_source = _keys(args, pkg)
    except orgkeys.KeyError_ as e:
        print(f"key error: {e}", file=sys.stderr)
        return 3
    except ValueError as e:  # legacy key file: wrong passphrase / not a key file
        print(f"key error: {e}", file=sys.stderr)
        return 3
    except (OSError, UsageError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    def progress(step, status, detail):
        print(f"[{step}] {status}: {detail}", file=sys.stderr)

    codec = codec_check(pkg)
    if codec.get("differs"):
        print(f"warning: the installed DNA codec differs from the version pinned in the package "
              f"({', '.join(codec['differs'])}). Results are still accepted only on exact SHA-256 matches.",
              file=sys.stderr)

    req = decoder.DecodeRequest(
        fasta_bytes=b"", fasta_name="", decoders=["baseline", "polish"] if args.decoder == "both" else [args.decoder],
        key_for=keys.get, key_source=key_source, mode="package_recovery", bundle=pkg.bundle(),
        expected_archive_id=pkg.archive_id, inputs=inputs, sample_map=pkg.sample_map(), lab=True,
        min_mean_quality=args.min_quality,
        evidence={"lab": "lab_format_reads", "simulated": "simulated_reads", "clean": "clean_design"}[args.evidence],
        archive_context={"recovery_package": {"revision": pkg.info.get("revision"),
                                              "sha256": package_format.sha256(Path(args.recovery_package).read_bytes()),
                                              "decoder": "offline lazarus-decode", "decoder_source": __file__,
                                              "codec": codec}},
    )
    try:
        report, recovered = decoder.run(req, progress)
    except fasta.FastaError as e:
        print(f"error: invalid sequence file: {e}", file=sys.stderr)
        return 2
    keys.clear()
    out = Path(args.output)
    try:
        written = _write_outputs(out, report, recovered, args.force)
    except (OSError, UsageError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"\n{report['verdict']}: {report['verdict_text']}")
    for f in report["files"]:
        print(f"  {'MATCH   ' if f['verified'] else 'NO MATCH'} {f['name']}  {f.get('reason') or ''}")
    for m in report["missing"]:
        print(f"  missing: {m}")
    print(f"evidence: {report['evidence']['text']}")
    print(f"wrote {len(written)} file(s) and verification_report.json/.html to {out}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
