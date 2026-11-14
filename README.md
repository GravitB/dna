# Lazarus: an AI DNA archivist for regulated enterprises

**HackPrinceton tracks:** Business & Enterprise (main) and Best use of deepagents by LangChain (special).

New to DNA storage? Start with [the biology, explained from zero](docs/BIOLOGY.md), then
[how Lazarus works end to end](docs/HOW_IT_WORKS.md).

Some records have to survive for decades: clinical-trial files (FDA 21 CFR Part 11), bank records
(SEC 17a-4), legal holds and media masters. DNA is the densest and longest-lasting storage medium
there is. It is also very noisy, and nobody at a normal company knows how to design a DNA archive or
prove that it can be read back.

Lazarus is a LangChain **deep agent** that does that job. It takes your files and retention policy,
runs real DNA codec experiments, attacks its own design until it holds, asks you to approve the cost,
writes vendor-ready DNA synthesis orders across several vault sites, then deletes the originals and
proves it can rebuild them from DNA alone. The result is a **Recoverability Certificate** with a full
chain of custody.

Built on [Erbgut](https://github.com/timarnoldev/hackmit2026) (HackMIT 2026). Erbgut provides the
DNA Fountain encoder, the sequencing simulators calibrated on real Nanopore reads, and the CNN decoder
that we use unchanged. See [Credits](#credits).

Approved archives include an interactive [DNA viewer](docs/VISUAL_DNA.md), powered by locally hosted
oxView. Explore the archive's saved DNA sequences in 3D or animate a strand being built.

---

## How it works

```
 files + policy
      │
      ▼
 SUPERVISOR (deep agent, write_todos plan)
  ├─ inventory_files ─ decides the DNA tier (cold, immutable files only)
  ├─ prepare_archive ─ zstd + AES-256-GCM (key stays in customer KMS), one stream, balanced pools
  ├─ task → CODEC ENGINEER ─ run_codec_sweep / run_codec_experiment / estimate_cost
  │                           real Erbgut encode → simulated sequencing → decode → recover
  ├─ task → ADVERSARY ─ stress_test: lose a vault site, a different sequencer (Erbgut Simulator B),
  │                     twice the storage time, 60% of the reads.  Fail → supervisor redesigns
  ├─ place_synthesis_order ◀── HUMAN APPROVAL (deepagents interrupt_on)
  │     order.fasta / order.csv per vault + DNA-encoded bootstrap manifest in every vault
  ├─ destroy_primary ◀── HUMAN APPROVAL      (originals and staging copies deleted)
  ├─ task → RECOVERY ENGINEER ─ recover_archive: read surviving vaults, decode the manifest with the
  │                             one-page bootstrap spec, decode every pool with the baseline AND the
  │                             CNN, decrypt, check SHA-256, retry deeper on failure
  └─ task → COMPLIANCE ─ read_job_log → write_certificate
```

The LLM never writes DNA letters and never invents numbers. Every recovery rate, cost and verdict comes
from a tool that runs the Erbgut codec.

### What makes it a deep agent (and not a chatbot)
| deepagents feature | How Lazarus uses it |
|---|---|
| Planning (`write_todos`) | The supervisor plans the archive job; the UI shows the live todo list |
| Subagents with their own context | codec-engineer, adversary, recovery-engineer, compliance, each with its own tools and prompt |
| Virtual filesystem | The supervisor records the design decision and evidence in `/design_notes.md` |
| Human in the loop (`interrupt_on`) | Spending money (synthesis order) and destroying data (drill) both pause for a human |
| Tool use on real computation | Every tool runs the actual Erbgut DNA codec |
| Fail → revise → retest loop | When the adversary breaks a design, the supervisor raises redundancy or coverage and retests |

### The deep learning part
Recovery uses Erbgut's **PolishDecoder**, a 1D CNN that corrects the majority-vote consensus. It was
trained on real Microsoft Nanopore reads (`checkpoints/polish/polish.pt`). Every drill decodes the same
reads with both decoders and shows the difference per file and per pool. In our runs the CNN recovered
pools that the baseline lost. It runs on CUDA or Apple MPS when available.

### Why it is a business
- **Buyer:** records and compliance officers at pharma, banks, law firms and media archives.
- **Deliverable:** a Recoverability Certificate (evidence for auditors) and vendor-neutral FASTA orders.
- **Revenue:** a fee per certified archive, plus a subscription for recurring recovery drills.
- **Honesty:** DNA is not cheaper than cloud for everyday data. Lazarus only puts cold, immutable,
  long-retention files in the DNA tier and keeps everything else on conventional storage.

### The "forgotten decoder" problem
In 50 years, the strands may survive while the software settings that wrote them are long gone. Every
vault therefore also holds the **manifest** (encoder settings, file offsets, hashes, vault layout),
written to DNA with one fixed, published setting. A future reader needs only the one-page
[bootstrap spec](docs/BOOTSTRAP.md) to read the manifest, and the manifest explains everything else.

---

## Run it

### Picture demo

Choose **Try a picture demo** to encode a bundled 412-byte PNG, test the real codec, and restore the same image.
The quick preset fixes 50 simulated years, three locations and 16 planned reads per strand. It measures three trials
per point, searches only redundancy 0.8, 1.2, 1.6 and 2.0, and checks normal recovery plus all four stress scenarios.
The Gemini supervisor delegates the measured design and evidence review to specialists; scripted analysis remains
available under Advanced. If no design passes within the modeled budget, the demo reports that failure.

The file preview is removed when the job's working originals are deleted. The restored preview is served only after
hash verification. DNA letter counts come from the emitted FASTA files and include manifest copies across locations.
Modelled DNA costs do not include actual Gemini API charges. API usage may consume credits on your provider account.

Ordinary uploads use the standard search and accept up to 200 KB total. Existing archives continue to work; missing
legacy measurements are shown as unavailable rather than reconstructed from guesses.

Requirements: Python 3.11–3.13, [uv](https://docs.astral.sh/uv/), Node 20+, git.

```bash
git clone https://github.com/GravitB/dna.git && cd dna
cp .env.example .env            # add GOOGLE_API_KEY or ANTHROPIC_API_KEY for the deep agent
scripts/run.sh                  # checks bundled Erbgut, installs, builds the UI, serves on :8000
```
Open http://localhost:8000 for the homepage, or http://localhost:8000/app/ for the business workspace. The **Archives** page lists your archives and their latest recovery outcomes.
Choose **Create archive** to upload your own records, or **Try sample archive** for fictional Northstar Bio files.
Review the inclusion checkboxes, enter retention and budget requirements, then select **Analyze archive**.
Technical settings and the analysis method are under **Advanced settings**.

Review the proposed cost and resilience evidence before selecting **Approve simulated archive**.
Then select **Run recovery test** to delete this job's working copies and restore the selected records from
simulated DNA. Original files elsewhere on your computer are untouched. The resulting report is simulation
evidence, not regulatory certification. Agent logs, codec charts, and synthesis files are under **Technical details**.
A rejected or interrupted archive can be revised with its requirements prefilled; upload the records again.

- **Deep agent mode** uses Gemini when `GOOGLE_API_KEY` is set and otherwise uses Anthropic when
  `ANTHROPIC_API_KEY` is set. Override the model with `LAZARUS_MODEL`, for example
  `google_genai:gemini-2.5-flash` or `anthropic:<model>`.
- **Autopilot mode** runs the same tools with a fixed recipe and no LLM. It is clearly labeled in the UI
  and exists so the pipeline can be tested and demoed offline.

Development (two terminals):
```bash
cd lazarus && uv run uvicorn lazarus.api:app --reload --port 8000
cd web && npm run dev           # http://localhost:5173/app/, proxies /api to :8000
```

Tests:
```bash
cd lazarus && uv run pytest -q
cd ../web && npm test && npm run build
```
The tests cover encryption and tamper detection, decoding the manifest with only the bootstrap spec,
corrupted strands never producing wrong bytes, recovery from 2 of 3 vaults, and the full deep agent
graph with human approval, driven by a scripted fake model so no API key is needed.
`tests/test_dna_experiment.py` covers the DNA experiment:
- clean FASTA gives a byte-exact PASS
- moderate damage gives a PASS with both decoders
- excessive damage is never reported as PASS
- missing or wrong keys give INCOMPLETE or FAIL
- independent recovery works after the archive workspace is deleted, with archive storage access
  forbidden
- the same seed gives identical reads
- PDF, PNG and text files are each verified
- simulations never modify archive artifacts

## DNA storage experiment: clean FASTA → damage → independent decode → SHA-256

After an archive design is approved, every archive page shows a seven-step experiment:

**Upload → Encode → Pre-Simulation FASTA → Simulate → Post-Simulation FASTA → Decode → Verify**

Everything here is digital. No DNA is synthesized or sequenced, and the UI labels it that way.

1. **Step 1: Original Encoded DNA (Pre-Simulation).** `exports/pre_simulation.fasta` is the approved
   vault order files (`vaults/vault-N/order.fasta`) concatenated in vault order, with ids
   `vault-N|{pool}|{index}`. It includes every manifest copy and data strand, and nothing is
   reordered. `exports/clean_dna.zip` adds every vault FASTA/CSV, `export_metadata.json` (counts, strand
   length, redundancy, nucleotides, encoder configuration), `recovery_bundle.json` and `SHA256SUMS`.
   This is the clean synthesis design (a potential manufacturing order), **not** sequencing data.
2. **Simulate.** Choose the sequencer profile (Nanopore or Illumina), coverage, storage years and seed.
   Advanced settings cover substitution/insertion/deletion rates, base dropout, simulator A or B, and
   loss of whole vaults. Each run copies the clean FASTA into its own immutable folder
   `simulations/<sim-id>/` and sends every (vault, pool) tube through Erbgut's channel simulator.
3. **Step 2: Damaged DNA (Post-Simulation).** `post_simulation_reads.fasta` contains the simulator's actual
   reads: shuffled, duplicates kept, lost strands left missing, headers `>read_000001 sample=pool-0000`.
   `sample` is the tube or primer pair that was sequenced, never the strand id. There are no quality
   scores, because the simulator does not model them. Strand identities and per-read edit alignments go
   to a separate `ground_truth.tsv` that the decoder never reads. **Compare Before vs. After**
   highlights substitutions, insertions and deletions against the source strand.
4. **DNA Decoder** (main navigation). It takes FASTA or FASTQ (qualities ignored) and has two modes.
   - **A: Existing archive.** Uses the archive's approved recovery bundle and key store, never its uploads.
     The input can be an uploaded file, a simulation run, or the clean FASTA as a control.
   - **B: Independent import.** Needs only the FASTA, an optional `recovery_bundle.json` (non-secret) and
     a passphrase-protected key file (**Export keys for independent recovery**, scrypt + AES-256-GCM).
     It works on a machine with no copy of the archive.
5. **Decode.** The pipeline runs:
   1. Parse and validate the reads, then group them by sample.
   2. Decode the bootstrap manifest from the `MANIFEST` reads.
   3. For each pool, run **reference-free read clustering** (`lazarus/clustering.py`, k-mer index plus
      edit distance). Erbgut's simulator returns clusters grouped by ground truth, so this stage is
      needed for honest decoding.
   4. Build the consensus with the majority-vote baseline **and** Erbgut's CNN PolishDecoder, reported
      separately.
   5. Fountain recovery, AES-256-GCM decryption and zstd decompression.
   6. SHA-256 check against the manifest and the bundle.
6. **Verify.** The verdict is **PASS** when every hash matches, **PARTIAL** when some match, **FAIL** when
   none match, and **INCOMPLETE** when metadata or keys are missing (the report names them).
   Similar-looking DNA never counts as recovery. Only byte-exact files can be downloaded. Each attempt
   writes `verification_report.json` and `.html`. One trial is reported as one trial, not as a
   reliability estimate.

New endpoints (all under `/api`):

| Method & path | Purpose |
|---|---|
| `GET /jobs/{id}/dna` | Clean export metadata, simulations and decodes |
| `GET /jobs/{id}/dna/sequences?offset&limit&sample` | Inspect clean sequences |
| `POST /jobs/{id}/simulations` | Start an immutable damage simulation (JSON settings) |
| `GET /jobs/{id}/simulations[/{sim}]` | Simulation status, settings and metrics |
| `GET /jobs/{id}/simulations/{sim}/compare` | Clean vs damaged reads with edit operations |
| `POST /jobs/{id}/recovery-keys` | Passphrase-protected key file (keys never sent in clear) |
| `GET /jobs/{id}/files/exports/…`, `…/simulations/{sim}/…` (`?download=1`) | Clean FASTA/ZIP/bundle, damaged FASTA, metadata, ground truth |
| `GET /decoder/capabilities` | Decoder availability and decodable archives |
| `POST /decoder/sessions` (multipart) | Import FASTA/FASTQ and run decoding (mode A or B) |
| `GET /decoder/sessions[/{sid}]` | Progress, verdict and per-file hash results |
| `GET /decoder/sessions/{sid}/files/{report.json, report.html, recovered/<n>}` | Reports and verified files |

Limitations:
- Reads must carry their pool label (`sample=` or `vault-N|pool|index`). Lazarus pools share Fountain
  seed spaces, so in a wet lab they would be separated by primers or barcodes before decoding. Reads are
  assumed to be forward-strand, because the simulator does not reverse-complement them.
- Decoder sessions are stored locally (`jobs/_decoder_sessions`). In Supabase mode, mode-A reports are also
  saved with the archive; independent (mode B) sessions stay local.
- Real sequencing data can be used once it is basecalled to FASTQ, demultiplexed per pool (sample label in
  the header) and trimmed of primers or adapters to the 110-nt payload. Reverse-complement
  normalization and primer trimming would be the next stages to add.

## Cloud storage

For private DNA storage, archive history, and recovery from another computer, see [Supabase setup](docs/SUPABASE.md). Local storage remains available until cloud setup has been verified.

## Repository layout
```
lazarus/lazarus/dna.py        thin wrapper over Erbgut (the only module that imports it)
lazarus/lazarus/crypto.py     zstd + AES-256-GCM + SHA-256
lazarus/lazarus/manifest.py   self-describing bootstrap manifest
lazarus/lazarus/vaults.py     per-site FASTA/CSV orders, vault destruction
lazarus/lazarus/fasta.py      strict FASTA/FASTQ parsing and writing
lazarus/lazarus/experiment.py clean pre-simulation export, reproducible damage simulations
lazarus/lazarus/clustering.py reference-free read clustering (no simulator labels)
lazarus/lazarus/decoder.py    standalone decoder, verdicts, verification reports, key files
lazarus/lazarus/tools.py      agent tools, event stream, custody log, certificate
lazarus/lazarus/agent.py      deepagents supervisor + 4 subagents + human-in-the-loop runner
lazarus/lazarus/autopilot.py  scripted no-LLM run of the same tools
lazarus/lazarus/api.py        FastAPI + server-sent events, serves the UI
web/                          React + Recharts dashboard
sample_data/northstar_bio/    fictional company files
docs/                         bootstrap spec, pitch and demo script
LAZARUS_TEAM_PLAN.md          original plan and team contracts
```

## Honesty notes
- DNA synthesis and sequencing are **simulated** with Erbgut's channel model. It is calibrated on real
  Nanopore reads; storage decay is extrapolated. We never claim physical DNA was made.
- Costs use Erbgut's placeholder prices and are always labeled "modeled".
- Recovery rates come from small trial counts (4–8 per point) on train seeds only (Erbgut's seed
  discipline). We do not pick lucky seeds.
- This is a local demo, not a compliance certification or production archive. Keys are stored in a
  local folder that only simulates a customer KMS. The server has no user authentication; do not
  upload sensitive files or expose it to a network.
- Vault placement spreads strands across sites; recovery from any chosen K of N sites is not guaranteed.
  The certificate describes a simulated drill, not a guarantee of future recovery.
- The bootstrap procedure still depends on the codec's implementation and its dependencies; the
  short spec alone has not been independently validated as sufficient to reimplement it.

## Credits
The DNA codec, both sequencing simulators, the baseline decoder and the CNN decoder are from
**Erbgut** by the HackMIT 2026 team (https://github.com/timarnoldev/hackmit2026,
https://plume.hackmit.org/project/mwrat-butaa-qmvaa-aebuw). Lazarus includes their source directly as `lazarus/dna_codec`, with runtime assets in `lazarus/profiles` and `lazarus/checkpoints`.
Erbgut's repository has no license file, so we are asking its authors for permission.

What Lazarus adds: the enterprise workflow, the deepagents supervisor and subagents, archive-level red
teaming with redesign, encryption and multi-site vault placement, the DNA-encoded bootstrap manifest,
the disaster drill with SHA-256 verification, the certificate and chain of custody, and the web app.

Bundled codec source: `lazarus/dna_codec`, from upstream revision `556924ab285980c5523a93871474ec773d32b7d9`. This contains the unchanged Python source, profiles and model checkpoint; hardware, datasets and the upstream dashboard are excluded. The codec is included in the Lazarus Python package, without a separate dnacodec dependency or download.

The bundled upstream `dnacodec` package is named `dna_codec` locally for integration. This naming change does not change its original authorship.
