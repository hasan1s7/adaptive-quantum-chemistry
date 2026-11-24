"""Run `python -m aqc --help`. No live computational chemistry is invoked."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from . import __version__
from .data import REVISION, UPSTREAM, prepare_real, sha256_file

ROOT = Path(__file__).resolve().parent.parent


def acquire_source(source: str | None) -> Path:
    if source:
        return Path(source).resolve()
    destination = ROOT / ".cache" / f"folmsbee-hutchison-{REVISION}"
    if destination.exists():
        return destination
    archive = ROOT / "data" / "source_snapshot.tar.gz"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        lock = json.loads((ROOT / "data" / "upstream_lock.json").read_text())
        if sha256_file(archive) != lock["archive_sha256"]:
            raise ValueError("Bundled source archive checksum mismatch")
        destination.mkdir()
        with tarfile.open(archive) as f:
            f.extractall(destination, filter="data")
    else:
        subprocess.run(["git", "clone", UPSTREAM, str(destination)], check=True)
        subprocess.run(["git", "-C", str(destination), "checkout", "--detach", REVISION], check=True)
    return destination


def pipeline(kind, out, source, bootstrap):
    out = Path(out).resolve()
    if (out / "frozen_config.json").exists():
        raise ValueError("Output already contains a frozen run; use 'reproduce' or a new --out path")
    prepared = out / "prepared"
    if kind == "fixture":
        from .fixture import prepare_fixture
        prepare_fixture(prepared)
    else:
        prepare_real(acquire_source(source), prepared)
    # Separate commands provide a clear audit boundary: development never reads
    # the holdout label table; evaluation starts only after a frozen file exists.
    subprocess.run([sys.executable, "-m", "aqc", "tune", "--prepared", str(prepared), "--out", str(out)], check=True, cwd=ROOT)
    subprocess.run([sys.executable, "-m", "aqc", "evaluate", "--prepared", str(prepared), "--out", str(out),
                    "--bootstrap", str(bootstrap)], check=True, cwd=ROOT)
    from .dashboard import build_dashboard
    build_dashboard(out)
    print(f"Completed {kind}: {out / 'REPORT.md'}\nDashboard: {out / 'dashboard.html'}", flush=True)


def reproduce(run: Path, out: Path):
    """Use the already-frozen choices; never retune a run whose holdout is observed."""
    from .benchmark import evaluate
    from .integrity import verify_artifact_seal
    run, out = run.resolve(), out.resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError("Reproduction output must be empty")
    verify_artifact_seal(run)
    original = json.loads((run / "evaluation_seal.json").read_text())
    if original.get("schema_version", 1) == 1:
        release = ROOT / "releases" / "v0.1.0"
        manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
        for name, sha in manifest["source_sha256"].items():
            if sha256_file(release / name) != sha:
                raise ValueError(f"Immutable historical engine changed: {name}")
        frozen = json.loads((run / "frozen_config.json").read_text(encoding="utf-8"))
        for name, sha in frozen["source_code_sha256"].items():
            if manifest["source_sha256"].get(f"aqc/{name}") != sha:
                raise ValueError("No verified historical engine matches this frozen run")
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        subprocess.run([sys.executable, "-m", "aqc", "reproduce", "--run", str(run),
                        "--out", str(out)], cwd=release, env=env, check=True)
        verify_artifact_seal(out)
        print("Historical v0.1 engine preserved: original five sealed outputs reproduced exactly.")
        return
    for name, sha in original["artifact_sha256"].items():
        if sha256_file(run / name) != sha:
            raise ValueError(f"Sealed run artifact altered: {name}")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(run / "frozen_config.json", out / "frozen_config.json")
    env = json.loads((run / "environment.json").read_text())
    evaluate(run / "prepared", out, env["bootstrap"], env["bootstrap_seed"])
    actual = json.loads((out / "evaluation_seal.json").read_text())
    deterministic = {"per_molecule.csv", "aggregate.csv", "paired_comparisons.csv", "decision.json", "traces.jsonl", "heldout_frontier.csv", "heldout_frontier_traces.jsonl.gz"}
    for name in deterministic:
        if actual["artifact_sha256"].get(name) != original["artifact_sha256"].get(name):
            raise ValueError(f"Reproduction failed: scientific output differs: {name}")
    from .dashboard import build_dashboard
    build_dashboard(out)
    print("Reproduction passed: seven deterministic scientific outputs match byte for byte; environment and views are recorded separately.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Adaptive Quantum Chemistry: reproducible paid-query replay, no quantum jobs")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for kind in ("fixture", "real"):
        p = commands.add_parser(kind, help=f"Prepare, tune, freeze, evaluate and dashboard the {kind} dataset")
        p.add_argument("--out", default=f"runs/{kind}")
        p.add_argument("--bootstrap", type=int, default=5000)
        if kind == "real":
            p.add_argument("--source", help="Clean upstream checkout at pinned revision; bundled audited snapshot used by default")
    p = commands.add_parser("prepare", help="Verify real data and build split/identity manifests")
    p.add_argument("--source")
    p.add_argument("--out", required=True)
    for command in ("tune", "evaluate"):
        p = commands.add_parser(command)
        p.add_argument("--prepared", required=True)
        p.add_argument("--out", required=True)
        if command == "evaluate":
            p.add_argument("--bootstrap", type=int, default=5000)
    p = commands.add_parser("dashboard", help="Rebuild a read-only local dashboard from existing results")
    p.add_argument("--results", required=True)
    p = commands.add_parser("reproduce", help="Replay sealed frozen choices without retuning; compare exact result hashes")
    p.add_argument("--run", required=True)
    p.add_argument("--out", required=True)
    p = commands.add_parser("verify", help="Verify a saved run's seal and internal consistency")
    p.add_argument("--run", required=True)
    p.add_argument("--complete", action="store_true")
    p = commands.add_parser("experiments", help="Run the 1,020-configuration DEVELOPMENT-only experiment suite and five family folds")
    p.add_argument("--prepared", default="results/real/prepared")
    p.add_argument("--out", default="runs/lab")
    p.add_argument("--bootstrap", type=int, default=5000)
    p.add_argument("--seed", type=int, default=271828)
    p.add_argument("--historical", default="results/real")
    p = commands.add_parser("lab", help="Build the interactive development lab from a verified experiment run")
    p.add_argument("--results", default="results/lab")
    p.add_argument("--historical", default="results/real")
    p.add_argument("--prepared", default="results/real/prepared")
    p.add_argument("--output")
    p = commands.add_parser("verify-experiments", help="Audit every experimental decision and optionally independently replay selected policies")
    p.add_argument("--results", default="results/lab")
    p.add_argument("--prepared", default="results/real/prepared")
    p.add_argument("--replay-selected", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command in {"fixture", "real"}:
            pipeline(args.command, args.out, getattr(args, "source", None), args.bootstrap)
        elif args.command == "prepare":
            audit = prepare_real(acquire_source(args.source), Path(args.out))
            print(json.dumps(audit, indent=2))
        elif args.command in {"tune", "evaluate"}:
            from .benchmark import tune, evaluate
            if args.command == "tune":
                tune(Path(args.prepared), Path(args.out))
            else:
                if args.bootstrap < 100:
                    raise ValueError("Final evaluation requires at least 100 family bootstrap draws")
                evaluate(Path(args.prepared), Path(args.out), args.bootstrap)
        elif args.command == "dashboard":
            from .dashboard import build_dashboard
            print(build_dashboard(Path(args.results)))
        elif args.command == "reproduce":
            reproduce(Path(args.run), Path(args.out))
        elif args.command == "verify":
            from .integrity import verify_artifact_seal
            print(json.dumps(verify_artifact_seal(Path(args.run), require_complete=args.complete), indent=2))
        elif args.command == "experiments":
            from .experiments import run_experiments
            from .lab import build_lab
            run_experiments(Path(args.prepared), Path(args.out), bootstrap=args.bootstrap, seed=args.seed)
            print(build_lab(Path(args.out), Path(args.historical), Path(args.prepared)))
        elif args.command == "lab":
            from .lab import build_lab
            print(build_lab(Path(args.results), Path(args.historical), Path(args.prepared),
                            Path(args.output) if args.output else None))
        elif args.command == "verify-experiments":
            from .experiments import verify_experiment_run
            from .integrity import verify_artifact_seal
            verify_artifact_seal(Path(args.results), require_complete=True)
            print(json.dumps(verify_experiment_run(Path(args.prepared), Path(args.results),
                                                   replay_selected=args.replay_selected), indent=2))
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"ERROR: {error}\n")


if __name__ == "__main__":
    main()
