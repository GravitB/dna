import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from lazarus import api, agent, store, tools, experience, presentation


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(agent, "start", lambda *a: None)
    with TestClient(api.app) as c:
        yield c


def new_demo(client):
    r = client.post('/api/jobs', data={'policy':'{}','mode':'autopilot','use_samples':'true','analysis_preset':'quick_demo'})
    assert r.status_code == 200, r.text
    return r.json()['job_id']


def test_quick_picture_roundtrip_and_real_sequence_counts(client, monkeypatch):
    jid = new_demo(client)
    job = store.load(jid)
    assert job['policy']['coverage'] == 16 and job['policy']['n_vaults'] == 3
    picture = experience.QUICK_SAMPLE
    original = (api.SAMPLE_DIR / picture).read_bytes()
    assert len(original) < 4096
    assert client.get(f'/api/jobs/{jid}/preview/{picture}').content == original
    tools.prepare_archive(job_id=jid, file_names=[picture])
    design = tools.run_quick_design(job_id=jid)
    assert 'error' not in design, design
    job = store.load(jid)
    wrong = {**design['settings'], 'decoder': 'baseline'}
    cost = tools.estimate_cost(job_id=jid, redundancy=design['settings']['redundancy'], coverage=16, n_vaults=3)
    assert not presentation.proposal(job, wrong, cost)['can_approve']
    assert experience.correction(job, wrong) == design['settings']
    run = agent.Run(jid)
    monkeypatch.setattr(run._event, 'wait', lambda: None)
    run._ask('place_synthesis_order', wrong)
    interrupt = [e for e in store.events_since(jid, 0, 0) if e['type']=='interrupt'][-1]
    assert interrupt['data']['summary']['correction_summary']['can_approve']
    assert all(e['trials']==3 for e in interrupt['data']['summary']['correction_summary']['evidence'])
    assert not presentation.proposal(job, design['settings'], {**cost, 'within_budget':False})['can_approve']
    assert not presentation.proposal(job, {**design['settings'], 'n_vaults':4}, cost)['can_approve']
    assert all(r['n_trials'] == 3 for r in job['experiments'] + job['stress'])
    n = len(job['experiments']) + len(job['stress'])
    assert tools.run_quick_design(job_id=jid) == design
    assert len(store.load(jid)['experiments']) + len(store.load(jid)['stress']) == n
    order = tools.place_synthesis_order(job_id=jid, **design['settings'])
    assert 'error' not in order, order
    summary = client.get(f'/api/jobs/{jid}').json()['dna_summary']
    lines = [line for p in (store.job_dir(jid)/'vaults').glob('*/order.fasta') for line in p.read_text().splitlines()]
    assert summary['example'] in lines
    assert summary['total_letters'] == sum(len(l) for l in lines if not l.startswith('>'))
    assert summary['total_letters'] == summary['data_letters'] + summary['manifest_letters']
    # Legacy derivation and unavailable artifacts have explicit results.
    old = store.load(jid); old.pop('dna_summary')
    assert experience.dna_summary(old) == summary
    tools.destroy_primary(job_id=jid)
    assert client.get(f'/api/jobs/{jid}/preview/{picture}').status_code == 404
    drill = tools.recover_archive(job_id=jid)
    assert drill['all_verified']
    assert client.get(f'/api/jobs/{jid}/preview/{picture}?stage=restored').content == original
    assert not client.get(f'/api/jobs/{jid}').json()['originals_available']


def test_quick_limits_and_preview_security(client):
    assert client.post('/api/jobs', data={'policy':'{}','mode':'autopilot','analysis_preset':'wrong'}).status_code == 400
    jid = new_demo(client)
    tools.prepare_archive(job_id=jid, file_names=[experience.QUICK_SAMPLE])
    bad = tools.run_codec_experiment(job_id=jid, pool_id='all',redundancy=0.9,coverage=16)
    assert 'error' in bad
    assert client.get(f'/api/jobs/{jid}/preview/unknown.png').status_code == 404
    assert client.get('/api/samples/unknown.png/preview').status_code == 404
    assert experience.preview_type('fake.png', b'<script>bad</script>') is None
    assert experience.preview_type('unsafe.svg', b'<svg/>') is None
    assert experience.preview_type('unsafe.html', b'<html/>') is None


def test_upload_names_are_optional_and_html_is_downloaded(client):
    r=client.post('/api/jobs', data={'policy':'{}','mode':'autopilot','company':'','name':''}, files={'files':('report.html',b'<script>alert(1)</script>')})
    assert r.status_code == 200
    jid=r.json()['job_id']
    assert client.get(f'/api/jobs/{jid}/preview/report.html').status_code == 415
    (store.job_dir(jid)/'restored/report.html').write_bytes(b'<script>alert(1)</script>')
    store.update(jid, lambda j: j.update(drills=[{'files':[{'name':'report.html','sha256_match':True}]}]))
    response=client.get(f'/api/jobs/{jid}/files/restored/report.html')
    assert response.headers['content-disposition'].startswith('attachment;')
    assert response.headers['x-content-type-options'] == 'nosniff'


@pytest.mark.parametrize('message,expected', [('402 prepayment credits depleted','prepaid credits'),('429 quota exceeded','usage limit'),('bad tool call','Analysis stopped')])
def test_provider_failures_explain_next_step(client, monkeypatch, message, expected):
    jid=new_demo(client)
    run=agent.Run(jid)
    def fail():
        raise RuntimeError(message)
    monkeypatch.setattr(run,'_run_agent',fail)
    run._main()
    job=store.load(jid)
    assert job['status']=='error' and job['finished']
    assert expected in job['error']
