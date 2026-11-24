from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import patch

from scripts.deploy_legacy_observed_runtime import (
    Blocked,
    Config,
    Executor,
    Result,
    SubprocessRunner,
)


class FakeRunner:
    def __init__(
        self,
        *,
        failure: str = "",
        running_job_on_failure: bool = False,
        interrupt_job_on_failure: bool = False,
        fail_worker_stop: bool = False,
    ) -> None:
        self.failure = failure
        self.running_job_on_failure = running_job_on_failure
        self.interrupt_job_on_failure = interrupt_job_on_failure
        self.fail_worker_stop = fail_worker_stop
        self.commands: list[tuple[str, ...]] = []
        self.current_at_events: list[tuple[str, str]] = []
        self.override_contents: list[bytes] = []
        self.jobs: dict[str, dict[str, str]] = {}
        self.running_services: set[str] = set()
        self.expected_image = "sha256:" + "a" * 64
        self.expected_revision = "b" * 40

    def run(self, argv: Sequence[str], *, timeout: int = 3600) -> Result:
        command = tuple(str(value) for value in argv)
        self.commands.append(command)
        for index, value in enumerate(command[:-1]):
            if value == "-f" and ".observed-phase-a-" in command[index + 1]:
                self.override_contents.append(Path(command[index + 1]).read_bytes())
        text = " ".join(command)
        if command[0] == "curl":
            return Result(0, '{"status":"ok"}\n200')
        if "import qlib,qlib.data" in text:
            return Result(0, '{"distribution":"pyqlib","version":"0.9.7"}')
        if command[:2] == ("docker", "info"):
            return Result(0, "fake-daemon-id\n")
        if command[:2] == ("docker", "ps"):
            filter_value = command[command.index("--filter") + 1]
            name = filter_value.removeprefix("name=^/").removesuffix("$")
            return Result(0, f"{name}\n" if name in self.jobs else "")
        if command[:2] == ("docker", "inspect"):
            name = command[-1]
            job = self.jobs.get(name)
            if job is None:
                return Result(1, stderr="no such container")
            values = f"/{name}|{job['attempt']}|{job['image']}|{job['running']}|{job['status']}\n"
            return Result(0, values)
        if command[:2] == ("docker", "stop"):
            if self.fail_worker_stop:
                return Result(1, stderr="injected owned job stop failure")
            job = self.jobs.get(command[-1])
            if job is not None:
                job["running"] = "false"
                job["status"] = "exited"
            return Result(0, command[-1] + "\n")
        if (
            self.fail_worker_stop
            and "stop" in command
            and "celery_worker" in command
            and "source-" in text
        ):
            return Result(1, stderr="injected phase B worker stop failure")
        if "docker compose version" in text or "docker-compose version" in text:
            return Result(0)
        if command[:2] == ("docker", "compose"):
            if "up" in command and "-d" in command:
                index = command.index("up")
                self.running_services.update(
                    value
                    for value in command[index + 1 :]
                    if value
                    in {
                        "web",
                        "celery_worker",
                        "celery_qlib_worker",
                        "celery_beat",
                        "terminal_agent_worker",
                    }
                )
            elif "stop" in command:
                index = command.index("stop")
                self.running_services.difference_update(
                    value
                    for value in command[index + 1 :]
                    if value
                    in {
                        "web",
                        "celery_worker",
                        "celery_qlib_worker",
                        "celery_beat",
                        "terminal_agent_worker",
                    }
                )
        if "docker image inspect" in text:
            return Result(
                0, self.expected_revision if "org.opencontainers" in text else self.expected_image
            )
        if "infra-capture" in text:
            output = Path(command[command.index("--output") + 1])
            output.write_text('{"schema":"test-infra"}', encoding="utf-8")
            return Result(0)
        if "check_legacy_migration_preservation.py" in text and "capture" in command:
            output = Path(command[command.index("--snapshot-json") + 1])
            output.write_text('{"schema":"test-preservation"}', encoding="utf-8")
            return Result(0)
        if "vps-backup.sh" in text:
            root = Path(command[command.index("--backup-dir") + 1])
            database = root / "database"
            metadata = root / "meta"
            database.mkdir(parents=True)
            metadata.mkdir()
            dump = database / "postgres-test.dump"
            dump.write_bytes(b"fake verified dump")
            manifest = metadata / "manifest-test.txt"
            digest = hashlib.sha256(dump.read_bytes()).hexdigest()
            manifest.write_text(f"{digest}  {dump}\n", encoding="utf-8")
            return Result(0, f"[INFO] Manifest: {manifest}\n")
        if "observed_deploy_runtime_checks.py" in text and "workers-stopped" in text:
            workers = {
                "celery_worker",
                "celery_qlib_worker",
                "celery_beat",
                "terminal_agent_worker",
            }
            if self.running_services & workers:
                return Result(1, stderr="injected running worker")
        is_phase_b_candidate_failure = (
            self.failure == "phase-b-candidate-check"
            and "candidate-app-check" in text
            and "--phase b" in text
        )
        if self.failure and (self.failure in text or is_phase_b_candidate_failure):
            if self.running_job_on_failure and "run" in command and "--name" in command:
                name = command[command.index("--name") + 1]
                label = command[command.index("--label") + 1]
                self.jobs[name] = {
                    "attempt": label.split("=", 1)[1],
                    "image": self.expected_image,
                    "running": "true",
                    "status": "running",
                }
                if self.interrupt_job_on_failure:
                    raise Blocked("OBSERVED_DEPLOY_INTERRUPTED")
            return Result(1, stderr="injected failure; sensitive-value-must-not-be-reported")
        return Result(0)


