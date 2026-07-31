"""Decision-safety contracts for policy sentiment gate state."""

from types import SimpleNamespace

from apps.policy.application.workbench_use_cases import (
    GetSentimentGateStateUseCase,
    SentimentGateStateInput,
)


def _gate_config() -> SimpleNamespace:
    return SimpleNamespace(
        heat_l1_threshold=30.0,
        heat_l2_threshold=60.0,
        heat_l3_threshold=85.0,
        sentiment_l1_threshold=-0.3,
        sentiment_l2_threshold=-0.6,
        sentiment_l3_threshold=-0.8,
        max_position_cap_l2=0.7,
        max_position_cap_l3=0.3,
    )


def test_gate_state_fails_closed_when_observations_are_missing() -> None:
    """A configured gate with no observations is valid diagnostics, not an L0 buy signal."""

    repository = SimpleNamespace(
        get_gate_config=lambda _asset_class: _gate_config(),
        get_global_heat_sentiment=lambda: (None, None),
    )

    result = GetSentimentGateStateUseCase(repository).execute(
        SentimentGateStateInput(asset_class="all")
    )

    assert result.success is True
    assert result.gate_level == "L0"
    assert result.data_sufficient is False
    assert result.must_not_use_for_decision is True
    assert result.signal_paused is True
    assert result.blocked_reason == "policy_sentiment_gate_observation_missing"


def test_gate_state_publishes_decision_safe_fields_when_observed() -> None:
    """Observed inputs clear the decision block and preserve the calculated gate."""

    repository = SimpleNamespace(
        get_gate_config=lambda _asset_class: _gate_config(),
        get_global_heat_sentiment=lambda: (70.0, -0.2),
    )

    result = GetSentimentGateStateUseCase(repository).execute(
        SentimentGateStateInput(asset_class="all")
    )

    assert result.gate_level == "L2"
    assert result.data_sufficient is True
    assert result.must_not_use_for_decision is False
    assert result.signal_paused is False
    assert result.blocked_reason == ""
