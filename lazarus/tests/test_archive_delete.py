from fastapi.testclient import TestClient
from lazarus import api, store
client = TestClient(api.app)


def test_delete_restore(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'JOBS_DIR', tmp_path)
    monkeypatch.setattr(store, 'get_cloud', lambda: None)
    job_id = store.new_job('Test', {'retention_years': 50})
    artifact = store.job_dir(job_id) / 'uploads' / 'original.txt'
    artifact.write_text('keep me')
    assert client.delete(f'/api/jobs/{job_id}').status_code == 200
    assert all(j['id'] != job_id for j in client.get('/api/jobs').json())
    assert artifact.read_text() == 'keep me'
    assert client.post(f'/api/jobs/{job_id}/restore').status_code == 200
    assert any(j['id'] == job_id for j in client.get('/api/jobs').json())


def test_active_and_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'JOBS_DIR', tmp_path)
    monkeypatch.setattr(store, 'get_cloud', lambda: None)
    job_id = store.new_job('Test', {'retention_years': 50})
    store.update(job_id, lambda j: j.update(simulations=[{'status': 'running'}]))
    assert client.delete(f'/api/jobs/{job_id}').status_code == 409
    assert not store.load(job_id).get('deleted_at')
    assert client.delete('/api/jobs/does-not-exist').status_code == 404
