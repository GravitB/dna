# Lazarus Long-Term Recovery Package, format v1

`lazarus-recovery-package-v1` · schema version 1

A Recovery Package lets someone recover one Lazarus DNA archive from sequencing reads of its DNA
without Lazarus' servers, database or original files. One package per archive. It is a ZIP file;
every member except `SHA256SUMS` is listed there with its SHA-256, and readers must reject a package
whose digests do not match, that has unlisted members, or member names that are absolute, contain
`..` or characters outside `A–Z a–z 0–9 _ . - /`.

The package never contains an unwrapped encryption key or an organization master key.

## Members

| Path | Content |
|---|---|
| `package.json` | Format, `schema_version`, `archive_id`, `revision`, key custody (`encryption`), DNA summary, decoder version, evidence. |
| `README.md` | Archive-specific recovery guide. |
| `SHA256SUMS` | `<sha256>  <path>` per member. |
| `archive/manifest.json` | The bootstrap manifest. Byte-identical JSON content to the manifest encoded in DNA (see `BOOTSTRAP.md`). |
| `archive/files.json` | Per file: `name, bytes, sha256` (of the original), `key_id, nonce` (hex, AES-GCM), `pools, offset, cipher_bytes` (position in the encrypted stream). |
| `archive/layout.json` | Per pool: `offset, n_bytes, n_chunks, strands_written`; vault placement rule. |
| `encoding/encoding.json` | Codec, per-pool `EncoderSettings`, Fountain parameters (robust soliton c, delta), strand layout, bootstrap settings, dependency versions. |
| `encryption/encryption.json` | File encryption algorithm and how keys are supplied. |
| `encryption/wrapped_keys.json` | Organization archives only. See below. |
| `sequencing/sample_sheet.csv` | `sample_id, archive_id, vault, pool, role, strands, strand_length, container, molecular_identifier`. |
| `sequencing/SEQUENCING.md` | Sample identification and read delivery. |
| `spec/BOOTSTRAP.md`, `spec/RECOVERY_PACKAGE.md` | Specifications. |
| `synthesis/…` | Clean design FASTA, per-vault order files, one FASTA per physical sample, `REQUIREMENTS.md`. |
| `decoder/…` | Offline decoder source (`lazarus/`), Erbgut codec source (`dna_codec/`, pinned in `dna_codec.lock.json`), `requirements.lock`, `pyproject.toml`, `INSTALL.md`. |

## Recovering a file

1. Group reads by physical sample (`sample_id` → `pool` via the sample sheet).
2. Decode the manifest from the `MANIFEST` reads with the fixed bootstrap setting (`BOOTSTRAP.md`), or
   use `archive/manifest.json`. Lazarus' decoder does both and warns if they differ.
3. Per pool: cluster reads, build a consensus strand per cluster, keep strands whose CRC-16 checks
   (either orientation), and run Fountain recovery with the pool's `settings`, `n_bytes`, `n_chunks`.
4. Concatenate pools in id order. Each file's ciphertext is `stream[offset : offset + cipher_bytes]`.
5. Decrypt with AES-256-GCM (key = the file's data key, `nonce` from `files.json`, AAD `lazarus-v1`),
   decompress with zstd, and accept the file only if its SHA-256 equals `sha256`.

## Keys

**Organization archives** (`package.json → encryption.mode = "organization"`):

```json
{
  "format": "lazarus-wrapped-keys-v1",
  "org_id": "org-…", "archive_id": "…", "kek_version": 1, "kek_fingerprint": "<32 hex>",
  "keys": { "<key_id>": { "nonce": "<base64, 12 bytes>", "wrapped": "<base64, 32-byte key + 16-byte tag>" } }
}
```

Data key = AES-256-GCM-decrypt(master key version `kek_version`, nonce, wrapped, AAD), where AAD is
the UTF-8 JSON `{"archive_id":…,"format":"lazarus-wrapped-keys-v1","key_id":…,"kek_version":…,"org_id":…}`
with sorted keys and no spaces. `kek_fingerprint` = first 32 hex characters of
HMAC-SHA256(master key, `lazarus-kek-fingerprint-v1`). It identifies the key without revealing it.

The master key comes from the organization's backup file:

```json
{
  "format": "lazarus-org-master-key-v1", "org_id": "org-…", "org_name": "…",
  "versions": [ { "version": 1, "fingerprint": "…" } ],
  "kdf": { "name": "scrypt", "n": 32768, "r": 8, "p": 1, "salt": "<base64>" },
  "cipher": "AES-256-GCM", "nonce": "<base64>", "ciphertext": "<base64>"
}
```

Plaintext = JSON `{"<version>": "<base64 master key>"}`. Key = scrypt(passphrase, salt, n, r, p, 32 bytes).
AAD = `lazarus-org-master-key-v1:<org_id>:<comma-separated sorted versions>`.

**Rotation.** Rotating creates master-key version n+1 and re-wraps every archive's data keys under it.
The DNA is not touched. A new package revision is issued per archive. Packages issued earlier keep
`kek_version` n and still need a backup that holds version n. Nothing upgrades them silently.

**Legacy archives** (`encryption.mode = "legacy-keyfile"`) need the per-archive `lazarus-keyfile-v1`
(scrypt + AES-256-GCM over `{key_id: base64 key}`, AAD `lazarus-keyfile-v1:<archive_id>`).

## Evidence levels

Reports distinguish three levels and never promote one into another:

1. **Simulated reads**: Erbgut channel simulation; a digital experiment.
2. **Laboratory-format reads**: real-world FASTA/FASTQ conventions (demultiplexed files, qualities,
   N bases, either orientation). Shows format compatibility; Lazarus cannot verify the reads' origin.
3. **Physical recovery**: sequencing of synthesized Lazarus-encoded DNA. Not demonstrated by Lazarus
   to date; `package.json → evidence.physical_dna_validated` is `false`.
