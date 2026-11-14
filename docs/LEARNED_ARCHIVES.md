# Learned customer archives

The business interface supports three explicit choices:

- **Evaluated model** reuses a server-generated model only when the complete sequencing profile, strand length, frozen decoder checkpoint and codec source hashes match.
- **Fresh learning** trains the bundled codec’s risk CNN in an isolated worker: 512 controlled synthetic training sequences, eight labeling repetitions, up to 12 epochs, and a separate 128-sequence ranking evaluation. This is exploratory model evaluation, not evidence of improved archival recovery. The existing CNN decoder is never retrained.
- **Standard rules** does not train or load a risk model. The original broader analysis remains available to API clients that omit `encoding_mode`; saved legacy archives retain their recovery path.

No model-upload endpoint exists. Registry entries refer to server-generated, SHA-256-addressed checkpoints. Loading uses `torch.load(weights_only=True)`, never the upstream unrestricted pickle fallback. Models, metadata, evidence and frozen candidate files follow the configured artifact backend. Missing or incompatible models require an explicit new choice, rather than a silent fallback.

## From file to candidate

Files are compressed and encrypted first. Each candidate contains those exact ciphertext pools, actual emitted DNA, every encoder setting, file and placement metadata, policy, decoder checksum and model provenance. Its ID is the SHA-256 of canonical contents. Loading rechecks identity against the current job.

The codec engineer tests matched standard/learned pairs on training seeds. Rules, ciphertext, reader, coverage and redundancy are matched within each pair. The bounded search revises through 0.8, 1.2, 1.6 and 2.0 extra recovery data, stopping on the first passing pair or budget exhaustion. Ties favor the requested learned model without claiming a benefit. Costs count actual data strands and every site's bootstrap instructions, using modeled placeholder prices. Gemini API charges are separate and unestimated.

Only after selection does the adversary perform final held-out normal, alternate-reader, lower-coverage, double-aging and location-loss trials. These include bootstrap recovery. Three trials per point are exploratory. Final results are persisted and never re-rolled. An interrupted final check cannot be resumed as a fresh independent test. Failure blocks approval and ends analysis; changing a design requires a revised archive.

Approval compares the exact candidate, file metadata, policy, decoder, immutable evidence artifact and modeled budget. Candidate orders copy frozen data strands verbatim; they do not re-encode customer data. The self-describing DNA manifest preserves all decoder/encoder metadata. A future recovery needs surviving vault FASTA, the bootstrap specification and separate encryption keys; the learned scorer and working ciphertext are unnecessary.

Fresh learning reports real stages and can be canceled. Cancellation terminates and reaps its worker. Server restarts mark persisted running experiments interrupted; workers also stop when their parent server dies. Restart/cancel/failure screens offer a revised archive using fresh learning or standard encoding.

## Reproduce

Backend tests:

```sh
cd lazarus
.venv/bin/python -m pytest tests -q
```

Real computation on a bundled public sample (creates a new job; deletes only that job's working copies after writing a passing DNA archive):

```sh
cd lazarus
.venv/bin/python ../scripts/verify_learned_archive.py --encoding fresh --sample picture_demo.png
```

Use `--encoding evaluated` to reuse a compatible local model, or `--encoding standard` for no learning. Results vary with encryption and simulations. Failure is an acceptance result, not a reason to repeat final seeds until success. The script is explicitly scripted and makes no LLM calls.

For a live agent run, upload a bundled image through the app, select the matching reader/aging/coverage settings, choose fresh/evaluated learning, and select Gemini agent analysis. The activity stream records actual delegation to researcher, codec engineer, adversary, recovery engineer and compliance. Review the tested candidate before approving; confirm the separate removal-of-working-copies step, then inspect recovered bytes and report.

## Verification boundaries

Automated Supabase tests use the real HTTP adapter against a private-storage protocol double. They validate frozen learned FASTA identity, remote persistence and key handling, then recover on an empty computer after one vault is lost, without loading the risk model. This is not a live hosted Supabase verification. The current machine has no Supabase credentials configured.

All physical synthesis, aging and sequencing remain simulated. Reports are simulation recovery reports, not compliance certification. Codec, simulator, risk learner and frozen CNN decoder are the bundled codec research components; their published improvements are not Lazarus results.
