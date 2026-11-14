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

from . import store, tools

MODEL = os.environ.get("LAZARUS_MODEL", "anthropic:claude-sonnet-5-5")

SUPERVISOR_PROMPT = """You are Lazarus, an autonomous DNA-archive engineer working for a regulated company.
Your job: turn the customer's long-retention files into a DNA archive that is PROVEN recoverable, then
prove it with a disaster drill and issue a Recoverability Certificate.

You never invent numbers. Every recovery rate, cost or verdict must come from a tool result.
You never write DNA letters yourself; tools run the real Erbgut codec (Fountain encoder, calibrated
sequencing simulator, majority-vote baseline and a CNN decoder trained on real Nanopore reads).

Workflow (write it as todos first with write_todos, keep them updated):
1. inventory_files. Decide the DNA tier: only cold, immutable, long-retention records go to DNA.
   Files that are clearly edited often (notes, drafts) stay on conventional storage; say why.
2. prepare_archive with the DNA-tier files. Note the reference_pool.
3. Delegate codec design to the `codec-engineer` subagent. Give it: job_id, reference pool id, policy
   (retention years, tech, planned coverage, budget, target, n_vaults). Ask for the cheapest
   (redundancy, coverage) that meets the target on the normal channel, with evidence.
4. Delegate red-teaming to the `adversary` subagent with the proposed design. If any scenario fails,
   REVISE the design (raise redundancy or coverage) and send it back to the adversary. Repeat until all
   scenarios pass or you hit budget; then explain the trade-off honestly.
5. Record the decision and the evidence in /design_notes.md (virtual filesystem).
6. Call place_synthesis_order with the final design. A human must approve it; if they reject or edit,
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
   coverages around the planned one, to map the recovery/cost frontier.
3. Confirm the cheapest point that meets the target on the WHOLE archive with run_codec_experiment,
   pool_id='all', decoder='polish', trials 6-8.
4. estimate_cost for the whole archive at that point.
Return: the chosen redundancy and coverage, recovery rates with trial counts, modeled costs, and the
cheaper points that failed (so the supervisor sees the trade-off). Never invent numbers."""

ADVERSARY_PROMPT = """You are the Adversary. Your job is to BREAK the proposed DNA archive design before
reality does. Run stress_test with pool_id='all' (the whole archive) for each scenario: vault_loss, simulator_b,
decay_x2, low_coverage (trials 4-6, decoder 'polish', target as given). Report each result with recovery rate and trial count,
and say plainly which scenarios fail. Do not soften failures. Suggest the smallest change you would test
next, but do not claim it works unless you tested it."""

RECOVERY_PROMPT = """You are the Recovery Engineer. It is decades later; all servers are gone. Run
recover_archive. It uses only the surviving vaults, the one-page bootstrap spec and the customer's KMS
keys. Report for every file whether its SHA-256 matched, and compare the baseline decoder with the CNN
decoder per pool. If any file failed, retry with attempt+1 and coverage about 1.5x higher (at most two
retries). Never report success without sha256_match."""

COMPLIANCE_PROMPT = """You are the Compliance Officer's agent. Call read_job_log, then write_certificate
with a 2-4 sentence factual summary (design, stress results, drill result, caveats: simulated channel,
modeled costs). Only state facts that appear in the log."""


def _t(fn) -> StructuredTool:
    return StructuredTool.from_function(fn, name=fn.__name__, description=(fn.__doc__ or "").strip())


