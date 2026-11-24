"""Registered acquisition experiments on the ORIGINAL DEVELOPMENT cohort only.

Every fixed configuration is replayed once per development molecule through the
hidden-label oracle. Five family-blocked outer folds choose operating points on
their other four folds. The old final-evaluation cohort is never loaded here.
The resulting cross-validation is internal development evidence, not a new
external holdout. Cached *completed outcomes* may be reused for fold selection
because no configuration fits parameters across molecules.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.metadata
import json
import math
import platform
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from .data import (canonical_json, digest, gzip_text_writer, load_pools,
                   sha256_file, write_csv, write_json)
from .oracle import Oracle, PolicyExecutionError, PolicySession
from .statistics import paired_comparisons, plot_risk_calls, summarize


TARGET_SUCCESS = .95
TARGET_SAVINGS = .30
SUCCESS_TOLERANCE = 1e-9
FOLD_COUNT = 5
ORIGINAL_GAPS = (0., .1, .25, .5, 1., 2., 4., 8.)
ORIGINAL_CAPS = (2, 4, 6, 8, 10)
ORIGINAL_INITIAL_K = (1, 2, 3, 4, 6, 8, 10)
ONE_GAPS = (0., .01, .025, .05, .1, .15, .2, .3, .4, .5, .75, 1., 1.5, 2., 3., 4., 8.)
ONE_RATIOS = (0., .05, .15, .3)
ERROR_SCALES = (1., 2., 4.)
SEQUENTIAL_CAPS = (2, 4, 6, 10)
SLACK = .25
ROLE_ORDER = ("full_rerank", "fixed_top_k", "adaptive", "sequential", "matched_simple", "cheap_only")
CORE_RESULT_FIELDS = ("selected_candidate", "queries", "expensive_calls", "observations")
CONDITIONAL_INTERVAL_NOTE = (
    "Descriptive family bootstrap within fixed outer folds, conditional on the selected fold policies. "
    "Does not reselect configurations, account for overlapping training sets, or establish a joint "
    "95% confidence guarantee. This is development cross-validation, not a fresh external holdout."
)


def build_configurations(max_candidates: int = 10) -> list[dict[str, Any]]:
    """204 original + 816 distinct sequential parameterizations for pools <=10."""
    if type(max_candidates) is not int or max_candidates < 1:
        raise ValueError("max_candidates must be a positive integer")
    result = []

    def add(name, config, generation):
        result.append({"config_id": name, "kind": config["kind"], "config": config,
                       "generation": generation})

    for k in range(1, max(10, max_candidates) + 1):
        add(f"fixed_k_{k:02}", {"kind": "fixed", "k": k}, "original")
    for k in ORIGINAL_INITIAL_K:
        for cap in ORIGINAL_CAPS:
            if cap < k:
                continue
            for gap in ORIGINAL_GAPS:
                add(f"adaptive_k{k:02}_gap{gap:g}_cap{cap:02}",
                    {"kind": "adaptive", "k": k, "gap": gap, "cap": cap}, "original")
    add("full_rerank", {"kind": "full"}, "original")
    add("cheap_only", {"kind": "diagnostic"}, "original")
    for gap in ONE_GAPS:
        for ratio in ONE_RATIOS:
            for scale in ERROR_SCALES:
                for cap in SEQUENTIAL_CAPS:
                    add(f"sequential_gap{gap:g}_ratio{ratio:g}_error{scale:g}_cap{cap:02}",
                        {"kind": "sequential", "one_gap": gap, "one_ratio": ratio,
                         "error_scale": scale, "cap": cap, "slack": SLACK}, "new")
    if len({entry["config_id"] for entry in result}) != len(result):
        raise ValueError("duplicate configuration IDs")
    if len({canonical_json(entry["config"]) for entry in result}) != len(result):
        raise ValueError("parameter-identical configurations in registry")
    return result


def make_family_folds(pools: list[dict], seed: int = 1729, n_folds: int = FOLD_COUNT) -> dict:
    """Assign families using identifiers only; no energy values enter this function."""
    if type(n_folds) is not int or n_folds < 2:
        raise ValueError("at least two family folds required")
    ids = [pool["molecule_id"] for pool in pools]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate molecule in fold input")
    families = sorted({pool["family_id"] for pool in pools},
                      key=lambda f: hashlib.sha256(f"{seed}|{f}".encode()).hexdigest())
    if len(families) < n_folds:
        raise ValueError("fewer families than outer folds")
    family_fold = {family: index % n_folds for index, family in enumerate(families)}
    assignments = [{"molecule_id": pool["molecule_id"], "family_id": pool["family_id"],
                    "fold_id": family_fold[pool["family_id"]], "n_candidates": len(pool["candidates"])}
                   for pool in sorted(pools, key=lambda p: p["molecule_id"])]
    folds = []
    for fold_id in range(n_folds):
        training = [a for a in assignments if a["fold_id"] != fold_id]
        validation = [a for a in assignments if a["fold_id"] == fold_id]
        folds.append({"fold_id": fold_id,
                      "training_molecules": len(training), "validation_molecules": len(validation),
                      "training_families": len({a["family_id"] for a in training}),
                      "validation_families": len({a["family_id"] for a in validation}),
                      "training_family_ids": sorted({a["family_id"] for a in training}),
                      "validation_family_ids": sorted({a["family_id"] for a in validation})})
    result = {"schema_version": 2, "analysis_scope": "development_family_cv", "seed": seed,
              "n_folds": n_folds,
              "rule": "Sort original-development families by SHA256(seed|family_id); assign round-robin to outer folds",
              "assignments": assignments, "folds": folds}
    validate_family_folds(result, pools)
    return result


def validate_family_folds(folds: dict, pools: list[dict]) -> None:
    expected = {pool["molecule_id"]: pool for pool in pools}
    seen = set()
    family_fold = {}
    counts = Counter()
    for row in folds["assignments"]:
        molecule = row["molecule_id"]
        if molecule in seen or molecule not in expected:
            raise ValueError("duplicate or unknown molecule in family folds")
        seen.add(molecule)
        pool = expected[molecule]
        if row["family_id"] != pool["family_id"] or row["n_candidates"] != len(pool["candidates"]):
            raise ValueError("fold metadata does not match fixed pool")
        fold = row["fold_id"]
        if type(fold) is not int or not 0 <= fold < folds["n_folds"]:
            raise ValueError("invalid outer fold")
        previous = family_fold.setdefault(row["family_id"], fold)
        if previous != fold:
            raise ValueError("chemical family leaks across folds")
        counts[fold] += 1
    if seen != set(expected) or set(counts) != set(range(folds["n_folds"])):
        raise ValueError("family folds do not cover every pool exactly once")
    if len(folds["folds"]) != folds["n_folds"]:
        raise ValueError("incorrect fold-summary count")
    for info in folds["folds"]:
        fold = info["fold_id"]
        validation_families = sorted(f for f, assigned in family_fold.items() if assigned == fold)
        training_families = sorted(f for f, assigned in family_fold.items() if assigned != fold)
        if (info["validation_family_ids"] != validation_families
                or info["training_family_ids"] != training_families
                or info["validation_molecules"] != counts[fold]
                or info["training_molecules"] != len(pools) - counts[fold]
                or info["validation_families"] != len(validation_families)
                or info["training_families"] != len(training_families)):
            raise ValueError("fold summary disagrees with assignments")


def _source_hashes() -> dict[str, str]:
    return {path.name: sha256_file(path) for path in sorted(Path(__file__).parent.glob("*.py"))
            if path.name not in {"dashboard.py", "lab.py"}}


def _metrics(regrets, calls, fallbacks, candidate_counts, family_ids, policy) -> dict:
    if len(regrets) == 0:
        raise ValueError("empty training or validation cohort")
    return {"policy": policy, "n_molecules": int(len(regrets)), "n_families": len(set(family_ids)),
            "success_rate": float(np.mean(regrets <= 1 + SUCCESS_TOLERANCE)),
            "median_regret_kcal": float(np.median(regrets)),
            "p95_regret_kcal": float(np.quantile(regrets, .95, method="linear")),
            "max_regret_kcal": float(np.max(regrets)), "mean_calls": float(np.mean(calls)),
            "total_calls": int(np.sum(calls)), "mean_call_fraction": float(np.mean(calls / candidate_counts)),
            "fallback_rate": float(np.mean(fallbacks))}


def _empty_outcomes(n_configs: int, n_pools: int) -> dict[str, np.ndarray]:
    return {"regrets": np.full((n_configs, n_pools), np.nan, dtype=float),
            "calls": np.full((n_configs, n_pools), -1, dtype=np.int32),
            "fallbacks": np.zeros((n_configs, n_pools), dtype=bool)}


def training_statistics(configurations, outcomes, pools, folds, validation_fold) -> dict[str, dict]:
    """Only training slices cross into the configuration-selection functions."""
    fold_of = {a["molecule_id"]: a["fold_id"] for a in folds["assignments"]}
    training = np.asarray([i for i, pool in enumerate(pools)
                           if fold_of[pool["molecule_id"]] != validation_fold], dtype=int)
    counts = np.asarray([len(pools[i]["candidates"]) for i in training], dtype=float)
    families = [pools[i]["family_id"] for i in training]
    return {entry["config_id"]: _metrics(outcomes["regrets"][i, training], outcomes["calls"][i, training],
                                       outcomes["fallbacks"][i, training], counts, families, entry["config_id"])
            for i, entry in enumerate(configurations)}


def choose_from_training(configurations: list[dict], metrics: dict[str, dict]) -> dict[str, dict]:
    """Pure selection from TRAINING metrics; this API receives no validation rows."""
    configs = {entry["config_id"]: entry for entry in configurations}

    def choice(kinds, minimum_success, explicit=None):
        if explicit:
            candidates = [configs[explicit]]
        else:
            candidates = [entry for entry in configurations if entry["kind"] in kinds
                          and metrics[entry["config_id"]]["success_rate"] + 1e-12 >= minimum_success]
        fallback = not candidates
        if fallback:
            entry = configs["full_rerank"]
        else:
            entry = min(candidates, key=lambda e: (
                metrics[e["config_id"]]["total_calls"], metrics[e["config_id"]]["p95_regret_kcal"],
                -metrics[e["config_id"]]["success_rate"], e["config_id"]))
        return {"config_id": entry["config_id"], "kind": entry["kind"], "config": entry["config"],
                "training_metrics": metrics[entry["config_id"]], "minimum_training_success": minimum_success,
                "selection_fallback": fallback}

    selected = {"full_rerank": choice({"full"}, 1., "full_rerank"),
                "fixed_top_k": choice({"fixed"}, TARGET_SUCCESS),
                "adaptive": choice({"adaptive"}, TARGET_SUCCESS),
                "sequential": choice({"sequential"}, TARGET_SUCCESS),
                "cheap_only": choice({"diagnostic"}, 0., "cheap_only")}
    matching_target = max(TARGET_SUCCESS, selected["sequential"]["training_metrics"]["success_rate"])
    selected["matched_simple"] = choice({"fixed", "adaptive", "full"}, matching_target)
    return {role: selected[role] for role in ROLE_ORDER}


def select_fold_choices(configurations, outcomes, pools, folds) -> dict:
    choices = []
    for info in folds["folds"]:
        training = training_statistics(configurations, outcomes, pools, folds, info["fold_id"])
        choices.append({**info, "choices": choose_from_training(configurations, training)})
    return {"schema_version": 2, "analysis_scope": "development_family_cv", "n_folds": folds["n_folds"],
            "primary_policy": "sequential", "primary_comparator": "matched_simple", "folds": choices,
            "selection_rule": "Training success >=95%; then minimum total calls, p95 regret, negative success, config ID",
            "matching_rule": "Cheapest original fixed/window/full rule with training success >=max(95%, selected sequential training success)",
            "validation_labels_used_for_selection": False}


def split_trace(pool: dict, result: dict) -> tuple[dict, dict]:
    """Deduplicate full charged-query cores; retain ALL remaining fields in ledger."""
    core = {"molecule_id": pool["molecule_id"], "family_id": pool["family_id"],
            "cheap_candidates": pool["candidates"],
            "result": {key: result[key] for key in CORE_RESULT_FIELDS}}
    annotations = {key: value for key, value in result.items() if key not in CORE_RESULT_FIELDS}
    return core, annotations


def reconstruct_trace(core: dict, annotations: dict) -> dict:
    if set(core["result"]) & set(annotations):
        raise ValueError("ledger annotations overwrite charged-query trace fields")
    return {**core, "result": {**core["result"], **annotations}}


def _behavior_bytes(pool: dict, result: dict) -> bytes:
    # Reasons/envelope thresholds may differ despite identical acquisition behavior.
    return (canonical_json({"molecule_id": pool["molecule_id"],
                            "selected_candidate": result["selected_candidate"],
                            "queries": [{key: event[key] for key in ("candidate_id", "charged", "status")}
                                        for event in result["queries"]]}) + "\n").encode()


def _evaluate_result(pool, config, session):
    if config["kind"] == "diagnostic":
        selected = min(pool["candidates"], key=lambda c: (c["cheap_kcal"], c["candidate_id"]))["candidate_id"]
        return {"selected_candidate": selected, "queries": [], "observations": {}, "expensive_calls": 0,
                "fallback": False, "stop_reason": "unverified_cheap_only_diagnostic", "policy_events": []}
    return session.run(pool["candidates"], pool["references"], config)


def _failure_record(entry, pool, error):
    record = {"config_id": entry["config_id"], "molecule_id": pool["molecule_id"],
              "family_id": pool["family_id"], "status": "policy_execution_failure",
              "queries": error.queries, "expensive_calls": error.expensive_calls,
              "error": str(error)}
    for name in ("failure_stage", "cause_type", "cleanup_errors", "worker_stderr", "policy_events", "observations"):
        if hasattr(error, name):
            record[name] = getattr(error, name)
    return record


def _ledger_row(pool, entry, result, trace_hash, annotations, fold_id):
    references = pool["references"]
    best = min(references, key=lambda cid: (references[cid], cid))
    selected = result["selected_candidate"]
    regret = max(0., references[selected] - references[best])
    return {"config_id": entry["config_id"], "molecule_id": pool["molecule_id"], "family_id": pool["family_id"],
            "fold_id": fold_id, "n_candidates": len(pool["candidates"]), "selected_candidate": selected,
            "best_pool_candidate": best, "regret_kcal": regret, "success_within_1_kcal": regret <= 1 + SUCCESS_TOLERANCE,
            "expensive_calls": result["expensive_calls"], "fallback": result["fallback"],
            "stop_reason": result["stop_reason"], "query_order": [q["candidate_id"] for q in result["queries"]],
            "verified_selection": entry["kind"] != "diagnostic", "trace_sha256": trace_hash,
            "result_annotations": annotations}


def _execute_registry(configurations, pools, folds, out):
    outcomes = _empty_outcomes(len(configurations), len(pools))
    family_ids = [pool["family_id"] for pool in pools]
    counts = np.asarray([len(pool["candidates"]) for pool in pools], dtype=float)
    fold_of = {a["molecule_id"]: a["fold_id"] for a in folds["assignments"]}
    seen_traces = set()
    behavior_representatives = {}
    experiment_rows = []
    total_calls = 0
    with (gzip_text_writer(out / "trace_catalog.jsonl.gz") as catalog,
          gzip_text_writer(out / "decision_ledger.jsonl.gz") as ledger,
          PolicySession() as session):
        for config_index, entry in enumerate(configurations):
            behavior_hash = hashlib.sha256()
            for molecule_index, pool in enumerate(pools):
                try:
                    result = _evaluate_result(pool, entry["config"], session)
                except PolicyExecutionError as error:
                    # Keep failed paid attempts and abort; do not silently drop them.
                    failure = _failure_record(entry, pool, error)
                    ledger.write(canonical_json(failure) + "\n")
                    ledger.flush()
                    write_json(out / "run_status.json", failure)
                    raise
                core, annotations = split_trace(pool, result)
                trace_hash = digest(core)
                if trace_hash not in seen_traces:
                    catalog.write(canonical_json({"trace_sha256": trace_hash, "trace": core}) + "\n")
                    seen_traces.add(trace_hash)
                record = _ledger_row(pool, entry, result, trace_hash, annotations, fold_of[pool["molecule_id"]])
                ledger.write(canonical_json(record) + "\n")
                outcomes["regrets"][config_index, molecule_index] = record["regret_kcal"]
                outcomes["calls"][config_index, molecule_index] = record["expensive_calls"]
                outcomes["fallbacks"][config_index, molecule_index] = record["fallback"]
                total_calls += record["expensive_calls"]
                behavior_hash.update(_behavior_bytes(pool, result))
            signature = behavior_hash.hexdigest()
            representative = behavior_representatives.setdefault(signature, entry["config_id"])
            metrics = _metrics(outcomes["regrets"][config_index], outcomes["calls"][config_index],
                               outcomes["fallbacks"][config_index], counts, family_ids, entry["config_id"])
            experiment_rows.append({"config_id": entry["config_id"], "kind": entry["kind"],
                                    "generation": entry["generation"],
                                    "analysis_scope": "pooled_original_development_descriptive",
                                    **{parameter: entry["config"].get(parameter) for parameter in
                                       ("k", "gap", "cap", "one_gap", "one_ratio", "error_scale", "slack")},
                                    **metrics, "behavior_signature": signature,
                                    "equivalence_representative": representative})
            if (config_index + 1) % 10 == 0 or config_index + 1 == len(configurations):
                ledger.flush()
                catalog.flush()
                print(f"experiments: {config_index + 1}/{len(configurations)} configs; "
                      f"{(config_index + 1) * len(pools)} independent replays; {total_calls} charged jobs", flush=True)
    write_csv(out / "experiments.csv", experiment_rows)
    return outcomes, {"configuration_count": len(configurations), "molecule_count": len(pools),
                      "decision_count": len(configurations) * len(pools), "charged_jobs": total_calls,
                      "unique_query_trace_count": len(seen_traces),
                      "unique_behavior_signature_count": len(behavior_representatives),
                      "behavior_definition": "Same ordered query IDs/statuses/charges and selected candidate for every development molecule; stopping explanations may differ",
                      "deduplication_scope": "Storage only: each configuration/pool was independently executed and charged"}


def _read_jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _select_oof_rows(out, pools, folds, choices):
    fold_choices = {row["fold_id"]: row["choices"] for row in choices["folds"]}
    wanted = {}
    for assignment in folds["assignments"]:
        for role, choice in fold_choices[assignment["fold_id"]].items():
            wanted.setdefault((choice["config_id"], assignment["molecule_id"]), []).append(role)
    rows = []
    selected_records = {}
    for entry in _read_jsonl_gz(out / "decision_ledger.jsonl.gz"):
        key = (entry["config_id"], entry["molecule_id"])
        if key not in wanted:
            continue
        selected_records[key] = entry
        for role in wanted[key]:
            row = {key: value for key, value in entry.items() if key != "result_annotations"}
            row.update(policy=role, split="development_cv", analysis_scope="development_family_cv",
                       query_order=canonical_json(entry["query_order"]),
                       trace_annotations=canonical_json(entry["result_annotations"]),
                       selection_fallback=fold_choices[entry["fold_id"]][role]["selection_fallback"])
            rows.append(row)
    if set(selected_records) != set(wanted):
        raise ValueError("missing selected configuration/pool ledger rows")
    rows.sort(key=lambda row: (row["policy"], row["molecule_id"]))
    if len(rows) != len(pools) * len(ROLE_ORDER):
        raise ValueError("out-of-fold policy coverage is incomplete")
    write_csv(out / "per_molecule.csv", rows)
    return rows, selected_records


def _load_catalog(out):
    catalog = {}
    for entry in _read_jsonl_gz(out / "trace_catalog.jsonl.gz"):
        trace_hash = entry["trace_sha256"]
        if trace_hash in catalog or digest(entry["trace"]) != trace_hash:
            raise ValueError("duplicate or invalid trace catalog hash")
        catalog[trace_hash] = entry["trace"]
    return catalog


def load_recorded_trace(out: Path, molecule_id: str, config_id: str) -> dict:
    """Reconstruct one complete acquisition trace for the local read-only lab."""
    record = next((row for row in _read_jsonl_gz(Path(out) / "decision_ledger.jsonl.gz")
                   if row["molecule_id"] == molecule_id and row["config_id"] == config_id), None)
    if record is None:
        raise KeyError((molecule_id, config_id))
    core = next((row["trace"] for row in _read_jsonl_gz(Path(out) / "trace_catalog.jsonl.gz")
                 if row["trace_sha256"] == record["trace_sha256"]), None)
    if core is None or digest(core) != record["trace_sha256"]:
        raise ValueError("recorded trace is absent or corrupt")
    return {"config_id": config_id, "fold_id": record["fold_id"],
            **reconstruct_trace(core, record["result_annotations"])}


def _replay_selected(pools, configurations, selected_records, catalog, out):
    by_pool = {pool["molecule_id"]: pool for pool in pools}
    by_config = {entry["config_id"]: entry for entry in configurations}
    count = calls = 0
    with gzip_text_writer(out / "verification_replays.jsonl.gz") as stream, PolicySession() as session:
        for key in sorted(selected_records):
            record = selected_records[key]
            try:
                result = _evaluate_result(by_pool[key[1]], by_config[key[0]]["config"], session)
            except PolicyExecutionError as error:
                failure = _failure_record(by_config[key[0]], by_pool[key[1]], error)
                failure["verification_stage"] = "independent_selected_policy_replay"
                failure["expected_trace_sha256"] = record["trace_sha256"]
                stream.write(canonical_json(failure) + "\n")
                stream.flush()
                write_json(out / "run_status.json", failure)
                raise
            expected = reconstruct_trace(catalog[record["trace_sha256"]], record["result_annotations"])["result"]
            matched = canonical_json(result) == canonical_json(expected)
            stream.write(canonical_json({"config_id": key[0], "molecule_id": key[1],
                                        "expected_trace_sha256": record["trace_sha256"],
                                        "result": result, "matched": matched}) + "\n")
            if not matched:
                stream.flush()
                raise ValueError(f"independent selected-policy replay differs: {key}")
            count += 1
            calls += result["expensive_calls"]
    return {"selected_unique_replays": count, "verification_charged_jobs": calls,
            "replay_scope": "Selected out-of-fold configurations rerun independently; no retuning"}


def _same_number(actual, expected, label):
    if not math.isclose(float(actual), float(expected), rel_tol=1e-11, abs_tol=1e-9):
        raise ValueError(f"saved statistic disagrees with audited decisions: {label}")


def _validate_catalog_core(core, pool):
    if core["family_id"] != pool["family_id"] or canonical_json(core["cheap_candidates"]) != canonical_json(pool["candidates"]):
        raise ValueError("trace catalog does not match cheap feature pool")
    result = core["result"]
    oracle = Oracle([candidate["candidate_id"] for candidate in pool["candidates"]], pool["references"])
    for recorded in result["queries"]:
        try:
            oracle.query(recorded["candidate_id"])
        except ValueError:
            pass
        if canonical_json(oracle.events[-1]) != canonical_json(recorded):
            raise ValueError("recorded oracle event differs from candidate/reference/accounting contract")
    if result["queries"]:
        oracle.validate_selected(result["selected_candidate"])
    else:
        best_cheap = min(pool["candidates"], key=lambda c: (c["cheap_kcal"], c["candidate_id"]))["candidate_id"]
        if result["selected_candidate"] != best_cheap:
            raise ValueError("zero-query diagnostic does not select cheapest candidate")
    if result["expensive_calls"] != oracle.expensive_calls or result["observations"] != oracle.observations:
        raise ValueError("trace query accounting or reference reveals disagree")


def _check_run_identity(prepared, out, registry):
    from .benchmark import verify_prepared
    audit, split = verify_prepared(prepared)
    copy = dict(registry)
    saved = copy.pop("registry_sha256")
    if digest(copy) != saved:
        raise ValueError("experiment registry changed after registration")
    if registry["source_code_sha256"] != _source_hashes():
        raise ValueError("scientific source changed after experiment registration")
    if (registry["source_audit_sha256"] != sha256_file(prepared / "audit.json")
            or registry["source_split_sha256"] != split["split_sha256"]
            or registry["prepared_files_sha256"] != audit["prepared_files_sha256"]
            or registry["folds_sha256"] != sha256_file(out / "folds.json")):
        raise ValueError("data or family assignments changed after experiment registration")
    return audit, split


def verify_experiment_run(prepared: Path, out: Path, replay_selected: bool = False) -> dict:
    """Read-only audit of every decision, all summaries, fold choices and replays.

    Optional fresh selected-policy replays must exactly reproduce their already
    recorded verification traces. They never tune or replace saved outcomes.
    """
    prepared, out = Path(prepared), Path(out)
    registry = json.loads((out / "experiment_registry.json").read_text())
    _check_run_identity(prepared, out, registry)
    pools = sorted(load_pools(prepared, "development"), key=lambda pool: pool["molecule_id"])
    configurations = registry["configurations"]
    folds = json.loads((out / "folds.json").read_text())
    validate_family_folds(folds, pools)
    expected_configurations = build_configurations(max(len(pool["candidates"]) for pool in pools))
    if canonical_json(configurations) != canonical_json(expected_configurations):
        raise ValueError("registered configurations differ from the prespecified grid")
    if canonical_json(folds) != canonical_json(make_family_folds(pools, registry["fold_seed"])):
        raise ValueError("fold assignments differ from their registered deterministic rule")
    if len(configurations) != registry["configuration_count"]:
        raise ValueError("registered configuration count mismatch")
    if len({canonical_json(entry["config"]) for entry in configurations}) != len(configurations):
        raise ValueError("registry contains identical parameterizations")
    config_index = {entry["config_id"]: i for i, entry in enumerate(configurations)}
    pool_index = {pool["molecule_id"]: i for i, pool in enumerate(pools)}
    if len(config_index) != len(configurations) or len(pool_index) != len(pools):
        raise ValueError("duplicate configuration or pool IDs")
    catalog = _load_catalog(out)
    for core in catalog.values():
        if core["molecule_id"] not in pool_index:
            raise ValueError("unknown molecule in trace catalog")
        _validate_catalog_core(core, pools[pool_index[core["molecule_id"]]])
    outcomes = _empty_outcomes(len(configurations), len(pools))
    seen = np.zeros((len(configurations), len(pools)), dtype=np.uint8)
    counts = np.asarray([len(pool["candidates"]) for pool in pools], dtype=float)
    family_ids = [pool["family_id"] for pool in pools]
    fold_of = {a["molecule_id"]: a["fold_id"] for a in folds["assignments"]}
    choices = json.loads((out / "fold_choices.json").read_text())
    by_fold = {fold["fold_id"]: fold["choices"] for fold in choices["folds"]}
    selected_keys = {(choice["config_id"], assignment["molecule_id"])
                     for assignment in folds["assignments"] for choice in by_fold[assignment["fold_id"]].values()}
    selected_records = {}
    behavior_hashes = [hashlib.sha256() for _ in configurations]
    used_traces = set()
    ledger_count = charged_jobs = 0
    for record in _read_jsonl_gz(out / "decision_ledger.jsonl.gz"):
        if record.get("status") == "policy_execution_failure":
            raise ValueError("experiment run contains an aborted policy execution")
        key = (record["config_id"], record["molecule_id"])
        if key[0] not in config_index or key[1] not in pool_index:
            raise ValueError("unknown config or molecule in decision ledger")
        ci, mi = config_index[key[0]], pool_index[key[1]]
        if seen[ci, mi]:
            raise ValueError("duplicate config/molecule decision")
        seen[ci, mi] = 1
        pool, config = pools[mi], configurations[ci]
        trace_hash = record["trace_sha256"]
        if trace_hash not in catalog or catalog[trace_hash]["molecule_id"] != key[1]:
            raise ValueError("decision refers to wrong or absent trace")
        used_traces.add(trace_hash)
        result = reconstruct_trace(catalog[trace_hash], record["result_annotations"])["result"]
        expected = _ledger_row(pool, config, result, trace_hash, record["result_annotations"], fold_of[key[1]])
        if canonical_json(expected) != canonical_json(record):
            raise ValueError("ledger decision differs from trace/reference regret/fold assignment")
        if config["kind"] != "diagnostic" and record["expensive_calls"] < 1:
            raise ValueError("paid configuration has no charged job")
        if config["kind"] == "diagnostic" and record["expensive_calls"] != 0:
            raise ValueError("unverified diagnostic was charged")
        outcomes["regrets"][ci, mi] = record["regret_kcal"]
        outcomes["calls"][ci, mi] = record["expensive_calls"]
        outcomes["fallbacks"][ci, mi] = record["fallback"]
        behavior_hashes[ci].update(_behavior_bytes(pool, result))
        ledger_count += 1
        charged_jobs += record["expensive_calls"]
        if key in selected_keys:
            selected_records[key] = record
    if not bool(np.all(seen == 1)) or used_traces != set(catalog):
        raise ValueError("configuration/pool coverage or trace catalog coverage is incomplete")
    if set(selected_records) != selected_keys:
        raise ValueError("selected configuration records are missing")
    recomputed_choices = select_fold_choices(configurations, outcomes, pools, folds)
    if canonical_json(recomputed_choices) != canonical_json(choices):
        raise ValueError("fold choices differ from training-only selection")
    with (out / "experiments.csv").open(newline="", encoding="utf-8") as stream:
        experiments = list(csv.DictReader(stream))
    if len(experiments) != len(configurations):
        raise ValueError("experiment table does not contain every registered configuration")
    representatives = {}
    for ci, (entry, record) in enumerate(zip(configurations, experiments)):
        if record["config_id"] != entry["config_id"]:
            raise ValueError("experiment table registry order/IDs changed")
        if record["kind"] != entry["kind"] or record["generation"] != entry["generation"]:
            raise ValueError("experiment family does not match its registered configuration")
        for parameter in ("k", "gap", "cap", "one_gap", "one_ratio", "error_scale", "slack"):
            if parameter in entry["config"]:
                _same_number(record[parameter], entry["config"][parameter], f"registered {parameter}")
            elif record[parameter] != "":
                raise ValueError("experiment table introduces an unregistered parameter")
        metrics = _metrics(outcomes["regrets"][ci], outcomes["calls"][ci], outcomes["fallbacks"][ci],
                           counts, family_ids, entry["config_id"])
        for field, expected in metrics.items():
            if field != "policy":
                _same_number(record[field], expected, f"{entry['config_id']}.{field}")
        signature = behavior_hashes[ci].hexdigest()
        representative = representatives.setdefault(signature, entry["config_id"])
        if record["behavior_signature"] != signature or record["equivalence_representative"] != representative:
            raise ValueError("behavioral equivalence metadata differs from acquired traces")
    with (out / "per_molecule.csv").open(newline="", encoding="utf-8") as stream:
        oof_rows = list(csv.DictReader(stream))
    if len(oof_rows) != len(pools) * len(ROLE_ORDER):
        raise ValueError("out-of-fold output has incomplete coverage")
    oof_keys = set()
    for row in oof_rows:
        key = (row["policy"], row["molecule_id"])
        if key in oof_keys or row["policy"] not in ROLE_ORDER:
            raise ValueError("duplicate/unknown out-of-fold policy result")
        oof_keys.add(key)
        fold_id = fold_of[row["molecule_id"]]
        choice = by_fold[fold_id][row["policy"]]
        if int(row["fold_id"]) != fold_id or row["config_id"] != choice["config_id"]:
            raise ValueError("out-of-fold result used the wrong training-selected configuration")
        original = selected_records[(row["config_id"], row["molecule_id"])]
        expected_row = {key: value for key, value in original.items() if key != "result_annotations"}
        expected_row.update(policy=row["policy"], split="development_cv", analysis_scope="development_family_cv",
                            query_order=canonical_json(original["query_order"]),
                            trace_annotations=canonical_json(original["result_annotations"]),
                            selection_fallback=choice["selection_fallback"])
        if row != {key: str(value) for key, value in expected_row.items()}:
            raise ValueError("out-of-fold CSV does not exactly reproduce the selected ledger record")
        for field in ("regret_kcal", "expensive_calls", "n_candidates"):
            _same_number(row[field], original[field], f"OOF {key}.{field}")
        for field in ("selected_candidate", "family_id", "trace_sha256", "stop_reason"):
            if row[field] != original[field]:
                raise ValueError("out-of-fold record differs from independent config replay")
        if (json.loads(row["query_order"]) != original["query_order"]
                or json.loads(row["trace_annotations"]) != original["result_annotations"]):
            raise ValueError("out-of-fold query trace metadata differs")
    replay_count = replay_calls = 0
    replay_seen = set()
    session_context = PolicySession() if replay_selected else None
    if session_context:
        session_context.__enter__()
    try:
        for replay in _read_jsonl_gz(out / "verification_replays.jsonl.gz"):
            key = (replay["config_id"], replay["molecule_id"])
            if key not in selected_records or key in replay_seen:
                raise ValueError("unknown/duplicate independently verified selection")
            replay_seen.add(key)
            record = selected_records[key]
            expected = reconstruct_trace(catalog[record["trace_sha256"]], record["result_annotations"])["result"]
            if (replay["expected_trace_sha256"] != record["trace_sha256"] or replay["matched"] is not True
                    or canonical_json(replay["result"]) != canonical_json(expected)):
                raise ValueError("independent verification replay differs from ledger")
            if session_context:
                actual = _evaluate_result(pools[pool_index[key[1]]], configurations[config_index[key[0]]]["config"], session_context)
                if canonical_json(actual) != canonical_json(expected):
                    raise ValueError("fresh selected-policy replay does not reproduce saved result")
            replay_count += 1
            replay_calls += expected["expensive_calls"]
    finally:
        if session_context:
            session_context.close()
    if replay_seen != selected_keys:
        raise ValueError("independent verification replay coverage is incomplete")
    # Recompute descriptive conditional intervals, not just the point estimates.
    expected_aggregate = summarize(oof_rows, registry["bootstrap"], registry["bootstrap_seed"], stratify_by="fold_id")
    expected_pairs = paired_comparisons(
        oof_rows, registry["bootstrap"], registry["bootstrap_seed"],
        comparators=("fixed_top_k", "adaptive", "matched_simple", "full_rerank"), stratify_by="fold_id")
    for filename, expected_rows, identifiers in (
        ("aggregate.csv", expected_aggregate, ("policy",)),
        ("paired_comparisons.csv", expected_pairs, ("policy", "comparator")),
    ):
        with (out / filename).open(newline="", encoding="utf-8") as stream:
            saved_rows = list(csv.DictReader(stream))
        if len(saved_rows) != len(expected_rows):
            raise ValueError(f"{filename} has the wrong number of rows")
        saved_by_key = {tuple(row[key] for key in identifiers): row for row in saved_rows}
        if len(saved_by_key) != len(saved_rows):
            raise ValueError(f"{filename} has duplicate comparison keys")
        for expected in expected_rows:
            saved = saved_by_key.get(tuple(expected[key] for key in identifiers))
            if saved is None:
                raise ValueError(f"{filename} is missing a selected role")
            for field, value in expected.items():
                if isinstance(value, (float, int)):
                    _same_number(saved[field], value, f"{filename}.{field}")
                elif saved[field] != ("" if value is None else value):
                    raise ValueError(f"{filename} metadata differs: {field}")
            if saved.get("analysis_scope") != "development_family_cv" or saved.get("interval_conditioning") != CONDITIONAL_INTERVAL_NOTE:
                raise ValueError("CV interval scope was relabeled")
    accounting = json.loads((out / "execution_accounting.json").read_text())
    for field, expected in {"configuration_count": len(configurations), "molecule_count": len(pools),
                            "decision_count": ledger_count, "charged_jobs": charged_jobs,
                            "unique_query_trace_count": len(catalog),
                            "unique_behavior_signature_count": len(representatives),
                            "selected_unique_replays": replay_count, "verification_charged_jobs": replay_calls}.items():
        if accounting[field] != expected:
            raise ValueError(f"execution accounting mismatch: {field}")
    expected_decision = _decision_from_cv(registry["dataset_kind"], len(pools), expected_aggregate, expected_pairs)
    saved_decision = json.loads((out / "decision.json").read_text())
    if canonical_json(saved_decision) != canonical_json(expected_decision):
        raise ValueError("decision fields/target flags differ from recomputed out-of-fold evidence")
    return {"verified": True, "analysis_scope": "development_family_cv",
            "registered_configurations": len(configurations), "development_molecules": len(pools),
            "development_families": len(set(family_ids)), "ledger_decisions_verified": ledger_count,
            "charged_jobs_verified": charged_jobs, "unique_query_traces_verified": len(catalog),
            "unique_behavior_signatures": len(representatives), "outer_folds_verified": folds["n_folds"],
            "oof_role_results_verified": len(oof_rows), "selected_unique_replays_verified": replay_count,
            "verification_charged_jobs": replay_calls, "fresh_selected_policy_replay": replay_selected,
            "historical_evaluation_labels_loaded": False}


def _decision_from_cv(dataset_kind, n_pools, aggregate, comparisons):
    table = {row["policy"]: row for row in aggregate}
    primary, comparator = table["sequential"], table["matched_simple"]
    pair = dict(next(row for row in comparisons
                     if row["policy"] == "sequential" and row["comparator"] == "matched_simple"))
    pair.update(analysis_scope="development_family_cv", interval_conditioning=CONDITIONAL_INTERVAL_NOTE)
    risk_ok = primary["success_rate"] >= TARGET_SUCCESS
    baseline_ok = comparator["success_rate"] >= TARGET_SUCCESS
    no_worse = pair["delta_success_rate"] >= -1e-12
    savings_ok = pair["relative_call_savings"] >= TARGET_SAVINGS
    return {"schema_version": 2, "analysis_scope": "development_family_cv", "dataset_kind": dataset_kind,
            "primary_policy": "sequential", "primary_comparator": "matched_simple",
            "development_molecules": n_pools, "development_families": primary["n_families"],
            "outer_folds": FOLD_COUNT, "primary_success_rate": primary["success_rate"],
            "sequential_success_rate": primary["success_rate"], "comparator_success_rate": comparator["success_rate"],
            "relative_call_savings": pair["relative_call_savings"], "paired_difference": pair,
            "observed_95pct_success_met": risk_ok, "frozen_comparator_95pct_success_met": baseline_ok,
            "target_risk_comparison_available": risk_ok and baseline_ok,
            "observed_risk_no_worse_than_frozen_comparator": no_worse,
            "observed_30pct_call_savings_met": savings_ok,
            "observed_joint_target_met": risk_ok and baseline_ok and no_worse and savings_ok,
            "inference": CONDITIONAL_INTERVAL_NOTE,
            "fresh_external_holdout": False, "historical_evaluation_labels_loaded": False,
            "shape_probe_benefit_measured": False,
            "interpretation": "Expanded acquisition experiment on original development data only; no external confirmation, live quantum work or wall-clock savings"}


def _report(registry, accounting, aggregate, decision):
    lines = ["# Adaptive Quantum Chemistry v0.2 — expanded development experiments", "",
             "**Internal development cross-validation. No new external holdout was used.**", "",
             f"Registered **{accounting['configuration_count']} parameter-distinct configurations** before execution. "
             f"They produced **{accounting['unique_behavior_signature_count']} distinct acquisition/selection behaviors** "
             f"on **{accounting['molecule_count']} original-development molecules**. Parameter count is not independent evidence.", "",
             f"All **{accounting['decision_count']} config/pool replays** were independently charged: "
             f"**{accounting['charged_jobs']} offline expensive-job equivalents**. Trace deduplication only reduced storage.", "",
             "Five deterministic chemical-family outer folds choose each operating point on the other four folds. "
             "The matched simple comparator is the cheapest original fixed/window/full rule meeting the training "
             "risk of the selected sequential rule, and at least 95% training success.", "",
             "| OOF role | Success ≤1 kcal/mol (95% descriptive family interval) | Median / p95 regret | Mean calls | Total calls | Fallback |",
             "|---|---:|---:|---:|---:|---:|"]
    for row in aggregate:
        lines.append(f"| {row['policy']} | {row['success_rate']:.2%} "
                     f"({row['success_rate_ci_low']:.2%}–{row['success_rate_ci_high']:.2%}) | "
                     f"{row['median_regret_kcal']:.4f} / {row['p95_regret_kcal']:.4f} | "
                     f"{row['mean_calls']:.3f} | {row['total_calls']} | {row['fallback_rate']:.2%} |")
    pair = decision["paired_difference"]
    lines += ["", "All regrets are kcal/mol. Cheap-only remains an unverified diagnostic.", "",
              "## Recorded development-CV decision", "",
              f"Sequential versus matched simple call savings: **{decision['relative_call_savings']:.2%}** "
              f"(descriptive 95% interval {pair['relative_call_savings_ci_low']:.2%}–{pair['relative_call_savings_ci_high']:.2%}).",
              f"Success difference: **{pair['delta_success_rate'] * 100:.3f} percentage points** "
              f"({pair['delta_success_rate_ci_low'] * 100:.3f}–{pair['delta_success_rate_ci_high'] * 100:.3f}).",
              f"Observed development-CV joint target met: **{decision['observed_joint_target_met']}**. "
              "This is not a fresh-holdout or population guarantee.", "", CONDITIONAL_INTERVAL_NOTE, "",
              "## Important limitations", "",
              "- The sequential envelope and one-query gate are heuristics. Queried residuals are not a calibrated bound on unseen candidates.",
              "- The design follows inspection of the earlier benchmark. This development CV must not be presented as independent confirmation.",
              "- The original final-evaluation cohort was not rescored, retuned on, or merged into these experiments.",
              "- Pooled experiment rows are descriptive development outcomes; only the role table uses fold-excluded selections.",
              "- Boundary success rates and constant paired differences can produce degenerate empirical intervals; warnings are recorded explicitly.",
              "- Reference labels, complete-case coverage, geometry provenance and inferred-family limitations remain those of the original benchmark.",
              "- No shape features, neural model, live quantum work, paid compute or wall-clock benefit is measured.", "",
              "## Reproducible evidence", "",
              "The registry, source/data/fold hashes, experiment table, five-fold choices, all decision ledger rows, "
              "deduplicated charged-query catalog, independently repeated OOF selections, verification manifest, "
              "paired table and risk plot are retained. `evaluation_seal.json` covers all scientific outputs.", ""]
    return "\n".join(lines)


def run_experiments(prepared: Path, out: Path, bootstrap: int = 5000, seed: int = 1729) -> dict:
    """Execute the registered grid and five-fold development-family experiment."""
    from .benchmark import verify_prepared
    from .integrity import write_artifact_seal
    prepared, out = Path(prepared).resolve(), Path(out).resolve()
    if type(bootstrap) is not int or bootstrap < 100:
        raise ValueError("at least 100 descriptive bootstrap draws required")
    project = Path(__file__).resolve().parents[1]
    for historic in (project / "results" / "real", project / "results" / "fixture"):
        if out == historic or historic in out.parents:
            raise ValueError("historical result directories are immutable")
    if out == prepared or prepared in out.parents or out in prepared.parents:
        raise ValueError("experiment output cannot overlap prepared input")
    if out.exists() and any(out.iterdir()):
        raise ValueError("experiment output is not empty; never overwrite a registered run")
    audit, source_split = verify_prepared(prepared)
    pools = sorted(load_pools(prepared, "development"), key=lambda pool: pool["molecule_id"])
    configurations = build_configurations(max(len(pool["candidates"]) for pool in pools))
    folds = make_family_folds(pools, seed)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "folds.json", folds)
    registry = {"schema_version": 2, "analysis_scope": "original_development_only",
                "dataset_kind": audit["dataset_kind"], "configuration_count": len(configurations),
                "parameter_distinct_configurations": len(configurations),
                "original_configuration_count": sum(e["generation"] == "original" for e in configurations),
                "new_configuration_count": sum(e["generation"] == "new" for e in configurations),
                "configurations": configurations, "registered_before_execution": True,
                "development_molecules": len(pools), "development_families": len({p["family_id"] for p in pools}),
                "historical_evaluation": source_split["counts"]["evaluation"],
                "historical_evaluation_policy": "Never load reference rows, score, tune, or merge this already-observed cohort",
                "outer_fold_count": FOLD_COUNT, "fold_seed": seed, "bootstrap": bootstrap, "bootstrap_seed": seed,
                "folds_sha256": sha256_file(out / "folds.json"),
                "source_audit_sha256": sha256_file(prepared / "audit.json"),
                "source_split_sha256": source_split["split_sha256"],
                "prepared_files_sha256": audit["prepared_files_sha256"],
                "source_code_sha256": _source_hashes(),
                "protocol": {"target_success": TARGET_SUCCESS, "target_savings": TARGET_SAVINGS,
                             "primary_policy": "sequential", "primary_comparator": "matched_simple",
                             "selection": "Training-only >=95% success, minimum calls, minimum p95 regret, maximum success, config ID",
                             "matching": "Original fixed/window/full rules at >=max(95%, selected sequential training success)",
                             "fold_bootstrap": CONDITIONAL_INTERVAL_NOTE,
                             "numerical_comparison_tolerance": SUCCESS_TOLERANCE,
                             "configuration_outcomes_reused_across_folds": "Allowed because configurations fit nothing across molecules",
                             "one_gap_grid": list(ONE_GAPS), "one_ratio_grid": list(ONE_RATIOS),
                             "error_scale_grid": list(ERROR_SCALES), "cap_grid": list(SEQUENTIAL_CAPS), "slack": SLACK}}
    registry["registry_sha256"] = digest(registry)
    write_json(out / "experiment_registry.json", registry)
    write_json(out / "run_status.json", {"status": "registered", "registry_sha256": registry["registry_sha256"]})
    write_json(out / "audit.json", {"analysis_scope": "development_family_cv", "dataset_kind": audit["dataset_kind"],
                                    "source_audit_sha256": registry["source_audit_sha256"],
                                    "source_split_sha256": registry["source_split_sha256"], "source_audit": audit,
                                    "historical_evaluation_labels_loaded": False})
    outcomes, accounting = _execute_registry(configurations, pools, folds, out)
    choices = select_fold_choices(configurations, outcomes, pools, folds)
    write_json(out / "fold_choices.json", choices)
    oof_rows, selected_records = _select_oof_rows(out, pools, folds, choices)
    aggregate = summarize(oof_rows, bootstrap, seed, stratify_by="fold_id")
    comparisons = paired_comparisons(oof_rows, bootstrap, seed,
                                    comparators=("fixed_top_k", "adaptive", "matched_simple", "full_rerank"),
                                    stratify_by="fold_id")
    for row in [*aggregate, *comparisons]:
        row["analysis_scope"] = "development_family_cv"
        row["interval_conditioning"] = CONDITIONAL_INTERVAL_NOTE
    write_csv(out / "aggregate.csv", aggregate)
    write_csv(out / "paired_comparisons.csv", comparisons)
    fold_aggregates = []
    for fold_id in range(FOLD_COUNT):
        for row in summarize([r for r in oof_rows if r["fold_id"] == fold_id], bootstrap=0):
            row.update(fold_id=fold_id, analysis_scope="outer_validation_fold_descriptive")
            fold_aggregates.append(row)
    write_csv(out / "fold_aggregates.csv", fold_aggregates)
    decision = _decision_from_cv(audit["dataset_kind"], len(pools), aggregate, comparisons)
    write_json(out / "decision.json", decision)
    catalog = _load_catalog(out)
    accounting.update(_replay_selected(pools, configurations, selected_records, catalog, out))
    write_json(out / "execution_accounting.json", accounting)
    plot_risk_calls(aggregate, out / "risk_vs_calls.png", "Original-development family CV · 5 outer folds",
                    decision["development_families"], scope_label="Development CV chemical families")
    write_json(out / "environment.json", {"python": platform.python_version(), "platform": platform.platform(),
                                          "packages": {p: importlib.metadata.version(p) for p in ("numpy", "matplotlib", "rdkit", "pillow")},
                                          "bootstrap": bootstrap, "seed": seed})
    (out / "REPORT.md").write_text(_report(registry, accounting, aggregate, decision), encoding="utf-8")
    _check_run_identity(prepared, out, registry)
    verification = verify_experiment_run(prepared, out)
    write_json(out / "verification_manifest.json", verification)
    write_json(out / "run_status.json", {"status": "complete", "registry_sha256": registry["registry_sha256"],
                                         "decision_count": accounting["decision_count"], "verified": True})
    write_artifact_seal(out, config_sha256=registry["registry_sha256"], split_sha256=registry["source_split_sha256"])
    print(canonical_json(decision), flush=True)
    return decision
