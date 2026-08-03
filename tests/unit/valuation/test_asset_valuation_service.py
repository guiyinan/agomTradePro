"""Application tests for injected valuation sources."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from apps.valuation.application.use_cases import AssetValuationService
from apps.valuation.domain.entities import ValuationSnapshot
from apps.valuation.infrastructure.providers import (
    AssetAnalysisValuationSource,
    DataCenterValuationFactSource,
    ObservableMarketPriceSource,
)


class _FormalSource:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload

    def get_payload(self, security_code: str) -> dict | None:
        return self.payload


class _SnapshotSource:
    def __init__(
        self,
        payloads: list[dict] | None = None,
        today_fallback: ValuationSnapshot | None = None,
    ) -> None:
        self.payloads = payloads or []
        self.today_fallback = today_fallback
        self.saved: ValuationSnapshot | None = None

    def list_recent_payloads(self, security_code: str) -> list[dict]:
        return self.payloads

    def get_today_fallback(self, security_code: str, today: date) -> ValuationSnapshot | None:
        return self.today_fallback

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
    today_fallback: ValuationSnapshot | None = None,
) -> tuple[AssetValuationService, _SnapshotSource]:
    snapshot_source = _SnapshotSource(snapshots, today_fallback)
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


def test_observable_market_price_uses_canonical_freshness_service() -> None:
    """Valuation cannot bypass the unified stale-quote and stale-close boundary."""

    unified = SimpleNamespace(
        require_latest_price_result=lambda _code: SimpleNamespace(
            price=10.25,
            source="daily_close",
            freshness="close_fallback",
        )
    )

    with patch(
        "apps.valuation.infrastructure.providers.UnifiedPriceService",
        return_value=unified,
    ):
        price, source = ObservableMarketPriceSource().get_latest("000001.SZ")

    assert price == Decimal("10.25")
    assert source == "daily_close:close_fallback"


def test_legacy_formal_missing_price_fields_remain_unknown() -> None:
    class _LegacyValuationService:
        def get_latest_valuation(self, security_code: str) -> object:
            return SimpleNamespace(fair_value=12)

    with patch(
        "apps.valuation.infrastructure.providers.import_module",
        return_value=SimpleNamespace(ValuationService=_LegacyValuationService),
    ):
        payload = AssetAnalysisValuationSource().get_payload("000001.SZ")

    assert payload is not None
    assert payload["fair_value"] == 12
    assert payload["entry_price_low"] is None
    assert payload["entry_price_high"] is None
    assert payload["target_price_low"] is None
    assert payload["target_price_high"] is None
    assert payload["stop_loss_price"] is None


def test_canonical_valuation_source_blocks_unpublished_rows(monkeypatch) -> None:
    published_payload = {
        "rows": [
            {
                "val_date": "2026-07-20",
                "fetched_at": "2026-07-20T08:00:00+00:00",
                "extra": {"intrinsic_value_per_share": "11.8"},
            }
        ],
        "must_not_use_for_decision": True,
        "blocked_reason": "publication_observation_stale",
    }
    monkeypatch.setattr(
        "apps.valuation.infrastructure.providers.get_published_valuation_facts",
        lambda *args, **kwargs: published_payload,
    )

    facts = DataCenterValuationFactSource().list_recent(
        "000001.SZ",
        date(2026, 7, 1),
        date(2026, 7, 20),
    )

    assert facts == []


def test_canonical_valuation_source_preserves_published_observation(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.valuation.infrastructure.providers.get_published_valuation_facts",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "val_date": "2026-07-20",
                    "fetched_at": "2026-07-20T08:00:00+00:00",
                    "extra": {"intrinsic_value_per_share": "11.8"},
                }
            ],
            "must_not_use_for_decision": False,
        },
    )

    facts = DataCenterValuationFactSource().list_recent(
        "000001.SZ",
        date(2026, 7, 1),
        date(2026, 7, 20),
    )

    assert facts == [
        {
            "valuation_fact_date": "2026-07-20",
            "fetched_at": "2026-07-20T08:00:00+00:00",
            "extra": {"intrinsic_value_per_share": "11.8"},
        }
    ]


def test_persisted_price_fallback_cannot_bypass_canonical_price() -> None:
    """A historical FALLBACK row is not a formal valuation source."""

    service, snapshot_source = _service(
        snapshots=[
            {
                "fair_value": 99,
                "entry_price_low": 95,
                "entry_price_high": 101,
                "target_price_low": 110,
                "target_price_high": 120,
                "stop_loss_price": 90,
                "valuation_method": "FALLBACK",
                "calculated_at": date(2026, 7, 20),
            }
        ],
        price=Decimal("10"),
    )

    result = service.get_valuation("000001.SZ")

    assert result is not None
    assert result["fair_value"] == 10.0
    assert snapshot_source.saved is not None
    assert snapshot_source.saved.fair_value == Decimal("10")


def test_today_fallback_cannot_bypass_unavailable_canonical_price() -> None:
    """Even today's fallback must be revalidated through the canonical source."""

    existing = ValuationSnapshot(
        snapshot_id="vs_existing",
        security_code="000001.SZ",
        valuation_method="FALLBACK",
        fair_value=Decimal("99"),
        entry_price_low=Decimal("95"),
        entry_price_high=Decimal("101"),
        target_price_low=Decimal("110"),
        target_price_high=Decimal("120"),
        stop_loss_price=Decimal("90"),
        calculated_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
        input_parameters={"source": "old_price:realtime"},
    )
    service, snapshot_source = _service(
        price=Decimal("0"),
        today_fallback=existing,
    )

    assert service.get_valuation("000001.SZ") is None
    assert snapshot_source.saved is None
