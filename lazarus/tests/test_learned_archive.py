"""Frozen candidates must be the exact validated, priced and ordered customer DNA."""
import hashlib
import shutil
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from lazarus import api, agent, candidates, dna, learned, model_registry, store, tools, vaults


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'JOBS_DIR', tmp_path)
    jid = store.new_job('Learned archive test', dict(tech='nanopore', retention_years=50, coverage=16,
                         budget_usd=50, target=1.0, n_vaults=3))
    data = b'Business record: a frozen candidate must restore exactly.\n' * 30
    (store.job_dir(jid) / 'uploads/record.txt').write_bytes(data)
    store.update(jid, lambda j: j.update(selected_files=['record.txt'], encoding_mode='standard'))
    tools.prepare_archive(job_id=jid, file_names=['record.txt'])
    return jid, data


@pytest.fixture
def exact_channel(monkeypatch):
    from dnacodec import simulator, simulator_b
    monkeypatch.setattr(simulator, 'simulate', lambda strands, *a: [[s] for s in strands])
    monkeypatch.setattr(simulator_b, 'simulate', lambda strands, *a: [[s] for s in strands])
    monkeypatch.setattr(dna, 'decode_clusters', lambda clusters, *a: [c[0] if c else None for c in clusters])
    monkeypatch.setattr(dna, 'sequence', lambda strands, *a, **kw: [[s] for s in strands])


def test_exact_customer_candidate_order_and_recovery_without_model_or_staging(prepared, exact_channel, monkeypatch):
    jid, data = prepared
    cid = candidates.create(jid, dna.EncoderSettings(redundancy=2.0))['id']
    frozen = candidates.load(jid, cid)
    args = candidates.proposal_args(jid, cid)
    assert not candidates.approval(jid, args)['can_approve']
    report = candidates.validate(jid, cid, trials=2)
    assert report['passed']
    assert report['seed_partition'] == 'heldout'
    assert candidates.validate(jid, cid, trials=3) == report
    assert not candidates.approval(jid, {**args, 'coverage': 20})['can_approve']
    assert not candidates.approval(jid, {**args, 'decoder': 'baseline'})['can_approve']
    assert 'error' in tools.place_synthesis_order(job_id=jid, **{**args,'coverage':20})
    # A candidate order may encode bootstrap instructions; customer pools must never be re-encoded.
    original = dna.encode_bytes
    def bootstrap_only(data, settings):
        assert len(data) == 4096
        return original(data, settings)
    monkeypatch.setattr(dna, 'encode_bytes', bootstrap_only)
    monkeypatch.setattr(tools.estimate_cost, '__wrapped__', lambda *a, **kw: pytest.fail('legacy estimation re-encodes customer files'))
    order = tools.place_synthesis_order(job_id=jid, **args)
    assert 'error' not in order
    merged = {}
    for v in range(1, 4):
        for pid, strands in vaults.read_vault(store.job_dir(jid), v).items():
            if pid != 'MANIFEST': merged.setdefault(pid, {}).update(strands)
    for pid, pool in frozen['pools'].items():
        assert [merged[pid][i] for i in range(len(merged[pid]))] == pool['strands']
    assert order['cost']['bases'] == store.load(jid)['dna_summary']['total_letters']
    tools.destroy_primary(job_id=jid)
    shutil.rmtree(store.job_dir(jid) / 'candidates')
    result = tools.recover_archive(job_id=jid)
    assert result['all_verified']
    assert (store.job_dir(jid) / 'restored/record.txt').read_bytes() == data


def test_candidate_rejects_policy_metadata_and_corrupt_strands(prepared):
    jid, _ = prepared
    cid = candidates.create(jid, dna.EncoderSettings(redundancy=1.6))['id']
    original = store.load(jid)
    store.update(jid, lambda j: j['sealed']['record.txt'].update(offset=7))
    with pytest.raises(ValueError, match='inputs'): candidates.load(jid, cid)
    store.save(jid, original)
    store.update(jid, lambda j: j['policy'].update(budget_usd=0.01))
    with pytest.raises(ValueError, match='inputs'): candidates.load(jid, cid)
    store.save(jid, original)
    (store.job_dir(jid) / f'candidates/{cid}.json').write_bytes(b'{}')
    with pytest.raises(ValueError, match='checksum'): candidates.load(jid, cid)


def test_failed_final_evidence_cannot_be_rerolled(prepared, monkeypatch):
    jid, _ = prepared
    cid = candidates.create(jid, dna.EncoderSettings(redundancy=1.6))['id']
    monkeypatch.setattr(dna, 'decode_clusters', lambda clusters, *a: [None] * len(clusters))
    report = candidates.validate(jid, cid, trials=1)
    assert not report['passed']
    monkeypatch.setattr(dna, 'decode_clusters', lambda *a: pytest.fail('must not re-roll'))
    assert candidates.validate(jid, cid, trials=5) == report
    assert not candidates.approval(jid, candidates.proposal_args(jid,cid))['can_approve']


