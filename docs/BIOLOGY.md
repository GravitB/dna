# DNA data storage: the biology, explained from zero

DNA data storage combines computer science, biology, chemistry and error-correcting algorithms. This
guide needs no biology background. It covers the fundamentals, what happens when a computer file is
converted into DNA, why errors occur, how DNA is read, and what problem the bundled codec (and therefore Lazarus)
solves.

---

## 1. What is DNA?

DNA stands for **deoxyribonucleic acid**. It is the molecule that stores genetic information in living
organisms; cells use it as instructions for making proteins.

DNA is essentially a **physical information storage system**. A computer stores information with two
symbols, `0` and `1`. DNA stores information with four chemical symbols, called **bases** (nucleobases):

| Letter | Base |
|---|---|
| A | Adenine |
| T | Thymine |
| G | Guanine |
| C | Cytosine |

A sequence looks like `ATGCCGTAACGTTAGC`. It is a physical molecule with the bases in that order, and
the order matters, just like the order of letters in a sentence or bits in a file.

### What DNA physically looks like

DNA usually has two strands twisted together into a **double helix**, like a twisted ladder:

- The sides of the ladder are repeating sugar and phosphate molecules.
- The rungs are pairs of bases.
- **A always pairs with T, and G always pairs with C.**

```
First strand:   A T G C
                | | | |
Second strand:  T A C G
```
(Simplified base pairing, without the twist.)

DNA does not have to come from a living organism. Scientists can manufacture artificial DNA in a lab,
which makes DNA usable as a storage medium with no organism involved.

---

## 2. How a computer file becomes DNA

Every file (image, video, PDF, song, text) is ultimately a sequence of bits.

**Step 1: map binary to bases.** Four bases can represent the four two-bit combinations, so each base
can store 2 bits:

| Binary | Base |
|---|---|
| 00 | A |
| 01 | C |
| 10 | G |
| 11 | T |

**Step 2: encode the file.** The capital letter `A` in ASCII is `01000001`:
```
01 00 00 01
 C  A  A  C   →  CAAC
```
That is **DNA encoding**.

**Step 3: make it physical.** `CAAC` is still just text on a computer. To store it in DNA, a lab must
build a molecule with those bases in that order. This is **DNA synthesis**:
1. A computer specifies the sequence.
2. A DNA synthesizer builds the molecule.
3. The DNA is collected and stored.

In practice, labs make much longer sequences, and large collections of them. This is the difference
between *simulating* DNA storage (software) and *actually* storing data in DNA (real molecules and lab
equipment).

---

## 3. The whole DNA storage pipeline

1. **Digital file.** For example `photo.png`.
2. **Encoding.** Convert the bits into DNA sequences (`ATGCTAGC…`).
3. **Synthesis.** Manufacture physical DNA molecules with those sequences.
4. **Storage.** Keep the molecules in a tube or another protective medium.
5. **Retrieval and preparation.** Collect the DNA and, if needed, make more copies with PCR.
6. **Sequencing.** A machine reads the order of the bases.
7. **Decoding.** Convert the recovered sequences back into bits.
8. **File recovery.** Rebuild `photo.png` and verify it is correct.

**Why bother?** DNA has extraordinarily high theoretical information density and can last a long time,
which makes it promising for dense, long-term archives. The catch: DNA is much harder to write and read
reliably than a hard drive. That is where the bundled codec’s core problem begins.

---

## 4. The problem: DNA data gets corrupted

On a damaged USB drive you might write `01000001` and read back `01010001`. One bit flipped, and the file
may be wrong. DNA has the same problem:
```
Original:   ATGCCATA
Recovered:  ATGTCATA     (the C at position 4 became a T)
```
One changed base can corrupt the underlying bits. Four kinds of error matter:

| Error | Meaning | Example |
|---|---|---|
| Substitution | One base is replaced | `ATGC → ATTC` |
| Insertion | An extra base appears | `ATGC → ATTGC` |
| Deletion | A base goes missing | `ATGC → AGC` |
| Dropout | A whole strand is missing | One of 1,000 stored fragments is never recovered |

A **deletion** removes one letter from a strand. A **dropout** means the entire strand is absent from the
data. Both matter more when a large file is split into thousands or millions of short fragments.

