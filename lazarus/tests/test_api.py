from fastapi.testclient import TestClient
from lazarus.api import app
from lazarus import store


def test_bad_policy_is_client_error(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path)
    with TestClient(app) as client:
        for policy in ('not-json', '{"n_vaults": "bad"}', '{"coverage": -1}', '{"n_vaults": 0}'):
            assert client.post('/api/jobs', data={'mode': 'autopilot', 'policy': policy}).status_code == 400
        assert client.post('/api/jobs', data={'mode': 'unknown', 'policy': '{}'}).status_code == 400
