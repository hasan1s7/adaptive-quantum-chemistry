"""Launcher and read-only diagnostic contracts, without scientific packages.

The Windows launcher is executed only on Windows. Passing POSIX tests or
inspecting a batch file is not a substitute for installed-device acceptance.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("aqc_launcher_doctor", ROOT / "scripts/doctor.py")
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)
SH = shutil.which("sh")


def make_application(folder, exit_code=0):
    (folder / "aqc_app").mkdir(parents=True)
    (folder / "aqc_app/__init__.py").write_text("")
    (folder / "aqc_app/__main__.py").write_text(
        "import json,os,sys\n"
        "print(json.dumps({'argv':sys.argv[1:],'cwd':os.getcwd(),"
        "'scientific_imports':[m for m in ['numpy','matplotlib','rdkit'] if m in sys.modules],"
        "'automatic_install':os.environ.get('PYTHON_MANAGER_AUTOMATIC_INSTALL')}))\n"
        f"raise SystemExit({exit_code})\n"
    )
    return folder


@unittest.skipUnless(SH and os.name != "nt", "POSIX shell required")
class PosixLauncherTests(unittest.TestCase):
    def run_launcher(self, folder, arguments=(), env=None):
        environment = dict(os.environ)
        environment.pop("AQC_PYTHON", None)
        environment.update(env or {})
        return subprocess.run([SH, str(folder / "start-aqc.sh"), *arguments],
                              cwd=folder.parent, env=environment, capture_output=True,
                              text=True, timeout=10)

    def fixture(self, directory, exit_code=0):
        folder = make_application(Path(directory) / "AQC folder with spaces", exit_code)
        shutil.copyfile(ROOT / "start-aqc.sh", folder / "start-aqc.sh")
        return folder

    def test_launch_from_another_directory_preserves_arguments_and_needs_no_science(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.fixture(directory)
            args = ["--port", "9812", "--no-open", "literal space; $(not-a-command)"]
            result = self.run_launcher(folder, args, {"AQC_PYTHON": sys.executable})
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(result.stdout.splitlines()[-1])
            self.assertEqual(record["argv"], args)
            self.assertEqual(Path(record["cwd"]), folder)
            self.assertEqual(record["scientific_imports"], [])

    def test_application_failure_exit_code_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.fixture(directory, exit_code=37)
            result = self.run_launcher(folder, env={"AQC_PYTHON": sys.executable})
            self.assertEqual(result.returncode, 37)

    def test_invalid_explicit_interpreter_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.fixture(directory)
            result = self.run_launcher(folder, env={"AQC_PYTHON": str(folder / "not installed")})
            self.assertEqual(result.returncode, 2)
            self.assertIn("AQC_PYTHON", result.stderr)
            self.assertNotIn("Starting AQC", result.stdout)

    def test_incompatible_interpreter_is_rejected_before_app_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.fixture(directory)
            fake = folder / "incompatible-python"
            fake.write_text("#!/bin/sh\nexit 1\n")
            fake.chmod(0o755)
            result = self.run_launcher(folder, env={"AQC_PYTHON": str(fake)})
            self.assertEqual(result.returncode, 2)
            self.assertIn("3.10 or newer", result.stderr)

    def test_missing_application_has_a_useful_extraction_error(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            shutil.copyfile(ROOT / "start-aqc.sh", folder / "start-aqc.sh")
            result = self.run_launcher(folder, env={"AQC_PYTHON": sys.executable})
            self.assertEqual(result.returncode, 2)
            self.assertIn("Extract the complete", result.stderr)

    def test_system_python_is_found_without_a_virtual_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.fixture(directory)
            commands = folder / "commands"
            commands.mkdir()
            (commands / "python3").symlink_to(sys.executable)
            (commands / "dirname").symlink_to(shutil.which("dirname"))
            result = self.run_launcher(folder, ["--no-open"], {"PATH": str(commands)})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout.splitlines()[-1])["argv"], ["--no-open"])

    def test_missing_python_does_not_attempt_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.fixture(directory)
            commands = folder / "commands"
            commands.mkdir()
            (commands / "dirname").symlink_to(shutil.which("dirname"))
            result = self.run_launcher(folder, env={"PATH": str(commands)})
            self.assertEqual(result.returncode, 2)
            self.assertIn("Python 3.10 or newer was not found", result.stderr)
            self.assertIn("Install Python separately", result.stderr)

    def test_existing_virtual_environment_is_used_without_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.fixture(directory)
            executable = folder / ".venv/bin/python"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + ' "$@"\n')
            executable.chmod(0o755)
            commands = folder / "commands"
            commands.mkdir()
            (commands / "dirname").symlink_to(shutil.which("dirname"))
            result = self.run_launcher(folder, env={"PATH": str(commands)})
            self.assertEqual(result.returncode, 0, result.stderr)


class WindowsLauncherTests(unittest.TestCase):
    def test_batch_launcher_disables_both_runtime_install_mechanisms(self):
        source = (ROOT / "start-aqc.cmd").read_text()
        self.assertIn('set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"', source)
        self.assertIn('set "PYLAUNCHER_ALLOW_INSTALL="', source)
        self.assertIn('set "PYLAUNCHER_ALWAYS_INSTALL="', source)
        self.assertIn('set "PYLAUNCHER_DRYRUN="', source)
        self.assertIn("DisableDelayedExpansion", source)
        self.assertNotIn("pip install", source)
        self.assertNotIn("py install", source)

    @unittest.skipUnless(os.name == "nt", "Native Windows execution is not available in this environment")
    def test_native_windows_launch_path_spaces_flags_and_no_optional_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = make_application(Path(directory) / "AQC folder with spaces")
            shutil.copyfile(ROOT / "start-aqc.cmd", folder / "start-aqc.cmd")
            env = dict(os.environ, AQC_PYTHON=sys.executable, AQC_NO_PAUSE="1")
            result = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c",
                                     str(folder / "start-aqc.cmd"), "--port", "9812", "--no-open"],
                                    cwd=folder.parent, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(result.stdout.splitlines()[-1])
            self.assertEqual(record["argv"], ["--port", "9812", "--no-open"])
            self.assertEqual(record["scientific_imports"], [])
            self.assertEqual(record["automatic_install"], "false")


class DoctorTests(unittest.TestCase):
    def test_hash_mismatch_and_path_escape_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path = folder / "evidence.txt"
            path.write_text("original")
            expected = doctor.sha256(path)
            self.assertEqual(doctor.verify_hashes(folder, {path.name: expected}), 1)
            path.write_text("changed")
            with self.assertRaisesRegex(ValueError, "Checksum differs"):
                doctor.verify_hashes(folder, {path.name: expected})
            for name in ["../outside", "/absolute", "a/../../outside", "a\\outside", "C:/absolute"]:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    doctor.safe_path(folder, name)

    def test_duplicate_json_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text('{"schema_version":1,"schema_version":2}')
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                doctor.read_json(path)

    def test_changed_validator_is_never_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "aqc").mkdir()
            (folder / "aqc/integrity.py").write_text("raise RuntimeError('UNTRUSTED VALIDATOR EXECUTED')")
            (folder / "results/lab").mkdir(parents=True)
            registry = {"source_code_sha256": {"integrity.py": "0" * 64}}
            registry["registry_sha256"] = doctor.digest(registry)
            (folder / "results/lab/experiment_registry.json").write_text(json.dumps(registry))
            report = doctor.diagnose(folder, port=None)
            source = next(check for check in report["checks"] if check["name"] == "frozen_scientific_source")
            self.assertEqual(source["status"], "fail")
            self.assertIn("Checksum differs", source["detail"])
            self.assertFalse(report["app_ready"])

    def test_missing_scientific_distributions_are_optional_and_not_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "requirements.txt").write_text("numpy==2.3.5\nrdkit==2025.9.6\n")
            before = set(sys.modules)
            with patch.object(doctor.importlib.metadata, "version", side_effect=importlib.metadata.PackageNotFoundError):
                result = doctor.scientific_dependencies(folder)
            self.assertEqual([item["installed"] for item in result], [None, None])
            self.assertTrue(all(item["required_to_open_app"] is False for item in result))
            self.assertFalse({"numpy", "rdkit"} & (set(sys.modules) - before))

    def test_port_probe_uses_loopback_and_reports_an_occupied_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            port = occupied.getsockname()[1]
            with self.assertRaises(OSError):
                doctor.check_port(port)

    def test_port_argument_validation(self):
        self.assertEqual(doctor.port_number("8765"), 8765)
        for value in ["0", "65536", "-1", "localhost", "1.5"]:
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                doctor.port_number(value)

    @unittest.skipUnless((ROOT / "results/lab/evaluation_seal.json").exists(), "Bundled real evidence required")
    def test_actual_diagnostics_run_with_site_packages_disabled(self):
        result = subprocess.run([sys.executable, "-S", str(ROOT / "scripts/doctor.py"),
                                 "--json", "--science", "--no-port-check"],
                                cwd=ROOT.parent, capture_output=True, text=True, timeout=40)
        self.assertIn(result.returncode, [0, 1], result.stderr)
        report = json.loads(result.stdout)
        checks = {check["name"]: check for check in report["checks"]}
        for name in ["python_runtime", "frozen_scientific_source", "app_summary_evidence", "prepared_data",
                     "expanded_evidence", "historical_evidence", "development_geometry", "historical_release"]:
            self.assertEqual(checks[name]["status"], "pass", checks[name])
        self.assertFalse(report["network_accessed"])
        self.assertFalse(report["files_modified"])
        self.assertTrue(all(not item["required_to_open_app"] for item in report["optional_scientific_dependencies"]))

    def test_doctor_summary_allowlist_matches_the_application(self):
        from aqc_app.data import DevelopmentStore
        self.assertEqual(set(doctor.APP_SUMMARY_FILES), set(DevelopmentStore.SUMMARY_FILES))

    @unittest.skipUnless((ROOT / "results/lab/decision_ledger.jsonl.gz").exists(), "Restored real evidence required")
    def test_missing_full_ledger_does_not_mislabel_saved_app_as_unusable(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            # Recreate the Git-clone shape without copying its large restored
            # ledger. Originals are read-only; no scientific bytes are edited.
            for name in ["aqc", "aqc_app", "app", "results/lab", "results/real",
                         "results/fixture", "releases/v0.1.0"]:
                shutil.copytree(ROOT / name, folder / name,
                                ignore=shutil.ignore_patterns("__pycache__", "decision_ledger.jsonl.gz"))
            (folder / "data").mkdir()
            for name in ["development_geometry.json.gz", "development_geometry_manifest.json",
                         "upstream_lock.json", "source_snapshot.tar.gz"]:
                shutil.copyfile(ROOT / "data" / name, folder / "data" / name)
            report = doctor.diagnose(folder, port=None)
            self.assertTrue(report["app_ready"], report["checks"])
            self.assertFalse(report["full_evidence_ready"])
            self.assertFalse(report["ok"])
            failure = next(check for check in report["checks"] if check["name"] == "expanded_evidence")
            self.assertIn("decision_ledger.jsonl.gz", failure["detail"])
            self.assertFalse(failure["app_required"])


if __name__ == "__main__":
    unittest.main()
