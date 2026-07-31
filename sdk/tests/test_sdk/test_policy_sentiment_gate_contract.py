"""SDK parsing regression for the policy sentiment-gate API contract."""

from types import SimpleNamespace

from agomtradepro.modules.policy import PolicyModule


def test_parser_reads_canonical_api_field_names() -> None:
    """The SDK must not silently replace real API scores with zeroes."""

    module = PolicyModule(SimpleNamespace())

    state = module._parse_sentiment_gate_state(
        {
            "gate_level": "L2",
            "heat_score": 70.5,
            "sentiment_score": -0.25,
            "max_position_cap": 0.7,
            "signal_paused": False,
            "data_sufficient": True,
            "must_not_use_for_decision": False,
            "blocked_reason": "",
        }
    )

    assert state.global_heat == 70.5
    assert state.global_sentiment == -0.25
    assert state.data_sufficient is True
    assert state.must_not_use_for_decision is False


def test_parser_preserves_missing_gate_observations() -> None:
    """Missing readings remain null and decision-blocked instead of becoming neutral zeroes."""

    module = PolicyModule(SimpleNamespace())

    state = module._parse_sentiment_gate_state(
        {
            "gate_level": "L0",
            "heat_score": None,
            "sentiment_score": None,
            "signal_paused": True,
            "data_sufficient": False,
            "must_not_use_for_decision": True,
            "blocked_reason": "policy_sentiment_gate_observation_missing",
        }
    )

    assert state.global_heat is None
    assert state.global_sentiment is None
    assert state.signal_paused is True
    assert state.must_not_use_for_decision is True
