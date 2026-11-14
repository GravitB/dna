"""Keys and downloadable artifacts, with Supabase as the authority in cloud mode."""

from pathlib import Path

from . import store
from .persistence import get_cloud, valid_path, StorageError


def key_name(key_id):
    if not key_id or Path(key_id).name != key_id or ".." in key_id or "\\" in key_id:
        raise ValueError("Invalid archive key identifier")
    return key_id


def put_key(jid, key_id, key):
    key_name(key_id)
    cloud = get_cloud()
    if cloud:
        cloud.put_key(jid, key_id, key)
    else:
        d = store.ensure_dirs(jid) / "kms"
        path = d / f"{key_id}.key"
        path.write_bytes(key)
        path.chmod(0o600)


def get_key(jid, key_id):
    key_name(key_id)
    cloud = get_cloud()
    if cloud:
        return cloud.get_key(jid, key_id)
    return (store.job_dir(jid) / "kms" / f"{key_id}.key").read_bytes()


def publish(jid, path, data):
    valid_path(path)
    cloud = get_cloud()
    if cloud:
        cloud.put_artifact(jid, path, data)
    target = store.ensure_dirs(jid) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def download(jid, path):
    valid_path(path)
    job = store.load(jid)
    if path.startswith("vaults/"):
        if not job.get("order") or path not in job["order"]["order_files"]:
            raise FileNotFoundError("DNA artifact is not committed")
        vault_id = path.split("/")[1].removeprefix("vault-")
        if job.get("vault_locations", {}).get(vault_id) == "destroyed":
            raise FileNotFoundError("Simulated storage location is unavailable")
    elif path == "certificate.html":
        if not job.get("certificate") or job["status"] == "recovering":
            raise FileNotFoundError("No current recovery report")
    elif path.startswith("restored/"):
        latest = job["drills"][-1] if job["drills"] else None
        name = path.removeprefix("restored/")
        if (
            job["status"] == "recovering"
            or not latest
            or not any(f["name"] == name and f["sha256_match"] for f in latest["files"])
        ):
            raise FileNotFoundError("No currently verified restored file")
    cloud = get_cloud()
    if cloud:
        return cloud.get_artifact(jid, path)
    return (store.job_dir(jid) / path).read_bytes()


def verify_order(jid):
    job = store.load(jid)
    if not job.get("order"):
        raise StorageError("A successful archive order is required.")
    cloud = get_cloud()
    if not cloud:
        return
    if job.get("storage", {}).get("state") != "saved":
        raise StorageError(
            "Save and verify the cloud archive before deleting working copies."
        )
    for path in job["order"]["order_files"]:
        cloud.get_artifact(jid, path)
    for f in job["sealed"].values():
        cloud.get_key(jid, f["key_id"])
