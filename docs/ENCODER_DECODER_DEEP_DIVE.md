# How the encoder and decoder work: a deep dive

This document explains, step by step, how Lazarus turns a file into DNA letters and how it turns
noisy DNA reads back into the exact same file. It also explains how the learned decoder was trained.
Nothing is skipped: every number, rule and design choice is explained, and the reason behind it.

If you only want the short version, read section 0 and the pipeline diagram. Everything after that
zooms in.

**Contents**

0. The big picture
1. DNA basics you need first
2. The encoder, step by step
3. What happens to the DNA: the channel simulator
4. The decoder, step by step
5. How the decoder was trained
6. The second learned model: the risk model
7. How Lazarus tests an archive before anyone approves it
8. Glossary
9. Where each piece lives in the code

---

## 0. The big picture

A computer file is a long list of bits (0s and 1s). DNA is a long list of letters from a
four-letter alphabet: A, C, G and T. Since 4 = 2 × 2, one DNA letter can hold exactly 2 bits:

```
00 → A     01 → C     10 → G     11 → T
```

So in principle, turning a file into DNA is easy: write the bits two at a time as letters. The hard
part is that DNA is **noisy**:

- When DNA is made (synthesis) and read back (sequencing), letters get **swapped** (substitution),
  **added** (insertion) or **dropped** (deletion).
- Whole pieces of DNA can **disappear** completely (dropout), and more of them disappear the longer
  the DNA is stored.
- DNA can only be made in short pieces (here: 110 letters each), so a file becomes thousands of
  pieces that come back **shuffled**, with no labels saying which piece is which.

Everything in the encoder and decoder exists to beat those problems. The whole round trip:

```
ENCODER (writing)
  your file
    │ 1. SHA-256 fingerprint of the original (to prove later that we got it back exactly)
    │ 2. compress with zstd (fewer bytes = less DNA = cheaper)
    │ 3. encrypt with AES-256-GCM (the key never goes into the DNA)
    │ 4. join all files into one stream, cut it into pools of ≤ 12 KB
    │ 5. Fountain-code each pool into 110-letter strands
    │      (each strand = 16-letter ID + 94 letters of mixed data + checksum,
    │       and only strands that obey the DNA chemistry rules are kept)
    │ 6. write a "manifest" (the instructions for reading everything) into DNA too
    │ 7. spread the strands across vault sites, write order files
    ▼
  ACGT strands  ──►  (synthesis, storage for decades, sequencing)  ──►  noisy, shuffled reads

DECODER (reading)
  noisy reads
    │ 1. group reads by tube (pool) label
    │ 2. cluster: group reads that came from the same strand, by similarity alone
    │ 3. consensus: turn each cluster of noisy reads into one clean 110-letter strand
    │      (classic majority vote, then a small neural network fixes what voting got wrong)
    │ 4. checksum each strand, throw away the bad ones
    │ 5. Fountain-decode: solve for the original data from whichever strands survived
    │ 6. read the manifest first, then every pool
    │ 7. join the pools, decrypt, decompress
    │ 8. compare SHA-256 with the original fingerprint: PASS only if every byte matches
    ▼
  your file, byte for byte
```

Three ideas carry the whole design:

1. **Redundancy instead of perfection.** We write more strands than strictly needed, mixed together
   so that *any* large enough subset of strands rebuilds the file. Losing strands is fine.
2. **Detect, don't guess.** Every strand carries a checksum. A strand that comes back even one
   letter wrong is detected and thrown away instead of corrupting the file.
3. **Many reads per strand.** Sequencing reads each strand several times. Every read has different
   random errors, so combining them (consensus) recovers the original letters.

---

## 1. DNA basics you need first

**Base / letter / nucleotide.** One position in DNA: A, C, G or T. Holds 2 bits.

**Strand / oligo.** One short synthetic piece of DNA. Here every strand is exactly **110 letters**.
"Oligo" (oligonucleotide) is the chemistry word for a short strand.

**Pool.** A tube holding thousands of different strands mixed together. One pool holds the DNA for
up to about 12 KB of (compressed, encrypted) data.

**Synthesis.** Making DNA from letters you choose. You send a vendor a list of sequences (a FASTA
file) and they make the molecules. You pay per letter.

**Sequencing.** Reading DNA back into letters. The machine reads many molecules at once and outputs
**reads**: one text string per molecule it read.

**Read.** One attempt at reading one molecule. Reads have errors. On Nanopore (the cheap, portable
technology) about **5.8% of letters are wrong** in the real data the decoder was trained on: about
2.2% substitutions, 1.7% insertions and 2.0% deletions per letter.

**Coverage.** How many reads you get per strand on average. More coverage means more evidence per
strand, but costs more. The Nanopore default here is 6 reads per strand.

**Dropout.** A strand that produces **zero** reads: it was never made, it decayed, or the sequencer
just never picked it up.

**Cluster.** All the reads that came from the same original strand. Sequencers do not tell you this;
the decoder has to figure it out.

**Homopolymer.** A run of the same letter, like `GGGG`. Sequencers struggle to count long runs, so
they often read `GGGG` as `GGG`. That is why the encoder forbids runs of 4 or more.

**GC content.** The share of letters that are G or C. DNA that is too GC-rich or too GC-poor is
harder to make and read evenly, so the encoder keeps every strand between 40% and 60% GC.

**Edit distance (Levenshtein distance).** The number of single-letter substitutions, insertions and
deletions needed to turn one string into another. `ACGT` → `AGT` has distance 1 (delete C). This is
the decoder's main way to measure "how similar are two reads".

**Why insertions and deletions are the hard part.** A substitution changes one letter in place. An
insertion or deletion **shifts every letter after it**:

```
original:  A C G T A C G T
read:      A C T A C G T        (G deleted)
position:  1 2 3 4 5 6 7
```

Position 3 of the read is `T`, but position 3 of the original is `G`. If you compared reads letter
by letter at the same position, everything after the deletion would look wrong. So the decoder must
first **align** reads (find which letter of the read matches which letter of the original) before it
can vote.

---

## 2. The encoder, step by step

### Step 1: Fingerprint the original (SHA-256)

Before anything else, Lazarus computes the **SHA-256 hash** of each original file. A hash is a
64-character fingerprint: change one bit of the file and the hash changes completely. At the very
end, the decoder recomputes the hash of what it rebuilt and compares. Equal hashes mean the file is
byte-for-byte identical. "Looks similar" never counts as success.

Code: `lazarus/lazarus/crypto.py`, `sha256()`.

