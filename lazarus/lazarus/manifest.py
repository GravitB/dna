"""Self-describing bootstrap manifest.

Problem: decades from now the strands may survive but the software settings that wrote them are
forgotten. Fix: the manifest (encoder settings, file sizes, hashes, vault layout) is itself written
to DNA with ONE fixed, published setting (BOOTSTRAP below, docs/BOOTSTRAP.md). A future reader
needs only that one-page spec to decode the manifest, and the manifest says how to read the rest.

Fixed manifest framing: exactly MANIFEST_BYTES bytes =
  b"LZM1" + 4-byte big-endian length + zstd(JSON) + zero padding.
Because the size is fixed, the Fountain metadata (n_bytes, n_chunks) is fixed too.
"""

from __future__ import annotations

import json
import struct
from functools import lru_cache

import zstandard

from . import dna

MAGIC = b"LZM1"
MANIFEST_BYTES = 8192
BOOTSTRAP = dna.EncoderSettings(strand_length=110, seed_bases=16, redundancy=1.0)


@lru_cache(maxsize=1)
def bootstrap_meta() -> dna.FileMeta:
    return dna.encode_bytes(bytes(MANIFEST_BYTES), BOOTSTRAP).meta


def pack(manifest: dict) -> bytes:
    body = zstandard.ZstdCompressor(level=19).compress(json.dumps(manifest, sort_keys=True).encode())
    framed = MAGIC + struct.pack(">I", len(body)) + body
    if len(framed) > MANIFEST_BYTES:
        raise ValueError(f"manifest too large ({len(framed)} > {MANIFEST_BYTES} bytes)")
    return framed + bytes(MANIFEST_BYTES - len(framed))


def unpack(blob: bytes) -> dict:
    if len(blob) != MANIFEST_BYTES or blob[:4] != MAGIC:
        raise ValueError("not a Lazarus manifest")
    (n,) = struct.unpack(">I", blob[4:8])
    return json.loads(zstandard.ZstdDecompressor().decompress(blob[8 : 8 + n]))


def encode_manifest(manifest: dict) -> list[str]:
    enc = dna.encode_bytes(pack(manifest), BOOTSTRAP)
    assert enc.meta == bootstrap_meta()
    return enc.strands


def decode_manifest(decoded_strands) -> dict | None:
    blob = dna.recover_bytes(decoded_strands, bootstrap_meta())
    if blob is None:
        return None
    try:
        return unpack(blob)
    except Exception:  # noqa: BLE001
        return None
