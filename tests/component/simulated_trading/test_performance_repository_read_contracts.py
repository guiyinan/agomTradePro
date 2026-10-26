"""Current-model ORM read contracts for correction-aware performance."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Protocol, cast

import pytest
from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionAccountHistoryProjection,
    FeeCorrectionHistoryRepositoryProtocol,
    FeeCorrectionRequest,
)
from apps.simulated_trading.application.performance_use_cases import (
    GetAccountPerformanceReportUseCase,
)
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_prefix import (
    fee_correction_account_genesis_sha256,
)
from apps.simulated_trading.infrastructure.models import (
    DailyNetValueModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.performance_repositories import (
    DjangoPerformanceAccountRepository,
    DjangoPerformanceDailyNetValueRepository,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)


class _LedgerFixtureLike(Protocol):
    """Typed shape returned by the existing fee-correction component helper."""

    account: SimulatedAccountModel
    trade: SimulatedTradeModel
    owner: AuthenticatedFeeCorrectionPrincipalProtocol
    repository: FeeCorrectionHistoryRepositoryProtocol
    request: FeeCorrectionRequest


class _RecordingCorrectionHistory:
    """Record the actual repository read while delegating all proof checks."""

    def __init__(self, delegate: FeeCorrectionHistoryRepositoryProtocol) -> None:
        self._delegate = delegate
        self.calls: list[tuple[int, datetime]] = []

    def get_account_history(
        self,
        *,
        account_id: int,
        as_of: datetime,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FeeCorrectionAccountHistoryProjection:
        """Forward the typed request and retain its account-local cutoff."""

        self.calls.append((account_id, as_of))
        return self._delegate.get_account_history(
            account_id=account_id,
            as_of=as_of,
            start_date=start_date,
            end_date=end_date,
        )


class _NoCashFlows:
    """Typed empty cash-flow collaborator for a real report use case."""

    def list_for_account(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        del account_id, start_date, end_date
        return []


class _NoBenchmarks:
    """Typed empty benchmark collaborator for a real report use case."""

    def list_active(self, account_id: int) -> list[dict[str, Any]]:
        del account_id
        return []


class _NoMarketData:
    """Typed market-data collaborator that is unused without benchmarks."""

    def get_close_price(self, asset_code: str, trade_date: date) -> float | None:
        del asset_code, trade_date
        return None

    def get_index_daily_returns(
        self,
        index_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, float]]:
        del index_code, start_date, end_date
        return []

    def get_index_cumulative_return(
        self,
        index_code: str,
        start_date: date,
        end_date: date,
    ) -> float | None:
        del index_code, start_date, end_date
        return None


class _NoClosedTrades:
    """Typed empty trade-history collaborator for performance reporting."""

    def list_closed_trades(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        del account_id, start_date, end_date
        return []


def _create_daily_snapshot(
    *,
    account: SimulatedAccountModel,
    trade: SimulatedTradeModel,
    record_date: date,
    watermark: int | None = 0,
) -> DailyNetValueModel:
    """Persist one pre-correction daily snapshot with a valid known or legacy watermark."""

    assert trade.execution_date is not None
    assert trade.execution_date < record_date, "daily snapshot must follow its BUY fixture"
    cash = account.initial_capital - trade.total_cost
    market_value = trade.amount
    watermark_sha256 = fee_correction_account_genesis_sha256(account.pk) if watermark == 0 else None
    return DailyNetValueModel.objects.create(
        account=account,
        record_date=record_date,
        correction_event_watermark=watermark,
        correction_event_watermark_sha256=watermark_sha256,
        net_value=cash + market_value,
        cash=cash,
        market_value=market_value,
        daily_return=0.0,
        cumulative_return=0.0,
        drawdown=0.0,
        total_trades=1,
        positions_count=1,
    )


def _create_real_correction() -> tuple[_LedgerFixtureLike, SimulatedFeeCorrectionEventModel]:
    """Create a persisted correction through the existing owner/evidence/use-case path."""

    from tests.component.simulated_trading.test_fee_correction_repository import (
        _CountingClock,
        _run_apply,
        _seed_ledger,
    )

    ledger = cast(
        _LedgerFixtureLike,
        _seed_ledger(
            commission=Decimal("0.05"),
            revised_commission=Decimal("0.07"),
        ),
    )
    clock = _CountingClock(timezone.now() + timedelta(days=2, seconds=1))
    receipt = _run_apply(ledger, clock).execute(ledger.request, principal=ledger.owner)
    event = SimulatedFeeCorrectionEventModel.objects.get(pk=receipt.event_id)
    return ledger, event


@pytest.mark.django_db(transaction=True)
def test_daily_repository_projects_full_history_before_start_window_and_uses_end_of_day() -> None:
    """An output-window row uses prior history and only events through end_date."""

    ledger, event = _create_real_correction()
    prior_date = event.posting_date - timedelta(days=1)
    _create_daily_snapshot(
        account=ledger.account,
        trade=ledger.trade,
        record_date=prior_date,
    )
    _create_daily_snapshot(
        account=ledger.account,
        trade=ledger.trade,
        record_date=event.posting_date,
    )

    history = _RecordingCorrectionHistory(ledger.repository)
    repository = DjangoPerformanceDailyNetValueRepository(correction_history=history)
    rows = repository.list_range(
        account_id=ledger.account.pk,
        start_date=event.posting_date,
        end_date=event.posting_date,
    )

    assert [row["record_date"] for row in rows] == [event.posting_date]
    row = rows[0]
    original_cash = ledger.account.initial_capital - ledger.trade.total_cost
    original_total = original_cash + ledger.trade.amount
    assert row["original_cash"] == pytest.approx(float(original_cash))
    assert row["original_net_value"] == pytest.approx(float(original_total))
    assert row["cash"] == pytest.approx(float(original_cash + event.cash_delta))
    assert row["net_value"] == pytest.approx(float(original_total + event.cash_delta))
    assert row["correction_coverage_known"] is True
    assert row["correction_overlay_applied"] is True
    expected_daily_return = float(event.cash_delta / original_total * Decimal("100"))
    assert row["daily_return"] == pytest.approx(expected_daily_return)
    assert history.calls == [
        (
            ledger.account.pk,
            timezone.make_aware(datetime.combine(event.posting_date, time.max)),
        )
    ]


@pytest.mark.django_db(transaction=True)
def test_late_real_correction_blocks_report_metrics_after_last_snapshot() -> None:
    """A real event after the last persisted observation makes dependent metrics unknown."""

    ledger, event = _create_real_correction()
    last_snapshot_date = event.posting_date - timedelta(days=1)
    _create_daily_snapshot(
        account=ledger.account,
        trade=ledger.trade,
        record_date=last_snapshot_date,
    )
    repository = DjangoPerformanceDailyNetValueRepository(
        correction_history=_RecordingCorrectionHistory(ledger.repository)
    )
    use_case = GetAccountPerformanceReportUseCase(
        account_repo=DjangoPerformanceAccountRepository(),
        daily_net_value_repo=repository,
        cash_flow_repo=_NoCashFlows(),
        benchmark_repo=_NoBenchmarks(),
        market_data_repo=_NoMarketData(),
        trade_history_repo=_NoClosedTrades(),
    )

    report = use_case.execute(
        account_id=ledger.account.pk,
        start_date=last_snapshot_date,
        end_date=event.posting_date,
    )

    assert report.returns.twr is None
    assert report.returns.annualized_twr is None
    assert report.returns.mwr is None
    assert report.risk.volatility is None
    assert report.risk.downside_volatility is None
    assert report.risk.max_drawdown is None
    assert report.ratios.sharpe is None
    assert report.ratios.sortino is None
    assert report.ratios.calmar is None
    assert any(
        warning.startswith("FEE_CORRECTION_AFTER_LAST_DAILY_SNAPSHOT:")
        for warning in report.warnings
    )


@pytest.mark.django_db(transaction=True)
def test_empty_requested_window_keeps_real_orm_read_and_end_date_cutoff() -> None:
    """A prior ORM row outside the requested window yields no observations."""

    from tests.component.simulated_trading.test_fee_correction_repository import _seed_ledger

    ledger = cast(
        _LedgerFixtureLike,
        _seed_ledger(
            commission=Decimal("0.05"),
            revised_commission=Decimal("0.07"),
        ),
    )
    snapshot_date = ledger.trade.execution_date + timedelta(days=1)
    _create_daily_snapshot(
        account=ledger.account,
        trade=ledger.trade,
        record_date=snapshot_date,
    )
    history = _RecordingCorrectionHistory(ledger.repository)
    repository = DjangoPerformanceDailyNetValueRepository(correction_history=history)
    start_date = snapshot_date + timedelta(days=1)
    end_date = snapshot_date + timedelta(days=2)

    rows = repository.list_range(
        account_id=ledger.account.pk,
        start_date=start_date,
        end_date=end_date,
    )

    assert rows == []
    assert DailyNetValueModel.objects.filter(account_id=ledger.account.pk).count() == 1
    assert history.calls == [
        (ledger.account.pk, timezone.make_aware(datetime.combine(end_date, time.max)))
    ]


@pytest.mark.django_db(transaction=True)
def test_legacy_null_watermark_with_real_correction_remains_unknown_not_zero() -> None:
    """Legacy null coverage blocks effective metrics instead of applying from genesis."""

    ledger, event = _create_real_correction()
    snapshot = _create_daily_snapshot(
        account=ledger.account,
        trade=ledger.trade,
        record_date=event.posting_date,
        watermark=None,
    )
    history = _RecordingCorrectionHistory(ledger.repository)
    repository = DjangoPerformanceDailyNetValueRepository(correction_history=history)

    rows = repository.list_range(
        account_id=ledger.account.pk,
        start_date=event.posting_date,
        end_date=event.posting_date,
    )

    assert len(rows) == 1
    row = rows[0]
    assert snapshot.correction_event_watermark is None
    assert snapshot.correction_event_watermark_sha256 is None
    assert row["correction_event_watermark"] is None
    assert row["correction_event_watermark_sha256"] is None
    assert row["correction_coverage_known"] is False
    assert row["correction_overlay_applied"] is False
    assert row["effective_metrics_known"] is False
    assert row["effective_metrics_reason_code"] == "FEE_CORRECTION_COVERAGE_UNKNOWN"
    assert row["daily_return"] is None
    assert row["cumulative_return"] is None
    assert row["drawdown"] is None
    assert row["cash"] == pytest.approx(float(snapshot.cash))
    assert row["net_value"] == pytest.approx(float(snapshot.net_value))
    assert row["original_cash"] == pytest.approx(float(snapshot.cash))
    assert row["original_net_value"] == pytest.approx(float(snapshot.net_value))
