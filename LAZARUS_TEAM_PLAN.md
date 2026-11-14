# LAZARUS — The AI DNA Archivist for Regulated Enterprises

**Hackathon tracks:** Business & Enterprise (main) + Best use of deepagents by LangChain (special)
**Built on:** Erbgut (HackMIT 2026), https://github.com/timarnoldev/hackmit2026 and
https://plume.hackmit.org/project/mwrat-butaa-qmvaa-aebuw, used unmodified in `vendor/hackmit2026-main`.

---

## 1. The idea in one paragraph

Lazarus is an AI agent that does the job of a company's DNA-archive engineer. A company hands it files
it must keep for decades, plus a retention policy. Lazarus plans the archive, runs real Erbgut DNA codec
experiments to choose the cheapest encoding that still recovers the file, attacks its own design to find
weaknesses, asks a human to approve the cost, produces a vendor-ready DNA synthesis order plus a
self-describing manifest, and later runs a verified "Year 2076" recovery drill using Erbgut's trained
neural-network decoder. The product it sells is a **Recoverability Certificate**: evidence for a
compliance officer that the archive can actually be read back.

## 2. Why this is a real business (the honest pitch)

- DNA storage is **not** cheaper than cloud or tape for everyday data. Do not claim it is.
- Where it makes sense: data that must survive **decades**, never changes and is rarely read.
  Examples: pharma clinical-trial records (25+ years, FDA 21 CFR Part 11), bank records
  (SEC 17a-4 WORM), legal holds, film and media masters.
- DNA storage vendors are forming now (for example Atlas Data Storage, Biomemory, Catalog).
- **The gap:** a company has nobody who can
  1. decide what should go into DNA,
  2. tune the codec to the vendor's sequencing technology and the time horizon,
  3. produce a synthesis order,
  4. prove decades later that it decodes, even if the original software is gone.
- Erbgut solves (2): "given my budget, sequencing tech and storage time, which encoding and how much
  redundancy?" Lazarus wraps that into an autonomous agent that does (1) to (4) and outputs audit
  evidence.
- **Business model:** a per-archive certification fee plus an annual subscription for recurring
  recovery drills. Partner with DNA vendors as the vendor-neutral "design and verify" layer.

## 3. How it works, step by step

1. **Intake.** An admin uploads files (for example `trial_042_consent.pdf`, `ledger_2026.csv`) and fills
   in a policy: retention years (e.g. 50), expected read technology (nanopore or illumina), budget,
   recovery target (e.g. 100% of trials) and number of physical vault sites (e.g. 3).
2. **Plan.** The supervisor agent writes a todo plan and classifies files. Cold, immutable files go to
   the DNA tier. Anything else gets the recommendation "keep this on Glacier or tape" (honest tiering).
3. **Prepare.** For each file: compress with zstd, encrypt with AES-256-GCM (the customer holds the key,
   it never goes into DNA), record the SHA-256 of the original, and split into pools of at most about
   16 KB (Erbgut was tested on 20 KB files, and small pools keep encoding fast).
4. **Codec design** (Codec Engineer subagent). Build a custom Erbgut `SituationProfile` from the policy
   (`storage_years` = retention, `decay_per_year` from tech and horizon). Grid-search `EncoderSettings`
   (redundancy 0.1 to 0.6, strand length 110 or 150, homopolymer and GC rules on or off) using Erbgut's
   `recovery_trials` on train seeds. Score cost with Erbgut's cost model (bits per base, $/MB write,
   $/MB read). Pick the cheapest setting that meets the recovery target.
5. **Red team** (Adversary subagent). Re-test the chosen setting under conditions it was **not** tuned
   on: Erbgut's Simulator B (a structurally different channel), double decay, lower read coverage, and
   loss of a whole vault. If it fails, it reports back and the supervisor revises the design (more
   redundancy, or spreading strands across vaults so any K of N vaults are enough). This repeats until
   it passes. This fail, revise and retest loop is the visible "the agent is thinking" moment in the demo.
6. **Human approval.** A deepagents `interrupt_on` pauses before `place_synthesis_order`. The UI shows
   number of bases, write cost, read cost, recovery rate and red-team results. The human can approve,
   edit or reject.
7. **Emit.** Write a vendor-ready `order.fasta` and `order.csv` per vault (a mock vendor API, since real
   vendors accept FASTA or CSV oligo pools). Also write the **bootstrap manifest**: settings, file
   metadata and hashes as JSON, itself DNA-encoded with one fixed, published, conservative setting
   (redundancy 1.0). This fixes the "forgotten decoder" problem: in 2076 you only need a one-page
   bootstrap spec to read the manifest strands, and the manifest tells you how to read everything else.
