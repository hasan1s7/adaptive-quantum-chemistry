#!/usr/bin/env python3
"""Split or restore byte-identical large evidence logs for repository transport.

The scientific engine and its original seal always see the original gzip file.
This transport helper does not rewrite JSON, recompress bytes, alter accounting,
or replace a mismatched local file. It uses Python's standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_PART_BYTES = 10 * 1024 * 1024


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def safe_path(root, name):
    if not isinstance(name, str) or "\\" in name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("Unsafe evidence transport path")
    result = (root / name).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Evidence transport path escapes repository")
    return result


def pack(source: Path, folder: Path, root: Path = PROJECT, part_bytes: int = DEFAULT_PART_BYTES):
    root, source, folder = root.resolve(), source.resolve(), folder.resolve()
    if part_bytes <= 0 or not source.is_relative_to(root) or not folder.is_relative_to(root):
        raise ValueError("Transport files must belong to this repository")
    if folder.exists() and any(folder.iterdir()):
        raise ValueError("Transport output must be empty")
    folder.mkdir(parents=True, exist_ok=True)
    parts = []
    with source.open("rb") as stream:
        while block := stream.read(part_bytes):
            part = folder / f"{source.name}.part{len(parts):03d}"
            part.write_bytes(block)
            parts.append({"path": part.relative_to(root).as_posix(), "size_bytes": len(block),
                          "sha256": hashlib.sha256(block).hexdigest()})
    manifest = {"schema_version": 1, "target_path": source.relative_to(root).as_posix(),
                "target_size_bytes": source.stat().st_size, "target_sha256": sha(source), "parts": parts,
                "meaning": "Lossless transport chunks; restored bytes must match the scientific run's original seal"}
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return manifest


def restore(manifest_path: Path, root: Path = PROJECT):
    root = root.resolve()
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not manifest.get("parts"):
        raise ValueError("Invalid evidence transport manifest")
    target = safe_path(root, manifest["target_path"])
    if target.exists():
        if target.stat().st_size != manifest["target_size_bytes"] or sha(target) != manifest["target_sha256"]:
            raise ValueError("Existing evidence differs; refusing to overwrite it")
        return {"status": "already_verified", "target": str(target), "sha256": sha(target)}
    names = [part["path"] for part in manifest["parts"]]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate evidence transport part")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".restoring")
    if temporary.exists():
        raise ValueError("An incomplete restoration exists; inspect it before retrying")
    try:
        with temporary.open("xb") as output:
            for part in manifest["parts"]:
                path = safe_path(root, part["path"])
                if path.stat().st_size != part["size_bytes"] or sha(path) != part["sha256"]:
                    raise ValueError(f"Transport part differs: {part['path']}")
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        output.write(block)
        if temporary.stat().st_size != manifest["target_size_bytes"] or sha(temporary) != manifest["target_sha256"]:
            raise ValueError("Restored evidence does not match the sealed original")
        temporary.replace(target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {"status": "restored_verified", "target": str(target), "sha256": sha(target)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    write = sub.add_parser("pack")
    write.add_argument("--source", type=Path, required=True)
    write.add_argument("--folder", type=Path, required=True)
    read = sub.add_parser("restore")
    read.add_argument("--manifest", type=Path, default=PROJECT / "data/evidence_chunks/lab-ledger/manifest.json")
    args = parser.parse_args()
    result = pack(args.source, args.folder) if args.action == "pack" else restore(args.manifest)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
