"""Read exact legacy position fields for the Account Application port."""

from __future__ import annotations

from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import router

from apps.account.application.historical_position_source import (
    LegacyPortfolioPositionRead,
    LegacyPositionSource,
)
from apps.account.domain.historical_position_quantity import normalize_legacy_share_quantity
from apps.account.infrastructure.portfolio_models import PortfolioModel, PositionModel


class DjangoLegacyPortfolioPositionRepository:
    """Account-owned, owner-filtered ORM reader for historical position diagnostics."""

    def read_open_and_closed_positions(
        self,
        *,
        user_id: int,
        portfolio_id: int,
        database_alias: str,
    ) -> LegacyPortfolioPositionRead:
        """Read all rows in a user-owned portfolio without omitting closed holdings."""

        routed_aliases = {
            alias
            for alias in (
                router.db_for_read(PortfolioModel),
                router.db_for_read(PositionModel),
                router.db_for_read(get_user_model()),
            )
            if alias is not None
        }
        if len(routed_aliases) > 1 or (routed_aliases and routed_aliases != {database_alias}):
            return LegacyPortfolioPositionRead(
                status="database_route_mismatch",
                database_alias=None,
                positions=(),
            )

        portfolio_exists = (
            PortfolioModel._default_manager.using(database_alias)
            .filter(
                pk=portfolio_id,
                user_id=user_id,
            )
            .exists()
        )
        if not portfolio_exists:
            return LegacyPortfolioPositionRead(
                status="portfolio_unavailable",
                database_alias=database_alias,
                positions=(),
            )

        records = (
            PositionModel._default_manager.using(database_alias)
            .filter(
                portfolio_id=portfolio_id,
                portfolio__user_id=user_id,
            )
            .only(
                "id",
                "portfolio_id",
                "asset_code",
                "shares",
                "is_closed",
                "updated_at",
            )
            .order_by("pk")
        )
        positions: list[LegacyPositionSource] = []
        for record in records:
            quantity = normalize_legacy_share_quantity(record.shares)
            positions.append(
                LegacyPositionSource(
                    portfolio_id=int(record.portfolio_id),
                    position_id=int(record.pk),
                    asset_code=str(record.asset_code),
                    total_quantity=quantity.value,
                    quantity_known=quantity.known,
                    quantity_reason_code=quantity.reason_code,
                    is_closed=bool(record.is_closed),
                    record_updated_at=_aware_datetime(record.updated_at),
                )
            )

        return LegacyPortfolioPositionRead(
            status="ready",
            database_alias=database_alias,
            positions=tuple(positions),
        )


def _aware_datetime(value: object) -> datetime | None:
    """Keep a local record timestamp only when the ORM boundary is timezone-aware."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value
