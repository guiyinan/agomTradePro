"""Read-only, aggregate environment checks for every S6 evidence stage."""

from __future__ import annotations

import json
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA = "release.s6-stage-environment-preflight.v1"
DOCKER_BUILD_POLICY_SCHEMA = "release.s6-docker-build-policy.v1"
DOCKER_BUILDER_MODE = "legacy"
DOCKER_DAEMON_ENDPOINT = "unix:///var/run/docker.sock"
MINIMUM_SUPPORTED_DOCKER_VERSION = (29, 3, 2)
MAXIMUM_SUPPORTED_DOCKER_CLIENT_VERSION_EXCLUSIVE = (30, 0, 0)
KNOWN_VULNERABLE_DOCKER_SERVER_VERSIONS = ("29.3.0", "29.3.1")
_DOCKER_VERSION_PATTERN = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)")
CATEGORIES = (
    "filesystem",
    "transfer_encoding",
    "network_egress",
    "identity_and_secrets",
    "resources_and_time",
    "external_state",
)
CONTRACT_STAGES = (
    "build_only",
    "docker_identity",
    "isolated_database_migrations",
    "provider_probe",
    "response_replay",
    "full_universe_capacity",
    "production_policy_parity",
    "isolated_postgresql_write",
    "github_ci_evidence",
    "akshare_financial_slice",
    "financial_scope_capacity",
    "bundle_build",
    "release_validator",
)
ALLOWED_ISSUE_CODES = frozenset(
    {
        "REHEARSAL_STAGE_ENVIRONMENT_CONTRACT_MISSING",
        "REHEARSAL_STAGE_FILESYSTEM_ENTRY_INVALID",
        "REHEARSAL_STAGE_TRANSFER_ENCODING_INVALID",
        "REHEARSAL_STAGE_IDENTITY_OR_SECRET_CONTRACT_INVALID",
        "REHEARSAL_STAGE_RUNNER_DEPENDENCY_MISSING",
        "REHEARSAL_DOCKER_BUILDER_POLICY_INVALID",
        "REHEARSAL_STAGE_DISK_HEADROOM_INSUFFICIENT",
        "REHEARSAL_STAGE_MEMORY_HEADROOM_INSUFFICIENT",
        "REHEARSAL_STAGE_CLOCK_INVALID",
        "REHEARSAL_STAGE_TIME_BUDGET_INVALID",
        "REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_UNAVAILABLE",
        "REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_REPORT_INVALID",
        "REHEARSAL_STAGE_MODEL_MARKET_ROUTE_INVALID",
        "REHEARSAL_FINANCIAL_SLICE_EGRESS_ROUTE_REQUIRED",
        "REHEARSAL_STAGE_PROVIDER_IDENTITY_INVALID",
        "REHEARSAL_STAGE_FINANCIAL_SECRET_CONTRACT_INVALID",
        "REHEARSAL_STAGE_DATABASE_CLOCK_INVALID",
        "REHEARSAL_STAGE_FINANCIAL_BUDGET_INVALID",
        "REHEARSAL_STAGE_PERIODIC_ENTRYPOINT_INVALID",
    }
)
MINIMUM_FREE_DISK_BYTES = 12 * 1024 * 1024 * 1024
BUILD_DISK_RESERVE_BYTES = 12 * 1024 * 1024 * 1024
MINIMUM_PREBUILD_FREE_DISK_BYTES = MINIMUM_FREE_DISK_BYTES + BUILD_DISK_RESERVE_BYTES
MINIMUM_AVAILABLE_MEMORY_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class DockerBuildPolicy:
    """Governed Docker endpoint, builder selection, and supported version bounds."""

    builder_mode: str
    daemon_endpoint: str
    minimum_client_version: str
    maximum_client_version_exclusive: str
    minimum_server_version: str
    known_vulnerable_server_versions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return the stable, secret-free policy projection used in S6 evidence."""

        return {
            "builder_mode": self.builder_mode,
            "daemon_endpoint": self.daemon_endpoint,
            "minimum_client_version": self.minimum_client_version,
            "maximum_client_version_exclusive": self.maximum_client_version_exclusive,
            "minimum_server_version": self.minimum_server_version,
            "known_vulnerable_server_versions": list(self.known_vulnerable_server_versions),
        }

    def supports_client_version(self, version: str) -> bool:
        """Return whether a Docker CLI version is known to support this legacy build mode."""

        parsed = _parse_docker_version(version)
        minimum = _parse_docker_version(self.minimum_client_version)
        maximum = _parse_docker_version(self.maximum_client_version_exclusive)
        return (
            parsed is not None
            and minimum is not None
            and maximum is not None
            and (minimum <= parsed < maximum)
        )

    def supports_server_version(self, version: str) -> bool:
        """Return whether a Docker Engine version includes the BuildKit panic fix."""

        parsed = _parse_docker_version(version)
        minimum = _parse_docker_version(self.minimum_server_version)
        return (
            parsed is not None
            and minimum is not None
            and parsed >= minimum
            and version not in self.known_vulnerable_server_versions
        )


@dataclass(frozen=True, slots=True)
class DockerBuildObservation:
    """Observed Docker CLI/Engine identity and confirmed builder mode."""

    builder_mode: str
    daemon_endpoint: str
    client_version: str
    server_version: str
    legacy_mode_confirmed: bool

    def to_dict(self) -> dict[str, object]:
        """Return the exact Docker build observation recorded in S6 evidence."""

        return {
            "builder_mode": self.builder_mode,
            "daemon_endpoint": self.daemon_endpoint,
            "client_version": self.client_version,
            "server_version": self.server_version,
            "legacy_mode_confirmed": self.legacy_mode_confirmed,
        }


def _parse_docker_version(value: object) -> tuple[int, int, int] | None:
    """Parse only an exact numeric Docker version, leaving unknown formats unsupported."""

    if not isinstance(value, str):
        return None
    match = _DOCKER_VERSION_PATTERN.fullmatch(value)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def parse_docker_build_policy(payload: object) -> DockerBuildPolicy:
    """Validate one governed builder policy and reject versions below the patched floor."""

    expected_keys = {
        "schema",
        "builder_mode",
        "daemon_endpoint",
        "minimum_client_version",
        "maximum_client_version_exclusive",
        "minimum_server_version",
        "known_vulnerable_server_versions",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ValueError("REHEARSAL_DOCKER_BUILDER_POLICY_INVALID")
    values: dict[str, object] = payload
    minimum_client = values["minimum_client_version"]
    maximum_client = values["maximum_client_version_exclusive"]
    minimum_server = values["minimum_server_version"]
    vulnerable = values["known_vulnerable_server_versions"]
    minimum_client_version = _parse_docker_version(minimum_client)
    maximum_client_version = _parse_docker_version(maximum_client)
    minimum_server_version = _parse_docker_version(minimum_server)
    if minimum_server_version is None:
        raise ValueError("REHEARSAL_DOCKER_BUILDER_POLICY_INVALID")
    if (
        values["schema"] != DOCKER_BUILD_POLICY_SCHEMA
        or values["builder_mode"] != DOCKER_BUILDER_MODE
        or values["daemon_endpoint"] != DOCKER_DAEMON_ENDPOINT
        or not isinstance(minimum_client, str)
        or not isinstance(maximum_client, str)
        or not isinstance(minimum_server, str)
        or minimum_client_version is None
        or minimum_client_version < MINIMUM_SUPPORTED_DOCKER_VERSION
        or maximum_client_version != MAXIMUM_SUPPORTED_DOCKER_CLIENT_VERSION_EXCLUSIVE
        or minimum_client_version >= maximum_client_version
        or minimum_server_version < MINIMUM_SUPPORTED_DOCKER_VERSION
        or not isinstance(vulnerable, list)
        or any(not isinstance(version, str) for version in vulnerable)
    ):
        raise ValueError("REHEARSAL_DOCKER_BUILDER_POLICY_INVALID")
    vulnerable_versions = tuple(vulnerable)
    if vulnerable_versions != tuple(sorted(set(vulnerable_versions))) or not set(
        KNOWN_VULNERABLE_DOCKER_SERVER_VERSIONS
    ).issubset(vulnerable_versions):
        raise ValueError("REHEARSAL_DOCKER_BUILDER_POLICY_INVALID")
    for version in vulnerable_versions:
        parsed_version = _parse_docker_version(version)
        if parsed_version is None or parsed_version >= minimum_server_version:
            raise ValueError("REHEARSAL_DOCKER_BUILDER_POLICY_INVALID")
    return DockerBuildPolicy(
        builder_mode=DOCKER_BUILDER_MODE,
        daemon_endpoint=DOCKER_DAEMON_ENDPOINT,
        minimum_client_version=minimum_client,
        maximum_client_version_exclusive=maximum_client,
        minimum_server_version=minimum_server,
        known_vulnerable_server_versions=vulnerable_versions,
    )


def load_docker_build_policy(path: Path) -> DockerBuildPolicy:
    """Read and validate the governed Docker build policy from a JSON file."""

    try:
        payload: object = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("REHEARSAL_DOCKER_BUILDER_POLICY_INVALID") from exc
    if not isinstance(payload, dict):
        raise ValueError("REHEARSAL_DOCKER_BUILDER_POLICY_INVALID")
    if payload.get("schema") != "release.rehearsal-policy.v1":
        raise ValueError("REHEARSAL_DOCKER_BUILDER_POLICY_INVALID")
    section = payload.get("docker_build_policy")
    return parse_docker_build_policy(section)


def parse_docker_build_observation(
    payload: object, policy: DockerBuildPolicy
) -> DockerBuildObservation:
    """Validate remote build evidence against the expected endpoint and safe versions."""

    expected_keys = {
        "builder_mode",
        "daemon_endpoint",
        "client_version",
        "server_version",
        "legacy_mode_confirmed",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ValueError("REHEARSAL_DOCKER_BUILDER_PREFLIGHT_FAILED")
    values: dict[str, object] = payload
    builder_mode = values["builder_mode"]
    daemon_endpoint = values["daemon_endpoint"]
    client_version = values["client_version"]
    server_version = values["server_version"]
    legacy_mode_confirmed = values["legacy_mode_confirmed"]
    if (
        builder_mode != policy.builder_mode
        or daemon_endpoint != policy.daemon_endpoint
        or not isinstance(client_version, str)
        or not policy.supports_client_version(client_version)
        or not isinstance(server_version, str)
        or not policy.supports_server_version(server_version)
        or legacy_mode_confirmed is not True
    ):
        raise ValueError("REHEARSAL_DOCKER_BUILDER_PREFLIGHT_FAILED")
    return DockerBuildObservation(
        builder_mode=policy.builder_mode,
        daemon_endpoint=policy.daemon_endpoint,
        client_version=client_version,
        server_version=server_version,
        legacy_mode_confirmed=True,
    )


@dataclass(frozen=True, slots=True)
class StageEnvironmentIssue:
    """One secret-free, stable preflight failure assigned to one or more stages."""

    category: str
    code: str
    stages: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError("REHEARSAL_STAGE_ENVIRONMENT_CATEGORY_INVALID")
        if self.code not in ALLOWED_ISSUE_CODES or not self.stages:
            raise ValueError("REHEARSAL_STAGE_ENVIRONMENT_ISSUE_INVALID")

    def to_dict(self) -> dict[str, object]:
        """Return only stable metadata suitable for release evidence."""

        return {"category": self.category, "code": self.code, "stages": list(self.stages)}


@dataclass(frozen=True, slots=True)
class StageEnvironmentInputs:
    """Already-frozen host and candidate observations consumed without writes."""

    stages: tuple[str, ...]
    filesystem_paths: tuple[Path, ...]
    text_transport_paths: tuple[Path, ...]
    missing_identity_keys: tuple[str, ...]
    free_disk_bytes: int
    available_memory_bytes: int
    observed_at: datetime
    build_timeout_seconds: float
    stage_timeout_seconds: float
    provider_timeout_seconds: float
    task_deadline_seconds: float
    lock_wait_limit_seconds: float
    missing_runtime_dependencies: tuple[str, ...] = ()
    dynamic_issues: tuple[StageEnvironmentIssue, ...] = ()
    minimum_free_disk_bytes: int = MINIMUM_FREE_DISK_BYTES
    docker_build_policy: DockerBuildPolicy | None = None


def _all(stages: Sequence[str], category: str, code: str) -> StageEnvironmentIssue:
    return StageEnvironmentIssue(category=category, code=code, stages=tuple(stages))


def _filesystem_issues(inputs: StageEnvironmentInputs) -> list[StageEnvironmentIssue]:
    issues: list[StageEnvironmentIssue] = []
    for path in inputs.filesystem_paths:
        try:
            metadata = path.lstat()
        except OSError:
            issues.append(
                _all(inputs.stages, "filesystem", "REHEARSAL_STAGE_FILESYSTEM_ENTRY_INVALID")
            )
            continue
        if path.is_symlink() or not (
            stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)
        ):
            issues.append(
                _all(inputs.stages, "filesystem", "REHEARSAL_STAGE_FILESYSTEM_ENTRY_INVALID")
            )
    return issues


def _encoding_issues(inputs: StageEnvironmentInputs) -> list[StageEnvironmentIssue]:
    issues: list[StageEnvironmentIssue] = []
    for path in inputs.text_transport_paths:
        try:
            raw = path.read_bytes()
            raw.decode("utf-8")
        except (OSError, UnicodeError):
            issues.append(
                _all(
                    inputs.stages, "transfer_encoding", "REHEARSAL_STAGE_TRANSFER_ENCODING_INVALID"
                )
            )
            continue
        if not raw or raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or b"\x00" in raw:
            issues.append(
                _all(
                    inputs.stages, "transfer_encoding", "REHEARSAL_STAGE_TRANSFER_ENCODING_INVALID"
                )
            )
    return issues


def _identity_issues(inputs: StageEnvironmentInputs) -> list[StageEnvironmentIssue]:
    issues: list[StageEnvironmentIssue] = []
    if inputs.missing_identity_keys:
        issues.append(
            _all(
                inputs.stages,
                "identity_and_secrets",
                "REHEARSAL_STAGE_IDENTITY_OR_SECRET_CONTRACT_INVALID",
            )
        )
    if inputs.missing_runtime_dependencies and "build_only" in inputs.stages:
        issues.append(
            StageEnvironmentIssue(
                category="identity_and_secrets",
                code="REHEARSAL_STAGE_RUNNER_DEPENDENCY_MISSING",
                stages=("build_only",),
            )
        )
    return issues


def _resource_issues(inputs: StageEnvironmentInputs) -> list[StageEnvironmentIssue]:
    issues: list[StageEnvironmentIssue] = []
    if inputs.free_disk_bytes < inputs.minimum_free_disk_bytes:
        issues.append(
            _all(
                inputs.stages,
                "resources_and_time",
                "REHEARSAL_STAGE_DISK_HEADROOM_INSUFFICIENT",
            )
        )
    if inputs.available_memory_bytes < MINIMUM_AVAILABLE_MEMORY_BYTES:
        issues.append(
            _all(
                inputs.stages,
                "resources_and_time",
                "REHEARSAL_STAGE_MEMORY_HEADROOM_INSUFFICIENT",
            )
        )
    if inputs.observed_at.tzinfo is None or inputs.observed_at.utcoffset() is None:
        issues.append(_all(inputs.stages, "resources_and_time", "REHEARSAL_STAGE_CLOCK_INVALID"))
    budgets = (
        inputs.build_timeout_seconds,
        inputs.stage_timeout_seconds,
        inputs.provider_timeout_seconds,
        inputs.task_deadline_seconds,
        inputs.lock_wait_limit_seconds,
    )
    if any(value <= 0 for value in budgets) or (
        inputs.provider_timeout_seconds > inputs.stage_timeout_seconds
        or inputs.task_deadline_seconds > inputs.stage_timeout_seconds
        or inputs.lock_wait_limit_seconds > inputs.task_deadline_seconds
    ):
        issues.append(
            _all(inputs.stages, "resources_and_time", "REHEARSAL_STAGE_TIME_BUDGET_INVALID")
        )
    return issues


def _deduplicate(issues: Sequence[StageEnvironmentIssue]) -> tuple[StageEnvironmentIssue, ...]:
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    result: list[StageEnvironmentIssue] = []
    for issue in issues:
        key = (issue.category, issue.code, issue.stages)
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return tuple(result)


def evaluate_stage_environment(inputs: StageEnvironmentInputs) -> dict[str, object]:
    """Evaluate every category and return every gap without short-circuiting."""

    registry_gaps = tuple(stage for stage in inputs.stages if stage not in CONTRACT_STAGES)
    issues: list[StageEnvironmentIssue] = []
    if registry_gaps:
        issues.append(
            StageEnvironmentIssue(
                category="external_state",
                code="REHEARSAL_STAGE_ENVIRONMENT_CONTRACT_MISSING",
                stages=registry_gaps,
            )
        )
    if "build_only" in inputs.stages and inputs.docker_build_policy is None:
        issues.append(
            StageEnvironmentIssue(
                category="external_state",
                code="REHEARSAL_DOCKER_BUILDER_POLICY_INVALID",
                stages=("build_only",),
            )
        )
    issues.extend(_filesystem_issues(inputs))
    issues.extend(_encoding_issues(inputs))
    issues.extend(_identity_issues(inputs))
    issues.extend(_resource_issues(inputs))
    issues.extend(inputs.dynamic_issues)
    frozen = _deduplicate(issues)
    cells: list[dict[str, object]] = []
    for stage in inputs.stages:
        for category in CATEGORIES:
            codes = tuple(
                issue.code
                for issue in frozen
                if issue.category == category and stage in issue.stages
            )
            cells.append(
                {
                    "stage": stage,
                    "category": category,
                    "outcome": "blocked" if codes else "pass",
                    "codes": list(codes),
                }
            )
    observations: dict[str, object] = {
        "observed_at": inputs.observed_at.isoformat(),
        "free_disk_bytes": inputs.free_disk_bytes,
        "minimum_free_disk_bytes": inputs.minimum_free_disk_bytes,
        "available_memory_bytes": inputs.available_memory_bytes,
        "build_timeout_seconds": inputs.build_timeout_seconds,
        "stage_timeout_seconds": inputs.stage_timeout_seconds,
        "provider_timeout_seconds": inputs.provider_timeout_seconds,
        "task_deadline_seconds": inputs.task_deadline_seconds,
        "lock_wait_limit_seconds": inputs.lock_wait_limit_seconds,
    }
    if "build_only" in inputs.stages and inputs.docker_build_policy is not None:
        observations["docker_build_policy"] = inputs.docker_build_policy.to_dict()
    return {
        "schema": SCHEMA,
        "outcome": "blocked" if frozen else "pass",
        "observations": observations,
        "categories": list(CATEGORIES),
        "stages": list(inputs.stages),
        "issues": [issue.to_dict() for issue in frozen],
        "matrix": cells,
    }


def parse_dynamic_issues(payload: Mapping[str, object]) -> tuple[StageEnvironmentIssue, ...]:
    """Parse a candidate probe without accepting free-form diagnostic text."""

    raw_issues = payload.get("issues")
    if payload.get("schema") != SCHEMA or not isinstance(raw_issues, list):
        raise ValueError("REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_REPORT_INVALID")
    parsed: list[StageEnvironmentIssue] = []
    for raw in raw_issues:
        if not isinstance(raw, dict) or set(raw) != {"category", "code", "stages"}:
            raise ValueError("REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_REPORT_INVALID")
        category, code, stages = raw["category"], raw["code"], raw["stages"]
        if (
            not isinstance(category, str)
            or not isinstance(code, str)
            or not isinstance(stages, list)
            or any(not isinstance(stage, str) for stage in stages)
            or any(stage not in CONTRACT_STAGES for stage in stages)
        ):
            raise ValueError("REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_REPORT_INVALID")
        parsed.append(StageEnvironmentIssue(category, code, tuple(stages)))
    return tuple(parsed)


__all__ = [
    "ALLOWED_ISSUE_CODES",
    "BUILD_DISK_RESERVE_BYTES",
    "CATEGORIES",
    "CONTRACT_STAGES",
    "DOCKER_BUILD_POLICY_SCHEMA",
    "DOCKER_BUILDER_MODE",
    "DOCKER_DAEMON_ENDPOINT",
    "DockerBuildObservation",
    "DockerBuildPolicy",
    "KNOWN_VULNERABLE_DOCKER_SERVER_VERSIONS",
    "MAXIMUM_SUPPORTED_DOCKER_CLIENT_VERSION_EXCLUSIVE",
    "MINIMUM_AVAILABLE_MEMORY_BYTES",
    "MINIMUM_FREE_DISK_BYTES",
    "MINIMUM_PREBUILD_FREE_DISK_BYTES",
    "MINIMUM_SUPPORTED_DOCKER_VERSION",
    "SCHEMA",
    "StageEnvironmentInputs",
    "StageEnvironmentIssue",
    "evaluate_stage_environment",
    "load_docker_build_policy",
    "parse_docker_build_observation",
    "parse_docker_build_policy",
    "parse_dynamic_issues",
]
