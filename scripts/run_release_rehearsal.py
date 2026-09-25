#!/usr/bin/env python3
"""Run the ordered, non-deploying S6 release rehearsal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.data_center.infrastructure.rehearsal_identity import (
    RehearsalProviderIdentity,
    parse_rehearsal_identities,
    rehearsal_identities_digest,
)

SHA = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
TAG = re.compile(r"[0-9]{14}")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
IMAGE_NAME = "agomtradepro-web"
STAGES = (
    "provider_probe",
    "response_replay",
    "full_universe_capacity",
    "isolated_postgresql_write",
    "github_ci_evidence",
    "bundle_build",
    "release_validator",
)


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


class _Chown(Protocol):
    """Portable callable shape for POSIX ownership changes."""

    def __call__(self, path: str | bytes | os.PathLike[str], uid: int, gid: int) -> None:
        """Change one filesystem entry's owner/group."""


class SubprocessRunner:
    """Production runner that captures output and never invokes a shell."""

    def run(self, command: Command) -> CommandResult:
        """Run one command and convert launch errors to a failed result."""
        environment = os.environ.copy()
        environment.update(command.env)
        try:
            result = subprocess.run(
                command.argv,
                cwd=command.cwd,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=command.timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return CommandResult(127, stderr=type(exc).__name__)
        return CommandResult(result.returncode, result.stdout, result.stderr)


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
    target_trade_date: str
    universe_sha256: str
    provider_identities_path: Path
    unit_contract_path: Path
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
    stage_timeout_seconds: int = 1800
    max_dispatches: int = 100


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


@dataclass(frozen=True)
class StageSpec:
    """One fixed stage in the release rehearsal sequence."""

    name: str
    report_name: str
    argv: tuple[str, ...]
    env_file: Path
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
    """Run one stage and stop on nonzero status without exposing stderr."""
    result = runner.run(Command(tuple(argv), root, env or {}, timeout, label, artifact_dir))
    if result.returncode:
        raise RehearsalBlocked(label, "S6_STAGE_COMMAND_FAILED")
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
    initial = artifact_dir.stat()
    identity = (initial.st_dev, initial.st_ino)
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
    try:
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
        current = artifact_dir.lstat()
        if artifact_dir.is_symlink() or (current.st_dev, current.st_ino) != identity:
            raise RehearsalBlocked(label, "S6_ARTIFACT_DIRECTORY_CHANGED")
        artifact_dir.chmod(0o750)


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


def _assert_candidate(runner: CommandRunner, root: Path, expected: str) -> None:
    """Ensure the frozen checkout is unchanged before each evidence stage."""
    if _candidate_sha(runner, root) != expected:
        raise RehearsalBlocked("candidate", "S6_CANDIDATE_CHANGED")


def _validate_inputs(
    config: RehearsalConfig,
) -> tuple[date, tuple[RehearsalProviderIdentity, ...], str, bytes, bytes]:
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
        or config.quote_provider_id <= 0
        or config.valuation_provider_id <= 0
        or config.github_run_id <= 0
        or config.provider_request_limit <= 0
        or config.provider_window_seconds <= 0
        or config.task_deadline_seconds <= 0
        or config.lock_wait_limit_seconds <= 0
        or config.build_timeout_seconds <= 0
        or config.stage_timeout_seconds <= 0
        or config.max_dispatches <= 0
        or not 0 < config.max_age_hours <= 168
    ):
        raise ValueError("S6_INPUT_INVALID")
    for path in (
        config.password_file,
        config.provider_env_file,
        config.isolated_postgres_env_file,
    ):
        _read_file(path)
    provider_raw = _read_file(config.provider_identities_path, 16_384)
    try:
        identities = parse_rehearsal_identities(json.loads(provider_raw))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("S6_PROVIDER_IDENTITY_INVALID") from exc
    by_role = {item.role: item.provider_id for item in identities}
    if by_role != {"quote": config.quote_provider_id, "valuation": config.valuation_provider_id}:
        raise ValueError("S6_PROVIDER_IDENTITY_MISMATCH")
    provider_digest = rehearsal_identities_digest(identities)
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
    return target_date, identities, provider_digest, provider_raw, unit_raw


