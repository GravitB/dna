"""Research failures must remain inspectable and must never alter archive settings."""
import json
import subprocess

import pytest
from lazarus import tools


@pytest.mark.parametrize('failure', ['timeout', 'process'])
def test_learning_failure_is_saved_without_deploying(monkeypatch, tmp_path, failure):
    job = {'policy': {'target': 1.0}, 'chosen': {'redundancy': 1.0}}
    monkeypatch.setattr(tools.store, 'job_dir', lambda jid: tmp_path)
    monkeypatch.setattr(tools.store, 'load', lambda jid: job)
    monkeypatch.setattr(tools.store, 'update', lambda jid, fn: fn(job))
    monkeypatch.setattr(tools, '_profile', lambda *a: object())
    monkeypatch.setattr(tools.dna, 'profile_to_dict', lambda p: {'name': 'test'})
    published = {}
    monkeypatch.setattr(tools.artifacts, 'publish', lambda jid, path, data: published.update({path: data}))
    def fail(*args, **kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])
        raise subprocess.CalledProcessError(1, args[0])
    monkeypatch.setattr(subprocess, 'run', fail)
    report = tools.run_learning_experiment.__wrapped__('test')
    assert report['status'] == ('timed_out' if failure == 'timeout' else 'failed')
    assert job['chosen'] == {'redundancy': 1.0}
    assert job['learning_experiments'] == [report]
    assert any(p.endswith('worker.log') for p in published)
    saved = next(data for p, data in published.items() if p.endswith('report.json'))
    assert json.loads(saved) == report
