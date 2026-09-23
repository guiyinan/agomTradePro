"""Strict JSON boundary for the System Audit authority renewal command."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NoReturn, cast

from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.owner_tenant_authority_v3 import (
    SupersedeOwnerTenantAuthorityV3Command,
)
from apps.account.application.single_owner_actor_authority import SingleOwnerPolicyBinding
from apps.audit.application.system_audit_authority_renewal import (
    SystemAuditAuthorityRenewalRequest,
)

_ROOT_KEYS = frozenset(
    {
        "database_alias",
        "actor_recorder_service_id",
        "actor_validity_seconds",
        "authority_validity_seconds",
        "minimum_window_seconds",
        "principal",
        "policy",
        "actor_capture",
        "owner_successor",
        "profile",
    }
)
_PRINCIPAL_KEYS = frozenset(
    {
        "principal_id",
        "user_id",
        "authentication_context_hash",
        "authenticated_at",
        "valid_until",
    }
)
_POLICY_KEYS = frozenset(
    {
        "policy_id",
        "policy_version",
        "expected_content_hash",
        "tenant_id",
        "owner_id",
        "account_namespace",
        "account_id",
    }
)
_ACTOR_KEYS = frozenset(
    {
        "source_id",
        "source_version",
        "principal_id",
        "user_id",
        "authentication_context_id",
        "authentication_context_version",
        "expected_authentication_context_content_hash",
        "user_source_id",
        "user_source_version",
        "expected_user_source_content_hash",
        "rbac_source_id",
        "rbac_source_version",
        "expected_rbac_source_content_hash",
    }
)
_OWNER_KEYS = frozenset(
    {
        "authority_id",
        "authority_version",
        "predecessor_version",
        "expected_predecessor_content_hash",
        "assignment_evidence_id",
        "assignment_evidence_version",
        "expected_assignment_evidence_content_hash",
    }
)
_PROFILE_KEYS = frozenset(
    {
        "environment",
        "actor",
        "reason",
        "release_ref",
        "expected_active_profile_id",
        "expected_active_profile_version",
        "expected_active_profile_hash",
        "expected_active_snapshot_hash",
    }
)


@dataclass(frozen=True, slots=True)
class RenewalProfileInput:
    """Hash-bound Config Center activation input."""

    environment: str
    actor: str
    reason: str
    release_ref: str
    expected_active_profile_id: str | None
    expected_active_profile_version: int | None
    expected_active_profile_hash: str | None
    expected_active_snapshot_hash: str | None


@dataclass(frozen=True, slots=True)
class SystemAuditAuthorityRenewalInput:
    """Typed composition input for one actor/scope/runtime renewal."""

    database_alias: str
    actor_recorder_service_id: str
    actor_validity_period: timedelta
    authority_validity_period: timedelta
    renewal: SystemAuditAuthorityRenewalRequest
    principal: AuthenticatedAccountPrincipalV3
    policy_binding: SingleOwnerPolicyBinding
    profile: RenewalProfileInput


def parse_system_audit_authority_renewal_request(
    payload: bytes,
) -> SystemAuditAuthorityRenewalInput:
    """Parse one strict UTF-8 JSON renewal envelope without storage access."""

    if type(payload) is not bytes or not payload:
        raise ValueError("renewal request payload must be non-empty UTF-8 JSON")
    try:
        parsed: object = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise ValueError("renewal request payload is invalid JSON") from error
    root = _exact_mapping(parsed, _ROOT_KEYS, "renewal request")
    principal_raw = _exact_mapping(root["principal"], _PRINCIPAL_KEYS, "principal")
    policy_raw = _exact_mapping(root["policy"], _POLICY_KEYS, "policy")
    actor_raw = _exact_mapping(root["actor_capture"], _ACTOR_KEYS, "actor_capture")
    owner_raw = _exact_mapping(root["owner_successor"], _OWNER_KEYS, "owner_successor")
    profile_raw = _exact_mapping(root["profile"], _PROFILE_KEYS, "profile")
    try:
        principal = AuthenticatedAccountPrincipalV3(
            principal_id=_string(principal_raw, "principal_id"),
            user_id=_integer(principal_raw, "user_id"),
            authentication_context_hash=_string(principal_raw, "authentication_context_hash"),
            authenticated_at=_datetime(principal_raw, "authenticated_at"),
            valid_until=_datetime(principal_raw, "valid_until"),
        )
        policy = SingleOwnerPolicyBinding(
            policy_id=_string(policy_raw, "policy_id"),
            policy_version=_string(policy_raw, "policy_version"),
            expected_content_hash=_string(policy_raw, "expected_content_hash"),
            tenant_id=_string(policy_raw, "tenant_id"),
            owner_id=_string(policy_raw, "owner_id"),
            account_namespace=_string(policy_raw, "account_namespace"),
            account_id=_string(policy_raw, "account_id"),
        )
        actor_command = CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command(
            source_id=_string(actor_raw, "source_id"),
            source_version=_string(actor_raw, "source_version"),
            principal_id=_string(actor_raw, "principal_id"),
            user_id=_integer(actor_raw, "user_id"),
            authentication_context_id=_string(actor_raw, "authentication_context_id"),
            authentication_context_version=_string(actor_raw, "authentication_context_version"),
            expected_authentication_context_content_hash=_string(
                actor_raw, "expected_authentication_context_content_hash"
            ),
            user_source_id=_string(actor_raw, "user_source_id"),
            user_source_version=_string(actor_raw, "user_source_version"),
            expected_user_source_content_hash=_string(
                actor_raw, "expected_user_source_content_hash"
            ),
            rbac_source_id=_string(actor_raw, "rbac_source_id"),
            rbac_source_version=_string(actor_raw, "rbac_source_version"),
            expected_rbac_source_content_hash=_string(
                actor_raw, "expected_rbac_source_content_hash"
            ),
        )
        owner_command = SupersedeOwnerTenantAuthorityV3Command(
            authority_id=_string(owner_raw, "authority_id"),
            authority_version=_string(owner_raw, "authority_version"),
            predecessor_version=_string(owner_raw, "predecessor_version"),
            expected_predecessor_content_hash=_string(
                owner_raw, "expected_predecessor_content_hash"
            ),
            assignment_evidence_id=_string(owner_raw, "assignment_evidence_id"),
            assignment_evidence_version=_string(owner_raw, "assignment_evidence_version"),
            expected_assignment_evidence_content_hash=_string(
                owner_raw, "expected_assignment_evidence_content_hash"
            ),
        )
        actor_validity = _positive_seconds(root, "actor_validity_seconds")
        authority_validity = _positive_seconds(root, "authority_validity_seconds")
        minimum_window = _positive_seconds(root, "minimum_window_seconds")
        profile = RenewalProfileInput(
            environment=_string(profile_raw, "environment"),
            actor=_string(profile_raw, "actor"),
            reason=_string(profile_raw, "reason"),
            release_ref=_string(profile_raw, "release_ref"),
            expected_active_profile_id=_optional_string(profile_raw, "expected_active_profile_id"),
            expected_active_profile_version=_optional_integer(
                profile_raw, "expected_active_profile_version"
            ),
            expected_active_profile_hash=_optional_string(
                profile_raw, "expected_active_profile_hash"
            ),
            expected_active_snapshot_hash=_optional_string(
                profile_raw, "expected_active_snapshot_hash"
            ),
        )
        renewal = SystemAuditAuthorityRenewalRequest(
            actor_capture=actor_command,
            owner_successor=owner_command,
            minimum_window=minimum_window,
        )
        database_alias = _alias(root["database_alias"])
        recorder_service_id = _string(root, "actor_recorder_service_id")
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError("renewal request contains invalid typed fields") from error
    return SystemAuditAuthorityRenewalInput(
        database_alias=database_alias,
        actor_recorder_service_id=recorder_service_id,
        actor_validity_period=actor_validity,
        authority_validity_period=authority_validity,
        renewal=renewal,
        principal=principal,
        policy_binding=policy,
        profile=profile,
    )


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys at every JSON object level."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    """Reject NaN and Infinity JSON extensions."""

    del value
    raise ValueError("non-finite JSON number is not allowed")


def _exact_mapping(value: object, expected: frozenset[str], label: str) -> dict[str, object]:
    """Narrow one JSON object and require its exact key set."""

    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    mapping = cast(dict[str, object], value)
    if any(type(key) is not str for key in mapping) or frozenset(mapping) != expected:
        raise ValueError(f"{label} keys are not canonical")
    return mapping


def _string(values: dict[str, object], name: str) -> str:
    """Read one required JSON string."""

    value = values[name]
    if type(value) is not str:
        raise ValueError(f"{name} must be a string")
    value.encode("utf-8")
    return value


def _integer(values: dict[str, object], name: str) -> int:
    """Read one integer while rejecting booleans."""

    value = values[name]
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _positive_seconds(values: dict[str, object], name: str) -> timedelta:
    """Read one positive bounded duration in seconds."""

    seconds = _integer(values, name)
    if seconds <= 0 or seconds > 31_536_000:
        raise ValueError(f"{name} must be within one year")
    return timedelta(seconds=seconds)


def _datetime(values: dict[str, object], name: str) -> datetime:
    """Parse one timezone-aware ISO-8601 timestamp."""

    raw = _string(values, name)
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{name} must be ISO-8601") from error
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _optional_string(values: dict[str, object], name: str) -> str | None:
    """Read an optional string used by dry-run profile binding."""

    value = values[name]
    if value is None:
        return None
    return _string(values, name)


def _optional_integer(values: dict[str, object], name: str) -> int | None:
    """Read an optional integer used by dry-run profile binding."""

    value = values[name]
    if value is None:
        return None
    parsed = _integer(values, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _alias(value: object) -> str:
    """Validate one exact Django database alias."""

    if type(value) is not str or not value or value.strip() != value or len(value) > 64:
        raise ValueError("database_alias is not canonical")
    if any(character.isspace() for character in value):
        raise ValueError("database_alias is not canonical")
    return value


__all__ = [
    "RenewalProfileInput",
    "SystemAuditAuthorityRenewalInput",
    "parse_system_audit_authority_renewal_request",
]
