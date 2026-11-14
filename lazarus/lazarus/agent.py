"""The Lazarus deep agent: a supervisor plus four subagents, built with LangChain deepagents.

- planning: deepagents write_todos (streamed to the UI as `plan` events)
- subagents with isolated context: codec-engineer, adversary, recovery-engineer, compliance
- virtual filesystem: the agents keep design notes in /design_notes.md
- human in the loop: place_synthesis_order and destroy_primary pause for approval
- every number comes from tools that run the real Erbgut codec
"""

from __future__ import annotations

import os
import threading
import traceback

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from . import store, tools, presentation

MODEL = os.environ.get("LAZARUS_MODEL", "google_genai:gemini-2.5-flash" if (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")) else "anthropic:claude-sonnet-5-5")


def has_model_key() -> bool:
    if isinstance(MODEL, str) and MODEL.startswith("google_genai:"):
        return bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))
    return bool(os.environ.get("ANTHROPIC_API_KEY"))

SUPERVISOR_PROMPT = """You are Lazarus, an autonomous DNA-archive engineer working for a regulated company.
Your job: turn the customer's long-retention files into a DNA archive with measured simulated recovery evidence, then
prove it with a disaster drill and issue a Simulation Recovery Report.

You never invent numbers. Every recovery rate, cost or verdict must come from a tool result.
You never write DNA letters yourself; tools run the real Erbgut codec (Fountain encoder, calibrated
sequencing simulator, majority-vote baseline and a CNN decoder trained on real Nanopore reads).

Workflow (write it as todos first with write_todos, keep them updated):
1. inventory_files. Decide the DNA tier: only cold, immutable, long-retention records go to DNA.
   All uploaded files were explicitly selected by the customer. Include ALL of them in prepare_archive.
   You may explain suitability concerns, but never silently exclude a selected record.
2. prepare_archive with the DNA-tier files. Note the reference_pool.
3. First delegate a quick learned-encoding investigation to codec-researcher. Use its report to explain
   the evidence and limits of learned selection. Keep research results distinct from the actual archive
   design: only archive experiments and recovery drills establish its recoverability.
   Delegate codec design to the `codec-engineer` subagent. Give it: job_id, reference pool id, policy
   (retention years, tech, planned coverage, budget, target, n_vaults). Ask for the cheapest
   (redundancy, coverage) that meets the target on the normal channel, with evidence.
   The number of vault sites is fixed by the customer's policy; do not change it.
4. Delegate red-teaming to the `adversary` subagent with the proposed design. If any scenario fails,
   REVISE the design (raise redundancy by at least 0.3 or increase coverage) and send it back to the adversary. Repeat until all
   scenarios pass or you hit budget; then explain the trade-off honestly.
5. Record the decision and the evidence in /design_notes.md (virtual filesystem).
6. Call place_synthesis_order with the final design, including both tested rule settings. A human must approve it; if they reject or edit,
   follow their decision.
7. Call destroy_primary to start the disaster drill (a human approves this too).
8. Delegate the drill to the `recovery-engineer` subagent. If any file fails verification, have it retry
   with a new attempt number and deeper coverage. Never claim success without sha256_match.
9. Delegate the certificate to the `compliance` subagent.
Finish with a short plain-English summary for the compliance officer.

Always pass job_id to tools and include it in every subagent task description.
Keep chat messages short: one or two sentences explaining what you are doing and why."""

CODEC_PROMPT = """You are the Codec Engineer. You design the DNA encoding for one archive using the real
Erbgut codec through tools. Method:
1. build_profile to see the channel (error rates, strand loss after the storage period).
2. run_codec_sweep with decoder='baseline', trials 4-6, redundancies like [0.3, 0.6, 1.0] and 1-3
   coverages around the planned one, to map the recovery/cost frontier and compare rule combinations.
3. Confirm the cheapest point that meets the target on the WHOLE archive with run_codec_experiment,
   pool_id='all', decoder='polish', trials 6-8.
4. estimate_cost for the whole archive at that point.
Pass the selected homopolymer_rule and gc_rule to confirmation and cost tools.
Return: the chosen redundancy, coverage and both rule settings, recovery rates with trial counts, modeled costs, and the
cheaper points that failed (so the supervisor sees the trade-off). Never invent numbers."""

ADVERSARY_PROMPT = """You are the Adversary. Your job is to BREAK the proposed DNA archive design before
reality does. Run stress_test with pool_id='all' (the whole archive) for each scenario: vault_loss, simulator_b,
decay_x2, low_coverage (trials 4-6, decoder 'polish', target as given). Report each result with recovery rate and trial count,
and say plainly which scenarios fail. Do not soften failures. Suggest the smallest change you would test
next, but do not claim it works unless you tested it. Pass the proposed homopolymer_rule and gc_rule to every test.
For low_coverage pass the original planned coverage, since stress_test itself applies the reduction. Always use the policy's vault count.
Test each scenario once per design and report the observed result; do not retry the same test looking for a better outcome."""

