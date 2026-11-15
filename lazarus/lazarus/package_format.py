"""Reading and verifying a Lazarus Long-Term Recovery Package (format lazarus-recovery-package-v1).

Portable: no server state, no network. Ships inside every package with the offline decoder.

A package is a ZIP read entirely in memory and never extracted, so a hostile archive cannot write
files anywhere. Before anything is used, every member is checked: safe relative name, size limits,
listed in SHA256SUMS with a matching digest, and package.json must declare the supported format.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass

FORMAT = "lazarus-recovery-package-v1"
SCHEMA_VERSION = 1
FILENAME = "lazarus-recovery-package-v1.zip"
MAX_PACKAGE_BYTES = 128 * 1024 * 1024
MAX_MEMBERS = 4000
MAX_UNCOMPRESSED = 512 * 1024 * 1024
MAX_RATIO = 200  # zip-bomb guard: uncompressed / compressed per member
_SAFE = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$")


class PackageError(ValueError):
    """The package is unusable. The message is safe to show."""


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def safe_member(name: str) -> bool:
    return bool(_SAFE.match(name)) and ".." not in name.split("/") and not name.startswith("/")


@dataclass
class Package:
    info: dict
    files: dict[str, bytes]

    def json(self, name: str) -> dict:
        try:
            doc = json.loads(self.files[name])
        except KeyError:
            raise PackageError(f"Package is missing {name}") from None
        except ValueError:
            raise PackageError(f"{name} is not valid JSON") from None
        if not isinstance(doc, dict):
            raise PackageError(f"{name} must be a JSON object")
        return doc

    @property
    def archive_id(self) -> str:
        return self.info["archive_id"]

    @property
    def manifest(self) -> dict:
        return self.json("archive/manifest.json")

    @property
    def encryption(self) -> dict:
        return self.info.get("encryption") or {}

    @property
    def wrapped_keys(self) -> dict | None:
        return self.json("encryption/wrapped_keys.json") if "encryption/wrapped_keys.json" in self.files else None

    def sample_map(self) -> dict[str, str]:
        """Physical sample id -> pool id, from sequencing/sample_sheet.csv."""
        raw = self.files.get("sequencing/sample_sheet.csv")
        if raw is None:
            return {}
        out = {}
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
            sid, pool = (row.get("sample_id") or "").strip(), (row.get("pool") or "").strip()
            if sid and pool:
                out[sid] = pool
        return out

    def bundle(self) -> dict:
        """The non-secret metadata in the shape the decoder's `bundle` argument expects."""
        man = self.manifest
        files = self.json("archive/files.json")["files"]
        return {"format": "lazarus-recovery-bundle-v1", "archive_id": self.archive_id, "manifest": man,
                "expected_files": {f["name"]: {"sha256": f["sha256"], "bytes": f["bytes"]} for f in files}}


def read(data: bytes) -> Package:
    if len(data) > MAX_PACKAGE_BYTES:
        raise PackageError("Recovery Package is larger than the supported size.")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise PackageError("Not a ZIP file; expected a Lazarus Recovery Package.") from None
    infos = z.infolist()
    if len(infos) > MAX_MEMBERS:
        raise PackageError("Recovery Package has too many entries.")
    names, total = set(), 0
    for i in infos:
        if i.is_dir():
            continue
        if not safe_member(i.filename) or i.filename in names:
            raise PackageError(f"Unsafe or duplicate entry name in package: {i.filename!r}")
        total += i.file_size
        if total > MAX_UNCOMPRESSED or (i.compress_size and i.file_size / i.compress_size > MAX_RATIO
                                        and i.file_size > 1_000_000):
            raise PackageError("Recovery Package expands beyond the supported size.")
        names.add(i.filename)
    files = {}
    for n in names:
        with z.open(n) as f:
            files[n] = f.read(MAX_UNCOMPRESSED + 1)
    if "SHA256SUMS" not in files or "package.json" not in files:
        raise PackageError("Not a Lazarus Recovery Package (package.json or SHA256SUMS missing).")
    listed = {}
    for line in files["SHA256SUMS"].decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        digest, _, path = line.partition("  ")
        listed[path] = digest
    for n, b in files.items():
        if n == "SHA256SUMS":
            continue
        if n not in listed:
            raise PackageError(f"{n} is not covered by SHA256SUMS.")
        if listed[n] != sha256(b):
            raise PackageError(f"Checksum mismatch for {n}: the package is damaged or was modified.")
    missing = sorted(set(listed) - set(files))
    if missing:
        raise PackageError(f"Package is missing files listed in SHA256SUMS: {', '.join(missing[:5])}")
    pkg = Package(info={}, files=files)
    info = pkg.json("package.json")
    if info.get("format") != FORMAT:
        raise PackageError(f"Unsupported package format {info.get('format')!r}; this decoder reads {FORMAT}.")
    if int(info.get("schema_version", 0)) > SCHEMA_VERSION:
        raise PackageError("This package uses a newer schema than this decoder understands.")
    pkg.info = info
    return pkg


def write(members: dict[str, bytes]) -> bytes:
    """Deterministic ZIP: sorted names, fixed timestamps, SHA256SUMS over every other member."""
    for n in members:
        if not safe_member(n):
            raise ValueError(f"unsafe member name {n}")
    sums = "".join(f"{sha256(members[n])}  {n}\n" for n in sorted(members)).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in sorted(members) + ["SHA256SUMS"]:
            info = zipfile.ZipInfo(n, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, sums if n == "SHA256SUMS" else members[n])
    return buf.getvalue()
