from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

import apps.data_center.application.price_service as price_service_module
from apps.data_center.application.price_service import (
    PriceLookupResult,
    UnifiedPriceService,
)
from apps.data_center.domain.entities import FundNavFact, PriceBar, QuoteSnapshot
from core.exceptions import DataFetchError


def _after_close_now() -> datetime:
    """Return a deterministic post-close instant for today's local test date."""

    return datetime.combine(_test_session_date(), time(8, 0), tzinfo=UTC)


def _test_session_date() -> date:
    """Return a weekday so freshness tests do not depend on CI calendar timing."""

    session_date = date.today()
    while session_date.weekday() >= 5:
        session_date -= timedelta(days=1)
    return session_date


def _published(rows: list[dict[str, object]]) -> dict[str, object]:
    """Build a decision-safe published port response for unit tests."""

    return {
        "rows": rows,
        "must_not_use_for_decision": False,
        "publication_id": "test-publication",
    }


def _quote_row(
    *,
    asset_code: str,
    current_price: object,
    snapshot_at: datetime,
    source: str = "eastmoney",
) -> dict[str, object]:
    """Build a canonical quote payload without bypassing the public port."""

    return {
        "asset_code": asset_code,
        "current_price": current_price,
        "snapshot_at": snapshot_at.isoformat(),
        "fetched_at": snapshot_at.isoformat(),
        "open": None,
        "high": None,
        "low": None,
        "prev_close": None,
        "volume": None,
        "source": source,
    }


def _bar_row(
    *,
    asset_code: str,
    bar_date: date,
    close: float = 4.95,
    source: str = "eastmoney",
) -> dict[str, object]:
    """Build a canonical daily bar payload for the published price port."""

    fetched_at = datetime.combine(bar_date, time(8, 0), tzinfo=UTC)
    return {
        "asset_code": asset_code,
        "timestamp": bar_date.isoformat(),
        "period": "1d",
        "open": close - 0.05,
        "high": close + 0.05,
        "low": close - 0.15,
        "close": close,
        "volume": None,
        "amount": None,
        "source": source,
        "fetched_at": fetched_at.isoformat(),
    }


def _nav_row(
    *,
    fund_code: str,
    nav_date: date,
    nav: float = 1.2345,
    source: str = "akshare_fund",
) -> dict[str, object]:
    """Build a canonical fund NAV payload for the published NAV port."""

    return {
        "fund_code": fund_code,
        "nav_date": nav_date.isoformat(),
        "nav": nav,
        "acc_nav": None,
        "daily_return": None,
        "source": source,
        "fetched_at": datetime.combine(nav_date, time(8, 0), tzinfo=UTC).isoformat(),
        "extra": {},
    }


def test_normalize_asset_code_handles_bare_exchange_codes():
    service = UnifiedPriceService()

    assert service.normalize_asset_code("159915") == "159915.SZ"
    assert service.normalize_asset_code("510300") == "510300.SH"
    assert service.normalize_asset_code("600519") == "600519.SH"
    assert service.normalize_asset_code("430001") == "430001.BJ"


def test_get_price_uses_historical_capability():
    service = UnifiedPriceService()
    service._dc_price_repo = Mock()
    service._dc_price_repo.get_bars.return_value = [
        SimpleNamespace(
            asset_code="510300.SH",
            bar_date=date(2026, 3, 20),
            open=4.9,
            high=5.0,
            low=4.8,
            close=4.95,
            source="eastmoney",
        )
    ]
    result = service.get_price_result("510300", trade_date=date(2026, 3, 20))

    assert result is not None
    assert result.normalized_code == "510300.SH"
    assert result.price == 4.95
    assert result.freshness == "historical"


def test_get_latest_price_prefers_realtime_quote(monkeypatch):
    service = UnifiedPriceService()
    observed_at = datetime.now(UTC)
    monkeypatch.setattr(
        price_service_module,
        "get_published_quote_payloads",
        lambda _codes: _published(
            [_quote_row(asset_code="159915.SZ", current_price=2.18, snapshot_at=observed_at)]
        ),
    )
    result = service.get_price_result("159915")

    assert result is not None
    assert result.normalized_code == "159915.SZ"
    assert result.price == 2.18
    assert result.freshness == "realtime"
    assert result.observed_at == observed_at


