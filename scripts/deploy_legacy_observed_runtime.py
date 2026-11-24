#!/usr/bin/env python3
"""Candidate-owned, bounded observed-runtime PhaseA/PhaseB executor."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Protocol
from urllib.parse import urlparse

OLD_TAG = "20261101013730"
SERVICES = ("web", "celery_worker", "celery_qlib_worker", "celery_beat", "terminal_agent_worker")
WORKER_SERVICES = SERVICES[1:]
CHILD_ENV_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "DOCKER_CONFIG",
        "SYSTEMROOT",
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "SYSTEMDRIVE",
        "TEMP",
        "TMP",
        "USERPROFILE",
    }
)
MANIFEST_KEYS = {
    "version",
    "release_tag",
    "source_commit",
    "image_tag",
    "image_id",
    "build_started_at",
    "build_finished_at",
    "source_mode",
}
STARTUP_FLAGS = (
    "AGOMTRADEPRO_CHECK_DEPLOY_ON_START",
    "AGOMTRADEPRO_AUTO_MIGRATE_ON_START",
    "AGOMTRADEPRO_BOOTSTRAP_ON_START",
    "AGOMTRADEPRO_COLLECTSTATIC_ON_START",
    "AGOMTRADEPRO_SETUP_SCHEDULE_ON_START",
    "AGOMTRADEPRO_ENSURE_SUPERUSER_ON_START",
    "AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START",
)
FALSE_ENV_VALUES = frozenset({"", "0", "false", "no", "off"})


class Blocked(RuntimeError):
    """Stable, secret-safe failure code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Result:
    """Command return status and non-persistent output used only for validation."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True, slots=True)
class OwnedJobState:
    """Secret-free Docker state for one attempt-owned one-off container."""

    name: str
    attempt_id: str
    image_id: str
    running: bool
    status: str


class Runner(Protocol):
    """Narrow command boundary so tests can inject failures without Docker."""

    def run(self, argv: Sequence[str], *, timeout: int = 3600) -> Result:
        """Run one argument vector without a shell."""


class SubprocessRunner:
    """Production command adapter with a minimal, deployment-safe environment."""

    def run(self, argv: Sequence[str], *, timeout: int = 3600) -> Result:
        """Capture a bounded result without inheriting app or Compose overrides."""
        try:
            result = subprocess.run(
                tuple(argv),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_minimal_child_environment(os.environ),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Blocked("OBSERVED_COMMAND_EXECUTION_FAILED") from exc
        return Result(result.returncode, result.stdout, result.stderr)


@dataclass(frozen=True, slots=True)
class Config:
    """Pinned candidate, proof inputs and inherited deploy options."""

    target: Path
    tag: str
    source_sha: str
    rehearsal_sha: str
    image_id: str
    baseline: Path
    baseline_sha: str
    compatibility: Path
    compatibility_sha: str
    report_dir: Path
    env: Mapping[str, str]
    attempt_id: str

    @property
    def release(self) -> Path:
        """Return the immutable candidate release root."""
        return self.target / "releases" / f"source-{self.tag}"

    @property
    def old(self) -> Path:
        """Return the one supported numeric legacy runtime root."""
        return self.target / "releases" / OLD_TAG

    @classmethod
    def load(cls, env: Mapping[str, str]) -> Config:
        """Load pinned environment inputs and require the exact production target."""

        def required(key: str) -> str:
            value = env.get(key, "")
            if not value:
                raise Blocked("OBSERVED_RUNTIME_INPUTS_INCOMPLETE")
            return value

        target = Path(env.get("TARGET_DIR", "/opt/agomtradepro"))
        if target != Path("/opt/agomtradepro"):
            raise Blocked("OBSERVED_TARGET_DIR_UNSUPPORTED")
        attempt_id = required("OBSERVED_DEPLOY_ATTEMPT_ID")
        if re.fullmatch(r"[0-9a-f]{32}", attempt_id) is None:
            raise Blocked("OBSERVED_DEPLOY_ATTEMPT_ID_INVALID")
        return cls(
            target,
            required("RELEASE_TAG"),
            required("SOURCE_COMMIT"),
            required("RELEASE_REHEARSAL_SHA256"),
            required("REHEARSAL_IMAGE_ID"),
            Path(required("OBSERVED_ROLLBACK_BASELINE_JSON")),
            required("OBSERVED_ROLLBACK_BASELINE_SHA256"),
            Path(required("OBSERVED_ROLLBACK_COMPATIBILITY_JSON")),
            required("OBSERVED_ROLLBACK_COMPATIBILITY_SHA256"),
            Path("/tmp"),
            env,
            attempt_id,
        )


class Executor:
    """Run only the explicitly pinned legacy bootstrap path."""

    def __init__(self, config: Config, runner: Runner) -> None:
        self.c = config
        self.runner = runner
        self.compose: tuple[str, ...] = ()
        self.report = (
            config.report_dir
            / f"agomtradepro-observed-deploy-{config.tag}-{config.attempt_id}.json"
        )
        self.infra = config.report_dir / f"agomtradepro-observed-infra-{uuid.uuid4().hex}.json"
        self.preservation = (
            config.report_dir / f"agomtradepro-observed-data-{uuid.uuid4().hex}.json"
        )
        self.override = config.target / f".observed-phase-a-{uuid.uuid4().hex}.yml"
        self.current_link = ""
        self.previous_present = False
        self.previous_link = ""
        self.backup_manifest: Path | None = None
        self.backup_sha = ""
        self.rollback_armed = False
        self.committed = False
        self.baseline_retired_at: str | None = None
        self.phase = "preflight"
        self.reason = ""
        self.override_created = False
        self.owned_job_names: list[str] = []
        self.job_counter = 0
        self.ownjobs_quiesced = True
        self.migration_started = False
        self.legacy_schema_verified = False
        self.phase_b_migration_started = False
        self.full_schema_verified = False
        self.readonly_override_retained = False
        self.qlib_version: str | None = None

    def execute(self) -> int:
        """Run the bounded deployment and return a stable outcome exit code."""
        outcome, status = "failed_preflight", 2
        try:
            self.preflight()
            self.stage_candidate_env()
            self.prepare_phase_a_override()
            self.rollback_armed = True
            self.phase = "phase_a"
            self.phase_a()
            self.phase = "phase_b"
            self.phase_b()
            if not self.full_schema_verified:
                raise Blocked("OBSERVED_FULL_SCHEMA_VERIFICATION_MISSING")
            self.ownjobs_quiesced = True
            outcome, status, self.reason = "deployed", 0, "OBSERVED_PHASE_B_COMPLETE"
        except BaseException as exc:
            self.reason = exc.code if isinstance(exc, Blocked) else "OBSERVED_UNEXPECTED_FAILURE"
            if self.committed:
                workers_stopped = self.stop_phase_b_workers()
                jobs_quiet = self.quiesce_owned_jobs()
                if workers_stopped and jobs_quiet:
                    web_verified = self.recover_modern_web(read_only=not self.full_schema_verified)
                    outcome, status = (
                        ("partial", 23) if web_verified else ("restore_unverified", 70)
                    )
                else:
                    outcome, status = "restore_unverified", 70
                    self.reason = (
                        "OBSERVED_PHASE_B_WORKERS_NOT_QUIESCED"
                        if not workers_stopped
                        else "OBSERVED_OWNED_JOBS_QUIESCE_FAILED"
                    )
            elif self.rollback_armed:
                jobs_quiet = self.quiesce_owned_jobs()
                schema_safe = not self.migration_started or self.legacy_schema_verified
                restored = jobs_quiet and schema_safe and self.restore_old_apps()
                if not jobs_quiet:
                    self.reason = "OBSERVED_OWNED_JOBS_QUIESCE_FAILED"
                elif not schema_safe:
                    self.reason = "OBSERVED_PARTIAL_MIGRATION_FORWARD_RECOVERY_REQUIRED"
                outcome, status = (
                    ("failed_restored", 20) if restored else ("restore_unverified", 70)
                )
            else:
                outcome, status = "failed_preflight", 2
        finally:
            retain_readonly_override = self.committed and not self.full_schema_verified
            if self.override_created and retain_readonly_override:
                self.readonly_override_retained = (
                    self.override.is_file() and not self.override.is_symlink()
                )
                if not self.readonly_override_retained and outcome == "partial":
                    outcome, status = "restore_unverified", 70
                    self.reason = "OBSERVED_READONLY_RECOVERY_OVERRIDE_MISSING"
            elif self.override_created:
                self.override.unlink(missing_ok=True)
            try:
                self.write_report(outcome)
            except Blocked:
                status = 70
        return status

    def preflight(self) -> None:
        """Validate options and read-only evidence before any production mutation."""
        env = self.c.env
        if self.report.exists() or self.report.is_symlink():
            raise Blocked("OBSERVED_REPORT_PATH_COLLISION")
        if (
            env.get("ACTION") != "upgrade"
            or env.get("AUTO_ROLLBACK") != "1"
            or env.get("PRESERVE_DATA_CENTER_CATALOG") != "1"
            or env.get("SKIP_PREDEPLOY_BACKUP") != "0"
            or env.get("WIPE_DOCKER", "0") != "0"
            or env.get("WIPE_VOLUMES", "0") != "0"
            or env.get("INCLUDE_SQLITE", "0") != "0"
            or env.get("ENABLE_CELERY") != "1"
            or not _is_strict_false(env.get("AGOMTRADEPRO_BOOTSTRAP_WITH_ALPHA"))
            or not _is_strict_false(env.get("AGOMTRADEPRO_BOOTSTRAP_WITH_DECISION_REPAIR"))
        ):
            raise Blocked("OBSERVED_RUNTIME_OPTIONS_UNSAFE")
        if (
            re.fullmatch(r"[0-9]{14}", self.c.tag) is None
            or re.fullmatch(r"[0-9a-f]{40}", self.c.source_sha) is None
            or re.fullmatch(r"[0-9a-f]{64}", self.c.rehearsal_sha) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.c.image_id) is None
            or re.fullmatch(r"[0-9a-f]{32}", self.c.attempt_id) is None
        ):
            raise Blocked("OBSERVED_CANDIDATE_PIN_INVALID")
        self.select_compose()
        self.verify_candidate()
        _verify_pin(self.c.baseline, self.c.baseline_sha)
        _verify_pin(self.c.compatibility, self.c.compatibility_sha)
        self.verify_old_runtime()
        self.require_helpers()
        self.observer("pre_cutover")
        self.native_check()
        self.helper(
            "observed_deploy_runtime_checks.py", "infra-capture", "--output", str(self.infra)
        )

    def select_compose(self) -> None:
        """Choose the installed Compose command without changing containers."""
        if self.runner.run(("docker", "compose", "version"), timeout=30).returncode == 0:
            self.compose = ("docker", "compose")
        elif self.runner.run(("docker-compose", "version"), timeout=30).returncode == 0:
            self.compose = ("docker-compose",)
        else:
            raise Blocked("OBSERVED_COMPOSE_UNAVAILABLE")

    def verify_candidate(self) -> None:
        """Recheck the candidate manifest, rehearsal image ID and OCI source label."""
        manifest_path = self.c.release / ".agom-release-manifest.json"
        if (
            self.c.release.resolve(strict=True) != self.c.release
            or _kind(manifest_path) != "file"
            or (os.name != "nt" and stat.S_IMODE(manifest_path.stat().st_mode) != 0o444)
        ):
            raise Blocked("OBSERVED_CANDIDATE_MANIFEST_INVALID")
        try:
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8"),
                object_pairs_hook=_unique_json_object,
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise Blocked("OBSERVED_CANDIDATE_MANIFEST_INVALID") from exc
        if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
            raise Blocked("OBSERVED_CANDIDATE_MANIFEST_INVALID")
        if (
            type(manifest.get("version")) is not int
            or manifest.get("version") != 1
            or manifest.get("release_tag") != self.c.tag
            or manifest.get("source_commit") != self.c.source_sha
            or manifest.get("image_tag") != f"agomtradepro-web:{self.c.tag}"
            or manifest.get("image_id") != self.c.image_id
            or not isinstance(manifest.get("source_mode"), str)
            or manifest.get("source_mode") not in {"source-upload", "git-clone"}
        ):
            raise Blocked("OBSERVED_CANDIDATE_MANIFEST_MISMATCH")
        try:
            started_text, finished_text = str(manifest["build_started_at"]), str(
                manifest["build_finished_at"]
            )
            timestamp = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"
            if (
                re.fullmatch(timestamp, started_text) is None
                or re.fullmatch(timestamp, finished_text) is None
            ):
                raise ValueError("strict UTC timestamp format required")
            started = datetime.strptime(started_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            finished = datetime.strptime(finished_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except (KeyError, TypeError, ValueError) as exc:
            raise Blocked("OBSERVED_CANDIDATE_BUILD_TIME_INVALID") from exc
        if finished < started:
            raise Blocked("OBSERVED_CANDIDATE_BUILD_TIME_INVALID")
        tag = str(manifest["image_tag"])
        actual = self.capture(("docker", "image", "inspect", tag, "--format", "{{.Id}}"))
        revision = self.capture(
            (
                "docker",
                "image",
                "inspect",
                tag,
                "--format",
                '{{index .Config.Labels "org.opencontainers.image.revision"}}',
            )
        )
        if actual != self.c.image_id or revision != self.c.source_sha:
            raise Blocked("OBSERVED_CANDIDATE_IMAGE_MISMATCH")

    def verify_old_runtime(self) -> None:
        """Require the one numeric current release, empty manifest dir and safe env."""
        current = self.c.target / "current"
        if not current.is_symlink() or current.resolve(strict=True) != self.c.old:
            raise Blocked("OBSERVED_LEGACY_CURRENT_IDENTITY_MISMATCH")
        self.current_link = os.readlink(current)
        if _kind(self.c.old / "docker/docker-compose.vps.yml") != "file":
            raise Blocked("OBSERVED_LEGACY_COMPOSE_MISSING")
        old_env = self.c.old / "deploy/.env"
        if _kind(old_env) != "file" or (
            os.name != "nt" and stat.S_IMODE(old_env.stat().st_mode) != 0o600
        ):
            raise Blocked("OBSERVED_LEGACY_ENV_UNSAFE")
        manifest = self.c.old / ".agom-release-manifest.json"
        if _kind(manifest) != "directory" or next(manifest.iterdir(), None) is not None:
            raise Blocked("OBSERVED_LEGACY_MANIFEST_INVALID")
        marker = self.c.target / ".postgres-migration-complete"
        if _kind(marker) != "file":
            raise Blocked("OBSERVED_POSTGRES_MIGRATION_MARKER_REQUIRED")
        previous = self.c.target / "previous"
        if previous.exists() and not previous.is_symlink():
            raise Blocked("OBSERVED_PREVIOUS_POINTER_INVALID")
        self.previous_present = previous.is_symlink()
        if self.previous_present:
            self.previous_link = os.readlink(previous)
        env = _parse_env(old_env.read_bytes())
        if any(not _is_strict_false(env.get(key)) for key in STARTUP_FLAGS):
            raise Blocked("OBSERVED_STARTUP_WRITE_FLAGS_UNSAFE")

    def require_helpers(self) -> None:
        """Fail closed if any candidate-owned proof helper is missing."""
        names = (
            "capture_legacy_observed_runtime.py",
            "observed_deploy_runtime_checks.py",
            "verify_legacy_observed_native_compatibility.py",
            "check_legacy_migration_preservation.py",
            "vps-backup.sh",
        )
        if any(_kind(self.c.release / "scripts" / name) != "file" for name in names):
            raise Blocked("OBSERVED_REQUIRED_EXECUTOR_HELPER_MISSING")

    def stage_candidate_env(self) -> None:
        """Copy old deploy settings and change only candidate WEB_IMAGE."""
        old = self.c.old / "deploy/.env"
        destination = self.c.release / "deploy/.env"
        lines, found = [], 0
        image = f"WEB_IMAGE=agomtradepro-web:{self.c.tag}".encode()
        for line in old.read_bytes().splitlines(keepends=True):
            if line.rstrip(b"\r\n").split(b"=", 1)[0] == b"WEB_IMAGE":
                found += 1
                ending = (
                    b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b""
                )
                lines.append(image + ending)
            else:
                lines.append(line)
        if found > 1:
            raise Blocked("OBSERVED_LEGACY_ENV_WEB_IMAGE_AMBIGUOUS")
        if not found:
            if lines and not lines[-1].endswith((b"\n", b"\r")):
                lines[-1] += b"\n"
            lines.append(image + b"\n")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".env.observed-{uuid.uuid4().hex}")
        payload = b"".join(lines)
        if destination.exists() or destination.is_symlink():
            if (
                _kind(destination) != "file"
                or destination.read_bytes() != payload
                or (os.name != "nt" and stat.S_IMODE(destination.stat().st_mode) != 0o600)
            ):
                raise Blocked("OBSERVED_CANDIDATE_ENV_DRIFT")
            return
        _write_private(temporary, payload)
        try:
            os.replace(temporary, destination)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise Blocked("OBSERVED_CANDIDATE_ENV_WRITE_FAILED") from exc

    def prepare_phase_a_override(self) -> None:
        """Fence database and persistent secret-volume writes before web starts."""
        if self.override_created:
            raise Blocked("OBSERVED_PHASE_A_OVERRIDE_ALREADY_CREATED")
        _write_private(
            self.override,
            b'services:\n  web:\n    environment:\n      PGOPTIONS: "-c default_transaction_read_only=on"\n'
            b"    volumes:\n      - sqlite_data:/app/data:ro\n",
        )
        self.override_created = True

    def phase_a(self) -> None:
        """Stop writers, back up and migrate, then verify read-only web before commit."""
        self.compose_run(self.c.old, "stop", *SERVICES)
        self.helper("observed_deploy_runtime_checks.py", "writers-stopped")
        self.infra_compare()
        backup_dir = self.c.target / "backups/observed-runtime" / f"{self.c.tag}-{uuid.uuid4().hex}"
        backups_root = self.c.target / "backups"
        observed_root = backups_root / "observed-runtime"
        if _kind(backups_root) not in {"directory", "missing"} or _kind(observed_root) not in {
            "directory",
            "missing",
        }:
            raise Blocked("OBSERVED_BACKUP_ROOT_INVALID")
        backups_root.mkdir(mode=0o700, exist_ok=True)
        if backups_root.resolve(strict=True).parent != self.c.target.resolve(strict=True):
            raise Blocked("OBSERVED_BACKUP_ROOT_INVALID")
        observed_root.mkdir(mode=0o700, exist_ok=True)
        if observed_root.resolve(strict=True).parent != backups_root.resolve(strict=True):
            raise Blocked("OBSERVED_BACKUP_ROOT_INVALID")
        backup_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
        backup = self.must(
            (
                "bash",
                str(self.c.release / "scripts/vps-backup.sh"),
                "--target-dir",
                str(self.c.old),
                "--backup-dir",
                str(backup_dir),
                "--keep-days",
                "0",
                "--no-redis",
            ),
            timeout=3600,
        )
        self.backup_manifest = _backup_manifest(backup.stdout, backup_dir)
        self.backup_sha = _verify_backup(self.backup_manifest, backup_dir)
        self.helper(
            "check_legacy_migration_preservation.py",
            "capture",
            "--snapshot-json",
            str(self.preservation),
        )
        self.native_check()
        self.apply_phase_a_migrations()
        self.compose_override(
            "run",
            "--rm",
            "--no-deps",
            "-e",
            "PGOPTIONS=-c default_transaction_read_only=on",
            "web",
            "python",
            "manage.py",
            "verify_canonical_schema",
            "--json",
        )
        self.native_check()
        self.helper(
            "check_legacy_migration_preservation.py",
            "verify",
            "--snapshot-json",
            str(self.preservation),
        )
        self.legacy_schema_verified = True
        self.compose_override(
            "run",
            "--rm",
            "--no-deps",
            "-e",
            "PGOPTIONS=-c default_transaction_read_only=on",
            "web",
            "python",
            "manage.py",
            "check",
            "--deploy",
        )
        self.compose_override("create", "--no-deps", *SERVICES)
        self.compose_override("up", "-d", "--no-deps", "web")
        self.wait_web()
        self.compose_run(
            self.c.release,
            "exec",
            "-T",
            "web",
            "python",
            "manage.py",
            "check_encryption_readiness",
            "--json",
        )
        self.show_identity()
        self.candidate_check("a")
        self.infra_compare()
        self.wait_public_health()
        self.commit()

    def apply_phase_a_migrations(self) -> None:
        """Apply all proven-compatible leaves while retaining the guarded AI005 leaf."""
        self.migration_started = True
        self.compose_run(
            self.c.release,
            "run",
            "--rm",
            "--no-deps",
            "-e",
            "AGOM_OBSERVED_MIGRATION_PHASE=phase_a",
            "migrator",
        )

    def phase_b(self) -> None:
        """Run deferred metadata/bootstrap steps and start all five app services."""
        self.complete_phase_b_migrations()
        self.compose_run(
            self.c.release,
            "run",
            "--rm",
            "--no-deps",
            "web",
            "python",
            "manage.py",
            "sync_ai_capability_catalog",
            "--type",
            "incremental",
            "--source",
            "mcp_tool",
            "--fail-on-error",
        )
        self.compose_run(
            self.c.release,
            "run",
            "--rm",
            "--no-deps",
            "web",
            "python",
            "manage.py",
            "check",
            "--deploy",
        )
        self.compose_run(
            self.c.release,
            "run",
            "--rm",
            "--no-deps",
            "web",
            "python",
            "manage.py",
            "collectstatic",
            "--noinput",
        )
        self.compose_run(
            self.c.release,
            "run",
            "--rm",
            "--no-deps",
            "web",
            "sh",
            "scripts/publish-tui-release.sh",
            self.c.tag,
        )
        self.compose_run(
            self.c.release,
            "run",
            "--rm",
            "--no-deps",
            "web",
            "sh",
            "-lc",
            "python manage.py bootstrap_cold_start --preserve-protected-schedules-disabled",
        )
        self.compose_run(
            self.c.release,
            "run",
            "--rm",
            "--no-deps",
            "web",
            "sh",
            "-lc",
            "python manage.py init_macro_indicator_governance --check && python manage.py normalize_macro_fact_units --check",
        )
        env = _parse_env((self.c.release / "deploy/.env").read_bytes())
        hour, minute = env.get("MACRO_SYNC_HOUR", "8"), env.get("MACRO_SYNC_MINUTE", "5")
        if not hour.isdigit() or int(hour) > 23 or not minute.isdigit() or int(minute) > 59:
            raise Blocked("OBSERVED_MACRO_SCHEDULE_INVALID")
        self.compose_run(
            self.c.release,
            "run",
            "--rm",
            "--no-deps",
            "web",
            "python",
            "manage.py",
            "setup_macro_daily_sync",
            "--hour",
            hour,
            "--minute",
            minute,
        )
        self.compose_run(
            self.c.release,
            "run",
            "--rm",
            "--no-deps",
            "-e",
            "AGOMTRADEPRO_ENSURE_SUPERUSER_ON_START=1",
            "web",
            "true",
        )
        self.compose_run(self.c.release, "up", "-d", "--no-deps", *SERVICES)
        self.wait_web()
        self.compose_run(
            self.c.release,
            "exec",
            "-T",
            "web",
            "python",
            "manage.py",
            "check_encryption_readiness",
            "--json",
        )
        self.show_identity()
        self.candidate_check("b")
        self.infra_compare()
        self.check_qlib_identity()
        self.wait_public_health()
        self.compose_run(
            self.c.release,
            "exec",
            "-T",
            "web",
            "python",
            "manage.py",
            "setup_audit_outbox_dispatch",
            "--ensure-enabled",
        )

    def complete_phase_b_migrations(self) -> None:
        """Apply the deferred guarded migration before any PhaseB metadata or writer."""
        self.phase_b_migration_started = True
        self.compose_run(
            self.c.release,
            "run",
            "--rm",
            "--no-deps",
            "-e",
            "AGOM_OBSERVED_MIGRATION_PHASE=phase_b",
            "migrator",
        )
        self.compose_override(
            "run",
            "--rm",
            "--no-deps",
            "-e",
            "PGOPTIONS=-c default_transaction_read_only=on",
            "web",
            "python",
            "manage.py",
            "verify_canonical_schema",
            "--json",
        )
        self.full_schema_verified = True

    def commit(self) -> None:
        """Atomically set current and previous to the same modern candidate."""
        link = str(Path("releases") / f"source-{self.c.tag}")
        self.atomic_link(self.c.target / "current", link)
        try:
            self.atomic_link(self.c.target / "previous", link)
        except BaseException:
            self.restore_pointers()
            raise
        self.committed = True
        self.baseline_retired_at = datetime.now(UTC).isoformat()

    def restore_old_apps(self) -> bool:
        """Restore only legacy app services and verify legacy plus infra identity."""
        valid = True
        try:
            self.restore_pointers()
            self.compose_run(self.c.old, "up", "-d", "--no-deps", *SERVICES)
        except BaseException:
            valid = False
        try:
            self.observer("after_restore")
            self.infra_compare()
        except BaseException:
            valid = False
        if not valid:
            quiesced = True
            try:
                self.compose_run(self.c.old, "stop", *SERVICES)
            except BaseException:
                quiesced = False
            try:
                self.helper("observed_deploy_runtime_checks.py", "writers-stopped")
            except BaseException:
                quiesced = False
            if not quiesced:
                self.reason = "OBSERVED_LEGACY_RECOVERY_WRITERS_NOT_QUIESCED"
        return valid

    def recover_modern_web(self, *, read_only: bool) -> bool:
        """Try the modern web service with the required database/secret write fence."""
        try:
            if read_only:
                self.compose_override("up", "-d", "--no-deps", "web")
            else:
                self.compose_run(self.c.release, "up", "-d", "--no-deps", "web")
            self.wait_web()
            self.show_identity()
            if read_only:
                self.candidate_check("a")
                self.infra_compare()
            return True
        except BaseException:
            self.reason = "OBSERVED_PHASE_B_FORWARD_RECOVERY_REQUIRED"
            return False

    def stop_phase_b_workers(self) -> bool:
        """Stop and verify the four modern worker services without stopping web."""
        try:
            self.compose_run(self.c.release, "stop", *WORKER_SERVICES)
            self.helper("observed_deploy_runtime_checks.py", "workers-stopped")
        except BaseException:
            return False
        return True

    def quiesce_owned_jobs(self) -> bool:
        """Stop only this attempt's candidate one-off jobs before recovery."""
        if not self.owned_job_names:
            self.ownjobs_quiesced = True
            return True
        self.ownjobs_quiesced = False
        try:
            daemon = self.runner.run(("docker", "info", "--format", "{{.ID}}"), timeout=30)
            daemon_id = daemon.stdout.strip()
            if (
                daemon.returncode != 0
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,127}", daemon_id) is None
            ):
                return False
            for name in self.owned_job_names:
                state = self._owned_job_state(name)
                if state is None or state.status in {"created", "exited", "dead"}:
                    continue
                stopped = self.runner.run(("docker", "stop", "--time", "30", name), timeout=45)
                if stopped.returncode != 0:
                    state = self._owned_job_state(name)
                    if state is not None and (
                        state.running or state.status not in {"created", "exited", "dead"}
                    ):
                        return False
                    continue
                state = self._owned_job_state(name)
                if state is not None and (
                    state.running or state.status not in {"created", "exited", "dead"}
                ):
                    return False
        except BaseException:
            return False
        self.ownjobs_quiesced = True
        return True

    def _owned_job_state(self, name: str) -> OwnedJobState | None:
        """Read and validate one exact name, attempt label and immutable image ID."""
        listed = self.runner.run(
            (
                "docker",
                "ps",
                "--all",
                "--filter",
                f"name=^/{name}$",
                "--format",
                "{{.Names}}",
            ),
            timeout=30,
        )
        if listed.returncode != 0:
            raise Blocked("OBSERVED_OWNED_JOB_DOCKER_QUERY_FAILED")
        names = [
            line.strip().removeprefix("/") for line in listed.stdout.splitlines() if line.strip()
        ]
        if not names:
            return None
        if names != [name]:
            raise Blocked("OBSERVED_OWNED_JOB_NAME_MISMATCH")
        inspected = self.runner.run(
            (
                "docker",
                "inspect",
                "--format",
                '{{.Name}}|{{index .Config.Labels "agom.observed.attempt"}}|{{.Image}}|{{.State.Running}}|{{.State.Status}}',
                name,
            ),
            timeout=30,
        )
        if inspected.returncode != 0:
            retry = self.runner.run(
                (
                    "docker",
                    "ps",
                    "--all",
                    "--filter",
                    f"name=^/{name}$",
                    "--format",
                    "{{.Names}}",
                ),
                timeout=30,
            )
            if retry.returncode == 0 and not retry.stdout.strip():
                return None
            raise Blocked("OBSERVED_OWNED_JOB_INSPECT_FAILED")
        values = inspected.stdout.strip().split("|")
        if len(values) != 5:
            raise Blocked("OBSERVED_OWNED_JOB_INSPECT_INVALID")
        container_name, attempt_id, image_id, running_text, status = values
        if (
            container_name.removeprefix("/") != name
            or attempt_id != self.c.attempt_id
            or image_id != self.c.image_id
            or running_text not in {"true", "false"}
            or status not in {"created", "running", "restarting", "paused", "exited", "dead"}
        ):
            raise Blocked("OBSERVED_OWNED_JOB_IDENTITY_MISMATCH")
        return OwnedJobState(name, attempt_id, image_id, running_text == "true", status)

    def restore_pointers(self) -> None:
        """Restore the exact current and previous symlink targets saved at preflight."""
        if self.current_link:
            self.atomic_link(self.c.target / "current", self.current_link)
        previous = self.c.target / "previous"
        if self.previous_present:
            self.atomic_link(previous, self.previous_link)
        elif previous.is_symlink():
            previous.unlink()

    def atomic_link(self, link: Path, target: str) -> None:
        """Replace one symlink atomically on the target filesystem."""
        temporary = link.with_name(f".{link.name}.observed-{uuid.uuid4().hex}")
        created = False
        try:
            temporary.symlink_to(target, target_is_directory=True)
            created = True
            os.replace(temporary, link)
        except OSError as exc:
            if created:
                temporary.unlink(missing_ok=True)
            raise Blocked("OBSERVED_RELEASE_POINTER_SWITCH_FAILED") from exc

    def observer(self, phase: str) -> None:
        """Compare the pinned observed legacy receipt at one supported phase."""
        self.helper(
            "capture_legacy_observed_runtime.py",
            "compare",
            "--baseline-json",
            str(self.c.baseline),
            "--baseline-sha256",
            self.c.baseline_sha,
            "--phase",
            phase,
        )

    def native_check(self) -> None:
        """Run the offline candidate-bound native compatibility report verifier."""
        self.helper(
            "verify_legacy_observed_native_compatibility.py",
            "verify",
            "--report",
            str(self.c.compatibility),
            "--sha256",
            self.c.compatibility_sha,
            "--candidate-root",
            str(self.c.release),
            "--baseline-sha256",
            self.c.baseline_sha,
        )

    def candidate_check(self, phase: str) -> None:
        """Check candidate OCI, source tree and service identity for one phase."""
        self.helper(
            "observed_deploy_runtime_checks.py",
            "candidate-app-check",
            "--release-root",
            str(self.c.release),
            "--phase",
            phase,
            "--image-id",
            self.c.image_id,
            "--candidate-sha",
            self.c.source_sha,
        )

    def infra_compare(self) -> None:
        """Require the four captured infrastructure services to remain unchanged."""
        self.helper(
            "observed_deploy_runtime_checks.py", "infra-compare", "--snapshot", str(self.infra)
        )

    def helper(self, name: str, *args: str) -> None:
        """Run a candidate-owned proof helper with its exact argv contract."""
        self.must(("python3", str(self.c.release / "scripts" / name), *args))

    def compose_run(self, release: Path, *args: str, timeout: int = 3600) -> Result:
        """Run one Compose operation using the selected release and env file."""
        command_args = self._owned_run_args(release, args)
        result = self.must(self._compose_argv(release, command_args), timeout=timeout)
        if args and args[0] == "run":
            self.ownjobs_quiesced = True
        return result

    def compose_override(self, *args: str, timeout: int = 3600) -> Result:
        """Run candidate Compose with the temporary read-only web override."""
        command_args = self._owned_run_args(self.c.release, args)
        result = self.must(
            (
                *self.compose_argv_prefix(self.c.release),
                "-f",
                str(self.override),
                "--env-file",
                str(self.c.release / "deploy/.env"),
                *command_args,
            ),
            timeout=timeout,
        )
        if args and args[0] == "run":
            self.ownjobs_quiesced = True
        return result

    def _owned_run_args(self, release: Path, args: Sequence[str]) -> tuple[str, ...]:
        """Pin every one-off container to this attempt, candidate image and label."""
        if not args or args[0] != "run":
            return tuple(args)
        if release != self.c.release:
            raise Blocked("OBSERVED_ONEOFF_RELEASE_UNSUPPORTED")
        self.job_counter += 1
        name = f"agom-observed-{self.c.attempt_id}-{self.job_counter}"
        self.owned_job_names.append(name)
        self.ownjobs_quiesced = False
        return (
            "run",
            "--name",
            name,
            "--label",
            f"agom.observed.attempt={self.c.attempt_id}",
            *args[1:],
        )

    def _compose_argv(self, release: Path, args: Sequence[str]) -> tuple[str, ...]:
        """Build Compose argv with an explicit release-local environment file."""
        return (
            *self.compose_argv_prefix(release),
            "--env-file",
            str(release / "deploy/.env"),
            *args,
        )

    def compose_argv_prefix(self, release: Path) -> tuple[str, ...]:
        """Return the Compose project and release-local compose-file arguments."""
        return (
            *self.compose,
            "-p",
            "agomtradepro",
            "-f",
            str(release / "docker/docker-compose.vps.yml"),
        )

    def must(self, argv: Sequence[str], *, timeout: int = 3600) -> Result:
        """Require successful command completion without retaining raw output."""
        result = self.runner.run(argv, timeout=timeout)
        if result.returncode:
            for line in (result.stdout + "\n" + result.stderr).splitlines():
                code = line.strip().removeprefix("[ERROR] ").strip()
                if code.startswith(("OBSERVED_", "LEGACY_", "S6_")) and re.fullmatch(
                    r"[A-Z0-9_,]+", code
                ):
                    raise Blocked(code)
            raise Blocked("OBSERVED_DEPLOY_COMMAND_FAILED")
        return result

    def capture(self, argv: Sequence[str]) -> str:
        """Return one identity token printed by a successful command."""
        return self.must(argv).stdout.strip()

    def show_identity(self) -> None:
        """Require the active candidate web to report the exact source commit."""
        self.compose_run(
            self.c.release,
            "exec",
            "-T",
            "web",
            "python",
            "manage.py",
            "show_release_identity",
            "--expected-commit",
            self.c.source_sha,
            "--json",
        )

    def wait_web(self) -> None:
        """Poll only the local non-business health endpoint for up to one minute."""
        program = "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/api/health/', timeout=5); raise SystemExit(0 if r.status==200 else 1)"
        for _ in range(30):
            if (
                self.runner.run(
                    (
                        *self.compose,
                        "-p",
                        "agomtradepro",
                        "-f",
                        str(self.c.release / "docker/docker-compose.vps.yml"),
                        "--env-file",
                        str(self.c.release / "deploy/.env"),
                        "exec",
                        "-T",
                        "web",
                        "python",
                        "-c",
                        program,
                    ),
                    timeout=15,
                ).returncode
                == 0
            ):
                return
            time.sleep(2)
        raise Blocked("OBSERVED_CANDIDATE_WEB_HEALTH_FAILED")

    def wait_public_health(self) -> None:
        """Verify Caddy and TLS against the existing public route before/after commit."""
        env = _parse_env((self.c.release / "deploy/.env").read_bytes())
        configured = urlparse(self.c.env.get("AGOMTRADEPRO_BASE_URL", ""))
        domain = env.get("DOMAIN") or self.c.env.get("DOMAIN") or configured.hostname
        if not domain or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", domain) is None:
            raise Blocked("OBSERVED_PUBLIC_HEALTH_DOMAIN_UNAVAILABLE")
        port = env.get("CADDY_HTTPS_PORT", "443")
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise Blocked("OBSERVED_PUBLIC_HEALTH_PORT_INVALID")
        argv = (
            "curl",
            "--silent",
            "--show-error",
            "--fail",
            "--max-time",
            "10",
            "--write-out",
            "\n%{http_code}",
            "--resolve",
            f"{domain}:{port}:127.0.0.1",
            f"https://{domain}:{port}/api/health/",
        )
        for _ in range(12):
            result = self.runner.run(argv, timeout=15)
            if result.returncode == 0:
                body, separator, status_code = result.stdout.rpartition("\n")
                try:
                    payload: object = json.loads(body)
                except (ValueError, TypeError):
                    payload = None
                if (
                    separator
                    and status_code == "200"
                    and isinstance(payload, dict)
                    and payload.get("status") == "ok"
                ):
                    return
            time.sleep(2)
        raise Blocked("OBSERVED_PUBLIC_HEALTH_TLS_FAILED")

    def check_qlib_identity(self) -> None:
        """Verify the running web imports the installed pyqlib distribution."""
        program = (
            "import importlib.metadata as m,json;from pathlib import Path;import qlib,qlib.data;"
            "d=m.distribution('pyqlib');"
            "Path(qlib.__file__).resolve().relative_to(Path(d.locate_file('qlib')).resolve());"
            "print(json.dumps({'distribution':'pyqlib','version':d.version}))"
        )
        result = self.compose_run(self.c.release, "exec", "-T", "web", "python", "-c", program)
        try:
            payload: object = json.loads(result.stdout)
        except (ValueError, TypeError) as exc:
            raise Blocked("OBSERVED_QLIB_RUNTIME_IDENTITY_INVALID") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("distribution") != "pyqlib"
            or not isinstance(payload.get("version"), str)
            or not payload["version"]
        ):
            raise Blocked("OBSERVED_QLIB_RUNTIME_IDENTITY_INVALID")
        self.qlib_version = payload["version"]

    def write_report(self, outcome: str) -> None:
        """Write the private, secret-free outcome report for wrapper retrieval."""
        payload = {
            "schema": "legacy-observed-deploy-result.v2",
            "outcome": outcome,
            "phase": self.phase,
            "reason_code": self.reason,
            "candidate_sha": self.c.source_sha,
            "release_tag": self.c.tag,
            "image_id": self.c.image_id,
            "release_rehearsal_sha256": self.c.rehearsal_sha,
            "baseline_sha256": self.c.baseline_sha,
            "compatibility_sha256": self.c.compatibility_sha,
            "backup_manifest_sha256": self.backup_sha,
            "backup_manifest": str(self.backup_manifest) if self.backup_manifest else "",
            "attempt_id": self.c.attempt_id,
            "ownjobs_quiesced": self.ownjobs_quiesced,
            "baseline_retired": self.committed,
            "baseline_retired_at": self.baseline_retired_at,
            "migration_started": self.migration_started,
            "legacy_schema_verified": self.legacy_schema_verified,
            "phase_b_migration_started": self.phase_b_migration_started,
            "full_schema_verified": self.full_schema_verified,
            "readonly_override_retained": self.readonly_override_retained,
            "readonly_override_path": str(self.override) if self.readonly_override_retained else "",
            "qlib_version": self.qlib_version,
            "forward_recovery_required": outcome != "deployed"
            and (self.committed or (self.migration_started and not self.legacy_schema_verified)),
        }
        self.report.parent.mkdir(parents=True, exist_ok=True)
        _write_private(self.report, (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode())
        print(f"OBSERVED_REPORT_PATH={self.report}")


def _kind(path: Path) -> str:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return "missing"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "file" if stat.S_ISREG(mode) else "directory" if stat.S_ISDIR(mode) else "other"


def _minimal_child_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Keep OS and Docker client settings while dropping ambient app overrides."""
    allowed = {key.upper() for key in CHILD_ENV_KEYS}
    child = {key: value for key, value in source.items() if key.upper() in allowed}
    child["DOCKER_CONTEXT"] = "default"
    return child


def _write_private(path: Path, data: bytes) -> None:
    created = False
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(path, 0o600)
    except OSError as exc:
        if created:
            path.unlink(missing_ok=True)
        raise Blocked("OBSERVED_PRIVATE_FILE_WRITE_FAILED") from exc


def _parse_env(raw: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            normalized_key = key.strip()
            if normalized_key in values:
                raise Blocked("OBSERVED_ENVIRONMENT_DUPLICATE_KEY")
            values[normalized_key] = value.strip().strip("\"'")
    return values


def _is_strict_false(value: str | None) -> bool:
    """Accept only explicit false literals for options that can enable writes."""
    return (value if value is not None else "0").strip().lower() in FALSE_ENV_VALUES


def _verify_pin(path: Path, expected: str) -> None:
    if (
        not path.is_absolute()
        or ".." in path.parts
        or path.suffix != ".json"
        or re.fullmatch(r"[0-9a-f]{64}", expected) is None
        or _kind(path) != "file"
    ):
        raise Blocked("OBSERVED_PROOF_FILE_INVALID")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise Blocked("OBSERVED_PROOF_DIGEST_MISMATCH")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise Blocked("OBSERVED_CANDIDATE_MANIFEST_DUPLICATE_KEY")
        values[key] = value
    return values


def _backup_manifest(output: str, root: Path) -> Path:
    matches = re.findall(r"^\[INFO\] Manifest: (.+)$", output, re.MULTILINE)
    if len(matches) != 1:
        raise Blocked("OBSERVED_BACKUP_MANIFEST_MISSING")
    path = Path(matches[0])
    if (
        path.parent.resolve(strict=True) != (root / "meta").resolve(strict=True)
        or _kind(path) != "file"
    ):
        raise Blocked("OBSERVED_BACKUP_MANIFEST_INVALID")
    return path


def _verify_backup(path: Path, root: Path) -> str:
    base = root.resolve(strict=True)
    lines = path.read_text(encoding="utf-8").splitlines()
    postgres_backup = False
    if not lines:
        raise Blocked("OBSERVED_BACKUP_MANIFEST_EMPTY")
    for line in lines:
        digest, sep, filename = line.partition("  ")
        file = Path(filename)
        if (
            not sep
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or file.is_symlink()
            or not file.is_file()
            or base not in file.resolve(strict=True).parents
        ):
            raise Blocked("OBSERVED_BACKUP_MANIFEST_INVALID")
        if hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise Blocked("OBSERVED_BACKUP_DIGEST_MISMATCH")
        postgres_backup = postgres_backup or (
            file.parent.name == "database" and file.name.startswith("postgres-")
        )
    if not postgres_backup:
        raise Blocked("OBSERVED_POSTGRES_BACKUP_MISSING")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    """Run once using the normal deploy wrapper's already-validated environment."""
    for signal_name in ("SIGTERM", "SIGHUP"):
        signal_number = getattr(signal, signal_name, None)
        if signal_number is not None:
            signal.signal(signal_number, _handle_interrupt)
    try:
        return Executor(Config.load(os.environ), SubprocessRunner()).execute()
    except Blocked as exc:
        print(f"[ERROR] {exc.code}", file=sys.stderr)
        return 2


def _handle_interrupt(signum: int, frame: FrameType | None) -> None:
    """Route TERM/HUP through the PhaseA rollback or PhaseB forward path."""
    raise Blocked("OBSERVED_DEPLOY_INTERRUPTED")


if __name__ == "__main__":
    raise SystemExit(main())
