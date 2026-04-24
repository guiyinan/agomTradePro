"""Repository providers for agent runtime application services."""

from apps.agent_runtime.infrastructure.repositories import (
    AgentOperatorRepository,
    AgentRuntimeUserRepository,
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
