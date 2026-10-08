"""Read-only, aggregate environment checks for every S6 evidence stage."""

from __future__ import annotations

import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA = "release.s6-stage-environment-preflight.v1"
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
    return {
        "schema": SCHEMA,
        "outcome": "blocked" if frozen else "pass",
        "observations": {
            "observed_at": inputs.observed_at.isoformat(),
            "free_disk_bytes": inputs.free_disk_bytes,
            "minimum_free_disk_bytes": inputs.minimum_free_disk_bytes,
            "available_memory_bytes": inputs.available_memory_bytes,
            "build_timeout_seconds": inputs.build_timeout_seconds,
            "stage_timeout_seconds": inputs.stage_timeout_seconds,
            "provider_timeout_seconds": inputs.provider_timeout_seconds,
            "task_deadline_seconds": inputs.task_deadline_seconds,
            "lock_wait_limit_seconds": inputs.lock_wait_limit_seconds,
        },
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
    "MINIMUM_AVAILABLE_MEMORY_BYTES",
    "MINIMUM_FREE_DISK_BYTES",
    "MINIMUM_PREBUILD_FREE_DISK_BYTES",
    "SCHEMA",
    "StageEnvironmentInputs",
    "StageEnvironmentIssue",
    "evaluate_stage_environment",
    "parse_dynamic_issues",
]
