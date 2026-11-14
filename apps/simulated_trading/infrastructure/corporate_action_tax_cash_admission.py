"""Require independently complete tax exposure before admitting a new simulated cash debit."""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    CorporateActionTaxCashCoverageReader,
    TaxCashCoverageSnapshot,
    TaxCashCoverageStatus,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)


def _blocked() -> SimulatedTradeExecutionBlocked:
    return SimulatedTradeExecutionBlocked(
        "尚未完整核对本账户的模拟税款责任，暂不能占用或支出这笔现金。",
        code="ORDER_TAX_CASH_COVERAGE_UNAVAILABLE",
    )


def require_current_tax_cash_coverage(
    *,
    reader: CorporateActionTaxCashCoverageReader | None,
    physical_account_id: int,
    owner_user_id: int,
    using: str,
) -> TaxCashCoverageSnapshot:
    """Read exact current account coverage; absent debt rows alone never clear admission.

    The caller owns the transaction and already locked the active physical
    account. The injected reader independently resolves its canonical mapping.
    This path issues no assessment, collection, consent or financial command.
    """
    if (
        reader is None
        or reader.database_alias != using
        or type(physical_account_id) is not int
        or physical_account_id <= 0
        or type(owner_user_id) is not int
        or owner_user_id <= 0
    ):
        raise _blocked()
    snapshot = reader.read_locked(
        physical_account_id=physical_account_id, owner_user_id=owner_user_id, using=using
    )
    if (
        type(snapshot) is not TaxCashCoverageSnapshot
        or snapshot.query.physical_account_id != physical_account_id
        or snapshot.query.owner_user_id != owner_user_id
    ):
        raise _blocked()
    snapshot.verify_for(snapshot.query, as_of=timezone.now())
    if (
        snapshot.coverage_status is not TaxCashCoverageStatus.COMPLETE
        or snapshot.tax_cash_unavailable is None
    ):
        raise _blocked()
    return snapshot


def assert_tax_cash_coverage_before_commit(
    *,
    reader: CorporateActionTaxCashCoverageReader | None,
    snapshot: TaxCashCoverageSnapshot,
    using: str,
    expected_account_updated_at: datetime | None = None,
) -> None:
    """Reject source changes and expiry after the final source I/O, while rollback remains possible."""
    if (
        reader is None
        or reader.database_alias != using
        or type(snapshot) is not TaxCashCoverageSnapshot
    ):
        raise _blocked()
    snapshot.verify_for(snapshot.query, as_of=timezone.now())
    if snapshot.tax_cash_unavailable is None:
        raise _blocked()
    if expected_account_updated_at is None:
        reader.assert_still_current(snapshot, using=using)
    else:
        if (
            type(expected_account_updated_at) is not datetime
            or expected_account_updated_at.tzinfo is None
            or expected_account_updated_at.utcoffset() is None
        ):
            raise _blocked()
        reader.assert_still_current(
            snapshot, using=using, expected_account_updated_at=expected_account_updated_at
        )
    snapshot.verify_for(snapshot.query, as_of=timezone.now())
