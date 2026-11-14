"""Isolated training on controlled DNA; never unpickles a model or customer input."""
import json
import sys
from pathlib import Path
import numpy as np
from . import dna


def train(request, output):
    from dna_codec.risk import RiskModel, generate_strands, label_failure_rates, spearman
    output.mkdir(parents=True, exist_ok=True)
    def progress(stage, **extra):
        p = output / 'progress.tmp'
        p.write_text(json.dumps({'stage': stage, **extra}))
        p.replace(output / 'progress.json')
    profile = dna.profile_from_dict(request['profile'])
    progress('Generating 512 controlled training sequences')
    strands = generate_strands(512, length=110, seed=17001)
    progress('Measuring decoder failures', sequences=512, repeats=8)
    labels = label_failure_rates(strands, dna._polish(), profile, k=8, seed=17002, workers=1)
    progress('Training risk model', epochs=12)
    model = RiskModel(channels=24, n_blocks=2, epochs=12, patience=4, seed=17003, device='cpu')
    model.fit(strands, labels)
    progress('Evaluating risk ranking on separate controlled sequences')
    seqs = generate_strands(128, length=110, seed=18001)
    truth = label_failure_rates(seqs, dna._polish(), profile, k=8, seed=18002, workers=1)
    valid = np.isfinite(truth)
    score = model(seqs)
    corr = spearman(truth[valid], score[valid])
    model.save(output / 'risk.pt')
    report = {'evaluated': True, 'training_sequences': len(strands), 'evaluation_sequences': len(seqs),
              'repeats': 8, 'epochs_completed': len(model.history),
              'rank_correlation': float(corr) if np.isfinite(corr) else None,
              'seed_partition': 'train', 'decoder_retrained': False,
              'scope': 'Controlled synthetic sequences; customer archive validation is separate.',
              'exploratory': True, 'attribution': 'the bundled codec RiskModel and frozen CNN decoder'}
    (output / 'report.json').write_text(json.dumps(report))
    progress('Training and model evaluation completed')


if __name__ == '__main__':
    # Do not leave a training process running after its API server dies or restarts.
    import os
    import threading
    import time
    parent = os.getppid()
    def watch_parent():
        while True:
            time.sleep(1)
            if os.getppid() != parent:
                os._exit(1)
    threading.Thread(target=watch_parent, daemon=True).start()
    train(json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2]))