def _build_image(
    config: RehearsalConfig, runner: CommandRunner, run_dir: Path, candidate_sha: str
) -> tuple[dict[str, object], Path]:
    """Build once in build-only mode, retain the image tar and inspect the loaded image."""
    report_dir, image_dir = run_dir / "build-report", run_dir / "images"
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
    unit_raw: bytes,
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
    )
    input_dir = run_dir / "inputs"
    input_dir.mkdir()
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
    env_file: Path,
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
        "--network",
        network,
        "--env-file",
        str(env_file.resolve()),
        "--env",
        f"AGOM_CANDIDATE_IMAGE_ID={identity.candidate_image_id}",
        "--env",
        "AGOM_RELEASE_MANIFEST_PATH=/run/agom/candidate-release-manifest.json",
    ]
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
        str(config.stage_timeout_seconds),
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
        "--output-dir",
        "/run/agom/stage/output",
    )
    return (
        StageSpec(
            "provider_probe",
            "probe.json",
            provider,
            config.provider_env_file,
            retain_responses=True,
        ),
        StageSpec(
            "response_replay",
            "output/real-response-unit-replay.json",
            replay,
            config.provider_env_file,
            mounts=(
                (cast(Path, paths["provider_dir"]), "/run/agom/provider-probe", True),
                (cast(Path, paths["unit_path"]), "/run/agom/unit-contract.json", True),
            ),
        ),
        StageSpec(
            "full_universe_capacity",
            "output/full-universe-capacity.json",
            capacity,
            config.provider_env_file,
        ),
        StageSpec(
            "isolated_postgresql_write",
            "output/isolated-write-rehearsal.json",
            isolated,
            config.isolated_postgres_env_file,
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
    temporary = path.with_suffix(".tmp")
    _write = {
        "schema": "release.rehearsal-launch-status.v1",
        "outcome": outcome,
        "completed_stages": list(completed),
        "current_stage": stage,
        "error_code": code,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    temporary.write_text(json.dumps(_write, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_release_rehearsal(config: RehearsalConfig, *, runner: CommandRunner | None = None) -> Path:
    """Execute S6 in fixed order and emit a non-authorizing evidence handoff receipt."""
    active = runner or SubprocessRunner()
    completed: list[str] = []
    stage: str | None = "inputs"
    run_dir: Path | None = None
    status_path: Path | None = None
    try:
        target_date, identities, provider_digest, provider_raw, unit_raw = _validate_inputs(config)
        candidate = _candidate_sha(active, config.root)
        unit = _object(json.loads(unit_raw), "S6_UNIT_CONTRACT_INVALID")
        if unit.get("candidate_sha") != candidate:
            raise RehearsalBlocked("inputs", "S6_UNIT_CONTRACT_CANDIDATE_MISMATCH")
        if config.output_dir.exists():
            raise RehearsalBlocked("inputs", "S6_OUTPUT_DIRECTORY_EXISTS")
        config.output_dir.parent.mkdir(parents=True, exist_ok=True)
        config.output_dir.mkdir()
        run_dir = config.output_dir.resolve()
        status_path = run_dir / "run-status.json"
        _status(status_path, "running", completed, "build_only", None)
        _assert_candidate(active, config.root, candidate)

        stage = "build_only"
        build_report, _archive = _build_image(config, active, run_dir, candidate)
        completed.append(stage)
        stage = "docker_identity"
        identity, identity_path, manifest_path, provider_path = _write_identity(
            run_dir,
            build_report,
            candidate,
            target_date,
            config.universe_sha256,
            provider_digest,
            identities,
            provider_raw,
            unit_raw,
        )
        container_gid = _candidate_container_gid(active, config.root, identity.candidate_image_id)
        unit_path = run_dir / "inputs" / "provider-unit-contract.json"
        provider_dir, replay_dir, capacity_dir, isolated_dir, ci_dir = (
            run_dir / name
            for name in (
                "provider-probe",
                "response-replay",
                "full-universe-capacity",
                "isolated-postgresql",
                "github-ci-evidence",
            )
        )
        for folder in (provider_dir, replay_dir, capacity_dir, isolated_dir, ci_dir):
            folder.mkdir()
        completed.append(stage)

        path_values: dict[str, Path] = {
            "provider_dir": provider_dir,
            "unit_path": unit_path,
            "probe_sha": Path(hashlib.sha256(b"").hexdigest()),
            "unit_sha": Path(hashlib.sha256(unit_raw).hexdigest()),
        }
        for spec in _stage_specs(config, identity, path_values)[:1]:
            stage = spec.name
            _status(status_path, "running", completed, stage, None)
            _assert_candidate(active, config.root, candidate)
            argv = _docker_command(
                identity,
                config.docker_network,
                spec.env_file,
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
            completed.append(stage)

        specs = _stage_specs(config, identity, path_values)
        for spec, folder in zip(specs[1:], (replay_dir, capacity_dir, isolated_dir), strict=True):
            stage = spec.name
            _status(status_path, "running", completed, stage, None)
            _assert_candidate(active, config.root, candidate)
            argv = _docker_command(
                identity,
                config.docker_network,
                spec.env_file,
                identity_path,
                manifest_path,
                provider_path,
                folder,
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
                artifact_dir=folder,
                container_gid=container_gid,
            )
            _report(folder / spec.report_name, identity, image_bound=True)
            completed.append(stage)

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
            "--isolated-write-rehearsal",
            str(isolated_dir / "output" / "isolated-write-rehearsal.json"),
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
            "--candidate-image-id",
            identity.candidate_image_id,
        )
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
        ):
            if manifest_payload.get(key) != expected:
                raise RehearsalBlocked(stage, "S6_MANIFEST_IDENTITY_MISMATCH")
        _freeze_bundle(bundle_dir)
        frozen_digest = bundle_tree_digest(bundle_dir)
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
    parser.add_argument("--build-host", required=True)
    parser.add_argument("--build-user", default="root")
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--provider-env-file", type=Path, required=True)
    parser.add_argument("--isolated-postgres-env-file", type=Path, required=True)
    parser.add_argument("--docker-network", required=True)
    parser.add_argument("--target-trade-date", required=True)
    parser.add_argument("--universe-sha256", required=True)
    parser.add_argument("--provider-identities", type=Path, required=True)
    parser.add_argument("--unit-contract", type=Path, required=True)
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
    parser.add_argument("--stage-timeout-seconds", type=int, default=1800)
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
        target_trade_date=args.target_trade_date,
        universe_sha256=args.universe_sha256,
        provider_identities_path=args.provider_identities.resolve(),
        unit_contract_path=args.unit_contract.resolve(),
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
        max_dispatches=args.max_dispatches,
    )
    try:
        receipt = run_release_rehearsal(config)
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
