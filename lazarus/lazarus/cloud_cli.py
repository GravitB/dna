"""Explicit provisioning, verification and non-destructive local archive import."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

from .persistence import SupabaseStore, StorageError

ROOT = Path(__file__).resolve().parents[2]


def cloud_from_env():
    return SupabaseStore(
        os.environ.get("SUPABASE_URL", ""),
        os.environ.get("SUPABASE_SECRET_KEY", ""),
        os.environ.get("LAZARUS_KEY_ENCRYPTION_KEY", ""),
        os.environ.get("SUPABASE_STORAGE_BUCKET", "lazarus-archives"),
    )


def keygen(env_file):
    from dotenv import dotenv_values

    path = Path(env_file)
    if path.exists() and dotenv_values(path).get("LAZARUS_KEY_ENCRYPTION_KEY"):
        print("Master key already configured; it was not changed.")
        return
    key = base64.b64encode(os.urandom(32)).decode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(f"\nLAZARUS_KEY_ENCRYPTION_KEY={key}\n")
    path.chmod(0o600)
    print(
        "Master key saved to the local environment file. Back it up separately in a secure password manager."
    )


def setup(cloud):
    if not os.environ.get("SUPABASE_DB_URL"):
        raise StorageError(
            "SUPABASE_DB_URL is required to install archive tables. The API secret cannot perform database migrations."
        )
    try:
        import psycopg
    except ImportError:
        raise StorageError(
            "Install setup dependencies with: uv sync --group cloud-setup"
        ) from None
    migrations = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
    if not migrations:
        raise StorageError(
            "Migration files are missing. Run setup from a complete repository checkout."
        )
    try:
        with psycopg.connect(
            os.environ["SUPABASE_DB_URL"], connect_timeout=15, sslmode="require"
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("""create table if not exists public.lazarus_migrations (
                    name text primary key, sha256 text not null, applied_at timestamptz not null default now());
                    alter table public.lazarus_migrations enable row level security;
                    revoke all on public.lazarus_migrations from public, anon, authenticated;
                    grant all on public.lazarus_migrations to service_role;""")
                for migration in migrations:
                    sql = migration.read_text()
                    digest = hashlib.sha256(sql.encode()).hexdigest()
                    cur.execute(
                        "select sha256 from public.lazarus_migrations where name=%s",
                        (migration.name,),
                    )
                    old = cur.fetchone()
                    if old:
                        if old[0] != digest:
                            raise StorageError(
                                "An applied migration has changed. Restore it and add a new migration."
                            )
                        continue
                    cur.execute(sql)
                    cur.execute(
                        "insert into public.lazarus_migrations(name,sha256) values(%s,%s)",
                        (migration.name, digest),
                    )
        # PostgREST reloads automatically, with an explicit notification for immediate setup checks.
        with psycopg.connect(
            os.environ["SUPABASE_DB_URL"], connect_timeout=15, sslmode="require"
        ) as conn:
            conn.execute("notify pgrst, 'reload schema'")
    except StorageError:
        raise
    except Exception:
        raise StorageError(
            "Database setup failed. Check SUPABASE_DB_URL and database permissions; no credentials were logged."
        ) from None
    cloud.ensure_bucket()
    print("Archive tables installed and private storage bucket verified.")


def import_archive(cloud, source):
    source = Path(source)
    job = json.loads((source / "job.json").read_text())
    jid = job["id"]
    if source.name != jid or "/" in jid or ".." in jid:
        raise StorageError("Archive folder and job identifier must match.")
    if not job.get("order"):
        raise StorageError(
            "Archive is incomplete: a DNA order is required before import."
        )
    # Preflight everything before touching cloud data. Never erase the local archive.
    locations = {}
    files = []
    for v in range(1, job["order"]["settings"]["n_vaults"] + 1):
        fasta = source / f"vaults/vault-{v}/order.fasta"
        locations[str(v)] = "healthy" if fasta.is_file() else "destroyed"
        if fasta.is_file():
            for ext in ("fasta", "csv"):
                path = f"vaults/vault-{v}/order.{ext}"
                if not (source / path).is_file():
                    raise StorageError(
                        "Archive is incomplete: a surviving vault artifact is missing."
                    )
                files.append(path)
    if not any(s == "healthy" for s in locations.values()):
        raise StorageError("Archive has no surviving DNA vaults to import.")
    keys = {}
    for f in job["sealed"].values():
        key_id = f["key_id"]
        from .artifacts import key_name

        key_name(key_id)
        path = source / "kms" / f"{key_id}.key"
        if not path.is_file() or len(path.read_bytes()) != 32:
            raise StorageError(
                "Archive is incomplete: a recovery key is missing or invalid."
            )
        keys[key_id] = path.read_bytes()
    if job.get("certificate"):
        if not (source / "certificate.html").is_file():
            raise StorageError("Archive report is missing.")
        files.append("certificate.html")
    latest = job["drills"][-1] if job["drills"] else None
    for f in latest["files"] if latest else []:
        if f["sha256_match"]:
            path = source / "restored" / f["name"]
            if (
                not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != f["sha256"]
            ):
                raise StorageError("A verified restored file is missing or changed.")
            files.append(f"restored/{f['name']}")
    source_hash = hashlib.sha256((source / "job.json").read_bytes()).hexdigest()
    try:
        existing, revision = cloud.load(jid)
        if existing.get("import_source") != source_hash:
            raise StorageError(
                "Cloud archive ID already exists with different data. Import stopped."
            )
        if existing.get("storage", {}).get("state") == "saved":
            for path in files:
                cloud.get_artifact(jid, path)
            for key_id, key in keys.items():
                if cloud.get_key(jid, key_id) != key:
                    raise StorageError("Imported archive key does not match.")
            return jid
        job = existing
    except FileNotFoundError:
        job.update(
            import_source=source_hash,
            storage={"backend": "supabase", "state": "uploading"},
            vault_locations=locations,
        )
        revision = cloud.save(jid, job, 0)
    for key_id, key in keys.items():
        cloud.put_key(jid, key_id, key)
    for path in files:
        cloud.put_artifact(jid, path, (source / path).read_bytes())
    event_path = source / "events.jsonl"
    for line in event_path.read_text().splitlines() if event_path.exists() else []:
        event = json.loads(line)
        event_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"lazarus-import:{jid}:{event['seq']}")
        )
        cloud.append_event(jid, event, event_id)
    job.update(
        storage={"backend": "supabase", "state": "saved"}, vault_locations=locations
    )
    cloud.save(jid, job, revision)
    return jid


def main():
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / "lazarus" / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup")
    sub.add_parser("check")
    sub.add_parser("bucket")
    k = sub.add_parser("keygen")
    k.add_argument("--env-file", default=str(ROOT / ".env"))
    i = sub.add_parser("import")
    i.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "keygen":
            keygen(args.env_file)
            return
        cloud = cloud_from_env()
        if args.command == "setup":
            setup(cloud)
        elif args.command == "bucket":
            cloud.ensure_bucket(check_schema=False)
            print("Private DNA storage bucket ready.")
        elif args.command == "check":
            cloud.check()
            print(
                "Supabase schema, private bucket, and configured key access verified."
            )
        elif args.command == "import":
            cloud.check()
            print(
                f"Imported archive {import_archive(cloud, args.directory)}; local files retained."
            )
    except (StorageError, OSError, ValueError, KeyError) as e:
        # OSError and JSON errors can include paths/data; only storage errors are user-safe.
        print(
            str(e)
            if isinstance(e, StorageError)
            else "Setup failed. Check local files and configuration.",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
