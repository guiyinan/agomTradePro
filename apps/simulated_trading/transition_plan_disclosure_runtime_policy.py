"""Resolve an active Config Center disclosure window and bounded internal lease."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol, TypedDict, cast

from django.db import DatabaseError

from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventCoverageLeasePolicy,
)
from core.exceptions import AgomTradeProException
from core.integration.config_center_runtime import (
    RuntimeConfigProfileRead,
    RuntimeConfigSnapshotRead,
    get_active_runtime_profile,
    get_active_runtime_value,
    get_latest_runtime_snapshot,
)

DISCLOSURE_COVERAGE_POLICY_KEY = "config_center.market.simulated_disclosure_coverage_policy"
SZSE_OFFICIAL_SOURCE_ID: Literal["szse_official"] = "szse_official"
_POLICY_SCHEMA_VERSION = "simulated-disclosure-coverage-policy.v1"
_OWNER_MAXIMUM_LEASE_TTL = timedelta(seconds=60)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_POLICY_FIELDS = frozenset(
    {
        "schema_version",
        "enabled",
        "source_id",
        "start_on",
        "end_on_mode",
        "body_store_root",
        "policy_version",
        "lease_ttl_seconds",
    }
)


class _DisclosureCoveragePolicyPayload(TypedDict):
    """Strict JSON shape stored in the optional active runtime profile."""

    schema_version: str
    enabled: bool
    source_id: str
    start_on: str
    end_on_mode: str
    body_store_root: str
    policy_version: str
    lease_ttl_seconds: int


@dataclass(frozen=True, slots=True)
class RuntimeDisclosurePolicyEvidence:
    """One active typed-JSON value bound to exact immutable Config Center reads."""

    runtime_environment: str
    definition_key: str
    value: object
    profile: RuntimeConfigProfileRead
    snapshot: RuntimeConfigSnapshotRead
    read_at: datetime


class DisclosurePolicyEvidenceReader(Protocol):
    """Read the active Config Center profile, snapshot, and typed policy at a cutoff."""

    def read_active_evidence(
        self,
        *,
        runtime_environment: str,
        definition_key: str,
        as_of: datetime,
    ) -> RuntimeDisclosurePolicyEvidence | None:
        """Return stable profile/snapshot evidence or None when unavailable or changed."""
        ...


@dataclass(frozen=True, slots=True)
class TransitionPlanDisclosureRuntimePolicy:
    """Exact official source window, body location, lease policy, and runtime provenance."""

    source_id: Literal["szse_official"]
    start_on: date
    end_on: date
    body_store_root: Path
    lease_policy: TransitionPlanEventCoverageLeasePolicy
    policy_version: str
    runtime_environment: str
    profile_id: str
    profile_key: str
    profile_version: int
    profile_content_hash: str
    snapshot_id: str
    snapshot_content_hash: str
    known_at: datetime
    effective_at: datetime
    read_at: datetime
    policy_content_hash: str


class ConfigCenterDisclosurePolicyEvidenceReader:
    """Read a stable active Config Center value through its public runtime facade."""

    def read_active_evidence(
        self,
        *,
        runtime_environment: str,
        definition_key: str,
        as_of: datetime,
    ) -> RuntimeDisclosurePolicyEvidence | None:
        """Return one unchanged active profile/snapshot/value tuple at the exact cutoff."""

        if (
            not _is_token(runtime_environment)
            or definition_key != DISCLOSURE_COVERAGE_POLICY_KEY
            or not _is_aware(as_of)
        ):
            return None
        try:
            profile_before = get_active_runtime_profile(runtime_environment)
            if not isinstance(profile_before, RuntimeConfigProfileRead):
                return None
            snapshot_before = get_latest_runtime_snapshot(profile_before.profile_key)
            if not isinstance(snapshot_before, RuntimeConfigSnapshotRead):
                return None
            value_before = get_active_runtime_value(
                environment=runtime_environment,
                definition_key=definition_key,
                as_of=as_of,
            )
            profile_after = get_active_runtime_profile(runtime_environment)
            if not isinstance(profile_after, RuntimeConfigProfileRead):
                return None
            snapshot_after = get_latest_runtime_snapshot(profile_after.profile_key)
            if not isinstance(snapshot_after, RuntimeConfigSnapshotRead):
                return None
            value_after = get_active_runtime_value(
                environment=runtime_environment,
                definition_key=definition_key,
                as_of=as_of,
            )
            if (
                profile_before != profile_after
                or snapshot_before != snapshot_after
                or value_before is None
                or value_before != value_after
                or snapshot_after.resolved_values.get(definition_key) != value_after
            ):
                return None
            return RuntimeDisclosurePolicyEvidence(
                runtime_environment=runtime_environment,
                definition_key=definition_key,
                value=value_after,
                profile=profile_after,
                snapshot=snapshot_after,
                read_at=as_of,
            )
        except (
            AgomTradeProException,
            ArithmeticError,
            AttributeError,
            DatabaseError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return None


class ConfiguredTransitionPlanDisclosureRuntimePolicyReader:
    """Resolve an explicit SZSE policy only from a stable active runtime profile."""

    def __init__(
        self,
        *,
        runtime_environment: str,
        evidence_reader: DisclosurePolicyEvidenceReader | None = None,
    ) -> None:
        """Bind an explicit environment and injectable active-evidence reader."""

        if not _is_token(runtime_environment):
            raise ValueError("disclosure policy runtime environment must be an explicit token")
        self._runtime_environment = runtime_environment
        self._evidence_reader = (
            ConfigCenterDisclosurePolicyEvidenceReader()
            if evidence_reader is None
            else evidence_reader
        )

    def read_policy(
        self,
        *,
        decision_on: date,
        earliest_required_on: date,
        as_of: datetime,
    ) -> TransitionPlanDisclosureRuntimePolicy | None:
        """Return a complete explicit policy for the supplied account and decision dates."""

        if (
            type(decision_on) is not date
            or type(earliest_required_on) is not date
            or not _is_aware(as_of)
            or earliest_required_on > decision_on
        ):
            return None
        try:
            evidence = self._evidence_reader.read_active_evidence(
                runtime_environment=self._runtime_environment,
                definition_key=DISCLOSURE_COVERAGE_POLICY_KEY,
                as_of=as_of,
            )
            if type(evidence) is not RuntimeDisclosurePolicyEvidence:
                return None
            parsed = _parse_runtime_policy(
                evidence,
                runtime_environment=self._runtime_environment,
                earliest_required_on=earliest_required_on,
                decision_on=decision_on,
                as_of=as_of,
            )
            if parsed is None:
                return None
            payload, body_store_root, policy_content_hash = parsed
            profile = evidence.profile
            snapshot = evidence.snapshot
            effective_at = snapshot.effective_from
            if effective_at is None:
                return None
            lease_policy = TransitionPlanEventCoverageLeasePolicy(
                policy_version=payload["policy_version"],
                ttl=timedelta(seconds=payload["lease_ttl_seconds"]),
                maximum_ttl=_OWNER_MAXIMUM_LEASE_TTL,
            )
            return TransitionPlanDisclosureRuntimePolicy(
                source_id=SZSE_OFFICIAL_SOURCE_ID,
                start_on=date.fromisoformat(payload["start_on"]),
                end_on=decision_on,
                body_store_root=body_store_root,
                lease_policy=lease_policy,
                policy_version=payload["policy_version"],
                runtime_environment=evidence.runtime_environment,
                profile_id=profile.profile_id,
                profile_key=profile.profile_key,
                profile_version=profile.version,
                profile_content_hash=profile.content_hash,
                snapshot_id=snapshot.snapshot_id,
                snapshot_content_hash=snapshot.snapshot_hash,
                known_at=profile.created_at,
                effective_at=effective_at,
                read_at=evidence.read_at,
                policy_content_hash=policy_content_hash,
            )
        except (
            AgomTradeProException,
            ArithmeticError,
            AttributeError,
            DatabaseError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return None


def _parse_runtime_policy(
    evidence: RuntimeDisclosurePolicyEvidence,
    *,
    runtime_environment: str,
    earliest_required_on: date,
    decision_on: date,
    as_of: datetime,
) -> tuple[_DisclosureCoveragePolicyPayload, Path, str] | None:
    """Validate runtime provenance, hashes, and the exact configured policy schema."""

    profile = evidence.profile
    snapshot = evidence.snapshot
    if (
        evidence.runtime_environment != runtime_environment
        or evidence.definition_key != DISCLOSURE_COVERAGE_POLICY_KEY
        or evidence.read_at != as_of
        or not isinstance(profile, RuntimeConfigProfileRead)
        or not isinstance(snapshot, RuntimeConfigSnapshotRead)
    ):
        return None
    profile.__post_init__()
    snapshot.__post_init__()
    activated_at = profile.activated_at
    effective_at = snapshot.effective_from
    if (
        profile.environment != runtime_environment
        or profile.status != "active"
        or not _is_token(profile.profile_id)
        or not _is_token(profile.profile_key)
        or type(profile.version) is not int
        or profile.version < 1
        or not _is_sha256(profile.content_hash)
        or not _is_aware(profile.created_at)
        or activated_at is None
        or not _is_aware(activated_at)
        or not _is_token(snapshot.snapshot_id)
        or not _is_sha256(snapshot.snapshot_hash)
        or not _is_aware(snapshot.generated_at)
        or effective_at is None
        or not _is_aware(effective_at)
        or (snapshot.profile_id, snapshot.profile_key, snapshot.profile_version)
        != (profile.profile_id, profile.profile_key, profile.version)
        or effective_at != activated_at
        or not profile.created_at <= activated_at <= snapshot.generated_at <= as_of
        or effective_at > as_of
    ):
        return None

    if not isinstance(snapshot.resolved_values, Mapping):
        return None
    resolved_values = dict(snapshot.resolved_values)
    if resolved_values.get(DISCLOSURE_COVERAGE_POLICY_KEY) != evidence.value:
        return None
    snapshot_hash = _canonical_sha256(resolved_values)
    if snapshot_hash is None or snapshot_hash != snapshot.snapshot_hash:
        return None

    parsed = _parse_policy_payload(evidence.value)
    if parsed is None:
        return None
    payload, body_store_root, policy_content_hash = parsed
    start_on = date.fromisoformat(payload["start_on"])
    if not start_on <= earliest_required_on <= decision_on:
        return None
    return payload, body_store_root, policy_content_hash


def _parse_policy_payload(
    value: object,
) -> tuple[_DisclosureCoveragePolicyPayload, Path, str] | None:
    """Narrow raw JSON to the single explicit schema; reject implicit or unknown fields."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        return None
    raw = cast(dict[str, object], value)
    if set(raw) != _POLICY_FIELDS:
        return None
    if (
        raw.get("schema_version") != _POLICY_SCHEMA_VERSION
        or type(raw.get("enabled")) is not bool
        or raw.get("enabled") is not True
        or raw.get("source_id") != SZSE_OFFICIAL_SOURCE_ID
        or raw.get("end_on_mode") != "decision_on"
        or type(raw.get("start_on")) is not str
        or type(raw.get("body_store_root")) is not str
        or not _is_token(raw.get("policy_version"))
        or type(raw.get("lease_ttl_seconds")) is not int
        or not 1 <= cast(int, raw.get("lease_ttl_seconds")) <= 60
    ):
        return None
    start_text = cast(str, raw["start_on"])
    try:
        start_on = date.fromisoformat(start_text)
    except ValueError:
        return None
    if start_on.isoformat() != start_text:
        return None
    body_store_text = cast(str, raw["body_store_root"])
    if (
        not body_store_text
        or body_store_text.strip() != body_store_text
        or "\x00" in body_store_text
    ):
        return None
    body_store_root = Path(body_store_text)
    if not body_store_root.is_absolute() or ".." in body_store_root.parts:
        return None
    payload = cast(_DisclosureCoveragePolicyPayload, raw)
    policy_content_hash = _canonical_sha256(payload)
    if policy_content_hash is None:
        return None
    return payload, body_store_root, policy_content_hash


def _canonical_sha256(value: object) -> str | None:
    """Hash one deterministic JSON value using Config Center's public snapshot encoding."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, UnicodeError, ValueError, OverflowError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _is_token(value: object) -> bool:
    """Return whether a value is a non-empty, trimmed runtime identity token."""

    return (
        type(value) is str
        and bool(value)
        and value.strip() == value
        and not any(character.isspace() for character in value)
    )


def _is_sha256(value: object) -> bool:
    """Require exact lowercase SHA-256 evidence identities."""

    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _is_aware(value: object) -> bool:
    """Return whether a value is an exact timezone-aware datetime."""

    if type(value) is not datetime or value.tzinfo is None:
        return False
    try:
        return value.utcoffset() is not None
    except (OverflowError, TypeError, ValueError):
        return False


__all__ = (
    "DISCLOSURE_COVERAGE_POLICY_KEY",
    "SZSE_OFFICIAL_SOURCE_ID",
    "ConfigCenterDisclosurePolicyEvidenceReader",
    "ConfiguredTransitionPlanDisclosureRuntimePolicyReader",
    "DisclosurePolicyEvidenceReader",
    "RuntimeDisclosurePolicyEvidence",
    "TransitionPlanDisclosureRuntimePolicy",
)
