"""A full-market quote session is fetched once and frozen to its scope."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.data_center.application.batch_identity import ProviderAssetIdentityError
from apps.data_center.application.full_market_task_support import (
    asset_code_scope_sha256,
    quote_session_prefetch_failure,
)
from apps.data_center.application.quote_session_prefetch import prepare_quote_session
from apps.data_center.domain.entities import QuoteSnapshot
from core.exceptions import DataFetchError

TARGET = date(2026, 9, 24)
OBSERVED_AT = datetime(2026, 9, 24, 7, 0, tzinfo=UTC)
FETCHED_AT = datetime(2026, 9, 24, 9, 5, tzinfo=UTC)
RAW_RESPONSE_SHA256 = "a" * 64


def _quote(asset_code: str, target_date: date = TARGET) -> QuoteSnapshot:
    """Return one source-timed quote row for the requested market session."""

    observed_at = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC).replace(hour=7)
    fetched_at = observed_at + timedelta(hours=2, minutes=5)
    return QuoteSnapshot(
        asset_code=asset_code,
        snapshot_at=observed_at,
        fetched_at=fetched_at,
        current_price=10.0,
        source="tushare",
        extra={
            "raw_payload_hash": RAW_RESPONSE_SHA256,
            "raw_payload_scope": "batch_response_body",
        },
    )


class _Provider:
    """Typed fake for one provider-level market-session read."""

    def __init__(self, rows: list[QuoteSnapshot] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[tuple[str, ...], date]] = []
        self.error: DataFetchError | None = None

    def provider_name(self) -> str:
        """Return the configured provider identity."""

        return "tushare-main"

    def fetch_quote_snapshots_for_session(
        self, asset_codes: list[str], target_trade_date: date
    ) -> list[QuoteSnapshot]:
        """Record and return one requested session response."""

        self.calls.append((tuple(asset_codes), target_trade_date))
        if self.error is not None:
            raise self.error
        return list(self.rows)


def test_full_market_quote_session_fetches_once_and_reuses_frozen_rows() -> None:
    """A 5,569-member session is split after one full-scope provider response."""

    codes = tuple(f"{value:06d}.SZ" for value in range(1, 5570))
    provider = _Provider([_quote(code) for code in codes])

    prepared = prepare_quote_session(
        provider=provider,
        provider_id=7,
        provider_name=provider.provider_name(),
        source_type="tushare",
        asset_codes=codes,
        target_trade_date=TARGET,
    )

    assert provider.calls == [(codes, TARGET)]
    assert prepared.universe_codes == codes
    assert prepared.universe_sha256
    assert prepared.response_completed_at == FETCHED_AT
    assert prepared.raw_response_sha256s == (RAW_RESPONSE_SHA256,)
    assert len(prepared.quote_rows_sha256) == 64
    for offset in range(0, len(codes), 100):
        batch = prepared.quote_rows_for(codes[offset : offset + 100])
        assert tuple(row.asset_code for row in batch) == codes[offset : offset + 100]
        assert all(row.snapshot_at == OBSERVED_AT for row in batch)
        assert all(row.fetched_at == FETCHED_AT for row in batch)
        assert all(
            row.extra["market_publication_quote_session"]["universe_sha256"]
            == prepared.universe_sha256
            for row in batch
        )
    assert provider.calls == [(codes, TARGET)]


def test_prepared_session_does_not_expose_mutable_provider_rows() -> None:
    """Mutating detached inspection rows cannot change the batch payload."""

    code = "000001.SZ"
    prepared = prepare_quote_session(
        provider=_Provider([_quote(code)]),
        provider_id=7,
        provider_name="tushare-main",
        source_type="tushare",
        asset_codes=(code,),
        target_trade_date=TARGET,
    )

    inspected = prepared.quote_rows[0]
    inspected.extra["changed"] = True

    assert "changed" not in prepared.quote_rows_for((code,))[0].extra


def test_quote_session_prefetch_has_no_cross_task_cache() -> None:
    """A later task performs its own provider request for the new target date."""

    codes = ("000001.SZ",)
    provider = _Provider([_quote(codes[0])])

    first = prepare_quote_session(
        provider=provider,
        provider_id=7,
        provider_name=provider.provider_name(),
        source_type="tushare",
        asset_codes=codes,
        target_trade_date=TARGET,
    )
    next_date = date(2026, 9, 25)
    provider.rows = [_quote(codes[0], next_date)]
    second = prepare_quote_session(
        provider=provider,
        provider_id=7,
        provider_name=provider.provider_name(),
        source_type="tushare",
        asset_codes=codes,
        target_trade_date=next_date,
    )

    assert len(provider.calls) == 2
    assert first.target_trade_date == TARGET
    assert second.target_trade_date == next_date
    assert first.quote_rows_sha256 != second.quote_rows_sha256


def test_quote_session_prefetch_rejects_same_day_pre_close_snapshot() -> None:
    """A 14:55 observation cannot represent the target session's official close."""

    code = "000001.SZ"
    pre_close = datetime(2026, 9, 24, 6, 55, tzinfo=UTC)
    quote = dataclasses.replace(
        _quote(code),
        snapshot_at=pre_close,
        fetched_at=pre_close + timedelta(minutes=10),
    )

    with pytest.raises(DataFetchError) as exc_info:
        prepare_quote_session(
            provider=_Provider([quote]),
            provider_id=7,
            provider_name="tushare-main",
            source_type="tushare",
            asset_codes=(code,),
            target_trade_date=TARGET,
        )

    assert exc_info.value.code == "CURRENT_QUOTE_SESSION_DATE_MISMATCH"