### Step 2: Compress (zstd, level 19)

The file is compressed with **Zstandard** at level 19 (a slow, strong setting). Fewer bytes means
fewer strands, which means less DNA to pay for.

Why compress **before** encrypting: good encryption output looks completely random, and random data
cannot be compressed. So the order has to be compress first, then encrypt.

### Step 3: Encrypt (AES-256-GCM)

The compressed bytes are encrypted with **AES-256-GCM**:

- **Key:** a fresh random 256-bit key per file. It is stored in the customer's key store under a
  key id like `kms-<archive>-00`. **The key never goes into DNA.** The DNA only contains the key id.
  Someone who steals the DNA gets ciphertext they cannot read.
- **Nonce:** 12 random bytes, different for every encryption. It is not secret; it is stored in
  the manifest.
- **AAD (additional authenticated data):** the fixed label `lazarus-v1`. It is not encrypted, but
  it is bound into the authentication tag, so ciphertext made for another purpose fails to decrypt.
- **Tag:** GCM appends a 16-byte authentication tag. On decryption, if even one bit of the
  ciphertext is wrong, or the key is wrong, decryption **fails loudly** instead of returning
  garbage. That gives a second integrity check on top of the hash.

For each file Lazarus records: key id, nonce, original SHA-256, original size, ciphertext size and
the file's offset in the stream (next step).

Code: `crypto.seal()` / `crypto.unseal()`.

### Step 4: One stream, split into pools

All encrypted files are concatenated into one long byte stream, in order. Each file's position is
remembered as `offset` and `cipher_bytes`, so it can be cut back out later.

The stream is then split into **pools** of at most 12,000 bytes, and the pools are made the same
size: `n_pools = ceil(stream_length / 12000)`, `size = ceil(stream_length / n_pools)`. For example, a
30,000-byte stream becomes 3 pools of 10,000 bytes, not 12,000 + 12,000 + 6,000.

Why equal sizes: the Fountain code (next step) behaves less predictably on very small inputs. A tiny
leftover pool would be the weakest link of the archive.

Why pools at all: in a lab, each pool is a separate tube with its own primer pair (a chemical
"address"), so a reader can pull out one pool without touching the others. Smaller pools also
encode and decode faster. A file can span two pools; the manifest records which.

Code: `lazarus/lazarus/tools.py`, `prepare_archive()`.

### Step 5: Fountain-code each pool into strands

This is the heart of the encoder: `lazarus/dna_codec/encoder.py`, `encode()`. It turns one pool's bytes into
a list of 110-letter strands.

#### 5a. The layout of one strand

Every strand is exactly 110 letters = 220 bits, laid out like this:

```
|<-- 16 letters -->|<-------------------- 94 letters -------------------->|
|   seed (32 bits) |  data chunk (172 bits)  +  CRC-16 (16 bits), whitened |
```

- **Seed (16 letters = 32 bits):** a number that works as the strand's ID. It decides which pieces
  of data are mixed into this strand (5d). The decoder reads it back to know how to unmix.
- **Payload (94 letters = 188 bits):** 172 bits of (mixed) data plus a 16-bit checksum.

Where 172 comes from: 110 letters × 2 bits = 220 bits. Minus 32 for the seed = 188. Minus 16 for the
checksum = **172 bits of data per strand** (21.5 bytes).

#### 5b. Add a whole-file checksum and cut into chunks

First a 4-byte **CRC-32** of the pool's bytes is put in front of them. CRC-32 is a fast checksum: at
the very end of decoding it catches the rare case where a wrong strand slipped through and the
solved data is wrong.

Then the bits are cut into **chunks** of 172 bits each (the last one padded with zeros):

```
n_chunks = ceil((n_bytes + 4) × 8 / 172)
```

A full 12,000-byte pool: (12,000 + 4) × 8 / 172 = 558.2, so **559 chunks**.

#### 5c. How many strands: redundancy

```
n_strands = ceil(n_chunks × (1 + redundancy))
```

With redundancy 0.3 that is ceil(559 × 1.3) = **727 strands** for a 12 KB pool. The decoder needs
roughly n_chunks valid strands (a little more in practice) out of all the strands written, so with
redundancy 0.3 you can lose about 1 − 1/1.3 ≈ **23%** of strands and still recover (measured: clean
recovery up to 22% loss). Lazarus tests redundancies 0.8, 1.2, 1.6 and 2.0 for real archives,
because decades of storage plus cheap Nanopore reading lose far more than 23%.

Density: 12,000 bytes × 8 bits / (727 strands × 110 letters) ≈ **1.2 bits per letter** at
redundancy 0.3. The theoretical maximum is 2. The gap pays for the seed, the checksum, the
redundancy and the chemistry rules.

#### 5d. Making one strand: the "droplet"

The Fountain code (also called an LT code, from DNA Fountain by Erlich and Zielinski, 2017) does
not put chunk 1 in strand 1, chunk 2 in strand 2, and so on. Each strand carries the **XOR** of a
few randomly chosen chunks.

**XOR** (exclusive or) works bit by bit: equal bits give 0, different bits give 1.

```
  1 0 1 1
⊕ 0 1 1 0
= 1 1 0 1
```

Its key property: XOR undoes itself. If `s = a ⊕ b` and you know `a`, then `s ⊕ a = b`. That is how
the decoder unmixes.

To build one strand:

1. **Pick a seed.** A counter (0, 1, 2, …) is passed through a scramble function that is a
   bijection (every counter maps to a different 32-bit number), so every strand gets a unique seed
   and seeds look random instead of `AAAA…AC`.
2. **Pick a degree** (how many chunks to mix) from the seed, using the **robust soliton
   distribution**. For a 559-chunk pool:
   - degree 1 (a chunk on its own): 2.6% of strands
   - degree 2: 42%
   - degree 3: 14%
   - more than 10: 19% (a few very high degrees)
   - average: about 9.3

   Why this mix: degree-1 strands are the starting points of decoding (they hand you a chunk
   directly). Degree-2 strands let decoding spread from chunk to chunk. The rare high-degree strands
   make sure every chunk is covered by some strand. The robust soliton distribution is the classic
   mix that makes the peeling decoder (4e) succeed with very little extra.
3. **Pick which chunks**, again from the seed, with Floyd's algorithm (exactly `degree` distinct
   chunk numbers, no retries).
4. **XOR those chunks together.** The result is the strand's 172-bit data.

Because the seed alone determines the degree and the chunk list, the decoder can recompute "which
chunks are in this strand" from the 16 seed letters. Nothing else has to be stored.

