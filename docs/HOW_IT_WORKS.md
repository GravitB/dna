# How Lazarus works, end to end

## 1. What we sell

Some companies must keep records for decades: pharma clinical-trial records (25+ years), bank records,
legal holds. Hard drives, tape and cloud accounts typically need migrating every 5 to 10 years. DNA
lasts centuries if kept cool and dry, and it is extremely dense.

DNA is also noisy: letters get swapped, added or lost, and whole strands disappear. No normal company
knows how to design a DNA archive or prove it can be read back. **Lazarus is the AI engineer that does
that, and the product is the proof**: a certificate showing the archive was rebuilt from DNA alone,
byte for byte.

## 2. How the customer puts documents in

1. They open the web app and fill in a policy: retention years, the sequencing technology the DNA
   vendor will use (Nanopore or Illumina), planned reads per strand, budget, recovery target and the
   number of vault sites.
2. They upload files of any type (PDF, CSV, images…) through the browser. The demo limit is 200 KB
   total, and a "Northstar Bio" sample set is included.
3. The files land in `jobs/<id>/uploads/` and the AI agent takes over.

Today it is upload only. A real product would add connectors to S3, SharePoint or Google Drive.

## 3. The pipeline, step by step

```
Your files ──► 1 Triage ──► 2 Compress + encrypt ──► 3 One stream, split into pools
  ──► 4 Encoder (bytes → A/C/G/T strands) ──► 5 Agent tunes and attacks the design
  ──► 6 Human approves ──► 7 Synthesis order per vault + DNA manifest
  ══ decades pass / disaster ══
  ──► 8 Sequencing (DNA → noisy reads) ──► 9 Decoder (reads → strands → bytes)
  ──► 10 Decrypt + SHA-256 check ──► original files, byte-exact ──► 11 Certificate
```

### Step 1: Triage
The agent lists every file with its size, type and SHA-256 fingerprint. Only cold, immutable,
long-retention files go into DNA. A file that is edited daily, such as `weekly_standup_notes.txt`, stays
on normal storage, because DNA is write-once and expensive.

### Step 2: Compress and encrypt (`crypto.py`)
Each file is compressed with zstd (fewer bytes means fewer DNA letters, which means a cheaper archive),
then encrypted with AES-256-GCM. Each file gets its own key, kept in the customer's key store (the
`kms/` folder stands in for a KMS). **The key never goes into DNA.** GCM also adds a tamper-detection tag.

### Step 3: One stream, balanced pools
All encrypted files are joined into one byte stream and cut into equal pools of at most about 12 KB. A
pool is one batch of DNA (in a lab: one tube or primer pair). Tiny pools turned out to be fragile in
testing, so equal sizes matter.

### Step 4: The encoder (the bundled codec’s DNA Fountain code)

**a) 2 bits per letter.** A=00, C=01, G=10, T=11, so one byte is four letters:
`'H' = 0x48 = 01 00 10 00 → C A G A`. In practice the strands look nothing like the file, because the
data is encrypted and then mixed.

**b) Chunks.** Each strand has 110 letters (220 bits):
```
[ seed: 16 letters = 32 bits ][ payload: 94 letters = 188 bits = 172 bits of data + 16-bit CRC ]
```
A 12 KB pool becomes about 560 chunks of 172 bits. A CRC-32 of the whole pool is prepended so the
decoder can later prove the result is exact.

**c) Fountain mixing.** Strands do not store chunk 1, chunk 2, chunk 3 in order. For each strand the
encoder takes a seed, which drives a random-number generator. The generator picks a degree `d` from the
robust soliton distribution (most strands combine 1 to 3 chunks, a few combine many), picks `d` chunks
and XORs them together. The strand stores the seed plus the XOR result, and whoever knows the seed can
work out which chunks were used. So no strand is special: any set of good strands slightly larger than
the number of chunks rebuilds everything.

**d) Redundancy.** With 560 chunks, redundancy 1.0 writes 1,120 strands and 1.5 writes 1,400. Extra
strands are insurance against loss, and redundancy is the main dial the AI tunes (safer but more
expensive).

**e) Biology-safe screening.** For each strand the encoder tries several seeds and keeps one with at
most 3 identical letters in a row and 40 to 60% G+C, because long runs and extreme GC content cause
sequencing errors and dropouts.

**f) Whitening.** The payload is XORed with a seed-derived mask, so even a file of all zeros produces
balanced DNA.

**g) Checksums.** Each strand carries a CRC-16, so a damaged strand is detected and dropped instead of
poisoning the rebuild.

### Step 5: The agent designs and attacks it (deepagents)
The **codec-engineer** subagent runs real experiments: encode, simulate sequencing, decode and check,
many times over different redundancy and read-count settings. It picks the cheapest design that meets
the target.

