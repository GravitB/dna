# Lazarus: pitch and demo script

## One-liner
Lazarus is an AI DNA archivist. It designs, attacks, orders and *proves* DNA archives for records that
must outlive every server a company owns.

## 30-second pitch
Pharma companies must keep trial records for 25 years or more. Banks and law firms have similar rules.
DNA can hold that data for centuries in a test tube, but it is a noisy medium, and nobody inside the
company knows how to design a DNA archive or prove it can be read back. Lazarus is a LangChain deep
agent that does that job end to end: it designs the codec with real experiments, red-teams the design,
asks a human before spending money, writes the synthesis orders, then deletes the originals and rebuilds
them from DNA alone. The output is a certificate an auditor can check.

## 3-minute live demo
1. **Intake (15 s).** Northstar Bio, 50-year retention, Nanopore, 3 vault sites, sample files included.
   Start the deep agent.
2. **Planning (15 s).** Point at the live todo list. The supervisor keeps `weekly_standup_notes.txt` out
   of DNA because it is a working file, not a record.
3. **Design (30 s).** The codec-engineer subagent's experiment chart fills in. Low redundancy fails;
   the agent finds the cheapest design that recovers the file in every trial.
4. **Red team (30 s).** The adversary destroys one vault site in simulation and the design breaks
   (red "broke" rows). The supervisor redesigns and retests until it survives. This is the moment that
   shows it is an agent, not a script.
5. **Approval (15 s).** The modal shows bases, modeled cost and the adversary results. Approve.
   Open `order.fasta`: these are the vendor-ready strands.
6. **Disaster (30 s).** Approve "destroy primary data". The recovery engineer decodes the manifest from
   DNA using only the one-page bootstrap spec, then every pool. Point at the baseline vs CNN columns.
7. **Proof (15 s).** All files show SHA-256 "match". Open the restored PDF. Then press **destroy** on
   Site 2 and **Re-run recovery drill**: it still rebuilds from 2 of 3 sites.
8. **Certificate (15 s).** Open the certificate, which includes the chain of custody of every agent action.

Backup: if the Wi-Fi or the API fails, run the same flow in Autopilot mode. It uses the same tools
with no LLM and is labeled as scripted.

## Judge Q&A
- *Is the DNA real?* Synthesis and sequencing are simulated with Erbgut's channel model, which is
  calibrated on real Nanopore reads. The orders are real FASTA that a vendor accepts.
- *Is DNA cheaper than S3?* No. Lazarus only uses DNA for cold, immutable, decades-long records, and
  says so.
- *Where is the deep learning?* Erbgut's CNN decoder, trained on real reads, runs in every drill next
  to the classic decoder.
- *What is yours vs Erbgut's?* Erbgut provides the codec, the simulators and the decoders, used
  unchanged. Lazarus is the agent, the workflow, red teaming, encryption, vault placement, the bootstrap
  manifest, the drill, the certificate and the app.
- *Why a deep agent?* Planning, isolated subagents, a virtual filesystem, human approval before spending
  money or deleting data, and a fail → redesign → retest loop driven by measured numbers.

## Devpost summary
**Inspiration:** Regulated records must survive decades. DNA can, but nobody can operate it.
**What it does:** A deep agent that designs, red-teams, orders and verifies DNA archives, then proves
recovery after deleting the originals.
**How we built it:** LangChain deepagents with Claude, four subagents, human-in-the-loop interrupts,
FastAPI with server-sent events, and React with Recharts. The DNA codec, simulators and CNN decoder
come from Erbgut (HackMIT 2026), credited and unmodified.
**Challenges:** Small Fountain-coded pools are fragile. Packing every file into one balanced stream and
attacking the whole archive (not just one pool) fixed recovery after losing a vault site.
**What's next:** Real vendor APIs, wet-lab validation, and scheduled drills as a subscription.