Real examples from a 559-chunk pool:

```
counter 0 → seed 0           → 30 chunks mixed (and its seed letters are AAAAAAAAAAAAAAAA,
                                so the chemistry rule in 5g rejects this strand)
counter 1 → seed 1121685590  → just chunk 509 (a degree-1 strand)
counter 2 → seed 2243371181  → chunks 177 ⊕ 216 ⊕ 306 ⊕ 349
```

This design is called a "fountain" because you can keep generating new strands forever, like drops
from a fountain, and any big enough set of drops rebuilds the file. That makes it cheap to throw a
strand away: just take the next seed.

#### 5e. Add the strand checksum (CRC-16)

A 16-bit **CRC** (CRC-CCITT) is computed over the seed and the 172-bit data, and appended. When the
decoder rebuilds a strand, it recomputes the CRC. If the strand has even one wrong letter, the CRC
almost certainly won't match (a wrong strand passes by chance only 1 time in 65,536), and the
strand is **thrown away**. To the Fountain decoder, a thrown-away strand looks exactly like a lost
one, and it already tolerates lost strands. So one wrong letter costs one strand, never the file.

#### 5f. Whiten the payload

The 188-bit payload (data + CRC) is XORed with a **whitening mask**: a pseudo-random bit pattern
generated from the seed (with the SplitMix64 generator). The decoder knows the seed, so it can make
the same mask and undo it.

Why: a file full of zeros would otherwise become strands like `AAAAAAAA…`, which break every
chemistry rule. Whitening makes every strand look random whatever the file contains. It also makes
any two different strands look completely unrelated, which the decoder's clustering relies on
(section 4b).

#### 5g. Bits to letters, then the chemistry rules

The 220 bits (seed, then whitened payload) are written two at a time as letters: `00→A`, `01→C`,
`10→G`, `11→T`. Example: the byte `01001011` becomes `C A G T`.

Then the strand is checked against two hard rules:

- **No homopolymer longer than 3:** any run of 4 or more identical letters (`AAAA`, `GGGG`) is
  rejected.
- **GC content between 40% and 60%** over the whole strand.

If the strand breaks a rule, the encoder **doesn't fix it**. It throws the candidate away and builds
a new strand from the **next seed** (different chunk mix, different whitening mask, so totally
different letters). It may try up to 20,000 seeds per strand slot. This costs nothing in density:
the decoder never needs to know which seeds were skipped, because each strand carries its own seed.

#### 5h. Optional: let a learned model choose between candidates

By default the first candidate that passes the rules is used. With a **risk model** (section 6),
the encoder instead collects 8 passing candidates per strand slot and keeps the one the model
predicts is least likely to be decoded wrongly on this customer's sequencing channel.

#### 5i. Make sure the set is decodable

With small files or low redundancy, a random set of mixes can be "rank deficient": some chunk can't
be solved from the strands written, no matter what. After choosing all strands, the encoder runs
the decoder's solver on the seeds alone. If the system can't be solved, it walks through the strands
and swaps any strand that adds no new information for one that does. This guarantees that the full
set of strands, read perfectly, always decodes.

#### 5j. What comes out

A list of strands, plus a small description (`FileMeta`): the encoder settings, the pool's byte
count and its number of chunks. That description is what the decoder needs besides the strands, and
it goes into the manifest.

### Step 6: The manifest, written into DNA

**Problem:** in 50 years the DNA may survive, but the software settings that wrote it may be
forgotten: strand length, redundancy, which pool holds which file, the nonces, the hashes.

**Fix:** all of that goes into a **manifest**, and the manifest itself is written into DNA with
**one fixed, published setting** (strand length 110, seed 16 letters, redundancy 1.0). A future
reader only needs that one-page spec (`docs/BOOTSTRAP.md`) to read the manifest, and the manifest
says how to read everything else.

The manifest contains: archive id, company, the channel it was designed for, the number of vaults
and the placement rule, the encoder settings of each pool, each pool's chunk count and offset, and
for each file its key id, nonce, SHA-256, size, offset, ciphertext size and pools. It never contains
keys.

Its framing is fixed so its Fountain settings are fixed too:

```
exactly 4,096 bytes = "LZM1" (4 bytes) + body length (4 bytes, big-endian) + zstd(JSON) + zero padding
```

4,096 bytes → 191 chunks → with redundancy 1.0, **382 strands**. Redundancy 1.0 (twice the
minimum) because the manifest is the single point of failure: lose it and nothing else can be read.
It is stored under the pool name `MANIFEST`, and **every vault gets a full copy**.

Code: `lazarus/lazarus/manifest.py`.

### Step 7: Vaults and order files

Strands are spread across vault sites: strand `i` of each pool goes to vault `(i mod n) + 1`. With 3
vaults, vault 1 gets strands 0, 3, 6, …, vault 2 gets 1, 4, 7, …, and so on. Losing a whole vault
then loses only every third strand of each pool, which the redundancy can absorb (if it is high
enough, and the agent tests exactly that).

Each vault gets:

- `order.fasta`: the strands in the format DNA synthesis vendors accept, one record per strand,
  header `>pool-0000|17`, then the 110 letters.
- `order.csv`: the same as a spreadsheet (name, sequence, length).

These are the files you would send to a synthesis company. Lazarus never actually orders DNA.

Code: `lazarus/lazarus/vaults.py`.

### Step 8: The clean export and the recovery bundle

After approval, all vault order files are joined (without reordering) into
`exports/pre_simulation.fasta`, with ids `vault-N|pool|index`. This is the exact DNA that was
designed: the "before" picture.

`exports/recovery_bundle.json` holds the non-secret metadata a decoder could use if the DNA manifest
itself were lost. The decoder reads the manifest from DNA first and only falls back to the bundle.

Code: `lazarus/lazarus/experiment.py`, `build_clean_export()`.

---

## 3. What happens to the DNA: the channel simulator

Lazarus never makes real DNA. To test an archive, it pushes the designed strands through a
**simulator** that reproduces what synthesis, storage and sequencing do to DNA. The simulator was
**calibrated on real sequencing data**, so its errors behave like real ones: on held-out real
Nanopore clusters, the classic decoder's accuracy on real reads and on simulated reads of the same
strands match within about 3 percentage points, and the simulator errs on the harder side.

For each strand, the simulator does this:

1. **Does the strand survive?** Probability of loss = base dropout + decay per year × years stored +
   a GC penalty. For the Nanopore profile stretched to 100 years:
   0.2% + 0.002 × 100 = **20.2% of strands lost** before reading even starts. The decay rate is an
   extrapolation, not a measurement, so the app always labels it "modeled".
