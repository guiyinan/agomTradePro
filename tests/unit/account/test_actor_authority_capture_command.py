"""Explicit canonical capture input and default no-write command behavior."""

import json
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.account.infrastructure.account_actor_authority_capture_request import (
    parse_actor_authority_capture_request,
)
from tests.unit.account.test_account_owner_assignment_actor_authority_source_v3 import _source
from tests.unit.account.test_account_owner_assignment_actor_authority_source_v3_application import (
    _command,
)


def payload() -> dict[str, object]:
    return {
        "command": asdict(_command()),
        "recorder_service_id": "account-attestor",
        "validity_seconds": 300,
        "database_alias": "authority",
    }


def test_parser_retains_exact_selector_recorder_alias_and_explicit_ttl() -> None:
    parsed = parse_actor_authority_capture_request(json.dumps(payload()).encode())
    assert parsed.command == _command()
    assert parsed.recorder.service_id == "account-attestor"
    assert parsed.validity_period.total_seconds() == 300
    assert parsed.database_alias == "authority"


@pytest.mark.parametrize(
    "field,value",
    [
        ("validity_seconds", True),
        ("validity_seconds", 0),
        ("validity_seconds", 0.5),
        ("validity_seconds", 10**100),
        ("database_alias", " default"),
        ("database_alias", ""),
        ("recorder_service_id", "bad identity"),
    ],
)
def test_invalid_execution_parameters_fail_before_composition(field: str, value: object) -> None:
    raw = payload()
    raw[field] = value
    with pytest.raises((ValueError, TypeError)):
        parse_actor_authority_capture_request(json.dumps(raw).encode())


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b"null",
        b"\xff",
        b'{"command":1,"command":2}',
        b'{"validity_seconds":NaN}',
        b'{"validity_seconds":Infinity}',
    ],
)
def test_noncanonical_json_is_rejected(raw: bytes) -> None:
    with pytest.raises((ValueError, TypeError)):
        parse_actor_authority_capture_request(raw)


def test_unknown_fields_and_boolean_user_id_are_rejected() -> None:
    raw = payload()
    raw["allow_all"] = True
    with pytest.raises(ValueError):
        parse_actor_authority_capture_request(json.dumps(raw).encode())
    raw = payload()
    command = asdict(_command())
    command["user_id"] = True
    raw["command"] = command
    with pytest.raises((ValueError, TypeError)):
        parse_actor_authority_capture_request(json.dumps(raw).encode())


def test_default_command_never_builds_a_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.account.management.commands import capture_account_actor_authority as module

    path = tmp_path / "request.json"
    path.write_text(json.dumps(payload()), encoding="utf-8")
    factory = Mock(side_effect=AssertionError("dry-run attempted composition"))
    monkeypatch.setattr(module, "build_account_actor_authority_capture", factory)
    output = StringIO()
    call_command("capture_account_actor_authority", input=str(path), stdout=output)
    result = json.loads(output.getvalue())
    assert result["outcome"] == "noop"
    assert result["mode"] == "dry_run"
    assert result["upstream_authority_verified"] is False
    assert result["capture_executed"] is False
    factory.assert_not_called()


def test_execute_calls_only_canonical_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.account.management.commands import capture_account_actor_authority as module

    path = tmp_path / "request.json"
    path.write_text(json.dumps(payload()), encoding="utf-8")
    factory = Mock()
    source = _source()
    factory.return_value.execute.return_value = source
    monkeypatch.setattr(module, "build_account_actor_authority_capture", factory)
    output = StringIO()
    call_command("capture_account_actor_authority", input=str(path), execute=True, stdout=output)
    result = json.loads(output.getvalue())
    assert result["outcome"] == "success"
    assert result["capture_executed"] is True
    # The canonical writer can replay a stored winner without checking live inputs.
    assert result["upstream_authority_verified"] is False
    assert result["reason"] == "canonical_capture_returned_current_authority_not_checked"
    assert result["content_hash"] == source.content_hash
    assert result["runtime_enabled"] is False
    factory.return_value.execute.assert_called_once_with(_command())
    assert factory.call_args.kwargs["using"] == "authority"
    assert factory.call_args.kwargs["recorder_service_id"] == "account-attestor"


def test_invalid_request_is_command_error_without_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.account.management.commands import capture_account_actor_authority as module

    path = tmp_path / "request.json"
    path.write_text("{}", encoding="utf-8")
    factory = Mock()
    monkeypatch.setattr(module, "build_account_actor_authority_capture", factory)
    with pytest.raises(CommandError):
        call_command("capture_account_actor_authority", input=str(path), execute=True)
    factory.assert_not_called()
