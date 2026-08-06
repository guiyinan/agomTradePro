"""Domain coverage for the Research R1 promotion lifecycle hash chain."""

from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import timedelta

import pytest

from apps.equity.domain.forecast_baseline import ForecastBaselineTrialResult, ForecastScenario
from apps.research.domain.r1_forecast_promotion import (
    R1ForecastPromotionDecision,
    R1PromotionDecisionOutcome,
    R1PromotionLifecycleAuthorization,
    R1PromotionLifecycleEventType,
    R1PromotionLifecycleState,
    create_r1_forecast_promotion_decision,
    create_r1_promotion_lifecycle_event,
    create_r1_promotion_lifecycle_root,
    derive_r1_promotion_lifecycle_state,
)
from apps.research.domain.r1_forecast_promotion_lifecycle import _build_event
from tests.unit.research.test_r1_forecast_promotion import (
    _artifact,
    _eligible_result,
    _ineligible_result,
    _paired_rows,
    _policy,
    _result,
    _spec,
)


def _decision(
    suffix: str,
    *,
    hour: int,
    result: ForecastBaselineTrialResult | None = None,
) -> R1ForecastPromotionDecision:
    trial_result = result or _eligible_result()
    return create_r1_forecast_promotion_decision(
        decision_id=f"research-r1-promotion:{suffix}",
        decision_version="decision.v1",
        policy=_policy(result=trial_result),
        result=trial_result,
        as_of=trial_result.evaluated_at + timedelta(hours=hour),
        recorded_at=trial_result.evaluated_at + timedelta(hours=hour, minutes=1),
    )


def _result_for_scenario(scenario: ForecastScenario) -> ForecastBaselineTrialResult:
    base_spec = _spec()
    spec_values = {
        name: getattr(base_spec, name)
        for name in inspect.signature(type(base_spec).create).parameters
    }
    spec_values.update(
        spec_id=f"r1-baseline-spec:consumer:{scenario.value}",
        candidate_scenario=scenario,
    )
    spec = type(base_spec).create(**spec_values)
    base_artifact = _artifact(base_spec)
    forecasts = tuple(
        replace(
            item,
            forecast_id=f"{item.forecast_id}:{scenario.value}",
            forecast_content_hash=("b" if index == 0 else "c") * 64,
            candidate_scenario=scenario,
        )
        for index, item in enumerate(base_artifact.forecasts)
    )
    artifact = type(base_artifact).create(
        artifact_id=f"r1-baseline-artifact:consumer:{scenario.value}",
        artifact_version=base_artifact.artifact_version,
        owner=base_artifact.owner,
        spec=spec,
        forecasts=forecasts,
        predictions=base_artifact.predictions,
        knowledge_as_of=base_artifact.knowledge_as_of,
        produced_at=base_artifact.produced_at,
        valid_until=base_artifact.valid_until,
    )
    forecasts_by_period = {item.target_period_end: item for item in forecasts}
    rows = tuple(
        replace(
            item,
            forecast_id=forecasts_by_period[item.period_end].forecast_id,
            forecast_content_hash=(forecasts_by_period[item.period_end].forecast_content_hash),
        )
        for item in _paired_rows()
    )
    return _result(spec, artifact, rows)


def _authorization(
    decision: R1ForecastPromotionDecision,
    *,
    event_type: R1PromotionLifecycleEventType,
    occurred_at,
    reason_codes: tuple[str, ...],
    rollback_target: R1ForecastPromotionDecision | None = None,
    owner: str = "research",
) -> R1PromotionLifecycleAuthorization:
    return R1PromotionLifecycleAuthorization.create(
        authorization_id=f"authorization:{event_type.value}:{decision.decision_id}",
        authorization_version="authorization.v1",
        owner=owner,
        capability="r1",
        purpose="valuation",
        event_type=event_type,
        decision=decision,
        rollback_target=rollback_target,
        reason_codes=reason_codes,
        issued_at=occurred_at - timedelta(minutes=2),
        recorded_at=occurred_at - timedelta(minutes=1),
        valid_until=occurred_at + timedelta(hours=1),
    )


def _root(decision: R1ForecastPromotionDecision):
    occurred_at = decision.recorded_at + timedelta(minutes=10)
    reasons = ("research_promotion_approved",)
    return create_r1_promotion_lifecycle_root(
        event_id=f"r1-promotion-event:root:{decision.decision_id}",
        event_version="event.v1",
        decision=decision,
        authorization=_authorization(
            decision,
            event_type=R1PromotionLifecycleEventType.PROMOTED,
            occurred_at=occurred_at,
            reason_codes=reasons,
        ),
        reason_codes=reasons,
        occurred_at=occurred_at,
        recorded_at=occurred_at + timedelta(minutes=1),
    )


