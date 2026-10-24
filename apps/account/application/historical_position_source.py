"""Public Account application port for exact legacy position diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from core.exceptions import InvalidInputError


@dataclass(frozen=True)
class LegacyPositionSource:
    """One position from the explicitly selected legacy portfolio."""

    portfolio_id: int
    position_id: int
    asset_code: str
    total_quantity: Decimal | None
    quantity_known: bool
    quantity_reason_code: str | None
    is_closed: bool
    record_updated_at: datetime | None


@dataclass(frozen=True)
class LegacyPortfolioPositionRead:
    """Owner-filtered portfolio rows and the result of the requested DB route."""

    status: Literal["ready", "portfolio_unavailable", "database_route_mismatch"]
    database_alias: str | None
    positions: tuple[LegacyPositionSource, ...]


class LegacyPortfolioPositionRepository(Protocol):
    """Persistence port implemented only by Account Infrastructure."""

    def read_open_and_closed_positions(
        self,
        *,
        user_id: int,
        portfolio_id: int,
        database_alias: str,
    ) -> LegacyPortfolioPositionRead:
        """Read every source position in the exact user-owned portfolio."""


class LegacyPortfolioPositionReader(Protocol):
    """Public Application surface consumed by another App's composition root."""

    def read(
        self,
        *,
        user_id: int,
        portfolio_id: int,
        database_alias: str,
    ) -> LegacyPortfolioPositionRead:
        """Read one exact portfolio through Account's own repository."""


class ReadLegacyPortfolioPositions:
    """Expose an exact, read-only legacy position projection to other Applications."""

    def __init__(self, repository: LegacyPortfolioPositionRepository) -> None:
        self._repository = repository

    def read(
        self,
        *,
        user_id: int,
        portfolio_id: int,
        database_alias: str,
    ) -> LegacyPortfolioPositionRead:
        """Return source positions only when the selected owner and DB route match."""

        if (
            not isinstance(user_id, int)
            or isinstance(user_id, bool)
            or user_id <= 0
            or not isinstance(portfolio_id, int)
            or isinstance(portfolio_id, bool)
            or portfolio_id <= 0
            or not isinstance(database_alias, str)
            or not database_alias.strip()
        ):
            raise InvalidInputError("user, portfolio, and database alias must be explicit")
        return self._repository.read_open_and_closed_positions(
            user_id=user_id,
            portfolio_id=portfolio_id,
            database_alias=database_alias,
        )
