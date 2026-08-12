"""Production composition for the read-only Equity research snapshot."""

from __future__ import annotations

from typing import Any, cast

from apps.data_center.application import public as data_center_public
from apps.equity.application.research_snapshot import (
    EquityResearchSnapshotReader,
    EquityResearchSnapshotUseCase,
    ReadPayload,
)
from core.health_checks import is_decision_ready, run_decision_readiness_checks


class DataCenterEquityResearchSnapshotReader:
    """Adapt Data Center publication-only reads and strict readiness to Equity."""

    def resolve_asset(self, stock_code: str) -> ReadPayload:
        """Resolve one canonical asset identity."""

        return cast(ReadPayload, data_center_public.resolve_asset_payload(stock_code))

    def get_decision_readiness(self) -> ReadPayload:
        """Return exact strict checks and their fail-closed aggregate."""

        checks = run_decision_readiness_checks()
        ready = is_decision_ready(checks)
        return cast(
            ReadPayload,
            {
                "status": "ok" if ready else "blocked",
                "must_not_use_for_decision": not ready,
                "checks": cast(dict[str, Any], checks),
            },
        )

    def get_latest_quotes(self, stock_code: str, *, strict_freshness: bool = True) -> ReadPayload:
        """Return one publication-gated latest quote."""

        if strict_freshness is not True:
            raise ValueError("research snapshot requires strict quote freshness")
        return cast(
            ReadPayload,
            data_center_public.get_published_latest_quote_payload(stock_code),
        )

    def get_price_history(self, stock_code: str, *, limit: int) -> ReadPayload:
        """Return publication-gated historical bars."""

        return cast(
            ReadPayload,
            data_center_public.get_published_price_bar_series(stock_code, limit=limit),
        )

    def get_valuations(self, stock_code: str, *, limit: int) -> ReadPayload:
        """Return publication-gated valuation facts."""

        return cast(
            ReadPayload,
            data_center_public.get_published_valuation_facts(stock_code, limit=limit),
        )

    def get_financials(self, stock_code: str, *, limit: int) -> ReadPayload:
        """Return publication-gated financial facts."""

        return cast(
            ReadPayload,
            data_center_public.get_published_financial_facts(stock_code, limit=limit),
        )

    def get_news(self, stock_code: str, *, limit: int) -> ReadPayload:
        """Return publication-gated market news."""

        return cast(
            ReadPayload,
            data_center_public.get_published_market_news(asset_code=stock_code, limit=limit),
        )

    def get_capital_flows(self, stock_code: str, *, limit: int) -> ReadPayload:
        """Return publication-gated capital flows."""

        return cast(
            ReadPayload,
            data_center_public.get_published_capital_flow_series(stock_code, limit=limit),
        )


def make_equity_research_snapshot_use_case() -> EquityResearchSnapshotUseCase:
    """Build the canonical read-only Equity snapshot use case."""

    return EquityResearchSnapshotUseCase(
        cast(EquityResearchSnapshotReader, DataCenterEquityResearchSnapshotReader())
    )


__all__ = [
    "DataCenterEquityResearchSnapshotReader",
    "make_equity_research_snapshot_use_case",
]