---

## 5. PCR amplification

**PCR (polymerase chain reaction)** takes a small amount of DNA and makes many copies of it, like a
biological photocopier. Ideally each cycle doubles the DNA (1 → 2 → 4 → 8 copies); in reality it is less
efficient.

Each PCR cycle has three stages:
1. **Denaturation.** Heat separates the two strands (pull the ladder apart).
2. **Annealing.** Short sequences called **primers** attach at specific spots and mark where copying starts.
3. **Extension.** An enzyme, **DNA polymerase**, builds new complementary strands. (An enzyme is a
   molecule, usually a protein, that speeds up a chemical reaction.)

The cycle repeats many times.

### PCR amplification bias

PCR does not copy every sequence equally:
- Some sequences amplify more easily than others because of their structure or composition.
- Polymerase occasionally inserts a wrong base, and the mistake is inherited by later copies.

| Fragment | Starting copies | Copies after PCR |
|---|---|---|
| A | 100 | 10,000 |
| B | 100 | 8,000 |
| C | 100 | 300 |

(Illustrative numbers, not experimental data.)

Fragment C barely got copied, so a sequencer sampling the mixture is much less likely to see it. Losing
one essential fragment can make the file unrecoverable.

---

## 6. Natural DNA degradation

DNA can break down over time. It is durable in the right conditions, but not indestructible. Water, heat,
oxygen and UV light can chemically change bases, break strands, or leave molecules unusable.

Archival DNA is usually kept **outside** living cells, so "degradation" does not mean an organism
mutating. It means the molecules themselves deteriorate, like a photograph slowly fading.

---

## 7. Homopolymers

A **homopolymer** is a run of the same base repeated, for example `AAAAAAAA` (compare a mixed sequence
like `ATGCTAGC`). Homopolymers cause trouble during synthesis, PCR and sequencing. Polymerase can slip on a
repeated stretch and add or drop bases, and nanopore sequencing has its own difficulty with them
(section 10). That is why DNA encoders cap how many identical bases may appear in a row.

---

## 8. GC content

**GC content** is the percentage of bases that are G or C. For `GCGCGCATAT`, 6 of 10 bases are G or C:
```
GC content = 6 / 10 × 100 = 60%
```

**Why it matters.** G–C pairs have three hydrogen bonds, while A–T pairs have two. GC-rich DNA is generally
more thermally stable, though neighboring bases and conditions matter too. Very GC-rich DNA can be hard to
separate during PCR and can form stable structures that block copying. Very GC-poor DNA causes problems as
well. So encoders usually target a middle range. There is no universally optimal GC percentage for every
lab workflow or sequencer.

### Secondary structure

DNA is not always a straight string. Parts of a strand can fold back and pair with the same strand,
forming shapes such as a **hairpin**. A stable hairpin can stop polymerase from moving along or copying the
strand. So it matters not only *which* letters are present but *how they are arranged*.

---

## 9. DNA sequencing

- **Synthesis** writes DNA.
- **Sequencing** reads DNA.

A sequencer takes physical molecules and reports their base order (for example `ATGCTAGCGCTA`), and a
decoding algorithm turns that back into digital data. Two important technologies are **Oxford Nanopore**
and **Illumina**.

Note: **NanoDrop** is a different instrument. It measures DNA/RNA concentration and purity and does not
read sequences. The technology discussed here is **Nanopore**.

---

## 10. Nanopore sequencing: reading DNA with electricity

- A **nanopore** is a tiny opening, often a protein embedded in a membrane (a thin barrier between two
  liquid regions).
- The liquid contains **ions** (charged particles). When a voltage is applied across the membrane, ions
  flow through the pore and create an electrical current, like water through a narrow pipe.
- A **motor protein** feeds DNA through the pore at a controlled speed (separating double strands as it goes).
- The DNA partly blocks the ion flow. Different combinations of bases produce different current patterns.
- A **basecaller** algorithm translates the current measurements into a DNA sequence.

