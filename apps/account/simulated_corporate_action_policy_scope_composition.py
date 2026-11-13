"""Dedicated service-write policy; staff reader policies are never reused."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from django.utils import timezone

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
    validate_simulated_corporate_action_write_capabilities,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
    SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    SimulatedCorporateActionWriteGrantBinding,
)
from apps.config_center.runtime_environment_lock_composition import locked_runtime_environment
from core.integration.config_center_runtime import (
    ActiveRuntimeValueEvidence,
    RuntimeConfigProfileRead,
    RuntimeConfigSnapshotRead,
    get_active_runtime_profile,
    get_active_runtime_value_evidence,
    get_latest_runtime_snapshot,
)

SIMULATED_ACTION_WRITE_POLICY_KEY = (
    "config_center.account.simulated_corporate_action_write_policies"
)
SIMULATED_ACTION_WRITE_POLICY_SCHEMA_V1 = "simulated-corporate-action-write-policies.v1"
SIMULATED_ACTION_WRITE_POLICY_SCHEMA_V2 = "simulated-corporate-action-write-policies.v2"
SIMULATED_ACTION_WRITE_POLICY_SCHEMA_V3 = "simulated-corporate-action-write-policies.v3"
_FIELDS = frozenset(
    {
        "policy_id",
        "policy_version",
        "canonical_account_id",
        "owner_user_id",
        "tenant_id",
        "owner_id",
        "valid_from",
        "valid_until",
        "maximum_grant_seconds",
        "permission",
        "service_actor_id",
    }
)
_V2_FIELDS = _FIELDS | frozenset({"capabilities", "terms_version", "terms_sha256"})
_V3_FIELDS = _V2_FIELDS
_V2_CAPABILITIES = frozenset(
    {
        SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE,
        SimulatedCorporateActionWriteCapability.TAX_ASSESS,
        SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
    }
)


@dataclass(frozen=True, slots=True)
class ConfiguredSimulatedActionWritePolicy:
    """Exact current configuration scope including immutable runtime lineage."""

    policy_id: str
    policy_version: str
    canonical_account_id: str
    owner_user_id: int
    tenant_id: str
    owner_id: str
    valid_from: datetime
    valid_until: datetime
    maximum_grant_seconds: int
    content_hash: str
    grant_schema: str = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA
    capabilities: tuple[SimulatedCorporateActionWriteCapability, ...] | None = None
    terms_version: str | None = None
    terms_sha256: str | None = None

    def grant_valid_until(self, *, as_of: datetime, source_valid_until: datetime) -> datetime:
        """Bound the configured duration before datetime addition, preserving finite source limits."""
        ceiling = min(self.valid_until, source_valid_until)
        if ceiling <= as_of:
            raise ValueError("service policy has no remaining grant validity")
        return as_of + min(timedelta(seconds=self.maximum_grant_seconds), ceiling - as_of)


def _hash(value: object) -> str:
    """Hash canonical public policy/lineage data without secret material."""
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _aware_text(value: object) -> datetime:
    """Narrow an explicit configured ISO cutoff before authority use."""
    if type(value) is not str:
        raise ValueError("service policy cutoff must be an ISO string")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("service policy cutoff must be timezone-aware")
    return result


def _require_grant_schema(value: object) -> str:
    """Accept only the explicitly supported grant schemas."""
    if type(value) is not str or value not in {
        SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
        SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    }:
        raise ValueError("expected grant schema is unsupported")
    return value


def _decode_capabilities(value: object) -> tuple[SimulatedCorporateActionWriteCapability, ...]:
    """Decode a nonempty JSON capability array without coercion or repair."""
    if type(value) is not list:
        raise ValueError("service policy capabilities must be a JSON array")
    raw_values = cast(list[object], value)
    decoded: list[SimulatedCorporateActionWriteCapability] = []
    for raw in raw_values:
        if type(raw) is not str:
            raise ValueError("service policy capability must be an exact string")
        try:
            decoded.append(SimulatedCorporateActionWriteCapability(raw))
        except ValueError as error:
            raise ValueError("service policy capability is unknown") from error
    try:
        return validate_simulated_corporate_action_write_capabilities(tuple(decoded))
    except (TypeError, ValueError) as error:
        raise ValueError("service policy capabilities are not canonical") from error


def _decode_terms(version: object, digest: object) -> tuple[str, str]:
    """Require explicit bounded terms identity and a canonical SHA-256 digest."""
    if (
        type(version) is not str
        or not version
        or version.strip() != version
        or len(version) > 192
        or any(character.isspace() for character in version)
    ):
        raise ValueError("service policy terms version is invalid")
    if (
        type(digest) is not str
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("service policy terms digest is invalid")
    return version, digest


def read_current_simulated_action_write_policy(
    *,
    canonical_account_id: str,
    owner_user_id: int,
    environment: str,
    as_of: datetime,
    expected_grant_schema: str | None = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
) -> ConfiguredSimulatedActionWritePolicy:
    """Discover one explicit current policy for an owner without issuing authority.

    Every configured scope is validated and account collisions are retained
    before checking the requester. ``None`` explicitly discovers the unique
    current account policy's schema; it must not be used by a write fence.
    Consumers must reacquire the activation fence and exact expected binding
    before granting or posting financial effects.
    The unique current account row is selected before its owner and requested
    grant schema are checked, so legacy readers cannot fall back to older rights.
    """
    if (
        type(canonical_account_id) is not str
        or not canonical_account_id
        or type(owner_user_id) is not int
        or owner_user_id <= 0
        or type(as_of) is not datetime
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
    ):
        raise ValueError("service policy discovery scope or clock is invalid")
    if expected_grant_schema is not None:
        expected_grant_schema = _require_grant_schema(expected_grant_schema)
    evidence = get_active_runtime_value_evidence(
        environment=environment, definition_key=SIMULATED_ACTION_WRITE_POLICY_KEY, as_of=as_of
    )
    if type(evidence) is not ActiveRuntimeValueEvidence or (
        evidence.environment != environment
        or evidence.definition_key != SIMULATED_ACTION_WRITE_POLICY_KEY
        or evidence.as_of != as_of
        or evidence.known_at != evidence.created_at
        or not evidence.created_at
        <= evidence.activated_at
        <= evidence.snapshot_generated_at
        <= as_of
        or evidence.effective_at != evidence.activated_at
    ):
        raise ValueError("service policy runtime lineage is unavailable")
    profile = get_active_runtime_profile(environment)
    snapshot = get_latest_runtime_snapshot(evidence.profile_key)
    if not isinstance(profile, RuntimeConfigProfileRead) or not isinstance(
        snapshot, RuntimeConfigSnapshotRead
    ):
        raise ValueError("service policy exact runtime source is missing")
    profile.__post_init__()
    snapshot.__post_init__()
    if (
        (profile.profile_id, profile.profile_key, profile.version, profile.content_hash)
        != (
            evidence.profile_id,
            evidence.profile_key,
            evidence.profile_version,
            evidence.profile_content_hash,
        )
        or profile.environment != environment
        or profile.status != "active"
        or profile.created_at != evidence.created_at
        or profile.activated_at != evidence.activated_at
        or (snapshot.profile_id, snapshot.profile_key, snapshot.profile_version)
        != (profile.profile_id, profile.profile_key, profile.version)
        or snapshot.snapshot_id != evidence.snapshot_id
        or snapshot.snapshot_hash != evidence.snapshot_hash
        or snapshot.generated_at != evidence.snapshot_generated_at
        or snapshot.effective_from != evidence.effective_at
        or _hash(dict(snapshot.resolved_values)) != evidence.snapshot_hash
        or snapshot.resolved_values.get(SIMULATED_ACTION_WRITE_POLICY_KEY) != evidence.value
    ):
        raise ValueError("service policy runtime snapshot does not match its source")
    if type(evidence.value) is not dict:
        raise ValueError("service policy must be explicit typed JSON")
    value = cast(dict[str, object], evidence.value)
    if (
        set(value) != {"schema_version", "enabled", "policies"}
        or type(value["schema_version"]) is not str
        or value["enabled"] is not True
        or type(value["policies"]) is not list
    ):
        raise ValueError("service policy schema is invalid or disabled")
    config_schema = value["schema_version"]
    if config_schema == SIMULATED_ACTION_WRITE_POLICY_SCHEMA_V1:
        grant_schema = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA
        expected_fields = _FIELDS
        expected_permission = SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION
    elif config_schema == SIMULATED_ACTION_WRITE_POLICY_SCHEMA_V2:
        grant_schema = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
        expected_fields = _V2_FIELDS
        expected_permission = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION
    elif config_schema == SIMULATED_ACTION_WRITE_POLICY_SCHEMA_V3:
        grant_schema = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA
        expected_fields = _V3_FIELDS
        expected_permission = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION
    else:
        raise ValueError("service policy schema version is unsupported")
    policies: list[ConfiguredSimulatedActionWritePolicy] = []
    for raw in cast(list[object], value["policies"]):
        if type(raw) is not dict:
            raise ValueError("service policy scope is invalid")
        item = cast(dict[str, object], raw)
        if set(item) != expected_fields or any(
            type(item[name]) is not str
            or not item[name]
            or len(cast(str, item[name])) > 192
            or any(character.isspace() for character in cast(str, item[name]))
            for name in (
                "policy_id",
                "policy_version",
                "canonical_account_id",
                "tenant_id",
                "owner_id",
            )
        ):
            raise ValueError("service policy identity is invalid")
        if (
            type(item["owner_user_id"]) is not int
            or item["owner_user_id"] <= 0
            or type(item["maximum_grant_seconds"]) is not int
            or item["maximum_grant_seconds"] <= 0
            or type(item["permission"]) is not str
            or item["permission"] != expected_permission
            or type(item["service_actor_id"]) is not str
            or item["service_actor_id"] != SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID
        ):
            raise ValueError("service policy permission or duration is invalid")
        try:
            timedelta(seconds=item["maximum_grant_seconds"])
        except OverflowError as error:
            raise ValueError("service policy duration is not representable") from error
        starts, ends = _aware_text(item["valid_from"]), _aware_text(item["valid_until"])
        if starts >= ends:
            raise ValueError("service policy validity is empty")
        capabilities: tuple[SimulatedCorporateActionWriteCapability, ...] | None = None
        terms_version: str | None = None
        terms_sha256: str | None = None
        if grant_schema in {
            SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
            SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
        }:
            capabilities = _decode_capabilities(item["capabilities"])
            if grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA and any(
                capability not in _V2_CAPABILITIES for capability in capabilities
            ):
                raise ValueError("V2 policy cannot include V3 capabilities")
            terms_version, terms_sha256 = _decode_terms(item["terms_version"], item["terms_sha256"])
        fingerprint = _hash(
            {
                "policy": item,
                "profile_id": evidence.profile_id,
                "profile_version": evidence.profile_version,
                "profile_hash": evidence.profile_content_hash,
                "snapshot_id": evidence.snapshot_id,
                "snapshot_hash": evidence.snapshot_hash,
                "effective_at": evidence.effective_at.isoformat(),
            }
        )
        policies.append(
            ConfiguredSimulatedActionWritePolicy(
                policy_id=cast(str, item["policy_id"]),
                policy_version=cast(str, item["policy_version"]),
                canonical_account_id=cast(str, item["canonical_account_id"]),
                owner_user_id=item["owner_user_id"],
                tenant_id=cast(str, item["tenant_id"]),
                owner_id=cast(str, item["owner_id"]),
                valid_from=starts,
                valid_until=ends,
                maximum_grant_seconds=item["maximum_grant_seconds"],
                content_hash=fingerprint,
                grant_schema=grant_schema,
                capabilities=capabilities,
                terms_version=terms_version,
                terms_sha256=terms_sha256,
            )
        )
    matches = tuple(
        p
        for p in policies
        if p.canonical_account_id == canonical_account_id and p.valid_from <= as_of < p.valid_until
    )
    if len(matches) != 1:
        raise ValueError("service policy requires one account scope without owner filtering")
    selected = matches[0]
    if selected.owner_user_id != owner_user_id:
        raise ValueError("service policy differs from requested owner scope")
    if expected_grant_schema is not None and selected.grant_schema != expected_grant_schema:
        raise ValueError("service policy grant schema differs from expected grant schema")
    return selected


def _read_policy(
    *,
    binding: SimulatedCorporateActionWriteGrantBinding,
    environment: str,
    as_of: datetime,
    expected_grant_schema: str = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
) -> ConfiguredSimulatedActionWritePolicy:
    """Match the discovered policy to every previously selected exact scope field."""
    expected_grant_schema = _require_grant_schema(expected_grant_schema)
    selected = read_current_simulated_action_write_policy(
        canonical_account_id=binding.account_id,
        owner_user_id=binding.owner_user_id,
        environment=environment,
        as_of=as_of,
        expected_grant_schema=expected_grant_schema,
    )
    if (
        selected.owner_user_id != binding.owner_user_id
        or selected.tenant_id != binding.tenant_id
        or selected.owner_id != binding.owner_id
        or selected.policy_id != binding.policy_id
        or selected.policy_version != binding.policy_version
        or selected.content_hash != binding.policy_content_hash
    ):
        raise ValueError("service policy differs from requested owner scope")
    return selected


@contextmanager
def locked_simulated_action_owner_policy(
    *,
    binding: SimulatedCorporateActionWriteGrantBinding,
    canonical_namespace: str,
    using: str,
    runtime_environment: str,
    expected_grant_schema: str = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
) -> Iterator[ConfiguredSimulatedActionWritePolicy]:
    """Hold the activation fence and recheck the expected policy schema before exit.

    Callers default to the V1 cash policy. Requesting V2 or V3 is explicit and
    does not itself issue a grant or authorize a financial operation.
    """
    binding.__post_init__()
    if canonical_namespace != "account":
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "service policy canonical namespace is invalid"
        )
    try:
        expected_grant_schema = _require_grant_schema(expected_grant_schema)
        with locked_runtime_environment(environment=runtime_environment, using=using):
            selected = _read_policy(
                binding=binding,
                environment=runtime_environment,
                as_of=timezone.now(),
                expected_grant_schema=expected_grant_schema,
            )
            yield selected
            if (
                _read_policy(
                    binding=binding,
                    environment=runtime_environment,
                    as_of=timezone.now(),
                    expected_grant_schema=expected_grant_schema,
                )
                != selected
            ):
                raise ValueError("service policy changed before commit")
    except (TypeError, ValueError, OverflowError) as error:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "simulated action service policy is unavailable"
        ) from error
