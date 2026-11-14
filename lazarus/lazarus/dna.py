"""Thin wrapper over the the bundled codec codec (dna_codec). The only module in Lazarus that imports it.

Everything DNA-related goes through the bundled codec’s own functions:
encode / recover (Fountain code), simulate (calibrated channel), simulator_b (red-team channel),
MajorityVoteDecoder (baseline) and PolishDecoder (1D CNN trained on real Nanopore reads).
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, replace, fields
from functools import lru_cache
from pathlib import Path
from typing import Sequence

import numpy as np

from dna_codec import simulator as sim_a
from dna_codec import simulator_b as sim_b
from dna_codec.baseline import MajorityVoteDecoder
from dna_codec.encoder import encode, payload_bits_per_base, recover
from dna_codec.profiles import SituationProfile, load_profile
from dna_codec.seeds import train_seed
from dna_codec.types import EncodedFile, EncoderSettings, FileMeta

CODEC_DIR = Path(__file__).resolve().parents[1]
POLISH_CHECKPOINT = Path(os.environ.get("LAZARUS_POLISH_CKPT", CODEC_DIR / "checkpoints/polish/polish.pt"))

# Base profiles shipped with the bundled codec, calibrated on real reads (nanopore) or literature (illumina).
BASE_PROFILES = {"nanopore": "nanopore_budget", "illumina": "illumina_standard"}
# Extra strand loss per year of storage. the bundled codec’s century archive profile uses 0.002/year.
# Extrapolated, not measured: always labeled "modeled" in the UI.
DECAY_PER_YEAR = 0.002

SETTING_KEYS = tuple(f.name for f in fields(EncoderSettings))


# ------------------------------------------------------------------ settings and profiles


def settings_from_dict(d: dict | None) -> EncoderSettings:
    d = dict(d or {})
    kw = {k: d[k] for k in SETTING_KEYS if k in d}
    if "strand_length" in kw:
        kw["strand_length"] = int(kw["strand_length"])
    if "redundancy" in kw:
        kw["redundancy"] = float(kw["redundancy"])
    return EncoderSettings(**kw)


def settings_to_dict(s: EncoderSettings) -> dict:
    return asdict(s)


def make_profile(tech: str, years: float, coverage: float) -> SituationProfile:
    """the bundled codec profile for the vendor's read technology, stretched to the retention horizon."""
    if tech not in BASE_PROFILES:
        raise ValueError(f"tech must be one of {sorted(BASE_PROFILES)}")
    base = load_profile(BASE_PROFILES[tech])
    return replace(
        base,
        name=f"{tech}_{int(years)}y_cov{coverage:g}",
        storage_years=float(years),
        decay_per_year=DECAY_PER_YEAR,
        coverage_mean=float(coverage),
    )


def profile_to_dict(p: SituationProfile) -> dict:
    return p.to_dict()


def profile_from_dict(d: dict) -> SituationProfile:
    return SituationProfile.from_dict(d)


# ------------------------------------------------------------------ decoders


_polish_lock = threading.Lock()


@lru_cache(maxsize=1)
def _polish():
    from dna_codec.model.polish import PolishDecoder

    import torch

    device = os.environ.get("LAZARUS_DEVICE") or (
        "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")
    return PolishDecoder(POLISH_CHECKPOINT, device=device, workers=1)


def decode_clusters(clusters, strand_length: int, decoder: str) -> list:
    if decoder == "baseline":
        return MajorityVoteDecoder().decode(clusters, strand_length)
    if decoder == "polish":
        with _polish_lock:  # one CNN, shared between threads
            return _polish().decode(clusters, strand_length)
    raise ValueError("decoder must be 'baseline' or 'polish'")


# ------------------------------------------------------------------ encoding


def encode_bytes(data: bytes, settings: EncoderSettings) -> EncodedFile:
    return encode(data, settings)


def recover_bytes(strands: Sequence[str | None], meta: FileMeta) -> bytes | None:
    return recover(strands, meta)


def meta_to_dict(meta: FileMeta) -> dict:
    return {"settings": settings_to_dict(meta.settings), "n_bytes": meta.n_bytes, "n_chunks": meta.n_chunks}


