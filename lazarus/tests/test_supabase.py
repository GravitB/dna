"""Exercise the real HTTP storage adapter against a deterministic Supabase protocol double."""

import base64
import copy
import json
import shutil

import httpx
import pytest

from lazarus import artifacts, persistence, store, tools, vaults
from lazarus.cloud_cli import keygen, import_archive


class SupabaseProtocol:
    def __init__(self):
        self.tables = {
            n: []
            for n in (
                "lazarus_jobs",
                "lazarus_events",
                "lazarus_artifacts",
                "lazarus_keys",
            )
        }
        self.objects = {}
        self.private = True
        self.fail_upload = False
        self.offline = False
        self.conflict = False
        self.retried_event = False

    def handle(self, r):
        if self.offline:
            raise httpx.ConnectError("unavailable", request=r)
        path = r.url.path
        body = (
            json.loads(r.content)
            if r.content
            and r.headers.get("content-type", "").startswith("application/json")
            else None
        )

        def reply(data, status=200):
            return httpx.Response(status, json=copy.deepcopy(data))

        if path.startswith("/storage/v1/bucket/"):
            return reply({"id": "lazarus-archives", "public": not self.private})
        if path.startswith("/storage/v1/object/"):
            if r.method == "POST":
                if self.fail_upload:
                    return reply({"message": "upload failed"}, 503)
                self.objects[path] = r.content
                return reply({"Key": path})
            if path not in self.objects:
                return reply({}, 404)
            return httpx.Response(200, content=self.objects[path])
        table = path.split("/")[-1]
        if table == "lazarus_save":
            rows = self.tables["lazarus_jobs"]
            row = next((x for x in rows if x["id"] == body["p_id"]), None)
            if self.conflict and row:
                self.conflict = False
                row["revision"] += 1
                row["data"]["concurrent"] = "preserved"
                return reply({}, 409)
            if (row is None and body["p_revision"] != 0) or (
                row and row["revision"] != body["p_revision"]
            ):
                return reply({}, 409)
            if row is None:
                row = {"id": body["p_id"], "revision": 0}
                rows.append(row)
            row["data"] = body["p_data"]
            row["revision"] += 1
            return reply(row["revision"])
        if table == "lazarus_append_event":
            rows = self.tables["lazarus_events"]
            old = next((x for x in rows if x["event_id"] == body["p_event_id"]), None)
            if old:
                return reply(old["payload"])
            seq = len([x for x in rows if x["job_id"] == body["p_id"]])
            payload = {**body["p_payload"], "seq": seq}
            rows.append(
                {
                    "job_id": body["p_id"],
                    "event_id": body["p_event_id"],
                    "seq": seq,
                    "payload": payload,
                }
            )
            if self.retried_event:
                self.retried_event = False
                raise httpx.ReadError("response lost after commit", request=r)
            return reply(payload)
        if table not in self.tables:
            return reply({}, 404)
        if r.method == "POST":
            fields = r.url.params["on_conflict"].split(",")
            rows = self.tables[table]
            old = next((x for x in rows if all(x[k] == body[k] for k in fields)), None)
            if old:
                old.update(body)
            else:
                rows.append(body)
            return reply(None, 201)
        rows = self.tables[table]
        for key, value in r.url.params.items():
            if value.startswith("eq."):
                rows = [x for x in rows if str(x.get(key)) == value[3:]]
            if value.startswith("gte."):
                rows = [x for x in rows if x.get(key, -1) >= int(value[4:])]
        if r.url.params.get("order", "").startswith("seq"):
            rows = sorted(rows, key=lambda x: x["seq"])
        offset = int(r.url.params.get("offset", 0))
        limit = int(r.url.params.get("limit", 500))
        return reply(rows[offset : offset + limit])


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    protocol = SupabaseProtocol()
    client = persistence.SupabaseStore(
        "https://test.supabase.co",
        "sb_secret_test",
        base64.b64encode(bytes(32)).decode(),
        transport=httpx.MockTransport(protocol.handle),
    )
    monkeypatch.setenv("LAZARUS_STORAGE_BACKEND", "supabase")
    monkeypatch.setattr(persistence, "_configured", lambda *a: client)
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path / "computer-a")
    monkeypatch.setattr(store, "_versions", {})
    monkeypatch.setattr(store, "_events", {})
    yield client, protocol
    client.client.close()


