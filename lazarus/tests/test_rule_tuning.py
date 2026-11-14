from lazarus import tools


def test_sweep_compares_all_rule_combinations(monkeypatch):
    calls = []

    def experiment(job_id, pool_id, redundancy, strand_length, coverage, decoder, trials, homopolymer_rule, gc_rule):
        calls.append((homopolymer_rule, gc_rule))
        return {"settings": {"redundancy": redundancy, "coverage": coverage,
                             "homopolymer_rule": homopolymer_rule, "gc_rule": gc_rule},
                "recovery_rate": 1, "strand_accuracy": 1, "write_usd": 1,
                "read_usd": 1, "bits_per_base": 1, "n_trials": trials}

    monkeypatch.setattr(tools, "_experiment", experiment)
    monkeypatch.setattr(tools.store, "emit", lambda *args: None)
    job = {"experiments": []}
    monkeypatch.setattr(tools.store, "update", lambda _, fn: fn(job))
    result = tools.run_codec_sweep.__wrapped__("job", "pool", [0.3], [10], trials=1)
    assert set(calls) == {(True, True), (True, False), (False, True), (False, False)}
    assert len(result["points"]) == 4


def test_stress_test_uses_selected_rules(monkeypatch):
    seen = []
    monkeypatch.setattr(tools.store, "load", lambda _: {"policy": {"tech": "nanopore", "retention_years": 50}, "sealed": {}})

    def experiment(*args, **kwargs):
        seen.append((args[7], args[8]))
        return {"recovery_rate": 1, "settings": {"redundancy": args[2]}}

    monkeypatch.setattr(tools, "_experiment", experiment)
    monkeypatch.setattr(tools.store, "emit", lambda *args: None)
    monkeypatch.setattr(tools.store, "update", lambda _, fn: fn({"stress": []}))
    tools.stress_test.__wrapped__("job", "pool", 0.3, 10, "low_coverage",
                                  homopolymer_rule=False, gc_rule=True)
    assert seen == [(False, True)]