def test_latest_price_requires_published_members(monkeypatch):
    """Current prices never fall back to raw repositories when publication is blocked."""

    service = UnifiedPriceService()
    service._dc_quote_repo = Mock()
    service._dc_quote_repo.get_latest.return_value = SimpleNamespace(
        asset_code="510300.SH",
        current_price=5.18,
        source="unpublished_quote",
        snapshot_at=datetime.now(UTC),
    )
    service._dc_price_repo = Mock()
    service._dc_price_repo.get_latest.return_value = SimpleNamespace(
        asset_code="510300.SH",
        bar_date=_test_session_date(),
        open=4.9,
        high=5.0,
        low=4.8,
        close=4.95,
        source="unpublished_close",
    )
    blocked = {
        "rows": [],
        "must_not_use_for_decision": True,
        "blocked_reason": "canonical_publication_missing",
    }
    monkeypatch.setattr(
        price_service_module, "get_published_quote_payloads", lambda _codes: blocked
    )
    monkeypatch.setattr(
        price_service_module,
        "get_published_price_bar_series",
        lambda _code, limit=1: blocked,
    )

    assert service.get_price_result("510300") is None
    service._dc_quote_repo.get_latest.assert_not_called()
    service._dc_price_repo.get_latest.assert_not_called()


def test_get_latest_price_rejects_stale_quote_and_uses_close_fallback(monkeypatch):
    """A stored quote outside the freshness window cannot be labelled realtime."""

    service = UnifiedPriceService(now_provider=_after_close_now)
    monkeypatch.setattr(
        price_service_module,
        "get_published_quote_payloads",
        lambda _codes: _published(
            [
                _quote_row(
                    asset_code="510300.SH",
                    current_price=5.18,
                    source="stale_quote",
                    snapshot_at=datetime.now(UTC) - timedelta(days=30),
                )
            ]
        ),
    )
    monkeypatch.setattr(
        price_service_module,
        "get_published_price_bar_series",
        lambda _code, limit=1: _published(
            [_bar_row(asset_code="510300.SH", bar_date=_test_session_date(), source="daily_close")]
        ),
    )

    result = service.get_price_result("510300")

    assert result is not None
    assert result.price == 4.95
    assert result.freshness == "close_fallback"
    assert result.source == "daily_close"
    assert result.observed_at is None


def test_get_latest_price_rejects_stale_close_fallback(monkeypatch):
    """An old daily bar is historical evidence, not a usable latest price."""

    service = UnifiedPriceService()
    monkeypatch.setattr(
        price_service_module,
        "get_published_quote_payloads",
        lambda _codes: _published([]),
    )
    monkeypatch.setattr(
        price_service_module,
        "get_published_price_bar_series",
        lambda _code, limit=1: _published(
            [
                _bar_row(
                    asset_code="510300.SH",
                    bar_date=_test_session_date() - timedelta(days=30),
                    source="stale_daily_close",
                )
            ]
        ),
    )

    assert service.get_price_result("510300") is None


def test_get_latest_price_falls_back_to_recent_close(monkeypatch):
    service = UnifiedPriceService(now_provider=_after_close_now)
    monkeypatch.setattr(
        price_service_module,
        "get_published_quote_payloads",
        lambda _codes: _published([]),
    )
    monkeypatch.setattr(
        price_service_module,
        "get_published_price_bar_series",
        lambda _code, limit=1: _published(
            [_bar_row(asset_code="510300.SH", bar_date=_test_session_date())]
        ),
    )
    result = service.get_price_result("510300")

    assert result is not None
    assert result.price == 4.95
    assert result.freshness == "close_fallback"
    assert result.is_fallback is True


def test_exchange_traded_etf_does_not_fallback_to_fund_nav(monkeypatch):
    service = UnifiedPriceService()
    monkeypatch.setattr(
        price_service_module, "get_published_quote_payloads", lambda _codes: _published([])
    )
    monkeypatch.setattr(
        price_service_module,
        "get_published_price_bar_series",
        lambda _code, limit=1: _published([]),
    )
    service._get_fund_nav_price = Mock(return_value=None)

    result = service.get_price_result("510300")

    assert result is None
    service._get_fund_nav_price.assert_not_called()


