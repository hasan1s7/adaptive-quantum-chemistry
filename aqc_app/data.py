"""Verified development-only data for the local interface.

This module deliberately imports no scientific dependency and never opens the
historical evaluation reference file. Only this server-side object owns labels.
"""
from __future__ import annotations

import csv
import copy
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re

from aqc.oracle import policy_payload


class DataIntegrityError(ValueError):
    """A bundled input differs from its recorded scientific evidence."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def strict_json(text):
    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError(f"duplicate JSON key: {name}")
            result[name] = value
        return result
    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite JSON number")
        return number
    def reject(value):
        raise ValueError("nonfinite JSON number")
    return json.loads(text, object_pairs_hook=pairs, parse_float=finite, parse_constant=reject)


def _read_json(path):
    return strict_json(Path(path).read_text(encoding="utf-8"))


def _csv(raw):
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"), newline="")))
    for row in rows:
        for name, value in list(row.items()):
            if value == "":
                row[name] = None
            elif value in ("True", "False"):
                row[name] = value == "True"
            elif re.fullmatch(r"-?\d+", value):
                row[name] = int(value)
            elif re.fullmatch(r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value):
                number = float(value)
                if not math.isfinite(number):
                    raise DataIntegrityError("nonfinite saved CSV value")
                row[name] = number
    return rows


DEFAULT_POLICIES = [
    {"id": "sequential", "label": "Sequential reference feedback", "config": {
        "kind": "sequential", "one_gap": 0.01, "one_ratio": 0.3,
        "error_scale": 1.0, "slack": 0.25, "cap": 10}},
    {"id": "fixed", "label": "Fixed top-2", "config": {"kind": "fixed", "k": 2}},
    {"id": "adaptive", "label": "Adaptive cheap window", "config": {"kind": "adaptive", "k": 2, "gap": 0.0, "cap": 4}},
    {"id": "full", "label": "Full reference rerank", "config": {"kind": "full"}},
    {"id": "manual", "label": "Manual paid queries", "config": {"kind": "manual"}},
]

# These roles belong to the already recorded development cross-validation.
# They are not a new configuration registry or newly selected operating points.
DIAGNOSTIC_ROLES = ("sequential", "matched_simple", "fixed_top_k", "adaptive",
                    "full_rerank", "cheap_only")
DIAGNOSTIC_FIELDS = ("molecule_id", "family_id", "fold_id", "n_candidates", "policy",
                     "config_id", "expensive_calls", "regret_kcal", "success_1kcal",
                     "fallback", "stop_reason")
DIAGNOSTIC_STOPS = frozenset({
    "fixed_k_complete", "all_candidates_queried", "cheap_gap_exceeds_threshold",
    "sequential_cheap_separation_heuristic", "sequential_empirical_envelope",
    "full_rerank_complete", "full_rerank_with_failed_outputs",
    "full_rerank_fallback_failed_output", "full_rerank_fallback_crowded_at_cap",
    "full_rerank_fallback_empirical_unresolved_at_cap", "unverified_cheap_only_diagnostic",
})
DIAGNOSTIC_CASES = (
    {"id": "rescue", "molecule_id": "omegacsd_GIHTUM", "title": "Escalation helps",
     "description": "Retrospective example: sequential escalation recovered a within-1 kcal/mol decision that fixed top-2 missed."},
    {"id": "waste", "molecule_id": "astex_1xoq", "title": "Extra calls, same decision quality",
     "description": "Retrospective example: sequential queried the complete pool while fixed top-2 already had zero regret."},
    {"id": "early_stop", "molecule_id": "omegapdb_2f4j", "title": "An early stop fails",
     "description": "Retrospective example: the sequential one-query stopping rule failed the tolerance while fixed top-2 succeeded."},
    {"id": "shared_failure", "molecule_id": "omegapdb_2byi", "title": "Both heuristics miss",
     "description": "Retrospective example: sequential and fixed top-2 both missed the tolerance; the paid full rerank recovered the pool minimum."},
    {"id": "comparator_fallback", "molecule_id": "omegapdb_1yc4", "title": "The comparator falls back",
     "description": "Retrospective example: the exact fold-selected matched simple cheap-window policy fell back to all 10 queries; fixed top-2 and sequential used 2 each, all with zero regret."},
)


def _fold_metadata(pools, folds, selected, registry):
    """Check complete, family-disjoint fold assignments and frozen role choices."""
    if (folds.get("analysis_scope") != "development_family_cv" or
            selected.get("analysis_scope") != "development_family_cv" or
            selected.get("validation_labels_used_for_selection") is not False or
            type(folds.get("n_folds")) is not int or folds["n_folds"] < 2 or
            selected.get("n_folds") != folds["n_folds"]):
        raise DataIntegrityError("diagnostic fold scope differs from frozen development cross-validation")
    assignments = folds.get("assignments", [])
    if not isinstance(assignments, list) or len(assignments) != len(pools):
        raise DataIntegrityError("diagnostic fold coverage differs from development molecules")
    by_molecule, by_family = {}, {}
    for row in assignments:
        mid, family, fold = row.get("molecule_id"), row.get("family_id"), row.get("fold_id")
        pool = pools.get(mid)
        if (pool is None or mid in by_molecule or family != pool["family_id"] or
                type(fold) is not int or not 0 <= fold < folds["n_folds"] or
                row.get("n_candidates") != len(pool["candidates"])):
            raise DataIntegrityError("diagnostic fold molecule, family, or pool identity differs")
        if family in by_family and by_family[family] != fold:
            raise DataIntegrityError("a chemical family crosses diagnostic folds")
        by_molecule[mid], by_family[family] = fold, fold
    if set(by_molecule) != set(pools):
        raise DataIntegrityError("diagnostic fold coverage differs from development molecules")
    expected_folds = set(range(folds["n_folds"]))
    registered = {row["config_id"]: row["config"] for row in registry["configurations"]}
    choices = {}
    for document in (folds, selected):
        seen = set()
        for row in document.get("folds", []):
            fold = row.get("fold_id")
            if type(fold) is not int or fold not in expected_folds or fold in seen:
                raise DataIntegrityError("diagnostic fold summary is missing or duplicated")
            seen.add(fold)
            validation = {family for family, assigned in by_family.items() if assigned == fold}
            training = set(by_family) - validation
            for prefix, families in (("training", training), ("validation", validation)):
                supplied = row.get(prefix + "_family_ids")
                expected_count = sum((assigned == fold) == (prefix == "validation")
                                     for assigned in by_molecule.values())
                if (not isinstance(supplied, list) or len(supplied) != len(families) or
                        set(supplied) != families or row.get(prefix + "_families") != len(families) or
                        row.get(prefix + "_molecules") != expected_count):
                    raise DataIntegrityError("diagnostic training and validation family boundaries differ")
            if document is selected:
                roles = row.get("choices")
                if not isinstance(roles, dict) or set(roles) != set(DIAGNOSTIC_ROLES):
                    raise DataIntegrityError("diagnostic policy roles differ from frozen choices")
                for choice in roles.values():
                    if (not isinstance(choice, dict) or choice.get("config_id") not in registered or
                            choice.get("config") != registered[choice["config_id"]]):
                        raise DataIntegrityError("diagnostic policy configuration differs from its registry")
                choices[fold] = roles
        if seen != expected_folds:
            raise DataIntegrityError("diagnostic fold summary is missing or duplicated")
    return by_molecule, choices


def _diagnostic_rows(rows, pools, fold_by_molecule, choices, aggregates):
    """Validate recorded outcomes and project an explicit metrics-only schema.

    Do not copy arbitrary columns: the sealed source also holds evaluator-best
    candidate IDs and trace annotations that are intentionally not public.
    """
    expected = {(mid, role) for mid in pools for role in DIAGNOSTIC_ROLES}
    seen, clean = set(), []
    for row in rows:
        mid, role = row.get("molecule_id"), row.get("policy")
        pair = (mid, role)
        if pair not in expected or pair in seen:
            raise DataIntegrityError("diagnostic molecule/policy coverage is unknown or duplicated")
        seen.add(pair)
        pool, fold = pools[mid], fold_by_molecule[mid]
        if (row.get("analysis_scope") != "development_family_cv" or row.get("split") != "development_cv" or
                row.get("family_id") != pool["family_id"] or type(row.get("fold_id")) is not int or
                row["fold_id"] != fold or type(row.get("n_candidates")) is not int or
                row["n_candidates"] != len(pool["candidates"]) or
                row.get("config_id") != choices[fold][role]["config_id"]):
            raise DataIntegrityError("diagnostic scope, identity, or selected configuration differs")
        calls, regret = row.get("expensive_calls"), row.get("regret_kcal")
        success, fallback = row.get("success_within_1_kcal"), row.get("fallback")
        if (type(calls) is not int or not 0 <= calls <= len(pool["candidates"]) or
                type(regret) not in (int, float) or not math.isfinite(regret) or regret < 0 or
                type(success) is not bool or success != (regret <= 1.0 + 1e-9) or
                type(fallback) is not bool or row.get("stop_reason") not in DIAGNOSTIC_STOPS):
            raise DataIntegrityError("diagnostic outcome or accounting is invalid")
        paid = role != "cheap_only"
        if ((paid and calls < 1) or (not paid and calls != 0) or
                row.get("verified_selection") is not paid or
                fallback != row["stop_reason"].startswith("full_rerank_fallback_") or
                (fallback and calls != len(pool["candidates"])) or
                (role == "full_rerank" and (calls != len(pool["candidates"]) or regret != 0))):
            raise DataIntegrityError("diagnostic paid/diagnostic/full-rerank accounting differs")
        clean.append({"molecule_id": mid, "family_id": pool["family_id"], "fold_id": fold,
                      "n_candidates": len(pool["candidates"]), "policy": role,
                      "config_id": row["config_id"], "expensive_calls": calls,
                      "regret_kcal": regret, "success_1kcal": success, "fallback": fallback,
                      "stop_reason": row["stop_reason"]})
    if seen != expected:
        raise DataIntegrityError("diagnostic molecule/policy coverage is incomplete")
    summaries = {row["policy"]: row for row in aggregates}
    if len(summaries) != len(aggregates) or set(summaries) != set(DIAGNOSTIC_ROLES):
        raise DataIntegrityError("diagnostic aggregate role coverage differs")
    for role in DIAGNOSTIC_ROLES:
        group = [row for row in clean if row["policy"] == role]
        count, summary = len(group), summaries[role]
        total = sum(row["expensive_calls"] for row in group)
        actual = {"n_molecules": count, "n_families": len({row["family_id"] for row in group}),
                  "total_calls": total, "mean_calls": total / count,
                  "success_rate": sum(row["success_1kcal"] for row in group) / count,
                  "fallback_rate": sum(row["fallback"] for row in group) / count,
                  "max_regret_kcal": max(row["regret_kcal"] for row in group)}
        if summary.get("analysis_scope") != "development_family_cv" or any(
                type(summary.get(key)) not in (int, float) or
                not math.isclose(summary[key], value, rel_tol=1e-12, abs_tol=1e-12)
                for key, value in actual.items()):
            raise DataIntegrityError("diagnostic rows do not reproduce the sealed aggregate metrics")
    order = {role: index for index, role in enumerate(DIAGNOSTIC_ROLES)}
    return sorted(clean, key=lambda row: (row["molecule_id"], order[row["policy"]]))


class DevelopmentStore:
    """Immutable verified inputs; public methods never serialize reference maps."""
    EXPORT_NAMES = frozenset({"aggregate.csv", "experiments.csv", "paired_comparisons.csv", "risk_vs_calls.png"})
    SUMMARY_FILES = ("aggregate.csv", "experiments.csv", "paired_comparisons.csv", "risk_vs_calls.png",
                     "decision.json", "fold_choices.json", "folds.json", "execution_accounting.json",
                     "experiment_registry.json", "per_molecule.csv")

    def __init__(self, root=None):
        self.root = Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]
        prepared = self.root / "results" / "real" / "prepared"
        results = self.root / "results" / "lab"
        audit_path = prepared / "audit.json"
        audit = _read_json(audit_path)
        split = _read_json(prepared / "split_manifest.json")
        if digest({key: value for key, value in split.items() if key != "split_sha256"}) != split["split_sha256"]:
            raise DataIntegrityError("development split checksum differs")
        seal = _read_json(results / "evaluation_seal.json")
        if (seal.get("schema_version") != 2 or
                digest({key: value for key, value in seal.items() if key != "seal_sha256"}) != seal["seal_sha256"]):
            raise DataIntegrityError("saved experiment seal is invalid")
        self._exports = {}
        documents = {}
        for name in self.SUMMARY_FILES:
            raw = (results / name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != seal["artifact_sha256"].get(name):
                raise DataIntegrityError(f"saved experiment evidence differs: {name}")
            if name in self.EXPORT_NAMES:
                self._exports[name] = raw
            if name.endswith(".json"):
                documents[name] = strict_json(raw.decode("utf-8"))
            elif name.endswith(".csv"):
                documents[name] = _csv(raw)
        registry = documents["experiment_registry.json"]
        if (file_sha256(audit_path) != registry["source_audit_sha256"] or
                split["split_sha256"] != registry["source_split_sha256"]):
            raise DataIntegrityError("prepared development provenance differs from the registered experiment")
        for name in ("oracle.py", "policy_worker.py"):
            if file_sha256(self.root / "aqc" / name) != registry["source_code_sha256"][name]:
                raise DataIntegrityError(f"preserved scientific engine changed: {name}")
        feature_path = prepared / "development_features.jsonl"
        reference_path = prepared / "development_references.jsonl"
        for path in (feature_path, reference_path):
            if (file_sha256(path) != audit["prepared_files_sha256"][path.name] or
                    file_sha256(path) != registry["prepared_files_sha256"][path.name]):
                raise DataIntegrityError(f"development input checksum differs: {path.name}")
        features = [strict_json(line) for line in feature_path.read_text(encoding="utf-8").splitlines()]
        reference_rows = [strict_json(line) for line in reference_path.read_text(encoding="utf-8").splitlines()]
        self._pools = {pool["molecule_id"]: pool for pool in features}
        self._references = {row["molecule_id"]: row["references"] for row in reference_rows}
        assignments = {row["molecule_id"]: row for row in split["assignments"] if row["split"] == "development"}
        if (len(self._pools) != len(features) or len(self._references) != len(reference_rows) or
                set(self._pools) != set(assignments) or set(self._references) != set(assignments)):
            raise DataIntegrityError("development pools are missing, duplicated, or outside their original split")
        for molecule_id, pool in self._pools.items():
            payload = policy_payload(pool["candidates"], {"kind": "full"})
            ids = {row["candidate_id"] for row in payload["candidates"]}
            references = self._references[molecule_id]
            if (set(references) != ids or pool["family_id"] != assignments[molecule_id]["family_id"] or
                    len(ids) != assignments[molecule_id]["n_candidates"]):
                raise DataIntegrityError("development candidate identity or family mismatch")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                   for value in references.values()):
                raise DataIntegrityError("verified real development pool has a missing or invalid label")

        asset_path = self.root / "data" / "development_geometry.json.gz"
        geometry_manifest = _read_json(self.root / "data" / "development_geometry_manifest.json")
        if (file_sha256(asset_path) != geometry_manifest["asset_sha256"] or
                asset_path.stat().st_size != geometry_manifest["asset_size_bytes"]):
            raise DataIntegrityError("development geometry asset checksum differs")
        with gzip.open(asset_path, "rt", encoding="utf-8") as stream:
            geometry = strict_json(stream.read())
        if (digest(geometry) != geometry_manifest["payload_sha256"] or
                geometry["source_split_sha256"] != split["split_sha256"] or
                geometry["source_audit_sha256"] != registry["source_audit_sha256"] or
                geometry["development_features_sha256"] != file_sha256(feature_path) or
                geometry["source_revision"] != audit["revision"] or
                geometry["scope"] != "original_development_only" or
                geometry_manifest.get("energy_labels_included") is not False):
            raise DataIntegrityError("geometry asset belongs to different inputs or contains labels")
        original_geometry_path = prepared / "geometry_manifest.csv"
        if file_sha256(original_geometry_path) != geometry["geometry_manifest_sha256"]:
            raise DataIntegrityError("original geometry audit checksum differs")
        with original_geometry_path.open(encoding="utf-8", newline="") as stream:
            identities = {(row["molecule_id"], row["conformer_id"]): row for row in csv.DictReader(stream)}
        self._geometry = {}
        atom_count = candidate_count = 0
        for molecule in geometry["molecules"]:
            molecule_id = molecule["molecule_id"]
            if molecule_id not in self._pools or molecule_id in self._geometry:
                raise DataIntegrityError("geometry includes duplicate or non-development molecule")
            indexed = {}
            for candidate in molecule["candidates"]:
                cid = candidate["candidate_id"]
                identity = identities.get((molecule_id, cid))
                symbols, coordinates = candidate["symbols"], candidate["coordinates_angstrom"]
                if (cid in indexed or not identity or not symbols or len(symbols) != len(coordinates) or
                        any(not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][a-z]?", symbol) for symbol in symbols) or
                        any(not isinstance(point, list) or len(point) != 3 or
                            any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                                for value in point) for point in coordinates) or
                        digest({"elements_in_order": symbols, "xyz_angstrom": coordinates}) != candidate["geometry_sha256"] or
                        candidate["geometry_sha256"] != identity["geometry_sha256"] or
                        candidate["xyz_sha256"] != identity["xyz_sha256"]):
                    raise DataIntegrityError("display coordinates differ from the verified candidate identity")
                indexed[cid] = {key: candidate[key] for key in
                                ("candidate_id", "symbols", "coordinates_angstrom", "geometry_sha256", "xyz_sha256")}
                atom_count += len(symbols)
                candidate_count += 1
            if set(indexed) != {row["candidate_id"] for row in self._pools[molecule_id]["candidates"]}:
                raise DataIntegrityError("geometry candidate coverage differs from development features")
            self._geometry[molecule_id] = indexed
        if (set(self._geometry) != set(self._pools) or len(self._geometry) != geometry["molecule_count"] or
                candidate_count != geometry["candidate_count"] or atom_count != geometry["atom_records"]):
            raise DataIntegrityError("development geometry counts differ")
        self.counts = {"molecules": len(self._pools), "families": len({p["family_id"] for p in features}),
                       "candidates": candidate_count, "atom_records": atom_count,
                       "max_candidates_per_pool": max(len(p["candidates"]) for p in features)}
        self._fold_by_molecule, self._fold_choices = _fold_metadata(
            self._pools, documents["folds.json"], documents["fold_choices.json"], registry)
        if file_sha256(results / "folds.json") != registry["folds_sha256"]:
            raise DataIntegrityError("diagnostic folds differ from the registered experiment")
        self.provenance = {"scope": "original_development_only", "fresh_external_holdout": False,
                           "historical_reference_labels_loaded": False, "source_revision": audit["revision"],
                           "source_split_sha256": split["split_sha256"], "registry_sha256": registry["registry_sha256"],
                           "evidence_seal_sha256": seal["seal_sha256"],
                           "geometry_asset_sha256": geometry_manifest["asset_sha256"],
                           "geometry_payload_sha256": geometry_manifest["payload_sha256"],
                           "geometry_purpose": "Display only; coordinates and inferred bonds are not policy features",
                           "bond_display": geometry["bond_display"], "coordinate_unit": "angstrom",
                           "cheap_method": audit["cheap_method"], "reference_method": audit["reference_method"],
                           "energy_unit": "kcal/mol", "calls_meaning": "Offline charged reference queries; no quantum jobs",
                           "verification_scope": "Development inputs, display geometries, unchanged worker/oracle, and served summary files checked against recorded hashes; no fresh all-ledger replay at app startup"}
        self._results = {"scope": "development_family_cv", "fresh_external_holdout": False,
                         "aggregate": documents["aggregate.csv"], "experiments": documents["experiments.csv"],
                         "paired_comparisons": documents["paired_comparisons.csv"],
                         "decision": documents["decision.json"], "fold_choices": documents["fold_choices.json"],
                         "execution_accounting": documents["execution_accounting.json"],
                         "provenance": self.provenance,
                         "downloads": [{"name": name, "url": "/api/results/" + name} for name in sorted(self.EXPORT_NAMES)]}
        rows = _diagnostic_rows(documents["per_molecule.csv"], self._pools, self._fold_by_molecule,
                                self._fold_choices, documents["aggregate.csv"])
        self._diagnostics = {
            "scope": "development_family_cv_retrospective", "fresh_external_holdout": False,
            "counts": {"molecules": self.counts["molecules"], "families": self.counts["families"],
                       "candidates": self.counts["candidates"], "folds": len(self._fold_choices),
                       "rows": len(rows), "roles": len(DIAGNOSTIC_ROLES)},
            "roles": list(DIAGNOSTIC_ROLES), "rows": rows,
            "cases": copy.deepcopy(list(DIAGNOSTIC_CASES)),
            "provenance": {**self.provenance, "scope": "development_family_cv_retrospective",
                           "source_file": "results/lab/per_molecule.csv",
                           "source_sha256": seal["artifact_sha256"]["per_molecule.csv"],
                           "candidate_labels_included": False,
                           "case_selection": "Retrospectively selected illustrations from already observed development outcomes; not representative sampling or independent validation",
                           "inference": "Filtered molecule and inferred-family outcomes are descriptive; filtering does not select a newly validated policy or rerun uncertainty estimation"}}

    def _require(self, molecule_id):
        if not isinstance(molecule_id, str) or molecule_id not in self._pools:
            raise KeyError("unknown development molecule")
        return self._pools[molecule_id]

    def public_molecule(self, molecule_id):
        pool = self._require(molecule_id)
        choices = self._fold_choices[self._fold_by_molecule[molecule_id]]
        configs = {item["id"]: dict(item["config"]) for item in DEFAULT_POLICIES}
        for name, role in (("sequential", "sequential"), ("adaptive", "adaptive"), ("fixed", "fixed_top_k")):
            configs[name] = dict(choices[role]["config"])
        configs["matched_simple"] = dict(choices["matched_simple"]["config"])
        return {"molecule_id": molecule_id, "family_id": pool["family_id"],
                "fold_id": self._fold_by_molecule[molecule_id], "n_candidates": len(pool["candidates"]),
                "policy_configs": configs, "scope": "original_development_only",
                "candidates": [{**row, **self._geometry[molecule_id][row["candidate_id"]]}
                               for row in sorted(pool["candidates"], key=lambda row: (row["cheap_kcal"], row["candidate_id"]))],
                "provenance": self.provenance}

    def public_catalog(self):
        return {"scope": "original_development_only", "counts": dict(self.counts),
                "molecules": [{"molecule_id": mid, "family_id": pool["family_id"],
                               "n_candidates": len(pool["candidates"]), "fold_id": self._fold_by_molecule[mid]}
                              for mid, pool in sorted(self._pools.items())],
                "policies": DEFAULT_POLICIES, "provenance": self.provenance}

    def public_results(self):
        return self._results

    def public_diagnostics(self):
        return copy.deepcopy(self._diagnostics)

    def diagnostics_csv(self):
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=DIAGNOSTIC_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(self._diagnostics["rows"])
        return output.getvalue().encode("utf-8")

    def export(self, name):
        if name not in self.EXPORT_NAMES:
            raise KeyError("unknown summary export")
        return self._exports[name]

    def session_inputs(self, molecule_id):
        """Server-internal capability. Never pass this return value to an HTTP encoder."""
        pool = self._require(molecule_id)
        return [dict(row) for row in pool["candidates"]], dict(self._references[molecule_id])