def fitted_model():
    from dnacodec.risk import RiskModel
    # Fast real fit exercises safe serialization. Full experiment is separately recorded.
    model = RiskModel(channels=8, n_blocks=1, epochs=1, device='cpu')
    return model.fit(['ACGT' * 28, 'A' * 110, 'G' * 110, 'AT' * 55], np.array([0.,1.,.8,.3]))


def test_model_registry_safe_roundtrip_compatibility_and_checksum(prepared):
    jid, _ = prepared
    model = fitted_model()
    row = model_registry.register(jid, model, {'evaluated':True, 'scope':'controlled synthetic test'})
    policy = store.load(jid)['policy']
    loaded = model_registry.load(row, policy)
    assert np.allclose(model(['ACGT'*28]), loaded(['ACGT'*28]))
    assert model_registry.find(policy)['id'] == row['id']
    with pytest.raises(ValueError, match='incompatible'):
        model_registry.load(row, {**policy, 'coverage':8})
    with pytest.raises(ValueError, match='Unregistered'):
        model_registry.load({**row,'source':'uploaded file'}, policy)
    (store.job_dir(jid) / row['path']).write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='checksum'): model_registry.load(row, policy)
    assert model_registry.find(policy) is None


def test_no_model_requires_explicit_choice_and_standard_never_trains(prepared, monkeypatch):
    jid, _ = prepared
    monkeypatch.setattr(learned, 'train', lambda *a: pytest.fail('standard may not train'))
    assert tools.prepare_learned_model(job_id=jid)['mode'] == 'standard'
    store.update(jid, lambda j: j.update(encoding_mode='evaluated'))
    assert 'error' in tools.prepare_learned_model(job_id=jid)
    monkeypatch.setattr(agent, 'start', lambda *a: None)
    with TestClient(api.app) as c:
        r=c.post('/api/jobs', data={'mode':'autopilot','encoding_mode':'evaluated','policy':'{}'}, files={'files':('a.txt',b'a')})
        assert r.status_code == 409
        assert c.post(f'/api/jobs/{jid}/learning/cancel').status_code == 409


def test_selection_does_not_choose_using_heldout(prepared, monkeypatch):
    jid, _ = prepared
    result = learned.compare(jid, trials=1)
    # No final seed is used for either screening design.
    assert result['selection_partition'] == 'train'
    assert all(c['screening']['seed_partition']=='train' for c in result['candidates'])
    monkeypatch.setattr(candidates, 'create', lambda *a: pytest.fail('selection must stay frozen'))
    assert learned.compare(jid, trials=5) == result


def test_interrupted_final_validation_is_not_restarted(prepared):
    jid, _ = prepared
    cid=candidates.create(jid,dna.EncoderSettings(redundancy=1.6))['id']
    store.update(jid,lambda j:j['candidates'][cid].update(validation={'state':'running'}))
    with pytest.raises(ValueError,match='interrupted'): candidates.validate(jid,cid)


def test_cancel_terminates_worker_and_records_no_model(prepared, monkeypatch):
    import subprocess
    import sys
    import threading
    import time
    jid, _ = prepared
    original = subprocess.Popen
    spawned=[]
    def sleeper(*a, **kw):
        proc=original([sys.executable,'-c','import time; time.sleep(60)'], **kw)
        spawned.append(proc)
        return proc
    monkeypatch.setattr(learned.subprocess, 'Popen', sleeper)
    result=[]
    worker=threading.Thread(target=lambda: result.append(learned.train(jid)))
    worker.start()
    end=time.monotonic()+5
    while jid not in learned._active and time.monotonic()<end:
        time.sleep(.01)
    learned.cancel(jid)
    worker.join(timeout=8)
    assert not worker.is_alive()
    assert result == [None]
    assert store.load(jid)['learning_state']['status']=='canceled'
    assert not store.load(jid).get('models')
    assert all(p.poll() is not None for p in spawned)


# The actual Supabase HTTP adapter is tested against a private-storage protocol double.
from test_supabase import cloud


