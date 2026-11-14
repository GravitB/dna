"""Isolated the bundled codec research worker; learned codecs are experimental, never silently deployed."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path


def experiment(request: dict, output: Path) -> dict:
    from dna_codec import results
    from dna_codec.loop import LoopConfig, run_loop
    from . import dna

    output.mkdir(parents=True, exist_ok=True)
    # This module runs in a dedicated process: redirect upstream's global output safely.
    results.RESULTS_DIR = output / "results"
    profile = dna.profile_from_dict(request["profile"])
    config = LoopConfig.quick_mode(workers=1) if request["quick"] else LoopConfig(workers=1)
    config = replace(config, target=request["target"])
    result = run_loop(profile, "learning", config=config,
                      decoder=dna._polish(), max_iterations=2,
                      store_root=output / "codecs")
    report = {
        "status": "completed", "quick": config.quick,
        "scope": "the bundled codec fixed research test file; not validation of the customer archive",
        "decoder": "polish", "decoder_retrained": False,
        "learned_risk_selection": True, "deployed_to_archive": False,
        "result": result.to_dict(),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    import sys
    import logging
    logging.basicConfig(level=logging.INFO)
    experiment(json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2]))
