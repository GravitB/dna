"""Small, factual summaries for the file-to-DNA experience."""
from pathlib import Path
from . import artifacts, store

QUICK_REDUNDANCIES = (0.8, 1.2, 1.6, 2.0)
QUICK_SAMPLE = "picture_demo.png"


def preview_type(name, data):
    suffix = Path(name).suffix.lower()
    if suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if suffix in (".jpg", ".jpeg") and data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if suffix == ".webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if suffix == ".pdf" and data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def dna_summary(job):
    if job.get("dna_summary"):
        return job["dna_summary"]
    order = job.get("order")
    if not order:
        return None
    totals = dict(data_strands=0, manifest_strands=0, data_letters=0, manifest_letters=0, example="")
    try:
        for path in order["order_files"]:
            if not path.endswith(".fasta"):
                continue
            is_manifest = False
            for line in artifacts.download(job["id"], path).decode("ascii").splitlines():
                if line.startswith(">"):
                    is_manifest = "MANIFEST" in line
                elif line.strip():
                    key = "manifest" if is_manifest else "data"
                    totals[f"{key}_strands"] += 1
                    totals[f"{key}_letters"] += len(line.strip())
                    if not is_manifest and not totals["example"]:
                        totals["example"] = line.strip()[:110]
        totals["total_letters"] = totals["data_letters"] + totals["manifest_letters"]
        return totals
    except (FileNotFoundError, ValueError, UnicodeError):
        return None


def correction(job, args):
    """Offer only a fully measured, policy-compatible alternative."""
    from . import presentation, tools
    for result in reversed(job["stress"]):
        d = result.get("design", {})
        candidate = {k: d[k] for k in ("redundancy", "coverage", "strand_length", "n_vaults", "decoder", "homopolymer_rule", "gc_rule") if k in d}
        if candidate and all(r["state"] == "passed" for r in presentation.evidence(job, candidate)):
            cost = tools.estimate_cost.__wrapped__(job["id"], **{k: v for k, v in candidate.items() if k != "decoder"})
            if presentation.proposal(job, candidate, cost)["can_approve"] and presentation.design(job, args) != d:
                return candidate
    return None
