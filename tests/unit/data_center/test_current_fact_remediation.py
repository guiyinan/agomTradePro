"""Fail-closed contracts for current-fact remediation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from apps.data_center.application.current_fact_remediation import (
    CompletedSessionPriceBarUseCase,
    CoreCurrentFactRefreshUseCase,
    FinancialAvailabilityBackfillPreview,
    FinancialAvailabilityBackfillResult,
    FinancialAvailabilityBackfillUseCase,
)
from apps.data_center.domain.entities import QuoteSnapshot

STARTED_AT = datetime(2026, 8, 30, 1, 0, tzinfo=UTC)
COMPLETED_AT = STARTED_AT + timedelta(minutes=5)
SESSION_DATE = date(2026, 8, 28)
SESSION_CLOSE = datetime(2026, 8, 28, 7, 0, tzinfo=UTC)


@contextmanager
def _transaction():
    yield


class _FinancialRepository:
    def __init__(
        self,
        before: FinancialAvailabilityBackfillPreview,
        after: FinancialAvailabilityBackfillPreview,
    ) -> None:
        self.previews = [before, after]
        self.updated = 0

    def preview_availability_backfill(self, *, asset_codes, recorded_at):
        del asset_codes, recorded_at
        return self.previews.pop(0)

    def backfill_available_at_from_report_date(self, *, asset_codes, recorded_at):
        del asset_codes, recorded_at
        self.updated += 1
        return 2


def _availability_preview(
    *,
    missing: int = 2,
    eligible: int = 2,
    future_reports: int = 0,
    future_availability: int = 0,
) -> FinancialAvailabilityBackfillPreview:
    return FinancialAvailabilityBackfillPreview(
        missing_row_count=missing,
        eligible_row_count=eligible,
        eligible_asset_count=1 if eligible else 0,
        unresolved_row_count=0,
        future_report_date_count=future_reports,
        future_available_at_count=future_availability,
        oldest_report_date=date(2026, 3, 31),
        newest_report_date=date(2026, 6, 30),
    )


def test_financial_availability_repair_is_exact_and_idempotent() -> None:
    repository = _FinancialRepository(
        _availability_preview(),
        _availability_preview(missing=0, eligible=0),
    )
    use_case = FinancialAvailabilityBackfillUseCase(
        repository=repository,
        transaction=_transaction,
    )

    result = use_case.execute(
        asset_codes=["000001.SZ"],
        recorded_at=STARTED_AT,
    )

    assert result.updated_row_count == 2
    assert result.after.eligible_row_count == 0
    assert repository.updated == 1


def test_financial_availability_repair_rejects_future_evidence() -> None:
    before = _availability_preview(future_reports=1)
    repository = _FinancialRepository(before, before)
    use_case = FinancialAvailabilityBackfillUseCase(
        repository=repository,
        transaction=_transaction,
    )

    with pytest.raises(ValueError, match="future boundary"):
        use_case.execute(asset_codes=["000001.SZ"], recorded_at=STARTED_AT)

    assert repository.updated == 0


class _QuoteRepository:
    def __init__(self, quotes: list[QuoteSnapshot]) -> None:
        self.quotes = quotes

    def list_latest_for_asset_codes(self, asset_codes):
        del asset_codes
        return self.quotes


class _PriceRepository:
    def __init__(self) -> None:
        self.bars = []

    def bulk_upsert(self, bars):
        self.bars = bars
        return len(bars)


def _quote(asset_code: str, *, observed_at: datetime = SESSION_CLOSE) -> QuoteSnapshot:
    return QuoteSnapshot(
        asset_code=asset_code,
        snapshot_at=observed_at,
        fetched_at=COMPLETED_AT,
        current_price=10.5,
        open=10.0,
        high=11.0,
        low=9.5,
        volume=100.0,
        amount=1_000.0,
        source="eastmoney",
    )


def test_completed_session_quotes_materialize_exact_daily_bars() -> None:
    price_repository = _PriceRepository()
    use_case = CompletedSessionPriceBarUseCase(
        quote_repository=_QuoteRepository([_quote("000001.SZ"), _quote("600000.SH")]),
        price_repository=price_repository,
        transaction=_transaction,
    )

    result = use_case.execute(
        asset_codes=["600000.SH", "000001.SZ"],
        session_date=SESSION_DATE,
        recorded_at=COMPLETED_AT,
    )

    assert result.preview.ready is True
    assert result.stored_count == 2
    assert {bar.asset_code for bar in price_repository.bars} == {
        "000001.SZ",
        "600000.SH",
    }
    assert all(bar.bar_date == SESSION_DATE for bar in price_repository.bars)


def test_completed_session_materialization_rejects_missing_or_old_quotes() -> None:
    use_case = CompletedSessionPriceBarUseCase(
        quote_repository=_QuoteRepository(
            [_quote("000001.SZ", observed_at=SESSION_CLOSE - timedelta(days=1))]
        ),
        price_repository=_PriceRepository(),
        transaction=_transaction,
    )

    preview = use_case.preview(
        asset_codes=["000001.SZ", "600000.SH"],
        session_date=SESSION_DATE,
        recorded_at=COMPLETED_AT,
    )

    assert preview.ready is False
    assert preview.missing_asset_codes == ("600000.SH",)
    assert preview.invalid_asset_codes == ("000001.SZ",)


class _SyncUseCase:
    def __init__(self, result) -> None:
        self.result = result
        self.requests = []

    def execute(self, request=None, **kwargs):
        self.requests.append(request if request is not None else kwargs)
        return self.result


class _FinancialAvailability:
    def preview(self, **kwargs):
        del kwargs
        return _availability_preview()

    def execute(self, **kwargs):
        del kwargs
        before = _availability_preview()
        after = _availability_preview(missing=0, eligible=0)
        return FinancialAvailabilityBackfillResult(2, before, after)


class _CompletedPrices:
    def preview(self, **kwargs):
        return SimpleNamespace(ready=True, to_dict=lambda: kwargs)

    def execute(self, **kwargs):
        return SimpleNamespace(to_dict=lambda: kwargs)


class _Publications:
    def __init__(self) -> None:
        self.execute_kwargs = None

    def preview(self, **kwargs):
        return SimpleNamespace(ready=True, to_dict=lambda: kwargs)

    def execute(self, **kwargs):
        self.execute_kwargs = kwargs
        return SimpleNamespace(to_dict=lambda: {"publication_ids": ["all"]})


def test_core_refresh_batches_then_publishes_at_completion_time() -> None:
    quote_sync = _SyncUseCase(SimpleNamespace(stored_count=2))
    price_sync = _SyncUseCase(SimpleNamespace(stored_count=1))
    valuation_sync = _SyncUseCase(
        SimpleNamespace(
            stored_count=2,
            succeeded_asset_codes=["000001.SZ", "600000.SH"],
        )
    )
    financial_sync = _SyncUseCase(SimpleNamespace(stored_count=4))
    publications = _Publications()
    use_case = CoreCurrentFactRefreshUseCase(
        provider_id=7,
        quote_sync_factory=lambda: quote_sync,
        price_sync_factory=lambda: price_sync,
        valuation_sync_factory=lambda: valuation_sync,
        financial_sync_factory=lambda: financial_sync,
        financial_availability=_FinancialAvailability(),
        completed_session_prices=_CompletedPrices(),
        publications=publications,
        clock=lambda: COMPLETED_AT,
    )

    result = use_case.execute(
        asset_codes=["600000.SH", "000001.SZ"],
        session_date=SESSION_DATE,
        recorded_at=STARTED_AT,
        batch_size=2,
    )

    assert result.quote_stored_count == 2
    assert result.valuation_stored_count == 2
    assert len(quote_sync.requests) == 1
    assert publications.execute_kwargs["published_at"] == COMPLETED_AT


def test_core_refresh_stops_before_publication_on_incomplete_quote_batch() -> None:
    publications = _Publications()
    use_case = CoreCurrentFactRefreshUseCase(
        provider_id=7,
        quote_sync_factory=lambda: _SyncUseCase(SimpleNamespace(stored_count=1)),
        price_sync_factory=lambda: _SyncUseCase(SimpleNamespace(stored_count=1)),
        valuation_sync_factory=lambda: _SyncUseCase(
            SimpleNamespace(
                stored_count=2,
                succeeded_asset_codes=["000001.SZ", "600000.SH"],
            )
        ),
        financial_sync_factory=lambda: _SyncUseCase(SimpleNamespace(stored_count=4)),
        financial_availability=_FinancialAvailability(),
        completed_session_prices=_CompletedPrices(),
        publications=publications,
        clock=lambda: COMPLETED_AT,
    )

    with pytest.raises(ValueError, match="quote provider batch incomplete"):
        use_case.execute(
            asset_codes=["000001.SZ", "600000.SH"],
            session_date=SESSION_DATE,
            recorded_at=STARTED_AT,
            batch_size=2,
        )

    assert publications.execute_kwargs is None


def test_core_refresh_preview_does_not_resolve_write_sync_factories() -> None:
    def forbidden_factory():
        raise AssertionError("write sync factory must stay lazy during preview")

    use_case = CoreCurrentFactRefreshUseCase(
        provider_id=7,
        quote_sync_factory=forbidden_factory,
        price_sync_factory=forbidden_factory,
        valuation_sync_factory=forbidden_factory,
        financial_sync_factory=forbidden_factory,
        financial_availability=_FinancialAvailability(),
        completed_session_prices=_CompletedPrices(),
        publications=_Publications(),
        clock=lambda: COMPLETED_AT,
    )

    preview = use_case.preview(
        asset_codes=["000001.SZ"],
        session_date=SESSION_DATE,
        recorded_at=STARTED_AT,
    )

    assert preview.ready_without_provider_refresh is True
