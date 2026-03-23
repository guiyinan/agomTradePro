"""
Domain Facade Layer for Agent Runtime.

WP-M2-02: Facades aggregate data from multiple existing apps,
normalize to fixed DTOs, and centralize cross-domain orchestration.
No MCP tool should directly aggregate multiple apps without going through a facade.
"""

from apps.agent_runtime.application.facades.base import BaseContextFacade
from apps.agent_runtime.application.facades.decision import DecisionTaskFacade
from apps.agent_runtime.application.facades.execution import ExecutionTaskFacade
from apps.agent_runtime.application.facades.monitoring import MonitoringTaskFacade
from apps.agent_runtime.application.facades.ops import OpsTaskFacade
from apps.agent_runtime.application.facades.research import ResearchTaskFacade

__all__ = [
    "BaseContextFacade",
    "ResearchTaskFacade",
    "MonitoringTaskFacade",
    "DecisionTaskFacade",
    "ExecutionTaskFacade",
    "OpsTaskFacade",
]


def get_facade(domain: str) -> BaseContextFacade:
    """
    Factory function to get a facade for a given domain.

    Args:
        domain: Task domain (research/monitoring/decision/execution/ops)

    Returns:
        Domain-specific facade instance

    Raises:
        ValueError: If domain is not recognized
    """
    facades = {
        "research": ResearchTaskFacade,
        "monitoring": MonitoringTaskFacade,
        "decision": DecisionTaskFacade,
        "execution": ExecutionTaskFacade,
        "ops": OpsTaskFacade,
    }
    facade_cls = facades.get(domain)
    if facade_cls is None:
        raise ValueError(
            f"Unknown domain: {domain}. Must be one of: {list(facades.keys())}"
        )
    return facade_cls()
