#!/usr/bin/env python3
"""Stage the unchanged historical ten tests with their original directory layout."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from reproduce_decision_history import INPUTS, ROOT


def main():
    with tempfile.TemporaryDirectory(prefix="erkidu-history-tests-") as td:
        stage = Path(td)
        for name in ("erkidu_two_call.py", "test_erkidu_two_call.py"):
            shutil.copyfile(ROOT / "scripts/historical" / name, stage / name)
        (stage / "inputs").mkdir()
        for name, location in INPUTS.items():
            (stage / "inputs" / name).symlink_to(ROOT / location)
        (stage / "run_001").symlink_to(ROOT / "results/decision_engine/recovery/reproduced_956")
        env = dict(os.environ, PYTHONPATH=str(stage), OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        completed = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(stage),
                                    "-p", "test_*.py", "-v"], cwd=stage, env=env)
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