2. **How many reads does it get?** A random number from a **negative binomial distribution**
   (mean = coverage, e.g. 6). This distribution has a long tail: some strands get 15 reads, others
   get 1 or 0. At mean 6 with the Nanopore spread, about 4.5% of surviving strands get zero reads.
3. **Each read gets its own errors.** For every letter, independently: deleted with probability
   p_del, an extra random letter inserted with probability p_ins, swapped with probability p_sub.
   The base Nanopore rates are 2.2% / 1.9% / 1.5%. Each rate is then multiplied by:
   - **homopolymer factor:** deletions get much more likely inside long runs of one letter (×2.3 in
     a run of 5, ×5 in a run of 6, ×6.7 in a run of 7 or more, measured on real reads);
   - **position ramp:** errors rise toward the end of the strand (×1.2 at the last letter);
   - **read quality:** each read gets a random quality multiplier (some reads are just worse);
   - **hot spots:** each position of each strand gets a random multiplier **shared by all its
     reads**. This is the nasty part: if a spot is bad, it is bad in every read, so more reads don't
     help there. That is why real clusters sometimes fail even at high coverage;
   - **sequence context:** a table of multipliers for every 5-letter neighbourhood, fitted on real
     reads (for example, deletions are more likely right after `CCCT`).
   The total chance of an error at any one letter is capped at 50%.
4. **Shuffle and label.** All reads of a tube are shuffled together and written as
   `>read_000001 sample=pool-0000`. The `sample` label is the tube (in a lab, the barcode used to
   separate tubes). Which strand a read came from is **not** in the file. It goes to a separate
   `ground_truth.tsv` that the decoder never opens.

You can also mark whole vaults as destroyed; their strands then produce no reads at all.

There is a second, deliberately different simulator, **Simulator B** (the "red-team channel"). It
uses different mechanisms for everything: bursts of errors, chimera reads glued from two strands,
transitions (A↔G, C↔T) more likely than other swaps, damaged stretches instead of independent hot
spots. Nothing is ever tuned against it. It exists to check that a design that passes on the normal
simulator isn't just exploiting that simulator's quirks.

Code: `lazarus/dna_codec/simulator.py`, `lazarus/dna_codec/simulator_b.py`, profiles in `lazarus/profiles/*.json`, Lazarus
wrapper in `lazarus/lazarus/dna.py` and `experiment.py`.

---

## 4. The decoder, step by step

The decoder takes a FASTA or FASTQ file of reads and returns verified files. **It is only allowed to
see:**

- the read file,
- non-secret metadata (optional; the manifest is read from DNA first),
- a way to look up keys by key id.

It never sees the original strands, the simulator's ground truth, or the uploaded files. That is the
whole point: the test proves the file can be rebuilt **from DNA alone**.

Code: `lazarus/lazarus/decoder.py`, `run()`.

### 4a. Parse and group by tube

The read file is parsed strictly (only A, C, G, T allowed; size and count limits). If it is FASTQ,
the quality scores are ignored. Each read is put in a bucket by its `sample=` label: `MANIFEST`,
`pool-0000`, `pool-0001`, … Reads with no label can't be placed and are reported as a warning.

### 4b. Clustering: which reads came from the same strand?

Inside one tube there are thousands of shuffled reads from hundreds of strands. Before anything can
be voted on, reads have to be grouped by the strand they came from, using **only their letters**.

Why this is possible: thanks to whitening (5f), two *different* strands look like unrelated random
sequences, with an edit distance of about half their length (roughly 55 to 60 for 110 letters). Two reads
of the *same* strand differ only by sequencing errors, a few percent per letter each. So "close" and
"far" are very far apart.

The algorithm (`lazarus/lazarus/clustering.py`):

1. **Greedy pass.** Go through the reads one by one. Each read is cut into all its 8-letter pieces
   (**k-mers**, k = 8). An index maps each k-mer to the clusters whose first read (the
   **centroid**) contains it. For a new read, find the 4 centroids sharing the most k-mers with it
   (at least 3 shared). Check them by edit distance: if one is within 35% of the length (about 38
   edits for 110 letters), the read joins that cluster. Otherwise the read starts a new cluster and
   becomes its centroid.

   Why k-mers first: computing edit distance against every cluster would be far too slow. Shared
   8-letter pieces are a cheap filter. Two random 110-letter strings almost never share three
   8-mers, while two reads of the same strand share many.

   Why such a loose threshold (35%): both the read and the centroid are noisy, so their errors add
   up. Real strangers are around 50%, so 35% still separates them.
2. **Merge pass.** Compute a consensus (4c) for every cluster. If two clusters' consensuses are
   within 30% of each other, merge them. This heals clusters that got split because their first
   read happened to be unusually bad.

Mistakes here are not fatal: a wrong grouping just produces a wrong consensus, the strand checksum
rejects it, and the Fountain code tolerates the missing strand.

### 4c. Consensus, part 1: the classic majority vote

For each cluster, this rebuilds one 110-letter strand from its noisy reads
(`lazarus/dna_codec/baseline.py`, `reconstruct()`):

1. **Cap the reads at 16.** Bigger clusters are thinned to 16 evenly spaced reads (deterministic,
   no randomness).
2. **Pick a draft.** The **medoid**: the read with the smallest total edit distance to all the other
   reads. It is the read most "in the middle" of the cluster. Ties go to the read whose length is
   closest to 110.
3. **Align every read to the draft.** Using Levenshtein alignment, figure out for each read which of
   its letters corresponds to which draft position, where it is missing a letter, and where it has
   an extra one.
4. **Count votes.** For each draft position: how many reads say A, C, G, T, or "missing here". For
   each gap between positions: how many reads have an extra letter there, and which letter.