class FakePointers:
    """Model only current/previous symlink replacements on Windows test hosts."""

    def __init__(self, target: Path) -> None:
        self.links = {
            target / "current": "releases/20261101013730",
            target / "previous": "releases/20261101013730",
        }
        self.pending: dict[Path, str] = {}
        self.stack = []

    def __enter__(self) -> FakePointers:
        path_is_symlink = Path.is_symlink
        path_exists = Path.exists
        path_resolve = Path.resolve
        os_readlink = os.readlink
        os_replace = os.replace

        def is_symlink(path: Path) -> bool:
            return path in self.links or path in self.pending or path_is_symlink(path)

        def exists(path: Path) -> bool:
            return path in self.links or path in self.pending or path_exists(path)

        def resolve(path: Path, strict: bool = False) -> Path:
            target = self.links.get(path) or self.pending.get(path)
            if target is None:
                return path_resolve(path, strict=strict)
            raw = Path(target)
            resolved = raw if raw.is_absolute() else path.parent / raw
            return path_resolve(resolved, strict=strict)

        def symlink_to(path: Path, target: str | Path, target_is_directory: bool = False) -> None:
            self.pending[path] = str(target)

        def readlink(path: str | os.PathLike[str]) -> str:
            key = Path(path)
            return self.links[key] if key in self.links else os_readlink(path)

        def replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
            src, dst = Path(source), Path(destination)
            if src in self.pending:
                self.links[dst] = self.pending.pop(src)
                return
            os_replace(source, destination)

        self.stack = [
            patch.object(Path, "is_symlink", is_symlink),
            patch.object(Path, "exists", exists),
            patch.object(Path, "resolve", resolve),
            patch.object(Path, "symlink_to", symlink_to),
            patch("os.readlink", readlink),
            patch("os.replace", replace),
        ]
        for item in self.stack:
            item.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        for item in reversed(self.stack):
            item.stop()


