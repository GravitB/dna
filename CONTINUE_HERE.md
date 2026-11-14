# Learned DNA integration — current handoff

Updated November 14, 2026 on `dsun-1/friendly-business-ux`, after merging the original `GB` continuation.

## Implemented

- Business file → DNA → restored-file interface, quick picture demo and actual FASTA viewer remain intact.
- Explicit evaluated-model, fresh-learning and standard-rule choices. Legacy API clients may omit `encoding_mode` for the original broader standard search; saved legacy archives still recover.
- Real the bundled codec risk-CNN training in a cancelable worker, with controlled synthetic sequences, independent ranking evaluation, progress, timeout and server-restart interruption reporting. The CNN decoder remains frozen.
- Server-generated model registry with profile, codec-source and decoder-checkpoint compatibility checks; SHA-256 identity and safe `weights_only=True` loading. No user-supplied pickle models.
- Frozen candidates encode actual encrypted uploaded files with the learned scorer. Matched standard/learned selection uses training seeds; only the selected candidate receives final held-out validation. Failed final evidence cannot be re-rolled.
- Exact candidate ID, file/placement metadata, sequence checksums, immutable evidence artifact and modeled budget gate approval. Orders use frozen strands verbatim and retain all codec settings in the self-describing DNA manifest.
- Comparison/revision history, final evidence, cancellation and next actions in the business UI. Reports explicitly describe simulation evidence and are not compliance certification.
- Learned FASTA persists through the existing artifact backend. Recovery needs vault DNA and separate keys, not the scorer, candidates or working ciphertext.

Read [docs/LEARNED_ARCHIVES.md](docs/LEARNED_ARCHIVES.md) for architecture, limits and reproduction. Run `scripts/verify_learned_archive.py` from the Lazarus virtualenv for a clearly labeled scripted real-computation check.

## Verified on this machine

- 64 backend tests; 21 frontend tests; production frontend build.
- Real fresh training: 512 controlled training sequences, 128 independent evaluation sequences, eight label repetitions, 12 completed epochs. This small model evaluation does not establish a learned encoding improvement.
- Live Gemini/deepagents notebook-image archive: `20261114-021339-c010c3`. Actual delegation to researcher, codec engineer, adversary, recovery engineer and compliance. Both standard and learned designs failed the location-loss selection test at 0.8 redundancy; both passed at 1.2. The requested learned design was selected on training evidence. This tie is not an improvement claim.
- All five final held-out scenarios passed 3/3 (exploratory). The browser displayed the matching proposal and both approval steps, followed by the recovered image and SHA-256 verification.
- Original/restored notebook: 25,144 bytes; SHA-256 `af294b42c2fed0af0c992da92566f02617bd1c766544b1a6529731a00a7d76ab`.
- Frozen candidate `bf0e9c42a5ebc8e5b834f7b6e6c05ca11ebb4822c97312d723103872c0c67cf0`; every ordered data strand matched it exactly. Actual FASTA total: 410,190 DNA letters. Modeled writing cost: $41.02; this is not an API charge or purchase.
- Working uploads/staging were absent when the restored file was checked byte-for-byte.
- Preserve the honest failed tiny-image run `20261114-021103-668c39`: it failed final held-out validation and was not ordered. Earlier debugging runs are not successful demonstrations.
- Supabase tests use the real HTTP adapter against a private-storage protocol double. A learned candidate survives an empty-machine recovery and one lost location without loading its risk model.

## Remaining external verification

Live hosted Supabase credentials are not configured on this machine; current live runs use local storage. Do not claim a hosted Supabase end-to-end run. Configure the private project using README/Supabase setup, then verify a fresh learned archive on a second empty working directory. Do not destroy existing user archives.

Models, keys, uploads, jobs and `.env` remain ignored local/private runtime data and are not pushed to Git. A teammate without the registry must choose fresh learning or standard encoding. the bundled codec remains an ignored dependency under `vendor/legacy-codec`; follow README setup instead of relying on another developer's absolute checkout path.

All synthesis, aging and sequencing are simulated. Costs are modeled placeholders. No physical synthesis, accounts/subscriptions or regulatory certification is implemented. Attribute the codec, simulators, risk learner and frozen decoder to the bundled codec; its published improvements are not Lazarus measurements.
