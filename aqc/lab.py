"""Build the portable AQC experiment workbench from verified local evidence.

Only original DEVELOPMENT pools enter the interactive oracle. Historical
evaluation contributes immutable saved summaries, never simulator labels.
The browser is inspectable; this interface illustrates the oracle boundary,
while the Python process boundary remains authoritative for benchmark runs.
"""
from __future__ import annotations

import csv
import base64
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from .data import digest, sha256_file

WEB = Path(__file__).resolve().parent / "web"
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def _value(key: str, value: str | None) -> Any:
    if value is None or value == "":
        return None
    if key.endswith(("_id", "_sha256")) or key in {"policy", "kind", "behavior_signature", "equivalence_representative", "stop_reason"}:
        return value
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.lower() in {"none", "null", "nan", "inf", "-inf"}:
        return None
    if _NUMBER.fullmatch(value):
        number = float(value)
        return int(value) if re.fullmatch(r"[+-]?\d+", value) else number
    return value


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return [{key: _value(key, value) for key, value in row.items()} for row in csv.DictReader(stream)]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _development_pools(prepared: Path) -> tuple[list[dict], dict, dict]:
    """Read development references only; match feature IDs to the locked split."""
    audit = _read_json(prepared / "audit.json")
    split = _read_json(prepared / "split_manifest.json")
    unsigned = {key: value for key, value in split.items() if key != "split_sha256"}
    if digest(unsigned) != split.get("split_sha256"):
        raise ValueError("Simulator split manifest checksum mismatch")
    names = ["development_features.jsonl", "development_references.jsonl"]
    for name in names:
        if audit.get("prepared_files_sha256", {}).get(name) != sha256_file(prepared / name):
            raise ValueError(f"Simulator development input checksum mismatch: {name}")
    features = _read_lines(prepared / names[0])
    reference_rows = _read_lines(prepared / names[1])
    references = {row["molecule_id"]: row["references"] for row in reference_rows}
    assignments = {row["molecule_id"]: row for row in split["assignments"] if row["split"] == "development"}
    if len(references) != len(reference_rows) or len({row["molecule_id"] for row in features}) != len(features):
        raise ValueError("Duplicate simulator molecule")
    if set(references) != set(assignments) or {row["molecule_id"] for row in features} != set(assignments):
        raise ValueError("Simulator must contain exactly the original development molecules")
    family_rows = _read_csv(prepared / "families.csv") if (prepared / "families.csv").exists() else []
    acyclic = {row["molecule_id"] for row in family_rows if row.get("generic_scaffold") == "ACYCLIC"}
    pools = []
    for row in sorted(features, key=lambda item: item["molecule_id"]):
        identity = assignments[row["molecule_id"]]
        candidates = row["candidates"]
        refs = references[row["molecule_id"]]
        if row["family_id"] != identity["family_id"] or len(candidates) != identity["n_candidates"]:
            raise ValueError("Simulator feature pool disagrees with original split")
        ids = [candidate["candidate_id"] for candidate in candidates]
        if len(ids) != len(set(ids)) or set(ids) != set(refs):
            raise ValueError("Simulator candidate/reference IDs do not match")
        for candidate in candidates:
            if set(candidate) != {"candidate_id", "cheap_kcal"} or not math.isfinite(candidate["cheap_kcal"]):
                raise ValueError("Simulator policy features contain undeclared fields")
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in refs.values()):
            raise ValueError("Real simulator pool has incomplete references")
        pools.append({**row, "references": refs, "is_acyclic": row["molecule_id"] in acyclic})
    return pools, audit, split


