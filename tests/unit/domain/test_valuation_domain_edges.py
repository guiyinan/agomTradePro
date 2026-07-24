"""Quality, freshness, and price-band tests for the Valuation Domain."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.valuation.domain.entities import create_valuation_snapshot
from apps.valuation.domain.rules import ValuationPayloadPolicy
from apps.valuation.domain.services import ValuationSnapshotService


def _formal_payload(today: date) -> dict[str, object]:
    """Build a complete fresh formal valuation."""
    return {
        "fair_value": "100",
        "entry_price_low": "95",
        "entry_price_high": "105",
        "target_price_low": "115",
        "target_price_high": "125",
        "stop_loss_price": "85",
        "valuation_method": "DCF",
        "valuation_date": today,
        "quality_flag": "ok",
    }


def test_snapshot_metrics_and_inclusive_price_boundaries() -> None:
    """Snapshot ratios and threshold predicates use inclusive boundaries."""
    snapshot = create_valuation_snapshot(
        security_code="000001.SZ",
        valuation_method="DCF",
        fair_value=Decimal("100"),
        entry_price_low=Decimal("90"),
        entry_price_high=Decimal("110"),
        target_price_low=Decimal("120"),
        target_price_high=Decimal("140"),
        stop_loss_price=Decimal("80"),
        input_parameters={"valuation_date": "2026-07-24"},
    )

    assert snapshot.calculated_at.tzinfo is UTC
    assert snapshot.entry_range == (Decimal("90"), Decimal("110"))
    assert snapshot.target_range == (Decimal("120"), Decimal("140"))
    assert snapshot.upside_potential == Decimal("30")
    assert snapshot.downside_risk == Decimal("20")
    assert snapshot.risk_reward_ratio == Decimal("1.5")
    assert snapshot.is_price_in_entry_range(Decimal("90")) is True
    assert snapshot.is_price_in_entry_range(Decimal("111")) is False
    assert snapshot.is_price_above_target(Decimal("120")) is True
    assert snapshot.should_stop_loss(Decimal("80")) is True
    assert snapshot.to_dict()["fair_value"] == "100"


def test_snapshot_metrics_fail_closed_for_non_positive_or_riskless_entry() -> None:
    """Invalid entry economics never produce infinite or misleading ratios."""
    snapshot = create_valuation_snapshot(
        security_code="000001.SZ",
        valuation_method="FALLBACK",
        fair_value=Decimal("0"),
        entry_price_low=Decimal("0"),
        entry_price_high=Decimal("0"),
        target_price_low=Decimal("10"),
        target_price_high=Decimal("10"),
        stop_loss_price=Decimal("1"),
        input_parameters={},
    )
    assert snapshot.upside_potential == 0
    assert snapshot.downside_risk == 0
    assert snapshot.risk_reward_ratio == 0

    no_downside = create_valuation_snapshot(
        security_code="000001.SZ",
        valuation_method="DCF",
        fair_value=Decimal("100"),
        entry_price_low=Decimal("90"),
        entry_price_high=Decimal("110"),
        target_price_low=Decimal("120"),
        target_price_high=Decimal("120"),
        stop_loss_price=Decimal("100"),
        input_parameters={},
    )
    assert no_downside.risk_reward_ratio == 0


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({}, True),
        ({"fair_value": 0}, False),
        ({"is_legacy": True}, False),
        ({"valuation_method": "legacy"}, False),
        ({"quality_flag": "stale"}, False),
        ({"is_valid": False}, False),
        ({"valuation_date": None}, False),
        ({"valuation_date": date(2026, 6, 23)}, False),
        ({"valuation_date": date(2026, 7, 25)}, False),
        ({"input_parameters": {"is_valid": False}}, False),
        ({"input_parameters": {"quality_flag": ["ok", "jump_alert"]}}, False),
    ],
)
def test_formal_payload_policy_enforces_quality_and_freshness(
    change: dict[str, object], expected: bool
) -> None:
    """Legacy, invalid, stale, future, or non-positive valuations are rejected."""
    today = date(2026, 7, 24)
    payload = _formal_payload(today) | change
    assert ValuationPayloadPolicy.is_usable(payload, today=today) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12.5", Decimal("12.5")),
        (12, Decimal("12")),
        (None, Decimal("0")),
        ("not-a-number", Decimal("0")),
    ],
)
def test_external_numeric_coercion_is_deterministic(value: object, expected: Decimal) -> None:
    """Malformed external numeric values normalize to zero."""
    assert ValuationPayloadPolicy.to_decimal(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        date(2026, 7, 24),
        datetime(2026, 7, 24, 1, tzinfo=UTC),
        "2026-07-24",
        "2026-07-24T01:02:03Z",
    ],
)
def test_supported_fact_dates_are_usable(value: object) -> None:
    """All supported external date encodings share one freshness rule."""
    payload = _formal_payload(date(2026, 7, 24))
    payload.pop("valuation_date")
    payload["fetched_at"] = value
    assert ValuationPayloadPolicy.is_usable(payload, today=date(2026, 7, 24)) is True


def test_nested_date_and_malformed_date_paths() -> None:
    """Nested audit dates are accepted while malformed dates fail closed."""
    today = date(2026, 7, 24)
    nested = _formal_payload(today)
    nested.pop("valuation_date")
    nested["input_parameters"] = {"as_of_date": "2026-07-24"}
    assert ValuationPayloadPolicy.is_usable(nested, today=today) is True

    malformed = nested | {"input_parameters": {"as_of_date": "not-a-date"}}
    assert ValuationPayloadPolicy.is_usable(malformed, today=today) is False


def test_fact_payload_rejects_invalid_shape_and_applies_price_defaults() -> None:
    """Fact normalization rejects unusable facts and fills conservative bands."""
    today = date(2026, 7, 24)
    assert ValuationPayloadPolicy.build_fact_payload({"extra": []}, today=today) is None
    assert (
        ValuationPayloadPolicy.build_fact_payload({"extra": {"fair_value": 0}}, today=today) is None
    )

    payload = ValuationPayloadPolicy.build_fact_payload(
        {
            "valuation_fact_date": today,
            "extra": {
                "estimated_fair_value": "100",
                "entry_low": "0",
                "quality_flag": "ok",
            },
        },
        today=today,
    )
    assert payload is not None
    assert payload["entry_price_low"] == 95.0
    assert payload["target_price_high"] == 125.0
    assert payload["stop_loss_price"] == 85.5

    assert (
        ValuationPayloadPolicy.build_fact_payload(
            {
                "valuation_fact_date": today - timedelta(days=31),
                "extra": {"fair_value": 100, "quality_flag": "ok"},
            },
            today=today,
        )
        is None
    )


@pytest.mark.parametrize(
    ("score", "multiplier"),
    [(80, "1.3"), (60, "1.15"), (40, "1.0"), (39, "0.9")],
)
def test_comprehensive_score_maps_to_explicit_fair_value_bands(score: int, multiplier: str) -> None:
    """Composite score tiers map to stable fair-value multipliers."""
    result = SimpleNamespace(
        overall_score=score,
        overall_signal="neutral",
        confidence=0.8,
        scores=[SimpleNamespace(method="PE", score=score, signal="neutral")],
    )
    snapshot = ValuationSnapshotService().create_from_comprehensive_valuation(
        "000001.SZ",
        result,
        Decimal("100"),
    )
    assert snapshot.fair_value == Decimal("100") * Decimal(multiplier)
    assert snapshot.valuation_method == "COMPOSITE"


def test_snapshot_service_handles_current_price_legacy_and_fallback_paths() -> None:
    """Formal, legacy, and fallback creation preserve their audit semantics."""
    service = ValuationSnapshotService()
    discounted = service.create_snapshot(
        "000001.SZ",
        "DCF",
        Decimal("100"),
        Decimal("80"),
        {"source": "model"},
        stop_loss_pct=0.2,
        target_upside_pct=0.3,
    )
    assert discounted.entry_price_low == Decimal("78.40")
    assert discounted.target_price_low == Decimal("124.00")

    legacy = service.create_legacy_snapshot("000001.SZ", Decimal("0"), Decimal("90"))
    assert legacy.is_legacy is True
    assert legacy.fair_value == Decimal("90")

    fallback = service.create_current_price_fallback_snapshot(
        "000001.SZ", Decimal("100"), source="latest_quote"
    )
    assert fallback.valuation_method == "FALLBACK"
    assert fallback.input_parameters["source"] == "latest_quote"
    assert fallback.stop_loss_price == Decimal("90.00")


def test_snapshot_serialization_contract_for_recommendations() -> None:
    """Recommendation payloads expose numeric bands and snapshot lineage."""
    snapshot = ValuationSnapshotService().create_current_price_fallback_snapshot(
        "000001.SZ", Decimal("100")
    )
    payload = ValuationPayloadPolicy.snapshot_to_payload(
        snapshot,
        valuation_source="test",
    )
    assert payload["fair_value"] == 100.0
    assert payload["valuation_snapshot_id"] == snapshot.snapshot_id
    assert payload["valuation_source"] == "test"
