from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[2]
FORMAL_EXECUTOR = REPO_ROOT / "scripts/deploy_legacy_observed_runtime.py"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(TEST_DIR))

from test_deploy_legacy_observed_runtime import ExecutorFixture  # noqa: E402


def _append_json_line(path: Path, value: dict[str, object]) -> None:
    """Append one sanitized fake-runner event for parent-process assertions."""
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")


class SignalFakeRunner:
    """Fake all Docker, Compose and backup commands while pausing at migration."""

    def __init__(self, log_path: Path, ready_path: Path, result_type: type[object]) -> None:
        self.log_path = log_path
        self.ready_path = ready_path
        self.result_type = result_type
        self.expected_image = "sha256:" + "a" * 64
        self.expected_revision = "b" * 40
        self.jobs: dict[str, dict[str, str]] = {}

    def _result(self, returncode: int, stdout: str = "", stderr: str = "") -> object:
        return self.result_type(returncode, stdout, stderr)

    def run(self, argv: Sequence[str], *, timeout: int = 3600) -> object:
        """Record and answer a single command without calling external services."""
        command = tuple(str(value) for value in argv)
        event: dict[str, object] = {"kind": "command", "argv": list(command)}
        text = " ".join(command)
        if command[:2] == ("docker", "compose") and "version" in command:
            _append_json_line(self.log_path, event)
            return self._result(0)
        if command[:3] == ("docker", "image", "inspect"):
            _append_json_line(self.log_path, event)
            output = (
                self.expected_revision
                if "org.opencontainers.image.revision" in text
                else self.expected_image
            )
            return self._result(0, output + "\n")
        if command[:2] == ("docker", "info"):
            _append_json_line(self.log_path, event)
            return self._result(0, "fake-daemon-id\n")
        if command[:2] == ("docker", "ps"):
            filter_value = command[command.index("--filter") + 1]
            name = filter_value.removeprefix("name=^/").removesuffix("$")
            _append_json_line(self.log_path, event)
            return self._result(0, f"{name}\n" if name in self.jobs else "")
        if command[:2] == ("docker", "inspect"):
            name = command[-1]
            job = self.jobs.get(name)
            if job is None:
                _append_json_line(self.log_path, event)
                return self._result(1, stderr="no such container")
            event["job_status"] = job["status"]
            _append_json_line(self.log_path, event)
            details = f"/{name}|{job['attempt']}|{job['image']}|{job['running']}|{job['status']}\n"
            return self._result(0, details)
        if command[:2] == ("docker", "stop"):
            job = self.jobs.get(command[-1])
            if job is not None:
                job["running"] = "false"
                job["status"] = "exited"
                event["job_status"] = "exited"
            _append_json_line(self.log_path, event)
            return self._result(0, command[-1] + "\n")
        if "infra-capture" in command:
            output = Path(command[command.index("--output") + 1])
            output.write_text('{"schema":"fake-infra"}\n', encoding="utf-8")
        if "check_legacy_migration_preservation.py" in text and "capture" in command:
            output = Path(command[command.index("--snapshot-json") + 1])
            output.write_text('{"schema":"fake-preservation"}\n', encoding="utf-8")
        if "vps-backup.sh" in text:
            root = Path(command[command.index("--backup-dir") + 1])
            database = root / "database"
            metadata = root / "meta"
            database.mkdir(parents=True)
            metadata.mkdir()
            dump = database / "postgres-test.dump"
            dump.write_bytes(b"fake database backup")
            import hashlib

            digest = hashlib.sha256(dump.read_bytes()).hexdigest()
            manifest = metadata / "manifest-test.txt"
            manifest.write_text(f"{digest}  {dump}\n", encoding="utf-8")
            _append_json_line(self.log_path, event)
            return self._result(0, f"[INFO] Manifest: {manifest}\n")
        if "run" in command and "migrator" in command:
            name = command[command.index("--name") + 1]
            label = command[command.index("--label") + 1]
            self.jobs[name] = {
                "attempt": label.split("=", 1)[1],
                "image": self.expected_image,
                "running": "true",
                "status": "running",
            }
            event["kind"] = "migrator_blocked"
            event["job_name"] = name
            event["sigterm_handler"] = getattr(signal.getsignal(signal.SIGTERM), "__name__", "")
            _append_json_line(self.log_path, event)
            self.ready_path.write_text("ready\n", encoding="utf-8")
            while True:
                signal.pause()
                # A handled nonterminal signal may wake pause without raising.
                self.ready_path.with_suffix(".resumed").write_text("resumed\n", encoding="utf-8")
        _append_json_line(self.log_path, event)
        return self._result(0)


