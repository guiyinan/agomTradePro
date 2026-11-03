"""Lazy composition for owner-scoped, simulation-only portfolio risk."""

from __future__ import annotations

from datetime import UTC, datetime

from django.utils import timezone

from apps.risk_center.application.portfolio_risk_runtime import get_portfolio_risk_runtime
from apps.risk_center.execution_settlement_composition import (
    build_execution_settlement_v3_rule_reader,
)
from apps.simulated_trading.application.portfolio_risk_calendar import (
    build_portfolio_risk_calendar_reader,
)
from apps.simulated_trading.application.portfolio_risk_pressure_runner import (
    PortfolioRiskPressureRunnerService,
)
from apps.simulated_trading.application.portfolio_risk_service import (
    OwnerScopedPortfolioRiskService,
)
from apps.simulated_trading.composition import build_observer_grant_repository
from apps.simulated_trading.execution_current_reference_composition import (
    build_configured_execution_calendar_reader,
    build_current_reference_identity_reader,
    get_simulated_execution_runtime_environment,
)
from apps.simulated_trading.infrastructure.portfolio_risk_code_version import (
    portfolio_risk_code_version,
)
from apps.simulated_trading.infrastructure.portfolio_risk_resource_repository import (
    DjangoPortfolioRiskResourceRepository,
)
from apps.simulated_trading.portfolio_risk_close_snapshot_composition import (
    build_portfolio_risk_close_snapshot_session_provider,
)


class _PortfolioRiskSystemClock:
    def now(self) -> datetime:
        """Read the actual server UTC clock without substituting any source clock."""

        return timezone.now().astimezone(UTC)


def build_portfolio_risk_service(using: str) -> OwnerScopedPortfolioRiskService:
    """Build existing read ports and explicit evidence writers without changing rows."""

    environment = get_simulated_execution_runtime_environment()
    clock = _PortfolioRiskSystemClock()
    runtime = get_portfolio_risk_runtime(using=using, environment=environment)
    code_version = portfolio_risk_code_version()
    identities = build_current_reference_identity_reader(runtime_environment=environment)
    calendar_reader = build_configured_execution_calendar_reader(runtime_environment=environment)
    calendars = build_portfolio_risk_calendar_reader(
        identity_reader=identities,
        calendar_reader=calendar_reader,
    )
    settlement_reader = build_execution_settlement_v3_rule_reader()
    close_snapshot_session_provider = build_portfolio_risk_close_snapshot_session_provider(
        environment=environment,
        identity_reader=identities,
        calendar_reader=calendar_reader,
        settlement_reader=settlement_reader,
    )
    resources = DjangoPortfolioRiskResourceRepository(
        using=using,
        observer_grant_repository=build_observer_grant_repository(using=using),
    )
    return OwnerScopedPortfolioRiskService(
        resources=resources,
        runtime=runtime,
        clock=clock,
        business_timezone=timezone.get_default_timezone(),
        code_version=code_version,
        using=using,
        calendar_reader=calendars,
        close_snapshot_session_provider=close_snapshot_session_provider,
        pressure_runner=PortfolioRiskPressureRunnerService(
            runtime=runtime,
            code_version=code_version,
            clock=clock,
        ),
    )
