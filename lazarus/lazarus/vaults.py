"""Physical vault stand-ins: one folder per site, each holding the strands ordered for that site.

Each vault gets one FASTA file (`order.fasta`) in the format DNA synthesis vendors accept for oligo
pools. Header = `>{pool_id}|{index}`; in a wet lab the pool id would be a PCR primer pair / tube.
Strand i of a data pool goes to vault (i mod N). Every vault gets a full copy of the manifest.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from . import store
from .persistence import get_cloud

from .manifest import MANIFEST_POOL  # noqa: E402  (kept here for existing imports)


def vault_dir(job_dir: Path, vault_id: int) -> Path:
    return job_dir / "vaults" / f"vault-{vault_id}"


def write_vaults(
    job_dir: Path,
    n_vaults: int,
    pools: dict[str, list[str]],
    manifest_strands: list[str],
) -> list[str]:
    """Write order.fasta + order.csv per vault. Returns written paths (relative to job_dir)."""
    rows: dict[int, list[tuple[str, int, str]]] = {
        v: [] for v in range(1, n_vaults + 1)
    }
    for v in rows:
        rows[v] += [(MANIFEST_POOL, i, s) for i, s in enumerate(manifest_strands)]
    for pool_id, strands in pools.items():
        for i, s in enumerate(strands):
            rows[(i % n_vaults) + 1].append((pool_id, i, s))
    written = []
    for v, items in rows.items():
        d = vault_dir(job_dir, v)
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        with open(d / "order.fasta", "w", newline="\n") as f:
            for pool_id, i, s in items:
                f.write(f">{pool_id}|{i}\n{s}\n")
        with open(d / "order.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["name", "sequence", "length"])
            for pool_id, i, s in items:
                w.writerow([f"{pool_id}_{i:05d}", s, len(s)])
        written += [
            (d / "order.fasta").relative_to(job_dir).as_posix(),
            (d / "order.csv").relative_to(job_dir).as_posix(),
        ]
    return written


def read_vault(job_dir: Path, vault_id: int) -> dict[str, dict[int, str]] | None:
    """Return {pool_id: {index: strand}} or None if the vault is gone."""
    cloud = get_cloud()
    if cloud:
        job = store.load(job_dir.name)
        if (
            not job.get("order")
            or job.get("vault_locations", {}).get(str(vault_id)) != "healthy"
        ):
            return None
        text = cloud.get_artifact(
            job_dir.name, f"vaults/vault-{vault_id}/order.fasta"
        ).decode()
    else:
        path = vault_dir(job_dir, vault_id) / "order.fasta"
        if not path.exists():
            return None
        text = path.read_text()
    out: dict[str, dict[int, str]] = {}
    header = None
    for line in text.splitlines():
        if line.startswith(">"):
            header = line[1:]
        elif header:
            pool_id, idx = header.rsplit("|", 1)
            out.setdefault(pool_id, {})[int(idx)] = line.strip()
            header = None
    return out


def list_vaults(job_dir: Path) -> list[dict]:
    if get_cloud():
        job = store.load(job_dir.name)
        return [
            {"vault_id": int(v), "status": s}
            for v, s in sorted(
                job.get("vault_locations", {}).items(), key=lambda x: int(x[0])
            )
        ]
    base = job_dir / "vaults"
    if not base.exists():
        return []
    out = []
    for d in sorted(base.iterdir()):
        if d.is_dir() and d.name.startswith("vault-"):
            out.append(
                {
                    "vault_id": int(d.name.split("-")[1]),
                    "status": "healthy"
                    if (d / "order.fasta").exists()
                    else "destroyed",
                }
            )
    return out


def destroy_vault(job_dir: Path, vault_id: int) -> bool:
    d = vault_dir(job_dir, vault_id)
    if get_cloud():
        job = store.load(job_dir.name)
        existed = job.get("vault_locations", {}).get(str(vault_id)) == "healthy"
        if existed:
            store.update(
                job_dir.name,
                lambda j: (
                    j["vault_locations"].update({str(vault_id): "destroyed"}),
                    j.update(needs_retest=True),
                ),
            )
        for f in ("order.fasta", "order.csv"):
            (d / f).unlink(missing_ok=True)
        return existed
    existed = (d / "order.fasta").exists()
    for f in ("order.fasta", "order.csv"):
        (d / f).unlink(missing_ok=True)
    return existed
