"""Pure tests for the complete Portfolio policy benchmark definition."""

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.portfolio.domain.policy_benchmark_definition import (
    POLICY_BENCHMARK_DEFINITION_BLOCKERS,
    PolicyBenchmarkConstituentDefinition,
    PolicyBenchmarkMethodologyRef,
    PortfolioPolicyBenchmarkDefinition,
)

NOW = datetime(2026, 8, 13, 7, tzinfo=UTC)
HASH = "a" * 64


def _ref(kind: str, days: int = 30) -> PolicyBenchmarkMethodologyRef:
    return PolicyBenchmarkMethodologyRef(
        owner="portfolio",
        artifact_type=kind,
        artifact_id=f"{kind}-cn-v1",
        artifact_version="v1",
        content_hash=HASH,
        recorded_at=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(days=days),
    )


def _definition(**changes: object) -> PortfolioPolicyBenchmarkDefinition:
    values: dict[str, object] = {
        "definition_id": "balanced-policy-benchmark",
        "definition_version": "v1",
        "base_currency": "CNY",
        "constituents": (
            PolicyBenchmarkConstituentDefinition(
                benchmark_code="CSI300",
                price_identifier="000300.SH",
                currency="CNY",
                weight=Decimal("0.6"),
                ordinal=0,
            ),
            PolicyBenchmarkConstituentDefinition(
                benchmark_code="CGB_TOTAL_RETURN",
                price_identifier="CBA00101.CS",
                currency="CNY",
                weight=Decimal("0.4"),
                ordinal=1,
            ),
        ),
        "trading_calendar_ref": _ref("trading_calendar_definition"),
        "price_fixing_ref": _ref("price_fixing_methodology"),
        "fx_fixing_ref": _ref("fx_fixing_methodology"),
        "corporate_action_ref": _ref("corporate_action_methodology"),
        "cost_tax_ref": _ref("cost_tax_methodology"),
        "valuation_timezone": "Asia/Shanghai",
        "valuation_cutoff": "15:00:00",
        "evaluation_window_days": 252,
        "max_price_age_seconds": 86400,
        "max_fx_age_seconds": 86400,
        "missing_price_policy": "fail_closed",
        "missing_fx_policy": "fail_closed",
        "recorded_at": NOW,
        "valid_until": NOW + timedelta(days=30),
    }
    values.update(changes)
    return PortfolioPolicyBenchmarkDefinition(**values)  # type: ignore[arg-type]


def test_definition_covers_complete_benchmark_methodology() -> None:
    value = _definition()
    payload = value.to_payload()

    assert value.permission == "definition_only"
    assert value.activation_available is False
    assert value.must_not_execute is True
    assert value.blocker_codes == POLICY_BENCHMARK_DEFINITION_BLOCKERS
    assert len(payload["methodology_refs"]) == 5  # type: ignore[arg-type]
    names = {field.name for field in fields(PortfolioPolicyBenchmarkDefinition)}
    assert {
        "trading_calendar_ref",
        "price_fixing_ref",
        "fx_fixing_ref",
        "corporate_action_ref",
        "cost_tax_ref",
        "evaluation_window_days",
        "max_price_age_seconds",
        "max_fx_age_seconds",
        "missing_price_policy",
        "missing_fx_policy",
    } <= names


def test_weights_are_exact_decimal_unique_and_conserved() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        PolicyBenchmarkConstituentDefinition("A", "A", "CNY", 0.5, 0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sum exactly"):
        _definition(
            constituents=(
                PolicyBenchmarkConstituentDefinition("A", "A.CN", "CNY", Decimal("0.9"), 0),
            )
        )
    with pytest.raises(ValueError, match="unique"):
        _definition(
            constituents=(
                PolicyBenchmarkConstituentDefinition("A", "A.CN", "CNY", Decimal("0.5"), 0),
                PolicyBenchmarkConstituentDefinition("A", "B.CN", "CNY", Decimal("0.5"), 1),
            )
        )


def test_missing_and_stale_policies_are_strictly_fail_closed() -> None:
    with pytest.raises(ValueError, match="missing_price_policy"):
        _definition(missing_price_policy="carry_forward")
    with pytest.raises(ValueError, match="missing_fx_policy"):
        _definition(missing_fx_policy="spot_fallback")
    with pytest.raises(ValueError, match="max_price_age_seconds"):
        _definition(max_price_age_seconds=0)
    with pytest.raises(ValueError, match="max_fx_age_seconds"):
        _definition(max_fx_age_seconds=True)


def test_methodology_refs_are_complete_ordered_and_bound_to_hash() -> None:
    value = _definition()
    changed = _definition(price_fixing_ref=replace(value.price_fixing_ref, content_hash="b" * 64))

    assert changed.content_hash != value.content_hash
    with pytest.raises(ValueError, match="complete and ordered"):
        _definition(price_fixing_ref=_ref("trading_calendar_definition"))


def test_validity_is_strict_minimum_and_sources_must_be_knowable() -> None:
    with pytest.raises(ValueError, match="source minimum"):
        _definition(valid_until=NOW + timedelta(days=29))
    with pytest.raises(ValueError, match="not knowable"):
        _definition(
            cost_tax_ref=replace(
                _ref("cost_tax_methodology"),
                recorded_at=NOW + timedelta(seconds=1),
            )
        )


def test_hash_binds_constituents_rules_and_clocks() -> None:
    value = _definition()
    changed = _definition(evaluation_window_days=126)

    assert changed.identity_hash == value.identity_hash
    assert changed.content_hash != value.content_hash
    with pytest.raises(ValueError, match="content_hash"):
        replace(value, evaluation_window_days=126)


def test_definition_has_no_status_activation_or_external_imports() -> None:
    names = {field.name for field in fields(PortfolioPolicyBenchmarkDefinition)}
    assert not {"status", "active", "activated_at", "approved_by"} & names

    source = Path("apps/portfolio/domain/policy_benchmark_definition.py").read_text(
        encoding="utf-8"
    )
    assert "django" not in source
    assert "from apps." not in source
    assert "import apps." not in source
