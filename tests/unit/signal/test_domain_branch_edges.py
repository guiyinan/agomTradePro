"""Behavioral boundary tests for the Signal Domain contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

import apps.signal.domain.indicators as indicators
import apps.signal.domain.rules as rules
from apps.regime.domain.asset_eligibility import Eligibility
from apps.signal.domain.forecast_realization_source_definition import (
    ForecastRealizationSourceDefinition,
    validated_manifest_source_copy,
)
from apps.signal.domain.indicators import (
    IndicatorCategory,
    IndicatorDefinition,
    find_indicator_by_alias,
    get_indicator,
    get_indicators_by_category,
    register_indicator,
)
from apps.signal.domain.parser import InvalidationLogicParser
from tests.unit.signal.test_forecast_realization_owner import RECORDED_AT, _source


def test_indicator_lookup_keeps_the_first_equal_alias_and_prefers_a_longer_name() -> None:
    """Alias ties stay deterministic while a more specific indicator name wins."""

    equal_alias_match = find_indicator_by_alias("PMI CPI")
    assert equal_alias_match is not None
    assert equal_alias_match.code == "CN_PMI_MANUFACTURING"

    longer_name_match = find_indicator_by_alias("PMI GDP同比")
    assert longer_name_match is not None
    assert longer_name_match.code == "CN_GDP_YOY"


def test_indicator_registration_updates_the_public_registry_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A runtime registration is visible through every public lookup surface."""

    monkeypatch.setattr(indicators, "INDICATOR_REGISTRY", dict(indicators.INDICATOR_REGISTRY))
    custom = IndicatorDefinition(
        code="TEST_SIGNAL_EDGE",
        name="测试信号指标",
        category=IndicatorCategory.MARKET,
        unit="点",
        aliases=["测试信号"],
    )

    register_indicator(custom)

    assert get_indicator(custom.code) is custom
    assert find_indicator_by_alias("测试信号") is custom
    assert custom in get_indicators_by_category(IndicatorCategory.MARKET)


def test_parser_reports_missing_threshold_after_the_default_operator_path() -> None:
    """An indicator without a comparison still fails clearly when no threshold exists."""

    result = InvalidationLogicParser().parse("PMI")

    assert result.success is False
    assert result.rule is None
    assert result.error is not None
    assert "无法提取阈值" in result.error


def test_low_confidence_preferred_asset_remains_eligible() -> None:
    """Low confidence rejects neutral assets but leaves a preferred asset usable."""

    rejected, reason, eligibility = rules.should_reject_signal(
        "a_share_growth",
        "Recovery",
        policy_level=0,
        confidence=0.2,
    )

    assert rejected is False
    assert reason is None
    assert eligibility is Eligibility.PREFERRED


def test_rejection_record_requires_complete_rejection_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected signal without reason or eligibility cannot become an audit record."""

    monkeypatch.setattr(
        rules,
        "should_reject_signal",
        lambda *_args: (True, None, Eligibility.HOSTILE),
    )

    with pytest.raises(RuntimeError, match="missing rejection evidence"):
        rules.create_rejection_record(
            "510300.SH",
            "a_share_growth",
            "Recovery",
            policy_level=0,
            confidence=0.8,
        )


def _definition() -> ForecastRealizationSourceDefinition:
    return ForecastRealizationSourceDefinition.create(
        source=_source(),
        registered_at=RECORDED_AT,
    )


def test_source_definition_rejects_a_naive_registration_clock() -> None:
    """Registration clocks must carry timezone information at the public factory."""

    with pytest.raises(ValueError, match="timezone-aware"):
        ForecastRealizationSourceDefinition.create(
            source=_source(),
            registered_at=datetime(2026, 7, 25),
        )


def test_source_definition_rejects_invalid_clock_policy_and_hash_values() -> None:
    """A sealed definition cannot cross its source window or relax safety flags."""

    definition = _definition()

    with pytest.raises(ValueError, match="owner or version"):
        replace(definition, definition_version="signal-r7-realization-source-definition.v2")

    with pytest.raises(ValueError, match="clocks"):
        replace(
            definition,
            registered_at=definition.source.available_at - timedelta(seconds=1),
        )

    with pytest.raises(ValueError, match="research-only"):
        replace(definition, must_not_execute=False)

    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(definition, content_hash="d" * 64)

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        replace(definition, content_hash="D" * 64)


def test_source_definition_requires_exact_domain_types_on_recursive_copy() -> None:
    """Source and definition subclasses cannot bypass the exact-type boundary."""

    definition = _definition()

    class SourceSubclass(type(definition.source)):
        pass

    source_subclass = SourceSubclass(**definition.source.__dict__)
    with pytest.raises(TypeError, match="exact Domain type"):
        validated_manifest_source_copy(source_subclass)

    class DefinitionSubclass(ForecastRealizationSourceDefinition):
        pass

    definition_subclass = DefinitionSubclass(**definition.__dict__)
    with pytest.raises(TypeError, match="exact Domain type"):
        definition_subclass.validated_copy()
