"""Owner-side adapter exposing exact SimulatedTrading row sources to Account."""

from __future__ import annotations

from datetime import datetime

from apps.account.application.physical_account_row_observation import (
    ExactPhysicalSimulatedAccountRow,
)
from apps.simulated_trading.application.simulated_account_row_source import (
    SimulatedAccountRowSourceCorruption,
    SimulatedAccountRowSourceRepository,
    SimulatedAccountRowSourceUnavailable,
)


class DjangoExactPhysicalSimulatedAccountRowProvider:
    """Map only an exact current owner-ledger head into the Account DTO."""

    __slots__ = ("_repository",)

    def __init__(self, repository: SimulatedAccountRowSourceRepository) -> None:
        self._repository = repository

    def get_exact_current(
        self,
        *,
        source_id: str,
        source_version: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> ExactPhysicalSimulatedAccountRow | None:
        """Return an unmodified DTO only when identity winner equals final head."""

        try:
            winner = self._repository.get_winner(
                source_id=source_id,
                source_version=source_version,
                as_of=as_of,
            )
            if winner is None:
                return None
            head = self._repository.get_current_head(
                source_id=source_id,
                account_namespace=account_namespace,
                account_id=account_id,
                underlying_unified_account_namespace=(underlying_unified_account_namespace),
                underlying_unified_account_id=underlying_unified_account_id,
                as_of=as_of,
            )
        except SimulatedAccountRowSourceUnavailable:
            return None
        except SimulatedAccountRowSourceCorruption:
            raise
        if head is None or head != winner:
            return None
        source = winner.source
        selectors = (
            source.source_id,
            source.source_version,
            source.account_namespace,
            source.account_id,
            source.underlying_unified_account_namespace,
            source.underlying_unified_account_id,
        )
        expected = (
            source_id,
            source_version,
            account_namespace,
            account_id,
            underlying_unified_account_namespace,
            underlying_unified_account_id,
        )
        if selectors != expected:
            raise SimulatedAccountRowSourceCorruption(
                "account physical-row source selector substitution"
            )
        if not source.is_current_at(as_of):
            return None
        value = ExactPhysicalSimulatedAccountRow(
            source_id=source.source_id,
            source_version=source.source_version,
            content_hash=source.content_hash,
            account_namespace=source.account_namespace,
            account_id=source.account_id,
            underlying_unified_account_namespace=(source.underlying_unified_account_namespace),
            underlying_unified_account_id=source.underlying_unified_account_id,
            row_user_id=source.row_user_id,
            account_type=source.raw_account_type,
            is_active=source.is_active,
            row_created_at=source.row_created_at,
            row_updated_at=source.row_updated_at,
            observed_at=source.observed_at,
            valid_until=source.valid_until,
        )
        ExactPhysicalSimulatedAccountRow.__post_init__(value)
        return value


__all__ = ["DjangoExactPhysicalSimulatedAccountRowProvider"]
