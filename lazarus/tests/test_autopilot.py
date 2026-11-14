from types import SimpleNamespace
from lazarus import autopilot


def test_failed_design_never_orders_or_deletes(monkeypatch):
    calls = []
    monkeypatch.setattr(autopilot.store, 'emit', lambda *a: None)
    fake = SimpleNamespace(
        inventory_files=lambda **kw: {'files': [{'name': 'a.pdf'}], 'policy': {'coverage': 10, 'n_vaults': 3, 'target': 1}},
        prepare_archive=lambda **kw: {'reference_pool': 'pool-0000'},
        build_profile=lambda **kw: {},
        run_codec_sweep=lambda **kw: {'points': []},
        stress_test=lambda **kw: {'passed': False},
        estimate_cost=lambda **kw: {'within_budget': True},
        place_synthesis_order=lambda **kw: calls.append('order'),
        destroy_primary=lambda **kw: calls.append('destroy'),
    )
    monkeypatch.setattr(autopilot, 'tools', fake)
    result = autopilot.run('test')
    assert 'error' in result
    assert calls == []
