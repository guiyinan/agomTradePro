"""Focused boundary tests for compact Domain modules."""

import pytest

from apps.config_center.domain.entities import AlphaUniverseConfig
from apps.operational_readiness.domain.evidence_contract import (
    classify_evidence_payload,
    classify_operation_context,
    decision_quote_freshness_status,
    get_decision_data,
    get_workspace_components,
    workspace_core_status,
)
from apps.pulse.domain.entities import DimensionScore, PulseConfig
from apps.pulse.domain.rules import classify_pulse_strength, should_warn_transition
from apps.research.domain.statistics import (
    benjamini_hochberg_q_values,
    deflated_sharpe_ratio,
)


@pytest.mark.parametrize(
    ("universe_id", "name", "source_type", "message"),
    [
        ("", "Core", "manual", "universe_id"),
        ("core", "", "manual", "name"),
        ("core", "Core", "remote", "source_type"),
    ],
)
def test_alpha_universe_rejects_incomplete_or_unsupported_definitions(
    universe_id: str,
    name: str,
    source_type: str,
    message: str,
) -> None:
    """Config-center refuses identities it cannot reproduce."""
    with pytest.raises(ValueError, match=message):
        AlphaUniverseConfig(
            universe_id=universe_id,
            name=name,
            source_type=source_type,
        )


def test_alpha_universe_publishes_an_isolated_json_contract() -> None:
    """Mutable boundary data is copied out of the frozen value object."""
    universe = AlphaUniverseConfig(
        universe_id="core",
        name="Core",
        source_type="data_center_filter",
        stock_codes=("000001.SZ",),
        filters={"market": "CN"},
        description="eligible universe",
    )
    payload = universe.to_dict()
    payload["filters"]["market"] = "US"

    assert universe.filters == {"market": "CN"}
    assert payload["stock_codes"] == ["000001.SZ"]


def test_readiness_operation_context_distinguishes_legacy_and_formal_evidence() -> None:
    """Only a closed-date formal run is an acceptance candidate."""
    legacy = classify_operation_context({})
    assert legacy["formal_evidence"] is None
    assert legacy["acceptance_candidate"] is True

    formal = classify_evidence_payload(
        {
            "operation_context": {
                "mode": "formal",
                "target_date_closed": True,
                "allow_unclosed_target_date": False,
                "trigger_source": "celery",
                "trigger_task_id": 123,
            }
        }
    )
    assert formal["formal_evidence"] is True
    assert formal["trigger_task_id"] == "123"

    unsafe = classify_operation_context(
        {
            "mode": "formal",
            "target_date_closed": False,
            "allow_unclosed_target_date": True,
        }
    )
    assert unsafe["acceptance_candidate"] is False


def test_readiness_nested_sections_are_type_safe() -> None:
    """Malformed external payloads normalize to empty mappings."""
    assert get_decision_data({"system": {"checks": {"decision_data": []}}}) == {}
    assert get_workspace_components({"workspace": {"result": {"components": []}}}) == {}
    assert get_decision_data({"system": {"checks": {"decision_data": {"quotes": {}}}}}) == {
        "quotes": {}
    }
    assert get_workspace_components(
        {"workspace": {"result": {"components": {"regime_snapshot": {}}}}}
    ) == {"regime_snapshot": {}}


@pytest.mark.parametrize(
    ("components", "expected"),
    [
        ({}, "missing"),
        (
            {
                "regime_snapshot": {"status": "failed"},
                "pulse_snapshot": {"status": "success", "is_reliable": True},
                "action_recommendation": {"status": "success"},
            },
            "regime_not_success",
        ),
        (
            {
                "regime_snapshot": {"status": "success"},
                "pulse_snapshot": {"status": "failed", "is_reliable": True},
                "action_recommendation": {"status": "success"},
            },
            "pulse_not_success",
        ),
        (
            {
                "regime_snapshot": {"status": "success"},
                "pulse_snapshot": {"status": "success", "is_reliable": False},
                "action_recommendation": {"status": "success"},
            },
            "pulse_not_reliable",
        ),
        (
            {
                "regime_snapshot": {"status": "success"},
                "pulse_snapshot": {"status": "success", "is_reliable": True},
                "action_recommendation": {"status": "failed"},
            },
            "action_not_success",
        ),
        (
            {
                "regime_snapshot": {"status": "success"},
                "pulse_snapshot": {"status": "success", "is_reliable": True},
                "action_recommendation": {"status": "success"},
            },
            "ok",
        ),
    ],
)
def test_workspace_core_status_fails_closed_by_component(
    components: dict[str, object], expected: str
) -> None:
    """Each required decision component has an explicit rejection reason."""
    assert workspace_core_status(components) == expected