class ExecutorFixture(unittest.TestCase):
    def make_fixture(self, *, failure: str = "") -> tuple[Config, FakeRunner, Path, Path, bytes]:
        temp = Path(tempfile.mkdtemp(prefix="observed-executor-"))
        target = temp / "opt/agomtradepro"
        old = target / "releases/20261101013730"
        release_tag = "20261117153000"
        candidate = target / f"releases/source-{release_tag}"
        (old / "docker").mkdir(parents=True)
        (old / "deploy").mkdir()
        (old / ".agom-release-manifest.json").mkdir()
        (candidate / "docker").mkdir(parents=True)
        (candidate / "deploy").mkdir()
        scripts = candidate / "scripts"
        scripts.mkdir()
        for name in (
            "capture_legacy_observed_runtime.py",
            "observed_deploy_runtime_checks.py",
            "verify_legacy_observed_native_compatibility.py",
            "check_legacy_migration_preservation.py",
            "vps-backup.sh",
        ):
            (scripts / name).write_text("# fake test hook\n", encoding="utf-8")
        (old / "docker/docker-compose.vps.yml").write_text("services: {}\n", encoding="utf-8")
        (candidate / "docker/docker-compose.vps.yml").write_text("services: {}\n", encoding="utf-8")
        old_env = (
            b"WEB_IMAGE=agomtradepro-web:20261101013730\n"
            b"DOMAIN=observed-test.invalid\n"
            b"POSTGRES_PASSWORD=secret-fixture-value\n"
            b"AGOMTRADEPRO_CHECK_DEPLOY_ON_START=0\n"
            b"AGOMTRADEPRO_AUTO_MIGRATE_ON_START=0\n"
            b"AGOMTRADEPRO_BOOTSTRAP_ON_START=0\n"
            b"AGOMTRADEPRO_COLLECTSTATIC_ON_START=0\n"
            b"AGOMTRADEPRO_SETUP_SCHEDULE_ON_START=0\n"
            b"AGOMTRADEPRO_ENSURE_SUPERUSER_ON_START=0\n"
            b"AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START=0\n"
            b"MACRO_SYNC_HOUR=8\nMACRO_SYNC_MINUTE=5\n"
        )
        (old / "deploy/.env").write_bytes(old_env)
        os.chmod(old / "deploy/.env", 0o600)
        image_id = "sha256:" + "a" * 64
        source_sha = "b" * 40
        manifest = {
            "version": 1,
            "release_tag": release_tag,
            "source_commit": source_sha,
            "image_tag": f"agomtradepro-web:{release_tag}",
            "image_id": image_id,
            "build_started_at": "2026-11-17T15:00:00Z",
            "build_finished_at": "2026-11-17T15:01:00Z",
            "source_mode": "git-clone",
        }
        manifest_path = candidate / ".agom-release-manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        os.chmod(manifest_path, 0o444)
        marker = target / ".postgres-migration-complete"
        marker.write_text("complete\n", encoding="utf-8")
        baseline = temp / "baseline.json"
        baseline.write_text('{"schema":"baseline"}\n', encoding="utf-8")
        compatibility = temp / "compatibility.json"
        compatibility.write_text('{"schema":"compat"}\n', encoding="utf-8")
        report_dir = temp / "reports"
        report_dir.mkdir()
        env = {
            "TARGET_DIR": "/opt/agomtradepro",
            "RELEASE_TAG": release_tag,
            "SOURCE_COMMIT": source_sha,
            "RELEASE_REHEARSAL_SHA256": "c" * 64,
            "REHEARSAL_IMAGE_ID": image_id,
            "OBSERVED_ROLLBACK_BASELINE_JSON": str(baseline),
            "OBSERVED_ROLLBACK_BASELINE_SHA256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
            "OBSERVED_ROLLBACK_COMPATIBILITY_JSON": str(compatibility),
            "OBSERVED_ROLLBACK_COMPATIBILITY_SHA256": hashlib.sha256(
                compatibility.read_bytes()
            ).hexdigest(),
            "ACTION": "upgrade",
            "AUTO_ROLLBACK": "1",
            "PRESERVE_DATA_CENTER_CATALOG": "1",
            "SKIP_PREDEPLOY_BACKUP": "0",
            "WIPE_DOCKER": "0",
            "WIPE_VOLUMES": "0",
            "INCLUDE_SQLITE": "0",
            "ENABLE_CELERY": "1",
        }
        config = Config(
            target,
            release_tag,
            source_sha,
            "c" * 64,
            image_id,
            baseline,
            env["OBSERVED_ROLLBACK_BASELINE_SHA256"],
            compatibility,
            env["OBSERVED_ROLLBACK_COMPATIBILITY_SHA256"],
            report_dir,
            env,
            "d" * 32,
        )
        return config, FakeRunner(failure=failure), target, old, old_env