def _promote_after(previous_events, decision: R1ForecastPromotionDecision):
    occurred_at = max(previous_events[-1].recorded_at, decision.recorded_at) + timedelta(minutes=10)
    reasons = ("replacement_promotion_approved",)
    return create_r1_promotion_lifecycle_event(
        event_id=f"r1-promotion-event:{decision.decision_id}",
        event_version="event.v1",
        previous_events=previous_events,
        event_type=R1PromotionLifecycleEventType.PROMOTED,
        decision=decision,
        rollback_target=None,
        authorization=_authorization(
            decision,
            event_type=R1PromotionLifecycleEventType.PROMOTED,
            occurred_at=occurred_at,
            reason_codes=reasons,
        ),
        reason_codes=reasons,
        occurred_at=occurred_at,
        recorded_at=occurred_at + timedelta(minutes=1),
    )


def test_promote_and_exact_rollback_restore_previous_decision() -> None:
    first = _decision("first", hour=1)
    second = _decision("second", hour=2)
    root = _root(first)
    promoted = _promote_after((root,), second)
    occurred_at = promoted.recorded_at + timedelta(minutes=10)
    reasons = ("replacement_failed_validation",)
    rolled_back = create_r1_promotion_lifecycle_event(
        event_id="r1-promotion-event:rollback-second",
        event_version="event.v1",
        previous_events=(root, promoted),
        event_type=R1PromotionLifecycleEventType.ROLLED_BACK,
        decision=second,
        rollback_target=first,
        authorization=_authorization(
            second,
            event_type=R1PromotionLifecycleEventType.ROLLED_BACK,
            occurred_at=occurred_at,
            reason_codes=reasons,
            rollback_target=first,
        ),
        reason_codes=reasons,
        occurred_at=occurred_at,
        recorded_at=occurred_at + timedelta(minutes=1),
    )

    snapshot = derive_r1_promotion_lifecycle_state(
        (root, promoted, rolled_back),
        evaluated_at=rolled_back.recorded_at,
    )
    assert snapshot.state is R1PromotionLifecycleState.ROLLED_BACK
    assert snapshot.active_decision is not None
    assert snapshot.active_decision.content_hash == first.content_hash
    assert rolled_back.previous_event_hash == promoted.content_hash


def test_rollback_target_must_be_exact_previous_promoted_decision() -> None:
    first = _decision("first", hour=1)
    second = _decision("second", hour=2)
    unrelated = _decision("unrelated", hour=3)
    root = _root(first)
    promoted = _promote_after((root,), second)
    occurred_at = promoted.recorded_at + timedelta(minutes=10)
    reasons = ("rollback_requested",)
    authorization = _authorization(
        second,
        event_type=R1PromotionLifecycleEventType.ROLLED_BACK,
        occurred_at=occurred_at,
        reason_codes=reasons,
        rollback_target=unrelated,
    )

    with pytest.raises(ValueError, match="exact previous promoted decision"):
        create_r1_promotion_lifecycle_event(
            event_id="r1-promotion-event:invalid-rollback",
            event_version="event.v1",
            previous_events=(root, promoted),
            event_type=R1PromotionLifecycleEventType.ROLLED_BACK,
            decision=second,
            rollback_target=unrelated,
            authorization=authorization,
            reason_codes=reasons,
            occurred_at=occurred_at,
            recorded_at=occurred_at + timedelta(minutes=1),
        )


def test_retired_and_expired_decisions_are_inactive() -> None:
    decision = _decision("retire", hour=1)
    root = _root(decision)
    occurred_at = root.recorded_at + timedelta(minutes=10)
    reasons = ("research_owner_retired",)
    retired = create_r1_promotion_lifecycle_event(
        event_id="r1-promotion-event:retire",
        event_version="event.v1",
        previous_events=(root,),
        event_type=R1PromotionLifecycleEventType.RETIRED,
        decision=decision,
        rollback_target=None,
        authorization=_authorization(
            decision,
            event_type=R1PromotionLifecycleEventType.RETIRED,
            occurred_at=occurred_at,
            reason_codes=reasons,
        ),
        reason_codes=reasons,
        occurred_at=occurred_at,
        recorded_at=occurred_at + timedelta(minutes=1),
    )
    retired_snapshot = derive_r1_promotion_lifecycle_state(
        (root, retired),
        evaluated_at=retired.recorded_at,
    )
    assert retired_snapshot.state is R1PromotionLifecycleState.RETIRED
    assert retired_snapshot.active_decision is None

    expired_snapshot = derive_r1_promotion_lifecycle_state(
        (root,),
        evaluated_at=decision.valid_until,
    )
    assert expired_snapshot.state is R1PromotionLifecycleState.EXPIRED
    assert expired_snapshot.active_decision is None


