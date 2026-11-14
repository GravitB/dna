"""Strict FASTA / FASTQ reading and FASTA writing for DNA archive experiments.

Two kinds of FASTA move through Lazarus and must never be confused:

* clean (pre-simulation) FASTA: the exact strands the encoder designed, one record per strand,
  header `>{pool}|{index}` (vault order files) or `>vault-{v}|{pool}|{index}` (whole-archive export).
* read (post-simulation) FASTA: noisy simulated sequencing reads, header `>read_000001 sample={pool}`.
  `sample` names the tube that was sequenced (in a wet lab: the primer pair / barcode used to
  demultiplex), never the strand a read came from.

The decoder only ever learns a record's sample label from its header (or from the sample sheet the
user supplies for a whole file). Strand indices in clean headers are ignored on purpose, so a clean
FASTA is decoded exactly like a read FASTA.

Laboratory reads are parsed in lenient mode: gzip input, N/IUPAC codes and very long reads are
counted and dropped per read instead of rejecting the whole run. FASTQ qualities are validated
(Phred+33) and kept on each Record.
"""

from __future__ import annotations

import gzip
import io
import re
from dataclasses import dataclass

MAX_FASTA_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 600_000
MAX_SEQUENCE_LENGTH = 2_000
LAB_MAX_LENGTH = 100_000
_SEQ = re.compile(r"[ACGT]+")
_IUPAC = re.compile(r"[ACGTNRYKMSWBDHV]+")
_QUAL = re.compile(r"[!-~]*")  # Phred+33: '!' (Q0) .. '~' (Q93)
_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SAMPLE = re.compile(r"(?:^|\s)sample=([^\s]+)")


class FastaError(ValueError):
    """Invalid sequence input. The message is safe to show to the user."""


@dataclass(frozen=True)
class Record:
    id: str
    description: str
    sequence: str
    quality: str | None = None  # FASTQ Phred+33 string, kept verbatim; None for FASTA

    @property
    def sample(self) -> str | None:
        return sample_of(self.id, self.description)

    @property
    def mean_quality(self) -> float | None:
        if not self.quality:
            return None
        return sum(ord(c) - 33 for c in self.quality) / len(self.quality)


@dataclass
class ReadStats:
    """What a lenient (laboratory) parse dropped instead of rejecting the whole file."""

    ambiguous_bases: int = 0  # reads containing N or other IUPAC codes
    too_long: int = 0

    def as_dict(self) -> dict:
        return {"ambiguous_base_reads_dropped": self.ambiguous_bases, "overlong_reads_dropped": self.too_long}


def sample_of(record_id: str, description: str = "") -> str | None:
    """The tube/pool a record was read from: `sample=` attribute, else the pool part of a
    `[vault-N|]pool|index` id. None when the header carries no pool information."""
    m = _SAMPLE.search(description)
    if m:
        label = m.group(1)
    else:
        parts = record_id.split("|")
        if len(parts) < 2:
            return None
        label = parts[-2]
    return label if _LABEL.match(label) else None


def valid_label(label: str) -> bool:
    return bool(_LABEL.match(label or ""))


def vault_of_id(record_id: str) -> int | None:
    parts = record_id.split("|")
    if len(parts) == 3 and parts[0].startswith("vault-") and parts[0][6:].isdigit():
        return int(parts[0][6:])
    return None


def maybe_gunzip(data: bytes) -> bytes:
    """Sequencing facilities usually ship .fastq.gz. Decompress with the same size limit."""
    if data[:2] != b"\x1f\x8b":
        return data
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
            out = g.read(MAX_FASTA_BYTES + 1)
    except (OSError, EOFError):
        raise FastaError("The file looks gzip-compressed but could not be decompressed.") from None
    if len(out) > MAX_FASTA_BYTES:
        raise FastaError(f"Decompressed file is larger than the {MAX_FASTA_BYTES // (1024 * 1024)} MB limit.")
    return out


def decode_text(data: bytes) -> str:
    if len(data) > MAX_FASTA_BYTES:
        raise FastaError(f"File is larger than the {MAX_FASTA_BYTES // (1024 * 1024)} MB limit.")
    if not data.strip():
        raise FastaError("The file is empty.")
    try:
        return data.decode("ascii")
    except UnicodeDecodeError:
        raise FastaError("The file is not a text FASTA/FASTQ file (non-ASCII bytes found).") from None


