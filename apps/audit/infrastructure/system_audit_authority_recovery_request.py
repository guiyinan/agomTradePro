"""Strict recovery envelope for an expired System Audit approval chain."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import NoReturn, cast

from apps.audit.infrastructure.system_audit_authority_renewal_request import (
    SystemAuditAuthorityRenewalInput,
    parse_system_audit_authority_renewal_request,
)

_ROOT_KEYS = frozenset({"renewal", "assignment_recovery"})
_RECOVERY_KEYS = frozenset(
    {
        "assignment_validity_seconds",
        "receipt_version",
        "subject_id",
        "subject_version",
        "evidence_version",
        "authority_id",
        "authority_version",
    }
)


@dataclass(frozen=True, slots=True)
class SystemAuditAuthorityRecoveryInput:
    """Bind one validated renewal base to append-only replacement identities."""

    renewal: SystemAuditAuthorityRenewalInput
    assignment_validity_period: timedelta
    receipt_version: str
    subject_id: str
    subject_version: str
    evidence_version: str
    authority_id: str
    authority_version: str


def parse_system_audit_authority_recovery_request(
    payload: bytes,
) -> SystemAuditAuthorityRecoveryInput:
    """Parse a strict recovery request while reusing the renewal source schema."""

    if type(payload) is not bytes or not payload:
        raise ValueError("recovery request payload must be non-empty UTF-8 JSON")
    try:
        parsed: object = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise ValueError("recovery request payload is invalid JSON") from error
    root = _mapping(parsed, _ROOT_KEYS, "recovery request")
    recovery = _mapping(root["assignment_recovery"], _RECOVERY_KEYS, "assignment recovery")
    renewal_payload = json.dumps(
        root["renewal"],
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    renewal = parse_system_audit_authority_renewal_request(renewal_payload)
    return SystemAuditAuthorityRecoveryInput(
        renewal=renewal,
        assignment_validity_period=_positive_seconds(recovery, "assignment_validity_seconds"),
        receipt_version=_token(recovery, "receipt_version"),
        subject_id=_token(recovery, "subject_id"),
        subject_version=_token(recovery, "subject_version"),
        evidence_version=_token(recovery, "evidence_version"),
        authority_id=_token(recovery, "authority_id"),
        authority_version=_token(recovery, "authority_version"),
    )


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    del value
    raise ValueError("non-finite JSON number is not allowed")


def _mapping(value: object, keys: frozenset[str], name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{name} must be a JSON object")
    result = cast(dict[str, object], value)
    if any(type(key) is not str for key in result) or frozenset(result) != keys:
        raise ValueError(f"{name} keys are not canonical")
    return result


def _token(values: dict[str, object], name: str) -> str:
    value = values[name]
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")
    return value


def _positive_seconds(values: dict[str, object], name: str) -> timedelta:
    value = values[name]
    if type(value) is not int or value <= 0 or value > 31_536_000:
        raise ValueError(f"{name} must be within one year")
    return timedelta(seconds=value)


__all__ = [
    "SystemAuditAuthorityRecoveryInput",
    "parse_system_audit_authority_recovery_request",
]
