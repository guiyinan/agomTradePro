"""Strict codecs for policy-benchmark methodology bundle activation ledgers."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.portfolio.domain.policy_benchmark_definition import PolicyBenchmarkMethodologyRef
from apps.portfolio.domain.policy_benchmark_methodology_activation import (
    PolicyBenchmarkMethodologyActivationActor,
    PolicyBenchmarkMethodologyActivationSubject,
    PolicyBenchmarkMethodologyBundle,
    PolicyBenchmarkMethodologyBundleActivation,
)


class PolicyBenchmarkMethodologyActivationCodecError(ValueError):
    """A stored methodology activation payload is malformed or non-canonical."""


def encode_policy_benchmark_methodology_activation_subject(
    value: PolicyBenchmarkMethodologyActivationSubject,
) -> dict[str, object]:
    """Encode one complete immutable methodology activation subject."""

    return value.to_payload()


def decode_policy_benchmark_methodology_activation_subject(
    payload: object,
) -> PolicyBenchmarkMethodologyActivationSubject:
    """Restore and revalidate one exact canonical methodology subject."""

    data = _mapping(
        payload,
        {
            "subject_id",
            "subject_version",
            "definition_id",
            "definition_version",
            "definition_identity_hash",
            "definition_content_hash",
            "definition_recorded_at",
            "definition_valid_until",
            "bundle",
            "requested_by",
            "requested_at",
            "valid_until",
            "supersedes_activation_hash",
            "content_hash",
            "clock_source",
        },
    )
    try:
        value = PolicyBenchmarkMethodologyActivationSubject(
            subject_id=_string(data["subject_id"]),
            subject_version=_string(data["subject_version"]),
            definition_id=_string(data["definition_id"]),
            definition_version=_string(data["definition_version"]),
            definition_identity_hash=_string(data["definition_identity_hash"]),
            definition_content_hash=_string(data["definition_content_hash"]),
            definition_recorded_at=_datetime(data["definition_recorded_at"]),
            definition_valid_until=_datetime(data["definition_valid_until"]),
            bundle=_bundle(data["bundle"]),
            requested_by=_actor(data["requested_by"]),
            requested_at=_datetime(data["requested_at"]),
            valid_until=_datetime(data["valid_until"]),
            supersedes_activation_hash=_optional_string(data["supersedes_activation_hash"]),
            content_hash=_string(data["content_hash"]),
            clock_source=_string(data["clock_source"]),
        )
    except (PolicyBenchmarkMethodologyActivationCodecError, TypeError, ValueError) as error:
        raise PolicyBenchmarkMethodologyActivationCodecError(
            "methodology activation subject is invalid"
        ) from error
    if payload != encode_policy_benchmark_methodology_activation_subject(value):
        raise PolicyBenchmarkMethodologyActivationCodecError(
            "methodology activation subject is non-canonical"
        )
    return value


def encode_policy_benchmark_methodology_activation(
    value: PolicyBenchmarkMethodologyBundleActivation,
) -> dict[str, object]:
    """Encode an activation without its four derived authority markers."""

    derived = {
        "activates_configuration_bundle",
        "daily_valuation_authority",
        "broker_execution_authority",
        "must_not_execute",
    }
    return {key: item for key, item in value.to_payload().items() if key not in derived}


def decode_policy_benchmark_methodology_activation(
    payload: object,
) -> PolicyBenchmarkMethodologyBundleActivation:
    """Restore and revalidate one exact canonical methodology activation."""

    data = _mapping(
        payload,
        {
            "owner",
            "capability",
            "artifact_type",
            "schema",
            "activation_id",
            "activation_version",
            "subject",
            "approved_by",
            "issued_at",
            "valid_until",
            "permission",
            "clock_source",
            "content_hash",
        },
    )
    try:
        value = PolicyBenchmarkMethodologyBundleActivation(
            activation_id=_string(data["activation_id"]),
            activation_version=_string(data["activation_version"]),
            subject=decode_policy_benchmark_methodology_activation_subject(data["subject"]),
            approved_by=_actor(data["approved_by"]),
            issued_at=_datetime(data["issued_at"]),
            valid_until=_datetime(data["valid_until"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            capability=_string(data["capability"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            clock_source=_string(data["clock_source"]),
        )
    except (PolicyBenchmarkMethodologyActivationCodecError, TypeError, ValueError) as error:
        raise PolicyBenchmarkMethodologyActivationCodecError(
            "methodology bundle activation is invalid"
        ) from error
    if payload != encode_policy_benchmark_methodology_activation(value):
        raise PolicyBenchmarkMethodologyActivationCodecError(
            "methodology bundle activation is non-canonical"
        )
    return value


def _bundle(payload: object) -> PolicyBenchmarkMethodologyBundle:
    data = _mapping(payload, {"methodology_refs", "valid_until", "bundle_hash"})
    raw_refs = data["methodology_refs"]
    if type(raw_refs) is not list:
        raise PolicyBenchmarkMethodologyActivationCodecError(
            "methodology_refs must be a canonical list"
        )
    return PolicyBenchmarkMethodologyBundle(
        methodology_refs=tuple(_reference(item) for item in raw_refs),
        valid_until=_datetime(data["valid_until"]),
        bundle_hash=_string(data["bundle_hash"]),
    )


def _reference(payload: object) -> PolicyBenchmarkMethodologyRef:
    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "artifact_id",
            "artifact_version",
            "content_hash",
            "recorded_at",
            "valid_until",
        },
    )
    return PolicyBenchmarkMethodologyRef(
        owner=_string(data["owner"]),
        artifact_type=_string(data["artifact_type"]),
        artifact_id=_string(data["artifact_id"]),
        artifact_version=_string(data["artifact_version"]),
        content_hash=_string(data["content_hash"]),
        recorded_at=_datetime(data["recorded_at"]),
        valid_until=_datetime(data["valid_until"]),
    )


def _actor(payload: object) -> PolicyBenchmarkMethodologyActivationActor:
    data = _mapping(
        payload,
        {"actor_id", "user_id", "role", "kind", "is_staff", "authentication_source"},
    )
    return PolicyBenchmarkMethodologyActivationActor(
        actor_id=_string(data["actor_id"]),
        user_id=_positive_integer(data["user_id"]),
        role=_string(data["role"]),
        kind=_string(data["kind"]),
        is_staff=_boolean(data["is_staff"]),
        authentication_source=_string(data["authentication_source"]),
    )


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise PolicyBenchmarkMethodologyActivationCodecError(
            "methodology activation payload shape is invalid"
        )
    return cast(dict[str, object], payload)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _positive_integer(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise TypeError("expected positive integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("expected boolean")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise ValueError("datetime must use canonical UTC Z format")
    result = datetime.fromisoformat(text[:-1] + "+00:00")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return result


__all__ = [
    "PolicyBenchmarkMethodologyActivationCodecError",
    "decode_policy_benchmark_methodology_activation",
    "decode_policy_benchmark_methodology_activation_subject",
    "encode_policy_benchmark_methodology_activation",
    "encode_policy_benchmark_methodology_activation_subject",
]
