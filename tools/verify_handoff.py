#!/usr/bin/env python3
"""Verify an extracted Erkidu handoff snapshot; no experiment or network access."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = json.loads((root / "HANDOFF_MANIFEST.json").read_text())
    for name, record in manifest["files"].items():
        path = (root / name).resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError("Missing or unsafe manifest path: " + name)
        data = path.read_bytes()
        if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("Handoff file mismatch: " + name)
    bundle = (root / "Erkidu-Result-Bundle.json").read_bytes()
    expected = manifest["integrated_bundle"]
    if len(bundle) != expected["bytes"] or hashlib.sha256(bundle).hexdigest() != expected["sha256"]:
        raise ValueError("Integrated result bundle mismatch")
    print(json.dumps({"verified": True, "files": len(manifest["files"]),
                      "integrated_bundle_verified": True,
                      "base_commit": manifest["base_commit"], "executed_policies": 0}, indent=2))


if __name__ == "__main__":
    main()