def test_require_price_raises_when_all_sources_missing():
    service = UnifiedPriceService()
    service._dc_price_repo = Mock()
    service._dc_price_repo.get_bars.return_value = []

    try:
        service.require_price("510300", trade_date=date(2026, 3, 20))
        raise AssertionError("expected DataFetchError")
    except DataFetchError as exc:
        assert exc.code == "PRICE_UNAVAILABLE"
        assert exc.details["requested_code"] == "510300"
        assert exc.details["normalized_code"] == "510300.SH"
        assert exc.details["trade_date"] == "2026-03-20"


def test_get_latest_price_prefers_data_center_quote(monkeypatch):
    service = UnifiedPriceService()
    observed_at = datetime.now(UTC)
    row = _quote_row(
        asset_code="159915.SZ",
        current_price=2.18,
        source="dc_eastmoney",
        snapshot_at=observed_at,
    )
    row.update(
        {
            "volume": 1000,
            "amount": 2180.0,
            "high": 2.2,
            "low": 2.15,
            "open": 2.16,
            "prev_close": 2.1,
        }
    )
    monkeypatch.setattr(
        price_service_module, "get_published_quote_payloads", lambda _codes: _published([row])
    )

    result = service.get_price_result("159915")

    assert result is not None
    assert result.price == 2.18
    assert result.source == "dc_eastmoney"
    assert result.observed_at == observed_at


def test_fund_price_can_read_from_data_center_nav(monkeypatch):
    service = UnifiedPriceService(now_provider=_after_close_now)
    monkeypatch.setattr(
        price_service_module,
        "get_published_quote_payloads",
        lambda _codes: _published([]),
    )
    monkeypatch.setattr(
        price_service_module,
        "get_published_price_bar_series",
        lambda _code, limit=1: _published([]),
    )
    monkeypatch.setattr(
        price_service_module,
        "get_published_fund_nav_series",
        lambda _code, limit=1: _published(
            [_nav_row(fund_code="110011", nav_date=_test_session_date(), source="dc_akshare")]
        ),
    )

    result = service.get_price_result("110011", asset_type="fund")

    assert result is not None
    assert result.price == 1.2345
    assert result.source == "dc_akshare"
    assert result.freshness == "close_fallback"


def test_latest_fund_nav_rejects_stale_observation(monkeypatch):
    service = UnifiedPriceService(now_provider=_after_close_now)
    monkeypatch.setattr(
        price_service_module, "get_published_quote_payloads", lambda _codes: _published([])
    )
    monkeypatch.setattr(
        price_service_module,
        "get_published_price_bar_series",
        lambda _code, limit=1: _published([]),
    )
    monkeypatch.setattr(
        price_service_module,
        "get_published_fund_nav_series",
        lambda _code, limit=1: _published(
            [
                _nav_row(
                    fund_code="110011",
                    nav_date=_test_session_date() - timedelta(days=30),
                    source="stale_nav",
                )
            ]
        ),
    )

    assert service.get_price_result("110011", asset_type="fund") is None


def test_stale_fund_nav_adapter_cannot_bypass_publication(monkeypatch):
    service = UnifiedPriceService(now_provider=_after_close_now)
    monkeypatch.setattr(
        price_service_module, "get_published_quote_payloads", lambda _codes: _published([])
    )
    monkeypatch.setattr(
        price_service_module,
        "get_published_price_bar_series",
        lambda _code, limit=1: _published([]),
    )
    monkeypatch.setattr(
        price_service_module, "get_published_fund_nav_series", lambda _code, limit=1: _published([])
    )
    service._fund_adapter = SimpleNamespace(
        fetch_fund_nav_em=lambda _code: pd.DataFrame(
            [{"nav_date": _test_session_date().isoformat(), "unit_nav": 1.2345}]
        )
    )

    result = service.get_price_result("110011", asset_type="fund")

    assert result is None


