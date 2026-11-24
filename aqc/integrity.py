"""Fail-closed verification of saved evidence before a user interface reads it.

Seals detect accidental changes and mixed runs. They are content integrity
records, not cryptographic signatures or attestations from an external auditor.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path, PurePosixPath

SEAL_NAME = "evaluation_seal.json"
PRIMARY_FILES = {"aggregate.csv", "per_molecule.csv", "paired_comparisons.csv", "decision.json"}
GENERATED_VIEWS = {"dashboard.html"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode("utf-8")).hexdigest()


def _hash(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _path(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("Unsafe artifact path in seal")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or str(relative) != name:
        raise ValueError("Unsafe artifact path in seal")
    path = root.joinpath(*relative.parts)
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Artifact path escapes run directory")
    return path


def _read_json(path):
    def invalid(value):
        raise ValueError(f"Nonfinite JSON number: {value}")
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=invalid)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid or missing evidence file: {Path(path).name}") from exc


def _csv(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        if not fields or len(set(fields)) != len(fields):
            raise ValueError(f"Invalid CSV header: {Path(path).name}")
        rows = list(reader)
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError(f"Malformed CSV row: {Path(path).name}")
    return rows


def _number(value, name):
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid numeric evidence: {name}") from exc
    if not math.isfinite(result):
        raise ValueError(f"Nonfinite numeric evidence: {name}")
    return result


def _integer(value, name):
    result = _number(value, name)
    if result != int(result) or result < 0:
        raise ValueError(f"Invalid nonnegative integer: {name}")
    return int(result)


def _boolean(value):
    if value is True or value == "True" or value == "true":
        return True
    if value is False or value == "False" or value == "false":
        return False
    raise ValueError("Invalid Boolean evidence")


def _close(actual, expected, name):
    if not math.isclose(_number(actual, name), expected, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError(f"Evidence inconsistency: {name}")


def _quantile(values, p):
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    left = int(index)
    return ordered[left] + (ordered[min(left + 1, len(ordered) - 1)] - ordered[left]) * (index - left)


def _validate_tables(root: Path):
    if not (root / "per_molecule.csv").is_file() or not (root / "aggregate.csv").is_file():
        raise ValueError("Sealed evidence requires per-molecule and aggregate tables")
    rows, aggregate = _csv(root / "per_molecule.csv"), _csv(root / "aggregate.csv")
    groups, keys = defaultdict(list), {}
    required = {"policy", "molecule_id", "family_id", "n_candidates", "regret_kcal",
                "expensive_calls", "fallback", "selected_candidate", "stop_reason"}
    for row in rows:
        if not required <= set(row):
            raise ValueError("Incomplete per-molecule evidence schema")
        key = (row["policy"], row["molecule_id"])
        if key in keys:
            raise ValueError("Duplicate molecule/policy evidence")
        keys[key] = row
        n = _integer(row["n_candidates"], "n_candidates")
        calls = _integer(row["expensive_calls"], "expensive_calls")
        regret = _number(row["regret_kcal"], "regret_kcal")
        if not n or regret < -1e-9 or calls > n:
            raise ValueError("Invalid candidate count, call accounting, or regret")
        verified = _boolean(row.get("verified_selection", row["policy"] != "cheap_only"))
        if verified and (calls < 1 or not row["selected_candidate"]):
            raise ValueError("Paid selection lacks a verified query")
        if not verified and calls:
            raise ValueError("Unverified diagnostic has paid calls")
        if "success_within_1_kcal" in row and _boolean(row["success_within_1_kcal"]) != (regret <= 1 + 1e-9):
            raise ValueError("Success flag disagrees with regret")
        _boolean(row["fallback"])
        groups[row["policy"]].append(row)
    if not rows or set(groups) != {r["policy"] for r in aggregate} or len(aggregate) != len(groups):
        raise ValueError("Aggregate policy set does not match molecule evidence")
    pool_sets = [{(r["molecule_id"], r["family_id"], r["n_candidates"]) for r in group}
                 for group in groups.values()]
    if any(pool != pool_sets[0] for pool in pool_sets[1:]):
        raise ValueError("Policies were not evaluated on identical pools")
    by_policy = {}
    for summary in aggregate:
        policy = summary["policy"]
        group = groups[policy]
        regrets = [_number(r["regret_kcal"], "regret") for r in group]
        total = sum(_integer(r["expensive_calls"], "calls") for r in group)
        expected = {"n_molecules": len(group), "n_families": len({r["family_id"] for r in group}),
                    "total_calls": total, "mean_calls": total / len(group),
                    "success_rate": sum(v <= 1 + 1e-9 for v in regrets) / len(group),
                    "median_regret_kcal": _quantile(regrets, .5),
                    "p95_regret_kcal": _quantile(regrets, .95), "max_regret_kcal": max(regrets),
                    "fallback_rate": sum(_boolean(r["fallback"]) for r in group) / len(group)}
        for name, value in expected.items():
            if name in summary:
                _close(summary[name], value, f"{policy}.{name}")
        by_policy[policy] = expected
    decision, primary, comparator = None, None, None
    decision_path = root / "decision.json"
    if decision_path.exists():
        decision = _read_json(decision_path)
        comparator = decision.get("primary_comparator", "fixed_top_k")
        primary = decision.get("primary_policy", "adaptive")
        if primary not in by_policy or comparator not in by_policy or comparator == "cheap_only":
            raise ValueError("Decision must name observed paid primary and comparator policies")
        if primary == "cheap_only":
            raise ValueError("Unverified diagnostic cannot be the primary paid policy")
        if primary in by_policy and comparator in by_policy:
            a, b = by_policy[primary], by_policy[comparator]
            for name, value in {"primary_success_rate": a["success_rate"],
                                f"{primary}_success_rate": a["success_rate"],
                                "baseline_success_rate": b["success_rate"],
                                "comparator_success_rate": b["success_rate"],
                                "relative_call_savings": 1 - a["total_calls"] / b["total_calls"]}.items():
                if name in decision:
                    _close(decision[name], value, f"decision.{name}")
            risk_ok, comparator_ok = a["success_rate"] >= .95, b["success_rate"] >= .95
            no_worse = a["success_rate"] + 1e-12 >= b["success_rate"]
            saving_ok = 1 - a["total_calls"] / b["total_calls"] >= .30
            expected_flags = {
                "observed_95pct_success_met": risk_ok,
                "frozen_comparator_95pct_success_met": comparator_ok,
                "target_risk_comparison_available": risk_ok and comparator_ok,
                "observed_risk_no_worse_than_frozen_comparator": no_worse,
                "observed_30pct_call_savings_met": saving_ok,
                "observed_joint_target_met": risk_ok and comparator_ok and no_worse and saving_ok,
            }
            for name, value in expected_flags.items():
                if name in decision and (type(decision[name]) is not bool or decision[name] != value):
                    raise ValueError(f"Evidence inconsistency: decision.{name}")
    pair_path = root / "paired_comparisons.csv"
    if pair_path.exists():
        pair_rows, pair_keys = _csv(pair_path), set()
        for row in pair_rows:
            if row.get("policy") not in by_policy or row.get("comparator") not in by_policy:
                raise ValueError("Paired comparison references an absent policy")
            pair_key = (row["policy"], row["comparator"])
            if pair_key in pair_keys or row["comparator"] == "cheap_only":
                raise ValueError("Duplicate paired comparison or unverified denominator")
            pair_keys.add(pair_key)
            a, b = by_policy[row["policy"]], by_policy[row["comparator"]]
            for name, value in {"delta_success_rate": a["success_rate"] - b["success_rate"],
                                "delta_mean_calls": a["mean_calls"] - b["mean_calls"],
                                "relative_call_savings": 1 - a["total_calls"] / b["total_calls"]}.items():
                if name in row:
                    _close(row[name], value, f"paired.{name}")
        if decision is not None and "paired_difference" in decision:
            matches = [row for row in pair_rows if row["policy"] == primary and row["comparator"] == comparator]
            embedded = decision["paired_difference"]
            if len(matches) != 1 or not isinstance(embedded, dict):
                raise ValueError("Decision paired difference has no matching comparison")
            match = matches[0]
            for name, value in embedded.items():
                if name not in match:
                    raise ValueError("Decision paired difference introduces an unknown statistic")
                if type(value) in (int, float):
                    _close(match[name], value, f"decision.paired_difference.{name}")
                elif match[name] != ("" if value is None else str(value)):
                    raise ValueError(f"Evidence inconsistency: decision.paired_difference.{name}")
            summary_rows = {row["policy"]: row for row in aggregate}
            for name in ("all_marginal_interval_checks_pass", "bootstrap_joint_evidence"):
                if name in decision:
                    bounds = (summary_rows[primary].get("success_rate_ci_low"),
                              summary_rows[comparator].get("success_rate_ci_low"),
                              match.get("delta_success_rate_ci_low"),
                              match.get("relative_call_savings_ci_low"))
                    expected = all(value not in (None, "") for value in bounds) and all(
                        _number(value, name) >= threshold
                        for value, threshold in zip(bounds, (.95, .95, 0, .30)))
                    if type(decision[name]) is not bool or decision[name] != expected:
                        raise ValueError(f"Evidence inconsistency: decision.{name}")
    return keys


def _validate_primary_traces(root, keys):
    path = root / "traces.jsonl"
    if not path.exists():
        return
    seen = set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            trace = json.loads(line)
            key = (trace["policy"], trace["molecule_id"])
            if key in seen or key not in keys:
                raise ValueError("Query traces do not match decision rows")
            seen.add(key)
            row, result = keys[key], trace["result"]
            queries = result["queries"]
            calls = sum(_integer(q["charged"], "query charge") for q in queries)
            _close(result["expensive_calls"], calls, "trace calls")
            _close(row["expensive_calls"], calls, "decision query calls")
            if result["selected_candidate"] != row["selected_candidate"] or result["stop_reason"] != row["stop_reason"]:
                raise ValueError("Trace selection/stop reason differs from decision")
            if "query_order" in row and json.loads(row["query_order"]) != [q["candidate_id"] for q in queries]:
                raise ValueError("Trace query order differs from decision")
            observed = {q["candidate_id"]: _number(q["reference_kcal"], "reference")
                        for q in queries if "reference_kcal" in q}
            if calls and (not observed or result["selected_candidate"] != min(observed, key=lambda c: (observed[c], c))):
                raise ValueError("Trace did not return its best verified candidate")
    if seen != set(keys):
        raise ValueError("Missing primary query traces")


def verify_artifact_seal(directory: Path, require_complete: bool = False) -> dict:
    """Verify immutable bytes and primary derived tables, or raise ValueError.

    Historical v1 seals cover five primary artifacts. V2 seals cover every
    generated evidence file; the derived dashboard itself is excluded.
    """
    root = Path(directory).resolve()
    seal = _read_json(root / SEAL_NAME)
    if not isinstance(seal, dict):
        raise ValueError("Malformed evaluation seal")
    version = seal.get("schema_version", 1)
    hashes = seal.get("artifact_sha256")
    if version not in {1, 2} or not isinstance(hashes, dict) or not PRIMARY_FILES <= set(hashes):
        raise ValueError("Evaluation seal is incomplete or unsupported")
    if version == 2:
        expected = dict(seal)
        supplied = expected.pop("seal_sha256", None)
        if supplied != _digest(expected):
            raise ValueError("Evaluation seal content changed")
    for name, sha in hashes.items():
        path = _path(root, name)
        if not isinstance(sha, str) or len(sha) != 64 or not path.is_file() or _hash(path) != sha:
            raise ValueError(f"Sealed artifact changed or missing: {name}")
    warnings = []
    actual_files = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
                    and p.name not in GENERATED_VIEWS and p.name != SEAL_NAME}
    unsealed = sorted(actual_files - set(hashes))
    if require_complete and (version != 2 or unsealed):
        raise ValueError("Complete evidence seal required; files are unsealed")
    if version == 1:
        warnings.append("Historical v0.1 seal verifies primary outcomes only; supplementary views have narrower integrity coverage.")
    if unsealed:
        warnings.append(f"{len(unsealed)} auxiliary files are outside this seal.")
    config_path = root / "frozen_config.json"
    if config_path.exists():
        frozen = _read_json(config_path)
        expected = dict(frozen)
        supplied = expected.pop("config_sha256", None)
        if _digest(expected) != supplied or seal.get("config_sha256") != supplied:
            raise ValueError("Frozen configuration does not match evaluation seal")
    split_path = root / "split_manifest.json"
    if split_path.exists():
        split = _read_json(split_path)
        expected = dict(split)
        supplied = expected.pop("split_sha256", None)
        if supplied is not None and _digest(expected) != supplied:
            raise ValueError("Split manifest content changed")
        if seal.get("split_sha256") and supplied != seal["split_sha256"]:
            raise ValueError("Split manifest does not match evaluation seal")
    try:
        keys = _validate_tables(root)
        _validate_primary_traces(root, keys)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Malformed evidence: {exc}") from exc
    return {"verified": True, "seal_schema_version": version, "sealed_files": sorted(hashes),
            "warnings": warnings, "unsealed_files": unsealed, "primary_rows_verified": len(keys),
            "seal_sha256": _hash(root / SEAL_NAME),
            "meaning": "Content integrity and internal consistency; not an external attestation or a population risk guarantee."}


def write_artifact_seal(directory: Path, filenames=None, config_sha256=None,
                        split_sha256=None, schema_version=2) -> dict:
    root = Path(directory).resolve()
    if schema_version != 2:
        raise ValueError("New runs require a complete v2 evidence seal")
    if filenames is None:
        filenames = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
                     and p.name not in GENERATED_VIEWS and p.name != SEAL_NAME]
    files = sorted(set(filenames))
    seal = {"schema_version": 2, "artifact_sha256": {name: _hash(_path(root, name)) for name in files}}
    if config_sha256 is not None:
        seal["config_sha256"] = config_sha256
    if split_sha256 is not None:
        seal["split_sha256"] = split_sha256
    seal["seal_sha256"] = _digest(seal)
    (root / SEAL_NAME).write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    verify_artifact_seal(root, require_complete=True)
    return seal