def test_learned_cloud_order_recovers_on_empty_machine_without_model(cloud, tmp_path, monkeypatch, exact_channel):
    from lazarus import artifacts
    client, protocol = cloud
    policy=dict(tech='nanopore',retention_years=50,coverage=16,budget_usd=50,target=1.,n_vaults=3)
    jid=store.new_job('Frozen learned cloud',policy)
    original=b'An encrypted company record, restored on a new machine.'*70
    d=store.job_dir(jid)
    (d/'uploads/record.txt').write_bytes(original)
    store.update(jid,lambda j:j.update(selected_files=['record.txt'],encoding_mode='fresh'))
    tools.prepare_archive(job_id=jid,file_names=['record.txt'])
    model=fitted_model()
    row=model_registry.register(jid,model,{'evaluated':True,'scope':'controlled synthetic test'})
    cid=candidates.create(jid,dna.EncoderSettings(redundancy=2.),model_registry.load(row,policy),row)['id']
    frozen=candidates.load(jid,cid)
    assert candidates.validate(jid,cid,trials=1)['passed']
    args=candidates.proposal_args(jid,cid)
    assert tools.place_synthesis_order(job_id=jid,**args)['candidate_id']==cid
    for v in range(1,4):
        remote=artifacts.download(jid,f'vaults/vault-{v}/order.fasta').decode()
        for pid,pool in frozen['pools'].items():
            for index,seq in enumerate(pool['strands']):
                if index % 3 == v-1: assert f'>{pid}|{index}\n{seq}\n' in remote
    tools.destroy_primary(job_id=jid)
    shutil.rmtree(d)
    monkeypatch.setattr(store,'JOBS_DIR',tmp_path/'empty-computer')
    store._versions.clear()
    monkeypatch.setattr(model_registry,'load',lambda *a:pytest.fail('recovery must not load learned model'))
    vaults.destroy_vault(store.job_dir(jid),2)
    restored=tools.recover_archive(job_id=jid)
    assert restored['all_verified']
    assert restored['vaults_available']==[1,3]
    assert artifacts.download(jid,'restored/record.txt') == original


def test_approval_rejects_missing_or_modified_evidence_and_over_budget(prepared, exact_channel):
    jid,_=prepared
    cid=candidates.create(jid,dna.EncoderSettings(redundancy=2.))['id']
    args=candidates.proposal_args(jid,cid)
    assert candidates.validate(jid,cid,trials=1)['passed']
    assert candidates.approval(jid,args)['can_approve']
    path=store.job_dir(jid)/store.load(jid)['candidates'][cid]['validation_path']
    original=path.read_bytes()
    path.write_bytes(b'{}')
    assert not candidates.approval(jid,args)['can_approve']
    path.write_bytes(original)
    # A different budget belongs to a new candidate, never stale passing evidence.
    store.update(jid,lambda j:j['policy'].update(budget_usd=.01))
    cid2=candidates.create(jid,dna.EncoderSettings(redundancy=2.))['id']
    assert candidates.validate(jid,cid2,trials=1)['passed']
    assert not candidates.approval(jid,candidates.proposal_args(jid,cid2))['can_approve']


def test_server_restart_marks_learning_interrupted(prepared, monkeypatch):
    jid,_=prepared
    store.update(jid,lambda j:j.update(learning_state={'status':'running','message':'Training'}))
    with TestClient(api.app):
        assert store.load(jid)['learning_state']['status']=='interrupted'
    store.update(jid,lambda j:j.update(encoding_mode='fresh'))
    monkeypatch.setattr(learned,'train',lambda *a:pytest.fail('interrupted training needs an explicit new archive'))
    assert 'error' in tools.prepare_learned_model(job_id=jid)


def test_auto_search_increases_reads_before_using_final_seeds(prepared, monkeypatch):
    jid,_=prepared
    seen=[]
    real_validate=candidates.validate
    def screening(jid,cid,trials,**kw):
        assert not kw['heldout'] and kw['safety_margin']
        assert trials >= 6
        c=candidates.load(jid,cid)
        reads=c['planned_coverage']
        seen.append(reads)
        return {'passed':reads>16, 'seed_partition':'train','scenarios':[]}
    monkeypatch.setattr(candidates,'validate',screening)
    result=learned.compare(jid)
    assert 16 in seen and 24 in seen
    args=candidates.proposal_args(jid,result['selected_id'])
    assert args['coverage']==24
    assert store.load(jid)['policy']['coverage']==16
    frozen=candidates.load(jid,result['selected_id'])
    assert candidates.archive_manifest(store.load(jid),result['selected_id'],frozen)['channel']['planned_coverage']==24
    assert result['screening_trials']==6
    # Existing final-test calls still reserve held-out seeds for one independent evaluation.
    monkeypatch.setattr(candidates,'validate',real_validate)


def test_adjusted_reads_are_bound_to_approval_and_cost(prepared, exact_channel):
    jid,_=prepared
    s=dna.EncoderSettings(redundancy=2.)
    cid=candidates.create(jid,s,coverage=24)['id']
    base=candidates.create(jid,s,coverage=16)['id']
    assert candidates.cost(jid,cid)['read_usd'] > candidates.cost(jid,base)['read_usd']
    assert candidates.validate(jid,cid,trials=1)['passed']
    args=candidates.proposal_args(jid,cid)
    assert candidates.approval(jid,args)['can_approve']
    assert not candidates.approval(jid,{**args,'coverage':16})['can_approve']
    assert tools.place_synthesis_order(job_id=jid,**args)['settings']['coverage']==24
    assert candidates.load(jid,cid)['policy']==store.load(jid)['policy']