def parse(data: bytes | str, *, max_records: int = MAX_RECORDS, max_length: int = MAX_SEQUENCE_LENGTH,
          lenient: bool = False, stats: ReadStats | None = None) -> tuple[str, list[Record]]:
    """Parse FASTA (multi-line sequences allowed) or FASTQ (4-line records, Phred+33 qualities
    validated and kept on each Record).

    Returns (format, records). Raises FastaError with a line number on any syntax problem.
    Lower-case bases are accepted and upper-cased. Strict mode (default; clean design FASTA)
    rejects anything other than A, C, G, T because the codec's alphabet has no ambiguity codes.
    Lenient mode (laboratory reads) accepts gzip, drops reads that contain N/IUPAC codes or are
    longer than LAB_MAX_LENGTH and counts them in `stats`; malformed files are still an error.
    """
    if lenient:
        stats = stats if stats is not None else ReadStats()
        max_length = LAB_MAX_LENGTH
    if isinstance(data, (bytes, bytearray)):
        text = decode_text(maybe_gunzip(bytes(data)) if lenient else bytes(data))
    else:
        text = data
    lines = text.splitlines()
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is None:
        raise FastaError("The file is empty.")
    if lines[first].startswith("@"):
        return "fastq", _parse_fastq(lines, first, max_records, max_length, stats if lenient else None)
    if not lines[first].startswith(">"):
        raise FastaError(f"Line {first + 1}: expected a FASTA header starting with '>'.")
    alphabet = _IUPAC if lenient else _SEQ
    records: list[Record] = []
    header: tuple[str, str] | None = None
    header_line = 0
    chunks: list[str] = []

    def finish():
        if header is None:
            return
        seq = "".join(chunks)
        if not seq:
            raise FastaError(f"Line {header_line}: record '{header[0]}' has no sequence.")
        if len(seq) > max_length:
            if lenient:
                stats.too_long += 1
                return
            raise FastaError(f"Line {header_line}: record '{header[0]}' is longer than {max_length} bases.")
        if lenient and not _SEQ.fullmatch(seq):
            stats.ambiguous_bases += 1
            return
        records.append(Record(header[0], header[1], seq))
        if len(records) > max_records:
            raise FastaError(f"More than {max_records} records; split the file.")

    for n, raw in enumerate(lines[first:], start=first + 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            finish()
            body = line[1:].strip()
            if not body:
                raise FastaError(f"Line {n}: empty FASTA header.")
            rid, _, desc = body.partition(" ")
            header, header_line, chunks = (rid, desc.strip()), n, []
            continue
        seq = line.upper()
        if not alphabet.fullmatch(seq):
            allowed = "ACGTNRYKMSWBDHV" if lenient else "ACGT"
            bad = next(c for c in seq if c not in allowed)
            raise FastaError(f"Line {n}: invalid character '{bad}' (only "
                             + ("A, C, G, T and IUPAC codes" if lenient else "A, C, G, T") + " are allowed).")
        chunks.append(seq)
    finish()
    return "fasta", records


def _parse_fastq(lines, first, max_records, max_length, stats: ReadStats | None) -> list[Record]:
    body = [line.strip() for line in lines[first:]]
    while body and not body[-1]:
        body.pop()
    if len(body) % 4:
        raise FastaError("FASTQ must have 4 lines per record (header, sequence, '+', qualities).")
    alphabet = _IUPAC if stats is not None else _SEQ
    records = []
    for i in range(0, len(body), 4):
        n = first + i + 1
        head, seq, plus, qual = body[i : i + 4]
        if not head.startswith("@") or len(head) < 2:
            raise FastaError(f"Line {n}: expected a FASTQ header starting with '@'.")
        if not plus.startswith("+"):
            raise FastaError(f"Line {n + 2}: expected '+' separator.")
        seq = seq.upper()
        if not seq or not alphabet.fullmatch(seq):
            raise FastaError(f"Line {n + 1}: sequence must be non-empty and only "
                             + ("A, C, G, T or IUPAC codes." if stats is not None else "A, C, G, T."))
        if len(qual) != len(seq):
            raise FastaError(f"Line {n + 3}: quality string length does not match the sequence.")
        if not _QUAL.fullmatch(qual):
            raise FastaError(f"Line {n + 3}: quality string has characters outside Phred+33 ('!'..'~').")
        rid, _, desc = head[1:].partition(" ")
        if len(seq) > max_length:
            if stats is not None:
                stats.too_long += 1
                continue
            raise FastaError(f"Line {n + 1}: sequence longer than {max_length} bases.")
        if stats is not None and not _SEQ.fullmatch(seq):
            stats.ambiguous_bases += 1
            continue
        records.append(Record(rid, desc.strip(), seq, qual))
        if len(records) > max_records:
            raise FastaError(f"More than {max_records} records; split the file.")
    return records


def write(records) -> str:
    """records: iterable of (header_without_gt, sequence). One sequence line per record."""
    return "".join(f">{h}\n{s}\n" for h, s in records)


def write_fastq(records) -> str:
    """records: iterable of (header_without_at, sequence, quality)."""
    return "".join(f"@{h}\n{s}\n+\n{q}\n" for h, s, q in records)
