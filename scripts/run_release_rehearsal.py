#!/usr/bin/env python3
"""Run the ordered, non-deploying S6 release rehearsal."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol, cast, runtime_checkable
from urllib.parse import unquote, urlsplit
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.data_center.infrastructure.rehearsal_identity import (
    RehearsalProviderIdentity,
    parse_rehearsal_identities,
    rehearsal_identities_digest,
)
from shared.release_rehearsal_stage_environment import (
    MINIMUM_AVAILABLE_MEMORY_BYTES,
    MINIMUM_PREBUILD_FREE_DISK_BYTES,
    StageEnvironmentInputs,
    StageEnvironmentIssue,
    evaluate_stage_environment,
    parse_dynamic_issues,
)


class _Checkpoint(Protocol):
    """Typed boundary for the helper imported by both script and package entrypoints."""

    records: dict[str, dict[str, object]]

    def done(self, stage: str) -> bool:
        """Return whether validated artifacts exist for this stage."""
        ...

    def complete(self, stage: str, artifacts: Sequence[Path]) -> None:
        """Save validated stage artifacts."""
        ...

    def prepare(self, stage: str, paths: Sequence[Path], *, resume: bool) -> None:
        """Preserve incomplete attempts before retrying."""
        ...


class _CheckpointFactory(Protocol):
    def __call__(
        self,
        root: Path,
        binding: Mapping[str, object],
        *,
        resume: bool,
        max_age_hours: float,
        stage_order: Sequence[str],
    ) -> _Checkpoint:
        """Open a new or verified existing journal."""
        ...


# scripts/ is a namespace directory. Match the deployment entrypoint's explicit
# import boundary so direct-file mypy checks do not load this helper twice.
_checkpoint_module = importlib.import_module("scripts.rehearsal_checkpoint")
Checkpoint = cast(_CheckpointFactory, _checkpoint_module.Checkpoint)
atomic_json = cast(Callable[[Path, Mapping[str, object]], None], _checkpoint_module.atomic_json)
file_digest = cast(Callable[[Path], str], _checkpoint_module.file_digest)
run_lock = cast(Callable[[Path], AbstractContextManager[None]], _checkpoint_module.run_lock)

SHA, COMMIT = re.compile(r"[0-9a-f]{64}"), re.compile(r"[0-9a-f]{40}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
TAG = re.compile(r"[0-9]{14}")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
STABLE_REHEARSAL_CODE = re.compile(r"^CommandError: (REHEARSAL_[A-Z0-9_]{3,96})\s*$", re.MULTILINE)
STABLE_REHEARSAL_HEADROOM_ERROR_CODE = re.compile(
    r"\[ERROR\]\s+(REHEARSAL_BUILD_DISK_HEADROOM_(?:INSUFFICIENT|UNAVAILABLE))(?=[:\s]|$)"
)
STABLE_REHEARSAL_CODE_VALUE = re.compile(r"REHEARSAL_[A-Z0-9_]{3,96}")
IMAGE_NAME = "agomtradepro-web"
STAGES = (
    "provider_probe",
    "response_replay",
    "full_universe_capacity",
    "production_policy_parity",
    "isolated_postgresql_write",
    "github_ci_evidence",
    "akshare_financial_slice",
    "bundle_build",
    "release_validator",
)
REQUIRED_PARAMIKO_VERSION = "5.0.0"


@dataclass(frozen=True)
class Command:
    """One command passed through the injectable execution boundary."""

    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    timeout_seconds: float
    label: str
    artifact_dir: Path | None = None


@dataclass(frozen=True)
class CommandResult:
    """Subprocess status and captured output."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    """Injectable command runner for safe orchestration tests."""

    def run(self, command: Command) -> CommandResult:
        """Execute a command without a shell."""


@runtime_checkable
class CancellableCommandRunner(CommandRunner, Protocol):
    """Command runner that can stop every subprocess owned by this run."""

    def cancel(self) -> None:
        """Stop all active commands after an operator interruption."""


class _Chown(Protocol):
    """Portable callable shape for POSIX ownership changes."""

    def __call__(self, path: str | bytes | os.PathLike[str], uid: int, gid: int) -> None:
        """Change one filesystem entry's owner/group."""