5. **Rebuild.** Each position takes the letter with the most votes (a tie keeps the draft's letter).
   A position is dropped if "missing" beats every letter. An extra letter is inserted in a gap only
   if a **strict majority** of reads has it.
6. **Repeat** steps 3 to 5 up to 3 times, aligning against the improved draft each time, until it
   stops changing.
7. **Force exactly 110 letters.** If the result is too long, drop the positions with the most
   "missing" votes. If too short, insert at the gaps with the most "extra letter" votes.

Tiny example with 3 reads of `ACGTAC`:

```
read 1: ACGTAC      (perfect)
read 2: ACTTAC      (G swapped for T)
read 3: ACGAC       (T deleted)

aligned to the draft ACGTAC:
position:  1 2 3 4 5 6
read 1:    A C G T A C
read 2:    A C T T A C
read 3:    A C G - A C
votes:     A C G T A C   (G wins 2:1 at position 3, T wins 2:1 over "missing" at 4)
```

This classic method is strong when there are many reads, and weak when there are few: with 3 or 4
reads, one bad read can tip a vote, and "missing" vs "present" is often a coin flip.

### 4d. Consensus, part 2: the learned polisher (the neural network)

This is the AI decoder. It does **not** replace the majority vote. It takes the vote's draft and
**corrects the mistakes the vote left behind**, the same way "polishers" clean up genome assemblies.

Why split the job this way: the classic method is already very good at **alignment** (working out
which letter of read 3 belongs to position 47). What it lacks is **knowledge about the channel**:
which letter patterns this sequencer tends to get wrong, and how much to trust a 4-to-2 vote when
there are only 6 reads. That knowledge is exactly what a small network can learn from data.

#### What the network sees: 17 numbers per position

For each of the 110 draft positions, the network gets 17 features (`features_of()` in
`lazarus/dna_codec/model/polish.py`):

| # | Feature | Meaning |
|---|---|---|
| 0–3 | votes for A, C, G, T | share of reads that have that letter at this position |
| 4 | "missing" votes | share of reads that skip this position |
| 5 | insertion votes | share of reads with an extra letter in the gap before this position |
| 6–9 | inserted letter | share of reads inserting A, C, G or T in that gap |
| 10–13 | draft letter | the draft's letter at this position, one-hot (e.g. G = 0,0,1,0) |
| 14 | coverage | number of reads / 16 |
| 15 | agreement | share of reads that agree with the draft's letter |
| 16 | position | 0 at the first letter, 1 at the last |

So the input is a 17 × 110 grid of numbers: one column per position.

#### The network: a dilated 1D CNN

A **CNN (convolutional neural network)** slides small learned filters along the sequence. A 1D
convolution with kernel size 3 looks at a position and its two neighbours and computes new numbers
from them. Stacking many such layers lets each position see further and further.

**Dilation** spaces the filter's taps apart: dilation 1 looks at neighbours ±1, dilation 2 at ±2,
dilation 8 at ±8. Doubling the dilation each layer grows the field of view exponentially with few
layers.

The exact architecture (`PolishNet`):

```
input: 17 features × 110 positions
  │
stem: convolution, kernel 5, 17 → 128 channels
  │
8 residual blocks, dilations 1, 2, 4, 8, 1, 2, 4, 8
  each block:  x → GroupNorm → GELU → conv (kernel 3, dilation d)
                 → GroupNorm → GELU → conv (kernel 3, dilation d) → add x back
  │
GroupNorm → GELU
  │
  ├── op head (1×1 conv): 6 scores per position
  │     keep | change to A | change to C | change to G | change to T | delete
  └── insert head (1×1 conv): 5 scores per gap
        nothing | insert A | insert C | insert G | insert T
```

- **128 channels:** each position is described by 128 learned numbers inside the network.
- **Residual ("add x back"):** each block learns a *correction* to its input instead of a whole new
  representation. This makes deep networks train much more easily.
- **GroupNorm:** keeps the numbers in a stable range (normalized in 8 groups of 16 channels).
- **GELU:** the non-linearity (a smooth version of "negative becomes zero"). Without it, stacked
  layers would collapse into one linear operation.
- **Field of view:** the stem sees ±2, and each block adds ±2d twice. In total each output position
  can be influenced by about 62 positions on either side, so effectively the **whole strand**.
- **Size:** 805,259 learned numbers (parameters), about **0.8M**. Small enough to run fast on a
  laptop CPU.

Why seeing context helps: on real Nanopore reads, about 45% of the position-to-position variation
in error rates is explained by the surrounding 5 letters. The network can learn "after `CCCT`, a
missing letter is probably a real sequencing deletion, not a real gap", which plain voting cannot.
It also sees coverage, so "4 against 2" means something different at 6 reads than at 16.

#### From scores to an edited strand

The scores go through **softmax**, which turns them into probabilities that add up to 1 (for
example: keep 0.91, change to A 0.02, …, delete 0.04).

Then `apply_edits()` edits the draft:

- **Substitution:** applied where the most likely op is "change to X" and its probability passes the
  substitution threshold.
- **Deletions and insertions are paired.** Both the draft and the true strand have exactly 110
  letters, so a correct edit script must have exactly as many deletions as insertions. The decoder
  takes the k most confident deletions and the k most confident insertions, where k is the smaller
  of the two counts. The output is exactly 110 letters by construction.

The thresholds were tuned on validation data (5.6) and are stored in the checkpoint:

| Cluster size | Substitution needs | Insertion/deletion needs |
|---|---|---|
| 1 to 3 reads | ≥ 70% probability | most likely option (no extra bar) |
| 4 or more reads | most likely option | most likely option |

Why a higher bar at very low coverage: with 1 to 3 reads, an unsure substitution is more often wrong
than right, so it is better to keep the draft.

Lazarus loads this network once (`dna._polish()`), on the GPU if there is one, otherwise Apple
Silicon (MPS) or CPU, and shares it between threads with a lock.

### 4e. Fountain recovery: from strands back to bytes

Now the decoder has one candidate strand per cluster. `lazarus/dna_codec/encoder.py`, `recover()`:

1. **Parse and check each strand.** Letters back to bits. The first 16 letters give the seed. The
   seed regenerates the whitening mask, which is XORed off the payload. Then the CRC-16 is checked.
   Any strand with a wrong CRC, the wrong length, a non-ACGT letter or an impossible seed is dropped.
   Duplicate seeds (two clusters for the same strand) keep the first valid copy.
2. **Enough strands?** If fewer valid strands than chunks remain, recovery fails for this pool.
3. **For each strand, recompute its chunk list from the seed** (same degree and chunk choice as 5d).
   Now every valid strand is an equation: `chunk 177 ⊕ chunk 216 ⊕ chunk 306 ⊕ chunk 349 = (data)`.
4. **Peeling (belief propagation).** Start with every equation that has only one unknown chunk: that
   chunk is now known. XOR it out of every other equation that contains it. Some of those drop to one
   unknown; solve those; repeat. Toy example with 3 chunks:

   ```
   strand A: c1           = 0110      → c1 = 0110
   strand B: c1 ⊕ c2      = 1100      → c2 = 1100 ⊕ 0110 = 1010
   strand C: c2 ⊕ c3      = 0011      → c3 = 0011 ⊕ 1010 = 1001
   ```

5. **Gaussian elimination when peeling gets stuck.** Sometimes every remaining equation has 2 or more
   unknowns. Then the decoder solves the rest as a system of linear equations over bits (XOR is
   addition mod 2), the same row-reduction you learn in algebra class, with XOR instead of
   subtraction. Sparse rows go first to keep it fast.
6. **Check the pool CRC-32.** Join the solved chunks, strip the padding, and compare the 4-byte
   CRC-32 from 5b. If it matches, the pool is recovered.
7. **Poison hunt (rare).** If the CRC-32 fails, some wrong strand slipped past its CRC-16 (a 1 in
   65,536 event per bad strand) and poisoned the solution. The decoder tracks which input strands
   each solved chunk depends on, finds the strands that disagree with the solution, drops the
   suspects and solves again. If that fails too, it retries with random subsets of the extra strands.

`recover()` never crashes on garbage and never returns wrong bytes: it returns the exact data or
nothing.

### 4f. Manifest first, then the pools

The decoder runs 4b to 4e on the `MANIFEST` reads first, with the fixed bootstrap settings. The
manifest then tells it, for every pool, the settings and chunk count it needs. If the manifest can't
be decoded from DNA, the decoder falls back to the recovery bundle (if one was supplied) and says so
in the report. Then every pool is clustered, decoded and recovered.

If both decoders are requested (`baseline` and `polish`), each runs separately and the report shows
both side by side.

### 4g. Rebuild the files and verify

1. Concatenate the recovered pools in order: that is the encrypted stream again.
2. For each file, cut out `stream[offset : offset + cipher_bytes]`.
3. Look up the key by key id. Missing key: the file is reported `key_missing`.
4. **Decrypt** with AES-256-GCM. A wrong key or a single corrupted bit fails the GCM tag check:
   `decryption_failed`.
5. **Decompress** with zstd.
6. **Compute SHA-256** and compare with the manifest's hash (and the recovery bundle's, if given).
   Only an exact match counts as `verified`.

