"""Strict JSON boundary for the canonical Account actor capture request."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import NoReturn, cast

from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3Recorder,
    CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command,
)

_REQUEST_KEYS = frozenset({"command", "recorder_service_id", "validity_seconds", "database_alias"})
_COMMAND_KEYS = frozenset(
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


@dataclass(frozen=True, slots=True)
class ActorAuthorityCaptureRequest:
    """Typed, selector-only input for one canonical actor capture."""

    command: CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command
    recorder: AccountOwnerAssignmentActorAuthoritySourceV3Recorder
    validity_period: timedelta
    database_alias: str


def parse_actor_authority_capture_request(payload: bytes) -> ActorAuthorityCaptureRequest:
    """Parse one strict JSON capture request without touching Django or storage."""

    if type(payload) is not bytes or not payload:
        raise ValueError("capture request payload must be non-empty UTF-8 JSON")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("capture request payload must be valid UTF-8") from error
    try:
        parsed: object = json.loads(
            text,
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, ValueError, RecursionError) as error:
        raise ValueError("capture request payload is invalid JSON") from error
    request = _mapping(parsed, "capture request")
    if frozenset(request) != _REQUEST_KEYS:
        raise ValueError("capture request keys are not canonical")
    command = _mapping(request["command"], "capture command")
    if frozenset(command) != _COMMAND_KEYS:
        raise ValueError("capture command keys are not canonical")

    try:
        typed_command = CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command(
            source_id=_string(command, "source_id"),
            source_version=_string(command, "source_version"),
            principal_id=_string(command, "principal_id"),
            user_id=_integer(command, "user_id"),
            authentication_context_id=_string(command, "authentication_context_id"),
            authentication_context_version=_string(command, "authentication_context_version"),
            expected_authentication_context_content_hash=_string(
                command, "expected_authentication_context_content_hash"
            ),
            user_source_id=_string(command, "user_source_id"),
            user_source_version=_string(command, "user_source_version"),
            expected_user_source_content_hash=_string(command, "expected_user_source_content_hash"),
            rbac_source_id=_string(command, "rbac_source_id"),
            rbac_source_version=_string(command, "rbac_source_version"),
            expected_rbac_source_content_hash=_string(command, "expected_rbac_source_content_hash"),
        )
        recorder_service_id = _string(request, "recorder_service_id")
        recorder = AccountOwnerAssignmentActorAuthoritySourceV3Recorder(recorder_service_id)
        validity_seconds = _integer(request, "validity_seconds")
        if validity_seconds <= 0:
            raise ValueError("validity_seconds must be positive")
        validity_period = timedelta(seconds=validity_seconds)
        database_alias = _alias(request["database_alias"])
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError("capture request contains invalid typed fields") from error
    return ActorAuthorityCaptureRequest(
        command=typed_command,
        recorder=recorder,
        validity_period=validity_period,
        database_alias=database_alias,
    )


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build one object while rejecting duplicate keys at every JSON level."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    """Reject JSON extensions that encode non-finite numbers."""

    del value
    raise ValueError("non-finite JSON number is not allowed")


def _mapping(value: object, label: str) -> dict[str, object]:
    """Narrow a JSON object to a string-keyed object map."""

    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if type(key) is not str:
            raise ValueError(f"{label} keys must be strings")
        result[key] = cast(object, item)
    return result


def _string(values: dict[str, object], name: str) -> str:
    """Narrow one required JSON string and reject invalid Unicode text."""

    value = values[name]
    if type(value) is not str:
        raise ValueError(f"{name} must be a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{name} must be valid Unicode") from error
    return value


def _integer(values: dict[str, object], name: str) -> int:
    """Narrow one required JSON integer while rejecting booleans."""

    value = values[name]
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _alias(value: object) -> str:
    """Validate one exact bounded database alias."""

    if type(value) is not str:
        raise ValueError("database_alias must be a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("database_alias must be valid Unicode") from error
    if (
        not value
        or value.strip() != value
        or len(value) > 64
        or any(character.isspace() for character in value)
    ):
        raise ValueError("database_alias is not canonical")
    return value


__all__ = ["ActorAuthorityCaptureRequest", "parse_actor_authority_capture_request"]