@pytest.mark.parametrize(
    ("quotes", "expected"),
    [
        (None, "missing"),
        ({}, "missing"),
        ({"000001.SZ": []}, "blocked"),
        ({"000001.SZ": {"must_not_use_for_decision": True}}, "blocked"),
        ({"000001.SZ": {"status": "failed"}}, "blocked"),
        (
            {
                "000001.SZ": {
                    "status": "ok",
                    "is_stale": True,
                    "freshness_status": "fresh",
                }
            },
            "stale",
        ),
        (
            {
                "000001.SZ": {
                    "status": "ok",
                    "is_stale": False,
                    "freshness_status": "unknown",
                }
            },
            "stale",
        ),
        (
            {
                "000001.SZ": {
                    "status": "ok",
                    "is_stale": False,
                    "freshness_status": "latest_completed_session",
                }
            },
            "ok",
        ),
    ],
)
def test_decision_quote_freshness_has_explicit_blocking_semantics(
    quotes: object, expected: str
) -> None:
    """Missing, malformed, blocked, and stale quotes remain distinguishable."""
    assert decision_quote_freshness_status({"quotes": quotes}) == expected


def _dimension(dimension: str, score: float) -> DimensionScore:
    """Build a Pulse dimension value."""
    return DimensionScore(
        dimension=dimension,
        score=score,
        signal="neutral",
        indicator_count=1,
        description=dimension,
    )


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0.31, "strong"), (0.3, "moderate"), (-0.3, "weak")],
)
def test_pulse_strength_exact_thresholds(score: float, expected: str) -> None:
    """Strength buckets preserve strict boundary semantics."""
    assert classify_pulse_strength(score) == expected


@pytest.mark.parametrize(
    ("regime", "scores", "direction"),
    [
        ("Recovery", [("growth", -0.4), ("liquidity", -0.4)], "Deflation"),
        ("Recovery", [("inflation", 0.4)], "Overheat"),
        ("Overheat", [("growth", -0.4)], "Stagflation"),
        ("Overheat", [("inflation", -0.4)], "Recovery"),
        (
            "Stagflation",
            [("inflation", -0.4), ("growth", -0.4)],
            "Deflation",
        ),
        (
            "Stagflation",
            [("inflation", -0.4), ("growth", 0.0)],
            "Recovery",
        ),
        (
            "Deflation",
            [("growth", 0.4), ("liquidity", 0.4)],
            "Recovery",
        ),
    ],
)
def test_pulse_transition_rules_cover_each_regime(
    regime: str,
    scores: list[tuple[str, float]],
    direction: str,
) -> None:
    """Each macro regime publishes its intended transition signal."""
    warning, actual_direction, reasons = should_warn_transition(
        [_dimension(name, score) for name, score in scores],
        regime,
        PulseConfig.defaults(),
    )
    assert warning is True
    assert actual_direction == direction
    assert reasons


def test_pulse_transition_rules_do_not_warn_without_joint_evidence() -> None:
    """A neutral snapshot cannot invent a transition."""
    assert should_warn_transition([_dimension("growth", 0.0)], "Recovery") == (
        False,
        None,
        [],
    )


def test_research_statistics_validate_empty_and_invalid_families() -> None:
    """Multiple-testing and DSR helpers fail explicitly at invalid boundaries."""
    assert benjamini_hochberg_q_values([]) == []
    with pytest.raises(ValueError, match="p-values"):
        benjamini_hochberg_q_values([1.01])
    with pytest.raises(ValueError, match="sample_count"):
        deflated_sharpe_ratio(1.0, sample_count=1, trial_count=1)

    probability = deflated_sharpe_ratio(
        0.8,
        sample_count=252,
        trial_count=10,
        skewness=-0.2,
        excess_kurtosis=1.0,
    )
    assert 0.0 <= probability <= 1.0