The overall verdict:

- **PASS:** every expected file's hash matches.
- **PARTIAL:** some files match, others don't.
- **FAIL:** no file matches.
- **INCOMPLETE:** something needed was unavailable (manifest, key, decoder).

The report (JSON and HTML) records every step: records parsed, clusters formed per tube, strands
reconstructed and valid per pool, which decoder recovered each file, expected and actual hashes, and
timing. A single PASS is described as one trial, not a reliability guarantee.

---

## 5. How the decoder was trained

The polisher ships as a **pre-trained checkpoint** (`lazarus/checkpoints/polish/polish.pt`). Lazarus does
not retrain it; it loads it and uses it. This section explains how that checkpoint was produced,
using the exact settings stored inside it.

### 5.1 What is being learned, exactly

The task for the network: **given the majority vote's draft and its vote columns, predict the edit
that turns the draft into the true strand.** Per position: keep, change to A/C/G/T, or delete. Per
gap: insert nothing or A/C/G/T.

It does not learn alignment and it does not read raw reads. That keeps the task small, which is why
a 0.8M-parameter network trained in minutes is enough.

### 5.2 The data: real reads plus simulated reads

**Real reads: the Microsoft clustered Nanopore reads dataset.** A public dataset of DNA strands
(110 letters each) that were synthesized and sequenced on Nanopore. For each strand, it gives the
true sequence (the "reference") and its real noisy reads. About 10,000 strands.

It was split three ways, and the split is enforced in code:

- **Held-out set:** every 5th strand (1,996 strands). **Never** used for training, threshold tuning
  or simulator calibration. Only for the final reported numbers.
- **Validation carve:** 500 strands picked at random from the remaining training strands. Used to
  pick the best checkpoint and tune thresholds.
- **Training set:** the rest, about 7,500 strands.

**Simulated reads.** Random 110-letter strands (and 20% at 140 letters, so the network doesn't
overfit to one length) pushed through the simulator with a **random channel for every batch**:

- total error rate drawn between 0.2% and 15% per letter (log-uniform, so low and high rates are
  both well represented), split randomly between substitutions, insertions and deletions;
- homopolymer factor 1.0 to 1.6, end-of-strand ramp 1.0 to 2.0;
- per-read quality spread 0 to 0.8;
- in half of the batches, up to 5% malformed reads (reads that actually belong to another strand,
  like a clustering mistake);
- average coverage 4 to 25 reads.

Why random channels: the network should learn the general skill of "correcting a consensus draft",
not memorize one sequencer. The real reads then teach the real Nanopore patterns.

**Seed discipline:** every random number used in training passes through `train_seed()`, which
refuses the seeds reserved for held-out evaluation (900,000 to 900,999). Training can't accidentally
reuse a held-out draw.

### 5.3 Coverage augmentation

Each training example uses a **random number of reads** from its cluster, drawn fresh each time:

- 75% of examples get 1 to 4 reads (the hard, low-coverage regime);
- 25% get 1 to 16 reads.

The real training set was passed over **24 times**, each time with different random read subsets, so
the same strand appears with many different read combinations. Together with 400,000 simulated
clusters that made about **577,000 training examples**, built in about 18 seconds across 8 worker
processes.

Why weight low coverage: that is where the polisher matters. With 16 reads the vote is usually right
already. With 4 to 6 reads (what a cheap archive will actually get), the vote makes many mistakes the
network can fix.

### 5.4 Turning one cluster into one training example

1. Take the chosen reads and run the **exact same majority vote** the decoder uses at runtime
   (medoid, align, vote, rebuild 3 times, force the length), plus one more alignment pass so the
   vote columns match the final draft.
2. Build the 17 × L feature grid from the draft and votes (4d).
3. Make the **labels** by comparing the draft with the true strand using
   `Levenshtein.editops(draft, truth)`, which lists the minimal edits:
   - "replace position 47 with G" → op label at 47 = change to G;
   - "delete position 80" → op label at 80 = delete;
   - "insert T before position 12" → insert label at gap 12 = insert T;
   - every other position: keep / nothing.

Because training uses the same draft procedure as inference, the network learns to fix exactly the
kind of drafts it will see in real use.

### 5.5 The training loop

