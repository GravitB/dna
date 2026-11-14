"""Compression, encryption, hashing and pool splitting.

The customer's key never goes into DNA. The archive stores only a key id; the key itself lives in
the customer's key store (here: a separate folder standing in for a KMS).
"""

from __future__ import annotations

import hashlib
import os

import zstandard
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

POOL_BYTES = 12_000  # bytes per oligo pool; the bundled codec was tested on ~20 KB files, small pools encode fast
NONCE_BYTES = 12


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def seal(data: bytes, key: bytes, aad: bytes = b"lazarus-v1") -> tuple[bytes, bytes]:
    """zstd compress then AES-256-GCM encrypt. Returns (nonce, ciphertext+tag)."""
    compressed = zstandard.ZstdCompressor(level=19).compress(data)
    nonce = os.urandom(NONCE_BYTES)
    return nonce, AESGCM(key).encrypt(nonce, compressed, aad)


def unseal(nonce: bytes, ciphertext: bytes, key: bytes, aad: bytes = b"lazarus-v1") -> bytes:
    """Decrypt (raises on any tampering, GCM tag) then decompress."""
    compressed = AESGCM(key).decrypt(nonce, ciphertext, aad)
    return zstandard.ZstdDecompressor().decompress(compressed)


def split_pools(blob: bytes, pool_bytes: int = POOL_BYTES) -> list[bytes]:
    if not blob:
        return [b""]
    return [blob[i : i + pool_bytes] for i in range(0, len(blob), pool_bytes)]


def compressed_size(data: bytes) -> int:
    return len(zstandard.ZstdCompressor(level=19).compress(data))
