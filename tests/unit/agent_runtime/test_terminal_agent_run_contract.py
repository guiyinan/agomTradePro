"""Pure TAR-01 contract tests; no Django database, broker, or Agent SDK."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.agent_runtime.domain.terminal_agent_run_contract import (
    InvalidTerminalRunTransition,
    TerminalAgentBrokerEnvelope,
    TerminalAgentRunContract,
    TerminalOwnershipError,
    TerminalRunContractError,
    TerminalRunSelector,
    TerminalRunStatus,
    TerminalRunSubmission,
    TerminalRuntimeMode,
    assert_no_sensitive_runtime_data,
    is_terminal_run_status,
    transition_terminal_run,
    validate_broker_payload,
    validate_terminal_run_id,
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


def test_submission_rejects_noncanonical_identity_mode_digest_and_clocks() -> None:
    accepted_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    with pytest.raises(TerminalRunContractError, match="canonical string"):
        validate_terminal_run_id(" run-20260818-0001")
    with pytest.raises(TerminalRunContractError, match="runtime_mode"):
        TerminalRunSubmission(
            selector=_selector(),
            runtime_mode=cast(TerminalRuntimeMode, "web_queued"),
            request_digest="a" * 64,
            accepted_at=accepted_at,
            deadline_at=accepted_at + timedelta(minutes=1),
        )
    with pytest.raises(TerminalRunContractError, match="lowercase SHA-256"):
        TerminalRunSubmission(
            selector=_selector(),
            runtime_mode=TerminalRuntimeMode.WEB_QUEUED,
            request_digest="A" * 64,
            accepted_at=accepted_at,
            deadline_at=accepted_at + timedelta(minutes=1),
        )
    with pytest.raises(TerminalRunContractError, match="timezone-aware"):
        TerminalRunSubmission(
            selector=_selector(),
            runtime_mode=TerminalRuntimeMode.WEB_QUEUED,
            request_digest="a" * 64,
            accepted_at=datetime(2026, 8, 18, 12, 0),
            deadline_at=accepted_at + timedelta(minutes=1),
        )
    with pytest.raises(TerminalRunContractError, match="after accepted_at"):
        TerminalRunSubmission(
            selector=_selector(),
            runtime_mode=TerminalRuntimeMode.WEB_QUEUED,
            request_digest="a" * 64,
            accepted_at=accepted_at,
            deadline_at=accepted_at,
        )


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


def test_status_strings_are_coerced_and_unknown_values_fail_closed() -> None:
    assert transition_terminal_run("accepted", "queued") is TerminalRunStatus.QUEUED
    with pytest.raises(TerminalRunContractError, match="unknown Terminal Agent status"):
        transition_terminal_run("invented", "queued")


def test_broker_envelope_is_exactly_id_only() -> None:
    envelope = TerminalAgentBrokerEnvelope(run_id="run-20260818-0001", task_id=17)
    payload = envelope.to_payload()

    assert payload == {"run_id": "run-20260818-0001", "task_id": 17}
    assert validate_broker_payload(payload) == envelope


def test_sensitive_payload_walks_non_string_keys_and_nested_sequences() -> None:
    payload = cast(
        Mapping[str, object],
        {1: [{"safe": True}, ["terminal-value"]]},
    )

    assert_no_sensitive_runtime_data(payload)


def test_broker_payload_rejects_non_string_run_id() -> None:
    with pytest.raises(TerminalRunContractError, match="run_id must be a string"):
        validate_broker_payload({"run_id": 17, "task_id": 17})


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


def test_run_contract_enforces_owner_deadline_payload_and_transition() -> None:
    accepted_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    submission = TerminalRunSubmission(
        selector=_selector(),
        runtime_mode=TerminalRuntimeMode.WEB_QUEUED,
        request_digest="a" * 64,
        accepted_at=accepted_at,
        deadline_at=accepted_at + timedelta(minutes=1),
    )
    contract = TerminalAgentRunContract(submission=submission)

    assert contract.is_owned_by(41)
    assert not contract.is_owned_by(42)
    contract.require_owner(41)
    with pytest.raises(TerminalOwnershipError, match="not owned"):
        contract.require_owner(42)
    assert not contract.is_expired(accepted_at)
    assert contract.is_expired(submission.deadline_at)
    with pytest.raises(TerminalRunContractError, match="timezone-aware"):
        contract.is_expired(datetime(2026, 8, 18, 12, 1))
    assert contract.broker_payload() == {
        "run_id": "run-20260818-0001",
        "task_id": 17,
    }
    assert contract.transition(TerminalRunStatus.QUEUED).dispatch_status is (
        TerminalRunStatus.QUEUED
    )


def test_run_contract_rejects_invalid_dispatch_status() -> None:
    accepted_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    submission = TerminalRunSubmission(
        selector=_selector(),
        runtime_mode=TerminalRuntimeMode.WEB_QUEUED,
        request_digest="a" * 64,
        accepted_at=accepted_at,
        deadline_at=accepted_at + timedelta(minutes=1),
    )

    with pytest.raises(TerminalRunContractError, match="dispatch_status"):
        TerminalAgentRunContract(
            submission=submission,
            dispatch_status=cast(TerminalRunStatus, "accepted"),
        )


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
