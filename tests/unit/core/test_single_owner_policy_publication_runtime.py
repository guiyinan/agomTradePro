"""Policy publication settings must come from one complete active snapshot."""

import pytest

from core.integration import single_owner_policy_publication_runtime as subject


def _payload():
    return {
        "schema_version": "account.single_owner_policy.publication_settings.v1",
        "owner_username": "designated-owner",
        "tenant_id": "test-tenant",
        "owner_id": "test-owner",
        "authorization_source_id": "test-declaration",
        "authorization_source_version": "v1",
        "authorization_content_hash": "a" * 64,
        "ttl_seconds": 300,
    }


def test_reads_one_complete_active_value_without_selecting_identity(monkeypatch):
    calls = []

    def read(**kwargs):
        calls.append(kwargs)
        return _payload()

    monkeypatch.setattr(subject.config_center_runtime, "get_active_runtime_value", read)
    settings = subject.get_active_single_owner_policy_publication_settings("staging")
    assert settings is not None
    assert settings.owner_username == "designated-owner"
    assert calls == [
        {
            "environment": "staging",
            "definition_key": "account.single_owner_policy.publication_settings",
        }
    ]
    assert "user_id" not in settings.to_payload()
    assert "authentication_context_hash" not in settings.to_payload()


@pytest.mark.parametrize("value", [None, {}, {"ttl_seconds": 300}, {**_payload(), "user_id": 1}])
def test_missing_or_partial_snapshot_has_no_default(monkeypatch, value):
    monkeypatch.setattr(
        subject.config_center_runtime, "get_active_runtime_value", lambda **_: value
    )
    assert subject.get_active_single_owner_policy_publication_settings("staging") is None


@pytest.mark.parametrize("environment", [None, True, "", " staging", "two environments"])
def test_invalid_environment_never_reads_configuration(monkeypatch, environment):
    def unexpected(**_):
        pytest.fail("invalid environment reached configuration")

    monkeypatch.setattr(subject.config_center_runtime, "get_active_runtime_value", unexpected)
    assert subject.get_active_single_owner_policy_publication_settings(environment) is None


def test_impossible_deadline_is_not_a_usable_snapshot(monkeypatch):
    value = {**_payload(), "ttl_seconds": 10**20}
    monkeypatch.setattr(
        subject.config_center_runtime, "get_active_runtime_value", lambda **_: value
    )
    assert subject.get_active_single_owner_policy_publication_settings("staging") is None