8. **Recovery drill** (Recovery subagent). "Year 2076, every server is gone." Delete local originals
   and metadata. Keep only the vault strand files and the bootstrap spec. Simulate sequencing, decode the
   manifest first, then decode the data with Erbgut's CNN `PolishDecoder` side by side with the
   `MajorityVoteDecoder` baseline. Run `recover`, decrypt, decompress, check SHA-256. If it fails, try
   more reads or another vault. Never claim success without a hash match.
9. **Certificate** (Compliance subagent). An HTML or PDF report: chosen setting, recovery rate over N
   trials under each stress test, hashes, decoder used, cost, and chain of custody (every tool call
   logged with a timestamp). Scheduled re-runs give a "continuous recoverability audit".

## 4. Why it fits each track

- **Business & Enterprise:** a real buyer (compliance or records officer), real regulations, concrete
  outputs (certificate and vendor order), cost optimisation, risk reduction, recurring SaaS revenue.
- **Best use of deepagents:** every deepagents feature is used for a real reason:
  - planning (`write_todos`)
  - subagents with isolated context (codec, adversary, recovery, compliance)
  - the virtual filesystem for experiment logs and the plan
  - tool calls into real computation
  - a human-in-the-loop interrupt before spending money
  - a fail, revise and retest loop driven by measured numbers rather than LLM guesses
- **Deep learning:** Erbgut's 1D-CNN polisher (`checkpoints/polish/polish.pt`, trained on real
  Microsoft Nanopore reads) runs in the recovery path. Erbgut's docs report 82.3% exact strands for the
  polisher against 67.2% for the baseline at 6 reads on held-out real data. Optionally, Erbgut's risk
  model (`KmerRiskModel`, quick to fit) can score candidate strands in the encoder.
- **Rule:** the LLM never writes DNA letters itself. It only calls tools.

## 5. Architecture and repo layout

```
DNA encoder/                       repo root (git)
  vendor/hackmit2026-main/         Erbgut, UNMODIFIED (dependency)
  lazarus/                         Python backend
    pyproject.toml                 uv; path dependency on ../vendor/hackmit2026-main (extra: train)
                                   + deepagents, langchain-anthropic, fastapi, uvicorn,
                                     sse-starlette, cryptography, zstandard
    lazarus/dna.py                 thin wrapper over dnacodec (the ONLY file that imports dnacodec)
    lazarus/crypto.py              zstd + AES-GCM + sha256 + pool splitting
    lazarus/vaults.py              vault folders, strand placement across N vaults, destroy_vault()
    lazarus/manifest.py            bootstrap manifest encode/decode (fixed BOOTSTRAP_SETTINGS)
    lazarus/tools.py               agent tools (section 7)
    lazarus/agent.py               create_deep_agent: supervisor + 4 subagents + interrupt_on
    lazarus/api.py                 FastAPI + SSE
    lazarus/report.py              certificate HTML
    tests/
    stubs/                         fake tool outputs so Lane B can work before Lane A lands
  web/                             Next.js + Tailwind + Recharts
    mock/events.jsonl              recorded SSE stream so Lane C can work offline
  sample_data/northstar_bio/       fictional company files (few KB to 50 KB each)
  docs/                            pitch, Devpost text, attribution
```

LLM: Claude through `langchain-anthropic`, model `claude-sonnet-5-5`, key in env `ANTHROPIC_API_KEY`
(never commit keys; use `.env` and add it to `.gitignore`).

### Erbgut functions to reuse (do not rewrite them)

| Need | Erbgut function | File |
|---|---|---|
| bytes to strands | `encode(data, EncoderSettings, scorer=None)` | `dnacodec/encoder.py:245` |
| strands to bytes, or None | `recover(strands, meta)` | `dnacodec/encoder.py:414` |
| settings and metadata types | `EncoderSettings`, `FileMeta`, `EncodedFile` | `dnacodec/types.py` |
| channel profile | `load_profile`, `SituationProfile` | `dnacodec/profiles.py:94` |
| sequencing noise | `simulate(strands, profile, seed)` | `dnacodec/simulator.py:228` |
| red-team channel | `simulate` | `dnacodec/simulator_b.py:212` |
| baseline decoder | `MajorityVoteDecoder()` | `dnacodec/baseline.py:146` |
| CNN decoder | `PolishDecoder(checkpoint_path, device, workers)` | `dnacodec/model/polish.py:731` |
| N-trial recovery rate | `recovery_trials`, `min_reads_at_target` | `dnacodec/evaluate.py:125,183` |
| cost and density | `_density_and_costs`, `payload_bits_per_base` | `dnacodec/evaluate.py:251` |
| train-only seeds | `train_seed()` | `dnacodec/seeds.py` |
| risk scorer (optional) | `KmerRiskModel.fit`, `load_risk_model` | `dnacodec/risk.py:688,744` |

