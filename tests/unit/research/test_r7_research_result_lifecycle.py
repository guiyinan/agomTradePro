"""Research-only lifecycle contracts for persisted R7 result packets."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from apps.research.application.r7_research_result_lifecycle import (
    ApplyR7ResultLifecycle,
    ApplyR7ResultLifecycleCommand,
    R7ResultLifecycleAuthorizationRef,
    R7ResultLifecycleUnavailable,
)
from apps.research.domain.r7_research_result_lifecycle import (
    R7ResearchResultRef,
    R7ResultLifecycleAction,
    R7ResultLifecycleEvent,
    R7ResultLifecycleStatus,
    R7ResultPromotionAuthorization,
    create_r7_result_lifecycle_event,
    derive_r7_result_lifecycle_state,
)
from apps.research.domain.r7_research_result_persistence import (
    PersistedR7ResearchResult,
)
from tests.unit.research.r7_research_result_factories import (
    RESULT_RECORDED_AT,
    make_result,
)


def _result_ref(result: PersistedR7ResearchResult | None = None) -> R7ResearchResultRef:
    item = result or make_result()
    return R7ResearchResultRef(item.result_id, item.result_version, item.content_hash)


def _authorization(
    *,
    result_ref: R7ResearchResultRef | None = None,
    action: R7ResultLifecycleAction = R7ResultLifecycleAction.PROMOTE,
    sequence: int = 1,
    recorded_at: datetime = RESULT_RECORDED_AT + timedelta(minutes=1),
) -> R7ResultPromotionAuthorization:
    return R7ResultPromotionAuthorization(
        authorization_id=f"r7-result-authorization:{sequence}",
        authorization_version="r7-result-authorization.v1",
        result_ref=result_ref or _result_ref(),
        event_id=f"r7-result-lifecycle-event:{sequence}",
        event_version="r7-result-lifecycle-event.v1",
        action=action,
        expected_sequence=sequence,
        owner="research",
        issued_at=recorded_at - timedelta(minutes=1),
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(days=1),
        reason_codes=("research-owner-reviewed",),
        evidence_ref=f"research://r7-result-review/{sequence}",
    )


def _event(
    authorization: R7ResultPromotionAuthorization,
    *,
    previous_event_hash: str | None,
) -> R7ResultLifecycleEvent:
    return create_r7_result_lifecycle_event(
        authorization=authorization,
        occurred_at=authorization.recorded_at,
        recorded_at=authorization.recorded_at + timedelta(seconds=1),
        previous_event_hash=previous_event_hash,
    )


def test_promotion_and_retirement_are_terminal_research_only_events() -> None:
    promotion = _event(_authorization(), previous_event_hash=None)
    retirement_authorization = _authorization(
        action=R7ResultLifecycleAction.RETIRE,
        sequence=2,
        recorded_at=promotion.recorded_at + timedelta(minutes=1),
    )
    retirement = _event(retirement_authorization, previous_event_hash=promotion.content_hash)

    promoted = derive_r7_result_lifecycle_state((promotion,), evaluated_at=promotion.recorded_at)
    retired = derive_r7_result_lifecycle_state(
        (promotion, retirement), evaluated_at=retirement.recorded_at
    )

    assert promoted.status is R7ResultLifecycleStatus.PROMOTED
    assert retired.status is R7ResultLifecycleStatus.RETIRED
    assert retired.promoted_at == promotion.occurred_at
    assert retired.retired_at == retirement.occurred_at
    assert all(
        (
            item.research_only,
            item.promotes_internal_research_record_only,
            not item.publishes_model_probability,
            not item.produces_decision,
            not item.executes_orders,
            item.must_not_use_for_decision,
            item.must_not_execute,
        )
        == (True, True, True, True, True, True, True)
        for item in (promotion, retirement)
    )

    repromotion = _event(
        _authorization(
            action=R7ResultLifecycleAction.PROMOTE,
            sequence=3,
            recorded_at=retirement.recorded_at + timedelta(minutes=1),
        ),
        previous_event_hash=retirement.content_hash,
    )
    with pytest.raises(ValueError, match="terminal"):
        derive_r7_result_lifecycle_state(
            (promotion, retirement, repromotion),
            evaluated_at=repromotion.recorded_at,
        )


@pytest.mark.parametrize(
    ("events", "match"),
    [
        (
            lambda first, second: (
                R7ResultLifecycleEvent(
                    event_id=second.event_id,
                    event_version=second.event_version,
                    result_ref=second.result_ref,
                    authorization_id=second.authorization_id,
                    authorization_version=second.authorization_version,
                    authorization_hash=second.authorization_hash,
                    action=second.action,
                    sequence=1,
                    occurred_at=second.occurred_at,
                    recorded_at=second.recorded_at,
                    previous_event_hash=None,
                    reason_codes=second.reason_codes,
                ),
            ),
            "root must promote",
        ),
        (
            lambda first, second: (
                first,
                R7ResultLifecycleEvent(
                    event_id=second.event_id,
                    event_version=second.event_version,
                    result_ref=second.result_ref,
                    authorization_id=second.authorization_id,
                    authorization_version=second.authorization_version,
                    authorization_hash=second.authorization_hash,
                    action=second.action,
                    sequence=3,
                    occurred_at=second.occurred_at,
                    recorded_at=second.recorded_at,
                    previous_event_hash=second.previous_event_hash,
                    reason_codes=second.reason_codes,
                ),
            ),
            "sequence",
        ),
        (
            lambda first, second: (
                first,
                R7ResultLifecycleEvent(
                    event_id=second.event_id,
                    event_version=second.event_version,
                    result_ref=second.result_ref,
                    authorization_id=second.authorization_id,
                    authorization_version=second.authorization_version,
                    authorization_hash=second.authorization_hash,
                    action=second.action,
                    sequence=second.sequence,
                    occurred_at=second.occurred_at,
                    recorded_at=second.recorded_at,
                    previous_event_hash="f" * 64,
                    reason_codes=second.reason_codes,
                ),
            ),
            "hash chain",
        ),
    ],
)
def test_replay_rejects_invalid_roots_gaps_and_broken_chains(events: object, match: str) -> None:
    first = _event(_authorization(), previous_event_hash=None)
    second = _event(
        _authorization(
            action=R7ResultLifecycleAction.RETIRE,
            sequence=2,
            recorded_at=first.recorded_at + timedelta(minutes=1),
        ),
        previous_event_hash=first.content_hash,
    )
    built = events(first, second)  # type: ignore[operator]
    with pytest.raises(ValueError, match=match):
        derive_r7_result_lifecycle_state(built, evaluated_at=second.recorded_at)


def test_authorization_rejects_owner_clock_and_safety_relaxation() -> None:
    valid = _authorization()
    values = {
        "authorization_id": valid.authorization_id,
        "authorization_version": valid.authorization_version,
        "result_ref": valid.result_ref,
        "event_id": valid.event_id,
        "event_version": valid.event_version,
        "action": valid.action,
        "expected_sequence": valid.expected_sequence,
        "issued_at": valid.issued_at,
        "recorded_at": valid.recorded_at,
        "valid_until": valid.valid_until,
        "reason_codes": valid.reason_codes,
        "evidence_ref": valid.evidence_ref,
    }
    with pytest.raises(ValueError, match="owner"):
        R7ResultPromotionAuthorization(owner="strategy", **values)
    with pytest.raises(ValueError, match="research-only"):
        R7ResultPromotionAuthorization(owner="research", publishes_model_probability=True, **values)
    with pytest.raises(ValueError, match="clocks"):
        R7ResultPromotionAuthorization(
            owner="research",
            **{**values, "issued_at": valid.recorded_at + timedelta(seconds=1)},
        )


@dataclass
class _Clock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class _AuthorizationProvider:
    unit_of_work_key = "fake:r7"

    def __init__(self) -> None:
        self.authorization: R7ResultPromotionAuthorization | None = None
        self.calls: list[tuple[object, ...]] = []

    def get_exact(
        self,
        *,
        authorization_ref: R7ResultLifecycleAuthorizationRef,
        result_ref: R7ResearchResultRef,
        action: R7ResultLifecycleAction,
        as_of: datetime,
    ) -> R7ResultPromotionAuthorization | None:
        self.calls.append((authorization_ref, result_ref, action, as_of))
        return self.authorization


class _Repository:
    unit_of_work_key = "fake:r7"

    def __init__(self, result: PersistedR7ResearchResult, clock: _Clock) -> None:
        self.result = result
        self.clock = clock
        self.events: list[R7ResultLifecycleEvent] = []
        self.authorizations: dict[tuple[str, str], R7ResultPromotionAuthorization] = {}

    def atomic(self) -> object:
        return nullcontext()

    def server_now(self) -> datetime:
        return self.clock.now()

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedR7ResearchResult | None:
        if (result_id, result_version, expected_content_hash) != (
            self.result.result_id,
            self.result.result_version,
            self.result.content_hash,
        ) or self.result.recorded_at > as_of:
            return None
        return self.result

    def load_lifecycle_stream(
        self, *, result_ref: R7ResearchResultRef
    ) -> tuple[R7ResultLifecycleEvent, ...]:
        return tuple(item for item in self.events if item.result_ref == result_ref)

    def get_event_by_authorization(
        self, *, authorization_ref: R7ResultLifecycleAuthorizationRef
    ) -> R7ResultLifecycleEvent | None:
        return next(
            (
                item
                for item in self.events
                if (item.authorization_id, item.authorization_version)
                == (
                    authorization_ref.authorization_id,
                    authorization_ref.authorization_version,
                )
            ),
            None,
        )

    def append_lifecycle(
        self,
        *,
        authorization: R7ResultPromotionAuthorization,
        event: R7ResultLifecycleEvent,
    ) -> R7ResultLifecycleEvent:
        self.authorizations[
            (authorization.authorization_id, authorization.authorization_version)
        ] = authorization
        self.events.append(event)
        return event


def _command(
    authorization: R7ResultPromotionAuthorization,
) -> ApplyR7ResultLifecycleCommand:
    return ApplyR7ResultLifecycleCommand(
        result_ref=authorization.result_ref,
        action=authorization.action,
        authorization_ref=R7ResultLifecycleAuthorizationRef(
            authorization.authorization_id,
            authorization.authorization_version,
        ),
    )


def test_application_rereads_exact_owner_authorization_and_is_idempotent_after_retire() -> None:
    result = make_result()
    clock = _Clock(RESULT_RECORDED_AT + timedelta(hours=1))
    repository = _Repository(result, clock)
    provider = _AuthorizationProvider()
    use_case = ApplyR7ResultLifecycle(provider, repository)

    promotion = _authorization(recorded_at=clock.value - timedelta(minutes=20))
    provider.authorization = promotion
    promotion_event = use_case.execute(_command(promotion))

    retirement = _authorization(
        action=R7ResultLifecycleAction.RETIRE,
        sequence=2,
        recorded_at=clock.value - timedelta(minutes=10),
    )
    provider.authorization = retirement
    use_case.execute(_command(retirement))

    provider.authorization = promotion
    assert use_case.execute(_command(promotion)) == promotion_event
    assert provider.calls[-1][-1] == clock.value
    assert promotion_event.recorded_at == clock.value


def test_application_fails_closed_on_missing_or_substituted_authorization() -> None:
    result = make_result()
    clock = _Clock(RESULT_RECORDED_AT + timedelta(hours=1))
    repository = _Repository(result, clock)
    provider = _AuthorizationProvider()
    use_case = ApplyR7ResultLifecycle(provider, repository)
    authorization = _authorization(recorded_at=clock.value - timedelta(minutes=1))

    with pytest.raises(R7ResultLifecycleUnavailable, match="authorization"):
        use_case.execute(_command(authorization))

    provider.authorization = _authorization(
        result_ref=R7ResearchResultRef(result.result_id, result.result_version, "f" * 64),
        recorded_at=clock.value - timedelta(minutes=1),
    )
    with pytest.raises(R7ResultLifecycleUnavailable, match="substitution"):
        use_case.execute(_command(authorization))


def test_application_module_does_not_publish_current_or_active_reader() -> None:
    from apps.research.application import r7_research_result_lifecycle as module

    assert not any("Current" in name or "Active" in name for name in module.__all__)