def build_agent(model: str | None = None):
    from deepagents import create_deep_agent
    from langchain.agents.middleware import TodoListMiddleware

    T = {f.__name__: _t(f) for f in tools.ALL_TOOLS}
    subagents = [
        {"name": "codec-engineer", "description": "Designs the DNA encoding: runs real Erbgut codec sweeps and experiments, returns the cheapest design meeting the target with evidence.",
         "system_prompt": CODEC_PROMPT, "tools": [T["build_profile"], T["run_codec_sweep"], T["run_codec_experiment"], T["estimate_cost"]]},
        {"name": "adversary", "description": "Red-teams a proposed design under vault loss, a different sequencing channel, double decay and low coverage.",
         "system_prompt": ADVERSARY_PROMPT, "tools": [T["stress_test"]]},
        {"name": "recovery-engineer", "description": "Runs the disaster recovery drill from the surviving DNA vaults and verifies every file by SHA-256.",
         "system_prompt": RECOVERY_PROMPT, "tools": [T["recover_archive"]]},
        {"name": "compliance", "description": "Writes the Recoverability Certificate from the measured log.",
         "system_prompt": COMPLIANCE_PROMPT, "tools": [T["read_job_log"], T["write_certificate"]]},
    ]
    return create_deep_agent(
        model=model or MODEL,
        tools=[T["inventory_files"], T["prepare_archive"], T["estimate_cost"], T["place_synthesis_order"], T["destroy_primary"]],
        system_prompt=SUPERVISOR_PROMPT,
        subagents=subagents,
        interrupt_on={"place_synthesis_order": True, "destroy_primary": True},
        middleware=[TodoListMiddleware()],
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
        if self.pending is None:
            return False
        self._decision = decision
        self._event.set()
        return True

    # ---- approval plumbing
    def _ask(self, tool: str, args: dict) -> dict:
        summary = {}
        try:
            if tool == "place_synthesis_order":
                summary = tools.estimate_cost.__wrapped__(self.job_id, float(args.get("redundancy", 1.0)),
                                                          float(args.get("coverage", 10)), int(args.get("strand_length", 110)), int(args.get("n_vaults", 3)))
                job = store.load(self.job_id)
                summary["stress"] = [{k: s[k] for k in ("scenario", "recovery_rate", "n_trials", "passed")} | {"redundancy": s["settings"]["redundancy"]}
                                     for s in job["stress"]][-8:]
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
            store.update(self.job_id, lambda j: j.update(finished=True))
            store.emit(self.job_id, "message", "supervisor", {"text": "Run finished."})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            store.emit(self.job_id, "message", "supervisor", {"text": f"Run failed: {type(e).__name__}: {e}"})
            store.update(self.job_id, lambda j: j.update(status="error", error=str(e)))

    def _run_agent(self):
        agent = build_agent()
        job = store.load(self.job_id)
        p = job["policy"]
        task = (f"job_id: {self.job_id}\nCompany: {job['company']}\nPolicy: retain {p['retention_years']} years, "
                f"read technology {p['tech']}, planned coverage {p['coverage']} reads/strand, budget ${p['budget_usd']} "
                f"(modeled write cost), recovery target {p['target']} (fraction of trials), {p['n_vaults']} vault sites.\n"
                f"Notes from the customer: {p.get('notes') or 'none'}\nBuild, red-team, order, drill and certify the archive.")
        config = {"configurable": {"thread_id": self.job_id}, "recursion_limit": 300}
        inp = {"messages": [{"role": "user", "content": task}]}
        while True:
            for ns, update in agent.stream(inp, config, stream_mode="updates", subgraphs=True):
                self._on_update(ns, update)
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
                store.emit(self.job_id, "plan", "supervisor", {"todos": [
                    {"text": t.get("content", ""), "status": t.get("status", "pending")} for t in val["todos"]]})
            for m in val.get("messages", []) or []:
                if not isinstance(m, AIMessage):
                    continue
                for tc in m.tool_calls or []:
                    if tc["name"] == "task" and not in_sub:
                        self.current_sub = tc["args"].get("subagent_type", "subagent")
                        store.emit(self.job_id, "delegate", "supervisor", {"subagent": self.current_sub,
                                                                           "description": tc["args"].get("description", "")[:600]})
                    elif tc["name"] in ("write_todos", "write_file", "edit_file") and not in_sub:
                        if tc["name"] != "write_todos":
                            store.emit(self.job_id, "file_write", "supervisor", {"path": tc["args"].get("file_path"),
                                                                                 "content": (tc["args"].get("content") or tc["args"].get("new_string") or "")[:4000]})
                text = m.content if isinstance(m.content, str) else " ".join(
                    b.get("text", "") for b in m.content if isinstance(b, dict) and b.get("type") == "text")
                if text.strip():
                    store.emit(self.job_id, "message", self.current_sub if in_sub else "supervisor", {"text": text.strip()[:3000]})


RUNS: dict[str, Run] = {}


def start(job_id: str, mode: str = "agent") -> Run:
    r = Run(job_id, mode).start()
    RUNS[job_id] = r
    return r
