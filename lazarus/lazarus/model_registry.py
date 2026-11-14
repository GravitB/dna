"""Server-generated, content-addressed risk models. No pickle or uploaded models."""
from __future__ import annotations
import hashlib
import io
import json
from . import artifacts, dna, store


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compatibility(policy):
    engine = dna.ERBGUT_DIR / 'dnacodec'
    source = b''.join(p.read_bytes() for p in sorted(engine.rglob('*.py')))
    return json.loads(json.dumps({'profile': dna.profile_to_dict(dna.make_profile(policy['tech'], policy['retention_years'], policy['coverage'])),
            'strand_length': 110, 'decoder': 'polish',
            'decoder_sha256': digest(dna.POLISH_CHECKPOINT.read_bytes()),
            'engine_sha256': digest(source), 'format': 'erbgut-risk-cnn-v1'}))


def register(job_id, model, evaluation):
    import torch
    if not evaluation.get('evaluated'):
        raise ValueError('Model must have a completed evaluation')
    out = io.BytesIO()
    torch.save(model._payload(), out)
    data = out.getvalue()
    model_id = digest(data)
    row = {'id': model_id, 'job_id': job_id, 'path': f'learning/models/{model_id}.pt',
           'compatibility': compatibility(store.load(job_id)['policy']),
           'evaluation': evaluation, 'created': store.now(), 'source': 'server-generated Erbgut RiskModel'}
    artifacts.publish(job_id, row['path'], data)
    store.update(job_id, lambda j: j.setdefault('models', {}).update({model_id: row}))
    return row


def load(row, policy):
    import torch
    from dnacodec.risk import RiskModel
    if row['compatibility'] != compatibility(policy):
        raise ValueError('Learned model is incompatible with this channel or decoder')
    # Resolve provenance from server state, never accept a client-provided path or model payload.
    trusted = store.load(row['job_id']).get('models', {}).get(row['id'])
    if trusted != row or not row['evaluation'].get('evaluated'):
        raise ValueError('Unregistered model')
    data = artifacts.download(row['job_id'], row['path'])
    if digest(data) != row['id']:
        raise ValueError('Model checksum mismatch')
    payload = torch.load(io.BytesIO(data), map_location='cpu', weights_only=True)
    if payload.get('kind') != 'cnn' or payload.get('state') is None:
        raise ValueError('Missing trained CNN weights')
    return RiskModel._from_payload(payload, device='cpu')


def find(policy):
    key = compatibility(policy)
    for job in store.list_jobs():
        for row in reversed(list(store.load(job['id']).get('models', {}).values())):
            if row.get('compatibility') == key and row.get('evaluation', {}).get('evaluated'):
                try:
                    load(row, policy)
                    return row
                except (ValueError, FileNotFoundError, RuntimeError):
                    continue
    return None


def summary(row):
    if row is None:
        return None
    return {k: row[k] for k in ('id', 'job_id', 'source', 'created', 'evaluation')}
