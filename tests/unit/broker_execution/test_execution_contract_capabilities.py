"""Agent schema declarations are parsed before heartbeat persistence."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from apps.broker_execution.application.agent_use_cases import AgentHeartbeatUseCase
from apps.broker_execution.application.execution_contract_capabilities import (
    parse_agent_execution_contracts,
)
from apps.broker_execution.application.ports import BrokerExecutionRepositoryProtocol
from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
    BrokerExecutionValidationError,
)
from apps.broker_execution.domain.execution_contract_capabilities import (
    EXECUTION_CONSTRAINT_SCHEMA_V2,
    AgentExecutionContracts,
)
from apps.broker_execution.infrastructure import broker_repository_agent_runtime as runtime
from apps.broker_execution.infrastructure.models import BrokerAgentModel


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "a-share-execution-constraints.v2",
        [True],
        [None],
        ["bad schema"],
        [" a-share-execution-constraints.v2"],
        ["a-share-execution-constraints.v2\n"],
        [""],
        ["a-share-execution-constraints.v2", "a-share-execution-constraints.v2"],
        ["a"] * 9,
    ],
)
def test_invalid_capability_is_rejected_before_heartbeat_write(raw: object) -> None:
    calls: list[object] = []
    repository = cast(
        BrokerExecutionRepositoryProtocol,
        SimpleNamespace(heartbeat_agent=lambda **kwargs: calls.append(kwargs) or {}),
    )
    with pytest.raises(BrokerExecutionValidationError, match="execution_constraint_schemas"):
        AgentHeartbeatUseCase(repository).execute(
            agent={"agent_pk": 1, "allowed_account_ids": [7]},
            payload={"execution_constraint_schemas": raw},
        )
    assert calls == []


def test_legacy_heartbeat_remains_readable_without_execution_capability() -> None:
    calls: list[object] = []
    repository = cast(
        BrokerExecutionRepositoryProtocol,
        SimpleNamespace(heartbeat_agent=lambda **kwargs: calls.append(kwargs) or {}),
    )
    AgentHeartbeatUseCase(repository).execute(
        agent={"agent_pk": 1, "allowed_account_ids": [7]}, payload={}
    )
    assert len(calls) == 1


@pytest.mark.parametrize("schemas", [(), ("a-share-execution-constraints.v1",), ("future.v9",)])
def test_missing_old_and_unknown_schemas_never_imply_v2(schemas: tuple[str, ...]) -> None:
    assert AgentExecutionContracts(schemas).supports_submission_v2 is False


def test_schema_support_is_explicit_and_not_execution_authority() -> None:
    from apps.risk_center.application.execution_submission_v2 import EXECUTION_SUBMISSION_V2_SCHEMA

    assert EXECUTION_CONSTRAINT_SCHEMA_V2 == EXECUTION_SUBMISSION_V2_SCHEMA
    capabilities = parse_agent_execution_contracts([EXECUTION_CONSTRAINT_SCHEMA_V2])
    assert capabilities.supports_submission_v2 is True


@pytest.mark.parametrize("schemas", [[], ("bad schema",), (True,), ("a", "a"), ("a",) * 9])
def test_domain_rejects_bypassed_invalid_capability_shapes(schemas: object) -> None:
    with pytest.raises(ValueError):
        AgentExecutionContracts(cast(tuple[str, ...], schemas))


@pytest.mark.parametrize(
    "snapshot",
    [
        None,
        [],
        {},
        {"execution_constraint_schemas": None},
        {"execution_constraint_schemas": ["future.v9"]},
    ],
)
def test_persisted_capability_guard_rejects_malformed_or_unsupported(snapshot: object) -> None:
    agent = BrokerAgentModel(health_snapshot=snapshot)
    with pytest.raises(BrokerExecutionConflictError, match="AGENT_EXECUTION_CONTRACT_UNSUPPORTED"):
        runtime._require_agent_submission_contract(agent)


def test_capability_guard_rejects_a_missing_agent() -> None:
    with pytest.raises(BrokerExecutionConflictError, match="AGENT_EXECUTION_CONTRACT_UNSUPPORTED"):
        runtime._require_agent_submission_contract(None)


def test_persisted_v2_capability_passes_only_this_guard() -> None:
    runtime._require_agent_submission_contract(
        BrokerAgentModel(
            health_snapshot={"execution_constraint_schemas": [EXECUTION_CONSTRAINT_SCHEMA_V2]}
        )
    )
