"""Operator boundary tests for guarded decision-runtime activation."""

from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import CommandError, call_command

COMMAND_MODULE = "apps.config_center.management.commands.activate_decision_runtime_fail_closed"
RELEASE_REF = "a" * 40


def test_activation_command_is_dry_run_by_default(mocker) -> None:
    use_case = mocker.Mock()
    use_case.preview.return_value = SimpleNamespace(
        to_dict=lambda: {"ready": True, "release_ref": RELEASE_REF}
    )
    factory = mocker.patch(
        f"{COMMAND_MODULE}.make_decision_runtime_activation_use_case",
        return_value=use_case,
    )
    stdout = StringIO()

    call_command(
        "activate_decision_runtime_fail_closed",
        "--release-ref",
        RELEASE_REF,
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert payload["mode"] == "dry_run"
    assert payload["ready"] is True
    use_case.preview.assert_called_once_with(release_ref=RELEASE_REF)
    use_case.execute.assert_not_called()
    factory.assert_called_once_with()


def test_activation_command_requires_operator_for_execute() -> None:
    with pytest.raises(CommandError, match="operator"):
        call_command(
            "activate_decision_runtime_fail_closed",
            "--execute",
            "--release-ref",
            RELEASE_REF,
            stdout=StringIO(),
        )


def test_activation_command_executes_guarded_transition(mocker) -> None:
    use_case = mocker.Mock()
    use_case.execute.return_value = SimpleNamespace(
        to_dict=lambda: {
            "activated": True,
            "reblocked": False,
            "release_ref": RELEASE_REF,
        }
    )
    mocker.patch(
        f"{COMMAND_MODULE}.make_decision_runtime_activation_use_case",
        return_value=use_case,
    )
    stdout = StringIO()

    call_command(
        "activate_decision_runtime_fail_closed",
        "--execute",
        "--operator",
        "release-owner",
        "--release-ref",
        RELEASE_REF,
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert payload["mode"] == "execute"
    assert payload["activated"] is True
    use_case.execute.assert_called_once_with(
        release_ref=RELEASE_REF,
        changed_by="release-owner",
    )


def test_activation_command_returns_error_after_confirmed_reblock(mocker) -> None:
    use_case = mocker.Mock()
    use_case.execute.return_value = SimpleNamespace(
        to_dict=lambda: {
            "activated": False,
            "reblocked": True,
            "release_ref": RELEASE_REF,
        }
    )
    mocker.patch(
        f"{COMMAND_MODULE}.make_decision_runtime_activation_use_case",
        return_value=use_case,
    )

    with pytest.raises(CommandError, match="re-blocked"):
        call_command(
            "activate_decision_runtime_fail_closed",
            "--execute",
            "--operator",
            "release-owner",
            "--release-ref",
            RELEASE_REF,
            stdout=StringIO(),
        )