def test_rejected_decision_cannot_enter_lifecycle() -> None:
    result = _ineligible_result()
    rejected = create_r1_forecast_promotion_decision(
        decision_id="research-r1-promotion:rejected-lifecycle",
        decision_version="decision.v1",
        policy=_policy(result=result),
        result=result,
        as_of=result.evaluated_at + timedelta(hours=1),
        recorded_at=result.evaluated_at + timedelta(hours=1, minutes=1),
    )
    occurred_at = rejected.recorded_at + timedelta(minutes=10)
    reasons = ("research_promotion_approved",)
    authorization = _authorization(
        rejected,
        event_type=R1PromotionLifecycleEventType.PROMOTED,
        occurred_at=occurred_at,
        reason_codes=reasons,
    )

    assert rejected.outcome is R1PromotionDecisionOutcome.REJECTED
    with pytest.raises(ValueError, match="only reference approved"):
        create_r1_promotion_lifecycle_root(
            event_id="r1-promotion-event:rejected-root",
            event_version="event.v1",
            decision=rejected,
            authorization=authorization,
            reason_codes=reasons,
            occurred_at=occurred_at,
            recorded_at=occurred_at + timedelta(minutes=1),
        )


def test_owner_authorization_and_dual_clocks_fail_closed() -> None:
    decision = _decision("clock", hour=1)
    occurred_at = decision.recorded_at + timedelta(minutes=10)
    reasons = ("research_promotion_approved",)
    with pytest.raises(ValueError, match="authority is invalid"):
        _authorization(
            decision,
            event_type=R1PromotionLifecycleEventType.PROMOTED,
            occurred_at=occurred_at,
            reason_codes=reasons,
            owner="equity",
        )
    authorization = _authorization(
        decision,
        event_type=R1PromotionLifecycleEventType.PROMOTED,
        occurred_at=occurred_at,
        reason_codes=reasons,
    )
    with pytest.raises(ValueError, match="record cannot predate"):
        create_r1_promotion_lifecycle_root(
            event_id="r1-promotion-event:bad-clock",
            event_version="event.v1",
            decision=decision,
            authorization=authorization,
            reason_codes=reasons,
            occurred_at=occurred_at,
            recorded_at=occurred_at - timedelta(seconds=1),
        )

    root = _root(decision)
    second = _decision("clock-second", hour=2)
    new_occurred = second.recorded_at + timedelta(minutes=10)
    new_reasons = ("replacement_promotion_approved",)
    with pytest.raises(ValueError, match="dual clocks cannot move backwards"):
        create_r1_promotion_lifecycle_event(
            event_id="r1-promotion-event:record-regression",
            event_version="event.v1",
            previous_events=(root,),
            event_type=R1PromotionLifecycleEventType.PROMOTED,
            decision=second,
            rollback_target=None,
            authorization=_authorization(
                second,
                event_type=R1PromotionLifecycleEventType.PROMOTED,
                occurred_at=new_occurred,
                reason_codes=new_reasons,
            ),
            reason_codes=new_reasons,
            occurred_at=new_occurred,
            recorded_at=root.recorded_at - timedelta(seconds=1),
        )


def test_hash_chain_root_and_future_receipt_tampering_are_rejected() -> None:
    first = _decision("hash-first", hour=1)
    second = _decision("hash-second", hour=2)
    root = _root(first)
    promoted = _promote_after((root,), second)

    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(root, event_id="r1-promotion-event:tampered-root")
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(promoted, previous_event_hash="0" * 64)
    with pytest.raises(ValueError, match="future-unrecorded"):
        derive_r1_promotion_lifecycle_state(
            (root, promoted),
            evaluated_at=promoted.recorded_at - timedelta(seconds=1),
        )