def _failure_anatomy(pools: list[dict]) -> dict:
    """Evaluator-only descriptive first/second-query comparison, no policy tuning."""
    rows = []
    for pool in pools:
        ranked = sorted(pool["candidates"], key=lambda item: (item["cheap_kcal"], item["candidate_id"]))
        refs = pool["references"]
        best = min(refs, key=lambda candidate: (refs[candidate], candidate))
        first = ranked[0]["candidate_id"]
        second_best = min([row["candidate_id"] for row in ranked[:2]], key=lambda candidate: (refs[candidate], candidate))
        regret_one = max(0.0, refs[first] - refs[best])
        regret_two = max(0.0, refs[second_best] - refs[best])
        rows.append({"molecule_id": pool["molecule_id"], "family_id": pool["family_id"],
                     "is_acyclic": pool["is_acyclic"], "regret_one": regret_one,
                     "regret_two": regret_two, "regret_improvement": regret_one - regret_two,
                     "best_cheap_rank": next(index + 1 for index, row in enumerate(ranked) if row["candidate_id"] == best),
                     "rescued_on_second": regret_one > 1 + 1e-9 and regret_two <= 1 + 1e-9,
                     "second_changes_selection": second_best != first})
    return {"scope": "Original development pools; descriptive evaluator analysis",
            "n_molecules": len(rows), "first_successes": sum(row["regret_one"] <= 1 + 1e-9 for row in rows),
            "second_successes": sum(row["regret_two"] <= 1 + 1e-9 for row in rows),
            "rescued_on_second": sum(row["rescued_on_second"] for row in rows),
            "second_changes_selection": sum(row["second_changes_selection"] for row in rows),
            "acyclic_development": sum(row["is_acyclic"] for row in rows), "rows": rows}


def _geometry_view(prepared: Path, asset_path: Path | None, pools: list[dict], audit: dict, split: dict) -> dict:
    """Validate display-only development coordinates, independent of policies."""
    if asset_path is None or not asset_path.exists():
        return {"available": False, "reason": "Verified development geometry asset is not included in this build."}
    compressed = asset_path.read_bytes()
    uncompressed = gzip.decompress(compressed)
    content = json.loads(uncompressed)
    companion_path = asset_path.with_name("development_geometry_manifest.json")
    if not companion_path.exists():
        raise ValueError("Missing geometry asset checksum manifest")
    companion = _read_json(companion_path)
    if companion.get("asset_sha256") != hashlib.sha256(compressed).hexdigest() or companion.get("payload_sha256") != digest(content):
        raise ValueError("Geometry asset checksum manifest does not match its bytes")
    if companion.get("energy_labels_included") is not False or companion.get("scope") != "original_development_only":
        raise ValueError("Geometry asset manifest has an invalid display-only scope")
    expected = {(pool["molecule_id"], candidate["candidate_id"])
                for pool in pools for candidate in pool["candidates"]}
    if content.get("scope") != "original_development_only" or content.get("source_revision") != audit.get("revision"):
        raise ValueError("Geometry asset has a different scientific source or scope")
    if content.get("source_audit_sha256") != sha256_file(prepared / "audit.json") or content.get("source_split_sha256") != split["split_sha256"]:
        raise ValueError("Geometry asset source differs from simulator development inputs")
    manifest_path = prepared / "geometry_manifest.csv"
    if content.get("geometry_manifest_sha256") != sha256_file(manifest_path):
        raise ValueError("Geometry manifest checksum differs from the viewer asset")
    manifest = {(row["molecule_id"], row["conformer_id"]): row for row in _read_csv(manifest_path)}
    observed = set()
    molecule_ids = set()
    for molecule in content["molecules"]:
        molecule_id = molecule["molecule_id"]
        if molecule_id in molecule_ids:
            raise ValueError("Duplicate geometry-asset molecule")
        molecule_ids.add(molecule_id)
        for candidate in molecule["candidates"]:
            key = (molecule_id, candidate["candidate_id"])
            if key not in expected or key in observed:
                raise ValueError("Geometry viewer includes duplicate or non-development candidates")
            observed.add(key)
            symbols, coordinates = candidate["symbols"], candidate["coordinates_angstrom"]
            if not symbols or len(symbols) != len(coordinates) or any(not isinstance(symbol, str) for symbol in symbols):
                raise ValueError("Invalid viewer atom identities")
            if any(len(position) != 3 or any(type(value) not in (int, float) or not math.isfinite(value) for value in position)
                   for position in coordinates):
                raise ValueError("Invalid viewer atom coordinates")
            geometry_hash = digest({"elements_in_order": symbols, "xyz_angstrom": coordinates})
            original = manifest.get(key)
            if not original or geometry_hash != candidate["geometry_sha256"] or geometry_hash != original["geometry_sha256"]:
                raise ValueError("Viewer geometry differs from the verified candidate identity")
            if candidate["xyz_sha256"] != original["xyz_sha256"]:
                raise ValueError("Viewer XYZ checksum differs from the verified source")
    if observed != expected or molecule_ids != {pool["molecule_id"] for pool in pools}:
        raise ValueError("Geometry asset does not cover exactly the original development pools")
    if content.get("molecule_count") != len(pools) or content.get("candidate_count") != len(expected):
        raise ValueError("Geometry asset declared counts disagree with validated coordinates")
    return {"available": True, "compression": "gzip", "compressed_bytes": len(compressed),
            "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
            "molecule_count": len(pools), "candidate_count": len(expected),
            "geometry_manifest_sha256": content["geometry_manifest_sha256"],
            "asset_manifest_sha256": sha256_file(companion_path),
            "source_revision": content["source_revision"],
            "payload_gzip_base64": base64.b64encode(compressed).decode("ascii"),
            "display_only": True, "bonds": "Display-only distance inference; not a bond-order assignment"}


