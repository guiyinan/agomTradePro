"""Focused fact-query use cases for Data Center."""

from __future__ import annotations

from datetime import date

from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.protocols import (
    CapitalFlowRepositoryProtocol,
    FinancialFactRepositoryProtocol,
    FundNavRepositoryProtocol,
    NewsRepositoryProtocol,
    SectorMembershipRepositoryProtocol,
    ValuationFactRepositoryProtocol,
)


class QueryFundNavUseCase:
    """Fetch fund NAV history."""

    def __init__(self, repo: FundNavRepositoryProtocol) -> None:
        self._repo = repo

    def execute(
        self,
        fund_code: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[dict[str, object]]:
        return [fact.to_dict() for fact in self._repo.get_series(fund_code, start, end)]


class QueryFinancialsUseCase:
    """Fetch financial facts for one asset."""

    def __init__(self, repo: FinancialFactRepositoryProtocol) -> None:
        self._repo = repo

    def execute(
        self,
        asset_code: str,
        period_type: FinancialPeriodType | None = None,
        limit: int = 20,
        end: date | None = None,
    ) -> list[dict[str, object]]:
        return [
            fact.to_dict()
            for fact in self._repo.get_facts(
                asset_code,
                period_type=period_type,
                limit=limit,
                end=end,
            )
        ]


class QueryValuationsUseCase:
    """Fetch valuation history for one asset."""

    def __init__(self, repo: ValuationFactRepositoryProtocol) -> None:
        self._repo = repo

    def execute(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        return [fact.to_dict() for fact in self._repo.get_series(asset_code, start, end)[:limit]]


class QuerySectorConstituentsUseCase:
    """Fetch members for one sector."""

    def __init__(self, repo: SectorMembershipRepositoryProtocol) -> None:
        self._repo = repo

    def execute(
        self,
        sector_code: str,
        as_of: date | None = None,
    ) -> list[dict[str, object]]:
        return [fact.to_dict() for fact in self._repo.get_members(sector_code, as_of)]


class QueryNewsUseCase:
    """Fetch news articles."""

    def __init__(self, repo: NewsRepositoryProtocol) -> None:
        self._repo = repo

    def execute(
        self,
        asset_code: str | None = None,
        limit: int = 50,
        end: date | None = None,
    ) -> list[dict[str, object]]:
        return [fact.to_dict() for fact in self._repo.get_recent(asset_code, limit, end)]


class QueryCapitalFlowsUseCase:
    """Fetch capital flow history for one asset."""

    def __init__(self, repo: CapitalFlowRepositoryProtocol) -> None:
        self._repo = repo

    def execute(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        return [fact.to_dict() for fact in self._repo.get_series(asset_code, start, end, limit)]


__all__ = [
    "QueryCapitalFlowsUseCase",
    "QueryFinancialsUseCase",
    "QueryFundNavUseCase",
    "QueryNewsUseCase",
    "QuerySectorConstituentsUseCase",
    "QueryValuationsUseCase",
]