def test_realtime_quote_failure_returns_none_and_logs_debug(monkeypatch, caplog):
    service = UnifiedPriceService()
    monkeypatch.setattr(
        price_service_module,
        "get_published_quote_payloads",
        Mock(side_effect=RuntimeError("quote backend offline")),
    )

    with caplog.at_level("DEBUG"):
        result = service._get_realtime_quote("159915.SZ")

    assert result is None
    assert "Realtime quote lookup failed" in caplog.text


@pytest.mark.parametrize("invalid_price", [0.0, -1.0, float("nan"), float("inf"), True])
def test_invalid_realtime_price_falls_back_to_valid_close(invalid_price, monkeypatch):
    service = UnifiedPriceService(now_provider=_after_close_now)
    monkeypatch.setattr(
        price_service_module,
        "get_published_quote_payloads",
        lambda _codes: _published(
            [
                _quote_row(
                    asset_code="510300.SH",
                    current_price=invalid_price,
                    snapshot_at=datetime.now(UTC),
                    source="realtime",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        price_service_module,
        "get_published_price_bar_series",
        lambda _code, limit=1: _published(
            [_bar_row(asset_code="510300.SH", bar_date=_test_session_date(), source="daily_close")]
        ),
    )

    result = service.get_price_result("510300")

    assert result is not None
    assert result.price == 4.95
    assert result.source == "daily_close"
    assert result.freshness == "close_fallback"


def test_unattributed_price_is_not_exposed_to_business_modules(monkeypatch):
    service = UnifiedPriceService()
    monkeypatch.setattr(
        price_service_module,
        "get_published_quote_payloads",
        lambda _codes: _published(
            [
                _quote_row(
                    asset_code="159915.SZ",
                    current_price=2.18,
                    source=" ",
                    snapshot_at=datetime.now(UTC),
                )
            ]
        ),
    )
    monkeypatch.setattr(
        price_service_module,
        "get_published_price_bar_series",
        lambda _code, limit=1: _published([]),
    )

    assert service.get_latest_price("159915") is None
    with pytest.raises(DataFetchError, match="无法获取"):
        service.require_latest_price("159915")


@pytest.mark.parametrize("invalid_price", [0.0, -1.0, float("nan"), float("inf"), True])
def test_canonical_price_entities_reject_nonpositive_or_nonfinite_values(
    invalid_price,
):
    with pytest.raises(ValueError):
        PriceBar(
            asset_code="510300.SH",
            bar_date=date(2026, 3, 20),
            open=1.0,
            high=1.0,
            low=1.0,
            close=invalid_price,
            source="test",
        )
    with pytest.raises(ValueError):
        QuoteSnapshot(
            asset_code="510300.SH",
            snapshot_at=datetime(2026, 3, 20, tzinfo=UTC),
            current_price=invalid_price,
            source="test",
        )
    with pytest.raises(ValueError):
        FundNavFact(
            fund_code="110011",
            nav_date=date(2026, 3, 20),
            nav=invalid_price,
            source="test",
        )


def test_price_lookup_result_enforces_executable_price_invariants():
    with pytest.raises(ValueError, match="正有限数"):
        PriceLookupResult(
            requested_code="510300",
            normalized_code="510300.SH",
            price=float("nan"),
            as_of=date(2026, 3, 20),
            source="test",
            freshness="historical",
        )


def test_price_lookup_result_requires_real_observation_time_for_realtime() -> None:
    """A realtime label without an aware source observation time fails closed."""

    with pytest.raises(ValueError, match="观测时间"):
        PriceLookupResult(
            requested_code="510300",
            normalized_code="510300.SH",
            price=4.95,
            as_of=None,
            source="test",
            freshness="realtime",
        )

    with pytest.raises(ValueError, match="观测时间"):
        PriceLookupResult(
            requested_code="510300",
            normalized_code="510300.SH",
            price=4.95,
            as_of=None,
            source="test",
            freshness="realtime",
            observed_at=datetime(2026, 7, 30, 10, 0),
        )
    with pytest.raises(ValueError, match="数据来源"):
        PriceLookupResult(
            requested_code="510300",
            normalized_code="510300.SH",
            price=4.95,
            as_of=date(2026, 3, 20),
            source="",
            freshness="historical",
        )
