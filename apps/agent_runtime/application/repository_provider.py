"""Repository providers for agent runtime application services."""

from typing import Any

from apps.agent_runtime.infrastructure.providers import (
    AgentContextRepository as AgentContextRepository,
)
from apps.agent_runtime.infrastructure.providers import (
    AgentHandoffRepository as AgentHandoffRepository,
)
from apps.agent_runtime.infrastructure.providers import (
    AgentOperatorRepository as AgentOperatorRepository,
)
from apps.agent_runtime.infrastructure.providers import (
    AgentProposalRepository as AgentProposalRepository,
)
from apps.agent_runtime.infrastructure.providers import (
    AgentRuntimeUserRepository as AgentRuntimeUserRepository,
)
from apps.agent_runtime.infrastructure.providers import AgentTaskRepository as AgentTaskRepository
from apps.agent_runtime.infrastructure.providers import (
    AgentTimelineRepository as AgentTimelineRepository,
)


def get_timeline_repository() -> AgentTimelineRepository:
    """Return the default timeline repository."""
    return AgentTimelineRepository()


def get_runtime_user_repository() -> AgentRuntimeUserRepository:
    """Return the default runtime user repository."""
    return AgentRuntimeUserRepository()


def get_operator_repository() -> AgentOperatorRepository:
    """Return the default operator query repository."""

    return AgentOperatorRepository()


def get_task_repository() -> AgentTaskRepository:
    """Return the default task repository."""

    return AgentTaskRepository()


def get_proposal_repository() -> AgentProposalRepository:
    """Return the default proposal repository."""

    return AgentProposalRepository()


def get_handoff_repository() -> AgentHandoffRepository:
    """Return the default handoff repository."""

    return AgentHandoffRepository()


def get_context_repository() -> AgentContextRepository:
    """Return the default context repository."""

    return AgentContextRepository()


def get_context_snapshot_repository() -> Any:
    """Return the context snapshot repository used by facades."""

    from apps.agent_runtime.infrastructure.context_snapshot_repository import (
        DjangoContextSnapshotRepository,
    )

    return DjangoContextSnapshotRepository()


def get_terminal_agent_service(*, capability_gateway: Any | None = None) -> Any:
    """Return the default terminal agent execution service."""

    from apps.agent_runtime.infrastructure.terminal_agent_service import (
        OpenAIAgentsTerminalService,
    )

    return OpenAIAgentsTerminalService(
        capability_gateway=capability_gateway,
        approval_gateway=get_terminal_mcp_approval_gateway(),
    )


def get_terminal_mcp_approval_gateway() -> Any:
    """Return the durable Terminal MCP approval facade."""

    from apps.agent_runtime.application.terminal_approval import (
        TerminalMcpApprovalFacade,
    )

    return TerminalMcpApprovalFacade()


def get_approved_mcp_capability_executor() -> Any:
    """Return the infrastructure adapter that executes an approved MCP proposal."""

    from apps.agent_runtime.infrastructure.mcp_proposal_executor import (
        ApprovedMcpCapabilityExecutor,
    )

    return ApprovedMcpCapabilityExecutor()
