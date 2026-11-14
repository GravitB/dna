"""Organizations and their master-key custody on this server.

Storage (local keystore; the `KekStore` class is the seam for a production KMS/HSM):

    {JOBS_DIR}/_orgs/{org_id}/org.json        public record: name, versions, fingerprints, backups,
                                               SHA-256 of the access token (never the token itself)
    {JOBS_DIR}/_orgs/{org_id}/keks/v{n}.key   raw 256-bit master key, version n (file mode 0600)

A KMS can replace `KekStore`, but recovery never depends on it: every organization exports a
passphrase-protected backup of its key ring (orgkeys.make_backup) and the offline decoder only needs
that backup, the Recovery Package and the DNA reads.

Authorization: each organization gets a random access token at creation, shown once. Every key
operation (export, rotate, migrate, recovery package download) requires it. Tokens are compared in
constant time against their stored SHA-256.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
from pathlib import Path

from . import orgkeys, store

_ORG_ID = re.compile(r"^org-[0-9a-f]{12}$")
_lock = threading.RLock()


class OrgError(ValueError):
    """Message is safe to show; status is the HTTP status the API should use."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def orgs_dir() -> Path:
    return store.JOBS_DIR / "_orgs"


def org_dir(org_id: str) -> Path:
    if not _ORG_ID.match(org_id or ""):
        raise OrgError("Organization not found", 404)
    return orgs_dir() / org_id


class KekStore:
    """Local master-key custody. Swap for a KMS/HSM client exposing the same three methods."""

    def __init__(self, org_id: str):
        self.dir = org_dir(org_id) / "keks"

    def put(self, version: int, kek: bytes) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self.dir / f"v{int(version)}.key"
        if p.exists():
            raise OrgError(f"Master key version {version} already exists", 409)
        p.write_bytes(kek)
        try:
            p.chmod(0o600)
        except OSError:  # pragma: no cover  (not enforced on every filesystem)
            pass

    def get(self, version: int) -> bytes:
        p = self.dir / f"v{int(version)}.key"
        if not p.exists():
            raise OrgError(f"Master key version {version} is not held by this server", 404)
        return p.read_bytes()

    def versions(self) -> list[int]:
        if not self.dir.exists():
            return []
        return sorted(int(p.stem[1:]) for p in self.dir.glob("v*.key"))


# ------------------------------------------------------------------ records


