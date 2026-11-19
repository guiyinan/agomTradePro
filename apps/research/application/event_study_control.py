"""Preregistration and final-OOS entrypoints, without ORM or infrastructure imports."""

from __future__ import annotations

from apps.research.domain.event_study_control import (
    EventStudyBinding,
    EventStudyBindingRequest,
    EventStudyControlError,
    EventStudyRegistry,
    FinalOOSClaim,
    FinalOOSEvaluator,
)


class EventStudyControl:
    """Keep final OOS callbacks strictly after a committed, exclusive use claim."""

    def __init__(self, registry: EventStudyRegistry) -> None:
        """Inject the existing-registry extension at the composition root."""
        self._registry = registry

    def register_spec(self, document: str, expected_sha256: str, *, actor_user_id: int) -> str:
        """Initialize a frozen specification through an authenticated operator."""
        _actor(actor_user_id)
        return self._registry.register_spec(document, expected_sha256, actor_user_id=actor_user_id)

    def bind(self, request: EventStudyBindingRequest, *, actor_user_id: int) -> EventStudyBinding:
        """Bind the existing draft trial before results or final OOS are available."""
        _actor(actor_user_id)
        if not request.study_key.strip() or not request.trial_id.strip():
            raise EventStudyControlError("BINDING_IDENTITY_REQUIRED")
        return self._registry.bind(request, actor_user_id=actor_user_id)

    def run_final_once(
        self, study_key: str, *, actor_user_id: int, evaluator: FinalOOSEvaluator
    ) -> FinalOOSClaim:
        """Consume OOS durably before evaluation; exceptions never refund use.

        This is an execution control, not data qualification or statistical
        support. The evaluator must still apply all frozen gates to exact
        manifest-bound data; a consumed insufficient-data run is not completion.
        """
        _actor(actor_user_id)
        if not study_key.strip():
            raise EventStudyControlError("BINDING_IDENTITY_REQUIRED")
        claim = self._registry.claim(study_key, actor_user_id=actor_user_id)
        evaluator.evaluate(claim)
        return claim


def _actor(value: int) -> None:
    if type(value) is not int or value < 1:
        raise EventStudyControlError("AUTHENTICATED_ACTOR_REQUIRED")
