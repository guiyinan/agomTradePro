"""Explicit no-tax scenario port for preexisting isolated trade/fee test fixtures.

This supplies a synthetic input to repository tests, just like their calendar,
prices and fee policies. It is never an ASH05 tax, current official window,
ordinary-owner financial, or NAV acceptance witness.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    TaxCashCoverageQuery,
    TaxCashCoverageSnapshot,
    TaxCashCoverageStatus,
)


class SyntheticTradeTaxCoverage:
    """Model no tax exposure only in the explicitly selected isolated fixture."""

    database_alias = "default"

    def __init__(self) -> None:
        self._issued: set[TaxCashCoverageSnapshot] = set()

    def read_locked(
        self, *, physical_account_id: int, owner_user_id: int, using: str
    ) -> TaxCashCoverageSnapshot:
        if using != self.database_alias:
            raise AssertionError("synthetic fixture cannot cross database aliases")
        checked = timezone.now()
        query = TaxCashCoverageQuery(
            physical_account_id,
            owner_user_id,
            f"synthetic-isolated-trade:{physical_account_id}",
            "synthetic-isolated-trade",
        )
        result = TaxCashCoverageSnapshot(
            query=query,
            currency_quantum=Decimal("0.01"),
            accepted_unpaid_tax=Decimal("0.00"),
            modeled_unapplied_tax_reserve=Decimal("0.00"),
            coverage_status=TaxCashCoverageStatus.COMPLETE,
            reason_codes=(),
            checked_at=checked,
            coverage_known_at=checked,
            valid_until=checked + timedelta(hours=1),
            coverage_sha256=hashlib.sha256(repr((query, checked)).encode()).hexdigest(),
            must_not_use_for_decision=True,
        )
        self._issued.add(result)
        return result

    def assert_still_current(
        self,
        snapshot: TaxCashCoverageSnapshot,
        *,
        using: str,
        expected_account_updated_at: datetime | None = None,
    ) -> None:
        if using != self.database_alias or snapshot not in self._issued:
            raise AssertionError("synthetic fixture proof was not issued in this fixture")
        snapshot.verify_for(snapshot.query, as_of=timezone.now())
        if expected_account_updated_at is not None and (
            expected_account_updated_at.tzinfo is None
            or expected_account_updated_at.utcoffset() is None
        ):
            raise AssertionError("synthetic fixture write clock must remain aware")


def install_synthetic_trade_tax_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject one explicit scenario only into otherwise unconfigured repository instances.

    Explicit readers, including a deliberate None negative, are preserved. This
    fixture is opt-in; no global conftest or production default is changed.
    """
    from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
        DjangoSimulatedTradeExecutionRepository,
    )
    from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
        DjangoSimulatedOrderFillRepository,
    )
    from apps.simulated_trading.infrastructure.order_reservation_repository import (
        DjangoSimulatedOrderReservationRepository,
    )

    reader = SyntheticTradeTaxCoverage()

    def install(repository: type) -> None:
        original = repository.__init__

        def initialize(self, *args, **kwargs):
            kwargs.setdefault("tax_cash_coverage_reader", reader)
            original(self, *args, **kwargs)

        monkeypatch.setattr(repository, "__init__", initialize)

    for repository in (
        DjangoSimulatedTradeExecutionRepository,
        DjangoSimulatedOrderReservationRepository,
        DjangoSimulatedOrderFillRepository,
    ):
        install(repository)


def install_synthetic_trade_tax_compositions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select the same explicit no-tax hypothesis in older isolated Owner-plan fixtures.

    These fixtures exercise market, risk, plan and reservation behavior; they
    have no corporate-action eligibility inputs. ASH05 financial, balance, NAV
    and current official-window goldens do not use this opt-in fixture.
    """
    import apps.simulated_trading.execution_settlement_composition as execution
    import apps.simulated_trading.local_daily_match_composition as match
    import apps.simulated_trading.owner_order_submission_composition as owner

    install_synthetic_trade_tax_coverage(monkeypatch)
    reader = SyntheticTradeTaxCoverage()

    def build(
        *, using: str = "default", runtime_environment: str | None = None
    ) -> SyntheticTradeTaxCoverage:
        del runtime_environment
        if using != reader.database_alias:
            raise AssertionError("synthetic tax scenario cannot cross database aliases")
        return reader

    monkeypatch.setattr(execution, "build_configured_tax_cash_coverage_reader", build)
    monkeypatch.setattr(owner, "build_configured_tax_cash_coverage_reader", build)
    monkeypatch.setattr(match, "DjangoCorporateActionTaxCashCoverageReader", build)
