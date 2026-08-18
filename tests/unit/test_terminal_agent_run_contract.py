"""Pure TAR-01 contract tests; no Django database, broker, or Agent SDK."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.agent_runtime.domain.terminal_agent_run_contract import (
    InvalidTerminalRunTransition,
    TerminalAgentBrokerEnvelope,
    TerminalRunContractError,
    TerminalRunSelector,
    TerminalRunStatus,
    TerminalRunSubmission,
    TerminalRuntimeMode,
    is_terminal_run_status,
    transition_terminal_run,
    validate_broker_payload,
)


def _selector() -> TerminalRunSelector:
    return TerminalRunSelector(
        run_id="run-20260818-0001",
        task_id=17,
        actor_user_id=41,
        client_request_id="request-0001",
    )


def test_submission_freezes_owner_mode_digest_and_aware_deadline() -> None:
    accepted_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    submission = TerminalRunSubmission(
        selector=_selector(),
        runtime_mode=TerminalRuntimeMode.WEB_QUEUED,
        request_digest="a" * 64,
        accepted_at=accepted_at,
        deadline_at=accepted_at + timedelta(minutes=1),
    )

    assert submission.selector.actor_user_id == 41
    assert submission.runtime_mode is TerminalRuntimeMode.WEB_QUEUED


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (TerminalRunStatus.ACCEPTED, TerminalRunStatus.QUEUED),
        (TerminalRunStatus.QUEUED, TerminalRunStatus.CLAIMED),
        (TerminalRunStatus.CLAIMED, TerminalRunStatus.RUNNING),
        (TerminalRunStatus.RUNNING, TerminalRunStatus.WAITING_APPROVAL),
        (TerminalRunStatus.WAITING_APPROVAL, TerminalRunStatus.QUEUED),
        (TerminalRunStatus.RUNNING, TerminalRunStatus.COMPLETED),
        (TerminalRunStatus.RUNNING, TerminalRunStatus.ORPHANED),
        (TerminalRunStatus.ORPHANED, TerminalRunStatus.QUEUED),
        (TerminalRunStatus.CANCEL_REQUESTED, TerminalRunStatus.CANCELLED),
    ],
)
def test_state_machine_accepts_only_frozen_forward_edges(
    current: TerminalRunStatus,
    requested: TerminalRunStatus,
) -> None:
    assert transition_terminal_run(current, requested) is requested


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (TerminalRunStatus.COMPLETED, TerminalRunStatus.QUEUED),
        (TerminalRunStatus.FAILED, TerminalRunStatus.RUNNING),
        (TerminalRunStatus.QUEUED, TerminalRunStatus.COMPLETED),
        (TerminalRunStatus.ORPHANED, TerminalRunStatus.RUNNING),
        (TerminalRunStatus.CANCEL_REQUESTED, TerminalRunStatus.RUNNING),
    ],
)
def test_state_machine_rejects_terminal_or_skipped_edges(
    current: TerminalRunStatus,
    requested: TerminalRunStatus,
) -> None:
    with pytest.raises(InvalidTerminalRunTransition):
        transition_terminal_run(current, requested)


def test_duplicate_delivery_is_idempotent_and_terminals_are_final() -> None:
    assert transition_terminal_run(TerminalRunStatus.RUNNING, TerminalRunStatus.RUNNING) is (
        TerminalRunStatus.RUNNING
    )
    assert is_terminal_run_status(TerminalRunStatus.COMPLETED)
    assert not is_terminal_run_status(TerminalRunStatus.QUEUED)


def test_broker_envelope_is_exactly_id_only() -> None:
    envelope = TerminalAgentBrokerEnvelope(run_id="run-20260818-0001", task_id=17)
    payload = envelope.to_payload()

    assert payload == {"run_id": "run-20260818-0001", "task_id": 17}
    assert validate_broker_payload(payload) == envelope


@pytest.mark.parametrize(
    "payload",
    [
        {"run_id": "run-20260818-0001", "task_id": 17, "prompt": "secret"},
        {"run_id": "run-20260818-0001", "task_id": 17, "api_key": "secret"},
        {"run_id": "run-20260818-0001", "task_id": True},
        {"run_id": "run-20260818-0001", "task_id": 17, "actor_user_id": 41},
    ],
)
def test_broker_payload_rejects_secrets_extra_fields_and_bool_ids(
    payload: dict[str, object],
) -> None:
    with pytest.raises(TerminalRunContractError):
        validate_broker_payload(payload)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"task_id": True},
        {"actor_user_id": True},
        {"run_id": "bad"},
        {"client_request_id": "bad id"},
    ],
)
def test_selector_rejects_type_substitution_and_noncanonical_ids(
    kwargs: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "run_id": "run-20260818-0001",
        "task_id": 17,
        "actor_user_id": 41,
        "client_request_id": "request-0001",
    }
    values.update(kwargs)
    with pytest.raises(TerminalRunContractError):
        TerminalRunSelector(**values)  # type: ignore[arg-type]


def test_domain_contract_has_no_orm_or_inline_agent_dependency() -> None:
    source_path = Path("apps/agent_runtime/domain/terminal_agent_run_contract.py")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert "django" not in imported_names
    assert "infrastructure" not in source
    assert "OpenAIAgentsTerminalService" not in source
    assert ".objects" not in source
