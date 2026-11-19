"""Final OOS invocation order and failure semantics independent of a database."""

from datetime import UTC, datetime

import pytest

from apps.research.application.event_study_control import EventStudyControl
from apps.research.domain.event_study_control import (
    EventStudyBinding,
    EventStudyBindingRequest,
    EventStudyControlError,
    FinalOOSClaim,
)

BINDING = EventStudyBinding(
    "study", "trial", "experiment", "family", "a" * 64, "pit", "b" * 64, "c" * 64
)


class Registry:
    def __init__(self) -> None:
        self.used = False

    def register_spec(self, document: str, expected_sha256: str, *, actor_user_id: int) -> str:
        return expected_sha256

    def bind(self, request: EventStudyBindingRequest, *, actor_user_id: int) -> EventStudyBinding:
        return BINDING

    def claim(self, study_key: str, *, actor_user_id: int) -> FinalOOSClaim:
        if self.used:
            raise EventStudyControlError("FINAL_OOS_ALREADY_USED")
        self.used = True
        return FinalOOSClaim(1, BINDING, datetime(2026, 11, 19, tzinfo=UTC), actor_user_id, 2)


def test_failure_consumes_use_and_never_reinvokes_evaluator() -> None:
    registry = Registry()
    control = EventStudyControl(registry)

    class Evaluator:
        calls = 0

        def evaluate(self, claim: FinalOOSClaim) -> None:
            assert registry.used
            self.calls += 1
            raise ArithmeticError("evaluation failed after committed claim")

    evaluator = Evaluator()
    with pytest.raises(ArithmeticError):
        control.run_final_once("study", actor_user_id=1, evaluator=evaluator)
    with pytest.raises(EventStudyControlError, match="FINAL_OOS_ALREADY_USED"):
        control.run_final_once("study", actor_user_id=1, evaluator=evaluator)
    assert evaluator.calls == 1


@pytest.mark.parametrize("actor", [0, -1, False])
def test_invalid_actor_never_claims_or_invokes(actor: int) -> None:
    registry = Registry()

    class Evaluator:
        def evaluate(self, claim: FinalOOSClaim) -> None:
            pytest.fail("invalid actor reached evaluator")

    with pytest.raises(EventStudyControlError, match="AUTHENTICATED_ACTOR_REQUIRED"):
        EventStudyControl(registry).run_final_once(
            "study", actor_user_id=actor, evaluator=Evaluator()
        )
    assert not registry.used