def _save(org: dict) -> None:
    d = org_dir(org["id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "org.tmp"
    tmp.write_text(json.dumps(org, indent=2))
    tmp.replace(d / "org.json")


def load(org_id: str) -> dict:
    p = org_dir(org_id) / "org.json"
    if not p.exists():
        raise OrgError("Organization not found", 404)
    return json.loads(p.read_text())


def public(org: dict) -> dict:
    """What the API may show: no token hash, no key material."""
    cur = org["current_version"]
    backed = {v for b in org.get("backups", []) for v in b["versions"]}
    return {
        "id": org["id"],
        "name": org["name"],
        "created": org["created"],
        "current_version": cur,
        "versions": org["versions"],
        "backups": org.get("backups", []),
        "backup_current": cur in backed,
        "archives": archives_of(org["id"]),
        "custody": "local keystore (KMS/HSM-ready interface); recovery uses your exported backup",
    }


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authorize(org_id: str, token: str | None) -> dict:
    org = load(org_id)
    if not token or not hmac.compare_digest(_token_hash(token), org["token_sha256"]):
        raise OrgError("Organization access token missing or invalid", 403)
    return org


def create(name: str) -> tuple[dict, str]:
    name = (name or "").strip()
    if not 1 <= len(name) <= 120:
        raise OrgError("Organization name must be 1–120 characters")
    with _lock:
        org_id = "org-" + secrets.token_hex(6)
        token = secrets.token_urlsafe(32)
        kek = orgkeys.new_kek()
        KekStore(org_id).put(1, kek)
        org = {
            "id": org_id, "name": name, "created": store.now(), "current_version": 1,
            "versions": [{"version": 1, "fingerprint": orgkeys.fingerprint(kek), "created": store.now(),
                          "status": "active"}],
            "backups": [], "token_sha256": _token_hash(token), "migrations": [], "rotations": [],
        }
        _save(org)
    return org, token


def keyring(org_id: str, versions: list[int] | None = None) -> dict[int, bytes]:
    ks = KekStore(org_id)
    return {v: ks.get(v) for v in (versions or ks.versions())}


def current(org_id: str) -> tuple[int, bytes]:
    v = load(org_id)["current_version"]
    return v, KekStore(org_id).get(v)


def export_backup(org_id: str, passphrase: str, scope: str = "all") -> tuple[bytes, list[int]]:
    """Passphrase-protected backup of the key ring ('all' versions or only the 'current' one)."""
    org = load(org_id)
    versions = [org["current_version"]] if scope == "current" else [v["version"] for v in org["versions"]]
    try:
        data = orgkeys.make_backup(org_id, org["name"], keyring(org_id, versions), passphrase, store.now())
    except orgkeys.KeyError_ as e:
        raise OrgError(str(e)) from None
    with _lock:
        org = load(org_id)
        org["backups"].append({"exported": store.now(), "versions": versions,
                               "sha256": hashlib.sha256(data).hexdigest()})
        _save(org)
    return data, versions


def restore(backup: bytes, passphrase: str) -> dict:
    """Verify a backup against this server, or re-establish the organization from it (a new
    server, or after data loss). Returns {org, restored, verified_versions, access_token?}."""
    try:
        info, ring = orgkeys.open_backup(backup, passphrase)
    except orgkeys.KeyError_ as e:
        raise OrgError(str(e)) from None
    org_id = info["org_id"]
    org_dir(org_id)  # validates the id format before touching the filesystem
    with _lock:
        if (org_dir(org_id) / "org.json").exists():
            org = load(org_id)
            ks = KekStore(org_id)
            held = {v: orgkeys.fingerprint(k) for v, k in keyring(org_id).items()}
            for v, k in ring.items():
                if v in held and held[v] != orgkeys.fingerprint(k):
                    raise OrgError(f"Backup version {v} does not match this organization's key", 409)
                if v not in held:
                    ks.put(v, k)
                    org["versions"].append({"version": v, "fingerprint": orgkeys.fingerprint(k),
                                            "created": store.now(), "status": "restored"})
            org["versions"].sort(key=lambda x: x["version"])
            _save(org)
            return {"org": public(org), "restored": False, "verified_versions": sorted(ring)}
        token = secrets.token_urlsafe(32)
        ks = KekStore(org_id)
        for v, k in ring.items():
            ks.put(v, k)
        cur = max(ring)
        org = {
            "id": org_id, "name": info.get("org_name") or org_id, "created": store.now(),
            "current_version": cur,
            "versions": [{"version": v, "fingerprint": orgkeys.fingerprint(k), "created": store.now(),
                          "status": "active" if v == cur else "retired"} for v, k in sorted(ring.items())],
            "backups": [{"exported": info.get("created"), "versions": sorted(ring), "sha256":
                         hashlib.sha256(backup).hexdigest(), "restored_from": True}],
            "token_sha256": _token_hash(token), "migrations": [], "rotations": [],
        }
        _save(org)
    return {"org": public(org), "restored": True, "verified_versions": sorted(ring), "access_token": token}


def archives_of(org_id: str) -> list[str]:
    out = []
    for j in store.list_jobs():
        try:
            if (store.load(j["id"]).get("key_management") or {}).get("org_id") == org_id:
                out.append(j["id"])
        except (FileNotFoundError, ValueError):
            continue
    return out


# ------------------------------------------------------------------ archive keys


def wrap_for_archive(org_id: str, archive_id: str, deks: dict[str, bytes]) -> dict:
    v, kek = current(org_id)
    doc = orgkeys.wrap_keys(org_id, archive_id, v, kek, deks)
    # Prove the round trip before anything relies on it.
    if orgkeys.unwrap_keys(doc, {v: kek}) != deks:
        raise OrgError("Key wrapping self-check failed", 500)
    return {"mode": "organization", "org_id": org_id, "kek_version": v,
            "kek_fingerprint": doc["kek_fingerprint"], "wrapped_keys": doc, "wrapped": store.now()}


def unwrap_for_archive(km: dict) -> dict[str, bytes]:
    doc = km["wrapped_keys"]
    return orgkeys.unwrap_keys(doc, keyring(km["org_id"], [int(doc["kek_version"])]),
                               org_id=km["org_id"])


def rotate(org_id: str) -> dict:
    """New master-key version; re-wrap every archive's data keys under it (no DNA re-synthesis).
    The previous version is retired but kept, so Recovery Packages issued before the rotation
    stay recoverable with the backup that holds that version. Updated packages are issued for
    every re-wrapped archive."""
    from . import recovery_package

    with _lock:
        org = load(org_id)
        old = org["current_version"]
        new = max(v["version"] for v in org["versions"]) + 1
        kek = orgkeys.new_kek()
        KekStore(org_id).put(new, kek)
        for v in org["versions"]:
            if v["status"] == "active":
                v["status"] = "retired"
        org["versions"].append({"version": new, "fingerprint": orgkeys.fingerprint(kek),
                                "created": store.now(), "status": "active"})
        org["current_version"] = new
        _save(org)
    rewrapped, packages = [], []
    for jid in archives_of(org_id):
        job = store.load(jid)
        deks = unwrap_for_archive(job["key_management"])  # under the old version
        km = wrap_for_archive(org_id, jid, deks)
        if unwrap_for_archive(km) != deks:
            raise OrgError(f"Re-wrap verification failed for {jid}; nothing was replaced", 500)
        prev = job["key_management"]
        km["history"] = (prev.get("history") or []) + [
            {k: prev.get(k) for k in ("kek_version", "kek_fingerprint", "wrapped")}]
        store.update(jid, lambda j: j.update(key_management=km))
        rewrapped.append(jid)
        if job.get("order"):
            packages.append(recovery_package.build(jid)["revision"])
    rec = {"rotated": store.now(), "from_version": old, "to_version": new, "archives_rewrapped": rewrapped}
    with _lock:
        org = load(org_id)
        org["rotations"].append(rec)
        _save(org)
    return {**rec, "recovery_packages_reissued": len(packages),
            "backup_required": True,
            "note": f"Export a new backup that includes version {new}. Packages issued before this rotation "
                    f"still need the backup holding version {old}."}


def migrate_legacy(org_id: str, archive_id: str, *, delete_legacy_keys: bool = False) -> dict:
    """Wrap a legacy archive's per-file keys under the organization's current master key.

    Order of operations: read legacy keys -> wrap -> verify unwrap equals the legacy keys -> run an
    independent decode of the archive's clean DNA with the *wrapped* keys -> only then switch the
    archive to organization key management. Legacy key files are kept unless delete_legacy_keys is
    set, and even then only after the decode verified every file."""
    from . import artifacts, decoder, experiment, recovery_package

    job = store.load(archive_id)
    if (job.get("key_management") or {}).get("mode") == "organization":
        raise OrgError("This archive already uses organization key management", 409)
    if not job.get("order"):
        raise OrgError("Only approved archives can be migrated", 409)
    legacy = {f["key_id"]: artifacts.get_key(archive_id, f["key_id"]) for f in job["sealed"].values()}
    km = wrap_for_archive(org_id, archive_id, legacy)
    unwrapped = unwrap_for_archive(km)
    if unwrapped != legacy:
        raise OrgError("Wrapped keys do not match the legacy keys; migration stopped", 500)
    experiment.build_clean_export(archive_id)
    clean = artifacts.download(archive_id, experiment.PRE_FASTA)
    report, _ = decoder.run(decoder.DecodeRequest(
        fasta_bytes=clean, fasta_name="pre_simulation.fasta", decoders=["baseline"],
        key_for=unwrapped.get, key_source="organization-wrapped keys (migration check)",
        mode="migration_check", expected_archive_id=archive_id))
    if report["verdict"] != "PASS":
        raise OrgError(f"Recovery verification with the wrapped keys returned {report['verdict']}; "
                       "the archive was not migrated and its legacy keys are unchanged", 409)
    km["migrated_from"] = "legacy per-archive key store"
    km["migration_verified"] = {"verdict": report["verdict"], "checked": store.now(),
                                "files_verified": sum(f["verified"] for f in report["files"])}
    store.update(archive_id, lambda j: j.update(key_management=km))
    deleted = False
    if delete_legacy_keys:
        kms = store.job_dir(archive_id) / "kms"
        for kid in legacy:
            (kms / f"{kid}.key").unlink(missing_ok=True)
        deleted = True
    pkg = recovery_package.build(archive_id)
    rec = {"archive_id": archive_id, "migrated": store.now(), "kek_version": km["kek_version"],
           "verification": "PASS", "legacy_keys_deleted": deleted}
    with _lock:
        org = load(org_id)
        org["migrations"].append(rec)
        _save(org)
    return {**rec, "recovery_package_revision": pkg["revision"],
            "note": "Legacy key files exported earlier still work with this archive's older Recovery "
                    "Packages; the new package needs your organization master key backup instead."}
