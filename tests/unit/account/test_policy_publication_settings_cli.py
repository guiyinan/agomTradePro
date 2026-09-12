"""The management command configures source references without claiming approval."""

import json
from io import StringIO

import pytest
from django.core.management.base import CommandError

from apps.account.management.commands import (
    activate_single_owner_policy_publication_settings as subject,
)


def _options():
    return {
        "environment": "staging",
        "actor": "test-operator",
        "reason": "Configure test publication",
        "owner_username": "designated-owner",
        "tenant_id": "test-tenant",
        "owner_id": "test-owner",
        "authorization_source_id": "declaration",
        "authorization_source_version": "v1",
        "authorization_content_hash": "a" * 64,
        "ttl_seconds": 300,
    }


def test_command_writes_only_publication_settings_and_claims_no_authority(monkeypatch):
    calls = []

    def activate(**kwargs):
        calls.append(kwargs)
        return {"profile_version": 2}

    monkeypatch.setattr(subject, "activate_runtime_profile_patch", activate)
    output = StringIO()
    subject.Command(stdout=output).handle(**_options())
    assert len(calls) == 1
    assert set(calls[0]["patch"]) == {"account.single_owner_policy.publication_settings"}
    payload = calls[0]["patch"]["account.single_owner_policy.publication_settings"]
    assert payload["owner_username"] == "designated-owner"
    assert "user_id" not in payload and "authentication_context_hash" not in payload
    assert calls[0]["bootstrap_values"] is None
    response = json.loads(output.getvalue())
    assert response["policy_published"] is False
    assert response["authority_granted"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("authorization_content_hash", ""),
        ("owner_username", ""),
        ("ttl_seconds", True),
        ("ttl_seconds", 10**20),
        ("actor", ""),
        ("environment", " staging"),
    ],
)
def test_invalid_settings_do_not_reach_activation(monkeypatch, field, value):
    def unexpected(**_):
        pytest.fail("invalid settings reached activation")

    monkeypatch.setattr(subject, "activate_runtime_profile_patch", unexpected)
    with pytest.raises(CommandError):
        subject.Command().handle(**{**_options(), field: value})


def test_parser_requires_all_values_without_identity_or_mode_flags():
    command = subject.Command()
    parser = command.create_parser("manage.py", "activate_single_owner_policy_publication_settings")
    flags = {option for action in parser._actions for option in action.option_strings}
    assert "--owner-username" in flags and "--authorization-content-hash" in flags
    assert "--user-id" not in flags and "--mode" not in flags