RECOVERY_PROMPT = """You are the Recovery Engineer. It is decades later; all servers are gone. Run
recover_archive. It uses only the surviving vaults, the one-page bootstrap spec and the customer's KMS
keys. Report for every file whether its SHA-256 matched, and compare the baseline decoder with the CNN
decoder per pool. If any file failed, retry with attempt+1 and coverage about 1.5x higher (at most two
retries). Never report success without sha256_match."""

COMPLIANCE_PROMPT = """You are the Compliance Officer's agent. Call read_job_log, then write_certificate
with a 2-4 sentence factual summary (design, stress results, drill result, caveats: simulated channel,
modeled costs). Only state facts that appear in the log."""


def _plan_rows(value):
    """Provider tool arguments can contain a JSON string or malformed rows. Observers must not crash a run."""
    import json
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if not isinstance(value, list):
        return []
    return [{"text": str(t.get("content", "")), "status": t.get("status", "pending")}
            for t in value if isinstance(t, dict)]


def _t(fn) -> StructuredTool:
    return StructuredTool.from_function(fn, name=fn.__name__, description=(fn.__doc__ or "").strip())


def build_agent(model: str | None = None, analysis_preset: str = "standard", candidate_workflow: bool = False):
    from deepagents import create_deep_agent

    T = {f.__name__: _t(f) for f in tools.ALL_TOOLS}
    subagents = [
        {"name": "codec-researcher", "description": "Runs real Erbgut risk-learning experiments and critically compares learned encoding with the same-decoder default.",
         "system_prompt": "Call prepare_learned_model once. Honor standard, evaluated or fresh encoding choice. If it fails, stop and explain the next action. Report actual evaluation scope; the CNN decoder is frozen. Attribute training to Erbgut. Save factual provenance to /learning-evidence.md.",
         "tools": [T["prepare_learned_model"]]},
        {"name": "codec-engineer", "description": "Designs the DNA encoding: runs real Erbgut codec sweeps and experiments, returns the cheapest design meeting the target with evidence.",
         "system_prompt": CODEC_PROMPT + " For quick_demo call run_quick_design once and return its exact settings; do not run a separate search.", "tools": [T["compare_archive_candidates"], T["run_quick_design"], T["build_profile"], T["run_codec_sweep"], T["run_codec_experiment"], T["estimate_cost"]]},
        {"name": "adversary", "description": "Red-teams a proposed design under vault loss, a different sequencing channel, double decay and low coverage.",
         "system_prompt": ADVERSARY_PROMPT + " For quick_demo use read_job_log to independently review the four measured tests produced by run_quick_design. Do not repeat those tests.", "tools": [T["validate_archive_candidate"], T["stress_test"], T["read_job_log"]]},
        {"name": "recovery-engineer", "description": "Runs the disaster recovery drill from the surviving DNA vaults and verifies every file by SHA-256.",
         "system_prompt": RECOVERY_PROMPT, "tools": [T["recover_archive"]]},
        {"name": "compliance", "description": "Writes a simulation recovery report from the measured log.",
         "system_prompt": COMPLIANCE_PROMPT, "tools": [T["read_job_log"], T["write_certificate"]]},
    ]
    if analysis_preset == "quick_demo":
        subagents = [s for s in subagents if s["name"] != "codec-researcher"]
        next(s for s in subagents if s["name"] == "codec-engineer")["tools"] = [T["run_quick_design"]]
        next(s for s in subagents if s["name"] == "adversary")["tools"] = [T["read_job_log"]]
    if candidate_workflow:
        next(s for s in subagents if s['name'] == 'codec-engineer').update(
            system_prompt="Call compare_archive_candidates once with job_id. It performs bounded matched train-seed comparisons on actual encrypted customer files, including any necessary revisions. Return its actual measurements and selected candidate ID. Stop honestly on error or no selection; never invent settings or use held-out results for selection.",
            tools=[T['compare_archive_candidates']])
        next(s for s in subagents if s['name'] == 'adversary').update(
            system_prompt="Call validate_archive_candidate once with job_id. This tests the frozen train-selected candidate on held-out normal and stress conditions. Return its exact settings including candidate_id or its failure. Never retry, retune, or fabricate final evidence.",
            tools=[T['validate_archive_candidate'], T['read_job_log']])
    return create_deep_agent(
        model=model or MODEL,
        tools=[T["inventory_files"], T["prepare_archive"], T["estimate_cost"], T["place_synthesis_order"], T["destroy_primary"]],
        system_prompt=SUPERVISOR_PROMPT,
        subagents=subagents,
        interrupt_on={"place_synthesis_order": True, "destroy_primary": True},
        checkpointer=InMemorySaver(),
        name="lazarus",
    )


