from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.single_owner_policy_publication_settings import (
    SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_SCHEMA_VERSION,
    SingleOwnerPolicyPublicationSettings,
    SingleOwnerPolicyPublicationSettingsError,
    decode_single_owner_policy_publication_settings,
)

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


def _settings(**changes: object) -> SingleOwnerPolicyPublicationSettings:
    """Build one complete valid source settings snapshot."""

    values: dict[str, object] = {
        "schema_version": SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_SCHEMA_VERSION,
        "owner_username": "configured-owner",
        "tenant_id": "tenant-a",
        "owner_id": "owner-a",
        "authorization_source_id": "owner-policy-declaration",
        "authorization_source_version": "v1",
        "authorization_content_hash": "a" * 64,
        "ttl_seconds": 300,
    }
    values.update(changes)
    return SingleOwnerPolicyPublicationSettings(**values)  # type: ignore[arg-type]


def test_settings_are_frozen_and_round_trip_as_one_closed_payload() -> None:
    settings = _settings()
    payload = settings.to_payload()

    assert payload == {
        "schema_version": SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_SCHEMA_VERSION,
        "owner_username": "configured-owner",
        "tenant_id": "tenant-a",
        "owner_id": "owner-a",
        "authorization_source_id": "owner-policy-declaration",
        "authorization_source_version": "v1",
        "authorization_content_hash": "a" * 64,
        "ttl_seconds": 300,
    }
    assert decode_single_owner_policy_publication_settings(payload) == settings
    assert settings.as_timedelta() == timedelta(seconds=300)
    assert settings.deadline_at(NOW) == NOW + timedelta(seconds=300)
    with pytest.raises(FrozenInstanceError):
        settings.ttl_seconds = 301  # type: ignore[misc]


def test_settings_have_no_authentication_or_policy_authority_fields() -> None:
    settings = _settings()
    field_names = {field.name for field in fields(SingleOwnerPolicyPublicationSettings)}

    assert field_names == {
        "schema_version",
        "owner_username",
        "tenant_id",
        "owner_id",
        "authorization_source_id",
        "authorization_source_version",
        "authorization_content_hash",
        "ttl_seconds",
    }
    assert "user_id" not in field_names
    assert "authentication_context_hash" not in field_names
    assert not hasattr(settings, "user_id")
    assert not hasattr(settings, "authentication_context_hash")


def test_large_ttl_is_safe_when_the_concrete_deadline_can_be_represented() -> None:
    settings = _settings(ttl_seconds=10**9)

    assert settings.deadline_at(NOW) == NOW + timedelta(seconds=10**9)


def test_ttl_deadline_checks_the_actual_datetime_boundary() -> None:
    settings = _settings(ttl_seconds=10**12)

    with pytest.raises(SingleOwnerPolicyPublicationSettingsError, match="datetime deadline"):
        settings.deadline_at(NOW)
    with pytest.raises(SingleOwnerPolicyPublicationSettingsError, match="datetime deadline"):
        _settings(ttl_seconds=1).deadline_at(datetime.max.replace(tzinfo=UTC))


@pytest.mark.parametrize("cutoff", [datetime(2026, 9, 11, 12), "cutoff", True])
def test_deadline_rejects_naive_or_non_datetime_cutoff(cutoff: object) -> None:
    with pytest.raises(SingleOwnerPolicyPublicationSettingsError, match="aware datetime"):
        _settings().deadline_at(cutoff)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"schema_version": SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_SCHEMA_VERSION},
        {**_settings().to_payload(), "unexpected": "value"},
        {key: value for key, value in _settings().to_payload().items() if key != "owner_id"},
    ],
)
def test_decoder_requires_exact_closed_field_set(payload: object) -> None:
    with pytest.raises(SingleOwnerPolicyPublicationSettingsError, match="incomplete or unknown"):
        decode_single_owner_policy_publication_settings(payload)


@pytest.mark.parametrize("value", [None, [], "payload", True])
def test_decoder_requires_an_exact_json_object(value: object) -> None:
    with pytest.raises(TypeError, match="exact JSON object"):
        decode_single_owner_policy_publication_settings(value)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("schema_version", "account.single_owner_policy.publication_settings.v2", "unsupported"),
        ("owner_username", "", "owner_username"),
        ("owner_username", "owner name", "owner_username"),
        ("owner_username", "x" * 151, "owner_username"),
        ("tenant_id", "", "tenant_id"),
        ("owner_id", "owner id", "owner_id"),
        ("authorization_source_id", " ", "authorization_source_id"),
        ("authorization_source_version", "x" * 193, "authorization_source_version"),
        ("authorization_content_hash", "A" * 64, "authorization_content_hash"),
        ("authorization_content_hash", "a" * 63, "authorization_content_hash"),
    ],
)
def test_settings_reject_invalid_schema_tokens_and_source_hash(
    field_name: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(SingleOwnerPolicyPublicationSettingsError, match=message):
        _settings(**{field_name: value})


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("schema_version", True),
        ("owner_username", True),
        ("tenant_id", 7),
        ("owner_id", True),
        ("authorization_source_id", None),
        ("authorization_source_version", False),
        ("authorization_content_hash", True),
        ("ttl_seconds", True),
        ("ttl_seconds", 0),
        ("ttl_seconds", -1),
        ("ttl_seconds", 1.5),
    ],
)
def test_settings_reject_exact_type_and_positive_ttl_violations(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(SingleOwnerPolicyPublicationSettingsError):
        _settings(**{field_name: value})


def test_extreme_ttl_is_rejected_before_any_timedelta_is_created() -> None:
    with pytest.raises(SingleOwnerPolicyPublicationSettingsError, match="timedelta range"):
        _settings(ttl_seconds=10**1000)


def test_source_hash_is_evidence_label_only_and_not_authentication() -> None:
    settings = _settings(
        authorization_source_id="declaration-file",
        authorization_source_version="2026-09-11",
    )

    assert settings.authorization_content_hash == "a" * 64
    assert set(settings.to_payload()) == {
        "schema_version",
        "owner_username",
        "tenant_id",
        "owner_id",
        "authorization_source_id",
        "authorization_source_version",
        "authorization_content_hash",
        "ttl_seconds",
    }
