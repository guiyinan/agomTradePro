"""Safety coverage for valuation source selection and price fallback."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import pytest

from apps.valuation.application.use_cases import AssetValuationService
from apps.valuation.domain.entities import ValuationSnapshot


class TrackingFormalSource:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.error = error

    def get_payload(self, security_code: str) -> dict[str, object] | None:
        self.calls.append(security_code)
        if self.error is not None:
            raise self.error
        return None


class TrackingSnapshotSource:
    def __init__(self) -> None:
        self.list_calls: list[str] = []
        self.fallback_calls: list[tuple[str, date]] = []
        self.saved: list[ValuationSnapshot] = []

    def list_recent_payloads(self, security_code: str) -> list[dict[str, object]]:
        self.list_calls.append(security_code)
        return []

    def get_today_fallback(
        self,
        security_code: str,
        today: date,
    ) -> ValuationSnapshot | None:
        self.fallback_calls.append((security_code, today))
        return None

    def save_fallback(self, snapshot: ValuationSnapshot) -> ValuationSnapshot:
        self.saved.append(snapshot)
        return snapshot


class TrackingFactSource:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_recent(
        self,
        security_code: str,
        start: date,
        end: date,
    ) -> list[dict[str, object]]:
        del start, end
        self.calls.append(security_code)
        return []


class TrackingMarketPriceSource:
    def __init__(self, price: Decimal, source: str = "truthful_price") -> None:
        self.price = price
        self.source = source
        self.calls: list[str] = []

    def get_latest(self, security_code: str) -> tuple[Decimal, str]:
        self.calls.append(security_code)
        return self.price, self.source


def _service(
    *,
    price: Decimal = Decimal("10"),
    price_source: str = "truthful_price",
    formal_error: Exception | None = None,
) -> tuple[
    AssetValuationService,
    TrackingFormalSource,
    TrackingSnapshotSource,
    TrackingFactSource,
    TrackingMarketPriceSource,
]:
    formal = TrackingFormalSource(error=formal_error)
    snapshots = TrackingSnapshotSource()
    facts = TrackingFactSource()
    market = TrackingMarketPriceSource(price, price_source)
    return (
        AssetValuationService(
            formal_source=formal,
            snapshot_source=snapshots,
            fact_source=facts,
            market_price_source=market,
            today_provider=lambda: date(2026, 7, 28),
        ),
        formal,
        snapshots,
        facts,
        market,
    )


@pytest.mark.parametrize("security_code", ["", "   ", "bad code", "A" * 21])
def test_invalid_security_code_is_rejected_before_source_io(security_code: str) -> None:
    service, formal, snapshots, facts, market = _service()

    assert service.get_valuation(security_code) is None
    assert formal.calls == []
    assert snapshots.list_calls == []
    assert snapshots.fallback_calls == []
    assert facts.calls == []
    assert market.calls == []


@pytest.mark.parametrize("price", [Decimal("NaN"), Decimal("Infinity"), Decimal("-1")])
def test_invalid_market_price_never_persists_fallback(price: Decimal) -> None:
    service, _, snapshots, _, _ = _service(price=price)

    assert service.get_valuation("000001.SZ") is None
    assert snapshots.saved == []


def test_invalid_price_source_never_persists_fallback() -> None:
    service, _, snapshots, _, _ = _service(price_source="provider\ntoken=secret")

    assert service.get_valuation("000001.SZ") is None
    assert snapshots.saved == []


def test_security_code_is_normalized_once_for_all_sources() -> None:
    service, formal, snapshots, facts, market = _service()

    result = service.get_valuation(" 000001.sz ")

    assert result is not None
    assert formal.calls == ["000001.SZ"]
    assert snapshots.list_calls == ["000001.SZ"]
    assert facts.calls == ["000001.SZ"]
    assert market.calls == ["000001.SZ"]
    assert snapshots.saved[0].security_code == "000001.SZ"


def test_provider_exception_details_are_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, _, _, _, _ = _service(
        formal_error=RuntimeError("valuation failed: token=secret"),
    )

    with caplog.at_level(logging.WARNING):
        assert service.get_valuation("000001.SZ") is None

    assert "RuntimeError" in caplog.text
    assert "token=secret" not in caplog.text