# ---------------------------------------------------------------- runner


class Run:
    """One agent run in a background thread. HITL decisions arrive through decide()."""

    def __init__(self, job_id: str, mode: str = "agent"):
        self.job_id = job_id
        self.mode = mode
        self.pending: dict | None = None
        self._decision: dict | None = None
        self._event = threading.Event()
        self.thread = threading.Thread(target=self._main, daemon=True)
        self.current_sub = "supervisor"

    def start(self):
        self.thread.start()
        return self

    def decide(self, decision: dict) -> bool:
        if self.pending is None or self._decision is not None:
            return False
        self._decision = decision
        self._event.set()
        return True

    # ---- approval plumbing
    def _ask(self, tool: str, args: dict) -> dict:
        summary = {}
        try:
            if tool == "place_synthesis_order":
                summary = {} if args.get("candidate_id") else tools.estimate_cost.__wrapped__(self.job_id, float(args.get("redundancy", 1.0)),
                                                          float(args.get("coverage", 10)), int(args.get("strand_length", 110)), int(args.get("n_vaults", 3)),
                                                          bool(args.get("homopolymer_rule", True)), bool(args.get("gc_rule", True)))
                job = store.load(self.job_id)
                summary = presentation.proposal(job, args, summary)
                if not summary["can_approve"]:
                    from .experience import correction
                    summary["correction"] = correction(job, args)
                    if summary["correction"]:
                        candidate = summary["correction"]
                        cost = tools.estimate_cost.__wrapped__(self.job_id, **{k:v for k,v in candidate.items() if k != "decoder"})
                        summary["correction_summary"] = presentation.proposal(job, candidate, cost)
        except Exception as e:  # noqa: BLE001
            summary = {"error": str(e)}
        self.pending = {"tool": tool, "args": args, "summary": summary}
        store.update(self.job_id, lambda j: j.update(status=f"awaiting_approval:{tool}"))
        store.emit(self.job_id, "interrupt", "supervisor", self.pending)
        self._event.wait()
        self._event.clear()
        d, self._decision, self.pending = self._decision or {"decision": "reject"}, None, None
        store.emit(self.job_id, "message", "human", {"text": f"Human decision on {tool}: {d.get('decision')}"})
        return d

    def _main(self):
        try:
            store.update(self.job_id, lambda j: j.update(status="running", mode=self.mode))
            if self.mode == "autopilot":
                from . import autopilot
                result = autopilot.run(self.job_id, approve=lambda t, a: self._ask(t, a).get("decision") in ("approve", "edit"))
                if result.get("error") or result.get("stopped"):
                    store.update(self.job_id, lambda j: j.update(status="stopped", error=result.get("error") or result["stopped"]))
                    store.emit(self.job_id, "message", "supervisor", {"text": result.get("error") or result.get("stopped")})
            else:
                self._run_agent()
                job = store.load(self.job_id)
                if not job.get("certificate"):
                    message = job.get("error") or "Agent stopped before producing a recovery report; check the timeline and model response."
                    store.update(self.job_id, lambda j: j.update(status="stopped", error=message))
                    store.emit(self.job_id, "message", "supervisor", {"text": message})
            store.update(self.job_id, lambda j: j.update(finished=True))
            store.emit(self.job_id, "message", "supervisor", {"text": "Run finished."})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            raw = str(e).lower()
            if "prepayment" in raw or "402" in raw:
                message = "Google could not run the AI analysis because prepaid credits are unavailable. Check Gemini billing or start a new archive with scripted analysis."
            elif "429" in raw or "quota" in raw:
                message = "The AI provider's usage limit was reached. Try a new archive later or choose scripted analysis."
            else:
                message = f"Analysis stopped ({type(e).__name__}). Review the requirements and create a revised archive, or use scripted analysis."
            store.emit(self.job_id, "message", "supervisor", {"text": message})
            store.update(self.job_id, lambda j: j.update(status="error", error=message, finished=True))

    def _run_agent(self):
        job = store.load(self.job_id)
        agent = build_agent(analysis_preset=job.get("analysis_preset", "standard"), candidate_workflow=bool(job.get("encoding_mode") and job.get("analysis_preset") != "quick_demo"))
        p = job["policy"]
        task = (f"job_id: {self.job_id}\nCompany: {job['company']}\nPolicy: retain {p['retention_years']} years, "
                f"read technology {p['tech']}, planned coverage {p['coverage']} reads/strand, budget ${p['budget_usd']} "
                f"(modeled write cost), recovery target {p['target']} (fraction of trials), {p['n_vaults']} vault sites.\n"
                f"Notes from the customer: {p.get('notes') or 'none'}\nBuild, red-team, order, drill and report measured simulation results.")
        if job.get("encoding_mode") and job.get("analysis_preset") != "quick_demo":
            task += ("\nFROZEN CANDIDATE WORKFLOW OVERRIDES LEGACY SEARCH: after prepare_archive delegate codec-researcher "
                     "to prepare_learned_model once, honoring encoding_mode=" + job['encoding_mode'] +
                     ". Stop on error; never silently change modes. Then delegate codec-engineer to compare_archive_candidates "
                     "once (redundancy 0.8, trials 3); matched customer trials, not the research file. "
                     "Delegate adversary to validate_archive_candidate once. If no settings are returned, stop honestly. "
                     "Use its exact returned settings including candidate_id in place_synthesis_order. Do not call legacy "
                     "sweep/stress/learning tools or retune on final results. Then approvals, disaster drill and report as usual. "
                     "Three trials are exploratory and cannot establish a future guarantee.")
        config = {"configurable": {"thread_id": self.job_id}, "recursion_limit": 300}
        if job.get("analysis_preset") == "quick_demo":
            task += "\nQUICK_DEMO: delegate to codec-engineer to call run_quick_design once. It measures baseline, CNN and four stress tests with 3 trials each, bounded to four designs. If it returns an error, stop honestly. Delegate adversary to review the recorded results with read_job_log, then use the exact returned settings for place_synthesis_order (decoder polish). Keep the selected picture and all policy values fixed. No extra experiments. Plan with write_todos first, then continue through both approval interrupts, recovery-engineer and compliance."
        inp = {"messages": [{"role": "user", "content": task}]}
        while True:
            for ns, update in agent.stream(inp, config, stream_mode="updates", subgraphs=True):
                self._on_update(ns, update)
                if store.load(self.job_id).get("candidate_rejected"):
                    return  # Failed selection/final evidence is terminal, never a prompt to re-roll.
            state = agent.get_state(config)
            interrupts = [i for t in state.tasks for i in (t.interrupts or [])] or list(getattr(state, "interrupts", []) or [])
            if not interrupts:
                break
            resume = {}
            for intr in interrupts:
                val = intr.value
                reqs = val.get("action_requests", []) if isinstance(val, dict) else []
                if not reqs and isinstance(val, dict) and val.get("type") == "tool_approval":
                    reqs = [val]
                decisions = []
                for r in reqs:
                    d = self._ask(r.get("name") or r.get("action", {}).get("name", "?"), r.get("args") or {})
                    if d.get("decision") == "approve":
                        decisions.append({"type": "approve"})
                    elif d.get("decision") == "edit":
                        decisions.append({"type": "edit", "edited_action": {"name": r.get("name"), "args": {**(r.get("args") or {}), **(d.get("args") or {})}}})
                    else:
                        decisions.append({"type": "reject", "message": d.get("message") or "The human rejected this action."})
                resume[intr.id] = {"decisions": decisions} if "action_requests" in (val or {}) else decisions[0]
            inp = Command(resume=resume if len(resume) > 1 else next(iter(resume.values())))

    def _on_update(self, ns, update):
        if not isinstance(update, dict):
            return
        in_sub = bool(ns)
        for node, val in update.items():
            if not isinstance(val, dict):
                continue
            if "todos" in val and not in_sub and val["todos"] is not None:
                store.emit(self.job_id, "plan", "supervisor", {"todos": _plan_rows(val["todos"])})
            for m in val.get("messages", []) or []:
                if not isinstance(m, AIMessage):
                    continue
                for tc in m.tool_calls or []:
                    if tc["name"] == "task" and not in_sub:
                        self.current_sub = tc["args"].get("subagent_type", "subagent")
                        store.emit(self.job_id, "delegate", "supervisor", {"subagent": self.current_sub,
                                                                           "description": tc["args"].get("description", "")[:600]})
                    elif tc["name"] in ("write_todos", "write_file", "edit_file") and not in_sub:
                        if tc["name"] == "write_todos":
                            store.emit(self.job_id, "plan", "supervisor", {"todos": _plan_rows(tc["args"].get("todos", []))})
                        else:
                            store.emit(self.job_id, "file_write", "supervisor", {"path": tc["args"].get("file_path"),
                                                                                 "content": (tc["args"].get("content") or tc["args"].get("new_string") or "")[:4000]})
                text = m.content if isinstance(m.content, str) else " ".join(
                    b.get("text", "") for b in m.content if isinstance(b, dict) and b.get("type") == "text")
                if text.strip():
                    store.emit(self.job_id, "message", self.current_sub if in_sub else "supervisor", {"text": text.strip()[:3000]})


RUNS: dict[str, Run] = {}


def start(job_id: str, mode: str = "agent") -> Run:
    r = Run(job_id, mode)
    RUNS[job_id] = r
    return r.start()
