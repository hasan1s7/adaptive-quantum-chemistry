#!/usr/bin/env python3
"""Package the local decision-engine evidence; no network, deployment or policy run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


ROOT = Path(__file__).resolve().parents[1]
BASE_COMMIT = "f2a603e14f1d704084f6ddcb07645f2f701fa844"
EVIDENCE = ROOT / "results/decision_engine"


def read(relative):
    return json.loads((ROOT / relative).read_text())


def record(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def bundle():
    return {
        "schema_version": "erkidu.integrated-research-result-bundle.v1",
        "as_of_date": "2026-11-27",
        "company_decision": {
            "formulation": "B: model-independent evaluation, provenance and decision audit",
            "adaptive_promoted": False,
            "reason": "One equal-budget rescue over MACE top-two; a prespecified frozen M3GNet baseline meets the same tolerance at zero acquisitions.",
            "buyer_hypothesis": "Computational materials lead with recurring oxide screening and reference-job expenditure",
            "primary_endpoint": "Fixed-pool, same-composition selection within 0.020 eV/atom of the lowest recorded compatible reference relaxation label",
            "generation_product_promoted": False,
        },
        "workspace_scope": "Original 27 November 2026 experiment; later GitHub publication and presentation revisions are described in docs/decision_engine/RELEASE_NOTES.md.",
        "workspace": {
            "repository": "https://github.com/hasan1s7/adaptive-quantum-chemistry",
            "base_commit": BASE_COMMIT,
            "work_local_only": True,
            "existing_tracked_files_changed": False,
            "nabu_used_or_modified": False,
            "pushed": False,
            "deployed": False,
            "live_mlip_inference": 0,
            "live_reference_jobs": 0,
            "paid_compute_dollars": 0,
        },
        "units": {
            "materials_energy": "eV/atom",
            "materials_display_regret": "meV/atom",
            "historical_molecular_energy": "kcal/mol",
            "geometry_length": "angstrom",
            "reference_cost_count": "one first valid attempted historical whole-relaxation label, including a synthetic failed attempt",
            "cost_sensitivity": "hypothetical regret-equivalent cost; not dollars",
        },
        "evidence_registry": [
            {"id": "historical_956", "status": "executed_historical_development_replay", "live_jobs": 0},
            {"id": "saved_669", "status": "executed_inspection_of_existing_result", "policy_rerun": False},
            {"id": "fixed_pair_allocation", "status": "proposed_not_run", "distinct_from_saved_669": True},
            {"id": "oxide", "status": "executed_real_data_energy_only_replay", "force_validation": False},
            {"id": "fault_injection", "status": "executed_synthetic_faults_on_real_replay", "real_failure_rate_estimated": False},
            {"id": "exact_examples", "status": "executed_synthetic_exact_rational_examples"},
            {"id": "generation", "status": "executed_geometry_only_generation", "physical_validation": False},
            {"id": "fresh_reference", "status": "proposed_not_run", "spend_authorized": False},
        ],
        "historical_recovery": read("results/decision_engine/recovery/summary.json"),
        "new_materials_replay": read("results/decision_engine/oxide_run/dashboard_bundle.json"),
        "frozen_protocol": read("results/decision_engine/oxide_prepared/preregistered_protocol.json"),
        "metadata_errata": read("data/decision_engine/source_metadata/metadata_errata.json"),
        "experiment_manifest": read("results/decision_engine/oxide_run/experiment_manifest.json"),
        "post_run_diagnostics": read("results/decision_engine/post_run_diagnostics.json"),
        "cost_scenarios": read("results/decision_engine/oxide_run/cost_sensitivity.json"),
        "two_run_accounting_and_trace_fix": read("results/decision_engine/replay_fix_verification.json"),
        "exact_finite_examples": read("results/decision_engine/decision_examples_results.json"),
        "generation": {
            "status": read("results/decision_engine/generation_status.json"),
            "manifest": read("results/decision_engine/generation/manifest.json"),
            "summary": read("results/decision_engine/generation/summary.json"),
            "runtime": read("results/decision_engine/generation/runtime_receipt.json"),
            "candidate_records": [json.loads(line) for line in (EVIDENCE / "generation/candidate_records.jsonl").read_text().splitlines()],
        },
        "proposed_fresh_reference_batch": read("proposed/fresh_sno2_batch/batch_manifest.json"),
        "audits": {
            "data": read("results/decision_engine/independent_data_audit.json"),
            "initial_geometry": read("results/decision_engine/independent_geometry_audit.json"),
            "canonical_primary_seal": read("results/decision_engine/oxide_verification.json"),
            "all_traces": read("results/decision_engine/full_trace_audit.json"),
        },
        "important_limits": [
            "Reference labels and model predictions are different relaxation endpoints, not same-geometry single points.",
            "Compatible forces, model-final coordinates and convergence trajectories were not available.",
            "Whole-system calibration relies on exchangeability; no blanket shifted-domain guarantee.",
            "Shared prototypes, parent lineages and pretrained MP exposure can correlate errors across groups.",
            "Public MP support distance is a proxy, not exact training membership.",
            "All heldout groups are now examined; any changed model or policy needs untouched validation.",
            "Regret scoring assumes complete evaluator truth; actual missing minima are outside the current scorer contract.",
            "Sub-meV regret differences are below the source convergence scale.",
            "Full browser screenshot QA was unavailable; JavaScript controls and the scientific export were checked.",
        ],
        "archive_paths": {
            "readme": "README_DECISION_ENGINE.md",
            "memo": "docs/decision_engine/TECHNICAL_MEMO.md",
            "statistics_review": "docs/decision_engine/HASAN_STATISTICAL_REVIEW.md",
            "physics_review": "docs/decision_engine/MATERIALS_PHYSICS_REVIEW.md",
            "old_physics_failures": "docs/decision_engine/RECOVERY_PHYSICS_CASES.md",
            "source_registry": "docs/decision_engine/sources.json",
            "primary_traces": "results/decision_engine/oxide_run/decision_traces.jsonl.gz",
            "additional_seed_traces": "results/decision_engine/oxide_run/random_seed_traces.jsonl.gz",
            "synthetic_fault_traces": "results/decision_engine/oxide_run/synthetic_failure_traces.jsonl.gz",
            "initial_geometries": "data/decision_engine/initial_geometries.json.gz",
        },
    }


def source_paths():
    paths = set()
    for directory in ("erkidu_decision", "data/decision_engine", "docs/decision_engine", "results/decision_engine", "proposed/fresh_sno2_batch", "tools", "scripts/historical"):
        paths.update(p for p in (ROOT / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    for relative in (
        "LICENSE", "README_DECISION_ENGINE.md", "requirements-decision.txt", "requirements-decision.lock.txt",
        "aqc/__init__.py", "aqc/oracle.py", "aqc/policy_worker.py", "tests/test_oracle.py",
        "tests/test_decision_engine_core.py", "tests/test_decision_engine_data.py", "tests/test_bounded_oxide_generation.py",
        "scripts/reproduce_decision_history.py", "scripts/test_decision_history.py", "scripts/inspect_saved_669.py",
        "scripts/audit_decision_data.py", "scripts/audit_initial_geometry_splits.py", "scripts/audit_decision_traces.py", "scripts/analyze_decision_results.py", "scripts/decision_examples.py",
        "data/UPSTREAM_LICENSE", "data/development_geometry.json.gz", "results/real/prepared/development_features.jsonl",
        "results/real/prepared/development_references.jsonl", "results/lab/folds.json",
    ):
        paths.add(ROOT / relative)
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    return sorted(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "Erkidu-Result-Bundle.json", bundle())
    shutil.copyfile(EVIDENCE / "oxide_run/dashboard.html", out / "Erkidu-Dashboard.html")
    shutil.copyfile(EVIDENCE / "oxide_run/cost_risk_frontier.png", out / "Erkidu-Cost-Risk-Frontier.png")
    paths = source_paths()
    files = {str(p.relative_to(ROOT)): record(p) for p in paths}
    manifest = {
        "schema_version": "erkidu.handoff-file-manifest.v1",
        "base_commit": BASE_COMMIT,
        "date": "2026-11-27",
        "scope": "Decision engine source and evidence plus selected unchanged Erkidu dependencies; not full product checkout",
        "files": files,
        "integrated_bundle": record(out / "Erkidu-Result-Bundle.json"),
        "status": "local_no_push_no_deployment_no_paid_compute",
    }
    archive = out / "Erkidu-Code-and-Evidence.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in paths:
            info = zipfile.ZipInfo("erkidu-decision-handoff/" + str(path.relative_to(ROOT)), (2026, 11, 27, 12, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, path.read_bytes())
        z.writestr("erkidu-decision-handoff/HANDOFF_MANIFEST.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        z.writestr("erkidu-decision-handoff/Erkidu-Result-Bundle.json", (out / "Erkidu-Result-Bundle.json").read_bytes())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError("ZIP CRC failure")
        for name, expected in files.items():
            raw = z.read("erkidu-decision-handoff/" + name)
            if hashlib.sha256(raw).hexdigest() != expected["sha256"]:
                raise ValueError("Archived content mismatch: " + name)
    receipt = {
        "evidence_kind": "executed_local_packaging_verification", "source_file_count": len(files),
        "archive": record(archive), "all_archived_source_hashes_verified": True,
        "new_policy_runs": 0, "new_reference_jobs": 0,
    }
    write_json(out / "Erkidu-Handoff-Receipt.json", receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
