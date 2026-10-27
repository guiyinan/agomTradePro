"""Fail-closed tests for the M1 publication-bound close reader."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest

from apps.account.application.market_price_contracts import MarketPriceResult
from apps.simulated_trading.application.rebalance_preview_reference_close import (
    PricePublicationReference,
    ReferenceCloseReadResult,
)
from apps.simulated_trading.application.rebalance_preview_valuation import (
    CurrentRebalanceValuationReader,
)
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount
from apps.simulated_trading.infrastructure.published_close_price_reader import (
    M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    PublishedClosePriceReader,
)

CODE = "600000.SH"
SESSION = date(2026, 10, 26)
CUTOFF = datetime(2026, 10, 27, 2, 0, tzinfo=UTC)
CLOSE = datetime(2026, 10, 26, 7, 0, tzinfo=UTC)
PUBLICATION_ID = "publication-123"
PUBLICATION_HASH = "a" * 64
RUN_ID = str(uuid4())


def _published_payload() -> dict[str, object]:
    """Build one exact, fully-qualified M1 close response."""

    return {
        "dataset_key": "equity.price.bar",
        "publication_key": M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        "publication_id": PUBLICATION_ID,
        "publication_hash": PUBLICATION_HASH,
        "publication_run_id": RUN_ID,
        "selected_source": "tushare",
        "freshness_scope": "asset",
        "asset_code": CODE,
        "policy_identity": "price-bars-v2",
        "publication_as_of": CUTOFF.isoformat(),
        "as_of": CUTOFF.isoformat(),
        "published_at": CUTOFF.isoformat(),
        "observed_at": CLOSE.isoformat(),
        "must_not_use_for_decision": False,
        "blocked_reason": "",
        "freshness_status": "latest_completed_session",
        "publication_outcome": "success",
        "coverage_requested_count": 1,
        "coverage_eligible_count": 1,
        "coverage_selected_count": 1,
        "coverage_missing_count": 0,
        "rows": [
            {
                "asset_code": CODE,
                "timestamp": SESSION.isoformat(),
                "period": "1d",
                "close": 10.25,
                "source": "tushare",
                "fetched_at": CUTOFF.isoformat(),
            }
        ],
    }


def _patch_reader(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    *,
    session: date | None = SESSION,
    latest_is_current: bool = True,
) -> list[dict[str, object]]:
    """Bind bounded calendar and public-query results without a database."""

    from apps.simulated_trading.infrastructure import published_close_price_reader as module

    calls: list[dict[str, object]] = []

    def _query(asset_code: str, **kwargs: object) -> dict[str, object]:
        calls.append({"asset_code": asset_code, **kwargs})
        return payload

    monkeypatch.setattr(module, "latest_completed_cn_market_session", lambda now: session)
    monkeypatch.setattr(module, "get_published_price_bar_series", _query)
    monkeypatch.setattr(
        module,
        "latest_daily_market_observation_is_current",
        lambda **kwargs: latest_is_current,
    )
    return calls


def test_reader_requests_exact_m1_lane_at_preview_knowledge_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful close is bound to the exact cutoff, publication, run, and close date."""

    payload = _published_payload()
    calls = _patch_reader(monkeypatch, payload)

    result = PublishedClosePriceReader().read(asset_code=CODE, cutoff=CUTOFF)

    assert result.blocked_reason is None
    assert result.price_result is not None
    assert result.price_result.price == 10.25
    assert result.price_result.as_of == SESSION
    assert result.price_result.freshness == "close_fallback"
    assert result.price_result.is_fallback is True
    assert result.price_result.observed_at == CLOSE
    assert result.publication is not None
    assert result.publication.publication_id == PUBLICATION_ID
    assert result.publication.publication_hash == PUBLICATION_HASH
    assert result.publication.publication_run_id == RUN_ID
    assert result.publication.knowledge_cutoff == CUTOFF
    assert result.publication.source_observed_at == CLOSE
    assert calls == [
        {
            "asset_code": CODE,
            "publication_key": M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
            "start": SESSION,
            "end": SESSION,
            "limit": 2,
            "knowledge_cutoff": CUTOFF,
        }
    ]