| Setting | Value | What it means |
|---|---|---|
| Steps | up to 10,000 | one step = one update of the weights |
| Batch size | 512 examples | examples per step, drawn at random |
| Optimizer | AdamW | adaptive gradient descent with weight decay |
| Learning rate | 0.002 peak | how big each update step is |
| Warmup | 200 steps | learning rate ramps up linearly from 0 |
| Schedule | cosine, floor 10% | after warmup it eases down smoothly to 10% of the peak |
| Weight decay | 0.01 | gently pulls weights toward 0, against overfitting |
| Loss | cross-entropy (op head) + cross-entropy (insert head) | how wrong the predicted probabilities are |
| Gradient clipping | 1.0 | caps very large updates, keeps training stable |
| Precision | bfloat16 on GPU | faster math, same results in practice |
| Time budget | 20 minutes | training stops after this, whatever the step |

**Cross-entropy**, in plain words: if the true label at a position is "delete" and the network gives
"delete" a probability of 0.9, the loss there is small (−log 0.9 ≈ 0.11). If it gives 0.01, the loss
is large (−log 0.01 ≈ 4.6). Training nudges every weight in the direction that lowers the average
loss over the batch (that direction is the **gradient**, computed by **backpropagation**). Most
positions are "keep", so the network mainly learns *when* to step in.

Each step picks a strand-length bucket (110 or 140, in proportion to their sizes), draws 512 random
examples of that length, runs the network, computes the loss and updates the weights.

### 5.6 Choosing the checkpoint and tuning the thresholds

Every 2,000 steps the network was tested on the 500-strand validation carve at 2, 4, 6, 10 and 16
reads per strand, measuring **exact strand accuracy** (all 110 letters right). The best mean so far
was saved.

The best checkpoint came at **step 8,000, about 10 minutes in** (training loss about 0.095). The
full 10,000 steps took about 13 minutes on a single GPU machine.

Then the application thresholds (4d) were tuned on the same validation carve: every combination of
{0, 0.3, 0.5, 0.7, 0.9, 0.98} for (substitution, insertion/deletion), separately for clusters of 1
to 3 reads and for bigger ones, keeping whichever gave the best mean accuracy. The result is the
table in 4d.

Validation accuracy after tuning (exact strands, polisher vs majority vote):

| Reads per strand | 2 | 4 | 6 | 10 | 16 |
|---|---|---|---|---|---|
| Majority vote | 5.2% | 44.2% | 70.2% | 83.2% | 88.2% |
| Polisher | 6.4% | 60.0% | 82.2% | 92.8% | 94.8% |

### 5.7 The final, honest numbers (held-out real reads)

Measured on the 1,996 held-out real strands the network never saw, averaged over 20 independent
random draws of reads per point (± is the standard deviation):

| Reads per strand | 2 | 4 | 6 | 10 | 16 |
|---|---|---|---|---|---|
| Majority vote | 5.2% ±0.5 | 39.9% ±0.9 | 67.2% ±0.8 | 84.1% ±0.5 | 89.7% ±0.3 |
| Polisher, default (what Lazarus runs) | 5.8% ±0.5 | 56.7% ±1.2 | 82.3% ±0.9 | 92.9% ±0.3 | 95.3% ±0.2 |
| Polisher, best variant | 7.0% ±0.7 | 66.6% ±1.1 | 88.1% ±0.5 | 95.7% ±0.3 | 97.2% ±0.2 |

How to read this:

- **A single read is exactly right only 1.1% of the time.** Without consensus, DNA storage at these
  error rates would not work at all.
- **At 6 reads**, the default polisher gets 82.3% of strands exactly right against 67.2% for the
  majority vote. The best variant reaches 88.1%: it polishes from 3 different starting drafts,
  runs 2 rounds, and picks edits jointly by log-odds. It is about 4 times slower, and **Lazarus runs
  the default path** (1 draft, 1 round). Keep that in mind when quoting the 88.1% figure.
- **At 2 reads** it is basically a tie: with 2 reads the draft is essentially one read, and there
  is nothing to vote with.
- **Ceiling:** even with every available read, 4.7% of strands fail. Their errors are shared by all
  reads (hot spots) or the cluster itself is malformed. No decoder can fix those, which is why the
  Fountain code's redundancy is still needed.

Why strand accuracy matters so much: the Fountain code needs a minimum number of valid strands. If
the decoder rebuilds more strands correctly, the archive needs fewer reads per strand or less
redundancy for the same safety, which means less DNA and less money.

### 5.8 What didn't work: a big transformer

Before the polisher, a 9.6M-parameter transformer (`ConsensusNet`, `lazarus/dna_codec/model/net.py`) tried to
learn the whole job end to end, alignment included, straight from raw reads. After 11,300 training
steps it reached 1.4% / 5.6% / 10.8% exact strands at 2 / 6 / 16 reads, against 4.8% / 68.1% /
90.6% for plain majority vote, and it was improving too slowly. It was dropped. The polisher is 12
times smaller, trains in about 13 minutes and beats the classic method.

