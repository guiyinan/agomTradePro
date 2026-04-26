"""Repository provider re-exports for application composition roots."""

from .ai_insight_client import DashboardAIInsightClient
from .repositories import *  # noqa: F401,F403


def get_dashboard_ai_insight_client() -> DashboardAIInsightClient:
    """Return the default dashboard AI insight client."""
    return DashboardAIInsightClient()
