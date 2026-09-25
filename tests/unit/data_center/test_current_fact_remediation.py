"""Fail-closed contracts for current-fact remediation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from apps.data_center.application.current_fact_remediation import (
    CompletedSessionPriceBarPreview,
    CompletedSessionPriceBarUseCase,
    CoreCurrentFactRefreshUseCase,
    FinancialAvailabilityBackfillPreview,
    FinancialAvailabilityBackfillResult,
    FinancialAvailabilityBackfillUseCase,
)
from apps.data_center.application.sync_use_cases import FinancialSourceEvidenceProbeResult
from apps.data_center.domain.entities import QuoteSnapshot
from core.exceptions import InvalidInputError

STARTED_AT = datetime(2026, 8, 30, 1, 0, tzinfo=UTC)
COMPLETED_AT = STARTED_AT + timedelta(minutes=5)
SESSION_DATE = date(2026, 8, 28)
SESSION_CLOSE = datetime(2026, 8, 28, 7, 0, tzinfo=UTC)


def test_price_preview_serialization_bounds_asset_code_evidence() -> None:
    missing = tuple(f"{index:06d}.SZ" for index in range(25))
    invalid = tuple(f"{index:06d}.SH" for index in range(30))
    payload = CompletedSessionPriceBarPreview(
        session_date=SESSION_DATE,
        requested_asset_count=25,
        eligible_asset_count=0,
        missing_asset_codes=missing,
        invalid_asset_codes=invalid,
        oldest_snapshot_at=None,
        newest_snapshot_at=None,
    ).to_dict()

    assert payload["missing_asset_count"] == 25
    assert payload["missing_asset_codes"] == list(missing[:20])
    assert payload["missing_asset_codes_truncated"] is True
    assert payload["invalid_asset_count"] == 30
    assert payload["invalid_asset_codes"] == list(invalid[:20])
    assert payload["invalid_asset_codes_truncated"] is True


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
    unresolved: int = 0,
) -> FinancialAvailabilityBackfillPreview:
    return FinancialAvailabilityBackfillPreview(
        missing_row_count=missing,
        eligible_row_count=eligible,
        eligible_asset_count=1 if eligible else 0,
        unresolved_row_count=unresolved,
        future_report_date_count=future_reports,
        future_available_at_count=future_availability,
        oldest_report_date=date(2026, 3, 31),
        newest_report_date=date(2026, 6, 30),
    )


def test_financial_date_only_availability_is_blocked_without_calling_writer() -> None:
    repository = _FinancialRepository(
        _availability_preview(),
        _availability_preview(missing=0, eligible=0),
    )
    use_case = FinancialAvailabilityBackfillUseCase(
        repository=repository,
        transaction=_transaction,
    )

    with pytest.raises(InvalidInputError, match="verified source timestamp"):
        use_case.execute(asset_codes=["000001.SZ"], recorded_at=STARTED_AT)

    assert repository.updated == 0
    assert repository.previews[0].eligible_row_count == 0


def test_financial_availability_noop_does_not_call_a_calendar_date_writer() -> None:
    before = _availability_preview(missing=0, eligible=0)
    repository = _FinancialRepository(before, before)
    use_case = FinancialAvailabilityBackfillUseCase(repository=repository, transaction=_transaction)

    result = use_case.execute(asset_codes=["000001.SZ"], recorded_at=STARTED_AT)

    assert result.updated_row_count == 0
    assert result.before == result.after == before
    assert repository.updated == 0


def test_financial_availability_noop_rejects_inventory_drift() -> None:
    repository = _FinancialRepository(
        _availability_preview(missing=0, eligible=0),
        _availability_preview(missing=1, eligible=0),
    )
    use_case = FinancialAvailabilityBackfillUseCase(repository=repository, transaction=_transaction)

    with pytest.raises(ValueError, match="count drifted"):
        use_case.execute(asset_codes=["000001.SZ"], recorded_at=STARTED_AT)
    assert repository.updated == 0


def test_financial_calendar_preview_does_not_advertise_executable_backfill() -> None:
    preview = _availability_preview()

    assert preview.safe_to_execute is False
    assert preview.to_dict()["safe_to_execute"] is False


def test_financial_unknown_date_is_blocked_without_calling_writer() -> None:
    preview = _availability_preview(missing=1, eligible=0, unresolved=1)
    repository = _FinancialRepository(preview, preview)
    use_case = FinancialAvailabilityBackfillUseCase(repository=repository, transaction=_transaction)

    with pytest.raises(InvalidInputError, match="verified source timestamp"):
        use_case.execute(asset_codes=["000001.SZ"], recorded_at=STARTED_AT)

    assert preview.safe_to_execute is False
    assert repository.updated == 0


def test_financial_availability_repair_rejects_future_evidence() -> None:
    before = _availability_preview(missing=0, eligible=0, future_reports=1)
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


@pytest.mark.parametrize("missing_field", ["volume", "amount"])
def test_completed_session_materialization_rejects_missing_liquidity_measures(
    missing_field: str,
) -> None:
    quote = _quote("000001.SZ")
    values = {"volume": quote.volume, "amount": quote.amount}
    values[missing_field] = None
    incomplete = QuoteSnapshot(
        asset_code=quote.asset_code,
        snapshot_at=quote.snapshot_at,
        fetched_at=quote.fetched_at,
        current_price=quote.current_price,
        open=quote.open,
        high=quote.high,
        low=quote.low,
        volume=values["volume"],
        amount=values["amount"],
        source=quote.source,
    )
    use_case = CompletedSessionPriceBarUseCase(
        quote_repository=_QuoteRepository([incomplete]),
        price_repository=_PriceRepository(),
        transaction=_transaction,
    )

    preview = use_case.preview(
        asset_codes=[incomplete.asset_code],
        session_date=SESSION_DATE,
        recorded_at=COMPLETED_AT,
    )

    assert preview.ready is False
    assert preview.invalid_asset_codes == (incomplete.asset_code,)


class _SyncUseCase:
    def __init__(self, result) -> None:
        self.result = result
        self.requests = []

    def execute(self, request=None, **kwargs):
        self.requests.append(request if request is not None else kwargs)
        return self.result

    def probe_source_evidence(self, request):
        self.requests.append(request)
        fact_count = int(self.result.stored_count)
        return FinancialSourceEvidenceProbeResult(
            provider_id=request.provider_id,
            provider_name="provider-main",
            requested_asset_code=request.asset_code,
            fact_count=fact_count,
            complete_fact_count=fact_count,
            block_reasons=(),
        )


class _FinancialAvailability:
    def preview(self, **kwargs):
        del kwargs
        return _availability_preview(missing=0, eligible=0)

    def execute(self, **kwargs):
        del kwargs
        before = _availability_preview(missing=0, eligible=0)
        return FinancialAvailabilityBackfillResult(0, before, before)


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
    execution_order: list[str] = []
    quote_sync = _SyncUseCase(
        SimpleNamespace(
            stored_count=2,
            stored_asset_codes=("000001.SZ", "600000.SH"),
        )
    )
    price_sync = _SyncUseCase(SimpleNamespace(stored_count=1))
    valuation_sync = _SyncUseCase(
        SimpleNamespace(
            stored_count=2,
            succeeded_asset_codes=["000001.SZ", "600000.SH"],
            returned_asset_codes=("000001.SZ", "600000.SH"),
        )
    )
    financial_sync = _SyncUseCase(SimpleNamespace(stored_count=4))
    publications = _Publications()
    use_case = CoreCurrentFactRefreshUseCase(
        provider_id=7,
        authority_preflight=lambda as_of: execution_order.append(f"authority:{as_of.isoformat()}"),
        quote_sync_factory=lambda: execution_order.append("quote_factory") or quote_sync,
        price_sync_factory=lambda: execution_order.append("price_factory") or price_sync,
        valuation_sync_factory=lambda: execution_order.append("valuation_factory")
        or valuation_sync,
        financial_sync_factory=lambda: execution_order.append("financial_factory")
        or financial_sync,
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
    assert result.financial_probe_fact_count == 8
    assert result.financial_probe_stored_count == 0
    assert len(quote_sync.requests) == 1
    assert len(financial_sync.requests) == 2
    assert publications.execute_kwargs["published_at"] == COMPLETED_AT
    assert execution_order[:2] == [
        f"authority:{STARTED_AT.isoformat()}",
        "quote_factory",
    ]


def test_core_refresh_blocks_publication_when_financial_source_time_is_missing() -> None:
    repository = _FinancialRepository(_availability_preview(), _availability_preview())
    publications = _Publications()
    use_case = CoreCurrentFactRefreshUseCase(
        provider_id=7,
        authority_preflight=lambda as_of: None,
        quote_sync_factory=lambda: _SyncUseCase(
            SimpleNamespace(
                stored_count=2,
                stored_asset_codes=("000001.SZ", "600000.SH"),
            )
        ),
        price_sync_factory=lambda: _SyncUseCase(SimpleNamespace(stored_count=1)),
        valuation_sync_factory=lambda: _SyncUseCase(
            SimpleNamespace(
                stored_count=2,
                succeeded_asset_codes=["000001.SZ", "600000.SH"],
                returned_asset_codes=("000001.SZ", "600000.SH"),
            )
        ),
        financial_sync_factory=lambda: _SyncUseCase(SimpleNamespace(stored_count=4)),
        financial_availability=FinancialAvailabilityBackfillUseCase(
            repository=repository, transaction=_transaction
        ),
        completed_session_prices=_CompletedPrices(),
        publications=publications,
        clock=lambda: COMPLETED_AT,
    )

    with pytest.raises(InvalidInputError, match="verified source timestamp"):
        use_case.execute(
            asset_codes=["000001.SZ", "600000.SH"],
            session_date=SESSION_DATE,
            recorded_at=STARTED_AT,
            batch_size=2,
        )

    assert repository.updated == 0
    assert publications.execute_kwargs is None


def test_core_refresh_source_probe_blocks_before_any_normalized_write() -> None:
    """An incomplete provider witness stops before price, quote or valuation writes."""

    price_sync = _SyncUseCase(SimpleNamespace(stored_count=1))
    quote_sync = _SyncUseCase(SimpleNamespace(stored_count=1, stored_asset_codes=("000001.SZ",)))
    valuation_sync = _SyncUseCase(
        SimpleNamespace(
            stored_count=1,
            succeeded_asset_codes=["000001.SZ"],
            returned_asset_codes=("000001.SZ",),
        )
    )
    financial_sync = _SyncUseCase(SimpleNamespace(stored_count=1))

    def incomplete_probe(_request):
        return FinancialSourceEvidenceProbeResult(
            provider_id=7,
            provider_name="provider-main",
            requested_asset_code="000001.SZ",
            fact_count=1,
            complete_fact_count=0,
            block_reasons=("financial_available_at_missing",),
        )

    financial_sync.probe_source_evidence = incomplete_probe
    use_case = CoreCurrentFactRefreshUseCase(
        provider_id=7,
        authority_preflight=lambda _as_of: None,
        quote_sync_factory=lambda: quote_sync,
        price_sync_factory=lambda: price_sync,
        valuation_sync_factory=lambda: valuation_sync,
        financial_sync_factory=lambda: financial_sync,
        financial_availability=_FinancialAvailability(),
        completed_session_prices=_CompletedPrices(),
        publications=_Publications(),
        clock=lambda: COMPLETED_AT,
    )

    with pytest.raises(InvalidInputError) as caught:
        use_case.execute(
            asset_codes=["000001.SZ"],
            session_date=SESSION_DATE,
            recorded_at=STARTED_AT,
            batch_size=1,
        )

    assert caught.value.code == "FINANCIAL_SOURCE_EVIDENCE_REQUIRED"
    assert price_sync.requests == []
    assert quote_sync.requests == []
    assert valuation_sync.requests == []


def test_core_refresh_rejects_mismatched_financial_probe_identity_before_writes() -> None:
    """A probe result for another provider or asset cannot authorize current writes."""

    price_sync = _SyncUseCase(SimpleNamespace(stored_count=1))
    quote_sync = _SyncUseCase(SimpleNamespace(stored_count=1, stored_asset_codes=("000001.SZ",)))
    valuation_sync = _SyncUseCase(
        SimpleNamespace(
            stored_count=1,
            succeeded_asset_codes=["000001.SZ"],
            returned_asset_codes=("000001.SZ",),
        )
    )
    financial_sync = _SyncUseCase(SimpleNamespace(stored_count=1))

    def mismatched_probe(_request):
        return FinancialSourceEvidenceProbeResult(
            provider_id=99,
            provider_name="provider-main",
            requested_asset_code="600000.SH",
            fact_count=1,
            complete_fact_count=1,
            block_reasons=(),
        )

    financial_sync.probe_source_evidence = mismatched_probe
    use_case = CoreCurrentFactRefreshUseCase(
        provider_id=7,
        authority_preflight=lambda _as_of: None,
        quote_sync_factory=lambda: quote_sync,
        price_sync_factory=lambda: price_sync,
        valuation_sync_factory=lambda: valuation_sync,
        financial_sync_factory=lambda: financial_sync,
        financial_availability=_FinancialAvailability(),
        completed_session_prices=_CompletedPrices(),
        publications=_Publications(),
        clock=lambda: COMPLETED_AT,
    )

    with pytest.raises(InvalidInputError) as caught:
        use_case.execute(
            asset_codes=["000001.SZ"],
            session_date=SESSION_DATE,
            recorded_at=STARTED_AT,
            batch_size=1,
        )

    assert caught.value.code == "FINANCIAL_SOURCE_EVIDENCE_REQUIRED"
    assert caught.value.details == {"block_reasons": ["financial_probe_identity_mismatch"]}
    assert price_sync.requests == []
    assert quote_sync.requests == []
    assert valuation_sync.requests == []


def test_core_refresh_stops_before_publication_on_incomplete_quote_batch() -> None:
    publications = _Publications()
    use_case = CoreCurrentFactRefreshUseCase(
        provider_id=7,
        authority_preflight=lambda as_of: None,
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
        authority_preflight=forbidden_factory,
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


def test_core_refresh_stops_before_write_factories_when_authority_preflight_fails() -> None:
    execution_order: list[str] = []

    def denied_authority(as_of: datetime) -> None:
        execution_order.append(f"authority:{as_of.isoformat()}")
        raise RuntimeError("current audit authority unavailable")

    def forbidden_factory():
        execution_order.append("write_factory")
        raise AssertionError("write factory must not resolve before authority preflight")

    use_case = CoreCurrentFactRefreshUseCase(
        provider_id=7,
        authority_preflight=denied_authority,
        quote_sync_factory=forbidden_factory,
        price_sync_factory=forbidden_factory,
        valuation_sync_factory=forbidden_factory,
        financial_sync_factory=forbidden_factory,
        financial_availability=_FinancialAvailability(),
        completed_session_prices=_CompletedPrices(),
        publications=_Publications(),
        clock=lambda: COMPLETED_AT,
    )

    with pytest.raises(RuntimeError, match="authority unavailable"):
        use_case.execute(
            asset_codes=["000001.SZ"],
            session_date=SESSION_DATE,
            recorded_at=STARTED_AT,
            batch_size=1,
        )

    assert execution_order == [f"authority:{STARTED_AT.isoformat()}"]


def test_core_refresh_revalidates_authority_before_each_provider_batch() -> None:
    preflight_calls = 0
    quote_sync = _SyncUseCase(SimpleNamespace(stored_count=1, stored_asset_codes=("000001.SZ",)))
    valuation_sync = _SyncUseCase(
        SimpleNamespace(
            stored_count=1,
            succeeded_asset_codes=["000001.SZ"],
            returned_asset_codes=("000001.SZ",),
        )
    )

    def authority_preflight(as_of: datetime) -> None:
        nonlocal preflight_calls
        assert as_of >= STARTED_AT
        preflight_calls += 1
        if preflight_calls == 8:
            raise RuntimeError("authority expired before second batch")

    use_case = CoreCurrentFactRefreshUseCase(
        provider_id=7,
        authority_preflight=authority_preflight,
        quote_sync_factory=lambda: quote_sync,
        price_sync_factory=lambda: _SyncUseCase(SimpleNamespace(stored_count=1)),
        valuation_sync_factory=lambda: valuation_sync,
        financial_sync_factory=lambda: _SyncUseCase(SimpleNamespace(stored_count=1)),
        financial_availability=_FinancialAvailability(),
        completed_session_prices=_CompletedPrices(),
        publications=_Publications(),
        clock=lambda: COMPLETED_AT,
    )

    with pytest.raises(RuntimeError, match="expired before second batch"):
        use_case.execute(
            asset_codes=["000001.SZ", "600000.SH"],
            session_date=SESSION_DATE,
            recorded_at=STARTED_AT,
            batch_size=1,
        )

    assert len(quote_sync.requests) == 1
    assert len(valuation_sync.requests) == 1


def test_core_refresh_revalidates_authority_before_final_publication() -> None:
    preflight_calls = 0
    publications = _Publications()

    def authority_preflight(as_of: datetime) -> None:
        nonlocal preflight_calls
        assert as_of >= STARTED_AT
        preflight_calls += 1
        if preflight_calls == 9:
            raise RuntimeError("authority expired before publication")

    use_case = CoreCurrentFactRefreshUseCase(
        provider_id=7,
        authority_preflight=authority_preflight,
        quote_sync_factory=lambda: _SyncUseCase(
            SimpleNamespace(stored_count=1, stored_asset_codes=("000001.SZ",))
        ),
        price_sync_factory=lambda: _SyncUseCase(SimpleNamespace(stored_count=1)),
        valuation_sync_factory=lambda: _SyncUseCase(
            SimpleNamespace(
                stored_count=1,
                succeeded_asset_codes=["000001.SZ"],
                returned_asset_codes=("000001.SZ",),
            )
        ),
        financial_sync_factory=lambda: _SyncUseCase(SimpleNamespace(stored_count=1)),
        financial_availability=_FinancialAvailability(),
        completed_session_prices=_CompletedPrices(),
        publications=publications,
        clock=lambda: COMPLETED_AT,
    )

    with pytest.raises(RuntimeError, match="expired before publication"):
        use_case.execute(
            asset_codes=["000001.SZ"],
            session_date=SESSION_DATE,
            recorded_at=STARTED_AT,
            batch_size=1,
        )

    assert publications.execute_kwargs is None


def test_core_refresh_rejects_quote_count_with_duplicate_or_substituted_assets() -> None:
    valuation_sync = _SyncUseCase(
        SimpleNamespace(
            stored_count=2,
            succeeded_asset_codes=["000001.SZ", "600000.SH"],
            returned_asset_codes=("000001.SZ", "600000.SH"),
        )
    )
    use_case = CoreCurrentFactRefreshUseCase(
        provider_id=7,
        authority_preflight=lambda as_of: None,
        quote_sync_factory=lambda: _SyncUseCase(
            SimpleNamespace(
                stored_count=2,
                stored_asset_codes=("000001.SZ", "000001.SZ"),
            )
        ),
        price_sync_factory=lambda: _SyncUseCase(SimpleNamespace(stored_count=1)),
        valuation_sync_factory=lambda: valuation_sync,
        financial_sync_factory=lambda: _SyncUseCase(SimpleNamespace(stored_count=1)),
        financial_availability=_FinancialAvailability(),
        completed_session_prices=_CompletedPrices(),
        publications=_Publications(),
        clock=lambda: COMPLETED_AT,
    )

    with pytest.raises(ValueError, match="quote provider batch asset identities"):
        use_case.execute(
            asset_codes=["000001.SZ", "600000.SH"],
            session_date=SESSION_DATE,
            recorded_at=STARTED_AT,
            batch_size=2,
        )

    assert valuation_sync.requests == []


def test_core_refresh_rejects_valuation_duplicate_rows_despite_set_coverage() -> None:
    publications = _Publications()
    use_case = CoreCurrentFactRefreshUseCase(
        provider_id=7,
        authority_preflight=lambda as_of: None,
        quote_sync_factory=lambda: _SyncUseCase(
            SimpleNamespace(
                stored_count=2,
                stored_asset_codes=("000001.SZ", "600000.SH"),
            )
        ),
        price_sync_factory=lambda: _SyncUseCase(SimpleNamespace(stored_count=1)),
        valuation_sync_factory=lambda: _SyncUseCase(
            SimpleNamespace(
                stored_count=2,
                succeeded_asset_codes=["000001.SZ", "600000.SH"],
                returned_asset_codes=("000001.SZ", "000001.SZ"),
            )
        ),
        financial_sync_factory=lambda: _SyncUseCase(SimpleNamespace(stored_count=1)),
        financial_availability=_FinancialAvailability(),
        completed_session_prices=_CompletedPrices(),
        publications=publications,
        clock=lambda: COMPLETED_AT,
    )

    with pytest.raises(ValueError, match="valuation provider batch asset identities"):
        use_case.execute(
            asset_codes=["000001.SZ", "600000.SH"],
            session_date=SESSION_DATE,
            recorded_at=STARTED_AT,
            batch_size=2,
        )

    assert publications.execute_kwargs is None
