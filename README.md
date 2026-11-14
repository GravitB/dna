# Lazarus: an AI DNA archivist for regulated enterprises

**HackPrinceton tracks:** Business & Enterprise (main) and Best use of deepagents by LangChain (special).

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

Requirements: Python 3.11–3.13, [uv](https://docs.astral.sh/uv/), Node 20+, git.

```bash
git clone https://github.com/GravitB/dna.git && cd dna
cp .env.example .env            # add ANTHROPIC_API_KEY for the deep agent
scripts/run.sh                  # fetches Erbgut, installs, builds the UI, serves on :8000
```
Open http://localhost:8000, keep "Include Northstar Bio sample files" ticked, and press **Start archive**.

- **Deep agent mode** needs `ANTHROPIC_API_KEY`. The model defaults to `claude-sonnet-5-5`; override it
  with `LAZARUS_MODEL=anthropic:<model>`.
- **Autopilot mode** runs the same tools with a fixed recipe and no LLM. It is clearly labeled in the UI
  and exists so the pipeline can be tested and demoed offline.

Development (two terminals):
```bash
cd lazarus && uv run uvicorn lazarus.api:app --reload --port 8000
cd web && npm run dev           # http://localhost:5173, proxies /api to :8000
```

Tests:
```bash
cd lazarus && uv run pytest -q
```
The tests cover encryption and tamper detection, decoding the manifest with only the bootstrap spec,
corrupted strands never producing wrong bytes, recovery from 2 of 3 vaults, and the full deep agent
graph with human approval, driven by a scripted fake model so no API key is needed.

## Repository layout
```
lazarus/lazarus/dna.py        thin wrapper over Erbgut (the only module that imports it)
lazarus/lazarus/crypto.py     zstd + AES-256-GCM + SHA-256
lazarus/lazarus/manifest.py   self-describing bootstrap manifest
lazarus/lazarus/vaults.py     per-site FASTA/CSV orders, vault destruction
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

## Credits
The DNA codec, both sequencing simulators, the baseline decoder and the CNN decoder are from
**Erbgut** by the HackMIT 2026 team (https://github.com/timarnoldev/hackmit2026,
https://plume.hackmit.org/project/mwrat-butaa-qmvaa-aebuw). Lazarus uses them unmodified as a
dependency and does not redistribute them: `scripts/get_erbgut.sh` downloads Erbgut at a pinned commit.
Erbgut's repository has no license file, so we are asking its authors for permission.

What Lazarus adds: the enterprise workflow, the deepagents supervisor and subagents, archive-level red
teaming with redesign, encryption and multi-site vault placement, the DNA-encoded bootstrap manifest,
the disaster drill with SHA-256 verification, the certificate and chain of custody, and the web app.
