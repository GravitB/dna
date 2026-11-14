# Lazarus bootstrap spec (v1): how to read a Lazarus DNA archive with nothing else

Print this page and keep it with the vaults. It is the only thing a future reader needs besides the DNA
and the customer's decryption keys.

## 1. Find the manifest strands
Every vault holds a full copy of the manifest. In `order.fasta` its strands are labeled `MANIFEST|i`;
in a wet lab they would be a separate tube or primer pair. Sequence them.

## 2. Decode them with this fixed setting
- DNA Fountain (LT) code as in Erlich & Zielinski 2017; reference implementation `dna_codec.encoder` (bundled codec)
- 2 bits per base: A=0, C=1, G=2, T=3
- strand length 110 bases, of which the first 16 are the seed
- each strand payload = chunk + CRC-16, whitened with a mask derived from the seed
- robust soliton degree distribution, c = 0.1, delta = 0.5
- redundancy 1.0, at most 3 identical bases in a row, GC content 40–60%
- decoded size exactly **4096 bytes** (this fixes `n_bytes` and therefore `n_chunks`)
- the decoded file starts with a 4-byte CRC-32 of its content

## 3. Unpack
```
bytes 0–3   "LZM1"
bytes 4–7   N, big-endian length of the body
bytes 8..   zstd-compressed JSON (N bytes), then zero padding
```

## 4. Follow the manifest
The JSON names, for each data pool, its exact encoder settings, `n_bytes`, `n_chunks` and offset in the
archive stream. For each file it gives its key id, nonce, offset, length and SHA-256. It also records how
strands were spread over the vaults and which decoder was recommended. Decode every pool, concatenate
the pools in id order, cut out each file, decrypt it with AES-256-GCM (aad `lazarus-v1`) using the key
from the customer's key store, decompress it with zstd, and check the SHA-256.