def build_lab(lab_results: Path, historical_results: Path, prepared: Path,
              output: Path | None = None, *, allow_pending: bool = False,
              geometry_asset: Path | None = None) -> Path:
    """Validate evidence and embed it in one dependency-free HTML workbench.

    ``allow_pending`` is an explicit preview mode: it never substitutes demo
    measurements. The completed lab requires a complete v2 artifact seal.
    """
    from .integrity import verify_artifact_seal

    lab_results, historical_results, prepared = map(Path, (lab_results, historical_results, prepared))
    history_integrity = verify_artifact_seal(historical_results)
    pending = not (lab_results / "experiment_registry.json").exists()
    if pending and not allow_pending:
        raise ValueError("Expanded experiment outputs are not available; use explicit pending preview mode")
    lab_integrity = ({"verified": False, "sealed_files": [], "warnings": ["Expanded experiment sweep pending; no new results displayed."]}
                     if pending else verify_artifact_seal(lab_results, require_complete=True))
    pools, audit, split = _development_pools(prepared)
    if geometry_asset is None and audit["dataset_kind"] == "real":
        geometry_asset = Path(__file__).resolve().parents[1] / "data" / "development_geometry.json.gz"
    geometry = _geometry_view(prepared, geometry_asset, pools, audit, split)
    loaded: list[dict] = []

    def load(directory: Path, name: str, scope: str, sealed: set[str], optional: bool = False):
        path = directory / name
        if not path.exists():
            if optional:
                return [] if name.endswith(".csv") else {}
            raise ValueError(f"Missing workbench input: {scope}/{name}")
        content = path.read_bytes()
        loaded.append({"scope": scope, "name": name, "bytes": len(content),
                       "sha256": hashlib.sha256(content).hexdigest(), "sealed": name in sealed})
        return _read_csv(path) if name.endswith(".csv") else _read_json(path)

    historical_sealed = set(history_integrity["sealed_files"])
    history = {key: load(historical_results, name, "historical", historical_sealed)
               for key, name in {"aggregate": "aggregate.csv", "decision": "decision.json", "frozen": "frozen_config.json"}.items()}
    prepared_audit_hash = sha256_file(prepared / "audit.json")
    if history["frozen"].get("audit_sha256") != prepared_audit_hash or history["frozen"].get("split_sha256") != split["split_sha256"]:
        raise ValueError("Historical choices and simulator development source differ")
    history["counts"] = split["counts"]["evaluation"]
    history["acyclic_evaluation"] = 0
    if (prepared / "families.csv").exists():
        acyclic_ids = {row["molecule_id"] for row in _read_csv(prepared / "families.csv") if row.get("generic_scaffold") == "ACYCLIC"}
        history["acyclic_evaluation"] = sum(row["split"] == "evaluation" and row["molecule_id"] in acyclic_ids for row in split["assignments"])
    experiments, registry, cross_validation = [], {}, {}
    if not pending:
        sealed = set(lab_integrity["sealed_files"])
        registry = load(lab_results, "experiment_registry.json", "development_lab", sealed)
        experiments = load(lab_results, "experiments.csv", "development_lab", sealed)
        if registry.get("source_audit_sha256") != prepared_audit_hash or registry.get("source_split_sha256") != split["split_sha256"]:
            raise ValueError("Expanded registry and simulator development source differ")
        if registry.get("prepared_files_sha256") != audit.get("prepared_files_sha256"):
            raise ValueError("Expanded registry prepared checksums differ from simulator source")
        configurations = {row["config_id"]: row for row in registry["configurations"]}
        if len(configurations) != len(registry["configurations"]) or len(experiments) != len(configurations) or set(configurations) != {row["config_id"] for row in experiments}:
            raise ValueError("Experiment registry and measured rows differ")
        if registry.get("analysis_scope") != "original_development_only":
            raise ValueError("Interactive registry must be development-only")
        for row in experiments:
            row["config"] = configurations[row["config_id"]]["config"]
            row["kind"] = configurations[row["config_id"]]["kind"]
            if row["n_molecules"] != len(pools):
                raise ValueError("Experiment row uses a different development population")
        cross_validation = {key: load(lab_results, name, "development_lab", sealed)
                            for key, name in {"aggregate": "aggregate.csv", "per_molecule": "per_molecule.csv",
                                              "paired": "paired_comparisons.csv", "decision": "decision.json",
                                              "folds": "folds.json", "choices": "fold_choices.json"}.items()}
        assignments = {row["molecule_id"]: row for row in cross_validation["folds"]["assignments"]}
        if len(assignments) != len(cross_validation["folds"]["assignments"]) or set(assignments) != {pool["molecule_id"] for pool in pools}:
            raise ValueError("Cross-validation folds differ from original development pools")
        family_folds: dict[str, set] = {}
        for pool in pools:
            assignment = assignments[pool["molecule_id"]]
            if assignment["family_id"] != pool["family_id"] or assignment["n_candidates"] != len(pool["candidates"]):
                raise ValueError("Cross-validation family differs from simulator family")
            pool["fold_id"] = assignment["fold_id"]
            family_folds.setdefault(pool["family_id"], set()).add(pool["fold_id"])
        if any(len(folds) != 1 for folds in family_folds.values()):
            raise ValueError("Chemical family crosses interactive cross-validation folds")
        if any(row["molecule_id"] not in assignments for row in cross_validation["per_molecule"]):
            raise ValueError("Non-development molecule in interactive cross-validation outcomes")
    for name in ["development_features.jsonl", "development_references.jsonl", "split_manifest.json", "audit.json"]:
        path = prepared / name
        loaded.append({"scope": "simulator_development", "name": name, "bytes": path.stat().st_size,
                       "sha256": sha256_file(path), "sealed": name in audit.get("prepared_files_sha256", {})})
    if geometry["available"]:
        loaded.append({"scope": "display_only_geometry", "name": geometry_asset.name,
                       "bytes": geometry["compressed_bytes"], "sha256": geometry["compressed_sha256"],
                       "sealed": False, "verification_status": "Viewer manifest and candidate identities checked"})
        companion = geometry_asset.with_name("development_geometry_manifest.json")
        loaded.append({"scope": "display_only_geometry", "name": companion.name,
                       "bytes": companion.stat().st_size, "sha256": geometry["asset_manifest_sha256"],
                       "sealed": False, "verification_status": "Hash recorded; declares source and asset digests"})
    payload = {"schema_version": 2, "meta": {"version": "0.2", "pending": pending, "dataset_kind": audit["dataset_kind"],
                   "scope": "original_development_only", "development_counts": split["counts"]["development"],
                   "historical_counts": split["counts"]["evaluation"], "source_revision": audit.get("revision"),
                   "expected_experiments": 1020, "original_experiments": 204},
               "experiments": experiments, "registry": registry, "cv": cross_validation,
               "historical": history, "simulator_pools": pools, "geometry": geometry,
               "failure_analysis": _failure_anatomy(pools),
               "verification": {"historical": history_integrity, "lab": lab_integrity,
                                  "geometry": {key: value for key, value in geometry.items() if key != "payload_gzip_base64"},
                                  "prepared": {"verified": True, "development_only": True,
                                               "split_sha256": split["split_sha256"],
                                               "audit_sha256": prepared_audit_hash},
                                  "files": loaded, "source_limits": audit.get("source_limits", [])}}
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = (WEB / "lab.html").read_text(encoding="utf-8")
    html = html.replace("__LAB_CSS__", (WEB / "lab.css").read_text(encoding="utf-8"))
    html = html.replace("__LAB_ENGINE__", (WEB / "lab-engine.js").read_text(encoding="utf-8"))
    viewer = WEB / "molecule-viewer.js"
    html = html.replace("__MOLECULE_VIEWER__", viewer.read_text(encoding="utf-8") if viewer.exists() else "/* Molecular renderer is not included in this build. */")
    html = html.replace("__LAB_APP__", (WEB / "lab-app.js").read_text(encoding="utf-8"))
    html = html.replace("__LAB_PAYLOAD__", encoded)
    destination = Path(output) if output is not None else lab_results / "dashboard.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8", newline="\n")
    return destination.resolve()