def test_distinct_promotion_scopes_have_independent_active_streams() -> None:
    base = _decision("base-scope", hour=1)
    bear = _decision(
        "bear-scope",
        hour=1,
        result=_result_for_scenario(ForecastScenario.BEAR),
    )
    base_root = _root(base)
    bear_root = _root(bear)

    base_snapshot = derive_r1_promotion_lifecycle_state(
        (base_root,),
        evaluated_at=base_root.recorded_at,
    )
    bear_snapshot = derive_r1_promotion_lifecycle_state(
        (bear_root,),
        evaluated_at=bear_root.recorded_at,
    )

    assert base.promotion_scope != bear.promotion_scope
    assert base_snapshot.stream_id != bear_snapshot.stream_id
    assert base_snapshot.state is R1PromotionLifecycleState.PROMOTED
    assert bear_snapshot.state is R1PromotionLifecycleState.PROMOTED
    assert base_snapshot.active_decision is not None
    assert bear_snapshot.active_decision is not None
    assert base_snapshot.active_decision.content_hash == base.content_hash
    assert bear_snapshot.active_decision.content_hash == bear.content_hash


def test_mixed_scope_append_replay_and_rollback_fail_closed() -> None:
    base = _decision("mixed-base", hour=1)
    bear = _decision(
        "mixed-bear",
        hour=1,
        result=_result_for_scenario(ForecastScenario.BEAR),
    )
    base_root = _root(base)
    bear_root = _root(bear)

    with pytest.raises(ValueError, match="crosses promotion scopes"):
        derive_r1_promotion_lifecycle_state(
            (base_root, bear_root),
            evaluated_at=max(base_root.recorded_at, bear_root.recorded_at),
        )
    with pytest.raises(ValueError, match="append across promotion scopes"):
        _promote_after((base_root,), bear)

    occurred_at = base_root.recorded_at + timedelta(minutes=10)
    with pytest.raises(ValueError, match="cannot cross promotion scopes"):
        _authorization(
            base,
            event_type=R1PromotionLifecycleEventType.ROLLED_BACK,
            occurred_at=occurred_at,
            reason_codes=("cross_scope_rollback_requested",),
            rollback_target=bear,
        )


def test_promotion_policy_cannot_be_substituted_across_scopes() -> None:
    base_spec = _spec()
    base_result = _result(base_spec, _artifact(base_spec), _paired_rows())
    bear_result = _result_for_scenario(ForecastScenario.BEAR)

    with pytest.raises(ValueError, match="policy does not govern the trial scope"):
        create_r1_forecast_promotion_decision(
            decision_id="research-r1-promotion:cross-scope-policy",
            decision_version="decision.v1",
            policy=_policy(result=base_result),
            result=bear_result,
            as_of=bear_result.evaluated_at + timedelta(hours=1),
            recorded_at=bear_result.evaluated_at + timedelta(hours=1, minutes=1),
        )


def test_next_occurrence_cannot_predate_previous_event_receipt() -> None:
    first = _decision("causal-first", hour=1)
    second = _decision("causal-second", hour=1)
    root = _root(first)
    occurred_at = root.occurred_at + timedelta(seconds=30)
    reasons = ("replacement_promotion_approved",)
    authorization = _authorization(
        second,
        event_type=R1PromotionLifecycleEventType.PROMOTED,
        occurred_at=occurred_at,
        reason_codes=reasons,
    )

    with pytest.raises(ValueError, match="dual clocks cannot move backwards"):
        create_r1_promotion_lifecycle_event(
            event_id="r1-promotion-event:backdated-next",
            event_version="event.v1",
            previous_events=(root,),
            event_type=R1PromotionLifecycleEventType.PROMOTED,
            decision=second,
            rollback_target=None,
            authorization=authorization,
            reason_codes=reasons,
            occurred_at=occurred_at,
            recorded_at=root.recorded_at + timedelta(seconds=1),
        )

    raw_backdated = _build_event(
        event_id="r1-promotion-event:raw-backdated-next",
        event_version="event.v1",
        event_type=R1PromotionLifecycleEventType.PROMOTED,
        sequence=2,
        decision=second,
        rollback_target=None,
        authorization=authorization,
        reason_codes=reasons,
        occurred_at=occurred_at,
        recorded_at=root.recorded_at + timedelta(seconds=1),
        previous_event_hash=root.content_hash,
    )
    with pytest.raises(ValueError, match="occurrence predates previous receipt"):
        derive_r1_promotion_lifecycle_state(
            (root, raw_backdated),
            evaluated_at=raw_backdated.recorded_at,
        )