class ExecutorSuccessTests(ExecutorFixture):
    def test_success_copies_only_web_image_and_runs_ordered_phase_b(self) -> None:
        config, runner, target, old, old_env = self.make_fixture()
        with FakePointers(target) as pointers:
            code = Executor(config, runner).execute()
        self.assertEqual(code, 0)
        modern_link = str(Path("releases") / f"source-{config.tag}")
        self.assertEqual(pointers.links[target / "current"], modern_link)
        self.assertEqual(pointers.links[target / "previous"], modern_link)
        self.assertEqual((old / "deploy/.env").read_bytes(), old_env)
        new_env = (config.release / "deploy/.env").read_bytes()
        self.assertEqual(
            [line for line in old_env.splitlines() if not line.startswith(b"WEB_IMAGE=")],
            [line for line in new_env.splitlines() if not line.startswith(b"WEB_IMAGE=")],
        )
        text = [" ".join(command) for command in runner.commands]
        self.assertTrue(any("--keep-days 0" in line and "--no-redis" in line for line in text))
        phase_b_start = next(
            index
            for index, command in enumerate(runner.commands)
            if "sync_ai_capability_catalog" in command
        )
        phase_a_web_runs = [
            command
            for command in runner.commands[:phase_b_start]
            if "run" in command and "web" in command
        ]
        self.assertEqual(len(phase_a_web_runs), 3)
        self.assertTrue(
            all(".observed-phase-a-" in " ".join(command) for command in phase_a_web_runs)
        )
        self.assertGreaterEqual(len(runner.override_contents), 4)
        self.assertTrue(
            all(
                b'PGOPTIONS: "-c default_transaction_read_only=on"' in content
                and b"sqlite_data:/app/data:ro" in content
                for content in runner.override_contents
            )
        )
        run_commands = [command for command in runner.commands if "run" in command]
        self.assertTrue(
            all("--name" in command and "--label" in command for command in run_commands)
        )
        self.assertNotIn("initialize_data_center_catalog", " ".join(text))
        migration = next(i for i, line in enumerate(text) if "migrator" in line)
        tui = next(i for i, line in enumerate(text) if "publish-tui-release.sh" in line)
        self.assertLess(migration, tui)
        enable = [
            i
            for i, command in enumerate(runner.commands)
            if "setup_audit_outbox_dispatch" in command
        ]
        self.assertEqual(len(enable), 1)
        self.assertGreater(
            enable[0], max(i for i, command in enumerate(runner.commands) if "curl" in command)
        )
        self.assertEqual(
            runner.commands[enable[0]][-2:], ("setup_audit_outbox_dispatch", "--ensure-enabled")
        )
        self.assertFalse(any(" down " in f" {line} " for line in text))
        report = next(config.report_dir.glob("agomtradepro-observed-deploy-*.json"))
        self.assertNotIn(b"secret-fixture-value", report.read_bytes())

    def test_wrapper_attempt_id_is_required_and_bound_to_report_name(self) -> None:
        config, _, _, _, _ = self.make_fixture()
        env = dict(config.env)
        env["OBSERVED_DEPLOY_ATTEMPT_ID"] = "e" * 32
        loaded = Config.load(env)
        self.assertEqual(loaded.attempt_id, "e" * 32)
        self.assertEqual(
            f"agomtradepro-observed-deploy-{loaded.tag}-{loaded.attempt_id}.json",
            Executor(loaded, FakeRunner()).report.name,
        )
        env.pop("OBSERVED_DEPLOY_ATTEMPT_ID")
        with self.assertRaisesRegex(Blocked, "OBSERVED_RUNTIME_INPUTS_INCOMPLETE"):
            Config.load(env)

    def test_subprocess_runner_drops_ambient_app_and_compose_overrides(self) -> None:
        ambient = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", "C:\\Users\\codex"),
            "DOCKER_CONFIG": "C:\\docker-config",
            "DOCKER_HOST": "tcp://untrusted.invalid:2375",
            "PYTHONPATH": "C:\\untrusted-python",
            "COMPOSE_FILE": "compose.injected.yml",
            "WEB_IMAGE": "attacker-image",
            "DATABASE_URL": "postgres://ambient-secret",
            "AGOMTRADEPRO_AUTO_MIGRATE_ON_START": "1",
        }
        with patch.dict(os.environ, ambient, clear=False):
            with patch("scripts.deploy_legacy_observed_runtime.subprocess.run") as subprocess_run:
                subprocess_run.return_value.returncode = 0
                subprocess_run.return_value.stdout = ""
                subprocess_run.return_value.stderr = ""
                SubprocessRunner().run(("docker", "compose", "version"))
        child_env = subprocess_run.call_args.kwargs["env"]
        self.assertEqual(child_env["DOCKER_CONTEXT"], "default")
        self.assertEqual(child_env["PATH"], ambient["PATH"])
        self.assertEqual(child_env["DOCKER_CONFIG"], ambient["DOCKER_CONFIG"])
        for key in (
            "DOCKER_HOST",
            "PYTHONPATH",
            "COMPOSE_FILE",
            "WEB_IMAGE",
            "DATABASE_URL",
            "AGOMTRADEPRO_AUTO_MIGRATE_ON_START",
        ):
            self.assertNotIn(key, child_env)