def job():
    return store.new_job(
        "Cloud test",
        {
            "retention_years": 50,
            "tech": "nanopore",
            "coverage": 10,
            "budget_usd": 100,
            "target": 1,
            "n_vaults": 3,
        },
    )


def test_cloud_state_events_retry_and_cas(cloud):
    c, p = cloud
    jid = job()
    p.conflict = True
    store.update(jid, lambda j: j.update(name="Cloud archive"))
    assert store.load(jid)["concurrent"] == "preserved"
    p.retried_event = True
    store.emit(jid, "message", "human", {"text": "one"})
    store.emit(jid, "message", "human", {"text": "two"})
    assert [e["seq"] for e in store.events_since(jid, 0, 0)] == [0, 1]
    assert len(store.list_jobs()) == 1
    assert not (store.job_dir(jid) / "job.json").exists()
    assert not (store.job_dir(jid) / "events.jsonl").exists()


def test_keys_encrypted_and_bound_to_archive(cloud):
    c, p = cloud
    jid = job()
    key = bytes(range(32))
    artifacts.put_key(jid, "key-one", key)
    assert artifacts.get_key(jid, "key-one") == key
    encoded = json.dumps(p.tables["lazarus_keys"])
    assert base64.b64encode(key).decode() not in encoded and key.hex() not in encoded
    assert not list((store.job_dir(jid) / "kms").iterdir())
    row = p.tables["lazarus_keys"][0]
    row["key_id"] = "key-two"
    with pytest.raises(persistence.StorageError, match="original master key"):
        c.get_key(jid, "key-two")
    row["key_id"] = "key-one"
    old = c.master
    c.master = bytes([1]) * 32
    with pytest.raises(persistence.StorageError):
        c.get_key(jid, "key-one")
    c.master = old


def test_artifact_roundtrip_checksum_and_missing_remote_never_use_cache(cloud):
    c, p = cloud
    jid = job()
    path = "vaults/vault-1/order.fasta"
    store.update(
        jid,
        lambda j: j.update(
            order={"order_files": [path]}, vault_locations={"1": "healthy"}
        ),
    )
    artifacts.publish(jid, path, b">pool|0\nACGT\n")
    assert artifacts.download(jid, path) == b">pool|0\nACGT\n"
    key = next(iter(p.objects))
    p.objects[key] = b"corrupt"
    with pytest.raises(persistence.StorageError, match="checksum"):
        artifacts.download(jid, path)
    del p.objects[key]
    with pytest.raises(persistence.StorageError):
        artifacts.download(jid, path)


def test_failed_cloud_upload_prevents_primary_destruction(cloud):
    c, p = cloud
    jid = job()
    d = store.job_dir(jid)
    (d / "uploads" / "record.txt").write_bytes(b"final record" * 100)
    assert "error" not in tools.prepare_archive(job_id=jid, file_names=["record.txt"])
    p.fail_upload = True
    r = tools.place_synthesis_order(job_id=jid, redundancy=1.6, coverage=10)
    assert "error" in r and store.load(jid)["order"] is None
    assert store.load(jid)["storage"]["state"] == "failed"
    assert "error" in tools.destroy_primary(job_id=jid)
    assert (d / "uploads" / "record.txt").exists()


def test_portable_recovery_from_empty_computer_and_simulated_loss(
    cloud, tmp_path, monkeypatch
):
    c, p = cloud
    jid = job()
    d = store.job_dir(jid)
    data = b"Final immutable record with important business data.\n" * 200
    (d / "uploads" / "record.txt").write_bytes(data)
    assert "error" not in tools.prepare_archive(job_id=jid, file_names=["record.txt"])
    order = tools.place_synthesis_order(job_id=jid, redundancy=1.6, coverage=15)
    assert "error" not in order
    assert "error" not in tools.destroy_primary(job_id=jid)
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path / "computer-b")
    store._versions.clear()
    store._events.clear()
    shutil.rmtree(d)
    assert store.load(jid)["storage"]["state"] == "saved"
    count = len(p.objects)
    assert vaults.destroy_vault(store.job_dir(jid), 2)
    assert len(p.objects) == count
    assert vaults.read_vault(store.job_dir(jid), 2) is None
    result = tools.recover_archive(job_id=jid, coverage=20)
    if not result["all_verified"]:
        result = tools.recover_archive(job_id=jid, attempt=1, coverage=30)
    assert result["all_verified"], result
    assert result["vaults_available"] == [1, 3]
    assert artifacts.download(jid, "restored/record.txt") == data
    tools.write_certificate(job_id=jid, summary="Verified cloud recovery")
    assert b"Verified cloud recovery" in artifacts.download(jid, "certificate.html")
    # A later failed drill cannot serve the old report or restored plaintext.
    vaults.destroy_vault(store.job_dir(jid), 1)
    vaults.destroy_vault(store.job_dir(jid), 3)
    assert not tools.recover_archive(job_id=jid)["all_verified"]
    with pytest.raises(FileNotFoundError):
        artifacts.download(jid, "certificate.html")
    with pytest.raises(FileNotFoundError):
        artifacts.download(jid, "restored/record.txt")