def _load_formal_module(path: Path) -> ModuleType:
    """Load the repository-owned executor without importing the temp proposal."""
    spec = importlib.util.spec_from_file_location("formal_observed_deploy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("formal executor import spec unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _child_main(
    formal_path: Path,
    config_path: Path,
    log_path: Path,
    ready_path: Path,
    status_path: Path,
) -> int:
    """Patch only config and runner, then invoke formal main and signal handler."""
    module = _load_formal_module(formal_path)
    values = json.loads(config_path.read_text(encoding="utf-8"))
    config = module.Config(
        Path(values["target"]),
        values["tag"],
        values["source_sha"],
        values["rehearsal_sha"],
        values["image_id"],
        Path(values["baseline"]),
        values["baseline_sha"],
        Path(values["compatibility"]),
        values["compatibility_sha"],
        Path(values["report_dir"]),
        values["env"],
        values["attempt_id"],
    )
    original_handler = module._handle_interrupt

    def recording_handler(signum: int, frame: object) -> None:
        _append_json_line(log_path, {"kind": "signal_received", "signum": signum})
        original_handler(signum, frame)

    module._handle_interrupt = recording_handler

    def nonterminal_handler(signum: int, frame: object) -> None:
        _append_json_line(log_path, {"kind": "nonterminal_signal", "signum": signum})

    signal.signal(signal.SIGUSR1, nonterminal_handler)
    module.Config.load = classmethod(lambda cls, env: config)
    fake_runner = SignalFakeRunner(log_path, ready_path, module.Result)
    module.SubprocessRunner = lambda: fake_runner
    status = module.main()
    status_path.write_text(f"{status}\n", encoding="ascii")
    return status


class RealSignalHandlerSubprocessTests(unittest.TestCase):
    """Exercise the production signal handler in a disposable POSIX child."""

    @unittest.skipUnless(
        os.name == "posix" and hasattr(signal, "SIGTERM"),
        "real child-process SIGTERM delivery is POSIX-only",
    )
    def test_sigterm_during_migrator_quiesces_job_without_legacy_start(self) -> None:
        fixture = ExecutorFixture(methodName="runTest")
        config, _, target, _, _ = fixture.make_fixture()
        current = target / "current"
        previous = target / "previous"
        current.symlink_to(Path("releases") / "20261101013730", target_is_directory=True)
        previous.symlink_to(Path("releases") / "20261101013730", target_is_directory=True)

        with tempfile.TemporaryDirectory(prefix="observed-sigterm-") as temp_name:
            temp = Path(temp_name)
            config_path = temp / "config.json"
            log_path = temp / "events.jsonl"
            ready_path = temp / "migrator.ready"
            status_path = temp / "status.txt"
            values = {
                "target": str(config.target),
                "tag": config.tag,
                "source_sha": config.source_sha,
                "rehearsal_sha": config.rehearsal_sha,
                "image_id": config.image_id,
                "baseline": str(config.baseline),
                "baseline_sha": config.baseline_sha,
                "compatibility": str(config.compatibility),
                "compatibility_sha": config.compatibility_sha,
                "report_dir": str(config.report_dir),
                "env": dict(config.env),
                "attempt_id": config.attempt_id,
            }
            config_path.write_text(json.dumps(values), encoding="utf-8")
            command = (
                sys.executable,
                str(Path(__file__).resolve()),
                "--child",
                str(FORMAL_EXECUTOR),
                str(config_path),
                str(log_path),
                str(ready_path),
                str(status_path),
            )
            process = subprocess.Popen(
                command,
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 15
                while not ready_path.exists():
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        self.fail(f"child exited before migrator gate: {stdout}\n{stderr}")
                    if time.monotonic() >= deadline:
                        self.fail("child did not reach the blocked migrator")
                    time.sleep(0.02)
                os.kill(process.pid, signal.SIGUSR1)
                resume_deadline = time.monotonic() + 5
                while not ready_path.with_suffix(".resumed").exists():
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        self.fail(f"nonterminal signal ended child: {stdout}\n{stderr}")
                    if time.monotonic() >= resume_deadline:
                        self.fail("child did not resume waiting after nonterminal signal")
                    time.sleep(0.01)
                self.assertIsNone(process.poll(), "child exited before direct SIGTERM")
                self.assertFalse(
                    list(config.report_dir.glob("agomtradepro-observed-deploy-*.json")),
                    "nonterminal signal prematurely produced a deployment report",
                )
                os.kill(process.pid, signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=15)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

            self.assertEqual(process.returncode, 70, f"child output:\n{stdout}\n{stderr}")
            self.assertEqual(status_path.read_text(encoding="ascii").strip(), "70")
            events = [
                json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
            ]
            signal_index = next(
                i
                for i, event in enumerate(events)
                if event.get("kind") == "signal_received" and event.get("signum") == signal.SIGTERM
            )
            nonterminal_index = next(
                i
                for i, event in enumerate(events)
                if event.get("kind") == "nonterminal_signal"
                and event.get("signum") == signal.SIGUSR1
            )
            migrator_index = next(
                i for i, event in enumerate(events) if event.get("kind") == "migrator_blocked"
            )
            self.assertEqual(events[migrator_index]["sigterm_handler"], "recording_handler")
            stop_index = next(
                i
                for i, event in enumerate(events)
                if event.get("argv", [])[:2] == ["docker", "stop"]
            )
            self.assertLess(migrator_index, signal_index)
            self.assertLess(nonterminal_index, signal_index)
            self.assertLess(signal_index, stop_index)
            self.assertTrue(
                any(
                    event.get("kind") == "command"
                    and event.get("argv", [])[:2] == ["docker", "info"]
                    for event in events[:stop_index]
                )
            )
            stopped_inspections = [
                event
                for event in events[stop_index + 1 :]
                if event.get("argv", [])[:2] == ["docker", "inspect"]
            ]
            self.assertTrue(stopped_inspections)
            self.assertEqual(stopped_inspections[-1].get("job_status"), "exited")
            old_writer_starts = [
                event
                for event in events
                if event.get("argv", [])[:2] == ["docker", "compose"]
                and "up" in event.get("argv", [])
                and "20261101013730" in " ".join(event.get("argv", []))
            ]
            self.assertEqual(old_writer_starts, [])
            report_path = config.report_dir / (
                f"agomtradepro-observed-deploy-{config.tag}-{config.attempt_id}.json"
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["outcome"], "restore_unverified")
            self.assertTrue(report["migration_started"])
            self.assertFalse(report["legacy_schema_verified"])
            self.assertTrue(report["ownjobs_quiesced"])
            self.assertFalse(report["baseline_retired"])
            self.assertTrue(report["forward_recovery_required"])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        raise SystemExit(
            _child_main(
                Path(sys.argv[2]),
                Path(sys.argv[3]),
                Path(sys.argv[4]),
                Path(sys.argv[5]),
                Path(sys.argv[6]),
            )
        )
    unittest.main()
