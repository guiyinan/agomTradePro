"""Contracts for the shared, transaction-aware portfolio-risk calendar reader."""

from __future__ import annotations

from datetime import date, datetime
from typing import cast

import pytest
from django.db import DEFAULT_DB_ALIAS

from apps.risk_center.application.portfolio_risk_assets import (
    CloseSnapshotSessionEvidenceProvider,
)
from apps.risk_center.application.portfolio_risk_runtime import PortfolioRiskRuntime
from apps.simulated_trading import portfolio_risk_composition as composition
from apps.simulated_trading.application.portfolio_risk_calendar import (
    PortfolioRiskCalendarReader,
)
from apps.simulated_trading.application.portfolio_risk_public import (
    PortfolioRiskUnavailable,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)


class _LazyCalendarReader:
    """Record any accidental source read during composition."""

    def __init__(self) -> None:
        self.reads = 0

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence | None:
        """Stay lazy; construction must not resolve a calendar publication."""

        self.reads += 1
        return None


def test_default_risk_composition_shares_transaction_aware_calendar_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Give GET and locked rechecks one lazily composed reference-aware reader."""

    runtime = cast(PortfolioRiskRuntime, object())
    calendar_reader = _LazyCalendarReader()
    configured_arguments: dict[str, object] = {}
    risk_calendar_arguments: dict[str, object] = {}
    close_provider_arguments: dict[str, object] = {}
    risk_calendar = cast(PortfolioRiskCalendarReader, object())
    close_provider = cast(CloseSnapshotSessionEvidenceProvider, object())

    def _build_calendar_reader(
        *,
        runtime_environment: str,
        read_publication: object,
        read_configuration: object,
    ) -> _LazyCalendarReader:
        configured_arguments.update(
            {
                "runtime_environment": runtime_environment,
                "read_publication": read_publication,
                "read_configuration": read_configuration,
            }
        )
        return calendar_reader

    def _build_risk_calendar_reader(
        *, identity_reader: object, calendar_reader: object
    ) -> PortfolioRiskCalendarReader:
        risk_calendar_arguments.update(
            {"identity_reader": identity_reader, "calendar_reader": calendar_reader}
        )
        return risk_calendar

    def _build_close_provider(
        *,
        environment: str,
        identity_reader: object,
        calendar_reader: object,
        settlement_reader: object,
    ) -> CloseSnapshotSessionEvidenceProvider:
        close_provider_arguments.update(
            {
                "environment": environment,
                "identity_reader": identity_reader,
                "calendar_reader": calendar_reader,
                "settlement_reader": settlement_reader,
            }
        )
        return close_provider

    monkeypatch.setattr(
        composition,
        "get_simulated_execution_runtime_environment",
        lambda: "development",
    )

    def _build_runtime(*, using: str, environment: str) -> PortfolioRiskRuntime:
        return runtime

    monkeypatch.setattr(composition, "get_portfolio_risk_runtime", _build_runtime)
    monkeypatch.setattr(composition, "portfolio_risk_code_version", lambda: "test-code-version")
    monkeypatch.setattr(
        composition, "build_configured_execution_calendar_reader", _build_calendar_reader
    )
    monkeypatch.setattr(
        composition, "build_portfolio_risk_calendar_reader", _build_risk_calendar_reader
    )
    monkeypatch.setattr(
        composition,
        "build_portfolio_risk_close_snapshot_session_provider",
        _build_close_provider,
    )

    composition.build_portfolio_risk_service(using=DEFAULT_DB_ALIAS)

    assert configured_arguments == {
        "runtime_environment": "development",
        "read_publication": composition.read_current_exchange_calendar_reference,
        "read_configuration": composition.read_calendar_capture_configuration_reference_at,
    }
    assert risk_calendar_arguments["calendar_reader"] is calendar_reader
    assert close_provider_arguments["calendar_reader"] is calendar_reader
    assert risk_calendar_arguments["identity_reader"] is close_provider_arguments["identity_reader"]
    assert close_provider_arguments["environment"] == "development"
    assert calendar_reader.reads == 0


def test_nondefault_risk_database_alias_fails_before_composing_any_readers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a split-alias risk context before any policy or source setup."""

    calls: list[str] = []

    def _unexpected_environment_read() -> str:
        calls.append("environment")
        raise AssertionError("unsupported alias must fail before composition")

    monkeypatch.setattr(
        composition,
        "get_simulated_execution_runtime_environment",
        _unexpected_environment_read,
    )

    with pytest.raises(PortfolioRiskUnavailable) as raised:
        composition.build_portfolio_risk_service(using="risk_replica")

    assert raised.value.code == "PORTFOLIO_RISK_DATABASE_ALIAS_UNSUPPORTED"
    assert calls == []