def test_offline_backend_does_not_fall_back(cloud):
    c, p = cloud
    jid = job()
    p.offline = True
    with pytest.raises(persistence.StorageError, match="Cannot reach"):
        store.load(jid)
    assert not (store.job_dir(jid) / "job.json").exists()


@pytest.mark.parametrize(
    "path",
    [
        "../kms/x",
        "kms/key.key",
        "/vaults/x",
        "restored/../kms/x",
        "restored//x",
        "restored/./x",
        "vaults\\x",
    ],
)
def test_private_paths_not_artifacts(path):
    with pytest.raises(ValueError):
        persistence.valid_path(path)


def test_keygen_preserves_existing_master(tmp_path):
    env = tmp_path / ".env"
    keygen(env)
    first = env.read_bytes()
    keygen(env)
    assert env.read_bytes() == first
    assert env.stat().st_mode & 0o777 == 0o600


def test_public_bucket_is_rejected(cloud):
    c, p = cloud
    p.private = False
    with pytest.raises(persistence.StorageError, match="private"):
        c.check()


def test_local_import_is_repeatable_and_preserves_originals(cloud, tmp_path):
    c, p = cloud
    source = tmp_path / "local-archive"
    source.mkdir()
    key = b"k" * 32
    (source / "kms").mkdir()
    (source / "kms/key-one.key").write_bytes(key)
    files = []
    for v in (1, 2, 3):
        d = source / f"vaults/vault-{v}"
        d.mkdir(parents=True)
        for ext in ("fasta", "csv"):
            path = f"vaults/vault-{v}/order.{ext}"
            (source / path).write_bytes(b"ACGT")
            files.append(path)
    data = {
        "id": "local-archive",
        "company": "Import test",
        "created": store.now(),
        "status": "ordered",
        "files": [],
        "sealed": {"record": {"key_id": "key-one"}},
        "policy": {},
        "drills": [],
        "order": {"settings": {"n_vaults": 3}, "order_files": files},
    }
    (source / "job.json").write_text(json.dumps(data))
    (source / "events.jsonl").write_text(
        json.dumps({"seq": 0, "type": "message", "data": {"text": "original"}}) + "\n"
    )
    assert import_archive(c, source) == "local-archive"
    count = len(p.objects)
    assert import_archive(c, source) == "local-archive"
    assert len(p.objects) == count and len(c.events("local-archive")) == 1
    assert (source / "kms/key-one.key").read_bytes() == key
    assert c.load("local-archive")[0]["storage"]["state"] == "saved"
    data["company"] = "changed"
    (source / "job.json").write_text(json.dumps(data))
    with pytest.raises(persistence.StorageError, match="different data"):
        import_archive(c, source)


def test_invalid_cloud_configuration_never_falls_back(monkeypatch):
    persistence._configured.cache_clear()
    monkeypatch.setenv("LAZARUS_STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    monkeypatch.setenv("LAZARUS_KEY_ENCRYPTION_KEY", "")
    with pytest.raises(persistence.StorageError, match="32-byte"):
        persistence.get_cloud()
    monkeypatch.setenv("LAZARUS_STORAGE_BACKEND", "invalid")
    with pytest.raises(persistence.StorageError):
        persistence.get_cloud()


def test_cloud_error_is_sanitized_and_protected_downloads_stay_private(
    cloud, monkeypatch
):
    from fastapi.testclient import TestClient
    from lazarus.api import app

    c, p = cloud
    jid = job()
    with TestClient(app) as api:
        assert api.get(f"/api/jobs/{jid}/files/kms/private.key").status_code == 404
        p.offline = True
        response = api.get("/api/jobs")
        assert response.status_code == 503
        assert "sb_secret_" not in response.text and "headers" not in response.text
