#!/usr/bin/env python3
"""Package only verified DEVELOPMENT coordinates for the offline 3D viewer.

Coordinates are a display asset. They never enter the acquisition policy or
experiment registry. Each XYZ byte hash must agree with the pinned source lock,
and each ordered geometry digest must agree with the original geometry audit.
No reference-energy table is opened by this script.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from aqc.data import REVISION, canonical_json, digest, gzip_text_writer, sha256_file, write_json


def parse_verified_xyz(raw: bytes, byte_hash: str, geometry_hash: str) -> tuple[list, list]:
    if hashlib.sha256(raw).hexdigest() != byte_hash:
        raise ValueError("Viewer XYZ bytes do not match the pinned source")
    lines = raw.decode("utf-8").splitlines()
    try:
        count = int(lines[0])
    except (IndexError, ValueError) as error:
        raise ValueError("Invalid XYZ atom count") from error
    if count < 1 or len(lines) < count + 2 or any(line.strip() for line in lines[count + 2:]):
        raise ValueError("Invalid XYZ atom record count")
    symbols, coordinates = [], []
    for line in lines[2:count + 2]:
        fields = line.split()
        if len(fields) != 4 or not re.fullmatch(r"[A-Z][a-z]?", fields[0]):
            raise ValueError("Invalid XYZ atom record")
        position = [float(value) for value in fields[1:]]
        if not all(math.isfinite(value) for value in position):
            raise ValueError("Nonfinite viewer coordinate")
        symbols.append(fields[0])
        coordinates.append(position)
    if digest({"elements_in_order": symbols, "xyz_angstrom": coordinates}) != geometry_hash:
        raise ValueError("Viewer ordered geometry does not match the original audit")
    return symbols, coordinates


def build_geometry(source: Path, prepared: Path, output: Path) -> dict:
    source, prepared, output = map(lambda path: Path(path).resolve(), (source, prepared, output))
    lock = json.loads((PROJECT / "data/upstream_lock.json").read_text(encoding="utf-8"))
    if lock["revision"] != REVISION:
        raise ValueError("Viewer source revision does not match benchmark pin")
    locked_files = {row["path"]: row for row in lock["files"]}
    split = json.loads((prepared / "split_manifest.json").read_text(encoding="utf-8"))
    if digest({key: value for key, value in split.items() if key != "split_sha256"}) != split["split_sha256"]:
        raise ValueError("Viewer split manifest checksum mismatch")
    audit = json.loads((prepared / "audit.json").read_text(encoding="utf-8"))
    features_path = prepared / "development_features.jsonl"
    if sha256_file(features_path) != audit["prepared_files_sha256"][features_path.name]:
        raise ValueError("Viewer development features changed")
    features = [json.loads(line) for line in features_path.read_text(encoding="utf-8").splitlines()]
    development = {row["molecule_id"] for row in split["assignments"] if row["split"] == "development"}
    if len(features) != len(development) or {row["molecule_id"] for row in features} != development:
        raise ValueError("Viewer contains a missing, duplicate, or non-development molecule")
    with (prepared / "geometry_manifest.csv").open(encoding="utf-8", newline="") as stream:
        geometries = list(csv.DictReader(stream))
    geometry_by_id = {(row["molecule_id"], row["conformer_id"]): row for row in geometries}
    if len(geometry_by_id) != len(geometries):
        raise ValueError("Duplicate original geometry identity")
    molecules, total_candidates, total_atoms = [], 0, 0
    for pool in sorted(features, key=lambda row: row["molecule_id"]):
        candidates = []
        ids = [candidate["candidate_id"] for candidate in pool["candidates"]]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate viewer candidate")
        for candidate_id in sorted(ids):
            identity = geometry_by_id[(pool["molecule_id"], candidate_id)]
            relative = identity["xyz_path"]
            path = (source / relative).resolve()
            if not path.is_relative_to(source) or relative not in locked_files:
                raise ValueError("Viewer geometry path is outside the locked source")
            locked = locked_files[relative]
            if locked["sha256"] != identity["xyz_sha256"]:
                raise ValueError("Original geometry audit and pinned source disagree")
            raw = path.read_bytes()
            if len(raw) != locked["size_bytes"]:
                raise ValueError("Viewer geometry byte count changed")
            symbols, coordinates = parse_verified_xyz(raw, locked["sha256"], identity["geometry_sha256"])
            if len(symbols) != int(identity["natoms"]):
                raise ValueError("Viewer atom count differs from original audit")
            candidates.append({"candidate_id": candidate_id,
                               "geometry_sha256": identity["geometry_sha256"],
                               "xyz_sha256": identity["xyz_sha256"],
                               "symbols": symbols, "coordinates_angstrom": coordinates})
            total_atoms += len(symbols)
        molecules.append({"molecule_id": pool["molecule_id"], "candidates": candidates})
        total_candidates += len(candidates)
    payload = {"schema_version": 1, "scope": "original_development_only",
               "source_revision": REVISION, "source_audit_sha256": sha256_file(prepared / "audit.json"),
               "source_split_sha256": split["split_sha256"],
               "geometry_manifest_sha256": sha256_file(prepared / "geometry_manifest.csv"),
               "development_features_sha256": sha256_file(features_path),
               "molecule_count": len(molecules), "candidate_count": total_candidates,
               "atom_records": total_atoms, "coordinate_unit": "angstrom",
               "purpose": "3D display only; never an acquisition feature or reference label",
               "bond_display": "Optional distance-inferred bonds are visual guides, not verified chemical bond orders",
               "molecules": molecules}
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip_text_writer(output) as stream:
        stream.write(canonical_json(payload) + "\n")
    manifest = {key: value for key, value in payload.items() if key != "molecules"}
    manifest.update(asset_filename=output.name, asset_sha256=sha256_file(output),
                    asset_size_bytes=output.stat().st_size, payload_sha256=digest(payload),
                    builder_sha256=sha256_file(Path(__file__)),
                    source_lock_sha256=sha256_file(PROJECT / "data/upstream_lock.json"),
                    energy_labels_included=False)
    write_json(output.with_name(output.name.removesuffix(".json.gz") + "_manifest.json"), manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--prepared", type=Path, default=PROJECT / "results/real/prepared")
    parser.add_argument("--output", type=Path, default=PROJECT / "data/development_geometry.json.gz")
    args = parser.parse_args()
    if args.source is None:
        from aqc.__main__ import acquire_source
        args.source = acquire_source(None)
    print(json.dumps(build_geometry(args.source, args.prepared, args.output), indent=2))


if __name__ == "__main__":
    main()