class SubprocessRunner:
    """Production runner that captures output and never invokes a shell."""

    def __init__(self, progress_dir: Path | None = None) -> None:
        self.progress_dir = progress_dir
        self._cancelled = threading.Event()
        self._active_lock = threading.Lock()
        self._active_processes: dict[int, subprocess.Popen[str]] = {}
        self._progress_lock = threading.Lock()
        self._active_progress: dict[str, dict[str, object]] = {}

    def cancel(self) -> None:
        """Stop all active process groups launched by this runner."""

        self._cancelled.set()
        with self._active_lock:
            processes = tuple(self._active_processes.values())
        for process in processes:
            try:
                self._stop_process(process)
            except (OSError, subprocess.SubprocessError):
                if process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        pass

    def _progress(
        self,
        command: Command,
        invocation_id: str,
        started: float,
        *,
        outcome: str,
        stdout: str | bytes = "",
        stderr: str | bytes = "",
        returncode: int | None = None,
    ) -> None:
        if self.progress_dir is None:
            return
        self.progress_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        error_text = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr
        output_text = stdout.decode("utf-8", "replace") if isinstance(stdout, bytes) else stdout
        diagnostic_text = output_text + "\n" + error_text
        # Only allow-listed diagnostic categories leave the subprocess boundary.
        # No argv, environment, raw exception message or provider response is persisted.
        categories = [
            name
            for name, pattern in (
                ("database", r"OperationalError|connection refused|could not connect"),
                ("permission", r"PermissionError|permission denied"),
                ("network", r"NameResolutionError|Name or service not known|network .*not found"),
                ("timeout", r"TimeoutExpired|timed out"),
                ("syntax", r"SyntaxError"),
            )
            if re.search(pattern, diagnostic_text, re.IGNORECASE)
        ]
        frames = [
            {
                "file": Path(filename.replace("\\", "/")).name,
                "line": int(line),
                "function": function,
            }
            for filename, line, function in re.findall(
                r'File "([^"\r\n]+\.py)", line ([0-9]+), in ([A-Za-z0-9_<>]+)', diagnostic_text
            )[-8:]
        ]
        payload: dict[str, object] = {
            "schema": "release.rehearsal-command-progress.v1",
            "invocation_id": invocation_id,
            "command": command.label,
            "outcome": outcome,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "timeout_seconds": command.timeout_seconds,
            "returncode": returncode,
            "stdout_bytes": len(stdout if isinstance(stdout, bytes) else stdout.encode()),
            "stderr_bytes": len(stderr if isinstance(stderr, bytes) else stderr.encode()),
            "diagnostic_categories": categories,
            "traceback_locations": frames,
            "stable_error_codes": sorted(set(STABLE_REHEARSAL_CODE.findall(diagnostic_text))),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        with self._progress_lock:
            atomic_json(self.progress_dir / "current-command.json", payload)
            active_dir = self.progress_dir / "active-commands"
            active_dir.mkdir(mode=0o700, exist_ok=True)
            active_path = active_dir / f"{invocation_id}.json"
            if outcome == "running":
                self._active_progress[invocation_id] = payload
                atomic_json(active_path, payload)
            else:
                self._active_progress.pop(invocation_id, None)
                active_path.unlink(missing_ok=True)
            active_commands = sorted(
                self._active_progress.values(),
                key=lambda item: (str(item["command"]), str(item["invocation_id"])),
            )
            atomic_json(
                self.progress_dir / "active-commands.json",
                {
                    "schema": "release.rehearsal-active-commands.v1",
                    "active_count": len(active_commands),
                    "active_commands": active_commands,
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
            if outcome != "running":
                atomic_json(self.progress_dir / f"{command.label}-{invocation_id}.json", payload)

    def run(self, command: Command) -> CommandResult:
        """Run one command and convert launch errors to a failed result."""
        environment = os.environ.copy()
        environment.update(command.env)
        started = time.monotonic()
        invocation_id = uuid4().hex
        self._progress(command, invocation_id, started, outcome="running")
        if self._cancelled.is_set():
            self._progress(command, invocation_id, started, outcome="interrupted", returncode=130)
            return CommandResult(130)
        try:
            process = subprocess.Popen(
                command.argv,
                cwd=command.cwd,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=sys.platform != "win32",
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                    if sys.platform == "win32"
                    else 0
                ),
            )
            with self._active_lock:
                self._active_processes[process.pid] = process
            try:
                with process:
                    while True:
                        if self._cancelled.is_set():
                            self._stop_process(process)
                            stdout, stderr = process.communicate(timeout=10)
                            self._progress(
                                command,
                                invocation_id,
                                started,
                                outcome="interrupted",
                                stdout=stdout,
                                stderr=stderr,
                                returncode=130,
                            )
                            self._remove_stage_container(command)
                            return CommandResult(130, stdout, stderr)
                        remaining = command.timeout_seconds - (time.monotonic() - started)
                        try:
                            stdout, stderr = process.communicate(
                                timeout=max(0.001, min(5, remaining))
                            )
                            break
                        except subprocess.TimeoutExpired as exc:
                            self._progress(
                                command,
                                invocation_id,
                                started,
                                outcome="running",
                                stdout=exc.output or b"",
                                stderr=exc.stderr or b"",
                            )
                            if time.monotonic() - started >= command.timeout_seconds:
                                self._stop_process(process)
                                stdout, stderr = process.communicate(timeout=10)
                                self._progress(
                                    command,
                                    invocation_id,
                                    started,
                                    outcome="timed_out",
                                    stdout=stdout,
                                    stderr=stderr + "\nTimeoutExpired",
                                    returncode=124,
                                )
                                self._remove_stage_container(command)
                                return CommandResult(124, stdout, stderr)
                        except KeyboardInterrupt:
                            self._stop_process(process)
                            self._remove_stage_container(command)
                            self._progress(
                                command,
                                invocation_id,
                                started,
                                outcome="interrupted",
                                returncode=130,
                            )
                            raise
            finally:
                with self._active_lock:
                    self._active_processes.pop(process.pid, None)
            if self._cancelled.is_set():
                self._progress(
                    command,
                    invocation_id,
                    started,
                    outcome="interrupted",
                    stdout=stdout,
                    stderr=stderr,
                    returncode=130,
                )
                self._remove_stage_container(command)
                return CommandResult(130, stdout, stderr)
            self._progress(
                command,
                invocation_id,
                started,
                outcome="success" if process.returncode == 0 else "failed",
                stdout=stdout,
                stderr=stderr,
                returncode=process.returncode,
            )
            return CommandResult(process.returncode, stdout, stderr)
        except (OSError, subprocess.SubprocessError) as exc:
            self._progress(
                command,
                invocation_id,
                started,
                outcome="launch_failed",
                stderr=type(exc).__name__,
                returncode=127,
            )
            return CommandResult(127, stderr=type(exc).__name__)

    def _stop_process(self, process: subprocess.Popen[str]) -> None:
        """Stop only this command's process tree so inherited pipes cannot hang a timeout."""
        if sys.platform == "win32":
            subprocess.run(
                ("taskkill", "/PID", str(process.pid), "/T", "/F"),
                capture_output=True,
                timeout=10,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if process.poll() is None:
                process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _remove_stage_container(self, command: Command) -> None:
        """Remove only the uniquely named container launched by this command."""
        if command.argv[:2] != ("docker", "run") or "--name" not in command.argv:
            return
        name = command.argv[command.argv.index("--name") + 1]
        if re.fullmatch(r"agom-s6-stage-[0-9a-f]{32}", name) is None:
            return
        cleanup = subprocess.run(
            ("docker", "rm", "--force", name), capture_output=True, timeout=30, check=False
        )
        if cleanup.returncode:
            raise OSError("S6_CONTAINER_CLEANUP_FAILED")


@dataclass(frozen=True)
class RehearsalConfig:
    """Explicit existing-command inputs; no deployment command is accepted."""

    root: Path
    output_dir: Path
    build_host: str
    build_user: str
    password_file: Path
    provider_env_file: Path
    isolated_postgres_env_file: Path
    docker_network: str
    isolated_database_name: str
    isolated_database_host: str
    isolated_database_container: str
    isolated_redis_host: str
    isolated_redis_container: str
    target_trade_date: str
    universe_sha256: str
    provider_identities_path: Path
    provider_settings_json: Path
    unit_contract_path: Path
    transport_input_paths: tuple[Path, ...]
    quote_provider_id: int
    valuation_provider_id: int
    provider_request_limit: int
    provider_window_seconds: float
    task_deadline_seconds: float
    lock_wait_limit_seconds: float
    github_repository: str
    github_run_id: int
    max_age_hours: float = 24.0
    build_timeout_seconds: int = 3600
    stage_timeout_seconds: int = 3600
    provider_probe_timeout_seconds: int = 1800
    max_dispatches: int = 100
    resume: bool = False


@dataclass(frozen=True)
class Identity:
    """Source/image/scope identity frozen before running producer stages."""

    candidate_sha: str
    candidate_image_id: str
    release_tag: str
    image_tag: str
    target_trade_date: str
    universe_sha256: str
    provider_identities_sha256: str
    provider_settings_raw_file_sha256: str
    provider_settings_canonical_payload_sha256: str


@dataclass(frozen=True)
class RehearsalInputs:
    """Validated input bytes and identities captured once at rehearsal startup."""

    target_date: date
    provider_identities: tuple[RehearsalProviderIdentity, ...]
    provider_identities_sha256: str
    provider_identities_raw: bytes
    provider_settings_raw: bytes
    provider_settings_raw_file_sha256: str
    provider_settings_canonical_payload_sha256: str
    unit_contract_raw: bytes
    provider_env_raw: bytes
    isolated_env_raw: bytes


@dataclass(frozen=True)
class StageSpec:
    """One fixed stage in the release rehearsal sequence."""

    name: str
    report_name: str
    argv: tuple[str, ...]
    env_files: tuple[Path, ...]
    image_bound: bool = True
    retain_responses: bool = False
    mounts: tuple[tuple[Path, str, bool], ...] = ()


class RehearsalBlocked(RuntimeError):
    """Stable stage and error code safe to show to an operator."""

    def __init__(self, stage: str, code: str) -> None:
        super().__init__(f"{stage}:{code}")
        self.stage = stage
        self.code = code


def _object(value: object, code: str) -> dict[str, object]:
    """Narrow decoded JSON into a string-keyed object."""
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(code)
    return cast(dict[str, object], value)


def _read_file(path: Path, maximum: int = 16_777_216) -> bytes:
    """Read a bounded regular file and reject symlinks."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("S6_INPUT_FILE_INVALID")
    raw = path.read_bytes()
    if not raw or len(raw) > maximum:
        raise ValueError("S6_INPUT_FILE_INVALID")
    return raw


def _write_json(path: Path, payload: Mapping[str, object], *, read_only: bool = False) -> None:
    """Create a JSON file exclusively and optionally remove write permission."""
    raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if read_only:
        path.chmod(0o444)


def _canonical_provider_settings_digest(payload: Mapping[str, object]) -> str:
    """Hash the canonical JSON form of a provider settings payload."""
    canonical = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _freeze_provider_settings_snapshot(run_dir: Path, inputs: RehearsalInputs) -> Path:
    """Create or verify the read-only settings copy captured at startup."""
    input_dir = run_dir / "inputs"
    if input_dir.is_symlink():
        raise ValueError("S6_PROVIDER_SETTINGS_SNAPSHOT_INVALID")
    input_dir.mkdir(exist_ok=True)
    path = input_dir / "provider-settings.json"
    if path.is_symlink():
        raise ValueError("S6_PROVIDER_SETTINGS_SNAPSHOT_INVALID")
    if path.exists():
        if not path.is_file() or path.read_bytes() != inputs.provider_settings_raw:
            raise ValueError("S6_PROVIDER_SETTINGS_SNAPSHOT_MISMATCH")
    else:
        with path.open("xb") as stream:
            stream.write(inputs.provider_settings_raw)
            stream.flush()
            os.fsync(stream.fileno())
    if hashlib.sha256(_read_file(path, 65_536)).hexdigest() != (
        inputs.provider_settings_raw_file_sha256
    ):
        raise ValueError("S6_PROVIDER_SETTINGS_SNAPSHOT_MISMATCH")
    path.chmod(0o444)
    return path


def _freeze_private_input(path: Path, raw: bytes) -> Path:
    """Freeze one startup-captured env file without ever decoding or logging it."""

    if path.is_symlink():
        raise ValueError("S6_PRIVATE_INPUT_SNAPSHOT_INVALID")
    if path.exists():
        if not path.is_file() or path.read_bytes() != raw:
            raise ValueError("S6_PRIVATE_INPUT_SNAPSHOT_MISMATCH")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    path.chmod(0o400 if os.name == "posix" else 0o444)
    return path


def _invoke(
    runner: CommandRunner,
    *,
    argv: Sequence[str],
    root: Path,
    label: str,
    timeout: float,
    env: Mapping[str, str] | None = None,
    artifact_dir: Path | None = None,
) -> CommandResult:
    """Run one stage and expose only an unambiguous stable rehearsal error code."""
    result = runner.run(Command(tuple(argv), root, env or {}, timeout, label, artifact_dir))
    if result.returncode:
        output = result.stdout + "\n" + result.stderr
        safe_codes = set(STABLE_REHEARSAL_CODE.findall(output))
        safe_codes.update(STABLE_REHEARSAL_HEADROOM_ERROR_CODE.findall(output))
        for line in output.splitlines():
            try:
                payload: object = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or set(payload) != {"outcome", "code"}:
                continue
            code = payload.get("code")
            if (
                payload.get("outcome") == "blocked"
                and isinstance(code, str)
                and STABLE_REHEARSAL_CODE_VALUE.fullmatch(code) is not None
            ):
                safe_codes.add(code)
        code = (
            "S6_STAGE_TIMEOUT"
            if result.returncode == 124
            else safe_codes.pop() if len(safe_codes) == 1 else "S6_STAGE_COMMAND_FAILED"
        )
        raise RehearsalBlocked(label, code)
    return result


def _invoke_container_stage(
    runner: CommandRunner,
    *,
    argv: Sequence[str],
    root: Path,
    label: str,
    timeout: float,
    env: Mapping[str, str],
    artifact_dir: Path,
    container_gid: int,
) -> CommandResult:
    """Grant only the candidate group write access, then seal the evidence directory."""

    if artifact_dir.is_symlink() or not artifact_dir.is_dir():
        raise RehearsalBlocked(label, "S6_ARTIFACT_DIRECTORY_INVALID")
    directory_fd: int | None = None
    if os.name == "posix":
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            directory_fd = os.open(artifact_dir, flags)
            initial = os.fstat(directory_fd)
        except OSError as exc:
            if directory_fd is not None:
                os.close(directory_fd)
            raise RehearsalBlocked(label, "S6_ARTIFACT_DIRECTORY_INVALID") from exc
    else:
        initial = artifact_dir.stat()
    identity = (initial.st_dev, initial.st_ino)
    try:
        if os.name == "posix":
            chown = cast(_Chown | None, getattr(os, "chown", None))
            if chown is None:
                raise RehearsalBlocked(label, "S6_ARTIFACT_DIRECTORY_OWNERSHIP_UNAVAILABLE")
            chown(artifact_dir, -1, container_gid)
            artifact_dir.chmod(0o2770)
            writable = artifact_dir.stat()
            if writable.st_gid != container_gid or stat.S_IMODE(writable.st_mode) != 0o2770:
                raise RehearsalBlocked(label, "S6_ARTIFACT_DIRECTORY_OWNERSHIP_FAILED")
        else:
            artifact_dir.chmod(0o770)
        return _invoke(
            runner,
            argv=argv,
            root=root,
            label=label,
            timeout=timeout,
            env=env,
            artifact_dir=artifact_dir,
        )
    finally:
        changed = True
        try:
            current = artifact_dir.lstat()
            changed = artifact_dir.is_symlink() or (current.st_dev, current.st_ino) != identity
        except OSError:
            pass
        try:
            if not changed:
                artifact_dir.chmod(0o750)
        finally:
            if directory_fd is not None:
                os.close(directory_fd)
        if changed:
            raise RehearsalBlocked(label, "S6_ARTIFACT_DIRECTORY_CHANGED")


def _candidate_container_gid(runner: CommandRunner, root: Path, image_id: str) -> int:
    """Resolve the exact candidate image's primary group without trusting its tag."""

    result = _invoke(
        runner,
        argv=("docker", "run", "--rm", "--entrypoint", "/usr/bin/id", image_id, "-g"),
        root=root,
        label="docker_gid",
        timeout=60,
    )
    try:
        gid = int(result.stdout.strip())
    except ValueError as exc:
        raise RehearsalBlocked("docker_gid", "S6_CONTAINER_GID_INVALID") from exc
    if gid < 0 or gid > 2_147_483_647:
        raise RehearsalBlocked("docker_gid", "S6_CONTAINER_GID_INVALID")
    return gid


def _candidate_sha(runner: CommandRunner, root: Path) -> str:
    """Freeze the full commit SHA and require a clean tracked/untracked tree."""
    head = _invoke(
        runner, argv=("git", "rev-parse", "HEAD"), root=root, label="git_head", timeout=15
    ).stdout.strip()
    if COMMIT.fullmatch(head) is None:
        raise RehearsalBlocked("candidate", "S6_CANDIDATE_SHA_INVALID")
    status = _invoke(
        runner,
        argv=("git", "status", "--porcelain=v1", "--untracked-files=all"),
        root=root,
        label="git_status",
        timeout=15,
    ).stdout.strip()
    if status:
        raise RehearsalBlocked("candidate", "S6_WORKTREE_DIRTY")
    return head


def _assert_launcher_provenance(root: Path, *, launcher_path: Path | None = None) -> None:
    """Require the CLI launcher to come from the selected checkout."""
    selected = (root / "scripts" / "run_release_rehearsal.py").resolve()
    actual = (launcher_path or Path(__file__)).resolve()
    if actual != selected or not selected.is_file():
        raise RehearsalBlocked("inputs", "S6_LAUNCHER_PROVENANCE_INVALID")


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a Docker env file without ever exposing its values in failures."""
    try:
        raw = _read_file(path)
        return _parse_env_bytes(raw)
    except UnicodeError as exc:
        raise RehearsalBlocked("inputs", "S6_ISOLATED_ENV_INVALID") from exc


def _parse_env_bytes(raw: bytes) -> dict[str, str]:
    """Parse already-captured Docker env bytes without exposing values."""

    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise RehearsalBlocked("inputs", "S6_ISOLATED_ENV_INVALID") from exc
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if (
            not separator
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is None
            or key in values
            or "\x00" in value
        ):
            raise RehearsalBlocked("inputs", "S6_ISOLATED_ENV_INVALID")
        values[key] = value
    return values


def _url_identity(value: str, *, schemes: frozenset[str]) -> tuple[str, str]:
    """Return a URL host and decoded path or a stable, secret-free failure."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise RehearsalBlocked("inputs", "S6_ISOLATED_ENV_INVALID") from exc
    if parsed.scheme not in schemes or host is None or port is not None and port <= 0:
        raise RehearsalBlocked("inputs", "S6_ISOLATED_ENV_INVALID")
    return host, unquote(parsed.path.removeprefix("/"))


def _validate_isolated_environment_identity(
    config: RehearsalConfig, isolated_env_raw: bytes | None = None
) -> None:
    """Bind effective database and Redis endpoints before any remote build."""
    values = (
        _parse_env_file(config.isolated_postgres_env_file)
        if isolated_env_raw is None
        else _parse_env_bytes(isolated_env_raw)
    )
    required = {
        "POSTGRES_HOST",
        "POSTGRES_DB",
        "DATABASE_URL",
        "MIGRATOR_DATABASE_URL",
        "REDIS_HOST",
        "REDIS_URL",
        "AGOM_RELEASE_REHEARSAL_DATABASE",
    }
    if not required.issubset(values):
        raise RehearsalBlocked("inputs", "S6_ISOLATED_ENV_IDENTITY_MISMATCH")
    database_host, database_name = _url_identity(
        values["DATABASE_URL"], schemes=frozenset({"postgres", "postgresql"})
    )
    migrator_host, migrator_name = _url_identity(
        values["MIGRATOR_DATABASE_URL"], schemes=frozenset({"postgres", "postgresql"})
    )
    redis_host, _redis_database = _url_identity(
        values["REDIS_URL"], schemes=frozenset({"redis", "rediss"})
    )
    if (
        values["AGOM_RELEASE_REHEARSAL_DATABASE"] != "1"
        or values["POSTGRES_HOST"] != config.isolated_database_host
        or values["POSTGRES_DB"] != config.isolated_database_name
        or database_host != config.isolated_database_host
        or database_name != config.isolated_database_name
        or migrator_host != config.isolated_database_host
        or migrator_name != config.isolated_database_name
        or values["REDIS_HOST"] != config.isolated_redis_host
        or redis_host != config.isolated_redis_host
    ):
        raise RehearsalBlocked("inputs", "S6_ISOLATED_ENV_IDENTITY_MISMATCH")


def _assert_candidate(runner: CommandRunner, root: Path, expected: str) -> None:
    """Ensure the frozen checkout is unchanged before each evidence stage."""
    if _candidate_sha(runner, root) != expected:
        raise RehearsalBlocked("candidate", "S6_CANDIDATE_CHANGED")


def _validate_inputs(
    config: RehearsalConfig,
) -> RehearsalInputs:
    """Validate dates, budgets, provider IDs and all input file identities."""
    root = config.root.resolve()
    output = config.output_dir.resolve()
    if root == output or root in output.parents:
        raise ValueError("S6_OUTPUT_MUST_BE_OUTSIDE_CHECKOUT")
    try:
        target_date = date.fromisoformat(config.target_trade_date)
    except ValueError as exc:
        raise ValueError("S6_TARGET_DATE_INVALID") from exc
    if (
        target_date.isoformat() != config.target_trade_date
        or SHA.fullmatch(config.universe_sha256) is None
        or REPOSITORY.fullmatch(config.github_repository) is None
        or not config.build_host.strip()
        or not config.build_user.strip()
        or not config.docker_network.strip()
        or re.fullmatch(r"agom_release_rehearsal_[a-z0-9_]+", config.isolated_database_name) is None
        or re.fullmatch(r"agom-s6-postgres-[a-z0-9-]+", config.isolated_database_host) is None
        or re.fullmatch(r"agom-s6-(?:pg|postgres)-[a-z0-9-]+", config.isolated_database_container)
        is None
        or re.fullmatch(r"agom-s6-redis-[a-z0-9-]+", config.isolated_redis_host) is None
        or re.fullmatch(r"agom-s6-redis-[a-z0-9-]+", config.isolated_redis_container) is None
        or config.quote_provider_id <= 0
        or config.valuation_provider_id <= 0
        or config.github_run_id <= 0
        or config.provider_request_limit <= 0
        or config.provider_window_seconds <= 0
        or config.task_deadline_seconds <= 0
        or config.lock_wait_limit_seconds <= 0
        or config.build_timeout_seconds <= 0
        or config.stage_timeout_seconds <= 0
        or config.provider_probe_timeout_seconds <= 0
        or config.max_dispatches <= 0
        or not config.transport_input_paths
        or not 0 < config.max_age_hours <= 168
    ):
        raise ValueError("S6_INPUT_INVALID")
    for path in (config.password_file, *config.transport_input_paths):
        _read_file(path)
    provider_env_raw = _read_file(config.provider_env_file)
    isolated_env_raw = _read_file(config.isolated_postgres_env_file)
    _validate_isolated_environment_identity(config, isolated_env_raw)
    provider_raw = _read_file(config.provider_identities_path, 16_384)
    try:
        identities = parse_rehearsal_identities(json.loads(provider_raw))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("S6_PROVIDER_IDENTITY_INVALID") from exc
    by_role = {item.role: item.provider_id for item in identities}
    if (
        by_role.get("quote") != config.quote_provider_id
        or by_role.get("valuation") != config.valuation_provider_id
    ):
        raise ValueError("S6_PROVIDER_IDENTITY_MISMATCH")
    provider_digest = rehearsal_identities_digest(identities)
    settings_raw = _read_file(config.provider_settings_json, 65_536)
    try:
        settings_payload = _object(json.loads(settings_raw), "S6_PROVIDER_SETTINGS_INVALID")
        if any(key != str(key).strip() for key in settings_payload):
            raise ValueError("S6_PROVIDER_SETTINGS_INVALID")
        settings_canonical_digest = _canonical_provider_settings_digest(settings_payload)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("S6_PROVIDER_SETTINGS_INVALID") from exc
    unit_raw = _read_file(config.unit_contract_path, 64_000)
    try:
        unit = _object(json.loads(unit_raw), "S6_UNIT_CONTRACT_INVALID")
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("S6_UNIT_CONTRACT_INVALID") from exc
    if (
        unit.get("schema") != "release.provider-unit-contract.v1"
        or unit.get("provider_identities_sha256") != provider_digest
    ):
        raise ValueError("S6_UNIT_CONTRACT_INVALID")
    return RehearsalInputs(
        target_date=target_date,
        provider_identities=identities,
        provider_identities_sha256=provider_digest,
        provider_identities_raw=provider_raw,
        provider_settings_raw=settings_raw,
        provider_settings_raw_file_sha256=hashlib.sha256(settings_raw).hexdigest(),
        provider_settings_canonical_payload_sha256=settings_canonical_digest,
        unit_contract_raw=unit_raw,
        provider_env_raw=provider_env_raw,
        isolated_env_raw=isolated_env_raw,
    )


def _build_image(
    config: RehearsalConfig,
    runner: CommandRunner,
    run_dir: Path,
    candidate_sha: str,
    checkpoint: _Checkpoint,
) -> tuple[dict[str, object], Path]:
    """Build once in build-only mode, retain the image tar and inspect the loaded image."""
    report_dir, image_dir = run_dir / "build-report", run_dir / "images"
    if not checkpoint.done("build_artifacts"):
        checkpoint.prepare("build_artifacts", (report_dir, image_dir), resume=config.resume)
        report_dir.mkdir()
        image_dir.mkdir()
        builder = config.root / "scripts" / "remote_build_deploy_vps.py"
        argv = (
            sys.executable,
            str(builder),
            "--host",
            config.build_host,
            "--user",
            config.build_user,
            "--password-file",
            str(config.password_file.resolve()),
            "--expected-source-commit",
            candidate_sha,
            "--report-dir",
            str(report_dir),
            "--built-image-dir",
            str(image_dir),
            "--timeout",
            str(config.build_timeout_seconds),
            "--skip-deploy-after-build",
            "--download-built-image",
            "--keep-remote-temp",
        )
        _invoke(
            runner,
            argv=argv,
            root=config.root,
            label="build_only",
            timeout=config.build_timeout_seconds,
            artifact_dir=run_dir,
        )
    reports = tuple(report_dir.glob("remote-build-report-*.json"))
    archives = tuple(image_dir.glob(f"{IMAGE_NAME}-*.tar"))
    if len(reports) != 1 or len(archives) != 1:
        raise RehearsalBlocked("build_only", "S6_BUILD_OUTPUT_INVALID")
    try:
        report = _object(json.loads(_read_file(reports[0])), "S6_BUILD_REPORT_INVALID")
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RehearsalBlocked("build_only", "S6_BUILD_REPORT_INVALID") from exc
    tag, image_tag, image_id = (
        report.get("release_tag"),
        report.get("image_tag"),
        report.get("image_id"),
    )
    if (
        report.get("source_commit") != candidate_sha
        or not isinstance(tag, str)
        or TAG.fullmatch(tag) is None
        or image_tag != f"{IMAGE_NAME}:{tag}"
        or not isinstance(image_id, str)
        or IMAGE_ID.fullmatch(image_id) is None
        or archives[0].name != f"{IMAGE_NAME}-{tag}.tar"
    ):
        raise RehearsalBlocked("build_only", "S6_BUILD_IDENTITY_MISMATCH")
    checkpoint.complete("build_artifacts", (report_dir, image_dir))
    loaded = checkpoint.done("build_only")
    if loaded:
        loaded = (
            runner.run(
                Command(
                    ("docker", "image", "inspect", str(image_id), "--format", "{{.Id}}"),
                    config.root,
                    {},
                    30,
                    "docker_image_available",
                )
            ).returncode
            == 0
        )
    if not loaded:
        _invoke(
            runner,
            argv=("docker", "load", "--input", str(archives[0].resolve())),
            root=config.root,
            label="docker_load",
            timeout=config.stage_timeout_seconds,
            artifact_dir=run_dir,
        )
    inspected = _invoke(
        runner,
        argv=("docker", "image", "inspect", str(image_tag), "--format", "{{json .}}"),
        root=config.root,
        label="docker_inspect",
        timeout=60,
        artifact_dir=run_dir,
    )
    try:
        image = _object(json.loads(inspected.stdout), "S6_IMAGE_INSPECT_INVALID")
        image_config = _object(image.get("Config"), "S6_IMAGE_INSPECT_INVALID")
        labels = _object(image_config.get("Labels"), "S6_IMAGE_INSPECT_INVALID")
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RehearsalBlocked("docker_inspect", "S6_IMAGE_INSPECT_INVALID") from exc
    if (
        image.get("Id") != image_id
        or labels.get("org.opencontainers.image.revision") != candidate_sha
    ):
        raise RehearsalBlocked("docker_inspect", "S6_IMAGE_IDENTITY_MISMATCH")
    return report, archives[0]


def _write_identity(
    run_dir: Path,
    build_report: Mapping[str, object],
    candidate_sha: str,
    target_date: date,
    universe_sha: str,
    provider_digest: str,
    identities: tuple[RehearsalProviderIdentity, ...],
    provider_raw: bytes,
    provider_settings_raw_file_sha256: str,
    provider_settings_canonical_payload_sha256: str,
    unit_raw: bytes,
    *,
    reuse: bool = False,
) -> tuple[Identity, Path, Path, Path]:
    """Write read-only identity, release manifest and provider snapshots."""
    image_id = cast(str, build_report["image_id"])
    identity = Identity(
        candidate_sha,
        image_id,
        cast(str, build_report["release_tag"]),
        cast(str, build_report["image_tag"]),
        target_date.isoformat(),
        universe_sha,
        provider_digest,
        provider_settings_raw_file_sha256,
        provider_settings_canonical_payload_sha256,
    )
    input_dir = run_dir / "inputs"
    if reuse:
        return (
            identity,
            input_dir / "candidate-identity.json",
            input_dir / "candidate-release-manifest.json",
            input_dir / "provider-identities.json",
        )
    input_dir.mkdir(exist_ok=True)
    identity_path = input_dir / "candidate-identity.json"
    manifest_path = input_dir / "candidate-release-manifest.json"
    provider_path = input_dir / "provider-identities.json"
    unit_path = input_dir / "provider-unit-contract.json"
    _write_json(
        identity_path,
        {**asdict(identity), "provider_identities": [asdict(i) for i in identities]},
        read_only=True,
    )
    _write_json(
        manifest_path,
        {
            "schema": "release.candidate-manifest.v1",
            "version": build_report.get("version"),
            "release_tag": identity.release_tag,
            "candidate_sha": candidate_sha,
            "source_commit": candidate_sha,
            "image_tag": identity.image_tag,
            "image_id": image_id,
            "candidate_image_id": image_id,
            "target_trade_date": identity.target_trade_date,
            "universe_sha256": identity.universe_sha256,
            "provider_identities_sha256": identity.provider_identities_sha256,
            "provider_settings_raw_file_sha256": identity.provider_settings_raw_file_sha256,
            "provider_settings_canonical_payload_sha256": (
                identity.provider_settings_canonical_payload_sha256
            ),
            "build_started_at": build_report.get("build_started_at"),
            "build_finished_at": build_report.get("build_finished_at"),
            "source_mode": build_report.get("source_mode"),
        },
        read_only=True,
    )
    for path, raw in ((provider_path, provider_raw), (unit_path, unit_raw)):
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o444)
    if (
        _object(json.loads(unit_raw), "S6_UNIT_CONTRACT_INVALID").get("candidate_sha")
        != candidate_sha
    ):
        raise RehearsalBlocked("identity", "S6_UNIT_CONTRACT_CANDIDATE_MISMATCH")
    return identity, identity_path, manifest_path, provider_path


def _mount(path: Path, target: str, readonly: bool) -> str:
    """Format a Docker bind mount and reject option-injection characters."""
    source = str(path.resolve())
    if any(char in source for char in (",", "\r", "\n")):
        raise RehearsalBlocked("container", "S6_MOUNT_PATH_INVALID")
    return f"{source}:{target}:{'ro' if readonly else 'rw'}"


def _docker_command(
    identity: Identity,
    network: str,
    env_files: Sequence[Path],
    identity_path: Path,
    manifest_path: Path,
    provider_path: Path,
    stage_dir: Path,
    stage: StageSpec,
) -> tuple[str, ...]:
    """Pin a producer container to the measured image ID and shared identity."""
    args: list[str] = [
        "docker",
        "run",
        "--rm",
        "--name",
        f"agom-s6-stage-{uuid4().hex}",
        "--label",
        "agom.s6.run="
        + hashlib.sha256(str(identity_path.parent.parent.resolve()).encode()).hexdigest(),
        "--network",
        network,
    ]
    for env_file in env_files:
        args.extend(("--env-file", str(env_file.resolve())))
    args.extend(
        (
            "--env",
            f"AGOM_CANDIDATE_IMAGE_ID={identity.candidate_image_id}",
            "--env",
            "AGOM_RELEASE_MANIFEST_PATH=/run/agom/candidate-release-manifest.json",
        )
    )
    mounts = [
        (identity_path, "/run/agom/candidate-identity.json", True),
        (manifest_path, "/run/agom/candidate-release-manifest.json", True),
        (provider_path, "/run/agom/provider-identities.json", True),
        (stage_dir, "/run/agom/stage", False),
        *stage.mounts,
    ]
    for source, target, readonly in mounts:
        args.extend(("--volume", _mount(source, target, readonly)))
    args.extend((identity.candidate_image_id, *stage.argv))
    return tuple(args)


def _report(path: Path, identity: Identity, *, image_bound: bool) -> dict[str, object]:
    """Require success and exact shared scope for a produced report."""
    try:
        value = _object(json.loads(_read_file(path)), "S6_STAGE_REPORT_INVALID")
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RehearsalBlocked(path.parent.name, "S6_STAGE_REPORT_INVALID") from exc
    provider_digest = value.get("provider_identities_sha256")
    if provider_digest is None and value.get("kind") == "candidate_regression_evidence":
        try:
            ci_identities = parse_rehearsal_identities(value.get("provider_identities"))
            provider_digest = rehearsal_identities_digest(ci_identities)
        except ValueError as exc:
            raise RehearsalBlocked(path.parent.name, "S6_STAGE_IDENTITY_MISMATCH") from exc
    if (
        value.get("outcome") != "success"
        or value.get("candidate_sha") != identity.candidate_sha
        or value.get("target_trade_date") != identity.target_trade_date
        or value.get("universe_sha256") != identity.universe_sha256
        or provider_digest != identity.provider_identities_sha256
        or (image_bound and value.get("candidate_image_id") != identity.candidate_image_id)
        or (
            value.get("kind") == "production_policy_parity"
            and (
                value.get("provider_settings_raw_file_sha256")
                != identity.provider_settings_raw_file_sha256
                or value.get("provider_settings_canonical_payload_sha256")
                != identity.provider_settings_canonical_payload_sha256
            )
        )
    ):
        raise RehearsalBlocked(path.parent.name, "S6_STAGE_IDENTITY_MISMATCH")
    return value


def _stage_specs(
    config: RehearsalConfig, identity: Identity, paths: Mapping[str, str | Path]
) -> tuple[StageSpec, ...]:
    """Render fixed producer commands from the frozen candidate configuration."""
    common = ("--candidate-sha", identity.candidate_sha)
    provider = (
        "python",
        "manage.py",
        "rehearse_market_providers",
        *common,
        "--target-trade-date",
        identity.target_trade_date,
        "--quote-provider-id",
        str(config.quote_provider_id),
        "--valuation-provider-id",
        str(config.valuation_provider_id),
        "--provider-identities",
        "/run/agom/provider-identities.json",
        "--sample-size",
        "50",
        "--max-dispatches",
        str(config.max_dispatches),
        "--max-seconds",
        str(config.provider_probe_timeout_seconds),
        "--output",
        "/run/agom/stage/probe.json",
        "--response-evidence-root",
        "/run/agom/stage",
    )
    replay = (
        "python",
        "manage.py",
        "replay_market_provider_responses",
        "--probe",
        "/run/agom/provider-probe/probe.json",
        "--probe-sha256",
        cast(str, paths["probe_sha"]),
        "--unit-contract",
        "/run/agom/unit-contract.json",
        "--unit-contract-sha256",
        cast(str, paths["unit_sha"]),
        *common,
        "--target-trade-date",
        identity.target_trade_date,
        "--output-dir",
        "/run/agom/stage/output",
    )
    capacity = (
        "python",
        "manage.py",
        "rehearse_full_universe_capacity",
        *common,
        "--target-trade-date",
        identity.target_trade_date,
        "--quote-provider-id",
        str(config.quote_provider_id),
        "--valuation-provider-id",
        str(config.valuation_provider_id),
        "--provider-identities",
        "/run/agom/provider-identities.json",
        "--provider-request-limit",
        str(config.provider_request_limit),
        "--provider-window-seconds",
        str(config.provider_window_seconds),
        "--task-deadline-seconds",
        str(config.task_deadline_seconds),
        "--lock-wait-limit-seconds",
        str(config.lock_wait_limit_seconds),
        "--max-dispatches",
        str(config.max_dispatches),
        "--output-dir",
        "/run/agom/stage/output",
    )
    parity = (
        "python",
        "manage.py",
        "rehearse_production_policy_parity",
        *common,
        "--target-trade-date",
        identity.target_trade_date,
        "--universe-sha256",
        identity.universe_sha256,
        "--provider-identities-sha256",
        identity.provider_identities_sha256,
        "--expected-provider-settings-raw-file-sha256",
        identity.provider_settings_raw_file_sha256,
        "--expected-provider-settings-canonical-payload-sha256",
        identity.provider_settings_canonical_payload_sha256,
        "--provider-identities",
        "/run/agom/provider-identities.json",
        "--provider-settings-json",
        "/run/agom/provider-settings.json",
        "--output-dir",
        "/run/agom/stage/output",
    )
    isolated = (
        "python",
        "manage.py",
        "rehearse_isolated_publication_write",
        *common,
        "--target-trade-date",
        identity.target_trade_date,
        "--universe-sha256",
        identity.universe_sha256,
        "--provider-identities-sha256",
        identity.provider_identities_sha256,
        "--expected-database-name",
        config.isolated_database_name,
        "--expected-database-host",
        config.isolated_database_host,
        "--initialize-reviewed-catalog",
        "--output-dir",
        "/run/agom/stage/output",
    )
    financial_slice = (
        "python",
        "manage.py",
        "rehearse_akshare_financial_slice",
        *common,
        "--target-trade-date",
        identity.target_trade_date,
        "--universe-sha256",
        identity.universe_sha256,
        "--provider-identities-sha256",
        identity.provider_identities_sha256,
        "--expected-database-name",
        config.isolated_database_name,
        "--expected-database-host",
        config.isolated_database_host,
        "--expected-redis-host",
        config.isolated_redis_host,
        "--provider-identities",
        "/run/agom/provider-identities.json",
        "--candidate-regression-evidence",
        "/run/agom/ci/candidate-regression-evidence.json",
        "--output-dir",
        "/run/agom/stage/output",
    )
    return (
        StageSpec(
            "provider_probe",
            "probe.json",
            provider,
            (config.provider_env_file, config.isolated_postgres_env_file),
            retain_responses=True,
        ),
        StageSpec(
            "response_replay",
            "output/real-response-unit-replay.json",
            replay,
            (config.provider_env_file, config.isolated_postgres_env_file),
            mounts=(
                (cast(Path, paths["provider_dir"]), "/run/agom/provider-probe", True),
                (cast(Path, paths["unit_path"]), "/run/agom/unit-contract.json", True),
            ),
        ),
        StageSpec(
            "full_universe_capacity",
            "output/full-universe-capacity.json",
            capacity,
            (config.provider_env_file, config.isolated_postgres_env_file),
        ),
        StageSpec(
            "production_policy_parity",
            "output/production-policy-parity.json",
            parity,
            (config.provider_env_file, config.isolated_postgres_env_file),
            mounts=(
                (
                    cast(Path, paths["provider_settings_path"]),
                    "/run/agom/provider-settings.json",
                    True,
                ),
            ),
        ),
        StageSpec(
            "isolated_postgresql_write",
            "output/isolated-write-rehearsal.json",
            isolated,
            (config.isolated_postgres_env_file,),
        ),
        StageSpec(
            "akshare_financial_slice",
            "output/akshare-financial-slice.json",
            financial_slice,
            (config.provider_env_file, config.isolated_postgres_env_file),
            mounts=((cast(Path, paths["ci_dir"]), "/run/agom/ci", True),),
        ),
    )


def bundle_tree_digest(bundle_dir: Path) -> str:
    """Hash all relative paths and bytes in a bundle, rejecting symlinks."""
    if bundle_dir.is_symlink() or not bundle_dir.is_dir():
        raise ValueError("S6_BUNDLE_DIRECTORY_INVALID")
    entries: list[dict[str, object]] = []
    for path in sorted(bundle_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError("S6_BUNDLE_SYMLINK_REJECTED")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("S6_BUNDLE_ENTRY_INVALID")
        raw = path.read_bytes()
        entries.append(
            {
                "path": path.relative_to(bundle_dir).as_posix(),
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    if not entries:
        raise ValueError("S6_BUNDLE_EMPTY")
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _freeze_bundle(bundle_dir: Path) -> None:
    """Make all regular bundle files read-only before validation."""
    for path in bundle_dir.rglob("*"):
        if path.is_symlink():
            raise RehearsalBlocked("bundle_build", "S6_BUNDLE_SYMLINK_REJECTED")
        if path.is_file():
            path.chmod(0o444)


def _status(
    path: Path, outcome: str, completed: Sequence[str], stage: str | None, code: str | None
) -> None:
    """Write safe progress for this run, never command output or credentials."""
    _write = {
        "schema": "release.rehearsal-launch-status.v1",
        "outcome": outcome,
        "completed_stages": list(completed),
        "current_stage": stage,
        "error_code": code,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    atomic_json(path, _write)


def _checkpoint_binding(
    config: RehearsalConfig, candidate: str, inputs: RehearsalInputs
) -> dict[str, object]:
    """Bind all semantic inputs without storing environment secrets in the journal."""
    values: dict[str, object] = {"candidate_sha": candidate}
    for key, value in asdict(config).items():
        if key in {"resume", "password_file", "build_timeout_seconds"}:
            continue
        if isinstance(value, Path):
            if key in {"root", "output_dir"}:
                values[key] = str(value.resolve())
            elif key == "provider_settings_json":
                values[key] = inputs.provider_settings_raw_file_sha256
            else:
                values[key] = file_digest(value)
        elif key == "transport_input_paths":
            values[key] = [file_digest(Path(path)) for path in value]
        else:
            values[key] = value
    values["provider_settings_canonical_payload_sha256"] = (
        inputs.provider_settings_canonical_payload_sha256
    )
    return values


def _preflight_isolated_container(
    config: RehearsalConfig,
    runner: CommandRunner,
    *,
    label: str,
    container: str,
    host: str,
    invalid_code: str,
) -> str:
    """Bind an isolated service host to its running container and network."""
    template = (
        '{"id":{{json .Id}},"name":{{json .Name}},'
        '"running":{{json .State.Running}},'
        '"networks":{{json .NetworkSettings.Networks}}}'
    )
    result = _invoke(
        runner,
        argv=(
            "docker",
            "container",
            "inspect",
            container,
            "--format",
            template,
        ),
        root=config.root,
        label=label,
        timeout=30,
    )
    try:
        payload = _object(json.loads(result.stdout), invalid_code)
        networks = _object(payload.get("networks"), invalid_code)
        network = _object(networks.get(config.docker_network), invalid_code)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RehearsalBlocked(
            label,
            invalid_code,
        ) from exc
    container_id = payload.get("id")
    network_names: set[str] = set()
    for key in ("Aliases", "DNSNames"):
        values = network.get(key)
        if isinstance(values, list):
            network_names.update(value for value in values if isinstance(value, str))
    if (
        not isinstance(container_id, str)
        or re.fullmatch(r"[0-9a-f]{64}", container_id) is None
        or payload.get("name") != f"/{container}"
        or payload.get("running") is not True
        or host not in network_names
    ):
        raise RehearsalBlocked(
            label,
            invalid_code,
        )
    return container_id


def _preflight_isolated_database_container(config: RehearsalConfig, runner: CommandRunner) -> str:
    """Bind the configured isolated database host to its running container."""
    return _preflight_isolated_container(
        config,
        runner,
        label="preflight_isolated_database_container",
        container=config.isolated_database_container,
        host=config.isolated_database_host,
        invalid_code="S6_ISOLATED_DATABASE_CONTAINER_INVALID",
    )


def _preflight_environment(config: RehearsalConfig, runner: CommandRunner) -> None:
    """Check the execution daemon and exact network before paying for a remote build."""
    for label, argv in (
        ("preflight_docker", ("docker", "info", "--format", "{{.ID}}")),
        ("preflight_network", ("docker", "network", "inspect", config.docker_network)),
    ):
        _invoke(runner, argv=argv, root=config.root, label=label, timeout=30)
    _preflight_isolated_database_container(config, runner)
    _preflight_isolated_container(
        config,
        runner,
        label="preflight_isolated_redis_container",
        container=config.isolated_redis_container,
        host=config.isolated_redis_host,
        invalid_code="S6_ISOLATED_REDIS_CONTAINER_INVALID",
    )
    run_id = hashlib.sha256(str(config.output_dir.resolve()).encode()).hexdigest()
    containers = _invoke(
        runner,
        argv=("docker", "ps", "--filter", f"label=agom.s6.run={run_id}", "--format", "{{.ID}}"),
        root=config.root,
        label="preflight_containers",
        timeout=30,
    )
    if containers.stdout.strip():
        raise RehearsalBlocked("preflight_containers", "S6_RUN_CONTAINERS_ACTIVE")


def _missing_release_runner_dependencies() -> tuple[str, ...]:
    """Return the secret-free dependency marker when the pinned SSH runtime is absent."""

    if importlib.util.find_spec("paramiko") is None:
        return ("paramiko",)
    try:
        version = importlib.metadata.version("paramiko")
    except importlib.metadata.PackageNotFoundError:
        return ("paramiko",)
    return () if version == REQUIRED_PARAMIKO_VERSION else ("paramiko",)


def _run_prebuild_stage_environment_preflight(config: RehearsalConfig) -> None:
    """Reject static build/identity assumptions before an expensive remote build."""

    isolated_values = _parse_env_file(config.isolated_postgres_env_file)
    provider_values = _parse_env_file(config.provider_env_file)
    missing = tuple(
        sorted(
            (
                {
                    "POSTGRES_HOST",
                    "POSTGRES_DB",
                    "DATABASE_URL",
                    "MIGRATOR_DATABASE_URL",
                    "REDIS_HOST",
                    "REDIS_URL",
                    "AGOM_RELEASE_REHEARSAL_DATABASE",
                }
                - isolated_values.keys()
            )
            | ({"DJANGO_SETTINGS_MODULE"} - provider_values.keys())
        )
    )
    missing_runtime_dependencies = _missing_release_runner_dependencies()
    files = (
        config.root,
        config.output_dir,
        config.password_file,
        config.provider_env_file,
        config.isolated_postgres_env_file,
        config.provider_identities_path,
        config.provider_settings_json,
        config.unit_contract_path,
        *config.transport_input_paths,
    )
    report = evaluate_stage_environment(
        StageEnvironmentInputs(
            stages=("build_only", "docker_identity"),
            filesystem_paths=files,
            text_transport_paths=(
                config.provider_env_file,
                config.isolated_postgres_env_file,
                config.provider_identities_path,
                config.provider_settings_json,
                config.unit_contract_path,
                *config.transport_input_paths,
            ),
            missing_identity_keys=missing,
            free_disk_bytes=shutil.disk_usage(config.output_dir).free,
            available_memory_bytes=_available_memory_bytes(),
            observed_at=datetime.now(UTC),
            build_timeout_seconds=config.build_timeout_seconds,
            stage_timeout_seconds=config.stage_timeout_seconds,
            provider_timeout_seconds=config.provider_probe_timeout_seconds,
            task_deadline_seconds=config.task_deadline_seconds,
            lock_wait_limit_seconds=config.lock_wait_limit_seconds,
            missing_runtime_dependencies=missing_runtime_dependencies,
            minimum_free_disk_bytes=MINIMUM_PREBUILD_FREE_DISK_BYTES,
        )
    )
    preflight_dir = config.output_dir / "stage-environment-preflight"
    preflight_dir.mkdir(exist_ok=True)
    atomic_json(preflight_dir / "prebuild-stage-environment-preflight.json", report)
    if report.get("outcome") != "pass":
        raise RehearsalBlocked(
            "stage_environment_preflight", "REHEARSAL_STAGE_ENVIRONMENT_PREFLIGHT_FAILED"
        )


def _available_memory_bytes() -> int:
    """Read Linux available memory without adding a mutable runtime dependency."""

    path = Path("/proc/meminfo")
    if not path.is_file():
        return MINIMUM_AVAILABLE_MEMORY_BYTES if os.name != "posix" else 0
    try:
        for line in path.read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                fields = line.split()
                return int(fields[1]) * 1024 if len(fields) == 3 and fields[2] == "kB" else 0
    except (OSError, UnicodeError, ValueError):
        return 0
    return 0


def _dynamic_stage_environment_issues(
    config: RehearsalConfig,
    runner: CommandRunner,
    identity: Identity,
    identity_path: Path,
    manifest_path: Path,
    provider_path: Path,
    run_dir: Path,
) -> tuple[StageEnvironmentIssue, ...]:
    """Run the candidate's read-only production-composition probes and parse safe issues."""

    preflight_dir = run_dir / "stage-environment-preflight"
    preflight_dir.mkdir(exist_ok=True)
    settings_path = run_dir / "inputs" / "provider-settings.json"
    spec = StageSpec(
        "stage_environment_preflight",
        "",
        (
            "python",
            "manage.py",
            "preflight_s6_stage_environment",
            "--provider-settings-json",
            "/run/agom/provider-settings.json",
            "--provider-identities",
            "/run/agom/provider-identities.json",
            "--output",
            "/run/agom/stage/dynamic-stage-environment-preflight.json",
        ),
        (config.provider_env_file, config.isolated_postgres_env_file),
        mounts=((settings_path, "/run/agom/provider-settings.json", True),),
    )
    argv = _docker_command(
        identity,
        config.docker_network,
        spec.env_files,
        identity_path,
        manifest_path,
        provider_path,
        preflight_dir,
        spec,
    )
    try:
        _invoke_container_stage(
            runner,
            argv=argv,
            root=config.root,
            label=spec.name,
            timeout=min(config.stage_timeout_seconds, 180),
            env={},
            artifact_dir=preflight_dir,
            container_gid=_candidate_container_gid(
                runner, config.root, identity.candidate_image_id
            ),
        )
    except RehearsalBlocked:
        return (
            StageEnvironmentIssue(
                "external_state",
                "REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_UNAVAILABLE",
                STAGES,
            ),
        )
    try:
        report_path = preflight_dir / "dynamic-stage-environment-preflight.json"
        payload = _object(
            json.loads(_read_file(report_path, 1_048_576)),
            "S6_STAGE_PREFLIGHT_REPORT_INVALID",
        )
        return tuple(parse_dynamic_issues(payload))
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return (
            StageEnvironmentIssue(
                "external_state",
                "REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_REPORT_INVALID",
                STAGES,
            ),
        )


def _run_stage_environment_preflight(
    config: RehearsalConfig,
    runner: CommandRunner,
    identity: Identity,
    identity_path: Path,
    manifest_path: Path,
    provider_path: Path,
    run_dir: Path,
) -> None:
    """Aggregate every known environment gap before any candidate evidence stage."""

    isolated_values = _parse_env_file(config.isolated_postgres_env_file)
    provider_values = _parse_env_file(config.provider_env_file)
    required_isolated = {
        "POSTGRES_HOST",
        "POSTGRES_DB",
        "DATABASE_URL",
        "MIGRATOR_DATABASE_URL",
        "REDIS_HOST",
        "REDIS_URL",
        "AGOM_RELEASE_REHEARSAL_DATABASE",
    }
    required_provider = {"DJANGO_SETTINGS_MODULE"}
    missing = tuple(
        sorted(
            (required_isolated - isolated_values.keys())
            | (required_provider - provider_values.keys())
        )
    )
    missing_runtime_dependencies = _missing_release_runner_dependencies()
    frozen_settings = run_dir / "inputs" / "provider-settings.json"
    frozen_unit = run_dir / "inputs" / "provider-unit-contract.json"
    files = (
        config.root,
        run_dir,
        config.password_file,
        config.provider_env_file,
        config.isolated_postgres_env_file,
        provider_path,
        frozen_settings,
        frozen_unit,
        *config.transport_input_paths,
    )
    text_files = (
        config.provider_env_file,
        config.isolated_postgres_env_file,
        provider_path,
        frozen_settings,
        frozen_unit,
        *config.transport_input_paths,
    )
    started_at = datetime.now(UTC)
    dynamic_issues = _dynamic_stage_environment_issues(
        config, runner, identity, identity_path, manifest_path, provider_path, run_dir
    )
    report = evaluate_stage_environment(
        StageEnvironmentInputs(
            stages=STAGES,
            filesystem_paths=files,
            text_transport_paths=text_files,
            missing_identity_keys=missing,
            free_disk_bytes=shutil.disk_usage(run_dir).free,
            available_memory_bytes=_available_memory_bytes(),
            observed_at=datetime.now(UTC),
            build_timeout_seconds=config.build_timeout_seconds,
            stage_timeout_seconds=config.stage_timeout_seconds,
            provider_timeout_seconds=config.provider_probe_timeout_seconds,
            task_deadline_seconds=config.task_deadline_seconds,
            lock_wait_limit_seconds=config.lock_wait_limit_seconds,
            missing_runtime_dependencies=missing_runtime_dependencies,
            dynamic_issues=dynamic_issues,
        )
    )
    report_path = run_dir / "stage-environment-preflight" / "stage-environment-preflight.json"
    if report.get("outcome") == "pass":
        prebuild_path = report_path.parent / "prebuild-stage-environment-preflight.json"
        evidence = {
            **report,
            "kind": "stage_environment_preflight",
            "outcome": "success",
            "candidate_sha": identity.candidate_sha,
            "candidate_image_id": identity.candidate_image_id,
            "candidate_source_attestation": "image_release_manifest",
            "target_trade_date": identity.target_trade_date,
            "universe_sha256": identity.universe_sha256,
            "provider_identities_sha256": identity.provider_identities_sha256,
            "evidence_mode": "read_only_environment_contract",
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "prebuild_report": {
                "path": prebuild_path.name,
                "sha256": hashlib.sha256(prebuild_path.read_bytes()).hexdigest(),
            },
        }
        atomic_json(report_path, evidence)
    else:
        atomic_json(report_path, report)
    if report.get("outcome") != "pass":
        raise RehearsalBlocked(
            "stage_environment_preflight", "REHEARSAL_STAGE_ENVIRONMENT_PREFLIGHT_FAILED"
        )


def _preflight_database(
    config: RehearsalConfig,
    runner: CommandRunner,
    identity: Identity,
    identity_path: Path,
    manifest_path: Path,
    provider_path: Path,
    run_dir: Path,
) -> None:
    """Check exact disposable DB identity and migrations before any provider dispatch."""
    code = (
        "from pathlib import Path\n"
        "from django.conf import settings\n"
        "from django.core.management.base import CommandError\n"
        "from core.exceptions import AgomTradeProException\n"
        "from apps.data_center.infrastructure.isolated_write_rehearsal_runner import preflight_isolated_write_rehearsal\n"
        "try:\n"
        " preflight_isolated_write_rehearsal("
        f"candidate_sha={identity.candidate_sha!r}, source_root=Path(settings.BASE_DIR), "
        f"expected_database_name={config.isolated_database_name!r}, "
        f"expected_database_host={config.isolated_database_host!r}, require_ephemeral_host=True)\n"
        "except AgomTradeProException as exc:\n"
        " raise CommandError(exc.code) from None\n"
    )
    preflight_dir = run_dir / "preflight"
    preflight_dir.mkdir(exist_ok=True)
    spec = StageSpec(
        "preflight_database",
        "",
        ("python", "manage.py", "shell", "-c", code),
        (config.provider_env_file, config.isolated_postgres_env_file),
    )
    _invoke(
        runner,
        argv=_docker_command(
            identity,
            config.docker_network,
            spec.env_files,
            identity_path,
            manifest_path,
            provider_path,
            preflight_dir,
            spec,
        ),
        root=config.root,
        label=spec.name,
        timeout=min(config.stage_timeout_seconds, 120),
    )


def _run_parallel_stage_member(
    runner: CommandRunner,
    *,
    config: RehearsalConfig,
    identity: Identity,
    spec: StageSpec,
    folder: Path,
    identity_path: Path,
    manifest_path: Path,
    provider_path: Path,
    container_gid: int,
    checkpoint: _Checkpoint,
) -> None:
    """Execute one independent container stage and validate its report.

    Checkpoint completion is deferred to the caller so journal records always
    remain an ordered prefix of the fixed stage order.
    """
    if not checkpoint.done(spec.name):
        checkpoint.prepare(spec.name, (folder,), resume=config.resume)
        folder.mkdir(exist_ok=True)
        argv = _docker_command(
            identity,
            config.docker_network,
            spec.env_files,
            identity_path,
            manifest_path,
            provider_path,
            folder,
            spec,
        )
        _invoke_container_stage(
            runner,
            argv=argv,
            root=config.root,
            label=spec.name,
            timeout=config.stage_timeout_seconds,
            env={
                "AGOM_CANDIDATE_IMAGE_ID": identity.candidate_image_id,
                "AGOM_RELEASE_MANIFEST_PATH": str(manifest_path),
            },
            artifact_dir=folder,
            container_gid=container_gid,
        )
    _report(folder / spec.report_name, identity, image_bound=True)


def _run_parallel_container_group(
    runner: CommandRunner,
    *,
    config: RehearsalConfig,
    identity: Identity,
    specs: Sequence[StageSpec],
    folders: Sequence[Path],
    identity_path: Path,
    manifest_path: Path,
    provider_path: Path,
    container_gid: int,
    checkpoint: _Checkpoint,
) -> dict[str, Exception | None]:
    """Run the independent container stages concurrently and collect per-stage outcomes.

    Every member runs to completion unless the operator interrupts the run; a
    stage failure never cancels its siblings. The
    returned mapping is keyed by stage name so the caller can complete checkpoint
    records as an ordered prefix of the fixed stage order and re-raise the first
    failure with its original stage and error code.
    """
    outcomes: dict[str, Exception | None] = {}
    pool = ThreadPoolExecutor(max_workers=min(4, len(specs)))
    futures: dict[Future[None], str] = {}
    try:
        futures = {
            pool.submit(
                _run_parallel_stage_member,
                runner,
                config=config,
                identity=identity,
                spec=spec,
                folder=folder,
                identity_path=identity_path,
                manifest_path=manifest_path,
                provider_path=provider_path,
                container_gid=container_gid,
                checkpoint=checkpoint,
            ): spec.name
            for spec, folder in zip(specs, folders, strict=True)
        }
        for future, name in futures.items():
            try:
                future.result()
            except Exception as exc:
                outcomes[name] = exc
            else:
                outcomes[name] = None
    except KeyboardInterrupt:
        if isinstance(runner, CancellableCommandRunner):
            runner.cancel()
        for future in futures:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)
    return outcomes


def run_release_rehearsal(config: RehearsalConfig, *, runner: CommandRunner | None = None) -> Path:
    """Run or resume a locked same-candidate rehearsal without weakening final validation."""
    try:
        inputs = _validate_inputs(config)
        if config.output_dir.is_symlink():
            raise ValueError("S6_CHECKPOINT_INVALID")
        if config.output_dir.exists() and not config.resume:
            raise RehearsalBlocked("inputs", "S6_OUTPUT_DIRECTORY_EXISTS")
        if config.resume and not config.output_dir.is_dir():
            raise ValueError("S6_CHECKPOINT_MISSING")
        active = runner or SubprocessRunner(config.output_dir / "diagnostics")
        candidate = _candidate_sha(active if runner else SubprocessRunner(), config.root)
        config.output_dir.mkdir(parents=True, exist_ok=config.resume)
        with run_lock(config.output_dir):
            checkpoint = Checkpoint(
                config.output_dir.resolve(),
                _checkpoint_binding(config, candidate, inputs),
                resume=config.resume,
                max_age_hours=config.max_age_hours,
                stage_order=("build_artifacts", "build_only", "docker_identity", *STAGES[:-1]),
            )
            if (config.output_dir / "s6-handoff-receipt.json").exists():
                raise RehearsalBlocked("handoff", "S6_RUN_ALREADY_COMPLETE")
            _freeze_provider_settings_snapshot(config.output_dir.resolve(), inputs)
            try:
                _status(
                    config.output_dir / "run-status.json",
                    "running",
                    tuple(checkpoint.records),
                    "preflight",
                    None,
                )
                _run_prebuild_stage_environment_preflight(config)
                _preflight_environment(config, active)
            except RehearsalBlocked as exc:
                _status(
                    config.output_dir / "run-status.json",
                    "blocked",
                    tuple(checkpoint.records),
                    exc.stage,
                    exc.code,
                )
                raise
            except KeyboardInterrupt:
                if isinstance(active, CancellableCommandRunner):
                    active.cancel()
                _status(
                    config.output_dir / "run-status.json",
                    "interrupted",
                    tuple(checkpoint.records),
                    "preflight",
                    "S6_RUN_INTERRUPTED",
                )
                raise
            return _run_release_rehearsal(config, checkpoint, inputs, runner=active)
    except ValueError as exc:
        code = str(exc)
        if not re.fullmatch(r"S6_(?:CHECKPOINT|RUN)_[A-Z_]+", code):
            code = "S6_INPUT_OR_ARTIFACT_INVALID"
        raise RehearsalBlocked("inputs", code) from exc
    except OSError as exc:
        raise RehearsalBlocked("inputs", "S6_INPUT_OR_ARTIFACT_INVALID") from exc


def _run_release_rehearsal(
    config: RehearsalConfig,
    checkpoint: _Checkpoint,
    inputs: RehearsalInputs,
    *,
    runner: CommandRunner,
) -> Path:
    """Execute S6 in fixed order and emit a non-authorizing evidence handoff receipt."""
    active = runner or SubprocessRunner()
    completed: list[str] = []
    stage: str | None = "inputs"
    run_dir: Path | None = None
    status_path: Path | None = None
    try:
        target_date = inputs.target_date
        identities = inputs.provider_identities
        provider_digest = inputs.provider_identities_sha256
        provider_raw = inputs.provider_identities_raw
        unit_raw = inputs.unit_contract_raw
        candidate = _candidate_sha(active, config.root)
        unit = _object(json.loads(unit_raw), "S6_UNIT_CONTRACT_INVALID")
        if unit.get("candidate_sha") != candidate:
            raise RehearsalBlocked("inputs", "S6_UNIT_CONTRACT_CANDIDATE_MISMATCH")
        run_dir = config.output_dir.resolve()
        status_path = run_dir / "run-status.json"
        _status(status_path, "running", completed, "build_only", None)
        _assert_candidate(active, config.root, candidate)

        stage = "build_only"
        build_report, _archive = _build_image(config, active, run_dir, candidate, checkpoint)
        checkpoint.complete("build_only", ())
        completed.append(stage)
        stage = "docker_identity"
        checkpoint.prepare("docker_identity", (run_dir / "inputs",), resume=config.resume)
        _freeze_provider_settings_snapshot(run_dir, inputs)
        identity, identity_path, manifest_path, provider_path = _write_identity(
            run_dir,
            build_report,
            candidate,
            target_date,
            config.universe_sha256,
            provider_digest,
            identities,
            provider_raw,
            inputs.provider_settings_raw_file_sha256,
            inputs.provider_settings_canonical_payload_sha256,
            unit_raw,
            reuse=checkpoint.done("docker_identity"),
        )
        frozen_provider_env = _freeze_private_input(
            run_dir / "inputs" / "provider.env", inputs.provider_env_raw
        )
        frozen_isolated_env = _freeze_private_input(
            run_dir / "inputs" / "isolated.env", inputs.isolated_env_raw
        )
        config = replace(
            config,
            provider_env_file=frozen_provider_env,
            isolated_postgres_env_file=frozen_isolated_env,
        )
        checkpoint.complete("docker_identity", (run_dir / "inputs",))
        container_gid = _candidate_container_gid(active, config.root, identity.candidate_image_id)
        unit_path = run_dir / "inputs" / "provider-unit-contract.json"
        provider_dir, replay_dir, capacity_dir, parity_dir, isolated_dir, ci_dir, financial_dir = (
            run_dir / name
            for name in (
                "provider-probe",
                "response-replay",
                "full-universe-capacity",
                "production-policy-parity",
                "isolated-postgresql",
                "github-ci-evidence",
                "akshare-financial-slice",
            )
        )
        completed.append(stage)
        stage = "stage_environment_preflight"
        _status(status_path, "running", completed, stage, None)
        _assert_candidate(active, config.root, candidate)
        _run_stage_environment_preflight(
            config,
            active,
            identity,
            identity_path,
            manifest_path,
            provider_path,
            run_dir,
        )
        isolated_database_container_id = _preflight_isolated_database_container(config, active)
        _preflight_database(
            config, active, identity, identity_path, manifest_path, provider_path, run_dir
        )

        path_values: dict[str, Path] = {
            "provider_dir": provider_dir,
            "unit_path": unit_path,
            "provider_settings_path": run_dir / "inputs" / "provider-settings.json",
            "ci_dir": ci_dir,
            "probe_sha": Path(hashlib.sha256(b"").hexdigest()),
            "unit_sha": Path(hashlib.sha256(unit_raw).hexdigest()),
        }
        for spec in _stage_specs(config, identity, path_values)[:1]:
            stage = spec.name
            _status(status_path, "running", completed, stage, None)
            _assert_candidate(active, config.root, candidate)
            if not checkpoint.done(stage):
                checkpoint.prepare(stage, (provider_dir,), resume=config.resume)
                provider_dir.mkdir(exist_ok=True)
                argv = _docker_command(
                    identity,
                    config.docker_network,
                    spec.env_files,
                    identity_path,
                    manifest_path,
                    provider_path,
                    provider_dir,
                    spec,
                )
                _invoke_container_stage(
                    active,
                    argv=argv,
                    root=config.root,
                    label=stage,
                    timeout=config.stage_timeout_seconds,
                    env={
                        "AGOM_CANDIDATE_IMAGE_ID": identity.candidate_image_id,
                        "AGOM_RELEASE_MANIFEST_PATH": str(manifest_path),
                    },
                    artifact_dir=provider_dir,
                    container_gid=container_gid,
                )
            probe_path = provider_dir / spec.report_name
            probe = _report(probe_path, identity, image_bound=True)
            if probe.get("response_retention_enabled") is not True:
                raise RehearsalBlocked(stage, "S6_PROVIDER_RESPONSES_NOT_RETAINED")
            path_values["probe_sha"] = Path(hashlib.sha256(_read_file(probe_path)).hexdigest())
            checkpoint.complete(stage, (provider_dir,))
            completed.append(stage)

        specs = _stage_specs(config, identity, path_values)
        evidence_specs = specs[1:5]
        financial_spec = specs[5]
        evidence_folders = (replay_dir, capacity_dir, parity_dir, isolated_dir)
        pending = [spec.name for spec in evidence_specs if not checkpoint.done(spec.name)]
        stage = pending[0] if pending else evidence_specs[0].name
        _status(status_path, "running", completed, stage, None)
        _assert_candidate(active, config.root, candidate)
        if _preflight_isolated_database_container(config, active) != isolated_database_container_id:
            raise RehearsalBlocked(
                "isolated_postgresql_write", "S6_ISOLATED_DATABASE_CONTAINER_CHANGED"
            )
        stage_pairs = tuple(zip(evidence_specs, evidence_folders, strict=True))
        capacity_spec, capacity_folder = next(
            pair for pair in stage_pairs if pair[0].name == "full_universe_capacity"
        )
        try:
            _run_parallel_stage_member(
                active,
                config=config,
                identity=identity,
                spec=capacity_spec,
                folder=capacity_folder,
                identity_path=identity_path,
                manifest_path=manifest_path,
                provider_path=provider_path,
                container_gid=container_gid,
                checkpoint=checkpoint,
            )
        except Exception as exc:
            capacity_failure: Exception | None = exc
        else:
            capacity_failure = None

        concurrent_pairs = tuple(
            pair for pair in stage_pairs if pair[0].name != "full_universe_capacity"
        )
        outcomes = _run_parallel_container_group(
            active,
            config=config,
            identity=identity,
            specs=tuple(pair[0] for pair in concurrent_pairs),
            folders=tuple(pair[1] for pair in concurrent_pairs),
            identity_path=identity_path,
            manifest_path=manifest_path,
            provider_path=provider_path,
            container_gid=container_gid,
            checkpoint=checkpoint,
        )
        outcomes[capacity_spec.name] = capacity_failure
        _assert_candidate(active, config.root, candidate)
        for spec, folder in stage_pairs:
            stage = spec.name
            failure = outcomes[spec.name]
            if failure is not None:
                raise failure
            checkpoint.complete(spec.name, (folder,))
            completed.append(spec.name)

        stage = "github_ci_evidence"
        _status(status_path, "running", completed, stage, None)
        _assert_candidate(active, config.root, candidate)
        ci_path = ci_dir / "candidate-regression-evidence.json"
        ci_argv = (
            sys.executable,
            str(config.root / "scripts" / "collect_release_regression_evidence.py"),
            "--candidate-sha",
            candidate,
            "--target-date",
            target_date.isoformat(),
            "--universe-sha256",
            identity.universe_sha256,
            "--provider-identities-json",
            str(provider_path),
            "--github-repository",
            config.github_repository,
            "--github-run-id",
            str(config.github_run_id),
            "--max-age-hours",
            str(config.max_age_hours),
            "--output-dir",
            str(ci_dir),
        )
        if not checkpoint.done(stage):
            checkpoint.prepare(stage, (ci_dir,), resume=config.resume)
            _invoke(
                active,
                argv=ci_argv,
                root=config.root,
                label=stage,
                timeout=config.stage_timeout_seconds,
                env={
                    "AGOM_CANDIDATE_IMAGE_ID": identity.candidate_image_id,
                    "AGOM_RELEASE_MANIFEST_PATH": str(manifest_path),
                },
                artifact_dir=ci_dir,
            )
        _report(ci_path, identity, image_bound=False)
        _checkpoint_module.seal_container_input_tree(ci_dir, container_gid, RehearsalBlocked)
        checkpoint.complete(stage, (ci_dir,))
        completed.append(stage)

        stage = financial_spec.name
        _status(status_path, "running", completed, stage, None)
        _assert_candidate(active, config.root, candidate)
        _checkpoint_module.verify_container_input_tree(ci_dir, container_gid, RehearsalBlocked)
        if not checkpoint.done(stage):
            checkpoint.prepare(stage, (financial_dir,), resume=config.resume)
            financial_dir.mkdir(exist_ok=True)
            financial_argv = _docker_command(
                identity,
                config.docker_network,
                financial_spec.env_files,
                identity_path,
                manifest_path,
                provider_path,
                financial_dir,
                financial_spec,
            )
            _invoke_container_stage(
                active,
                argv=financial_argv,
                root=config.root,
                label=stage,
                timeout=config.stage_timeout_seconds,
                env={
                    "AGOM_CANDIDATE_IMAGE_ID": identity.candidate_image_id,
                    "AGOM_RELEASE_MANIFEST_PATH": str(manifest_path),
                },
                artifact_dir=financial_dir,
                container_gid=container_gid,
            )
        financial_report_path = financial_dir / financial_spec.report_name
        financial_report = _report(financial_report_path, identity, image_bound=True)
        if financial_report.get("kind") != "akshare_financial_slice":
            raise RehearsalBlocked(stage, "S6_FINANCIAL_SLICE_REPORT_INVALID")
        checkpoint.complete(stage, (financial_dir,))
        completed.append(stage)

        stage = "bundle_build"
        _status(status_path, "running", completed, stage, None)
        _assert_candidate(active, config.root, candidate)
        bundle_dir = run_dir / "bundle"
        bundle_argv = (
            sys.executable,
            str(config.root / "scripts" / "build_release_rehearsal_manifest.py"),
            "--real-response-unit-replay",
            str(replay_dir / "output" / "real-response-unit-replay.json"),
            "--full-universe-capacity",
            str(capacity_dir / "output" / "full-universe-capacity.json"),
            "--production-policy-parity",
            str(parity_dir / "output" / "production-policy-parity.json"),
            "--isolated-write-rehearsal",
            str(isolated_dir / "output" / "isolated-write-rehearsal.json"),
            "--akshare-financial-slice",
            str(financial_report_path),
            "--stage-environment-preflight",
            str(run_dir / "stage-environment-preflight" / "stage-environment-preflight.json"),
            "--candidate-regression-evidence",
            str(ci_path),
            "--output-dir",
            str(bundle_dir),
            "--candidate-sha",
            candidate,
            "--target-trade-date",
            target_date.isoformat(),
            "--universe-sha256",
            identity.universe_sha256,
            "--provider-identities-sha256",
            provider_digest,
            "--provider-settings-raw-file-sha256",
            identity.provider_settings_raw_file_sha256,
            "--provider-settings-canonical-payload-sha256",
            identity.provider_settings_canonical_payload_sha256,
            "--candidate-image-id",
            identity.candidate_image_id,
        )
        if not checkpoint.done(stage):
            checkpoint.prepare(stage, (bundle_dir,), resume=config.resume)
            _invoke(
                active,
                argv=bundle_argv,
                root=config.root,
                label=stage,
                timeout=120,
                env={
                    "AGOM_CANDIDATE_IMAGE_ID": identity.candidate_image_id,
                    "AGOM_RELEASE_MANIFEST_PATH": str(manifest_path),
                },
                artifact_dir=bundle_dir,
            )
        final_manifest = bundle_dir / "release-rehearsal-manifest.json"
        manifest_payload = _object(json.loads(_read_file(final_manifest)), "S6_MANIFEST_INVALID")
        for key, expected in (
            ("candidate_sha", candidate),
            ("candidate_image_id", identity.candidate_image_id),
            ("target_trade_date", target_date.isoformat()),
            ("universe_sha256", identity.universe_sha256),
            ("provider_identities_sha256", provider_digest),
            (
                "provider_settings_raw_file_sha256",
                identity.provider_settings_raw_file_sha256,
            ),
            (
                "provider_settings_canonical_payload_sha256",
                identity.provider_settings_canonical_payload_sha256,
            ),
        ):
            if manifest_payload.get(key) != expected:
                raise RehearsalBlocked(stage, "S6_MANIFEST_IDENTITY_MISMATCH")
        _freeze_bundle(bundle_dir)
        frozen_digest = bundle_tree_digest(bundle_dir)
        checkpoint.complete(stage, (bundle_dir,))
        completed.append(stage)

        stage = "release_validator"
        _status(status_path, "running", completed, stage, None)
        _assert_candidate(active, config.root, candidate)
        validator_argv = (
            sys.executable,
            str(config.root / "scripts" / "validate_release_rehearsal.py"),
            "--manifest",
            str(final_manifest),
            "--expected-candidate",
            candidate,
            "--expected-target-date",
            target_date.isoformat(),
            "--expected-universe-sha256",
            identity.universe_sha256,
            "--expected-provider-identities-sha256",
            provider_digest,
            "--expected-provider-settings-raw-file-sha256",
            identity.provider_settings_raw_file_sha256,
            "--expected-provider-settings-canonical-payload-sha256",
            identity.provider_settings_canonical_payload_sha256,
            "--expected-candidate-image-id",
            identity.candidate_image_id,
            "--expected-github-repository",
            config.github_repository,
            "--expected-github-run-id",
            str(config.github_run_id),
            "--max-age-hours",
            str(config.max_age_hours),
        )
        _invoke(
            active,
            argv=validator_argv,
            root=config.root,
            label=stage,
            timeout=config.stage_timeout_seconds,
            env={
                "AGOM_CANDIDATE_IMAGE_ID": identity.candidate_image_id,
                "AGOM_RELEASE_MANIFEST_PATH": str(manifest_path),
            },
            artifact_dir=bundle_dir,
        )
        if bundle_tree_digest(bundle_dir) != frozen_digest:
            raise RehearsalBlocked(stage, "S6_BUNDLE_CHANGED_AFTER_VALIDATION")
        receipt_path = run_dir / "s6-handoff-receipt.json"
        _write_json(
            receipt_path,
            {
                "schema": "release.rehearsal-evidence-handoff.v1",
                "issuer": "release_rehearsal_launcher",
                "receipt_status": "evidence_complete",
                "deployable": False,
                "evidence_completed_at": datetime.now(UTC).isoformat(),
                "validator": str(config.root / "scripts" / "validate_release_rehearsal.py"),
                "validator_exit_code": 0,
                **asdict(identity),
                "github_repository": config.github_repository,
                "github_run_id": config.github_run_id,
                "max_age_hours": config.max_age_hours,
                "bundle_dir": str(bundle_dir.resolve()),
                "bundle_tree_sha256": frozen_digest,
                "manifest_sha256": hashlib.sha256(_read_file(final_manifest)).hexdigest(),
            },
            read_only=True,
        )
        completed.append(stage)
        _status(status_path, "success_evidence", completed, None, None)
        return receipt_path
    except RehearsalBlocked as exc:
        if status_path is not None:
            _status(status_path, "blocked", completed, exc.stage, exc.code)
        raise
    except KeyboardInterrupt:
        if isinstance(active, CancellableCommandRunner):
            active.cancel()
        if status_path is not None:
            _status(status_path, "interrupted", completed, stage, "S6_RUN_INTERRUPTED")
        raise
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        if status_path is not None:
            _status(status_path, "blocked", completed, stage, "S6_INPUT_OR_ARTIFACT_INVALID")
        raise RehearsalBlocked(stage or "unknown", "S6_INPUT_OR_ARTIFACT_INVALID") from exc


def verify_evidence_handoff_receipt(receipt_path: Path) -> dict[str, object]:
    """Recheck the launcher handoff; this receipt never grants deploy permission."""
    try:
        receipt = _object(json.loads(_read_file(receipt_path)), "S6_RECEIPT_INVALID")
        bundle = Path(cast(str, receipt["bundle_dir"]))
        manifest = bundle / "release-rehearsal-manifest.json"
        completed_at = datetime.fromisoformat(cast(str, receipt["evidence_completed_at"]))
        valid = (
            receipt.get("schema") == "release.rehearsal-evidence-handoff.v1"
            and receipt.get("issuer") == "release_rehearsal_launcher"
            and receipt.get("receipt_status") == "evidence_complete"
            and receipt.get("deployable") is False
            and completed_at.utcoffset() is not None
            and receipt.get("bundle_tree_sha256") == bundle_tree_digest(bundle)
            and receipt.get("manifest_sha256") == hashlib.sha256(_read_file(manifest)).hexdigest()
        )
        manifest_payload = _object(json.loads(_read_file(manifest)), "S6_MANIFEST_INVALID")
        for key in (
            "provider_settings_raw_file_sha256",
            "provider_settings_canonical_payload_sha256",
        ):
            digest = receipt.get(key)
            if (
                not isinstance(digest, str)
                or SHA.fullmatch(digest) is None
                or manifest_payload.get(key) != digest
            ):
                valid = False
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise RehearsalBlocked("handoff", "S6_RECEIPT_INVALID") from exc
    if not valid:
        raise RehearsalBlocked("handoff", "S6_HANDOFF_RECEIPT_MISMATCH")
    return receipt


def _parser() -> argparse.ArgumentParser:
    """Parse the existing stage inputs for one candidate rehearsal."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a verified same-candidate checkpoint in --output-dir",
    )
    parser.add_argument("--build-host", required=True)
    parser.add_argument("--build-user", default="root")
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--provider-env-file", type=Path, required=True)
    parser.add_argument("--isolated-postgres-env-file", type=Path, required=True)
    parser.add_argument("--docker-network", required=True)
    parser.add_argument("--isolated-database-name", required=True)
    parser.add_argument("--isolated-database-host", required=True)
    parser.add_argument("--isolated-database-container", required=True)
    parser.add_argument("--isolated-redis-host", required=True)
    parser.add_argument("--isolated-redis-container", required=True)
    parser.add_argument("--target-trade-date", required=True)
    parser.add_argument("--universe-sha256", required=True)
    parser.add_argument("--provider-identities", type=Path, required=True)
    parser.add_argument("--provider-settings-json", type=Path, required=True)
    parser.add_argument("--unit-contract", type=Path, required=True)
    parser.add_argument(
        "--transport-input",
        type=Path,
        action="append",
        required=True,
        help="Repeat for every script/config transferred through SSH or a pipe before S6.",
    )
    parser.add_argument("--quote-provider-id", type=int, required=True)
    parser.add_argument("--valuation-provider-id", type=int, required=True)
    parser.add_argument("--provider-request-limit", type=int, required=True)
    parser.add_argument("--provider-window-seconds", type=float, required=True)
    parser.add_argument("--task-deadline-seconds", type=float, required=True)
    parser.add_argument("--lock-wait-limit-seconds", type=float, required=True)
    parser.add_argument("--github-repository", required=True)
    parser.add_argument("--github-run-id", type=int, required=True)
    parser.add_argument("--max-age-hours", type=float, default=24.0)
    parser.add_argument("--build-timeout-seconds", type=int, default=3600)
    parser.add_argument("--stage-timeout-seconds", type=int, default=3600)
    parser.add_argument("--provider-probe-timeout-seconds", type=int, default=1800)
    parser.add_argument("--max-dispatches", type=int, default=100)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run S6 and print the non-authorizing evidence handoff location."""
    args = _parser().parse_args(argv)
    config = RehearsalConfig(
        root=args.root.resolve(),
        output_dir=args.output_dir.resolve(),
        build_host=args.build_host,
        build_user=args.build_user,
        password_file=args.password_file.resolve(),
        provider_env_file=args.provider_env_file.resolve(),
        isolated_postgres_env_file=args.isolated_postgres_env_file.resolve(),
        docker_network=args.docker_network,
        isolated_database_name=args.isolated_database_name,
        isolated_database_host=args.isolated_database_host,
        isolated_database_container=args.isolated_database_container,
        isolated_redis_host=args.isolated_redis_host,
        isolated_redis_container=args.isolated_redis_container,
        target_trade_date=args.target_trade_date,
        universe_sha256=args.universe_sha256,
        provider_identities_path=args.provider_identities.resolve(),
        provider_settings_json=args.provider_settings_json.resolve(),
        unit_contract_path=args.unit_contract.resolve(),
        transport_input_paths=tuple(path.resolve() for path in args.transport_input),
        quote_provider_id=args.quote_provider_id,
        valuation_provider_id=args.valuation_provider_id,
        provider_request_limit=args.provider_request_limit,
        provider_window_seconds=args.provider_window_seconds,
        task_deadline_seconds=args.task_deadline_seconds,
        lock_wait_limit_seconds=args.lock_wait_limit_seconds,
        github_repository=args.github_repository,
        github_run_id=args.github_run_id,
        max_age_hours=args.max_age_hours,
        build_timeout_seconds=args.build_timeout_seconds,
        stage_timeout_seconds=args.stage_timeout_seconds,
        provider_probe_timeout_seconds=args.provider_probe_timeout_seconds,
        max_dispatches=args.max_dispatches,
        resume=args.resume,
    )
    try:
        _assert_launcher_provenance(config.root)
        receipt = run_release_rehearsal(config)
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    "outcome": "interrupted",
                    "error_code": "S6_RUN_INTERRUPTED",
                    "deployable": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 130
    except RehearsalBlocked as exc:
        print(
            json.dumps(
                {
                    "outcome": "blocked",
                    "stage": exc.stage,
                    "error_code": exc.code,
                    "deployable": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "outcome": "success_evidence",
                "receipt_status": "evidence_complete",
                "deployable": False,
                "receipt": str(receipt),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