def test_reader_uses_row_source_when_publication_summarizes_multiple_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-row source remains precise when the publication has a source summary."""

    payload = _published_payload()
    payload["selected_source"] = "canonical-multi-source"
    _patch_reader(monkeypatch, payload)

    result = PublishedClosePriceReader().read(asset_code=CODE, cutoff=CUTOFF)

    assert result.blocked_reason is None
    assert result.price_result is not None
    assert result.price_result.source == "tushare"


def test_reader_blocks_numeric_overflow_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrepresentable JSON number cannot escape the no-price result contract."""

    payload = _published_payload()
    rows = payload["rows"]
    assert isinstance(rows, list)
    rows[0]["close"] = 10**400
    calls = _patch_reader(monkeypatch, payload)

    result = PublishedClosePriceReader().read(asset_code=CODE, cutoff=CUTOFF)

    assert result.price_result is None
    assert result.publication is None
    assert result.blocked_reason == "M1_REFERENCE_CLOSE_ROW_INVALID"
    assert len(calls) == 1


def test_reader_fails_closed_when_calendar_gate_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calendar errors cannot escape as a usable close or trigger a fallback."""

    from apps.simulated_trading.infrastructure import published_close_price_reader as module

    _patch_reader(monkeypatch, _published_payload())
    monkeypatch.setattr(
        module,
        "latest_daily_market_observation_is_current",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("calendar unavailable")),
    )

    result = PublishedClosePriceReader().read(asset_code=CODE, cutoff=CUTOFF)

    assert result.price_result is None
    assert result.publication is None
    assert result.blocked_reason == "M1_REFERENCE_CLOSE_CALENDAR_UNAVAILABLE"


def test_reader_fails_before_query_when_calendar_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unavailable completed-session calendar cannot be replaced by a weekday guess."""

    calls = _patch_reader(monkeypatch, _published_payload(), session=None)

    result = PublishedClosePriceReader().read(asset_code=CODE, cutoff=CUTOFF)

    assert result.price_result is None
    assert result.publication is None
    assert result.blocked_reason == "M1_REFERENCE_CLOSE_CALENDAR_UNAVAILABLE"
    assert calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("dataset_key", "equity.quote.snapshot"),
        ("publication_key", "current"),
        ("publication_id", ""),
        ("publication_hash", "not-a-digest"),
        ("publication_run_id", ""),
        ("policy_identity", ""),
        ("must_not_use_for_decision", None),
        ("must_not_use_for_decision", True),
        ("publication_outcome", "partial"),
        ("coverage_missing_count", 1),
        ("freshness_status", "unverified"),
        ("observed_at", "2026-10-26T07:00:00"),
        ("published_at", "2026-10-27T03:00:00+00:00"),
        ("as_of", "2026-10-27T03:00:00+00:00"),
    ),
)
def test_reader_blocks_unqualified_or_future_publication_scope(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    """Unknown scope, incomplete evidence, naive clocks, and post-cutoff data block."""

    payload = _published_payload()
    payload[field] = value
    _patch_reader(monkeypatch, payload)

    result = PublishedClosePriceReader().read(asset_code=CODE, cutoff=CUTOFF)

    assert result.price_result is None
    assert result.publication is None
    assert result.blocked_reason in {
        "M1_REFERENCE_PUBLICATION_BLOCKED",
        "M1_REFERENCE_PUBLICATION_SCOPE_INVALID",
    }


@pytest.mark.parametrize("value", ([], {}))
def test_reader_blocks_malformed_json_blocked_reason(
    monkeypatch: pytest.MonkeyPatch,
    value: object,
) -> None:
    """Malformed JSON blocking reasons fail closed instead of escaping membership checks."""

    payload = _published_payload()
    payload["blocked_reason"] = value
    _patch_reader(monkeypatch, payload)

    result = PublishedClosePriceReader().read(asset_code=CODE, cutoff=CUTOFF)

    assert result.price_result is None
    assert result.publication is None
    assert result.blocked_reason == "M1_REFERENCE_PUBLICATION_BLOCKED"


@pytest.mark.parametrize("value", ([], {}))
def test_reader_blocks_malformed_json_freshness_status(
    monkeypatch: pytest.MonkeyPatch,
    value: object,
) -> None:
    """Malformed JSON freshness values fail closed instead of escaping set membership."""

    payload = _published_payload()
    payload["freshness_status"] = value
    _patch_reader(monkeypatch, payload)

    result = PublishedClosePriceReader().read(asset_code=CODE, cutoff=CUTOFF)

    assert result.price_result is None
    assert result.publication is None
    assert result.blocked_reason == "M1_REFERENCE_PUBLICATION_BLOCKED"


@pytest.mark.parametrize(
    "row_change",
    (
        {"asset_code": "000001.SZ"},
        {"timestamp": "2026-10-25"},
        {"period": "1m"},
        {"close": 0},
        {"close": -1},
        {"close": float("nan")},
        {"close": True},
        {"source": ""},
        {"fetched_at": "2026-10-27T03:00:00+00:00"},
    ),
)
def test_reader_blocks_wrong_or_invalid_close_row(
    monkeypatch: pytest.MonkeyPatch,
    row_change: dict[str, Any],
) -> None:
    """Only one exact positive finite daily close at the latest session may be used."""

    payload = _published_payload()
    row = dict(payload["rows"][0])  # type: ignore[index]
    row.update(row_change)
    payload["rows"] = [row]
    _patch_reader(monkeypatch, payload)

    result = PublishedClosePriceReader().read(asset_code=CODE, cutoff=CUTOFF)

    assert result.price_result is None
    assert result.publication is None
    assert result.blocked_reason == "M1_REFERENCE_CLOSE_ROW_INVALID"


def test_reader_blocks_duplicate_rows_and_stale_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate rows and a close rejected by the formal calendar gate fail closed."""

    payload = _published_payload()
    payload["rows"] = [deepcopy(payload["rows"][0]), deepcopy(payload["rows"][0])]  # type: ignore[index]
    _patch_reader(monkeypatch, payload)
    duplicate = PublishedClosePriceReader().read(asset_code=CODE, cutoff=CUTOFF)
    assert duplicate.blocked_reason == "M1_REFERENCE_CLOSE_ROW_INVALID"

    _patch_reader(monkeypatch, _published_payload(), latest_is_current=False)
    stale = PublishedClosePriceReader().read(asset_code=CODE, cutoff=CUTOFF)
    assert stale.price_result is None
    assert stale.publication is None
    assert stale.blocked_reason == "M1_REFERENCE_CLOSE_DATE_NOT_CURRENT"


class _UnusedMarketReader:
    """Guard against accidentally falling back to live market prices."""

    def get_price_result(
        self,
        asset_code: str,
        trade_date: date | None = None,
    ) -> MarketPriceResult | None:
        raise AssertionError(f"market price reader used for {asset_code} at {trade_date}")

    def clear_cache(self) -> None:
        """Satisfy the existing market reader protocol."""


class _CloseReader:
    """Return prevalidated publication-bound close results by exact asset code."""

    def __init__(self, results: dict[str, ReferenceCloseReadResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, datetime]] = []

    def read(self, *, asset_code: str, cutoff: datetime) -> ReferenceCloseReadResult:
        self.calls.append((asset_code, cutoff))
        return self.results[asset_code]


def _valuation_account() -> SimulatedAccount:
    """Return a valid simulated account with known ledger cash."""

    return SimulatedAccount(
        account_id=7,
        account_name="published close valuation",
        account_type=AccountType.SIMULATED,
        initial_capital=10000.0,
        current_cash=10000.0,
        current_market_value=0.0,
        total_value=10000.0,
    )


def _close_result_for(
    asset_code: str,
    *,
    publication_id: str,
    publication_hash: str,
) -> ReferenceCloseReadResult:
    """Build a close result whose typed price and publication clocks agree."""

    price = MarketPriceResult(
        normalized_code=asset_code,
        price=10.25,
        as_of=SESSION,
        source="tushare",
        freshness="close_fallback",
        is_fallback=True,
        observed_at=CLOSE,
    )
    reference = PricePublicationReference(
        dataset_key="equity.price.bar",
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        publication_id=publication_id,
        publication_hash=publication_hash,
        publication_run_id=RUN_ID,
        published_at=CUTOFF,
        publication_as_of=CUTOFF,
        knowledge_cutoff=CUTOFF,
        bar_date=SESSION,
        source_observed_at=CLOSE,
        freshness_status="latest_completed_session",
    )
    return ReferenceCloseReadResult(price, reference, None)


def test_valuation_uses_the_selected_close_lane_at_the_same_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The close mode never consults live prices and preserves publication metadata."""

    _patch_reader(monkeypatch, _published_payload())
    close_reader = PublishedClosePriceReader()
    valuation = CurrentRebalanceValuationReader(
        _UnusedMarketReader(),
        reference_close_reader=close_reader,
    ).read(
        asset_codes={CODE},
        account=_valuation_account(),
        positions=(),
        checks=(),
        position_codes_valid=True,
        cutoff=CUTOFF,
        current_local_date=CUTOFF.date(),
        reference_price_basis="published_close",
    )

    assert valuation.reference_price_basis == "published_close"
    assert valuation.prices[CODE] is not None
    assert valuation.prices[CODE].price == 10.25
    assert valuation.price_publications[CODE].publication_id == PUBLICATION_ID
    assert valuation.price_publications[CODE].knowledge_cutoff == CUTOFF


def test_valuation_keeps_market_default_and_does_not_call_close_reader() -> None:
    """Existing previews continue through the original price provider by default."""

    result = MarketPriceResult(
        normalized_code=CODE,
        price=11.0,
        as_of=None,
        source="fixture:market",
        freshness="realtime",
        is_fallback=False,
        observed_at=CUTOFF,
    )

    class _MarketReader:
        def get_price_result(
            self,
            asset_code: str,
            trade_date: date | None = None,
        ) -> MarketPriceResult:
            assert asset_code == CODE
            assert trade_date is None
            return result

        def clear_cache(self) -> None:
            """Satisfy the existing market reader protocol."""

    class _UnexpectedCloseReader:
        def read(self, *, asset_code: str, cutoff: datetime) -> ReferenceCloseReadResult:
            raise AssertionError(f"close reader used for {asset_code} at {cutoff}")

    valuation = CurrentRebalanceValuationReader(
        _MarketReader(),
        reference_close_reader=_UnexpectedCloseReader(),
    ).read(
        asset_codes={CODE},
        account=_valuation_account(),
        positions=(),
        checks=(),
        position_codes_valid=True,
        cutoff=CUTOFF,
        current_local_date=CUTOFF.date(),
    )

    assert valuation.reference_price_basis == "market"
    assert valuation.prices[CODE] is result
    assert valuation.price_publications == {}


def test_valuation_blocks_mixed_publication_identities() -> None:
    """A portfolio snapshot cannot combine prices from different publications."""

    first = _close_result_for(CODE, publication_id="publication-a", publication_hash="a" * 64)
    second = _close_result_for(
        "000001.SZ", publication_id="publication-b", publication_hash="b" * 64
    )
    close_reader = _CloseReader({CODE: first, "000001.SZ": second})

    valuation = CurrentRebalanceValuationReader(
        _UnusedMarketReader(),
        reference_close_reader=close_reader,
    ).read(
        asset_codes={CODE, "000001.SZ"},
        account=_valuation_account(),
        positions=(),
        checks=(),
        position_codes_valid=True,
        cutoff=CUTOFF,
        current_local_date=CUTOFF.date(),
        reference_price_basis="published_close",
    )

    assert valuation.prices == {CODE: None, "000001.SZ": None}
    assert valuation.price_reasons == {
        CODE: "M1_REFERENCE_PUBLICATION_MIXED",
        "000001.SZ": "M1_REFERENCE_PUBLICATION_MIXED",
    }
    assert valuation.price_publications == {}
