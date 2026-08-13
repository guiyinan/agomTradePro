"""Pure tests for the Portfolio benchmark FX-fixing methodology."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest

from apps.portfolio.domain.policy_benchmark_fx_fixing import (
    POLICY_BENCHMARK_FX_FIXING_TYPE,
    PolicyBenchmarkFxSourceRef,
    PortfolioPolicyBenchmarkFxFixing,
)

RECORDED_AT = datetime(2026, 3, 1, tzinfo=UTC)
VALID_UNTIL = datetime(2027, 3, 1, tzinfo=UTC)


def _source(ordinal: int, artifact_id: str) -> PolicyBenchmarkFxSourceRef:
    return PolicyBenchmarkFxSourceRef(
        owner="portfolio",
        artifact_type="benchmark_fx_source_definition",
        artifact_id=artifact_id,
        artifact_version="v1",
        content_hash=("a" if ordinal == 0 else "b") * 64,
        ordinal=ordinal,
        recorded_at=RECORDED_AT - timedelta(days=1),
        valid_until=VALID_UNTIL,
    )


def _methodology(**changes: object) -> PortfolioPolicyBenchmarkFxFixing:
    values: dict[str, object] = {
        "methodology_id": "usd-cny-benchmark-fixing",
        "methodology_version": "v1",
        "base_currency": "USD",
        "quote_currency": "CNY",
        "fixing_convention": "quote_per_base",
        "inverse_rate_allowed": False,
        "timezone": "Asia/Shanghai",
        "valuation_cutoff_local": time(16, 30),
        "source_priority": (_source(0, "official-usdcny"), _source(1, "licensed-usdcny")),
        "stale_after_seconds": 86_400,
        "triangulation_policy": "prohibited",
        "source_failure_policy": "block",
        "missing_fx_policy": "fail_closed",
        "recorded_at": RECORDED_AT,
        "valid_until": VALID_UNTIL,
    }
    values.update(changes)
    return PortfolioPolicyBenchmarkFxFixing(**values)  # type: ignore[arg-type]


def test_definition_seals_pair_direction_sources_and_inactive_authority() -> None:
    value = _methodology()
    payload = value.to_payload()
    assert value.owner == "portfolio"
    assert value.artifact_type == "fx_fixing_methodology"
    assert value.permission == "methodology_definition_only"
    assert value.activation_available is False
    assert value.automatic_fallback_allowed is False
    assert value.must_not_execute is True
    assert payload["currency_pair"] == "USD/CNY"
    assert payload["valuation_cutoff_local"] == "16:30:00"
    assert len(value.identity_hash) == len(value.content_hash) == 64


def test_currency_pair_and_fixing_convention_are_exact() -> None:
    with pytest.raises(ValueError, match="currency"):
        _methodology(base_currency="usd")
    with pytest.raises(ValueError, match="distinct"):
        _methodology(quote_currency="USD")
    with pytest.raises(ValueError, match="fixing_convention"):
        _methodology(fixing_convention="market_default")
    with pytest.raises(TypeError, match="inverse_rate_allowed"):
        _methodology(inverse_rate_allowed=1)
    inverse = _methodology(fixing_convention="base_per_quote", inverse_rate_allowed=True)
    assert inverse.fixing_convention == "base_per_quote"


def test_v1_triangulation_and_fallback_are_prohibited() -> None:
    with pytest.raises(ValueError, match="triangulation"):
        _methodology(triangulation_policy="via_usd")
    with pytest.raises(ValueError, match="source_failure_policy"):
        _methodology(source_failure_policy="try_next")
    with pytest.raises(ValueError, match="fail_closed"):
        _methodology(missing_fx_policy="use_previous")
    assert _methodology().triangulation_currency is None
    with pytest.raises(ValueError, match="triangulation_currency"):
        _methodology(triangulation_currency="USD")


def test_source_priority_is_exact_ordered_unique_and_min_validity_bound() -> None:
    value = _methodology()
    with pytest.raises(ValueError, match="ordinal"):
        _methodology(source_priority=(value.source_priority[1], value.source_priority[0]))
    with pytest.raises(ValueError, match="unique"):
        _methodology(source_priority=(_source(0, "same"), _source(1, "same")))
    with pytest.raises(ValueError, match="valid_until"):
        _methodology(
            source_priority=(
                replace(_source(0, "short"), valid_until=VALID_UNTIL - timedelta(seconds=1)),
            )
        )


def test_staleness_and_types_reject_float_bool_and_unknown_values() -> None:
    with pytest.raises(TypeError, match="exact positive integer"):
        _methodology(stale_after_seconds=1.5)
    with pytest.raises(TypeError, match="exact positive integer"):
        _methodology(stale_after_seconds=True)
    with pytest.raises(ValueError, match="positive"):
        _methodology(stale_after_seconds=0)


def test_iana_cutoff_rejects_dst_gap_and_ambiguity() -> None:
    with pytest.raises(ValueError, match="IANA timezone"):
        _methodology(timezone="Not/AZone")
    spring_source = replace(
        _source(0, "spring"),
        recorded_at=datetime(2026, 3, 7, tzinfo=UTC),
        valid_until=datetime(2026, 3, 9, 5, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="does not exist"):
        _methodology(
            timezone="America/New_York",
            valuation_cutoff_local=time(2, 30),
            recorded_at=datetime(2026, 3, 8, tzinfo=UTC),
            valid_until=spring_source.valid_until,
            source_priority=(spring_source,),
        )
    fall_source = replace(
        _source(0, "fall"),
        recorded_at=datetime(2026, 10, 31, tzinfo=UTC),
        valid_until=datetime(2026, 11, 2, 5, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="ambiguous"):
        _methodology(
            timezone="America/New_York",
            valuation_cutoff_local=time(1, 30),
            recorded_at=datetime(2026, 11, 1, tzinfo=UTC),
            valid_until=fall_source.valid_until,
            source_priority=(fall_source,),
        )


def test_hash_binds_pair_direction_cutoff_sources_and_policy() -> None:
    value = _methodology()
    changed = _methodology(stale_after_seconds=43_200)
    assert changed.identity_hash == value.identity_hash
    assert changed.content_hash != value.content_hash
    with pytest.raises(ValueError, match="content_hash"):
        replace(value, quote_currency="HKD")
    with pytest.raises(ValueError, match="timezone-aware"):
        _methodology(recorded_at=datetime(2026, 3, 1))


def test_fixed_owner_and_zero_cross_app_dependencies() -> None:
    assert POLICY_BENCHMARK_FX_FIXING_TYPE == "fx_fixing_methodology"
    with pytest.raises(ValueError, match="authority"):
        _methodology(owner="data_center")
    source = Path("apps/portfolio/domain/policy_benchmark_fx_fixing.py").read_text(encoding="utf-8")
    assert "django" not in source
    assert "from apps." not in source
    assert "import apps." not in source
