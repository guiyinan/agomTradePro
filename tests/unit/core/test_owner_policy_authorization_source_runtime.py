"""Declaration lookup verifies bytes and selectors without granting authority."""

import base64
import hashlib
import json

import pytest

from apps.account.application.single_owner_policy_publication_settings import (
    decode_single_owner_policy_publication_settings,
)
from core.integration import owner_policy_authorization_source_runtime as subject


def _fixture(recorded_at="2020-01-01T00:00:00+00:00"):
    raw = json.dumps(
        {
            "schema": "sprint-owner-account-authorization.v1",
            "recorded_at": recorded_at,
            "source": {
                "kind": "interactive_user_declaration",
                "account_binding_answer": "Use the designated owner",
            },
            "owner_account": {
                "username": "designated-owner",
                "user_id": 42,
                "role": "project_owner_and_human_approver",
                "binding_basis": "explicit_user_designation",
            },
        }
    ).encode()
    digest = hashlib.sha256(raw).hexdigest()
    package = {
        "schema_version": "account.single_owner_policy.authorization_source.v1",
        "source_id": "test-declaration",
        "source_version": "v1",
        "content_hash": digest,
        "document_base64": base64.b64encode(raw).decode(),
    }
    settings = {
        "schema_version": "account.single_owner_policy.publication_settings.v1",
        "owner_username": "designated-owner",
        "tenant_id": "test-tenant",
        "owner_id": "test-owner",
        "authorization_source_id": "test-declaration",
        "authorization_source_version": "v1",
        "authorization_content_hash": digest,
        "ttl_seconds": 300,
    }
    return package, settings


def _read(monkeypatch, package, settings, environment="staging"):
    monkeypatch.setattr(
        subject.config_center_runtime, "get_active_runtime_value", lambda **_: package
    )
    return subject.get_active_owner_policy_authorization_source(
        environment=environment,
        settings=decode_single_owner_policy_publication_settings(settings),
    )


def test_exact_source_read_preserves_declaration_without_authentication(monkeypatch):
    package, settings = _fixture()
    calls = []

    def read(**kwargs):
        calls.append(kwargs)
        return package

    monkeypatch.setattr(subject.config_center_runtime, "get_active_runtime_value", read)
    source = subject.get_active_owner_policy_authorization_source(
        environment="staging",
        settings=decode_single_owner_policy_publication_settings(settings),
    )
    assert source is not None
    assert source.to_payload() == package
    assert source.declared_user_id == 42
    assert calls == [
        {"environment": "staging", "definition_key": subject.OWNER_POLICY_AUTHORIZATION_SOURCE_KEY}
    ]
    assert not hasattr(source, "is_authenticated")


@pytest.mark.parametrize(
    "field,value",
    [
        ("authorization_source_id", "another"),
        ("authorization_source_version", "v2"),
        ("authorization_content_hash", "a" * 64),
        ("owner_username", "another-owner"),
    ],
)
def test_selector_mismatch_is_unusable(monkeypatch, field, value):
    package, settings = _fixture()
    settings[field] = value
    assert _read(monkeypatch, package, settings) is None


@pytest.mark.parametrize("package", [None, {}, {"source_id": "test-declaration"}])
def test_missing_source_has_no_fallback(monkeypatch, package):
    _, settings = _fixture()
    assert _read(monkeypatch, package, settings) is None


def test_tampered_document_is_rejected(monkeypatch):
    package, settings = _fixture()
    package["document_base64"] = base64.b64encode(b"{}").decode()
    assert _read(monkeypatch, package, settings) is None


def test_future_declaration_is_not_yet_usable(monkeypatch):
    package, settings = _fixture("9999-01-01T00:00:00+00:00")
    assert _read(monkeypatch, package, settings) is None


@pytest.mark.parametrize("environment", [None, True, "", " staging", "two environments"])
def test_invalid_environment_never_reads(monkeypatch, environment):
    _, settings = _fixture()

    def unexpected(**_):
        pytest.fail("invalid environment reached configuration")

    monkeypatch.setattr(subject.config_center_runtime, "get_active_runtime_value", unexpected)
    assert (
        subject.get_active_owner_policy_authorization_source(
            environment=environment,
            settings=decode_single_owner_policy_publication_settings(settings),
        )
        is None
    )


def test_unexpected_programming_error_propagates(monkeypatch):
    _, settings = _fixture()

    def unexpected(**_):
        raise AssertionError("reader defect")

    monkeypatch.setattr(subject.config_center_runtime, "get_active_runtime_value", unexpected)
    with pytest.raises(AssertionError, match="reader defect"):
        subject.get_active_owner_policy_authorization_source(
            environment="staging",
            settings=decode_single_owner_policy_publication_settings(settings),
        )
