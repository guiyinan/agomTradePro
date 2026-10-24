"""Application orchestration for an owner-scoped historical quantity report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from apps.account.application.historical_position_source import (
    LegacyPortfolioPositionReader,
)
from apps.simulated_trading.domain.historical_sellable_difference import (
    HistoricalPositionMappingFact,
    HistoricalSellableDifferenceReport,
    HistoricalSourcePositionFact,
    HistoricalTargetPositionFact,
    assemble_historical_difference_rows,
)
from core.exceptions import InvalidInputError


@dataclass(frozen=True)
class LedgerMappingProjection:
    """One migration mapping returned by Simulated Trading Infrastructure."""

    mapping_id: int
    source_app: str
    source_table: str
    source_id: int
    target_table: str
    target_id: int


@dataclass(frozen=True)
class TargetPositionProjection:
    """A target position boundary row; ownership is checked before serialization."""

    position_id: int
    account_id: int
    asset_code: str
    quantity: Decimal | None
    available_quantity: Decimal | None
    available_quantity_known: bool | None


@dataclass(frozen=True)
class SelectedAccountScopeRead:
    """Exact selected-account lookup and candidate portfolio mappings."""

    status: Literal["ready", "account_unavailable", "database_route_mismatch"]
    database_alias: str | None
    portfolio_mappings: tuple[LedgerMappingProjection, ...]


@dataclass(frozen=True)
class TargetPositionScopeRead:
    """Selected-account positions and only mappings relevant to those rows."""

    status: Literal["ready", "account_unavailable", "database_route_mismatch"]
    database_alias: str | None
    positions: tuple[TargetPositionProjection, ...]
    mappings: tuple[LedgerMappingProjection, ...]
    existing_target_position_ids: frozenset[int]


class HistoricalSellableDifferenceRepository(Protocol):
    """Persistence port for Simulated Trading's own ledger models."""

    def read_selected_account_scope(
        self,
        *,
        user_id: int,
        account_id: int,
        database_alias: str,
    ) -> SelectedAccountScopeRead:
        """Find the exact owner/account and its portfolio map candidates."""

    def read_position_scope(
        self,
        *,
        user_id: int,
        account_id: int,
        source_position_ids: tuple[int, ...],
        database_alias: str,
    ) -> TargetPositionScopeRead:
        """Read selected target positions and their source/target map edges."""


