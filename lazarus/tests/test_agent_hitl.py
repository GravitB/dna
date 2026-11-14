"""Drives the real deep agent graph with a scripted fake chat model (no API key needed) to check
delegation to subagents, the human-approval interrupts and the event stream end to end."""
import shutil
import time
from pathlib import Path

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from lazarus import agent, store

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data" / "northstar_bio"


class FakeModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kw):
        return self


def call(name, args, i):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c{i}"}])


def test_agent_hitl_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path)
    pol = {"retention_years": 50, "tech": "nanopore", "coverage": 10, "budget_usd": 50, "target": 1.0, "n_vaults": 3}
    jid = store.new_job("Northstar Bio", pol)
    for f in SAMPLES.iterdir():
        shutil.copy(f, store.job_dir(jid) / "uploads" / f.name)
    files = ["ledger_FY2026.csv", "trial_NB042_consent.pdf"]
    script = iter([
        call("write_todos", {"todos": [{"content": "inventory", "status": "in_progress"}]}, 1),
        call("inventory_files", {"job_id": jid}, 2),
        call("prepare_archive", {"job_id": jid, "file_names": files}, 3),
        call("task", {"subagent_type": "adversary", "description": f"job_id {jid} stress pool-0000"}, 4),
        call("stress_test", {"job_id": jid, "pool_id": "pool-0000", "redundancy": 1.0, "coverage": 10,
                             "scenario": "vault_loss", "trials": 1}, 5),
        AIMessage(content="vault_loss: tested."),
        call("place_synthesis_order", {"job_id": jid, "redundancy": 1.2, "coverage": 10, "n_vaults": 3}, 6),
        call("destroy_primary", {"job_id": jid}, 7),
        call("task", {"subagent_type": "recovery-engineer", "description": f"job_id {jid} recover"}, 8),
        call("recover_archive", {"job_id": jid}, 9),
        AIMessage(content="All files verified."),
        AIMessage(content="Done."),
    ])
    monkeypatch.setattr(agent, "MODEL", FakeModel(messages=script))
    run = agent.start(jid)
    approvals = 0
    t0 = time.time()
    while run.thread.is_alive() and time.time() - t0 < 300:
        if run.pending:
            assert run.pending["tool"] in ("place_synthesis_order", "destroy_primary")
            run.decide({"decision": "approve"})
            approvals += 1
        time.sleep(0.2)
    assert approvals == 2
    types = [e["type"] for e in store._events[jid]]
    for t in ("plan", "delegate", "stress_result", "interrupt", "vault_event", "drill_result"):
        assert t in types, t
    job = store.load(jid)
    assert job["drills"][-1]["all_verified"]
    assert not any((store.job_dir(jid) / "uploads").iterdir())


def test_provider_plan_arguments_never_crash_observer(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'JOBS_DIR', tmp_path)
    jid=store.new_job('Plan parsing', {})
    r=agent.Run(jid)
    for todos in ('[{"content":"Test frozen candidate","status":"pending"}]', 'malformed', ['bad row'], {'content':'bad shape'}):
        r._on_update((), {'model':{'messages':[call('write_todos',{'todos':todos},1)]}})
    assert len(store.events_since(jid,0,0))==4
    assert agent._plan_rows('bad')==[]
