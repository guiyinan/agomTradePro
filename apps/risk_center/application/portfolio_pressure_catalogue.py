"""Read the existing approved Scenario catalogue for an ordinary-user selector."""

from __future__ import annotations

from datetime import datetime

from apps.risk_center.application.portfolio_risk_contracts import PortfolioPressureOptionPayload
from apps.risk_center.application.scenario_public import list_scenarios
from apps.risk_center.domain.scenarios import ScenarioDefinitionStatus, ScenarioRevisionStatus


def list_approved_portfolio_pressure_options(
    *, as_of: datetime
) -> list[PortfolioPressureOptionPayload]:
    """Return actual immutable versions without creating, activating or guessing scenarios."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("scenario catalogue cutoff must be timezone-aware")
    return [
        {
            "value": item.revision.revision_id,
            "label": f"{item.definition.name} · v{item.revision.version}",
        }
        for item in list_scenarios()
        if item.definition.status is ScenarioDefinitionStatus.ACTIVE
        and item.revision.status in {ScenarioRevisionStatus.APPROVED, ScenarioRevisionStatus.ACTIVE}
        and item.definition.created_at <= as_of
        and item.revision.created_at <= as_of
    ]
