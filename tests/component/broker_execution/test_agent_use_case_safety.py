"""Machine API authentication and Agent use-case safety contracts."""

from datetime import UTC, datetime

import pytest

from apps.broker_execution.application.agent_auth import (
    AuthenticateAgentRequestUseCase,
    build_agent_signature,
)
from apps.broker_execution.application.agent_use_cases import (
    CompleteAgentCommandUseCase,
    LeaseAgentCommandsUseCase,
    ReportAgentEventsUseCase,
)
from apps.broker_execution.application.use_case_errors import (
    BrokerAgentAuthenticationError,
    BrokerExecutionValidationError,
)
from apps.broker_execution.infrastructure.models import BrokerExecutionAuditModel
from apps.broker_execution.infrastructure.repositories import (
    DjangoBrokerExecutionRepository,
)


class _NeverCalledRepository:
    def lease_agent_commands(self, **_kwargs):
        raise AssertionError("repository must not be called")

    def complete_agent_command(self, **_kwargs):
        raise AssertionError("repository must not be called")

    def report_agent_events(self, **_kwargs):
        raise AssertionError("repository must not be called")


def _agent() -> dict:
    return {"agent_pk": 1, "allowed_account_ids": [7]}


@pytest.mark.django_db
def test_malformed_signed_credential_fails_as_authentication_error() -> None:
    """An invalid UUID cannot escape into a Django UUIDField lookup."""

    body = b'{"contract_version":"1.0"}'
    secret = "s" * 32
    sent_at = datetime.now(UTC).isoformat()
    nonce = "malformed-credential-nonce"
    request_id = "malformed-credential-request"
    headers = {
        "Authorization": f"Agent not-a-uuid.{secret}",
        "X-Agent-Id": "agent-test",
        "X-Request-Id": request_id,
        "X-Sent-At": sent_at,
        "X-Nonce": nonce,
        "X-Signature": build_agent_signature(
            secret=secret,
            sent_at=sent_at,
            nonce=nonce,
            request_id=request_id,
            body=body,
        ),
    }

    with pytest.raises(BrokerAgentAuthenticationError, match="Malformed"):
        AuthenticateAgentRequestUseCase(DjangoBrokerExecutionRepository()).execute(
            headers=headers,
            body=body,
            required_scope="agent.heartbeat.write",
            source_ip="127.0.0.1",
        )

    audit = BrokerExecutionAuditModel.objects.get(action="agent_auth_failed")
    assert audit.after["failure_code"] == "credential_malformed"
    assert audit.request_id == request_id


@pytest.mark.parametrize(
    "agent",
    [
        {"agent_pk": 0, "allowed_account_ids": [7]},
        {"agent_pk": 1, "allowed_account_ids": []},
        {"agent_pk": 1, "allowed_account_ids": [-1]},
        {"agent_pk": "invalid", "allowed_account_ids": [7]},
    ],
)
def test_agent_scope_is_strictly_validated(agent: dict) -> None:
    with pytest.raises(BrokerExecutionValidationError, match="scope is invalid"):
        LeaseAgentCommandsUseCase(_NeverCalledRepository()).execute(
            agent=agent,
            limit=20,
        )


def test_command_limit_is_rejected_instead_of_silently_clamped() -> None:
    with pytest.raises(BrokerExecutionValidationError, match="limit is invalid"):
        LeaseAgentCommandsUseCase(_NeverCalledRepository()).execute(
            agent=_agent(),
            limit=0,
        )


def test_command_completion_rejects_string_boolean() -> None:
    with pytest.raises(BrokerExecutionValidationError, match="success must be boolean"):
        CompleteAgentCommandUseCase(_NeverCalledRepository()).execute(
            agent=_agent(),
            command_id="command-1",
            success="false",
            result={},
        )


def test_empty_agent_event_batch_is_rejected() -> None:
    with pytest.raises(BrokerExecutionValidationError, match="Between 1 and 200"):
        ReportAgentEventsUseCase(_NeverCalledRepository()).execute(
            agent=_agent(),
            events=[],
        )
