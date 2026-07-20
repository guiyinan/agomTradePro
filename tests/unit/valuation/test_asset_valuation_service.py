"""Application tests for injected valuation sources."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from apps.valuation.application.use_cases import AssetValuationService
from apps.valuation.domain.entities import ValuationSnapshot


class _FormalSource:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload

    def get_payload(self, security_code: str) -> dict | None:
        return self.payload


class _SnapshotSource:
    def __init__(self, payloads: list[dict] | None = None) -> None:
        self.payloads = payloads or []
        self.saved: ValuationSnapshot | None = None

    def list_recent_payloads(self, security_code: str) -> list[dict]:
        return self.payloads

    def get_today_fallback(self, security_code: str, today: date) -> ValuationSnapshot | None:
        return None

    def save_fallback(self, snapshot: ValuationSnapshot) -> ValuationSnapshot:
        self.saved = snapshot
        return snapshot


class _FactSource:
    def __init__(self, facts: list[dict] | None = None) -> None:
        self.facts = facts or []

    def list_recent(self, security_code: str, start: date, end: date) -> list[dict]:
        return self.facts


class _MarketPriceSource:
    def __init__(self, price: Decimal = Decimal("0")) -> None:
        self.price = price

    def get_latest(self, security_code: str) -> tuple[Decimal, str]:
        return self.price, "test_price"


def _service(
    *,
    formal: dict | None = None,
    snapshots: list[dict] | None = None,
    facts: list[dict] | None = None,
    price: Decimal = Decimal("0"),
) -> tuple[AssetValuationService, _SnapshotSource]:
    snapshot_source = _SnapshotSource(snapshots)
    return (
        AssetValuationService(
            formal_source=_FormalSource(formal),
            snapshot_source=snapshot_source,
            fact_source=_FactSource(facts),
            market_price_source=_MarketPriceSource(price),
            today_provider=lambda: date(2026, 7, 20),
        ),
        snapshot_source,
    )


def test_fresh_formal_valuation_has_priority() -> None:
    service, snapshot_source = _service(
        formal={
            "fair_value": 12,
            "entry_price_low": 11,
            "entry_price_high": 12,
            "target_price_low": 13,
            "target_price_high": 14,
            "stop_loss_price": 10,
            "valuation_date": date(2026, 7, 20),
            "quality_flag": "ok",
        },
        price=Decimal("9"),
    )

    result = service.get_valuation("000001.SZ")

    assert result is not None
    assert result["fair_value"] == 12
    assert snapshot_source.saved is None


def test_stale_formal_valuation_falls_through_to_valid_fact() -> None:
    service, _ = _service(
        formal={
            "fair_value": 12,
            "entry_price_low": 11,
            "entry_price_high": 12,
            "target_price_low": 13,
            "target_price_high": 14,
            "valuation_date": date(2026, 7, 20) - timedelta(days=31),
        },
        facts=[
            {
                "valuation_fact_date": date(2026, 7, 19),
                "extra": {"intrinsic_value_per_share": "11.8", "quality_flag": "ok"},
            }
        ],
    )

    result = service.get_valuation("000001.SZ")

    assert result is not None
    assert result["valuation_source"] == "data_center_valuation_fact"
    assert result["fair_value"] == 11.8


def test_missing_formal_sources_create_explicit_price_fallback() -> None:
    service, snapshot_source = _service(price=Decimal("10"))

    result = service.get_valuation("000001.SZ")

    assert result is not None
    assert result["valuation_method"] == "FALLBACK"
    assert result["valuation_source"] == "current_price_fallback"
    assert snapshot_source.saved is not None
    assert snapshot_source.saved.input_parameters["source"] == "test_price"
