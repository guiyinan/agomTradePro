"""Pure tests for the Portfolio benchmark price-fixing methodology."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest

from apps.portfolio.domain.policy_benchmark_price_fixing import (
    POLICY_BENCHMARK_PRICE_FIXING_TYPE,
    PolicyBenchmarkPriceSourceRef,
    PortfolioPolicyBenchmarkPriceFixing,
)

RECORDED_AT = datetime(2026, 3, 1, tzinfo=UTC)
VALID_UNTIL = datetime(2027, 3, 1, tzinfo=UTC)


def _source(ordinal: int, source_id: str) -> PolicyBenchmarkPriceSourceRef:
    return PolicyBenchmarkPriceSourceRef(
        owner="portfolio",
        artifact_type="benchmark_price_source_definition",
        artifact_id=source_id,
        artifact_version="v1",
        content_hash=("a" if ordinal == 0 else "b") * 64,
        ordinal=ordinal,
        recorded_at=RECORDED_AT - timedelta(days=1),
        valid_until=VALID_UNTIL,
    )


def _methodology(**changes: object) -> PortfolioPolicyBenchmarkPriceFixing:
    values: dict[str, object] = {
        "methodology_id": "cn-listed-benchmark-price-fixing",
        "methodology_version": "v1",
        "price_identifier_namespace": "MIC_TICKER",
        "price_field": "close",
        "adjustment_basis": "unadjusted",
        "venue": "XSHG",
        "timezone": "Asia/Shanghai",
        "valuation_cutoff_local": time(15, 30),
        "source_priority": (_source(0, "licensed-eod-primary"), _source(1, "official-eod")),
        "stale_after_seconds": 86_400,
        "missing_price_policy": "fail_closed",
        "recorded_at": RECORDED_AT,
        "valid_until": VALID_UNTIL,
    }
    values.update(changes)
    return PortfolioPolicyBenchmarkPriceFixing(**values)  # type: ignore[arg-type]


def test_definition_seals_exact_owner_price_semantics_and_safety() -> None:
    value = _methodology()
    payload = value.to_payload()

    assert value.owner == "portfolio"
    assert value.artifact_type == "price_fixing_methodology"
    assert value.schema == "portfolio-policy-benchmark-price-fixing.v1"
    assert value.permission == "methodology_definition_only"
    assert value.activation_available is False
    assert value.automatic_fallback_allowed is False
    assert value.must_not_execute is True
    assert len(value.identity_hash) == len(value.content_hash) == 64
    assert payload["valuation_cutoff_local"] == "15:30:00"
    assert payload["source_priority"][0]["ordinal"] == 0  # type: ignore[index]


@pytest.mark.parametrize("price_field", ["close", "nav", "settlement"])
def test_price_field_evidence_minimum_is_explicit(price_field: str) -> None:
    assert _methodology(price_field=price_field).price_field == price_field


def test_unknown_field_adjustment_and_identifier_namespace_fail_closed() -> None:
    with pytest.raises(ValueError, match="price_field"):
        _methodology(price_field="last")
    with pytest.raises(ValueError, match="adjustment_basis"):
        _methodology(adjustment_basis="auto_adjusted")
    with pytest.raises(ValueError, match="namespace"):
        _methodology(price_identifier_namespace="ticker with fallback")


def test_source_priority_is_exact_unique_and_not_automatic_fallback() -> None:
    value = _methodology()
    with pytest.raises(ValueError, match="ordinal"):
        _methodology(source_priority=(value.source_priority[1], value.source_priority[0]))
    with pytest.raises(ValueError, match="unique"):
        _methodology(source_priority=(_source(0, "same"), _source(1, "same")))
    with pytest.raises(ValueError, match="valid_until"):
        _methodology(
            source_priority=(
                replace(_source(0, "x"), valid_until=VALID_UNTIL - timedelta(seconds=1)),
            )
        )
    assert value.automatic_fallback_allowed is False
    assert value.source_failure_policy == "block"


def test_stale_missing_and_scalar_types_cannot_be_weakened() -> None:
    with pytest.raises(TypeError, match="exact positive integer"):
        _methodology(stale_after_seconds=1.5)
    with pytest.raises(ValueError, match="positive"):
        _methodology(stale_after_seconds=0)
    with pytest.raises(ValueError, match="fail_closed"):
        _methodology(missing_price_policy="use_previous")
    with pytest.raises(ValueError, match="block"):
        _methodology(source_failure_policy="try_next")


def test_iana_timezone_and_cutoff_are_dst_safe_for_validity_window() -> None:
    with pytest.raises(ValueError, match="IANA timezone"):
        _methodology(timezone="Not/AZone")
    with pytest.raises(ValueError, match="does not exist"):
        _methodology(
            timezone="America/New_York",
            valuation_cutoff_local=time(2, 30),
            recorded_at=datetime(2026, 3, 8, 0, tzinfo=UTC),
            valid_until=datetime(2026, 3, 9, 5, tzinfo=UTC),
            source_priority=(
                replace(
                    _source(0, "spring-source"),
                    recorded_at=datetime(2026, 3, 7, tzinfo=UTC),
                    valid_until=datetime(2026, 3, 9, 5, tzinfo=UTC),
                ),
            ),
        )
    with pytest.raises(ValueError, match="ambiguous"):
        _methodology(
            timezone="America/New_York",
            valuation_cutoff_local=time(1, 30),
            recorded_at=datetime(2026, 11, 1, 0, tzinfo=UTC),
            valid_until=datetime(2026, 11, 2, 5, tzinfo=UTC),
            source_priority=(
                replace(
                    _source(0, "fall-source"),
                    recorded_at=datetime(2026, 10, 31, tzinfo=UTC),
                    valid_until=datetime(2026, 11, 2, 5, tzinfo=UTC),
                ),
            ),
        )


def test_hash_binds_sources_cutoff_staleness_and_clock() -> None:
    value = _methodology()
    changed = _methodology(stale_after_seconds=43_200)
    assert changed.identity_hash == value.identity_hash
    assert changed.content_hash != value.content_hash
    with pytest.raises(ValueError, match="content_hash"):
        replace(value, venue="XSHE")
    with pytest.raises(ValueError, match="timezone-aware"):
        _methodology(recorded_at=datetime(2026, 3, 1))


def test_owner_type_cannot_be_substituted_and_domain_has_zero_cross_app_imports() -> None:
    assert POLICY_BENCHMARK_PRICE_FIXING_TYPE == "price_fixing_methodology"
    with pytest.raises(ValueError, match="authority"):
        _methodology(owner="valuation")
    source = Path("apps/portfolio/domain/policy_benchmark_price_fixing.py").read_text(
        encoding="utf-8"
    )
    assert "django" not in source
    assert "from apps." not in source
    assert "import apps." not in source
