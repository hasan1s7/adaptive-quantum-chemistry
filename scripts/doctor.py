#!/usr/bin/env python3
"""Read-only AQC diagnostics. Python's standard library is sufficient.

No package import, install, download, evidence restoration, or quantum job is
performed. Missing scientific packages are informational for the saved app.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path, PurePosixPath
import platform
import socket
import sys


PROJECT = Path(__file__).resolve().parents[1]
APP_FILES = (
    "aqc_app/__main__.py", "app/index.html", "app/assets/client.js",
    "app/assets/app.js", "app/assets/styles.css", "app/assets/molecule-viewer.js",
)
APP_SUMMARY_FILES = (
    "aggregate.csv", "experiments.csv", "paired_comparisons.csv", "risk_vs_calls.png",
    "decision.json", "fold_choices.json", "folds.json", "execution_accounting.json",
    "experiment_registry.json",
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode("utf-8")).hexdigest()


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def safe_path(root, name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("Unsafe path in integrity record")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or str(relative) != name:
        raise ValueError("Unsafe path in integrity record")
    path = Path(root).joinpath(*relative.parts)
    if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("Integrity path escapes the application folder")
    return path


def read_json(path):
    def duplicate_guard(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError(f"Nonfinite JSON value: {value}")

    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=duplicate_guard, parse_constant=nonfinite)


def verify_hashes(root, hashes):
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("No files declared in integrity record")
    for name, expected in hashes.items():
        path = safe_path(root, name)
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError(f"Invalid recorded checksum: {name}")
        if not path.is_file():
            raise ValueError(f"Missing file: {name}")
        if sha256(path) != expected:
            raise ValueError(f"Checksum differs: {name}")
    return len(hashes)


def check_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.bind(("127.0.0.1", port))
    return f"127.0.0.1:{port} is available now; startup checks it again."


def scientific_dependencies(root):
    """Inspect distribution metadata only; never import chemistry/numeric code."""
    pins = []
    for line in (Path(root) / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            raise ValueError("Scientific requirements must use exact version pins")
        name, expected = line.split("==", 1)
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        pins.append({"name": name, "pinned": expected, "installed": installed,
                     "matches_pin": installed == expected, "required_to_open_app": False})
    return pins


def diagnose(root=PROJECT, *, port=8765, include_science=False):
    root = Path(root).resolve()
    checks = []

    def record(name, status, detail, *, app_required=True, **extra):
        checks.append({"name": name, "status": status, "detail": detail,
                       "app_required": app_required, **extra})

    def attempt(name, action, *, app_required=True, remedy=None):
        try:
            value = action()
            record(name, "pass", value, app_required=app_required)
            return value
        except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
            record(name, "fail", str(error), app_required=app_required, remedy=remedy)
            return None

    version_ok = sys.version_info >= (3, 10)
    record("python_runtime", "pass" if version_ok else "fail",
           f"Python {platform.python_version()} at {sys.executable}; app requires 3.10 or newer.")
    def application_check():
        missing = [name for name in APP_FILES if not safe_path(root, name).is_file()]
        if missing:
            raise ValueError("Missing: " + ", ".join(missing))
        return f"All {len(APP_FILES)} application entry/assets are present."

    attempt("application_files", application_check,
            remedy="Extract the complete application archive or restore the repository checkout.")

    registry_path = root / "results/lab/experiment_registry.json"

    def source_check():
        registry = read_json(registry_path)
        unsigned = {key: value for key, value in registry.items() if key != "registry_sha256"}
        if digest(unsigned) != registry.get("registry_sha256"):
            raise ValueError("Expanded registry self-checksum differs")
        n = verify_hashes(root / "aqc", registry["source_code_sha256"])
        return f"All {n} registered scientific source modules match their frozen hashes."

    source_ok = attempt("frozen_scientific_source", source_check,
                        remedy="Restore the exact v0.2 scientific source; do not update frozen hashes to suppress this error.")

    def app_summary_check():
        folder = root / "results/lab"
        seal = read_json(folder / "evaluation_seal.json")
        unsigned = {key: value for key, value in seal.items() if key != "seal_sha256"}
        if seal.get("schema_version") != 2 or digest(unsigned) != seal.get("seal_sha256"):
            raise ValueError("Saved experiment seal is invalid")
        count = verify_hashes(folder, {name: seal["artifact_sha256"][name] for name in APP_SUMMARY_FILES})
        return f"All {count} served summary files match the recorded seal; the full ledger is checked separately."

    attempt("app_summary_evidence", app_summary_check,
            remedy="Restore the original saved summary files and their seal.")

    def prepared_check():
        registry = read_json(registry_path)
        prepared = root / "results/real/prepared"
        if sha256(prepared / "audit.json") != registry["source_audit_sha256"]:
            raise ValueError("Prepared audit differs from the experiment registry")
        split = read_json(prepared / "split_manifest.json")
        unsigned = {key: value for key, value in split.items() if key != "split_sha256"}
        if digest(unsigned) != split.get("split_sha256") or split["split_sha256"] != registry["source_split_sha256"]:
            raise ValueError("Prepared split differs from the frozen experiment")
        n = verify_hashes(prepared, registry["prepared_files_sha256"])
        return f"Prepared audit, split identity, and {n} feature/reference file hashes match."

    attempt("prepared_data", prepared_check,
            remedy="Restore the original prepared files; do not join or replace individual energy rows.")

    # The verified module is stdlib-only. A modified validator is not imported.
    if source_ok:
        # Importing the verified validator must not write into the distribution.
        previous_bytecode_setting = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec = importlib.util.spec_from_file_location("_aqc_doctor_integrity", root / "aqc/integrity.py")
            integrity = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(integrity)
        finally:
            sys.dont_write_bytecode = previous_bytecode_setting
        for name, folder, complete in (("expanded_evidence", "results/lab", True),
                                       ("historical_evidence", "results/real", False)):
            result = attempt(name, lambda folder=folder, complete=complete:
                             integrity.verify_artifact_seal(root / folder, require_complete=complete),
                             app_required=False,
                             remedy="For a Git clone missing the ledger, run python scripts/archive_evidence.py restore. For a checksum mismatch, restore the original bytes; the doctor never overwrites evidence.")
            if result and result.get("warnings"):
                record(name + "_coverage", "warn", " ".join(result["warnings"]), app_required=False)
    else:
        record("evidence_validation", "fail", "Skipped: the frozen validator source did not pass its checksum guard.")

    def geometry_check():
        path = root / "data/development_geometry_manifest.json"
        manifest = read_json(path)
        asset = safe_path(path.parent, manifest["asset_filename"])
        if sha256(asset) != manifest["asset_sha256"] or asset.stat().st_size != manifest["asset_size_bytes"]:
            raise ValueError("Development geometry asset checksum or size differs")
        if manifest.get("energy_labels_included") is not False or manifest.get("scope") != "original_development_only":
            raise ValueError("Geometry asset has an unexpected label/scope declaration")
        registry = read_json(registry_path)
        if manifest["source_audit_sha256"] != registry["source_audit_sha256"] or manifest["source_split_sha256"] != registry["source_split_sha256"]:
            raise ValueError("Geometry asset belongs to a different prepared cohort")
        if sha256(root / "results/real/prepared/geometry_manifest.csv") != manifest["geometry_manifest_sha256"]:
            raise ValueError("Geometry identity manifest checksum differs")
        if sha256(root / "data/upstream_lock.json") != manifest["source_lock_sha256"]:
            raise ValueError("Pinned source lock differs from the geometry manifest")
        return f"Bundled coordinate bytes and source identity match ({manifest['molecule_count']} development molecules, {manifest['candidate_count']} candidates)."

    attempt("development_geometry", geometry_check,
            remedy="Restore the bundled development geometry asset and its original manifest.")

    def release_check():
        release = root / "releases/v0.1.0"
        manifest = read_json(release / "manifest.json")
        source_count = verify_hashes(release, manifest["source_sha256"])
        artifact_count = verify_hashes(root, manifest["historical_artifact_sha256"])
        return f"Historical release unchanged: {source_count} source files and {artifact_count} recorded artifacts."

    attempt("historical_release", release_check, app_required=False,
            remedy="Restore releases/v0.1.0 and the original historical artifacts.")

    snapshot = root / "data/source_snapshot.tar.gz"
    if snapshot.exists():
        def snapshot_check():
            lock = read_json(root / "data/upstream_lock.json")
            if sha256(snapshot) != lock["archive_sha256"]:
                raise ValueError("Pinned source snapshot checksum differs")
            return "Pinned source archive bytes match upstream_lock.json; no extraction or download performed."
        attempt("benchmark_source_snapshot", snapshot_check, app_required=False)
    else:
        record("benchmark_source_snapshot", "warn", "Bundled source snapshot absent; saved-results viewing does not need it. Offline benchmark reconstruction does.", app_required=False)

    if port is not None:
        try:
            message = check_port(port)
            record("loopback_port", "pass", message, app_required=False)
        except OSError as error:
            record("loopback_port", "warn", f"127.0.0.1:{port} is unavailable: {error}. An AQC server may already be running; use --port with another local port if needed.", app_required=False)

    dependencies = None
    if include_science:
        try:
            dependencies = scientific_dependencies(root)
            matching = sum(item["matches_pin"] for item in dependencies)
            record("optional_scientific_dependencies", "pass" if matching == len(dependencies) else "warn",
                   f"{matching}/{len(dependencies)} installed versions match requirements.txt. These packages are not required to open the saved-results app.", app_required=False)
        except (OSError, ValueError) as error:
            record("optional_scientific_dependencies", "warn", str(error), app_required=False)
    return {"schema_version": 1, "root": str(root),
            "ok": not any(check["status"] == "fail" for check in checks),
            "app_ready": not any(check["app_required"] and check["status"] == "fail" for check in checks),
            "full_evidence_ready": all(any(check["name"] == name and check["status"] == "pass" for check in checks)
                                       for name in ("expanded_evidence", "historical_evidence", "historical_release")),
            "checks": checks, "optional_scientific_dependencies": dependencies,
            "scope": "Read-only file integrity, frozen-source checks, summary consistency, and local runtime diagnostics. No independent quantum calculation or full policy replay is performed.",
            "network_accessed": False, "files_modified": False}


def port_number(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535") from error
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535")
    return number


def main(argv=None):
    if sys.version_info < (3, 10):
        print("AQC diagnostics require Python 3.10 or newer. Use an existing compatible interpreter.", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT, help="extracted application/repository folder")
    parser.add_argument("--json", action="store_true", help="print a machine-readable report")
    parser.add_argument("--science", action="store_true", help="report optional benchmark package versions without importing them")
    parser.add_argument("--port", type=port_number, default=8765, help="check a loopback port without starting a server")
    parser.add_argument("--no-port-check", action="store_true", help="omit the optional local port probe")
    args = parser.parse_args(argv)
    result = diagnose(args.root, port=None if args.no_port_check else args.port,
                      include_science=args.science)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    else:
        print("AQC diagnostics — saved-results app")
        print(f"Application folder: {result['root']}")
        for check in result["checks"]:
            detail = check["detail"]
            if isinstance(detail, dict):
                detail = f"{len(detail['sealed_files'])} sealed files and {detail['primary_rows_verified']} decision rows checked."
            print(f"[{check['status'].upper()}] {check['name']}: {detail}")
            if check.get("remedy") and check["status"] == "fail":
                print("       " + check["remedy"])
        print("App prerequisites: " + ("ready" if result["app_ready"] else "needs attention"))
        print("Complete scientific evidence: " + ("ready" if result["full_evidence_ready"] else "needs attention; separate from opening the app"))
        print("Scientific dependency installation is not required to open saved results.")
        print(result["scope"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