@pytest.mark.parametrize(
    "returned_codes",
    [
        ["000001.SZ", "000001.SZ"],
        ["000002.SZ"],
    ],
)
def test_quote_session_prefetch_rejects_incomplete_or_duplicate_scope(returned_codes) -> None:
    provider = _Provider([_quote(code) for code in returned_codes])

    with pytest.raises(ProviderAssetIdentityError):
        prepare_quote_session(
            provider=provider,
            provider_id=7,
            provider_name=provider.provider_name(),
            source_type="tushare",
            asset_codes=("000001.SZ", "000002.SZ"),
            target_trade_date=TARGET,
        )


def test_quote_session_prefetch_accepts_only_explicitly_verified_missing_suspensions() -> None:
    """A provider gap becomes an exclusion only after exact target-day proof."""

    available = "000001.SZ"
    suspended = "000002.SZ"
    verifier_calls: list[tuple[tuple[str, ...], date]] = []

    def verify(missing: tuple[str, ...], target: date) -> tuple[str, ...]:
        verifier_calls.append((missing, target))
        return (suspended,)

    prepared = prepare_quote_session(
        provider=_Provider([_quote(available)]),
        provider_id=7,
        provider_name="tushare-main",
        source_type="tushare",
        asset_codes=(available, suspended),
        target_trade_date=TARGET,
        missing_asset_verifier=verify,
    )

    assert prepared.universe_codes == (available, suspended)
    assert prepared.available_codes == (available,)
    assert prepared.eligible_codes == (available,)
    assert prepared.excluded_codes == (suspended,)
    assert verifier_calls == [((suspended,), TARGET)]
    evidence = prepared.quote_rows_for((available,))[0].extra["market_publication_quote_session"]
    assert evidence["eligible_codes_sha256"] == asset_code_scope_sha256((available,))
    assert evidence["excluded_codes"] == (suspended,)
    assert evidence["excluded_count"] == 1
    assert len(evidence["excluded_codes_sha256"]) == 64
    with pytest.raises(DataFetchError) as caught:
        prepared.quote_rows_for((suspended,))
    assert caught.value.code == "CURRENT_QUOTE_SESSION_SCOPE_MISMATCH"


def test_quote_session_prefetch_rejects_partial_suspension_proof() -> None:
    """A verifier that omits one missing code keeps the session fail-closed."""

    with pytest.raises(DataFetchError) as caught:
        prepare_quote_session(
            provider=_Provider([_quote("000001.SZ")]),
            provider_id=7,
            provider_name="tushare-main",
            source_type="tushare",
            asset_codes=("000001.SZ", "000002.SZ", "000003.SZ"),
            target_trade_date=TARGET,
            missing_asset_verifier=lambda _missing, _target: ("000002.SZ",),
        )

    assert caught.value.code == "CURRENT_QUOTE_SESSION_SUSPENSION_UNVERIFIED"


