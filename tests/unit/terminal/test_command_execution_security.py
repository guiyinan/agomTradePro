"""Security and failure-boundary tests for legacy Terminal command execution."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.terminal.application.repository_provider import TerminalApiRequestError
from apps.terminal.application.services import CommandExecutionService
from apps.terminal.application.use_cases import (
    ExecuteCommandRequest,
    ExecuteCommandUseCase,
)
from apps.terminal.domain.entities import CommandType, TerminalCommand
from apps.terminal.domain.exceptions import (
    TerminalAuditPersistenceError,
    TerminalCommandExecutionError,
)


def _api_command(
    *,
    endpoint: str = "https://example.test/data",
    method: str = "GET",
    response_filter: str | None = None,
) -> TerminalCommand:
    return TerminalCommand(
        id="command-1",
        name="secure_api",
        description="secure API command",
        command_type=CommandType.API,
        api_endpoint=endpoint,
        api_method=method,
        response_jq_filter=response_filter,
        requires_mcp=False,
    )


def test_external_request_failure_does_not_expose_provider_details(caplog):
    client = MagicMock()
    client.request_json.side_effect = TerminalApiRequestError(
        "postgresql://admin:raw-secret@example.test/prod"
    )

    with (
        patch(
            "apps.terminal.application.services.get_terminal_command_http_client",
            return_value=client,
        ),
        caplog.at_level(logging.WARNING),
        pytest.raises(TerminalCommandExecutionError) as raised,
    ):
        CommandExecutionService().execute_api_command(_api_command(), {})

    assert str(raised.value) == "terminal_external_api_failed"
    assert "raw-secret" not in caplog.text
    assert "postgresql://" not in caplog.text


def test_prompt_failure_does_not_expose_agent_error_details(caplog):
    runtime = MagicMock()
    runtime.execute.return_value = SimpleNamespace(
        success=False,
        error_message="redis://default:raw-secret@example.test:6379/0",
    )
    service = CommandExecutionService()

    with (
        patch.object(service, "_get_agent_runtime", return_value=runtime),
        caplog.at_level(logging.WARNING),
        pytest.raises(TerminalCommandExecutionError) as raised,
    ):
        service.execute_prompt_command(
            TerminalCommand(
                id="prompt-1",
                name="secure_prompt",
                description="secure prompt command",
                command_type=CommandType.PROMPT,
                user_prompt_template="summarize",
                requires_mcp=False,
            ),
            {},
        )

    assert str(raised.value) == "terminal_prompt_execution_failed"
    assert "raw-secret" not in caplog.text
    assert "redis://" not in caplog.text


def test_external_http_error_fails_without_returning_response_payload():
    client = MagicMock()
    client.request_json.return_value = (503, {"detail": "database password=raw-secret"})

    with (
        patch(
            "apps.terminal.application.services.get_terminal_command_http_client",
            return_value=client,
        ),
        pytest.raises(TerminalCommandExecutionError) as raised,
    ):
        CommandExecutionService().execute_api_command(_api_command(), {})

    assert str(raised.value) == "terminal_external_api_failed"


def test_invalid_http_method_is_rejected_before_dispatch():
    client = MagicMock()

    with (
        patch(
            "apps.terminal.application.services.get_terminal_command_http_client",
            return_value=client,
        ),
        pytest.raises(TerminalCommandExecutionError) as raised,
    ):
        CommandExecutionService().execute_api_command(
            _api_command(method="TRACE"),
            {},
        )

    assert str(raised.value) == "terminal_api_method_invalid"
    client.request_json.assert_not_called()


@pytest.mark.parametrize("user_id", [None, True, 0, -1])
def test_internal_api_requires_strict_positive_user_id(user_id):
    with (
        patch("apps.terminal.application.services.get_terminal_auth_user") as get_user,
        pytest.raises(TerminalCommandExecutionError) as raised,
    ):
        CommandExecutionService().execute_api_command(
            _api_command(endpoint="/api/terminal/status/"),
            {},
            user_id=user_id,
        )

    assert str(raised.value) == "terminal_internal_user_invalid"
    get_user.assert_not_called()


def test_internal_api_rejects_unknown_user_before_resolving_view():
    with (
        patch(
            "apps.terminal.application.services.get_terminal_auth_user",
            return_value=None,
        ),
        patch("apps.terminal.application.services.resolve") as resolve,
        pytest.raises(TerminalCommandExecutionError) as raised,
    ):
        CommandExecutionService().execute_api_command(
            _api_command(endpoint="/api/terminal/status/"),
            {},
            user_id=42,
        )

    assert str(raised.value) == "terminal_internal_user_not_found"
    resolve.assert_not_called()


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/../admin/",
        "/api/%2e%2e/admin/",
        "/api/terminal/status/?token=raw-secret",
        "/api/terminal\\status/",
    ],
)
def test_internal_api_rejects_noncanonical_paths(endpoint):
    with (
        patch("apps.terminal.application.services.get_terminal_auth_user") as get_user,
        pytest.raises(TerminalCommandExecutionError) as raised,
    ):
        CommandExecutionService().execute_api_command(
            _api_command(endpoint=endpoint),
            {},
            user_id=1,
        )

    assert str(raised.value) == "terminal_internal_api_url_invalid"
    get_user.assert_not_called()


def test_external_api_rejects_embedded_credentials_before_dispatch():
    client = MagicMock()

    with (
        patch(
            "apps.terminal.application.services.get_terminal_command_http_client",
            return_value=client,
        ),
        pytest.raises(TerminalCommandExecutionError) as raised,
    ):
        CommandExecutionService().execute_api_command(
            _api_command(endpoint="https://admin:raw-secret@example.test/data"),
            {},
        )

    assert str(raised.value) == "terminal_external_api_url_invalid"
    client.request_json.assert_not_called()


def test_path_parameters_are_encoded_and_excluded_from_request_params():
    client = MagicMock()
    client.request_json.return_value = (200, {"ok": True})

    with patch(
        "apps.terminal.application.services.get_terminal_command_http_client",
        return_value=client,
    ):
        result = CommandExecutionService().execute_api_command(
            _api_command(endpoint="https://example.test/assets/{symbol}"),
            {"symbol": "A/B ?", "limit": 5},
        )

    client.request_json.assert_called_once_with(
        method="GET",
        url="https://example.test/assets/A%2FB%20%3F",
        params={"limit": 5},
        timeout=60,
    )
    assert result["metadata"] == {
        "status_code": 200,
        "structured_output": {"ok": True},
    }


def test_invalid_output_filter_fails_closed():
    client = MagicMock()
    client.request_json.return_value = (200, {"items": []})

    with (
        patch(
            "apps.terminal.application.services.get_terminal_command_http_client",
            return_value=client,
        ),
        pytest.raises(TerminalCommandExecutionError) as raised,
    ):
        CommandExecutionService().execute_api_command(
            _api_command(response_filter=".items[2]"),
            {},
        )

    assert str(raised.value) == "terminal_output_filter_failed"


@pytest.mark.parametrize(
    "payload,expected_error",
    [
        ({"value": float("nan")}, "terminal_api_payload_invalid"),
        ({"value": float("inf")}, "terminal_api_payload_invalid"),
        ({"value": "x" * 1_048_576}, "terminal_api_payload_too_large"),
    ],
)
def test_unbounded_or_nonfinite_api_payload_is_rejected(payload, expected_error):
    client = MagicMock()
    client.request_json.return_value = (200, payload)

    with (
        patch(
            "apps.terminal.application.services.get_terminal_command_http_client",
            return_value=client,
        ),
        pytest.raises(TerminalCommandExecutionError) as raised,
    ):
        CommandExecutionService().execute_api_command(_api_command(), {})

    assert str(raised.value) == expected_error


def test_use_case_returns_stable_failure_and_redacts_audit_params(caplog):
    repository = MagicMock()
    repository.get_by_name.return_value = _api_command()
    execution_service = MagicMock()
    execution_service.execute_api_command.side_effect = TerminalCommandExecutionError(
        "postgresql://admin:raw-secret@example.test/prod"
    )
    audit_repository = MagicMock()
    request = ExecuteCommandRequest(
        command_name="secure_api",
        params={
            "symbol": "000001.SZ",
            "password": "raw-password",
            "profile": {"api_key": "raw-api-key"},
            "items": [{"Authorization": "Bearer raw-token"}],
        },
        user_id=7,
        username="operator",
        user_role="read_only",
        mcp_enabled=True,
        terminal_mode="confirm_each",
    )

    with caplog.at_level(logging.WARNING):
        response = ExecuteCommandUseCase(
            repository,
            execution_service,
            audit_repository,
        ).execute(request)

    assert response.success is False
    assert response.error == "terminal_command_execution_failed"
    audit_entry = audit_repository.save.call_args.args[0]
    audit_params = json.loads(audit_entry.params_summary)
    assert audit_entry.result_status == "error"
    assert audit_entry.error_message == "terminal_command_execution_failed"
    assert audit_params == {
        "symbol": "000001.SZ",
        "password": "***",
        "profile": {"api_key": "***"},
        "items": [{"Authorization": "***"}],
    }
    combined_text = f"{caplog.text}\n{audit_entry.params_summary}"
    assert "raw-secret" not in combined_text
    assert "raw-password" not in combined_text
    assert "raw-api-key" not in combined_text
    assert "raw-token" not in combined_text


def test_audit_summary_remains_valid_and_bounded_for_large_values():
    repository = MagicMock()
    repository.get_by_name.return_value = _api_command()
    execution_service = MagicMock()
    execution_service.execute_api_command.return_value = {
        "output": "ok",
        "metadata": {},
    }
    audit_repository = MagicMock()

    response = ExecuteCommandUseCase(
        repository,
        execution_service,
        audit_repository,
    ).execute(
        ExecuteCommandRequest(
            command_name="secure_api",
            params={"notes": '\\"' * 2_000, "score": float("nan")},
            user_id=7,
            user_role="read_only",
            mcp_enabled=True,
        )
    )

    assert response.success is True
    summary = audit_repository.save.call_args.args[0].params_summary
    assert len(summary) <= 500
    parsed = json.loads(summary)
    assert parsed["notes"].endswith("<truncated>")
    assert parsed["score"] == "<non-finite>"
    assert "NaN" not in summary


def test_audit_persistence_failure_is_redacted_and_does_not_fail_command(caplog):
    repository = MagicMock()
    repository.get_by_name.return_value = _api_command()
    execution_service = MagicMock()
    execution_service.execute_api_command.return_value = {
        "output": "ok",
        "metadata": {},
    }
    audit_repository = MagicMock()
    audit_repository.save.side_effect = TerminalAuditPersistenceError(
        "postgresql://admin:raw-secret@example.test/prod"
    )

    with caplog.at_level(logging.WARNING):
        response = ExecuteCommandUseCase(
            repository,
            execution_service,
            audit_repository,
        ).execute(
            ExecuteCommandRequest(
                command_name="secure_api",
                user_id=7,
                user_role="read_only",
                mcp_enabled=True,
            )
        )

    assert response.success is True
    assert "raw-secret" not in caplog.text
    assert "postgresql://" not in caplog.text
