#!/usr/bin/env python3
"""Fetch pinned oxView source/runtime assets and prepare its isolated Lazarus embed."""

import concurrent.futures
import hashlib
import json
import re
import urllib.request
from urllib.parse import quote
from pathlib import Path

COMMIT = "6993bc982cf4e9d4b4962545e8627c77bfc3bfd8"
REPO = "https://raw.githubusercontent.com/sulcgroup/oxdna-viewer/" + COMMIT + "/"
ROOT = Path(__file__).resolve().parents[1] / "web/public/oxview"


def main():
    tree = json.load(
        urllib.request.urlopen(
            "https://api.github.com/repos/sulcgroup/oxdna-viewer/git/trees/"
            + COMMIT
            + "?recursive=1"
        )
    )["tree"]
    selected = [
        f
        for f in tree
        if f["type"] == "blob"
        and (
            f["path"].startswith(("dist/", "ts/", "css/", "mif/", "favicons/"))
            or (f["path"].startswith("img/") and f["size"] < 50000)
            or f["path"]
            in (
                "index.html",
                "LICENSE",
                "README.md",
                "file-format.md",
                "tsconfig.json",
                "package.json",
                "renderer.js",
                "favicon.png",
            )
        )
    ]
    ROOT.mkdir(parents=True, exist_ok=True)

    def fetch(f):
        path = ROOT / f["path"]
        data = path.read_bytes() if path.exists() else b""
        def digest(b):
            return hashlib.sha1(f"blob {len(b)}\0".encode() + b).hexdigest()
        if digest(data) != f["sha"]:
            data = urllib.request.urlopen(REPO + quote(f["path"]), timeout=30).read()
            if digest(data) != f["sha"]:
                raise ValueError("Pinned source checksum mismatch: " + f["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return {"path": f["path"], "sha256": hashlib.sha256(data).hexdigest()}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        manifest = list(pool.map(fetch, selected))
    original = (ROOT / "index.html").read_text()
    (ROOT / "upstream-index.html").write_text(original)
    # Keep the full upstream DOM required by oxView, but hide editing UI in the embed.
    text = re.sub(
        r"<script\b[^>]*>[\s\S]*?</script>",
        lambda m: ""
        if ("googletagmanager" in m[0] or "gtag(" in m[0] or "api.nanobase.org" in m[0])
        else m[0],
        original,
    )
    text = text.replace(
        "<head>",
        """<head>
<!-- Lazarus embed modifications: tracking and external import UI disabled; local read-only bridge. -->
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'none'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'none'">
<link rel="stylesheet" href="./lazarus.css">""",
    )
    text = text.replace('<script src="./dist/UI/keybindings.js"></script>', "")
    text = re.sub(r'<img[^>]+src="https?://[^"]+"[^>]*>', "", text)
    text = text.replace("</body>", '<script src="./lazarus-bridge.js"></script></body>')
    (ROOT / "index.html").write_text(text)
    # Prevent upstream's generic file/script message interface from accepting outside messages.
    path = ROOT / "dist/main.js"
    text = path.read_text()
    text = text.replace(
        "if (event.data.message) {",
        "if (event.source === window.parent && event.origin === location.origin && event.data.message) {",
    )
    path.write_text(text)
    (ROOT / "UPSTREAM.json").write_text(
        json.dumps(
            {
                "repository": "https://github.com/sulcgroup/oxdna-viewer",
                "commit": COMMIT,
                "license": "GPL-3.0-or-later",
                "files": manifest,
            },
            indent=2,
        )
        + "\n"
    )
    print("Pinned oxView runtime and source files:", len(selected))


if __name__ == "__main__":
    main()
