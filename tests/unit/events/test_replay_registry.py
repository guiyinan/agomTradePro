"""Explicit controlled-replay target registry contracts."""

import pytest

from apps.events.application.replay_registry import ReplayTargetRegistry
from apps.events.domain.entities import EventType
from core.integration.event_replay import build_replay_target_registry

EXPECTED_TARGETS = {
    "events.decision.approved",
    "events.decision.rejected",
    "events.decision.executed",
    "events.decision.execution_failed",
    "decision_rhythm.main",
    "decision_rhythm.quota",
    "decision_rhythm.cooldown",
    "alpha_trigger.main",
    "alpha_trigger.invalidation",
    "alpha_trigger.promotion",
}


def test_replay_registry_contains_only_approved_stable_targets() -> None:
    registry = build_replay_target_registry()

    assert set(registry.keys()) == EXPECTED_TARGETS
    for target in registry.list_targets():
        assert target.supported_event_types
        assert target.side_effect_description.strip()
        assert callable(target.factory)


def test_replay_registry_rejects_unknown_and_type_mismatch() -> None:
    registry = build_replay_target_registry()

    with pytest.raises(KeyError, match="Unknown replay target"):
        registry.resolve("apps.module.ArbitraryHandler")
    with pytest.raises(ValueError, match="does not support"):
        registry.resolve_for_event(
            "events.decision.approved",
            EventType.SYSTEM_ERROR,
        )


def test_replay_registry_cannot_be_built_from_request_callables() -> None:
    with pytest.raises(ValueError, match="Replay target key"):
        ReplayTargetRegistry([]).resolve("")
