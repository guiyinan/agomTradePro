"""Exercise empty-origin tax coverage and BUY admission on a public owner account."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.db import connection, transaction
from django.test import override_settings
from django.utils import timezone

import tests.component.simulated_trading.test_execution_settlement_uow as trade_fixtures
from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    TaxCashCoverageReason,
    TaxCashCoverageSnapshot,
    TaxCashCoverageStatus,
)
from apps.simulated_trading.corporate_action_tax_cash_coverage_composition import (
    DjangoCorporateActionTaxCashCoverageReader,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedTradeSide,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_ownership_anchor_models import (
    SimulatedAccountOwnershipAnchorModel,
)
from core.exceptions import BusinessLogicError
from shared.config.secrets import get_secrets
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_owner_account_authority import (
    ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)
from tests.support.runtime_config import configure_critical_runtime
from tests.support.simulated_tax_model_native_account import (
    create_public_nonstaff_tax_owner_seed,
)
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = [
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Empty-origin tax coverage requires the migrated PostgreSQL schema",
    ),
    pytest.mark.django_db(
        transaction=True,
        available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
    ),
]


@dataclass(frozen=True, slots=True)
class _ActualClock:
    """Retain the actual Django clock after the public-owner setup clock is restored."""

    read_now: Callable[[], datetime]

    def now(self) -> datetime:
        """Return a fresh aware operation time rather than a frozen plan timestamp."""
        return self.read_now().astimezone(UTC)


class _SyntheticUnknownCoverageReader(DjangoCorporateActionTaxCashCoverageReader):
    """Downgrade only an actual complete read to a labeled synthetic unknown result."""

    def __init__(self, *, runtime_environment: str, using: str = "default") -> None:
        super().__init__(runtime_environment=runtime_environment, using=using)
        self.read_count = 0

    def read_locked(
        self,
        *,
        physical_account_id: int,
        owner_user_id: int,
        using: str,
    ) -> TaxCashCoverageSnapshot:
        """Require real complete current evidence before injecting UNKNOWN for the consumer test."""
        self.read_count += 1
        actual = super().read_locked(
            physical_account_id=physical_account_id,
            owner_user_id=owner_user_id,
            using=using,
        )
        if actual.coverage_status is not TaxCashCoverageStatus.COMPLETE:
            raise AssertionError("synthetic UNKNOWN test requires an actual complete source read")
        return replace(
            actual,
            coverage_status=TaxCashCoverageStatus.UNKNOWN,
            reason_codes=(TaxCashCoverageReason.HISTORY_UNVERIFIED,),
        )


def _counts(account_id: int) -> tuple[int, int, int, int, int]:
    return (
        PositionModel.objects.filter(account_id=account_id).count(),
        SimulatedTradeModel.objects.filter(account_id=account_id).count(),
        CorporateActionPostingModel.objects.filter(account_id=account_id).count(),
        CorporateActionTaxAssessmentHeaderModel.objects.filter(account_id=account_id).count(),
        SimulatedOrderReservationModel.objects.filter(account_id=account_id).count(),
    )


def test_public_empty_asset_owner_coverage_and_synthetic_unknown_blocks_buy_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use real Account evidence; execution-market fixtures remain explicitly synthetic."""
    assert connection.vendor == "postgresql"
    actual_clock = timezone.now
    setup_at = actual_clock().astimezone(UTC)
    try:
        with isolated_task_channels():
            monkeypatch.setenv(
                "AGOMTRADEPRO_ENCRYPTION_KEY",
                base64.urlsafe_b64encode(b"t" * 32).decode("ascii"),
            )
            get_secrets.cache_clear()
            with monkeypatch.context() as setup_clock:
                setup_clock.setattr(timezone, "now", lambda: setup_at)
                configure_critical_runtime()
                with override_settings(ROOT_URLCONF="tests.support.ash07_owner_source_test_urls"):
                    owner_seed = create_public_nonstaff_tax_owner_seed(as_of=setup_at)
            # All coverage, source-window, and write checks below use the real restored clock.
            assert timezone.now() >= setup_at
            assert owner_seed.owner.is_staff is False
            assert owner_seed.owner.is_superuser is False
            assert owner_seed.account.user_id == owner_seed.owner.pk
            assert type(owner_seed.account.pk) is int
            account_id = owner_seed.account.pk
            owner_id = owner_seed.owner.pk
            account = SimulatedAccountModel.objects.get(pk=account_id, user_id=owner_id)
            cash_before = account.current_cash
            updated_at_before = account.updated_at
            anchor = SimulatedAccountOwnershipAnchorModel.objects.get(account_id=account_id)
            assert anchor.owner_user_id == owner_id
            assert anchor.quantity == Decimal("0.000000")
            assert anchor.anchor_id == f"simulated-account-zero-origin.v1:{account_id}"
            assert _counts(account_id) == (0, 0, 0, 0, 0)

            coverage = DjangoCorporateActionTaxCashCoverageReader(
                runtime_environment=owner_seed.environment,
                using="default",
            )
            with transaction.atomic(using="default"):
                locked_account = SimulatedAccountModel.objects.select_for_update().get(
                    pk=account_id,
                    user_id=owner_id,
                    account_type="simulated",
                )
                snapshot = coverage.read_locked(
                    physical_account_id=account_id,
                    owner_user_id=owner_id,
                    using="default",
                )
                entitlements = coverage.read_current_entitlement_coverage(
                    snapshot,
                    using="default",
                )
                assert locked_account.current_cash == cash_before
            assert snapshot.coverage_status is TaxCashCoverageStatus.COMPLETE
            assert snapshot.accepted_unpaid_tax == Decimal("0")
            assert snapshot.modeled_unapplied_tax_reserve == Decimal("0")
            assert snapshot.tax_cash_unavailable == Decimal("0")
            assert snapshot.must_not_use_for_decision is True
            assert entitlements == ()
            assert snapshot.coverage_known_at is not None
            assert snapshot.coverage_known_at <= snapshot.checked_at < snapshot.valid_until
            assert snapshot.checked_at <= timezone.now()

            # The established execution fixture supplies synthetic settlement-market
            # inputs only; the account, cash reader, and reservation write are real.
            as_of = timezone.now().astimezone(UTC)
            monkeypatch.setattr(trade_fixtures, "AS_OF", as_of)
            fee_config = FeeConfigModel.objects.create(
                config_name=f"ash05-empty-owner-fees-{uuid4().hex}",
                asset_type="equity",
                commission_rate_buy=0.0003,
                commission_rate_sell=0.0003,
                min_commission=1.0,
                stamp_duty_rate=0.001,
                transfer_fee_rate=0.00002,
                min_transfer_fee=0.0,
                slippage_rate=0.001,
                is_default=False,
                is_active=False,
            )
            trade_fixtures._seed_fee_policy(fee_config)

            original_calendar = trade_fixtures._calendar

            def current_synthetic_calendar(
                *,
                as_of: datetime,
                open_dates: set[date],
                exchange: str = "SH",
                start: date = date(2026, 10, 16),
                end: date = date(2026, 10, 21),
            ):
                del open_dates, start, end
                local_today = as_of.astimezone(ZoneInfo("Asia/Shanghai")).date()
                calendar_start = local_today - timedelta(days=7)
                calendar_end = local_today + timedelta(days=7)
                sessions = {
                    calendar_start + timedelta(days=offset)
                    for offset in range((calendar_end - calendar_start).days + 1)
                    if (calendar_start + timedelta(days=offset)).weekday() < 5
                }
                return original_calendar(
                    as_of=as_of,
                    open_dates=sessions,
                    exchange=exchange,
                    start=calendar_start,
                    end=calendar_end,
                )

            monkeypatch.setattr(trade_fixtures, "_calendar", current_synthetic_calendar)
            intent = trade_fixtures._intent(
                user_id=owner_id,
                account_id=account_id,
                key=f"ash05-empty-owner-buy-{uuid4().hex}",
                side=SimulatedTradeSide.BUY,
            )
            bundle = trade_fixtures._bundle(as_of=as_of)
            execution = DjangoSimulatedTradeExecutionRepository(using="default")
            plan = trade_fixtures._v2_plan(
                repository=execution,
                intent=intent,
                as_of=as_of,
                source_exchange="SH",
                bundle=bundle,
            )
            fees = plan.fee_policy_v2.calculate_for(
                asset_type=intent.asset_type,
                market=intent.market,
                board=intent.board,
                side=intent.side,
                amount=plan.amount,
                as_of=as_of,
            )
            reservations = DjangoSimulatedOrderReservationRepository(
                using="default",
                tax_cash_coverage_reader=coverage,
            )
            result = reservations.reserve_order(
                plan=plan,
                execution_bundle=bundle,
                fee_budget=fees.total_fee,
                clock=_ActualClock(actual_clock),
            )
            assert result.book.book_cash == cash_before
            assert result.book.tax_cash_unavailable == Decimal("0")
            assert result.book.available_cash == cash_before - plan.amount - fees.total_fee
            assert result.reservation.identity.idempotency_key == intent.idempotency_key
            account.refresh_from_db()
            assert account.current_cash == cash_before
            assert account.updated_at == updated_at_before
            assert _counts(account_id) == (0, 0, 0, 0, 1)

            # This negative is a synthetic UNKNOWN input based on another complete
            # actual coverage read; it does not claim the source lease expired.
            unknown_reader = _SyntheticUnknownCoverageReader(
                runtime_environment=owner_seed.environment,
                using="default",
            )
            unknown_reservations = DjangoSimulatedOrderReservationRepository(
                using="default",
                tax_cash_coverage_reader=unknown_reader,
            )
            retry_intent = replace(intent, idempotency_key=f"unknown-coverage-{uuid4().hex}")
            retry_plan = replace(plan, intent=retry_intent)
            before_failed_hold = _counts(account_id)
            with pytest.raises(BusinessLogicError) as error:
                unknown_reservations.reserve_order(
                    plan=retry_plan,
                    execution_bundle=bundle,
                    fee_budget=fees.total_fee,
                    clock=_ActualClock(actual_clock),
                )
            assert error.value.code == "ORDER_TAX_CASH_COVERAGE_UNAVAILABLE"
            assert unknown_reader.read_count >= 1
            assert _counts(account_id) == before_failed_hold == (0, 0, 0, 0, 1)
            account.refresh_from_db()
            assert account.current_cash == cash_before
            assert account.updated_at == updated_at_before
    finally:
        get_secrets.cache_clear()