The lesson: put the learning where knowledge is missing (the channel's error patterns), not where
the problem is hardest (alignment, which the classic algorithm already does very well).

---

## 6. The second learned model: the risk model

The polisher helps at **read** time. The risk model helps at **write** time: it predicts, for a
candidate strand, how likely the decoder is to get it wrong on a given channel. The encoder uses it
to pick the safest of several equally valid candidates (5h).

**How it is trained** (`lazarus/dna_codec/risk.py`; Lazarus's "fresh learning" in
`lazarus/lazarus/learned_worker.py`):

1. **Generate controlled training strands.** Random strands plus strands with deliberately risky
   features (letter runs of 2 to 10, skewed GC from 15% to 85%, repeats). Lazarus's quick version
   uses 512 strands of 110 letters.
2. **Label each strand with a failure rate.** Simulate it 8 times on the customer's channel, decode
   each noisy cluster with the frozen polisher, and count how often the result is wrong. The label is
   a rate (for example 3 of 8 = 0.375), not a single pass/fail, because a single outcome is mostly
   luck. Strands that got no reads at all are left out: loss isn't the decoder's fault.
3. **Train a small CNN** to predict that rate from the letters alone:
   - input: 6 channels per position (one-hot A, C, G, T, a mask for real positions, relative
     position);
   - a convolution with kernel 9, then residual blocks (kernel 5 convolution, batch norm, GELU, 1×1
     convolution);
   - average and maximum over all positions, then a small 2-layer head that outputs one number;
   - loss: binary cross-entropy against the soft failure rate; AdamW with a one-cycle learning-rate
     schedule; early stopping on a validation slice.
   - Lazarus's quick version: 24 channels, 2 blocks, up to 12 epochs.
4. **Evaluate on 128 separate strands** with their own failure labels, using rank correlation
   (Spearman): does the model rank risky strands above safe ones?

A risk model is only valid for **one channel, one reading budget and one decoder**. Lazarus records
all three, plus hashes of the decoder checkpoint and the codec source, and refuses to load a model
for a different combination.

What it learns by itself (from the larger research runs): letter runs are dangerous, but from 4 to 5
letters rather than the textbook 3; G and C runs are worse than A and T runs; the channel's real
deletion contexts matter; and on Illumina (which is much cleaner) everything scores near zero.

---

## 7. How Lazarus tests an archive before anyone approves it

Encoding and decoding are only useful if the design is proven to work. Before a human can approve an
order, Lazarus:

1. **Freezes candidate designs**: the exact strands for a given redundancy, with or without the risk
   model, so what gets tested is exactly what would be ordered.
2. **Screens them** with simulated reading at the customer's coverage and retention period, using
   **training seeds**, from the cheapest redundancy (0.8) upward, comparing standard and learned
   encodings under identical conditions. The cheapest design that passes within budget is selected.
3. **Runs a final check on held-out seeds** that were never used for selection. If it fails, no
   order can be approved, and that final test cannot be re-rolled: the archive has to be revised
   (more reads or more redundancy) and tested again from the start. This stops "try again until it
   works" from passing off luck as reliability.
4. **Stress-tests** it under conditions it was not tuned on: one vault site destroyed, twice the
   storage time, only 60% of the planned reads, and the red-team simulator B. A stress trial only
   passes if every pool of the archive comes back.

Every number in the workspace comes from real encode → simulate → decode runs. Nothing is estimated
by asking a language model.

---

## 8. Glossary

| Term | Meaning |
|---|---|
| AAD | Data bound into the encryption's authentication without being encrypted (`lazarus-v1`) |
| AES-256-GCM | Encryption with a 256-bit key that also detects any tampering (via a 16-byte tag) |
| Alignment | Matching each letter of a read to a position in a reference or draft |
| Backpropagation | The method that computes how to change each weight to lower the loss |
| Bijection | A one-to-one mapping: every input gives a different output |
| Bootstrap setting | The one fixed encoder setting used for the manifest, published so future readers can start |
| CNN | Convolutional neural network: learned filters slid along the sequence |
| Consensus | One best-guess strand built from many noisy reads |
| Coverage | Average number of reads per strand |
| CRC | Cyclic redundancy check: a short checksum that detects accidental errors |
| Cross-entropy | Loss that punishes giving low probability to the correct answer |
| Degree | How many data chunks are XORed into one strand |
| Dilation | Spacing between a convolution filter's taps, to see further with few layers |
| Draft | The current best guess of a strand during consensus |
| Dropout (DNA) | A strand that produces no reads |
| Edit distance | Minimum substitutions, insertions and deletions to turn one string into another |
| Fountain / LT code | Code where each output mixes random inputs, and any large enough subset decodes |
| GC content | Share of G and C letters |
| Held-out | Data kept aside and never used for training or tuning, only for final numbers |
| Homopolymer | A run of one repeated letter |
| k-mer | A piece of k consecutive letters |
| Manifest | The instructions for reading the archive, stored in DNA |
| Medoid | The member of a group with the smallest total distance to all others |
| Nonce | A random number used once per encryption; not secret |
| Peeling | Solving XOR equations one known chunk at a time |
| Pool | One tube of mixed strands, holding up to ~12 KB of data |
| Read | One sequencer output string for one molecule |
| Redundancy | Extra strands beyond the minimum, as a fraction (0.3 = 30% more) |
| Residual block | A layer that adds a learned correction to its input |
| Robust soliton | The degree distribution that makes peeling succeed with little overhead |
| Seed | The number in a strand's first 16 letters that determines its chunk mix and mask |
| SHA-256 | A 64-hex-character fingerprint of a file |
| Softmax | Turns raw scores into probabilities that add up to 1 |
| Strand / oligo | One short synthetic DNA molecule, here 110 letters |
| Whitening | XORing data with a pseudo-random mask so strands look random |
| XOR | Bitwise "different?": 1 if the bits differ, 0 if they're equal; undoes itself |
| zstd | Zstandard, a fast modern compression algorithm |

---

## 9. Where each piece lives in the code

The DNA codec is bundled in `lazarus/dna_codec/`, with its channel profiles in `lazarus/profiles/` and
the pre-trained decoder in `lazarus/checkpoints/`. Lazarus's own code is in `lazarus/lazarus/`.

| Piece | File |
|---|---|
| Compress, encrypt, hash, pool size | `lazarus/lazarus/crypto.py` |
| Stream and pool splitting, synthesis order | `lazarus/lazarus/tools.py` (`prepare_archive`, `place_synthesis_order`) |
| Fountain encoder and recovery | `lazarus/dna_codec/encoder.py` (`encode`, `recover`, `_Layout`, `_solve`) |
| Encoder settings and file metadata | `lazarus/dna_codec/types.py` |
| Lazarus wrapper around the codec | `lazarus/lazarus/dna.py` |
| DNA manifest (bootstrap) | `lazarus/lazarus/manifest.py`, spec in `docs/BOOTSTRAP.md` |
| Vault placement and order files | `lazarus/lazarus/vaults.py` |
| Clean export, read simulation runs | `lazarus/lazarus/experiment.py` |
| Channel simulator A and red-team B | `lazarus/dna_codec/simulator.py`, `lazarus/dna_codec/simulator_b.py` |
| Channel profiles (calibrated) | `lazarus/profiles/nanopore_budget.json`, `lazarus/profiles/illumina_standard.json` |
| FASTA/FASTQ parsing | `lazarus/lazarus/fasta.py` |
| Read clustering | `lazarus/lazarus/clustering.py` |
| Majority vote decoder | `lazarus/dna_codec/baseline.py` |
| Learned polisher (network, features, edits) | `lazarus/dna_codec/model/polish.py` |
| Polisher training | not bundled: only the trained checkpoint `lazarus/checkpoints/polish/polish.pt` ships |
| Real dataset loader and held-out split | `lazarus/dna_codec/realdata.py` |
| Seed discipline | `lazarus/dna_codec/seeds.py` |
| Standalone decoder and verification report | `lazarus/lazarus/decoder.py` |
| Risk model | `lazarus/dna_codec/risk.py`; Lazarus training worker `lazarus/lazarus/learned_worker.py` |
| Candidate designs and approval checks | `lazarus/lazarus/candidates.py`, `lazarus/lazarus/learned.py` |