def test_quote_session_prefetch_can_represent_all_verified_suspensions_without_rows() -> None:
    """An all-suspension response remains an empty eligible scope for blocking."""

    codes = ("000001.SZ", "000002.SZ")
    prepared = prepare_quote_session(
        provider=_Provider([]),
        provider_id=7,
        provider_name="tushare-main",
        source_type="tushare",
        asset_codes=codes,
        target_trade_date=TARGET,
        missing_asset_verifier=lambda missing, _target: missing,
    )

    assert prepared.available_codes == ()
    assert prepared.eligible_codes == ()
    assert prepared.excluded_codes == codes
    assert prepared.response_completed_at is None


def test_quote_session_prefetch_rejects_wrong_observation_date() -> None:
    provider = _Provider([_quote("000001.SZ", date(2026, 9, 23))])

    with pytest.raises(DataFetchError) as caught:
        prepare_quote_session(
            provider=provider,
            provider_id=7,
            provider_name=provider.provider_name(),
            source_type="tushare",
            asset_codes=("000001.SZ",),
            target_trade_date=TARGET,
        )

    assert caught.value.code == "CURRENT_QUOTE_SESSION_DATE_MISMATCH"


def test_quote_session_prefetch_rejects_rows_from_multiple_responses() -> None:
    """A prepared full-market snapshot has one shared completion identity."""

    first = _quote("000001.SZ")
    second = dataclasses.replace(_quote("000002.SZ"), fetched_at=FETCHED_AT + timedelta(minutes=1))

    with pytest.raises(DataFetchError) as caught:
        prepare_quote_session(
            provider=_Provider([first, second]),
            provider_id=7,
            provider_name="tushare-main",
            source_type="tushare",
            asset_codes=("000001.SZ", "000002.SZ"),
            target_trade_date=TARGET,
        )

    assert caught.value.code == "CURRENT_QUOTE_SESSION_EVIDENCE_INVALID"


def test_quote_session_provider_failure_is_not_replaced_with_cached_data() -> None:
    provider = _Provider([_quote("000001.SZ")])
    provider.error = DataFetchError(
        "provider rejected the request", code="TUSHARE_PROVIDER_REJECTED"
    )

    with pytest.raises(DataFetchError) as caught:
        prepare_quote_session(
            provider=provider,
            provider_id=7,
            provider_name=provider.provider_name(),
            source_type="tushare",
            asset_codes=("000001.SZ",),
            target_trade_date=TARGET,
        )

    assert caught.value.code == "TUSHARE_PROVIDER_REJECTED"
    assert provider.calls == [(("000001.SZ",), TARGET)]


def test_prefetch_failure_result_preserves_partial_writes_and_stops_publication() -> None:
    """A quote prefetch rejection is an explicit failed phase after seed writes."""

    result = quote_session_prefetch_failure(
        asset_count=5569,
        batch_count=56,
        target_trade_date=TARGET.isoformat(),
        publication_run_id="11111111-1111-4111-8111-111111111111",
        quote_source="tushare",
        valuation_source="akshare",
        market_universe={"active_count": 5569},
        valuation_requested_count=5569,
        valuation_succeeded_count=5569,
        valuation_missing_codes=(),
        valuation_stored_count=5569,
        valuation_coverage_ratio=1.0,
        valuation_policy_identity=None,
        error_code="TUSHARE_PROVIDER_REJECTED",
    )

    phases = {item["phase"]: item for item in result["phase_results"]}
    assert result["outcome"] == "partial"
    assert result["phase"] == "quote"
    assert result["error_code"] == "TUSHARE_PROVIDER_REJECTED"
    assert (result["requested"], result["succeeded"], result["failed"], result["stored"]) == (
        5569,
        0,
        5569,
        5569,
    )
    assert phases["quote"]["stored"] == 0
    assert result["publication_updated"] is False
    assert result["published_members"] == 0