### Why homopolymers are hard for nanopore
The signal depends on a small group of neighboring bases inside the pore, not on each base alone. In
`AAAAAAAAAA`, consecutive positions give very similar signals, so the machine must infer the run length
from timing. Was it 9 A's, 10 or 11?
```
Original:   AAAAAAAAAA
Recovered:  AAAAAAAAA     (one A lost: a deletion error)
```
Modern nanopore chemistry and AI basecalling have improved a lot; this is a challenge, not an absolute limit.

---

## 11. Illumina sequencing: reading DNA with light

Illumina uses **sequencing by synthesis (SBS)**: instead of measuring DNA as it passes through a pore, it
watches a new strand being built.

1. **Prepare fragments.** Short DNA sequences called **adapters** are attached so fragments can connect
   to the sequencing system.
2. **Make clusters.** Fragments attach to a **flow cell** (where the reactions happen) and are copied in
   place into clusters of identical copies (**cluster amplification**).
3. **Add fluorescent nucleotides.** Modified A, T, G and C building blocks carry a light-detectable label
   and a reversible block, so only one base is added per strand per cycle.
4. **Image.** The fluorescence shows which base was added (for example, G).
5. **Repeat.** The label and block are removed and the next base is added, until the sequence is read.

Note: modern Illumina SBS does not feed one nucleotide type at a time. All four are available in each
cycle and the complementary base is incorporated. Different Illumina chemistries detect the fluorescence
in different ways.

**Illumina errors** come from preparation, amplification and chemistry. GC-rich fragments may amplify
differently, giving uneven coverage, and copies within a cluster can fall out of sync. Its base-by-base
reading generally handles homopolymer lengths much better than older nanopore approaches.

---

## 12. Nanopore vs Illumina

| Feature | Nanopore | Illumina |
|---|---|---|
| Reading mechanism | Electrical current | Fluorescence during synthesis |
| What it measures | Current changes as DNA moves through a pore | Bases added to a growing strand |
| Read length | Can read very long molecules | Typically short reads |
| PCR required? | Not inherently | Cluster amplification is built in; library PCR may also be used |
| Homopolymers | Can cause length-counting errors | Generally handled well |
| GC problems | Can affect preparation and signal analysis | Can cause amplification and coverage bias |

Both have other error types too, and actual error rates depend on the instrument, chemistry, sample
preparation and software. **That is why one universal encoding strategy is unlikely to be optimal for
both.**

---

## 13. Redundancy and error correction

**Redundancy** means adding extra information or copies so the original data can still be recovered when
something goes wrong. If a file is split into exactly 100 essential fragments, losing one may make it
unrecoverable. With an error-correcting code, you might encode 100 data fragments into 120 encoded
fragments (20% redundancy), and losing some of the 120 can still allow complete recovery. How much loss is
tolerated depends on the code and on the type and pattern of errors.

Redundancy costs resources: more fragments mean more synthesis and storage, and reading more material can
raise sequencing cost. That is the core **density vs cost vs reliability** trade-off.

### Three kinds of redundancy

| Type | Meaning |
|---|---|
| Logical redundancy | Extra encoded information that helps rebuild missing or damaged data |
| Physical redundancy | Many molecular copies of the same sequence |
| Sequencing depth | Reading each sequence multiple times for more confidence |

They are not interchangeable. 1,000 copies of fragment A and zero copies of fragment B do not recover B;
you need error-correcting information to rebuild it.

### Error-correcting codes (ECC)

An **ECC** adds structured information so errors can be detected and, within limits, corrected. DNA
storage uses codes such as **Reed–Solomon** and **fountain codes**. These are computer-science
algorithms, not biological processes: biology introduces the uncertainty, and the code overcomes it.

---

## 14. What the bundled codec improves

Researchers already follow biological rules when encoding: limit homopolymers, restrict GC content, avoid
troublesome structures, and add redundancy. But each rule is a compromise:

| Parameter | Encoder A | Encoder B |
|---|---|---|
| Max homopolymer length | 3 | 5 |
| GC target | 50% | 40–60% |
| Added redundancy | 30% | 15% |
| Reliability | To be tested | To be tested |

You cannot tell which is better from the numbers alone. It depends on the sequencer, preparation,
amplification and storage. That is why a **DNA storage simulator** is useful:
1. Encode a real file into DNA sequences.
2. Measure GC content, homopolymer lengths and other risk features.
3. Simulate synthesis errors, PCR bias and degradation.
4. Simulate Nanopore or Illumina sequencing errors.
5. Decode the corrupted sequences and try to rebuild the file.
6. Measure how much redundancy was needed for reliable recovery.

