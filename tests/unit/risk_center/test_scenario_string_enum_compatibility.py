"""Compatibility contract for the original string-valued Scenario enums."""

from __future__ import annotations

from enum import Enum
from typing import cast

from apps.risk_center.domain.portfolio_exit_pressure import ExitPressureStatus
from apps.risk_center.domain.scenario_serialization import (
    canonical_scenario_snapshot_json,
    stable_content_hash,
)
from apps.risk_center.domain.scenarios import (
    ProbabilitySource,
    RollingDirection,
    RollingMetric,
    ScenarioDefinitionStatus,
    ScenarioRevisionStatus,
    ScenarioSourceType,
    ScenarioType,
    ShockUnit,
)

_LEGACY_STRING_ENUM_MEMBERS: tuple[Enum, ...] = (
    ScenarioType.HISTORICAL_WINDOW,
    ScenarioRevisionStatus.APPROVED,
    ScenarioDefinitionStatus.ACTIVE,
    ScenarioSourceType.HUMAN,
    RollingMetric.CUMULATIVE_RETURN,
    RollingDirection.MINIMUM,
    ShockUnit.PERCENT,
    ProbabilitySource.SUBJECTIVE,
)


def test_scenario_enums_keep_legacy_string_and_evidence_semantics() -> None:
    """Retain the former ``str, Enum`` display, formatting, and hash contract."""

    for member in _LEGACY_STRING_ENUM_MEMBERS:
        member_text = cast(str, member)
        assert str(member) == Enum.__str__(member)
        for format_spec in ("", ">32", "^24"):
            assert format(member, format_spec) == str.__format__(member_text, format_spec)
        assert hash(member) == hash(member_text)
        assert canonical_scenario_snapshot_json({"enum": member}) == (
            canonical_scenario_snapshot_json({"enum": member_text})
        )
        assert stable_content_hash({"enum": member}) == stable_content_hash({"enum": member_text})


def test_new_exit_pressure_status_uses_value_display() -> None:
    """The newly introduced status follows StrEnum's intended value display."""

    assert str(ExitPressureStatus.LIMITED) == "limited"
    assert format(ExitPressureStatus.LIMITED) == "limited"
