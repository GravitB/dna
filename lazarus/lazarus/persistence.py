"""Server-only Supabase persistence. No local fallback when cloud storage is selected."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import uuid
from functools import lru_cache
from pathlib import PurePosixPath
from urllib.parse import quote, urlparse

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class StorageError(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class RevisionConflict(StorageError):
    pass


def valid_path(path: str) -> str:
    parts = PurePosixPath(path).parts
    allowed = path == "certificate.html" or (
        len(parts) >= 2 and parts[0] in ("vaults", "restored", "candidates", "candidate-evidence", "learning")
    )
    if (
        not allowed
        or "\\" in path
        or path.startswith("/")
        or any(p in ("", ".", "..") for p in path.split("/"))
    ):
        raise ValueError("Invalid archive artifact path")
    return path


class SupabaseStore:
    def __init__(
        self,
        url: str,
        secret: str,
        master: str,
        bucket="lazarus-archives",
        *,
        transport=None,
    ):
        parsed = urlparse(url)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
        ):
            raise StorageError(
                "SUPABASE_URL must use HTTPS (except a local Supabase server)."
            )
        if (
            not parsed.netloc
            or parsed.path not in ("", "/")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise StorageError(
                "SUPABASE_URL must be a project origin without credentials or a path."
            )
        if not secret:
            raise StorageError("SUPABASE_SECRET_KEY is required for cloud storage.")
        try:
            self.master = base64.b64decode(master, validate=True)
        except (ValueError, TypeError):
            raise StorageError(
                "LAZARUS_KEY_ENCRYPTION_KEY must be a base64-encoded 32-byte key."
            ) from None
        if len(self.master) != 32:
            raise StorageError(
                "LAZARUS_KEY_ENCRYPTION_KEY must be a base64-encoded 32-byte key."
            )
        if bucket != "lazarus-archives":
            raise StorageError(
                "This schema requires the private lazarus-archives bucket."
            )
        self.bucket = bucket
        self.key_fingerprint = hashlib.sha256(self.master).hexdigest()[:16]
        headers = {"apikey": secret}
        # Legacy service_role JWTs need the Authorization header. New secret keys use apikey.
        if secret.startswith("eyJ"):
            try:
                payload = secret.split(".")[1]
                role = json.loads(
                    base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
                )["role"]
                if role != "service_role":
                    raise ValueError()
            except (ValueError, KeyError, IndexError):
                raise StorageError(
                    "Use a backend secret key or legacy service_role key, not an anonymous key."
                ) from None
            headers["Authorization"] = f"Bearer {secret}"
        elif not secret.startswith("sb_secret_"):
            raise StorageError(
                "Use a Supabase backend secret key, not a publishable key."
            )
        self.client = httpx.Client(
            base_url=url.rstrip("/"), headers=headers, timeout=30, transport=transport
        )

    def request(self, method, path, *, retry=False, **kwargs):
        for attempt in range(3 if retry else 1):
            try:
                response = self.client.request(method, path, **kwargs)
                if response.status_code == 409:
                    raise RevisionConflict(
                        "Cloud archive changed. Reload and retry the operation."
                    )
                if response.status_code >= 500 and retry and attempt < 2:
                    time.sleep(0.1 * (attempt + 1))
                    continue
                if not response.is_success:
                    # Never include response bodies, headers, URLs, or credentials in user-visible errors.
                    raise StorageError(
                        f"Supabase request failed (HTTP {response.status_code}). Check configuration and retry.",
                        status_code=response.status_code,
                    )
                return response
            except httpx.TransportError:
                if retry and attempt < 2:
                    time.sleep(0.1 * (attempt + 1))
                    continue
                raise StorageError(
                    "Cannot reach Supabase. Retry when the connection is available."
                ) from None

    def rows(self, table, params=None):
        result = []
        offset = 0
        while True:
            page = self.request(
                "GET",
                f"/rest/v1/{table}",
                params={**(params or {}), "limit": 500, "offset": offset},
                retry=True,
            ).json()
            result.extend(page)
            if len(page) < 500:
                return result
            offset += len(page)

    def load(self, jid):
        rows = self.rows("lazarus_jobs", {"id": f"eq.{jid}", "select": "data,revision"})
        if not rows:
            raise FileNotFoundError("Archive not found")
        return rows[0]["data"], rows[0]["revision"]

    def save(self, jid, data, revision):
        # Do not retry a non-idempotent CAS write: the server may have committed it.
        return self.request(
            "POST",
            "/rest/v1/rpc/lazarus_save",
            json={"p_id": jid, "p_data": data, "p_revision": revision},
        ).json()

    def list_jobs(self):
        return [
            row["data"]
            for row in self.rows(
                "lazarus_jobs", {"select": "data", "order": "created_at.desc,id.desc"}
            )
        ]

    def append_event(self, jid, event, event_id=None):
        return self.request(
            "POST",
            "/rest/v1/rpc/lazarus_append_event",
            retry=True,
            json={
                "p_id": jid,
                "p_event_id": event_id or str(uuid.uuid4()),
                "p_payload": event,
            },
        ).json()

    def events(self, jid, since=0):
        return [
            row["payload"]
            for row in self.rows(
                "lazarus_events",
                {
                    "job_id": f"eq.{jid}",
                    "seq": f"gte.{since}",
                    "order": "seq.asc",
                    "select": "payload",
                },
            )
        ]

    def upsert(self, table, row, conflict):
        self.request(
            "POST",
            f"/rest/v1/{table}",
            retry=True,
            params={"on_conflict": conflict},
            headers={"Prefer": "resolution=merge-duplicates"},
            json=row,
        )

    def put_key(self, jid, key_id, key):
        nonce = os.urandom(12)
        aad = f"lazarus-key-v1:{jid}:{key_id}".encode()
        envelope = {
            "version": 1,
            "key_fingerprint": self.key_fingerprint,
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(
                AESGCM(self.master).encrypt(nonce, key, aad)
            ).decode(),
        }
        self.upsert(
            "lazarus_keys",
            {"job_id": jid, "key_id": key_id, "envelope": envelope},
            "job_id,key_id",
        )
        if self.get_key(jid, key_id) != key:
            raise StorageError("Cloud encryption key verification failed.")

    def get_key(self, jid, key_id):
        rows = self.rows(
            "lazarus_keys",
            {"job_id": f"eq.{jid}", "key_id": f"eq.{key_id}", "select": "envelope"},
        )
        if not rows:
            raise StorageError("The archive encryption key is missing from Supabase.")
        envelope = rows[0]["envelope"]
        try:
            if (
                envelope["version"] != 1
                or envelope["key_fingerprint"] != self.key_fingerprint
            ):
                raise ValueError()
            key = AESGCM(self.master).decrypt(
                base64.b64decode(envelope["nonce"]),
                base64.b64decode(envelope["ciphertext"]),
                f"lazarus-key-v1:{jid}:{key_id}".encode(),
            )
            if len(key) != 32:
                raise ValueError()
            return key
        except (InvalidTag, ValueError, KeyError, TypeError):
            raise StorageError(
                "Cannot unlock archive keys. Restore the original master key; do not generate a replacement."
            ) from None

    def artifact(self, jid, path):
        valid_path(path)
        rows = self.rows(
            "lazarus_artifacts", {"job_id": f"eq.{jid}", "path": f"eq.{path}"}
        )
        if not rows:
            raise FileNotFoundError("Archive artifact not found")
        return rows[0]

    def object_url(self, key):
        return (
            f"/storage/v1/object/{quote(self.bucket, safe='')}/{quote(key, safe='/')}"
        )

    def put_artifact(self, jid, path, data):
        valid_path(path)
        digest = hashlib.sha256(data).hexdigest()
        # Content-addressed objects make retries safe and preserve earlier report evidence.
        key = f"{jid}/{digest}/{path}"
        self.request(
            "POST",
            self.object_url(key),
            content=data,
            retry=True,
            headers={"Content-Type": "application/octet-stream", "x-upsert": "true"},
        )
        downloaded = self.request("GET", self.object_url(key), retry=True).content
        if hashlib.sha256(downloaded).hexdigest() != digest:
            raise StorageError(
                "Supabase artifact checksum verification failed. Working copies were retained."
            )
        self.upsert(
            "lazarus_artifacts",
            {
                "job_id": jid,
                "path": path,
                "object_key": key,
                "sha256": digest,
                "bytes": len(data),
            },
            "job_id,path",
        )

    def get_artifact(self, jid, path):
        row = self.artifact(jid, path)
        data = self.request(
            "GET", self.object_url(row["object_key"]), retry=True
        ).content
        if (
            len(data) != row["bytes"]
            or hashlib.sha256(data).hexdigest() != row["sha256"]
        ):
            raise StorageError("Supabase artifact checksum mismatch. Recovery stopped.")
        return data

    def check(self):
        try:
            self.rows("lazarus_jobs", {"select": "id", "limit": 1})
        except StorageError as exc:
            if exc.status_code == 404:
                raise StorageError(
                    "Archive tables are not installed. Run lazarus-cloud setup with SUPABASE_DB_URL, or apply the migration in the SQL Editor."
                ) from None
            raise
        bucket = self.request(
            "GET", f"/storage/v1/bucket/{quote(self.bucket, safe='')}", retry=True
        ).json()
        if bucket.get("public") is not False:
            raise StorageError("The Lazarus Supabase bucket must be private.")

        keys = self.request(
            "GET",
            "/rest/v1/lazarus_keys",
            params={"select": "job_id,key_id", "limit": 1},
            retry=True,
        ).json()
        if keys:
            self.get_key(keys[0]["job_id"], keys[0]["key_id"])

    def ensure_bucket(self, check_schema=True):
        r = self.client.get(f"/storage/v1/bucket/{quote(self.bucket, safe='')}")
        if r.status_code == 404 or (
            r.status_code == 400 and r.json().get("message") == "Bucket not found"
        ):
            self.request(
                "POST",
                "/storage/v1/bucket",
                json={"id": self.bucket, "name": self.bucket, "public": False},
            )
        elif not r.is_success:
            raise StorageError(
                "Cannot inspect Supabase bucket. Check backend credentials."
            )
        if check_schema:
            self.check()
        else:
            data = self.request(
                "GET", f"/storage/v1/bucket/{quote(self.bucket, safe='')}"
            ).json()
            if data.get("public") is not False:
                raise StorageError("The archive bucket must be private.")


@lru_cache(maxsize=1)
def _configured(url, secret, master, bucket):
    return SupabaseStore(url, secret, master, bucket)


def get_cloud():
    backend = os.environ.get("LAZARUS_STORAGE_BACKEND", "local")
    if backend == "local":
        return None
    if backend != "supabase":
        raise StorageError("LAZARUS_STORAGE_BACKEND must be local or supabase.")
    return _configured(
        os.environ.get("SUPABASE_URL", ""),
        os.environ.get("SUPABASE_SECRET_KEY", ""),
        os.environ.get("LAZARUS_KEY_ENCRYPTION_KEY", ""),
        os.environ.get("SUPABASE_STORAGE_BUCKET", "lazarus-archives"),
    )
