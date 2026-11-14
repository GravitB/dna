"""Organization master keys (KEKs) and envelope encryption of archive data keys (DEKs).

Pure functions only: no server state, no network. This module ships inside every Recovery Package
so a future reader can unwrap archive keys without Lazarus.

    organization master key (KEK, 256-bit, versioned)
        └─ wraps, with AES-256-GCM ─> each archive file's data key (DEK, 256-bit, unique per file)
                                        └─ encrypts, with AES-256-GCM ─> the zstd-compressed file

Wrapped key = AES-256-GCM(KEK_v, nonce=96 random bits, plaintext=DEK, aad=wrap_aad(...)).
The AAD binds every wrapped key to its organization, archive, key id and master-key version, so a
wrapped key copied into another archive or presented under another version fails authentication.

Master-key backup = the organization's key ring (one or more versions) encrypted under a key
derived from a passphrase with scrypt (N=2^15, r=8, p=1), AES-256-GCM, AAD bound to the org id and
the versions it contains. The raw master key is never written anywhere except this encrypted form
and the server's key store.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

KEK_BYTES = 32
WRAPPED_FORMAT = "lazarus-wrapped-keys-v1"
BACKUP_FORMAT = "lazarus-org-master-key-v1"
WRAP_ALGORITHM = "AES-256-GCM (96-bit random nonce, 128-bit tag) over the raw 256-bit data key"
MIN_PASSPHRASE = 12
SCRYPT = {"n": 2**15, "r": 8, "p": 1}


class KeyError_(ValueError):
    """A key problem the user can act on. The message never contains key material."""


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def unb64(s: str) -> bytes:
    return base64.b64decode(s, validate=True)


def new_kek() -> bytes:
    return AESGCM.generate_key(bit_length=256)  # os.urandom under the hood (CSPRNG)


def fingerprint(kek: bytes) -> str:
    """Non-secret identifier of a master key: HMAC-SHA256(kek, label), first 128 bits in hex.
    Lets a reader check that a backup matches a package without revealing anything usable."""
    return hmac.new(kek, b"lazarus-kek-fingerprint-v1", hashlib.sha256).hexdigest()[:32]


def check_passphrase(passphrase: str | None) -> str:
    p = passphrase or ""
    if len(p) < MIN_PASSPHRASE or len(set(p)) < 6:
        raise KeyError_(f"Use a strong passphrase: at least {MIN_PASSPHRASE} characters with some variety "
                        "(a few unrelated words works well).")
    return p


# ------------------------------------------------------------------ wrapping


def wrap_aad(org_id: str, archive_id: str, key_id: str, kek_version: int) -> bytes:
    return json.dumps({"format": WRAPPED_FORMAT, "org_id": org_id, "archive_id": archive_id,
                       "key_id": key_id, "kek_version": int(kek_version)},
                      sort_keys=True, separators=(",", ":")).encode()


def wrap_keys(org_id: str, archive_id: str, kek_version: int, kek: bytes, deks: dict[str, bytes]) -> dict:
    """Wrapped-keys document for one archive. Fresh random nonce per wrapped key."""
    if len(kek) != KEK_BYTES:
        raise ValueError("master key must be 256 bits")
    keys = {}
    for key_id, dek in sorted(deks.items()):
        nonce = os.urandom(12)
        ct = AESGCM(kek).encrypt(nonce, dek, wrap_aad(org_id, archive_id, key_id, kek_version))
        keys[key_id] = {"nonce": b64(nonce), "wrapped": b64(ct)}
    return {
        "format": WRAPPED_FORMAT,
        "org_id": org_id,
        "archive_id": archive_id,
        "kek_version": int(kek_version),
        "kek_fingerprint": fingerprint(kek),
        "algorithm": WRAP_ALGORITHM,
        "aad": "canonical JSON {format, org_id, archive_id, key_id, kek_version}, sorted keys, no spaces",
        "keys": keys,
    }


def unwrap_keys(doc: dict, keyring: dict[int, bytes], *, org_id: str | None = None,
                archive_id: str | None = None) -> dict[str, bytes]:
    """Unwrap every data key in a wrapped-keys document. Raises KeyError_ with an actionable
    message (wrong organization, missing version, wrong key) and never returns partial results."""
    if not isinstance(doc, dict) or doc.get("format") != WRAPPED_FORMAT:
        raise KeyError_("Not a Lazarus wrapped-keys document.")
    if org_id is not None and doc.get("org_id") != org_id:
        raise KeyError_(f"These archive keys belong to organization {doc.get('org_id')}, "
                        f"not {org_id}.")
    if archive_id is not None and doc.get("archive_id") != archive_id:
        raise KeyError_("The wrapped keys belong to a different archive.")
    v = int(doc["kek_version"])
    kek = keyring.get(v)
    if kek is None:
        have = ", ".join(str(x) for x in sorted(keyring)) or "none"
        raise KeyError_(f"This archive's keys are wrapped with master-key version {v}; the supplied "
                        f"master key backup holds version(s) {have}. Use the backup that contains version {v}, "
                        "or an updated Recovery Package that was re-wrapped under your current version.")
    if fingerprint(kek) != doc.get("kek_fingerprint"):
        raise KeyError_(f"The supplied master key (version {v}) is not the key these archive keys were "
                        "wrapped with (fingerprint differs).")
    out = {}
    for key_id, w in doc["keys"].items():
        try:
            out[key_id] = AESGCM(kek).decrypt(unb64(w["nonce"]), unb64(w["wrapped"]),
                                              wrap_aad(doc["org_id"], doc["archive_id"], key_id, v))
        except (InvalidTag, ValueError, KeyError, TypeError):
            raise KeyError_(f"Wrapped key {key_id} failed authentication (wrong master key or tampered "
                            "package).") from None
    return out


# ------------------------------------------------------------------ passphrase-protected backup


def _kdf(salt: bytes, n: int = SCRYPT["n"], r: int = SCRYPT["r"], p: int = SCRYPT["p"]) -> Scrypt:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p)


def _backup_aad(org_id: str, versions: list[int]) -> bytes:
    return f"{BACKUP_FORMAT}:{org_id}:{','.join(str(v) for v in sorted(versions))}".encode()


def make_backup(org_id: str, org_name: str, keyring: dict[int, bytes], passphrase: str, created: str) -> bytes:
    check_passphrase(passphrase)
    if not keyring:
        raise ValueError("empty key ring")
    salt, nonce = os.urandom(16), os.urandom(12)
    versions = sorted(keyring)
    body = json.dumps({str(v): b64(keyring[v]) for v in versions}).encode()
    ct = AESGCM(_kdf(salt).derive(passphrase.encode())).encrypt(nonce, body, _backup_aad(org_id, versions))
    return json.dumps({
        "format": BACKUP_FORMAT,
        "org_id": org_id,
        "org_name": org_name,
        "created": created,
        "versions": [{"version": v, "fingerprint": fingerprint(keyring[v])} for v in versions],
        "kdf": {"name": "scrypt", **SCRYPT, "salt": b64(salt)},
        "cipher": "AES-256-GCM",
        "nonce": b64(nonce),
        "ciphertext": b64(ct),
        "warning": "Organization master key backup. Anyone with this file AND its passphrase can unlock "
                   "every archive protected by these key versions. Keep copies offline, in separate places.",
    }, indent=2).encode()


def open_backup(data: bytes, passphrase: str) -> tuple[dict, dict[int, bytes]]:
    """(public info, keyring). Verifies each key against its recorded fingerprint."""
    try:
        doc = json.loads(data)
        if not isinstance(doc, dict) or doc.get("format") != BACKUP_FORMAT:
            raise ValueError()
        kdf = doc["kdf"]
        if kdf.get("name") != "scrypt" or not (2**14 <= int(kdf["n"]) <= 2**20):
            raise ValueError()
        versions = [int(v["version"]) for v in doc["versions"]]
        salt, nonce, ct = unb64(kdf["salt"]), unb64(doc["nonce"]), unb64(doc["ciphertext"])
        org_id = str(doc["org_id"])
    except (ValueError, KeyError, TypeError):
        raise KeyError_("Not a Lazarus organization master key backup.") from None
    try:
        key = _kdf(salt, int(kdf["n"]), int(kdf["r"]), int(kdf["p"])).derive((passphrase or "").encode())
        body = AESGCM(key).decrypt(nonce, ct, _backup_aad(org_id, versions))
    except InvalidTag:
        raise KeyError_("Wrong passphrase for this master key backup (or the file was modified).") from None
    ring = {int(v): unb64(k) for v, k in json.loads(body).items()}
    for v in doc["versions"]:
        k = ring.get(int(v["version"]))
        if k is None or len(k) != KEK_BYTES or fingerprint(k) != v["fingerprint"]:
            raise KeyError_("Master key backup is internally inconsistent (fingerprint mismatch).")
    info = {k: doc.get(k) for k in ("org_id", "org_name", "created", "versions")}
    return info, ring
