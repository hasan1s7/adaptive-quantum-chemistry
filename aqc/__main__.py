"""Run `python -m aqc --help`. No live computational chemistry is invoked."""
from __future__ import annotations

import argparse
import json
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
    if out.exists() and any(out.iterdir()):
        raise ValueError("Reproduction output must be empty")
    original = json.loads((run / "evaluation_seal.json").read_text())
    for name, sha in original["artifact_sha256"].items():
        if sha256_file(run / name) != sha:
            raise ValueError(f"Sealed run artifact altered: {name}")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(run / "frozen_config.json", out / "frozen_config.json")
    env = json.loads((run / "environment.json").read_text())
    evaluate(run / "prepared", out, env["bootstrap"], env["bootstrap_seed"])
    actual = json.loads((out / "evaluation_seal.json").read_text())
    if actual != original:
        raise ValueError("Reproduction failed: output checksums differ")
    from .dashboard import build_dashboard
    build_dashboard(out)
    print("Reproduction passed: all sealed evaluation artifacts match byte for byte.")


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
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"ERROR: {error}\n")


if __name__ == "__main__":
    main()