Built-in profiles: `nanopore_budget`, `illumina_standard`, `illumina_archive_100y`
(in `vendor/hackmit2026-main/profiles/`).

## 6. Team split: who does what

### Lane 0: Spike and contracts (ONE person, first ~2 hours, everyone else sets up)
- `git init`, push to GitHub, add `.gitignore` (`.env`, `.venv`, `node_modules`, `vaults/`, `jobs/`).
- In `lazarus/dna.py`: round-trip a 16 KB file: encode, simulate (`nanopore_budget`), PolishDecoder,
  recover, sha256. **Time each step on CPU** and record the numbers in `docs/TIMINGS.md`.
- If the CNN is too slow on CPU: use fewer trials, use `workers`, or use the baseline decoder for grid
  search and the CNN only for the final drill.
- Freeze the tool schemas (section 7) and SSE events (section 8). Commit them as `lazarus/contracts.py`
  and `web/mock/events.jsonl`. **After this, contracts change only with agreement from the whole team.**

### Lane A: DNA core (backend person, fastest laptop, ideally with an NVIDIA GPU)
- `dna.py`, `crypto.py`, `vaults.py`, `manifest.py`, `tests/`.
- Depends only on Erbgut.
- Done when: pool round-trip passes with both decoders; manifest decodes with no external metadata;
  recovery works with K of N vaults; a tampered strand makes `recover` return None (never wrong bytes).

### Lane B: Agent and API (AI person)
- `tools.py`, `agent.py`, `api.py`, `report.py`.
- Codes against `stubs/` until Lane A lands, then swaps stubs for the real functions.
- Done when: a headless CLI run on `sample_data/northstar_bio` produces the plan, experiments, red-team
  revision, interrupt, order files, drill and certificate, and streams events matching section 8.

### Lane C: Web UI (frontend person)
- Next.js pages: intake form, live agent timeline, experiment chart (redundancy vs recovery rate and
  cost), red-team panel, approval modal, vault map with "destroy" buttons, drill view (baseline vs CNN
  side by side), certificate view.
- Builds against `web/mock/events.jsonl` replayed as SSE until Lane B's API is ready.

### Lane D: Story (optional 4th person)
- Northstar Bio sample data, pitch deck, Devpost write-up, 3-minute demo script.
- Email the Erbgut authors for permission (see section 10), write the attribution section.

### Timeline
| Phase | What |
|---|---|
| 0 to 2 h | Lane 0 spike and contracts; others install tools and read the Erbgut README |
| 2 h to ~50% | Lanes A, B, C, D in parallel on separate branches |
| ~50% | Integration: B uses real A, C points at real B |
| last 25% | Demo rehearsals end to end, bug fixes, pitch |

### Rules for working together
- One branch per lane (`lane-a-dna`, `lane-b-agent`, `lane-c-web`, `lane-d-story`). Merge to `main`
  through small PRs.
- Stay inside your lane's files. Contracts change only with team agreement.
- **Never edit `vendor/hackmit2026-main`.**
- If you use an AI coding agent, give it this file and say: "You own Lane X. Don't touch other lanes'
  files. Follow sections 7 and 8 exactly."

### Setup on every machine
```bash
# needs: git, Python 3.11+, uv, Node 20+
git clone <our repo>
cd lazarus && uv sync          # pulls Erbgut as a path dependency, plus torch
cd ../web && npm install
cp .env.example .env           # put ANTHROPIC_API_KEY here, never commit it
cd ../vendor/hackmit2026-main && uv run pytest -q   # Erbgut's own tests should pass
```

## 7. Contract: agent tools

All tools return JSON and every call is logged to the job's event stream.

