"""Normalize Agent capability JSON at the application boundary."""

from __future__ import annotations

from typing import cast

from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionValidationError,
)
from apps.broker_execution.domain.execution_contract_capabilities import AgentExecutionContracts


def parse_agent_execution_contracts(value: object) -> AgentExecutionContracts:
    """Validate a bounded JSON array; callers provide [] for omitted legacy data."""

    if type(value) is not list:
        raise BrokerExecutionValidationError("execution_constraint_schemas must be a JSON array")
    values = cast(list[object], value)
    if any(type(item) is not str for item in values):
        raise BrokerExecutionValidationError("execution_constraint_schemas requires schema names")
    try:
        return AgentExecutionContracts(tuple(cast(list[str], values)))
    except ValueError as error:
        raise BrokerExecutionValidationError(str(error)) from error