The **adversary** subagent then attacks that design four ways:
- destroying one vault site
- a different sequencer model (the bundled codec’s Simulator B, which the design was not tuned on)
- twice the storage time
- 60% of the planned reads

If any attack breaks the design, the supervisor raises redundancy or reads and tests again. In our runs,
redundancy 0.6 failed vault loss (0/4), 1.2 recovered 2/4 and 1.5 survived 4/4.

### Step 6: Human approval
The agent pauses (deepagents `interrupt_on`) and shows the number of letters to synthesize, the modeled
cost and the attack results. Nothing is ordered without a person approving it.

### Step 7: Synthesis orders and the DNA manifest (`vaults.py`, `manifest.py`)
Strand *i* goes to site *(i mod N)*, so losing one site loses every Nth strand, which the Fountain code
tolerates. Each site gets `order.fasta` and `order.csv`, the formats DNA vendors accept for oligo pools.

The decoder needs settings (strand length, redundancy, chunk counts, file offsets, hashes). If those
lived only in software they could be lost, so the manifest is itself written into DNA with one fixed,
published setting, and every vault gets a full copy. A future reader needs only the one-page
[bootstrap spec](BOOTSTRAP.md).

The sequences and order files are real; physical synthesis is not done. In the real world: the vendor
synthesizes the pool, the DNA is dried or encapsulated and stored in the vaults, and years later a
sequencer reads it.

### Step 8: Sequencing
A sequencer returns many noisy copies (reads) of each strand. We simulate it with the bundled codec’s channel
model, calibrated on real Nanopore data. Per letter, it applies roughly 1.5% substitutions, 1.9%
insertions and 2.2% deletions, more inside letter runs and at strand ends. It also loses some strands
entirely, adds extra loss per year of storage, and gives about 10 reads per strand. In our simulation
the reads arrive already grouped per strand; a real lab first clusters them by similarity.

### Step 9: The decoder
**a) Majority vote.** Pick the read closest to all the others as a draft, align every read to it (the
alignment handles insertions and deletions), vote letter by letter, and repeat 3 times.

**b) CNN polisher (deep learning).** the bundled codec’s 1D convolutional network reads the vote counts at each
position and its neighbors, predicts where the vote is wrong and fixes it. It was trained on real
Microsoft Nanopore reads, and the bundled codec reports 82% vs 67% exactly-correct strands at 6 reads. Lazarus
runs both decoders on the same reads and reports both; in our runs the CNN recovered a file the classic
decoder lost.

**c) Drop bad strands** whose CRC-16 fails.

**d) Fountain solve.** Peeling: find a strand holding a single chunk, so that chunk is known; XOR it out
of every other strand that used it, and repeat. If peeling stalls, use Gaussian elimination over GF(2).
This needs only slightly more good strands than chunks, in any order, from any surviving site.

**e) Pool check.** The CRC-32 must match. If a wrong strand slipped through, it is traced, dropped and
the solve is retried. The output is exact bytes or nothing, never wrong bytes.

### Step 10: Decrypt and verify
Join the pools, cut out each file by its manifest offset, decrypt with the customer's key (the GCM tag
catches tampering), decompress, and compare the SHA-256 with the fingerprint taken at upload. A match
means the identical file came back.

### Step 11: Certificate
The compliance subagent writes an HTML report: the design, every attack with trial counts, the drill
(which sites were read and which decoder succeeded), per-file hash matches, and a timestamped chain of
custody of every agent action.

## 4. Seven layers of protection

| Layer | Protects against |
|---|---|
| Many reads per strand + majority vote | Random sequencer errors |
| CNN polisher | Errors the vote cannot fix |
| CRC-16 per strand | Corrupted strands poisoning the rebuild |
| Fountain redundancy | Lost strands and lost vault sites |
| CRC-32 per pool | A wrong strand slipping through |
| AES-GCM tag + SHA-256 | Tampering, and proof of exact recovery |
| DNA manifest + bootstrap spec | Losing the software or settings |

## 5. Honest limits
- DNA synthesis currently costs orders of magnitude more per MB than cloud storage. Lazarus is for
  small, critical, very-long-retention records. Costs shown are the bundled codec placeholder prices labeled
  "modeled".
- Physical DNA is simulated. The channel model is calibrated on real reads; storage decay is
  extrapolated.
- Trial counts are small (4 to 8 per point) and use train-only seeds. We never pick lucky seeds.
- the bundled codec built the encoder, the simulators and the decoders. Lazarus built the enterprise workflow
  around them: the agent team, red teaming and redesign, encryption, multi-site placement, the DNA
  manifest, the disaster drill, the certificate and the app.
