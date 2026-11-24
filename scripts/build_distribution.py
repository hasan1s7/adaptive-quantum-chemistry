#!/usr/bin/env python3
"""Package a verified Git index plus the restored, sealed replay ledger.

The caller verifies the supplied source commit/tree against the remote repo.
This script checks the index tree, every working file's Git blob identity,
and the restored ledger, then writes a deterministic ZIP and file manifest.
It needs only Git and Python's standard library. It never includes .git,
the Python environment, caches, or untracked files other than the ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for value in (args.source_commit, args.source_tree):
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            parser.error("Source commit and tree must be complete lowercase Git SHAs")
    if git("write-tree").decode().strip() != args.source_tree:
        parser.error("Git index does not match the verified source tree")
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(ROOT):
        parser.error("Choose a new archive path outside the repository")

    entries = []
    for record in git("ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, blob, stage = metadata.decode().split()
        name = raw_path.decode("utf-8")
        path = ROOT / name
        if stage != "0" or mode not in ("100644", "100755") or path.is_symlink():
            raise ValueError("Unsupported or unresolved tracked entry: " + name)
        content = path.read_bytes()
        identity = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if identity != blob:
            raise ValueError("Working file differs from the staged source: " + name)
        entries.append({"path": name, "mode": mode, "size_bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(), "git_blob": blob})

    transport = json.loads((ROOT / "data/evidence_chunks/lab-ledger/manifest.json").read_text())
    ledger = ROOT / transport["target_path"]
    if ledger.stat().st_size != transport["target_size_bytes"] or sha256_file(ledger) != transport["target_sha256"]:
        raise ValueError("Restored ledger differs from its recorded seal")
    if any(entry["path"] == transport["target_path"] for entry in entries):
        raise ValueError("The restored ledger is unexpectedly tracked")
    tracked_count = len(entries)
    entries.append({"path": transport["target_path"], "mode": "100644",
                    "size_bytes": transport["target_size_bytes"], "sha256": transport["target_sha256"]})
    entries.sort(key=lambda entry: entry["path"])
    manifest = {"schema_version": 1, "version": "0.4.0",
                "repository": "hasan1s7/adaptive-quantum-chemistry",
                "source_commit": args.source_commit, "source_tree": args.source_tree,
                "tracked_files": tracked_count, "restored_ledger_included": True,
                "manifest_excludes_itself": True, "files": entries}
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for entry in entries + [{"path": "DISTRIBUTION.json", "mode": "100644"}]:
                name = entry["path"]
                content = ((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
                           if name == "DISTRIBUTION.json" else (ROOT / name).read_bytes())
                if name != "DISTRIBUTION.json" and hashlib.sha256(content).hexdigest() != entry["sha256"]:
                    raise ValueError("File changed during packaging: " + name)
                info = zipfile.ZipInfo("adaptive-quantum-chemistry/" + name, (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = int(entry["mode"], 8) << 16
                archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    print(json.dumps({"archive": str(output), "size_bytes": output.stat().st_size,
                      "sha256": sha256_file(output), "source_commit": args.source_commit,
                      "source_tree": args.source_tree, "tracked_files": tracked_count,
                      "bundled_files": len(entries) + 1}, indent=2))


if __name__ == "__main__":
    main()
