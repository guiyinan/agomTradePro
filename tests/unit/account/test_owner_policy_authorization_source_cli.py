"""Source import preserves exact bytes and never supplies authentication."""

import base64
import hashlib
import json
from io import StringIO

import pytest
from django.core.management.base import CommandError

from apps.account.management.commands import import_owner_policy_authorization_source as subject


def _options(tmp_path):
    raw = (
        b"\xef\xbb\xbf"
        + json.dumps(
            {
                "schema": "sprint-owner-account-authorization.v1",
                "recorded_at": "2020-01-01T00:00:00+00:00",
                "source": {
                    "kind": "interactive_user_declaration",
                    "account_binding_answer": "Use owner",
                },
                "owner_account": {
                    "username": "owner",
                    "user_id": 42,
                    "role": "project_owner_and_human_approver",
                    "binding_basis": "explicit_user_designation",
                },
            }
        ).encode()
        + b"\r\n"
    )
    path = tmp_path / "declaration.json"
    path.write_bytes(raw)
    return {
        "file": str(path),
        "expected_sha256": hashlib.sha256(raw).hexdigest(),
        "source_id": "declaration",
        "source_version": "v1",
        "environment": "staging",
        "actor": "test-operator",
        "reason": "Import declaration",
    }, raw


def test_import_preserves_raw_bytes_and_only_writes_source(monkeypatch, tmp_path):
    options, raw = _options(tmp_path)
    calls = []

    def activate(**kwargs):
        calls.append(kwargs)
        return {"profile_version": 2}

    monkeypatch.setattr(subject, "activate_runtime_profile_patch", activate)
    output = StringIO()
    subject.Command(stdout=output).handle(**options)
    assert len(calls) == 1
    assert set(calls[0]["patch"]) == {subject.OWNER_POLICY_AUTHORIZATION_SOURCE_KEY}
    package = calls[0]["patch"][subject.OWNER_POLICY_AUTHORIZATION_SOURCE_KEY]
    assert base64.b64decode(package["document_base64"]) == raw
    assert package["content_hash"] == options["expected_sha256"]
    assert calls[0]["bootstrap_values"] is None
    result = json.loads(output.getvalue())
    assert result["policy_published"] is False
    assert result["authority_granted"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_sha256", "a" * 64),
        ("source_id", ""),
        ("source_version", "v 1"),
        ("actor", ""),
        ("environment", " staging"),
    ],
)
def test_invalid_import_never_activates(monkeypatch, tmp_path, field, value):
    options, _ = _options(tmp_path)
    options[field] = value
    monkeypatch.setattr(
        subject, "activate_runtime_profile_patch", lambda **_: pytest.fail("unexpected write")
    )
    with pytest.raises(CommandError):
        subject.Command().handle(**options)


def test_oversized_file_never_activates(monkeypatch, tmp_path):
    options, raw = _options(tmp_path)
    raw += b" " * (64 * 1024)
    from pathlib import Path

    Path(options["file"]).write_bytes(raw)
    options["expected_sha256"] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(
        subject, "activate_runtime_profile_patch", lambda **_: pytest.fail("unexpected write")
    )
    with pytest.raises(CommandError):
        subject.Command().handle(**options)


def test_missing_file_reports_command_error(tmp_path):
    options, _ = _options(tmp_path)
    options["file"] = str(tmp_path / "missing.json")
    with pytest.raises(CommandError):
        subject.Command().handle(**options)
