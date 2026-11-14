"""Reference-free clustering of sequencing reads.

the bundled codec’s simulator returns reads already grouped by the strand they came from ("clusters"). Real
sequencing output, and Lazarus' post-simulation FASTA, is a flat, shuffled list of reads with no
strand identity. Before consensus decoding, reads have to be grouped by similarity alone. the bundled codec has
no such stage, so Lazarus implements one here. It never sees reference strands or simulator labels.

Why this works for Fountain-coded strands: every strand is whitened with a seed-derived mask, so two
different strands look like independent random sequences (edit distance about half their length),
while two reads of the same strand differ only by sequencing errors (a few percent per base).

Algorithm (per sample/pool):
1. Greedy pass: each read looks up its k-mers in an index of cluster centroids, checks the few
   centroids it shares the most k-mers with by banded edit distance, and joins the first one within
   READ_THRESHOLD x length. Otherwise it starts a new cluster.
2. Consensus of every cluster (the bundled codec’s majority-vote reconstruct), then clusters whose consensus
   sequences are within MERGE_THRESHOLD x length are merged (heals clusters that were split because
   their first read happened to be unusually noisy).

Result: a list of clusters (lists of reads). Wrong groupings are not fatal: the codec's per-strand
CRC rejects bad consensus strands and the Fountain code tolerates missing ones.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median

from rapidfuzz.distance import Levenshtein

from dna_codec.baseline import reconstruct

K = 8
MIN_SHARED_KMERS = 3
CANDIDATES = 4
READ_THRESHOLD = 0.35  # read vs centroid read: both noisy
MERGE_THRESHOLD = 0.30  # consensus vs consensus (or vs a singleton read)


def _kmers(seq: str, k: int = K) -> set[str]:
    return {seq[i : i + k] for i in range(len(seq) - k + 1)}


class _Index:
    def __init__(self):
        self.table: dict[str, list[int]] = defaultdict(list)

    def add(self, cid: int, seq: str):
        for km in _kmers(seq):
            self.table[km].append(cid)

    def candidates(self, seq: str, exclude: int | None = None) -> list[tuple[int, int]]:
        counts: Counter[int] = Counter()
        for km in _kmers(seq):
            hits = self.table.get(km)
            if hits:
                counts.update(hits)
        if exclude is not None:
            counts.pop(exclude, None)
        return [(c, n) for c, n in counts.most_common(CANDIDATES) if n >= MIN_SHARED_KMERS]


def _close(a: str, b: str, threshold: float) -> bool:
    cutoff = max(4, int(threshold * max(len(a), len(b))))
    return Levenshtein.distance(a, b, score_cutoff=cutoff) <= cutoff


def cluster_reads(reads: list[str], strand_length: int | None = None) -> tuple[list[list[str]], dict]:
    """Group reads by similarity. Returns (clusters, stats). Input order does not matter for
    correctness; it is kept so results are deterministic for a given file."""
    if not reads:
        return [], {"reads": 0, "clusters": 0, "singletons": 0, "merged": 0, "largest": 0}
    length = strand_length or int(median(len(r) for r in reads))

    # 1. greedy assignment to centroid reads
    index, centroids, members = _Index(), [], []
    for read in reads:
        home = None
        for cid, _ in index.candidates(read):
            if _close(read, centroids[cid], READ_THRESHOLD):
                home = cid
                break
        if home is None:
            home = len(centroids)
            centroids.append(read)
            members.append([])
            index.add(home, read)
        members[home].append(read)

    # 2. consensus per cluster, then merge clusters with near-identical consensus
    cons = [reconstruct(m, length) if len(m) > 1 else m[0] for m in members]
    parent = list(range(len(cons)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    cindex = _Index()
    for cid, seq in enumerate(cons):
        cindex.add(cid, seq)
    merged = 0
    for cid, seq in enumerate(cons):
        for other, _ in cindex.candidates(seq, exclude=cid):
            a, b = find(cid), find(other)
            if a != b and _close(seq, cons[other], MERGE_THRESHOLD):
                parent[max(a, b)] = min(a, b)
                merged += 1
    groups: dict[int, list[str]] = {}
    for cid, m in enumerate(members):
        groups.setdefault(find(cid), []).extend(m)
    clusters = list(groups.values())
    sizes = [len(c) for c in clusters]
    return clusters, {
        "reads": len(reads),
        "clusters": len(clusters),
        "singletons": sum(s == 1 for s in sizes),
        "merged": merged,
        "largest": max(sizes),
        "mean_size": round(sum(sizes) / len(sizes), 2),
    }