| Tool | Input | Output |
|---|---|---|
| `inventory_files` | `job_id` | `[{name, bytes, mime, sha256}]` |
| `prepare_archive` | `job_id, file_names[]` | `[{pool_id, file, bytes_compressed, bytes_encrypted}]` |
| `build_profile` | `tech: "nanopore"\|"illumina", years: float, coverage: float` | `{profile}` (SituationProfile dict) |
| `run_codec_experiment` | `pool_id, settings{redundancy, strand_length, max_homopolymer, gc_min, gc_max}, profile, trials:int, decoder:"baseline"\|"polish"` | `{recovery_rate, n_trials, bits_per_base, write_usd_per_mb, read_usd_per_mb, n_strands, seconds}` |
| `stress_test` | `pool_id, settings, scenario: "simulator_b"\|"decay_x2"\|"low_coverage"\|"vault_loss", trials` | same as above + `{scenario, passed}` |
| `estimate_cost` | `settings, total_bytes, profile` | `{bases, write_usd, read_usd}` |
| `place_synthesis_order` **(needs human approval)** | `job_id, settings, n_vaults, k_required` | `{order_files[], manifest_strands, total_bases}` |
| `destroy_primary` **(needs human approval)** | `job_id` | `{deleted[]}` |
| `recover_archive` | `job_id, vaults_available[], decoder, reads_per_strand` | `{files:[{name, recovered, sha256_match}], seconds, decoder}` |
| `write_certificate` | `job_id` | `{path}` |

## 8. Contract: SSE events (backend to UI)

`GET /jobs/{id}/events`. Each event is JSON: `{"type": ..., "ts": ISO8601, "agent": "supervisor"|"codec-engineer"|"adversary"|"recovery-engineer"|"compliance", "data": {...}}`

| type | data |
|---|---|
| `plan` | `{todos:[{text, status}]}` |
| `tool_call` | `{tool, args}` |
| `tool_result` | `{tool, result}` |
| `experiment_result` | output of `run_codec_experiment` + `settings` |
| `stress_result` | output of `stress_test` |
| `interrupt` | `{tool, args, summary:{bases, write_usd, read_usd, recovery_rate}}` |
| `vault_event` | `{vault_id, status: "healthy"\|"destroyed"\|"reading"}` |
| `drill_result` | output of `recover_archive` |
| `message` | `{text}` (agent narration) |
| `done` | `{certificate_path}` |

REST endpoints: `POST /jobs` (multipart files + policy JSON), `POST /jobs/{id}/approve`
(`{decision: "approve"|"edit"|"reject", args?}`), `POST /jobs/{id}/drill`, `GET /jobs/{id}/files/{name}`.

## 9. The 3-minute demo

1. Upload Northstar Bio files. Set 50 years, nanopore, budget.
2. The agent plans live and the experiment chart fills up.
3. The adversary breaks the first design under Simulator B or vault loss.
4. The agent raises redundancy and spreads strands across vaults; the retest passes.
5. Approval modal with costs. Click approve; `order.fasta` and the DNA manifest are produced.
6. Click "2076: destroy everything".
7. Recovery from 2 of 3 vaults, CNN vs baseline side by side.
8. The PDF opens, SHA-256 matches, the certificate appears.

Show measured rates only, and never pick a lucky seed. This is Erbgut's own honesty rule
(see the `dnacodec/demo.py` docstring).

## 10. Risks and must-dos

- **License:** the Erbgut repo has **no LICENSE file** (checked). By default that means all rights
  reserved. Before submitting: ask the authors (GitHub `timarnoldev`) for permission, credit them on
  Devpost and the README, keep Erbgut unmodified under `vendor/` as a dependency, and state clearly what
  Lazarus adds. Check HackPrinceton's rules on pre-existing code.
- **Speed:** Erbgut runs 300 trials on a GPU machine. We use 20 to 50 trials on train seeds, run them in
  background threads and cache results per (pool, settings).
- Never claim physical DNA synthesis. Label everything "simulated channel, calibrated on real reads".
- Costs in Erbgut profiles are placeholders (`profiles.py:38` says so). Show them as "modeled" and let
  the user edit them.
- The encryption key never goes into the DNA manifest. The manifest stores a key ID only.

## 11. How we know it works

- Erbgut's own tests still pass: `cd vendor/hackmit2026-main && uv run pytest -q`.
- `lazarus/tests` pass: pool round-trip with both decoders, manifest bootstrap with no external
  metadata, K-of-N vault recovery, tampered strand returns None, encrypt/decrypt hash match.
- A headless agent run on sample data produces the order, manifest strands and certificate, the
  interrupt fires before the order, and after `destroy_primary` the drill restores byte-identical files.
- Run the full demo in the UI twice, end to end, before judging.