class HistoricalSellableDifferenceService:
    """Compose Account's public source read with Simulated Trading's own read port."""

    def __init__(
        self,
        *,
        source_reader: LegacyPortfolioPositionReader,
        repository: HistoricalSellableDifferenceRepository,
    ) -> None:
        self._source_reader = source_reader
        self._repository = repository

    def build_report(
        self,
        *,
        user_id: int,
        account_id: int,
        database_alias: str,
        reported_at: datetime,
    ) -> HistoricalSellableDifferenceReport:
        """Build a best-effort report without making repairs or sellable claims."""

        if (
            not isinstance(user_id, int)
            or isinstance(user_id, bool)
            or user_id <= 0
            or not isinstance(account_id, int)
            or isinstance(account_id, bool)
            or account_id <= 0
            or not isinstance(database_alias, str)
            or not database_alias.strip()
        ):
            raise InvalidInputError("user, account, and database alias must be explicit")
        if reported_at.tzinfo is None or reported_at.utcoffset() is None:
            raise InvalidInputError("reported_at must be timezone-aware")

        account_read = self._repository.read_selected_account_scope(
            user_id=user_id,
            account_id=account_id,
            database_alias=database_alias,
        )
        if account_read.status == "database_route_mismatch":
            return self._blocked_report(
                user_id=user_id,
                account_id=account_id,
                database_alias=database_alias,
                reported_at=reported_at,
                reason_code="DATABASE_ROUTER_ALIAS_MISMATCH",
            )
        if account_read.status != "ready" or account_read.database_alias != database_alias:
            return self._blocked_report(
                user_id=user_id,
                account_id=account_id,
                database_alias=database_alias,
                reported_at=reported_at,
                reason_code="SCOPE_UNAVAILABLE",
            )

        portfolio_maps = account_read.portfolio_mappings
        matching_portfolio_maps = tuple(
            mapping
            for mapping in portfolio_maps
            if mapping.source_app == "account"
            and mapping.source_table == "portfolio"
            and mapping.target_table == "simulated_account"
            and mapping.target_id == account_id
        )
        if len(matching_portfolio_maps) > 1:
            return self._blocked_report(
                user_id=user_id,
                account_id=account_id,
                database_alias=database_alias,
                reported_at=reported_at,
                reason_code="PORTFOLIO_ACCOUNT_MAPPING_AMBIGUOUS",
            )
        if not matching_portfolio_maps:
            wrong_table_map = any(
                mapping.source_app == "account"
                and mapping.source_table == "portfolio"
                and mapping.target_id == account_id
                and mapping.target_table != "simulated_account"
                for mapping in portfolio_maps
            )
            reason_code = (
                "PORTFOLIO_ACCOUNT_MAP_TARGET_TABLE_MISMATCH"
                if wrong_table_map
                else "PORTFOLIO_ACCOUNT_MAP_MISSING"
            )
            return self._blocked_report(
                user_id=user_id,
                account_id=account_id,
                database_alias=database_alias,
                reported_at=reported_at,
                reason_code=reason_code,
            )

        portfolio_mapping = matching_portfolio_maps[0]
        source_read = self._source_reader.read(
            user_id=user_id,
            portfolio_id=portfolio_mapping.source_id,
            database_alias=database_alias,
        )
        if source_read.status == "database_route_mismatch":
            return self._blocked_report(
                user_id=user_id,
                account_id=account_id,
                database_alias=database_alias,
                reported_at=reported_at,
                reason_code="DATABASE_ROUTER_ALIAS_MISMATCH",
            )
        if source_read.status != "ready" or source_read.database_alias != database_alias:
            return self._blocked_report(
                user_id=user_id,
                account_id=account_id,
                database_alias=database_alias,
                reported_at=reported_at,
                reason_code="SCOPE_UNAVAILABLE",
            )

        source_ids = tuple(position.position_id for position in source_read.positions)
        target_read = self._repository.read_position_scope(
            user_id=user_id,
            account_id=account_id,
            source_position_ids=source_ids,
            database_alias=database_alias,
        )
        if target_read.status == "database_route_mismatch":
            return self._blocked_report(
                user_id=user_id,
                account_id=account_id,
                database_alias=database_alias,
                reported_at=reported_at,
                reason_code="DATABASE_ROUTER_ALIAS_MISMATCH",
            )
        if target_read.status != "ready" or target_read.database_alias != database_alias:
            return self._blocked_report(
                user_id=user_id,
                account_id=account_id,
                database_alias=database_alias,
                reported_at=reported_at,
                reason_code="SCOPE_UNAVAILABLE",
            )

        source_facts = tuple(
            HistoricalSourcePositionFact(
                portfolio_id=position.portfolio_id,
                position_id=position.position_id,
                asset_code=position.asset_code,
                quantity=position.total_quantity,
                quantity_known=position.quantity_known,
                quantity_reason_code=position.quantity_reason_code,
                is_closed=position.is_closed,
                record_updated_at=position.record_updated_at,
            )
            for position in source_read.positions
        )
        mapping_facts = tuple(
            HistoricalPositionMappingFact(
                mapping_id=mapping.mapping_id,
                source_app=mapping.source_app,
                source_table=mapping.source_table,
                source_id=mapping.source_id,
                target_table=mapping.target_table,
                target_id=mapping.target_id,
            )
            for mapping in target_read.mappings
        )
        target_facts = tuple(
            HistoricalTargetPositionFact(
                position_id=position.position_id,
                account_id=position.account_id,
                asset_code=position.asset_code,
                quantity=position.quantity,
                available_quantity=position.available_quantity,
                available_quantity_known=position.available_quantity_known,
            )
            for position in target_read.positions
        )
        rows = assemble_historical_difference_rows(
            source_positions=source_facts,
            target_positions=target_facts,
            mappings=mapping_facts,
            existing_target_position_ids=target_read.existing_target_position_ids,
            account_id=account_id,
        )
        return HistoricalSellableDifferenceReport(
            user_id=user_id,
            account_id=account_id,
            portfolio_mapping_id=portfolio_mapping.mapping_id,
            database_alias=database_alias,
            reported_at=reported_at,
            scope_status="ok",
            reason_codes=(),
            rows=rows,
        )

    @staticmethod
    def _blocked_report(
        *,
        user_id: int,
        account_id: int,
        database_alias: str,
        reported_at: datetime,
        reason_code: str,
    ) -> HistoricalSellableDifferenceReport:
        """Return a generic scope refusal with no source or target row details."""

        return HistoricalSellableDifferenceReport(
            user_id=user_id,
            account_id=account_id,
            portfolio_mapping_id=None,
            database_alias=database_alias,
            reported_at=reported_at,
            scope_status="blocked",
            reason_codes=(reason_code,),
            rows=(),
        )