def meta_from_dict(d: dict) -> FileMeta:
    return FileMeta(settings=settings_from_dict(d["settings"]), n_bytes=int(d["n_bytes"]), n_chunks=int(d["n_chunks"]))


def vault_of(index: int, n_vaults: int) -> int:
    """Strand i goes to vault (i mod n). Losing one vault loses every n-th strand."""
    return index % n_vaults


# ------------------------------------------------------------------ channel


def sequence(strands: Sequence[str], profile: SituationProfile, seed: int, channel: str = "a"):
    """Simulated sequencing: one cluster of noisy reads per strand (empty = dropout)."""
    fn = sim_b.simulate if channel == "b" else sim_a.simulate
    return fn(list(strands), profile, train_seed(seed))


def run_trials(
    data: bytes | Sequence[bytes],
    settings: EncoderSettings,
    profile: SituationProfile,
    trials: int,
    decoder: str = "baseline",
    *,
    channel: str = "a",
    lost_vaults: int = 0,
    n_vaults: int = 1,
    seed_base: int = 1000,
) -> dict:
    """Encode once, then run `trials` independent sequencing passes and count exact recoveries.

    data may be one pool or a list of pools (a whole archive): a trial only counts as recovered
    when every pool comes back byte-exact. Uses train seeds only (the bundled codec seed discipline).
    lost_vaults removes every strand stored in the first `lost_vaults` of `n_vaults` vaults.
    """
    t0 = time.time()
    datas = [data] if isinstance(data, (bytes, bytearray)) else list(data)
    encs = [encode(d, settings) for d in datas]
    lost = set(range(min(lost_vaults, n_vaults)))
    strand_acc, ok = [], 0
    for t in range(trials):
        all_ok, hits, total = True, 0, 0
        for j, (d, enc) in enumerate(zip(datas, encs)):
            clusters = sequence(enc.strands, profile, seed_base + 97 * j + t, channel)
            if lost:
                clusters = [[] if vault_of(i, n_vaults) in lost else c for i, c in enumerate(clusters)]
            decoded = decode_clusters(clusters, settings.strand_length, decoder)
            hits += sum(a == b for a, b in zip(decoded, enc.strands))
            total += len(enc.strands)
            all_ok = all_ok and recover(decoded, enc.meta) == d
        strand_acc.append(hits / max(1, total))
        ok += all_ok
    n = sum(len(e.strands) for e in encs)
    c = [costs(e.meta, len(e.strands), profile) for e in encs]
    bases = sum(x["bases"] for x in c)
    payload_bits = sum(payload_bits_per_base(e.meta, len(e.strands)) * x["bases"] for e, x in zip(encs, c))
    return {
        "recovery_rate": ok / trials if trials else 0.0,
        "n_trials": trials,
        "n_recovered": ok,
        "n_pools": len(encs),
        "strand_accuracy": round(float(np.mean(strand_acc)), 4) if strand_acc else None,
        "n_strands": n,
        "bits_per_base": round(payload_bits / bases, 4) if bases else 0.0,
        "bases": bases,
        "write_usd": round(sum(x["write_usd"] for x in c), 4),
        "read_usd": round(sum(x["read_usd"] for x in c), 4),
        "write_usd_per_mb": c[0]["write_usd_per_mb"],
        "read_usd_per_mb": c[0]["read_usd_per_mb"],
        "decoder": decoder,
        "seconds": round(time.time() - t0, 2),
    }


def costs(meta: FileMeta, n_strands: int, profile: SituationProfile) -> dict:
    """Modeled costs from the bundled codec’s profile prices (placeholders, never quoted as real)."""
    bases = n_strands * meta.settings.strand_length
    bpb = payload_bits_per_base(meta, n_strands)
    bases_per_mb = 8e6 / bpb if bpb > 0 else float("inf")
    return {
        "bases": bases,
        "write_usd": round(bases * profile.synthesis_usd_per_base, 4),
        "read_usd": round(n_strands * profile.coverage_mean * profile.sequencing_usd_per_read, 4),
        "write_usd_per_mb": round(bases_per_mb * profile.synthesis_usd_per_base, 2),
        "read_usd_per_mb": round(
            bases_per_mb / meta.settings.strand_length * profile.coverage_mean * profile.sequencing_usd_per_read, 2
        ),
    }
