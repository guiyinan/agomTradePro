"""Repository providers for agent runtime application services."""

from apps.agent_runtime.infrastructure.providers import (
    AgentContextRepository,
    AgentHandoffRepository,
    AgentOperatorRepository,
    AgentProposalRepository,
    AgentRuntimeUserRepository,
    AgentTaskRepository,
    AgentTimelineRepository,
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


def get_context_snapshot_repository():
    """Return the context snapshot repository used by facades."""

    from apps.agent_runtime.infrastructure.context_snapshot_repository import (
        DjangoContextSnapshotRepository,
    )

    return DjangoContextSnapshotRepository()