Then try different encodings and find the ones that recover reliably with the least overhead. Biological
knowledge of the physical process is used to improve the algorithms.

Research caveat: DNA-storage simulators already exist, for example a 2023 Nature Communications "digital
twin" that models synthesis, PCR, aging and Illumina sequencing errors. The opportunity is not inventing
simulation itself but improving the model, its validation or the optimization.

---

## 15. Glossary

| Term | Simple meaning |
|---|---|
| DNA | Physical molecule that stores biological information |
| Nucleotide | Building block of DNA: a base, a sugar and a phosphate |
| Base | One of the four letters: A, T, G, C |
| DNA strand | Chain of nucleotides |
| Double helix | Two paired strands twisted together |
| Oligonucleotide (oligo) | A short DNA or RNA molecule |
| Base pair (bp) | Two complementary bases paired together |
| DNA synthesis | Manufacturing DNA molecules |
| DNA sequencing | Reading the order of bases |
| PCR | Making many copies of selected sequences |
| Primer | Short sequence that starts copying |
| DNA polymerase | Enzyme that builds DNA strands |
| GC content | Percentage of G and C bases |
| Homopolymer | A run of the same base |
| Secondary structure | A strand folding into shapes such as hairpins |
| Amplification bias | Some sequences being copied more efficiently than others |
| Degradation | Chemical or physical damage to DNA |
| Nanopore | Tiny hole used to read DNA through electrical signals |
| Basecalling | Converting sequencer measurements into letters |
| Illumina | Company making SBS sequencers |
| Redundancy | Extra copies or information that support recovery |
| Sequencing depth | Number of reads covering a sequence |
| Dropout | A fragment completely missing from the recovered data |
| Decoding | Translating DNA back into digital data |

---

## 16. The whole idea in one example

You want to store a photograph in DNA. You convert it to binary and encode it into 10,000 short DNA
sequences. A lab synthesizes them. Over time some molecules degrade. During retrieval, PCR copies some
fragments better than others. A Nanopore machine misjudges some repeated-base runs; an Illumina workflow
under-represents some GC-rich fragments. Your decoder receives an incomplete, imperfect set of sequences,
and error-correcting algorithms recover the missing or damaged pieces to rebuild the photo.

The real question: **how much redundancy should you add up front so recovery works, without wasting
DNA?** Biology decides how the medium behaves; computer science decides how efficiently you can store and
recover information in it.

---

## 17. How this maps to Lazarus

| Biology concept | Where it lives in Lazarus / bundled codec |
|---|---|
| 2 bits per base, strands, oligos | the bundled codec encoder: 110-base strands, 16-base seed + payload (`dna_codec/encoder.py`) |
| Homopolymer limit | `EncoderSettings.max_homopolymer` (default 3); the encoder rejects candidate strands that break it |
| GC content range | `EncoderSettings.gc_min` / `gc_max` (default 40–60%) |
| Substitutions, insertions, deletions | the bundled codec channel simulator, rates per technology (`profiles/nanopore_budget.json`, `illumina_standard.json`) |
| Homopolymer errors in nanopore | `homopolymer_run_factors` in the nanopore profile |
| Dropout and degradation | `dropout_rate` + `decay_per_year × storage_years` in the profile; Lazarus sets years from the retention policy |
| Sequencing depth | "coverage" / planned reads per strand, a design knob the agent tunes |
| Logical redundancy + ECC | Fountain code (`redundancy`), CRC-16 per strand, CRC-32 per pool |
| Physical redundancy | Spreading strands across vault sites; every vault holds a full copy of the manifest |
| Basecalling / decoding noisy reads | Majority-vote decoder and the bundled codec’s CNN polisher trained on real Nanopore reads |
| "How much redundancy?" | The codec-engineer and adversary agents measure it per archive |

Full walk-through of the software pipeline: [HOW_IT_WORKS.md](HOW_IT_WORKS.md).

Lazarus simulates synthesis, storage and sequencing. It produces real DNA sequences and vendor-ready order
files, but no physical DNA is made.
