# Resume here — business DNA simulator integration

Handoff: November 14, 2026. Branch: GB. User paused to continue on another device because credits are low.

## Goal and decisions

Implement Erbgut's real learned encoding for company files uploaded through Lazarus UI. Compare standard versus learned designs, approve a tested candidate, store exact DNA sequences in private Supabase, simulate sequencing, recover and verify original file hashes. No physical lab: label synthesis, aging, sequencing and costs as simulated/modeled.

Two modes were approved: default to an evaluated compatible learned model; offer fresh learning in a background experiment. If no compatible model exists, explicitly offer fresh learning or standard encoding. Keep the 200 KB upload limit. Preserve approvals for archive creation and destructive disaster drills.

The LangChain prize brief is only “Best use of deepagents — by LangChain: Teams build a deepagent for any use case they want.” Do not invent judging criteria. User has 1–3 days. Demonstrate actual agent delegation, measured experiments, adversarial failures and revisions, approval and verified recovery. Attribute Erbgut's research to its authors; its published improvements are not Lazarus results.

## What exists

- React UI, FastAPI backend, working Supabase archive persistence, crypto, simulated vaults, recovery and certificates.
- oxView integration committed on visual-dna (34e13a2), inherited by this branch. Uses real saved FASTA. Frontend previously passed 16 tests and actual browser checks.
- New learning.py runs upstream run_loop in a separate process. codec-researcher specialist and run_learning_experiment tool are wired into the agent. Reports/logs/checkpoints are published as artifacts. Quick/full process budgets are 600/7200 seconds.
- Learning currently uses Erbgut's fixed research file, NOT uploaded customer bytes. It does NOT deploy its scorer into actual archive orders.
- Upstream can train risk selection; its CNN polisher stays fixed. Only upstream's transformer supports decoder adaptation. Do not claim CNN retraining.
- candidates.py creates content-addressed frozen strand sets from encrypted customer pools, records model provenance, verifies content/input identity and has a stress validation function. It is NOT connected to API, UI, approval or order creation yet.
- dna.py now round-trips every EncoderSettings field instead of dropping seed/risk settings.
- persistence.valid_path allows learning/candidates/candidate-evidence artifacts.
- Most recent backend suite: 44 tests passed using `lazarus/.venv/bin/python -m pytest lazarus/tests -q`. Candidate tests prove scorer invocation and byte recovery; they do not prove a trained model improves outcomes. Candidate stress validation has not had end-to-end verification.

## Next implementation steps

1. Review these unfinished changes before extending them. Create real model registry/provenance and compatibility checks. Never load arbitrary user-supplied pickle models. Keep standard encoding explicitly available when no evaluated model exists.
2. Connect learning output to candidate creation for uploaded encrypted pools. Keep train-based selection separate from held-out final validation; do not choose or repeatedly tune candidates using held-out outcomes. Compare standard and learned under matched conditions. Fresh learning must support progress, cancellation and restart interruption reporting.
3. Bind experiments, exact sequence checksums, costs and approval to an immutable candidate ID. Current tools.place_synthesis_order still constructs standard settings and calls dna.encode_bytes without a learned scorer. Replace that path for candidate orders with frozen, validated sequences; retain legacy archive compatibility. Update proposal/approval guards and preserve decoding settings in the DNA manifest.
4. Add upload mode selection, candidate comparison, progress/cancel controls and a clear decision history to the business UI. Existing activity stream can carry agent evidence. Do not show research-file results as customer archive validation.
5. Validate exact candidate -> approved order -> Supabase FASTA -> oxView -> recovery identity. Recover with local staging/working artifacts unavailable. Test missing/corrupt models, checksum failures, stale approval, vault loss, failed recovery and cancellation.
6. Run a real complete training experiment, Supabase round trip and LLM-driven agent run. Demonstrate actual delegation and a measured revision. Existing 44 tests do not establish those outcomes.
7. Label certificates simulation recoverability reports rather than regulatory certification. Produce reproducible evidence and clearly label recorded demonstrations.

## Environment and branch notes

- This branch starts from visual-dna, NOT latest main. Last observed origin/main c2f7178 includes Gemini integration and dark theme, absent here. Earlier dry merge was conflict-free; 16 frontend tests/build passed. Recheck latest main and integrate deliberately; avoid losing newer Gemini changes. DNA panel still has light-theme colors.
- `.env.example` Gemini placeholder is included. Real `.env` secrets are excluded. On the new device configure credentials securely; do not expect this branch to carry them.
- Supabase project reference: feiddjfuuqfvvsiionds. Existing verified sample archive: 20261114-004141-19a4a2. Do not destroy existing user archives while testing.
- Erbgut dependency is ignored under vendor/hackmit2026-main; follow README setup on the new device. The separate /Users/gravitbali/hackmit2026 checkout matched all 23 engine files, five profiles and the decoder checkpoint. Do not depend on that absolute path.
- A manually started learning experiment wrote to ignored scratch/learning-check on the old device. Its completion was not verified and its artifacts are not in Git. Do not claim it passed or rely on it.
- `uv` was unavailable on the old shell; the existing virtualenv worked. Browser connector bootstrap failed there; actual UI checks used Playwright and system Chrome. See scripts/verify_visual_dna.mjs.

Read docs/DEEPAGENTS_DEMO.md for the demo narrative and docs/VISUAL_DNA.md for viewer verification.
