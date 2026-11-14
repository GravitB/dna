# Evidence-driven DNA archive research

Prize direction: demonstrate a deepagent making an evidence-based decision across a long task: plan, delegate a measured experiment, inspect evidence, challenge a proposal, obtain approval, recover files, and explain the result. This is a proposed demo strategy, not a verified judging rubric or a promise of a prize.

Official framework reference: https://www.langchain.com/deep-agents

## Implemented research integration

The supervisor delegates to `codec-researcher`, whose `run_learning_experiment` tool starts the real the bundled codec `run_loop` in an isolated Python process. It uses the archive's channel, retention model, coverage and target with the bundled codec’s fixed research test file. The loop audits rules, trains a risk scorer on simulated decoder failures, searches settings and evaluates with held-out seeds. The existing CNN polisher remains fixed: upstream only implements decoder adaptation for its transformer.

Quick mode uses upstream reduced budgets and a ten-minute process limit. Full mode uses upstream default budgets and a two-hour limit. Neither promises improvement. Reports, logs, risk model checkpoints and codec manifests are published through the existing artifact store; a completed report is also recorded on the job. The agent receives tool events through the existing activity stream. Autopilot remains a separate scripted recipe and does not demonstrate deepagent behavior.

## Demo narrative

1. Show the company's retention and recovery requirements and the supervisor's plan.
2. Show delegation to the codec researcher and the measured default-versus-learned comparison, with trial counts and quick-mode labeling visible.
3. Explain negative results if learning fails or does not help. Do not replace them with a rehearsed success.
4. Show the codec engineer's actual archive experiments and the adversary's failed scenarios and redesign attempts.
5. Show human approval of the modeled cost, then the separate disaster-drill approval.
6. Recover the records and show per-file SHA-256 verification and the resulting certificate.

Keep research and operational evidence separate. Learning currently does **not** change the archive encoder. Before deploying a learned scorer, it must be threaded through archive experiments and order creation, its settings preserved in the DNA manifest, and the exact emitted sequences subjected to independent channel and vault-loss tests. Customer recovery and certificates must not inherit success from the research test file.

## Outstanding validation

A real complete training run, measured improvement (if any), an actual LLM-driven delegation trace, and end-to-end testing of the new research tool's cloud artifact publication must be demonstrated before pitching this as verified. The exact competition judging criteria have not yet been supplied.
