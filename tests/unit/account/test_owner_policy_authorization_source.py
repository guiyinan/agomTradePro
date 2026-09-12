"""Tests for the strict, declaration-only owner policy source package."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from apps.account.application.owner_policy_authorization_source import (
    OWNER_POLICY_AUTHORIZATION_SOURCE_DOCUMENT_SCHEMA,
    OWNER_POLICY_AUTHORIZATION_SOURCE_MAX_DOCUMENT_BYTES,
    OWNER_POLICY_AUTHORIZATION_SOURCE_SCHEMA_VERSION,
    OwnerPolicyAuthorizationSource,
    OwnerPolicyAuthorizationSourceError,
    decode_owner_policy_authorization_source,
)

NOW = datetime(2026, 9, 10, 11, 5, 1, 917705, tzinfo=UTC)


def _document_payload() -> dict[str, object]:
    """Build one synthetic declaration with the required source facts."""

    return {
        "schema": OWNER_POLICY_AUTHORIZATION_SOURCE_DOCUMENT_SCHEMA,
        "recorded_at": NOW.isoformat(),
        "source": {
            "kind": "interactive_user_declaration",
            "account_binding_answer": "yes, use the designated owner",
            "informational": {"signature_present": False},
        },
        "owner_account": {
            "username": "owner-test",
            "user_id": 17,
            "role": "project_owner_and_human_approver",
            "binding_basis": "explicit_user_designation",
        },
        "informational": {"purpose": "source-content fixture"},
    }


def _raw_document(
    payload: dict[str, object] | None = None,
    *,
    bom: bool = False,
) -> bytes:
    """Serialize a declaration fixture without changing its supplied bytes."""

    value = _document_payload() if payload is None else payload
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return b"\xef\xbb\xbf" + raw if bom else raw


def _package(
    raw: bytes | None = None,
    *,
    source_id: object = "source-fixture",
    source_version: object = "2026-09-10",
    content_hash: object | None = None,
    document_base64: object | None = None,
) -> dict[str, object]:
    """Build an outer package while preserving room for invalid-value tests."""

    document = _raw_document() if raw is None else raw
    encoded = base64.b64encode(document).decode("ascii")
    return {
        "schema_version": OWNER_POLICY_AUTHORIZATION_SOURCE_SCHEMA_VERSION,
        "source_id": source_id,
        "source_version": source_version,
        "content_hash": (
            hashlib.sha256(document).hexdigest() if content_hash is None else content_hash
        ),
        "document_base64": encoded if document_base64 is None else document_base64,
    }


def _source(
    raw: bytes | None = None,
    *,
    source_id: object = "source-fixture",
    source_version: object = "2026-09-10",
    content_hash: object | None = None,
    document_base64: object | None = None,
) -> OwnerPolicyAuthorizationSource:
    """Decode one fixture package through the public boundary."""

    return decode_owner_policy_authorization_source(
        _package(
            raw,
            source_id=source_id,
            source_version=source_version,
            content_hash=content_hash,
            document_base64=document_base64,
        )
    )


def test_valid_package_roundtrips_and_exposes_only_declaration_facts() -> None:
    source = _source()

    assert source.schema_version == OWNER_POLICY_AUTHORIZATION_SOURCE_SCHEMA_VERSION
    assert source.owner_username == "owner-test"
    assert source.declared_user_id == 17
    assert source.declared_at == NOW
    assert source.to_payload() == _package()
    assert decode_owner_policy_authorization_source(source.to_payload()) == source
    assert {field.name for field in fields(source)} == {
        "source_id",
        "source_version",
        "content_hash",
        "document_base64",
    }
    for forbidden_name in (
        "is_authenticated",
        "is_staff",
        "is_superuser",
        "signature_verified",
        "permission",
    ):
        assert not hasattr(source, forbidden_name)


def test_real_declaration_file_is_checked_as_content_only() -> None:
    path = (
        Path(__file__).parents[3]
        / "docs"
        / "deployment"
        / ("sprint-owner-admin-authorization-2026-09-10.json")
    )
    source = _source(path.read_bytes())

    assert source.owner_username
    assert type(source.declared_user_id) is int
    assert source.declared_user_id > 0
    assert source.declared_at.tzinfo is not None
    assert source.declared_at.utcoffset() is not None


def test_informational_auth_and_database_fields_are_not_authentication() -> None:
    payload = _document_payload()
    source_payload = cast(dict[str, object], payload["source"])
    source_payload["cryptographic_signature_present"] = True
    owner_payload = cast(dict[str, object], payload["owner_account"])
    owner_payload.update(
        {
            "is_active": False,
            "is_staff": False,
            "is_superuser": False,
            "current_database_observed_at": "not-an-authentication-proof",
        }
    )

    source = _source(_raw_document(payload))

    assert source.owner_username == "owner-test"
    assert not hasattr(source, "is_staff")


def test_bom_is_part_of_the_hash_and_utf8_document_is_accepted() -> None:
    source = _source(_raw_document(bom=True))

    assert source.owner_username == "owner-test"
    assert source.declared_at == NOW


def test_source_is_frozen_and_to_payload_rechecks_a_tampered_seal() -> None:
    source = _source()

    with pytest.raises(FrozenInstanceError):
        source.source_id = "changed"  # type: ignore[misc]

    object.__setattr__(source, "content_hash", "0" * 64)
    with pytest.raises(OwnerPolicyAuthorizationSourceError, match="content_hash"):
        source.to_payload()


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_outer_package_has_exactly_five_fields(mutation: str) -> None:
    payload = _package()
    if mutation == "missing":
        payload.pop("source_id")
    else:
        payload["unexpected"] = "reject"

    with pytest.raises(OwnerPolicyAuthorizationSourceError, match="fields"):
        decode_owner_policy_authorization_source(payload)


@pytest.mark.parametrize(
    "value",
    [None, [], "wrong", True],
)
def test_outer_package_must_be_an_exact_object(value: object) -> None:
    with pytest.raises(OwnerPolicyAuthorizationSourceError, match="exact JSON object"):
        decode_owner_policy_authorization_source(value)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("schema_version", True),
        ("schema_version", "other.v1"),
        ("source_id", True),
        ("source_id", ""),
        ("source_id", "source id"),
        ("source_id", "x" * 193),
        ("source_version", None),
        ("source_version", "version\n1"),
        ("source_version", "x" * 193),
        ("content_hash", True),
        ("content_hash", "A" * 64),
        ("content_hash", "a" * 63),
        ("document_base64", True),
    ],
)
def test_outer_package_rejects_exact_type_token_and_digest_substitution(
    field_name: str,
    value: object,
) -> None:
    payload = _package()
    payload[field_name] = value

    with pytest.raises(OwnerPolicyAuthorizationSourceError):
        decode_owner_policy_authorization_source(payload)


def test_wrong_explicit_hash_is_rejected_without_auto_sealing() -> None:
    with pytest.raises(OwnerPolicyAuthorizationSourceError, match="does not match"):
        _source(content_hash="0" * 64)

    with pytest.raises(OwnerPolicyAuthorizationSourceError, match="digest"):
        _source(content_hash="")


@pytest.mark.parametrize(
    "encoded",
    [
        "***",
        base64.b64encode(b"{}").decode("ascii").rstrip("="),
        base64.b64encode(b"{}").decode("ascii") + "\n",
        base64.b64encode(b"\xfb\xff").decode("ascii").replace("+", "-").replace("/", "_"),
    ],
)
def test_document_base64_must_be_canonical_standard_base64(encoded: str) -> None:
    raw = b"{}"
    if encoded.endswith("_"):
        raw = b"\xfb\xff"
    payload = _package(raw, document_base64=encoded)

    with pytest.raises(OwnerPolicyAuthorizationSourceError, match="base64"):
        decode_owner_policy_authorization_source(payload)


def test_document_size_and_utf8_are_checked_after_base64_decode() -> None:
    oversized = b"x" * (OWNER_POLICY_AUTHORIZATION_SOURCE_MAX_DOCUMENT_BYTES + 1)
    with pytest.raises(OwnerPolicyAuthorizationSourceError, match="size"):
        _source(oversized)

    invalid_utf8 = b"\xff"
    with pytest.raises(OwnerPolicyAuthorizationSourceError, match="UTF-8"):
        _source(invalid_utf8)


@pytest.mark.parametrize(
    ("section", "field_name", "value"),
    [
        ("__top__", "schema", "wrong.v1"),
        ("__top__", "recorded_at", "2026-09-10T11:05:01.917705"),
        ("__top__", "recorded_at", True),
        ("source", "kind", "server_assertion"),
        ("source", "account_binding_answer", "   "),
        ("source", "account_binding_answer", 1),
        ("owner_account", "username", ""),
        ("owner_account", "username", "owner name"),
        ("owner_account", "username", "x" * 151),
        ("owner_account", "user_id", True),
        ("owner_account", "user_id", 0),
        ("owner_account", "binding_basis", "configuration"),
        ("owner_account", "role", "administrator"),
    ],
)
def test_declaration_required_facts_fail_closed(
    section: str,
    field_name: str,
    value: object,
) -> None:
    payload = _document_payload()
    if section == "__top__":
        payload[field_name] = value
    else:
        section_value = cast(dict[str, object], payload[section])
        section_value[field_name] = value

    with pytest.raises(OwnerPolicyAuthorizationSourceError):
        _source(_raw_document(payload))


@pytest.mark.parametrize(
    "raw",
    [
        (
            b'{"schema":"sprint-owner-account-authorization.v1",'
            b'"schema":"sprint-owner-account-authorization.v1",'
            b'"recorded_at":"2026-09-10T11:05:01.917705+00:00",'
            b'"source":{"kind":"interactive_user_declaration",'
            b'"account_binding_answer":"yes"},'
            b'"owner_account":{"username":"owner-test","user_id":17,'
            b'"role":"project_owner_and_human_approver",'
            b'"binding_basis":"explicit_user_designation"}}'
        ),
        (
            b'{"schema":"sprint-owner-account-authorization.v1",'
            b'"recorded_at":"2026-09-10T11:05:01.917705+00:00",'
            b'"source":{"kind":"interactive_user_declaration",'
            b'"kind":"interactive_user_declaration",'
            b'"account_binding_answer":"yes"},'
            b'"owner_account":{"username":"owner-test","user_id":17,'
            b'"role":"project_owner_and_human_approver",'
            b'"binding_basis":"explicit_user_designation"}}'
        ),
        (
            b'{"schema":"sprint-owner-account-authorization.v1",'
            b'"recorded_at":"2026-09-10T11:05:01.917705+00:00",'
            b'"source":{"kind":"interactive_user_declaration",'
            b'"account_binding_answer":"yes"},'
            b'"owner_account":{"username":"owner-test","username":"other",'
            b'"user_id":17,"role":"project_owner_and_human_approver",'
            b'"binding_basis":"explicit_user_designation"}}'
        ),
    ],
)
def test_nested_and_top_level_duplicate_json_keys_are_rejected(raw: bytes) -> None:
    with pytest.raises(OwnerPolicyAuthorizationSourceError, match="duplicate"):
        _source(raw)


def test_nonfinite_json_number_is_not_accepted_as_informational_content() -> None:
    raw = (
        b'{"schema":"sprint-owner-account-authorization.v1",'
        b'"recorded_at":"2026-09-10T11:05:01.917705+00:00",'
        b'"source":{"kind":"interactive_user_declaration",'
        b'"account_binding_answer":"yes"},'
        b'"owner_account":{"username":"owner-test","user_id":17,'
        b'"role":"project_owner_and_human_approver",'
        b'"binding_basis":"explicit_user_designation"},"extra":NaN}'
    )

    with pytest.raises(OwnerPolicyAuthorizationSourceError, match="non-finite"):
        _source(raw)


def test_json_document_must_have_an_object_root() -> None:
    raw = b"[]"

    with pytest.raises(OwnerPolicyAuthorizationSourceError, match="JSON object"):
        _source(raw)