class ExecutorFailureTests(ExecutorFixture):
    def test_audit_schedule_failure_prevents_success_and_stops_candidate_workers(self) -> None:
        config, runner, target, _, _ = self.make_fixture(failure="setup_audit_outbox_dispatch")
        with FakePointers(target):
            self.assertEqual(Executor(config, runner).execute(), 23)
        report = next(config.report_dir.glob("agomtradepro-observed-deploy-*.json"))
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["outcome"], "partial")
        self.assertEqual(runner.running_services, {"web"})

    def test_phase_b_schema_failure_reads_back_readonly_fence_before_partial_report(self) -> None:
        config, _, target, _, _ = self.make_fixture()

        class PhaseBRunner(FakeRunner):
            def run(self, argv: Sequence[str], *, timeout: int = 3600) -> Result:
                if "AGOM_OBSERVED_MIGRATION_PHASE=phase_b" in argv:
                    self.commands.append(tuple(argv))
                    return Result(1, stderr="injected deferred migration failure")
                return super().run(argv, timeout=timeout)

        runner = PhaseBRunner()
        with FakePointers(target):
            status = Executor(config, runner).execute()
        self.assertEqual(status, 23)
        report = json.loads(
            next(config.report_dir.glob("agomtradepro-observed-deploy-*.json")).read_text()
        )
        self.assertFalse(report["full_schema_verified"])
        self.assertTrue(report["readonly_override_retained"])
        self.assertIsNotNone(report["baseline_retired_at"])
        commands = [" ".join(command) for command in runner.commands]
        failed = next(
            i for i, text in enumerate(commands) if "AGOM_OBSERVED_MIGRATION_PHASE=phase_b" in text
        )
        self.assertTrue(
            any(
                "candidate-app-check" in text and "--phase a" in text
                for text in commands[failed + 1 :]
            )
        )
        self.assertEqual(runner.running_services, {"web"})

    def test_unverified_old_runtime_is_stopped_after_restore_identity_failure(self) -> None:
        config, _, target, _, _ = self.make_fixture()

        class DriftRunner(FakeRunner):
            def run(self, argv: Sequence[str], *, timeout: int = 3600) -> Result:
                if "after_restore" in argv:
                    self.commands.append(tuple(argv))
                    return Result(1, stderr="injected legacy runtime drift")
                return super().run(argv, timeout=timeout)

        runner = DriftRunner(failure="check_encryption_readiness")
        with FakePointers(target):
            code = Executor(config, runner).execute()
        self.assertEqual(code, 70)
        self.assertFalse(runner.running_services)
        commands = [" ".join(command) for command in runner.commands]
        drift = next(i for i, text in enumerate(commands) if "after_restore" in text)
        stopped = next(
            i for i, text in enumerate(commands) if i > drift and " stop web celery_worker" in text
        )
        self.assertTrue(any("writers-stopped" in text for text in commands[stopped + 1 :]))

    def test_failed_old_restore_stop_reports_unquiesced_writers(self) -> None:
        config, _, target, _, _ = self.make_fixture()

        class UnquiescedRunner(FakeRunner):
            def run(self, argv: Sequence[str], *, timeout: int = 3600) -> Result:
                old_stop = "stop" in argv and "20261101013730" in " ".join(argv)
                if "after_restore" in argv or old_stop:
                    self.commands.append(tuple(argv))
                    return Result(1, stderr="injected recovery failure")
                if "writers-stopped" in argv and self.running_services:
                    self.commands.append(tuple(argv))
                    return Result(1, stderr="injected writers still running")
                return super().run(argv, timeout=timeout)

        runner = UnquiescedRunner(failure="check_encryption_readiness")
        with FakePointers(target):
            code = Executor(config, runner).execute()
        self.assertEqual(code, 70)
        self.assertTrue(runner.running_services)
        report = json.loads(
            next(config.report_dir.glob("agomtradepro-observed-deploy-*.json")).read_text()
        )
        self.assertEqual(report["reason_code"], "OBSERVED_LEGACY_RECOVERY_WRITERS_NOT_QUIESCED")

    def test_running_writer_gate_blocks_backup_and_restores_legacy_apps(self) -> None:
        config, runner, target, old, _ = self.make_fixture(failure="writers-stopped")
        with FakePointers(target) as pointers:
            code = Executor(config, runner).execute()
        self.assertEqual(code, 20)
        self.assertEqual(pointers.links[target / "current"], "releases/20261101013730")
        text = [" ".join(command) for command in runner.commands]
        self.assertTrue(any("writers-stopped" in line for line in text))
        self.assertFalse(any("vps-backup.sh" in line or "migrator" in line for line in text))
        self.assertTrue(any("--phase after_restore" in line for line in text))

    def test_duplicate_legacy_env_key_is_rejected_before_stopping_writers(self) -> None:
        config, runner, target, old, _ = self.make_fixture()
        old_env = old / "deploy/.env"
        old_env.write_bytes(old_env.read_bytes() + b"AGOMTRADEPRO_CHECK_DEPLOY_ON_START=1\n")
        with FakePointers(target):
            code = Executor(config, runner).execute()
        self.assertEqual(code, 2)
        self.assertFalse(any(" stop " in f" {' '.join(command)} " for command in runner.commands))
        report = json.loads(
            next(config.report_dir.glob("agomtradepro-observed-deploy-*.json")).read_text()
        )
        self.assertEqual(report["reason_code"], "OBSERVED_ENVIRONMENT_DUPLICATE_KEY")

    def test_inline_comment_cannot_enable_startup_migration_before_dml(self) -> None:
        config, runner, _, old, _ = self.make_fixture()
        old_env = old / "deploy/.env"
        old_env.write_bytes(
            old_env.read_bytes().replace(
                b"AGOMTRADEPRO_AUTO_MIGRATE_ON_START=0",
                b'AGOMTRADEPRO_AUTO_MIGRATE_ON_START="1" # comment',
            )
        )
        with FakePointers(config.target):
            code = Executor(config, runner).execute()
        self.assertEqual(code, 2)
        self.assertFalse(any("migrator" in command for command in runner.commands))
        self.assertFalse(any(" stop " in f" {' '.join(command)} " for command in runner.commands))
        report = json.loads(
            next(config.report_dir.glob("agomtradepro-observed-deploy-*.json")).read_text()
        )
        self.assertEqual(report["reason_code"], "OBSERVED_STARTUP_WRITE_FLAGS_UNSAFE")

    def test_inline_comment_cannot_enable_alpha_bootstrap_option(self) -> None:
        config, runner, _, _, _ = self.make_fixture()
        config.env["AGOMTRADEPRO_BOOTSTRAP_WITH_ALPHA"] = "1 # comment"
        with FakePointers(config.target):
            code = Executor(config, runner).execute()
        self.assertEqual(code, 2)
        self.assertFalse(any("docker compose" in command for command in runner.commands))
        report = json.loads(
            next(config.report_dir.glob("agomtradepro-observed-deploy-*.json")).read_text()
        )
        self.assertEqual(report["reason_code"], "OBSERVED_RUNTIME_OPTIONS_UNSAFE")

    def test_phase_a_migration_failure_restores_old_pointer_and_checks_identity(self) -> None:
        config, runner, target, old, _ = self.make_fixture(failure="migrator")
        with FakePointers(target) as pointers:
            code = Executor(config, runner).execute()
        self.assertEqual(code, 70)
        self.assertEqual(pointers.links[target / "current"], "releases/20261101013730")
        self.assertEqual(pointers.links[target / "previous"], "releases/20261101013730")
        text = [" ".join(command) for command in runner.commands]
        self.assertFalse(any("--phase after_restore" in line for line in text))
        self.assertFalse(any("up -d --no-deps web celery_worker" in line for line in text))
        self.assertFalse(any(" down " in f" {line} " for line in text))
        report = json.loads(
            next(config.report_dir.glob("agomtradepro-observed-deploy-*.json")).read_text()
        )
        self.assertEqual(report["outcome"], "restore_unverified")
        self.assertTrue(report["ownjobs_quiesced"])

    def test_live_interrupted_migrator_is_stopped_before_any_old_writer(self) -> None:
        config, runner, target, _, _ = self.make_fixture(failure="migrator")
        runner.running_job_on_failure = True
        runner.interrupt_job_on_failure = True
        with FakePointers(target):
            code = Executor(config, runner).execute()
        self.assertEqual(code, 70)
        text = [" ".join(command) for command in runner.commands]
        stop_index = next(i for i, line in enumerate(text) if line.startswith("docker stop"))
        old_up = [
            i
            for i, line in enumerate(text)
            if "docker compose" in line
            and " up -d --no-deps web celery_worker" in line
            and "source-" not in line
        ]
        self.assertFalse(old_up)
        self.assertEqual(runner.jobs[next(iter(runner.jobs))]["status"], "exited")
        self.assertTrue(any("docker info" in line for line in text[:stop_index]))
        report = json.loads(
            next(config.report_dir.glob("agomtradepro-observed-deploy-*.json")).read_text()
        )
        self.assertTrue(report["ownjobs_quiesced"])
        self.assertEqual(report["outcome"], "restore_unverified")

    def test_owned_migrator_stop_failure_never_starts_legacy_writers(self) -> None:
        config, runner, _, _, _ = self.make_fixture(failure="migrator")
        runner.running_job_on_failure = True
        runner.fail_worker_stop = True
        with FakePointers(config.target):
            code = Executor(config, runner).execute()
        self.assertEqual(code, 70)
        text = [" ".join(command) for command in runner.commands]
        self.assertTrue(any(line.startswith("docker stop") for line in text))
        self.assertFalse(any("up -d --no-deps web celery_worker" in line for line in text))
        report = json.loads(
            next(config.report_dir.glob("agomtradepro-observed-deploy-*.json")).read_text()
        )
        self.assertFalse(report["ownjobs_quiesced"])
        self.assertEqual(report["outcome"], "restore_unverified")

    def test_verified_migration_allows_legacy_restore_after_readonly_web_failure(self) -> None:
        config, runner, target, _, _ = self.make_fixture(failure="check_encryption_readiness")
        with FakePointers(target) as pointers:
            code = Executor(config, runner).execute()
        self.assertEqual(code, 20)
        self.assertEqual(pointers.links[target / "current"], "releases/20261101013730")
        text = [" ".join(command) for command in runner.commands]
        self.assertTrue(any("--phase after_restore" in line for line in text))
        self.assertTrue(any("up -d --no-deps web celery_worker" in line for line in text))

    def test_phase_b_failure_keeps_modern_anchor_and_only_recovers_web(self) -> None:
        config, runner, target, _, _ = self.make_fixture(failure="publish-tui-release.sh")
        with FakePointers(target) as pointers:
            code = Executor(config, runner).execute()
        self.assertEqual(code, 23)
        modern_link = str(Path("releases") / f"source-{config.tag}")
        self.assertEqual(pointers.links[target / "current"], modern_link)
        self.assertEqual(pointers.links[target / "previous"], modern_link)
        text = [" ".join(command) for command in runner.commands]
        self.assertTrue(any("up -d --no-deps web" in line for line in text))
        self.assertFalse(any("up -d --no-deps web celery_worker" in line for line in text))
        self.assertFalse(any("--phase after_restore" in line for line in text))
        report = json.loads(
            next(config.report_dir.glob("agomtradepro-observed-deploy-*.json")).read_text()
        )
        self.assertEqual(report["outcome"], "partial")
        self.assertTrue(report["forward_recovery_required"])

    def test_phase_b_identity_failure_stops_four_workers_before_modern_web_recovery(self) -> None:
        config, runner, target, _, _ = self.make_fixture(failure="phase-b-candidate-check")
        with FakePointers(target) as pointers:
            code = Executor(config, runner).execute()
        self.assertEqual(code, 23)
        modern_link = str(Path("releases") / f"source-{config.tag}")
        self.assertEqual(pointers.links[target / "current"], modern_link)
        text = [" ".join(command) for command in runner.commands]
        worker_stop = next(
            i
            for i, line in enumerate(text)
            if " stop celery_worker celery_qlib_worker celery_beat terminal_agent_worker" in line
            and "source-" in line
        )
        verify_stop = next(i for i, line in enumerate(text) if "workers-stopped" in line)
        web_recovery = next(
            i
            for i, line in enumerate(text[verify_stop + 1 :], verify_stop + 1)
            if line.endswith("up -d --no-deps web")
        )
        self.assertLess(worker_stop, verify_stop)
        self.assertLess(verify_stop, web_recovery)
        self.assertFalse(any("stop web" in line and "source-" in line for line in text))
        self.assertEqual(runner.running_services, {"web"})

    def test_phase_b_worker_stop_failure_reports_retired_forward_recovery(self) -> None:
        config, runner, target, _, _ = self.make_fixture(failure="phase-b-candidate-check")
        runner.fail_worker_stop = True
        with FakePointers(target) as pointers:
            code = Executor(config, runner).execute()
        self.assertEqual(code, 70)
        modern_link = str(Path("releases") / f"source-{config.tag}")
        self.assertEqual(pointers.links[target / "current"], modern_link)
        text = [" ".join(command) for command in runner.commands]
        phase_b_check = next(i for i, line in enumerate(text) if "--phase b" in line)
        post_failure_commands = text[phase_b_check + 1 :]
        self.assertFalse(
            any(line.endswith("up -d --no-deps web") for line in post_failure_commands)
        )
        self.assertFalse(
            any("up -d --no-deps web celery_worker" in line for line in post_failure_commands)
        )
        report = json.loads(
            next(config.report_dir.glob("agomtradepro-observed-deploy-*.json")).read_text()
        )
        self.assertEqual(report["outcome"], "restore_unverified")
        self.assertTrue(report["baseline_retired"])
        self.assertTrue(report["forward_recovery_required"])
        self.assertEqual(
            runner.running_services,
            {"web", "celery_worker", "celery_qlib_worker", "celery_beat", "terminal_agent_worker"},
        )


if __name__ == "__main__":
    unittest.main()
