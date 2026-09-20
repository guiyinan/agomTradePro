"""DATA-17 branch evidence for public R7 research Domain boundaries."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from apps.research.application.r7_research_result_persistence import (
    materialize_persisted_r7_research_result,
)
from apps.research.domain import r7_result_family_lifecycle as family_contracts
from apps.research.domain.r7_path_owner import ScenarioPathRawSource
from apps.research.domain.r7_post_promotion_monitoring import (
    R7ForecastRealizationMember,
    calculate_r7_brier_score,
    calculate_r7_forecast_outcome_coverage,
)
from apps.research.domain.r7_post_promotion_monitoring_contracts import (
    R7MonitoringActiveResult,
    R7MonitoringPredictionMember,
)
from apps.research.domain.r7_research_result_lifecycle import (
    R7ResearchResultRef,
    R7ResultLifecycleAction,
    R7ResultLifecycleEvent,
    R7ResultPromotionAuthorization,
    create_r7_result_lifecycle_event,
    derive_r7_result_lifecycle_state,
)
from apps.research.domain.r7_research_result_persistence import (
    PersistedR7ResearchResult,
    R7ResearchEvidenceGraph,
    R7ResearchInputReceipt,
)
from apps.research.domain.r7_result_family_lifecycle import (
    R7FamilyLifecycleAction,
    R7FamilyLifecycleAuthorization,
    R7FamilyLifecycleEvent,
    R7FamilyResultOwnerEvidence,
    R7LocalLifecycleStreamAttestation,
    R7ResultFamilyIdentity,
    create_r7_family_lifecycle_event,
    derive_r7_family_lifecycle_state,
)
from apps.research.domain.r7_sample_policy import PersistedR7SamplePolicy
from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
)
from apps.research.domain.scenario_research_evidence import (
    PointInTimeManifestFeature,
    PointInTimeManifestReference,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioProbabilitySource
from tests.unit.research.r7_research_result_factories import (
    make_policy_record,
    make_result,
)
from tests.unit.research.r7_sample_policy_factories import (
    RECORDED_AT,
    REVISION_A,
    make_authorization,
    make_draft,
    make_policy_definition,
    make_scope,
)
from tests.unit.research.test_r7_analogy_path_owner import _path_receipt
from tests.unit.research.test_r7_post_promotion_monitoring import (
    _active_period_and_fact,
    _lifecycle_owner_evidence,
)
from tests.unit.research.test_r7_post_promotion_monitoring_missing_boundaries import (
    _fact_with_members,
    _fresh_active,
    _fresh_member,
    _fresh_prediction,
    _observation_with_invalidation,
)
from tests.unit.research.test_r7_research_result_lifecycle import (
    _authorization as local_authorization,
)
from tests.unit.research.test_r7_research_result_lifecycle import _event as local_event
from tests.unit.research.test_r7_result_family_lifecycle import (
    _authorization as family_authorization,
)
from tests.unit.research.test_r7_result_family_lifecycle import (
    _data12_family_chain,
)
from tests.unit.research.test_r7_result_family_lifecycle import _event as family_event
from tests.unit.research.test_r7_result_family_lifecycle import _evidence as family_evidence
from tests.unit.research.test_r7_result_family_lifecycle import _local_stream as local_stream
from tests.unit.research.test_r7_result_family_lifecycle import _result as family_result


def _promotion_stream_for_result(
    result: PersistedR7ResearchResult,
    *,
    promoted_at: datetime | None = None,
    result_hash: str | None = None,
) -> tuple[R7ResultLifecycleEvent, ...]:
    """Create one valid owner promotion stream for a result projection."""

    when = promoted_at or (result.recorded_at + timedelta(minutes=1))
    result_ref = R7ResearchResultRef(
        result.result_id,
        result.result_version,
        result.content_hash if result_hash is None else result_hash,
    )
    authorization = R7ResultPromotionAuthorization(
        authorization_id=f"data17-promotion:{result.result_id}",
        authorization_version="r7-result-authorization.v1",
        result_ref=result_ref,
        event_id=f"data17-promotion-event:{result.result_id}",
        event_version="r7-result-lifecycle-event.v1",
        action=R7ResultLifecycleAction.PROMOTE,
        expected_sequence=1,
        owner="research",
        issued_at=when - timedelta(seconds=1),
        recorded_at=when,
        valid_until=when + timedelta(days=30),
        reason_codes=("data17-owner-reviewed",),
        evidence_ref=f"research://data17-promotion/{result.result_id}",
    )
    return (
        create_r7_result_lifecycle_event(
            authorization=authorization,
            occurred_at=when,
            recorded_at=when + timedelta(seconds=1),
            previous_event_hash=None,
        ),
    )


def _manual_family_event(
    authorization: R7FamilyLifecycleAuthorization,
    subject: R7FamilyResultOwnerEvidence,
    target: R7FamilyResultOwnerEvidence | None = None,
    *,
    occurred_at: datetime | None = None,
    recorded_at: datetime | None = None,
) -> R7FamilyLifecycleEvent:
    """Construct a locally valid event for public replay rejection tests."""

    occurred = authorization.recorded_at if occurred_at is None else occurred_at
    recorded = occurred if recorded_at is None else recorded_at
    return R7FamilyLifecycleEvent(
        event_id=authorization.event_id,
        event_version=authorization.event_version,
        family=authorization.family,
        action=authorization.action,
        sequence=authorization.expected_sequence,
        subject_evidence=subject,
        rollback_target_evidence=target,
        authorization=authorization,
        occurred_at=occurred,
        recorded_at=recorded,
        previous_event_hash=authorization.expected_previous_event_hash,
    )


def _foreign_family(family: R7ResultFamilyIdentity) -> R7ResultFamilyIdentity:
    """Build a separately sealed family identity for cross-family tests."""

    policy_id = f"{family.policy_id}:foreign"
    digest = family_contracts._family_hash(
        family_version=family.family_version,
        policy_id=policy_id,
        policy_version=family.policy_version,
        policy_record_hash=family.policy_record_hash,
        scope_content_hash=family.scope_content_hash,
    )
    return R7ResultFamilyIdentity(
        family_id=f"r7-result-family:{digest[:32]}",
        family_version=family.family_version,
        policy_id=policy_id,
        policy_version=family.policy_version,
        policy_record_hash=family.policy_record_hash,
        scope_content_hash=family.scope_content_hash,
        content_hash=digest,
    )


def test_data17_r7_research_graph_and_receipt_reject_public_temporal_edges() -> None:
    """Exercise canonical, look-ahead, scope, and seal checks through replace/create."""

    result = make_result()
    graph = result.evidence_graph
    first, second = graph.forecast_observations
    assert graph.historical_analogy is not None

    invalidated = _observation_with_invalidation(first)
    assert invalidated.invalidation is not None
    graph_cases = (
        (lambda: replace(graph, forecast_observations=(second, first)), "canonically ordered"),
        (lambda: replace(graph, forecast_observations=(first, first)), "duplicate identities"),
        (
            lambda: replace(
                graph,
                evaluated_at=first.published_at - timedelta(microseconds=1),
            ),
            "future-dated",
        ),
        (
            lambda: replace(
                graph,
                evaluated_at=first.outcome_recorded_at - timedelta(microseconds=1),
            ),
            "future-dated",
        ),
        (
            lambda: R7ResearchEvidenceGraph.create(
                scope_content_hash=graph.scope_content_hash,
                evaluated_at=invalidated.invalidation.invalidated_at - timedelta(microseconds=1),
                forecast_observations=(invalidated,),
                historical_analogy=None,
                path_study=None,
            ),
            "invalidation is future-dated",
        ),
        (lambda: replace(graph, scope_content_hash="f" * 64), "scope substitution"),
        (
            lambda: replace(
                graph,
                evaluated_at=graph.historical_analogy.generated_at - timedelta(microseconds=1),
            ),
            "future-dated",
        ),
        (lambda: replace(graph, content_hash="0" * 64), "content_hash mismatch"),
    )
    for construct, message in graph_cases:
        with pytest.raises(ValueError, match=message):
            construct()

    empty_graph = R7ResearchEvidenceGraph.create(
        scope_content_hash=graph.scope_content_hash,
        evaluated_at=graph.evaluated_at,
        forecast_observations=(),
        historical_analogy=None,
        path_study=None,
    )
    assert not empty_graph.forecast_observations

    receipt = result.input_receipt
    with pytest.raises(ValueError, match="canonically ordered"):
        replace(receipt, forecast_observations=tuple(reversed(receipt.forecast_observations)))
    with pytest.raises(ValueError, match="duplicate identities"):
        replace(
            receipt,
            forecast_observations=(receipt.forecast_observations[0],) * 2,
        )
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(receipt, content_hash="0" * 64)


def test_data17_r7_persisted_result_rejects_identity_cutoff_graph_and_safety_drift() -> None:
    """Keep the persisted result bound to its receipt, graph, and research-only flags."""

    result = make_result()
    receipt = result.input_receipt
    with pytest.raises(ValueError, match="identity"):
        replace(
            result,
            input_receipt=R7ResearchInputReceipt.create(
                result_id="data17-other-result",
                result_version=result.result_version,
                policy_id=receipt.policy_id,
                policy_version=receipt.policy_version,
                policy_record_hash=receipt.policy_record_hash,
                evidence_graph=result.evidence_graph,
            ),
        )
    with pytest.raises(ValueError, match="recorded before"):
        replace(result, recorded_at=receipt.evaluated_at - timedelta(seconds=1))

    variant_graph = R7ResearchEvidenceGraph.create(
        scope_content_hash=result.evidence_graph.scope_content_hash,
        evaluated_at=result.evidence_graph.evaluated_at,
        forecast_observations=result.evidence_graph.forecast_observations,
        historical_analogy=None,
        path_study=None,
    )
    with pytest.raises(ValueError, match="evidence graph"):
        replace(result, evidence_graph=variant_graph)
    with pytest.raises(ValueError, match="non-training and research-only"):
        replace(result, trains_probability_model=True)
    with pytest.raises(ValueError, match="non-training and research-only"):
        replace(result, must_not_execute=False)
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(result, content_hash="0" * 64)


def test_data17_result_lifecycle_rejects_public_authorization_event_and_replay_edges() -> None:
    """Exercise result-local authorization, event, and replay guards without forged objects."""

    authorization = local_authorization()
    common = {
        "authorization_id": "data17-invalid-authorization",
        "authorization_version": authorization.authorization_version,
        "result_ref": authorization.result_ref,
        "event_id": "data17-invalid-event",
        "event_version": authorization.event_version,
        "expected_sequence": 1,
        "owner": "research",
        "issued_at": authorization.issued_at,
        "recorded_at": authorization.recorded_at,
        "valid_until": authorization.valid_until,
        "reason_codes": ("research-owner-reviewed",),
        "evidence_ref": "research://data17-invalid",
    }
    with pytest.raises(ValueError, match="timezone-aware"):
        R7ResultPromotionAuthorization(
            **{
                **common,
                "action": R7ResultLifecycleAction.PROMOTE,
                "issued_at": datetime(2026, 1, 1),
            }
        )
    with pytest.raises(ValueError, match="sequence is invalid"):
        R7ResultPromotionAuthorization(
            **{**common, "action": R7ResultLifecycleAction.PROMOTE, "expected_sequence": 0}
        )
    with pytest.raises(ValueError, match="reasons"):
        R7ResultPromotionAuthorization(
            **{**common, "action": R7ResultLifecycleAction.PROMOTE, "reason_codes": ()}
        )
    with pytest.raises(ValueError, match="research-only"):
        R7ResultPromotionAuthorization(
            **{
                **common,
                "action": R7ResultLifecycleAction.PROMOTE,
                "publishes_model_probability": True,
            }
        )

    event_common = {
        "event_id": "data17-event",
        "event_version": "r7-result-lifecycle-event.v1",
        "result_ref": authorization.result_ref,
        "authorization_id": authorization.authorization_id,
        "authorization_version": authorization.authorization_version,
        "authorization_hash": authorization.content_hash,
        "sequence": 1,
        "occurred_at": authorization.recorded_at,
        "recorded_at": authorization.recorded_at,
        "previous_event_hash": None,
        "reason_codes": authorization.reason_codes,
    }
    with pytest.raises(ValueError, match="sequence is invalid"):
        R7ResultLifecycleEvent(
            **{**event_common, "action": R7ResultLifecycleAction.PROMOTE, "sequence": 0}
        )
    with pytest.raises(ValueError, match="cannot precede"):
        R7ResultLifecycleEvent(
            **{
                **event_common,
                "action": R7ResultLifecycleAction.PROMOTE,
                "recorded_at": authorization.recorded_at - timedelta(seconds=1),
            }
        )
    with pytest.raises(ValueError, match="research-only"):
        R7ResultLifecycleEvent(
            **{
                **event_common,
                "action": R7ResultLifecycleAction.PROMOTE,
                "publishes_model_probability": True,
            }
        )

    with pytest.raises(ValueError, match="inactive"):
        create_r7_result_lifecycle_event(
            authorization=authorization,
            occurred_at=authorization.valid_until,
            recorded_at=authorization.valid_until,
            previous_event_hash=None,
        )
    with pytest.raises(ValueError, match="root cannot"):
        create_r7_result_lifecycle_event(
            authorization=authorization,
            occurred_at=authorization.recorded_at,
            recorded_at=authorization.recorded_at,
            previous_event_hash="0" * 64,
        )
    continuation = local_authorization(
        action=R7ResultLifecycleAction.RETIRE,
        sequence=2,
        recorded_at=authorization.recorded_at + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="continuation"):
        create_r7_result_lifecycle_event(
            authorization=continuation,
            occurred_at=continuation.recorded_at,
            recorded_at=continuation.recorded_at,
            previous_event_hash=None,
        )

    first = local_event(authorization, previous_event_hash=None)
    with pytest.raises(ValueError, match="no events"):
        derive_r7_result_lifecycle_state((), evaluated_at=first.recorded_at)
    with pytest.raises(ValueError, match="future evidence"):
        derive_r7_result_lifecycle_state(
            (first,), evaluated_at=first.recorded_at - timedelta(seconds=1)
        )
    other_ref = R7ResearchResultRef("data17-other-result", "r7-result.v1", "f" * 64)
    cross = local_event(
        local_authorization(
            result_ref=other_ref,
            action=R7ResultLifecycleAction.RETIRE,
            sequence=2,
            recorded_at=first.recorded_at + timedelta(minutes=1),
        ),
        previous_event_hash=first.content_hash,
    )
    with pytest.raises(ValueError, match="crosses result identities"):
        derive_r7_result_lifecycle_state((first, cross), evaluated_at=cross.recorded_at)
    nonmonotonic = local_event(
        local_authorization(
            action=R7ResultLifecycleAction.RETIRE,
            sequence=2,
            recorded_at=first.recorded_at - timedelta(minutes=1),
        ),
        previous_event_hash=first.content_hash,
    )
    with pytest.raises(ValueError, match="non-monotonic"):
        derive_r7_result_lifecycle_state((first, nonmonotonic), evaluated_at=first.recorded_at)
    repromotion = local_event(
        local_authorization(
            action=R7ResultLifecycleAction.PROMOTE,
            sequence=2,
            recorded_at=first.recorded_at + timedelta(minutes=1),
        ),
        previous_event_hash=first.content_hash,
    )
    with pytest.raises(ValueError, match="already promoted"):
        derive_r7_result_lifecycle_state((first, repromotion), evaluated_at=repromotion.recorded_at)


def test_data17_family_owner_and_authorization_guards_use_public_values() -> None:
    """Keep family evidence and authorization bound to one valid local stream."""

    result_a = family_result("data17-owner-a")
    evidence_a = family_evidence(result_a)
    family = R7ResultFamilyIdentity.from_result(result_a)
    stream = local_stream(result_a, retire=True)

    bad_tail = replace(stream[-1], sequence=3)
    attestation = R7LocalLifecycleStreamAttestation.from_stream(
        attestation_id="data17-local-attestation",
        attestation_version="r7-local-lifecycle-attestation.v1",
        complete_local_lifecycle_stream=stream,
        recorded_at=stream[-1].recorded_at,
    )
    with pytest.raises(ValueError, match="not canonical"):
        R7FamilyResultOwnerEvidence.from_owner_graph(
            result=result_a,
            complete_local_lifecycle_stream=(stream[0], bad_tail),
            local_lifecycle_attestation=attestation,
            evaluated_at=stream[-1].recorded_at,
        )
    with pytest.raises(ValueError, match="predates local Promotion"):
        replace(
            evidence_a,
            local_promoted_at=evidence_a.evaluated_at + timedelta(seconds=1),
        )

    foreign_family = _foreign_family(family)
    foreign_evidence = replace(evidence_a, family=foreign_family)
    with pytest.raises(ValueError, match="crosses families"):
        create_r7_family_lifecycle_event(
            previous_events=(),
            authorization=family_authorization(
                family=family,
                action=R7FamilyLifecycleAction.PROMOTE,
                subject=foreign_evidence,
                sequence=1,
                recorded_at=foreign_evidence.evaluated_at + timedelta(minutes=1),
                previous=None,
            ),
            subject_evidence=foreign_evidence,
            rollback_target_evidence=None,
            occurred_at=foreign_evidence.evaluated_at + timedelta(minutes=1, seconds=1),
            recorded_at=foreign_evidence.evaluated_at + timedelta(minutes=1, seconds=2),
        )

    result_b = family_result("data17-owner-b")
    evidence_b = family_evidence(result_b)
    root = family_event(
        previous_events=(),
        authorization=family_authorization(
            family=family,
            action=R7FamilyLifecycleAction.PROMOTE,
            subject=evidence_a,
            sequence=1,
            recorded_at=evidence_a.evaluated_at + timedelta(minutes=1),
            previous=None,
        ),
        subject=evidence_a,
    )
    second = family_event(
        previous_events=(root,),
        authorization=family_authorization(
            family=family,
            action=R7FamilyLifecycleAction.PROMOTE,
            subject=evidence_b,
            sequence=2,
            recorded_at=root.recorded_at + timedelta(minutes=1),
            previous=root,
        ),
        subject=evidence_b,
    )
    retired_target = family_evidence(result_a, retire=True, as_of=second.recorded_at)
    rollback_authorization = family_authorization(
        family=family,
        action=R7FamilyLifecycleAction.ROLLBACK,
        subject=evidence_b,
        target=retired_target,
        sequence=3,
        recorded_at=second.recorded_at + timedelta(minutes=1),
        previous=second,
    )
    with pytest.raises(ValueError, match="cannot activate"):
        family_event(
            previous_events=(root, second),
            authorization=rollback_authorization,
            subject=evidence_b,
            target=retired_target,
        )

    foreign_target = replace(evidence_a, family=foreign_family)
    foreign_target_authorization = family_authorization(
        family=family,
        action=R7FamilyLifecycleAction.ROLLBACK,
        subject=evidence_b,
        target=foreign_target,
        sequence=3,
        recorded_at=second.recorded_at + timedelta(minutes=2),
        previous=second,
    )
    with pytest.raises(ValueError, match="crosses families"):
        family_event(
            previous_events=(root, second),
            authorization=foreign_target_authorization,
            subject=evidence_b,
            target=foreign_target,
        )


def test_data17_family_replay_rejects_public_stale_heads_and_stack_mutations() -> None:
    """Replay validly sealed events and reject only their chain-level contradictions."""

    (
        result_a,
        result_b,
        evidence_a,
        evidence_b,
        family,
        _,
        root,
        _,
        second,
    ) = _data12_family_chain()
    latest = second.recorded_at + timedelta(hours=1)

    foreign_evidence = replace(evidence_a, family=_foreign_family(family))
    foreign_event = _manual_family_event(
        family_authorization(
            family=foreign_evidence.family,
            action=R7FamilyLifecycleAction.PROMOTE,
            subject=foreign_evidence,
            sequence=2,
            recorded_at=root.recorded_at + timedelta(minutes=1),
            previous=root,
        ),
        foreign_evidence,
    )
    with pytest.raises(ValueError, match="crosses families"):
        derive_r7_family_lifecycle_state((root, foreign_event), evaluated_at=latest)

    gap_event = _manual_family_event(
        family_authorization(
            family=family,
            action=R7FamilyLifecycleAction.PROMOTE,
            subject=evidence_b,
            sequence=3,
            recorded_at=root.recorded_at + timedelta(minutes=2),
            previous=root,
        ),
        evidence_b,
    )
    with pytest.raises(ValueError, match="discontinuous"):
        derive_r7_family_lifecycle_state((root, gap_event), evaluated_at=latest)

    stale_authorization = replace(
        family_authorization(
            family=family,
            action=R7FamilyLifecycleAction.PROMOTE,
            subject=evidence_b,
            sequence=2,
            recorded_at=root.recorded_at + timedelta(minutes=1),
            previous=root,
        ),
        expected_previous_event_id="data17-wrong-head",
    )
    with pytest.raises(ValueError, match="authorization head is stale"):
        derive_r7_family_lifecycle_state(
            (root, _manual_family_event(stale_authorization, evidence_b)),
            evaluated_at=latest,
        )

    nonmonotonic = _manual_family_event(
        family_authorization(
            family=family,
            action=R7FamilyLifecycleAction.PROMOTE,
            subject=evidence_b,
            sequence=2,
            recorded_at=root.recorded_at,
            previous=root,
        ),
        evidence_b,
    )
    with pytest.raises(ValueError, match="non-monotonic"):
        derive_r7_family_lifecycle_state((root, nonmonotonic), evaluated_at=latest)

    root_retire = _manual_family_event(
        family_authorization(
            family=family,
            action=R7FamilyLifecycleAction.RETIRE,
            subject=evidence_a,
            sequence=1,
            recorded_at=evidence_a.evaluated_at + timedelta(minutes=1),
            previous=None,
        ),
        evidence_a,
    )
    with pytest.raises(ValueError, match="root must promote"):
        derive_r7_family_lifecycle_state((root_retire,), evaluated_at=latest)

    inactive_evidence = family_evidence(result_a, retire=True)
    inactive_promotion = _manual_family_event(
        family_authorization(
            family=family,
            action=R7FamilyLifecycleAction.PROMOTE,
            subject=inactive_evidence,
            sequence=1,
            recorded_at=inactive_evidence.evaluated_at + timedelta(minutes=1),
            previous=None,
        ),
        inactive_evidence,
    )
    with pytest.raises(ValueError, match="cannot activate"):
        derive_r7_family_lifecycle_state((inactive_promotion,), evaluated_at=latest)

    duplicate = _manual_family_event(
        family_authorization(
            family=family,
            action=R7FamilyLifecycleAction.PROMOTE,
            subject=evidence_a,
            sequence=3,
            recorded_at=second.recorded_at + timedelta(minutes=1),
            previous=second,
        ),
        evidence_a,
    )
    with pytest.raises(ValueError, match="duplicates"):
        derive_r7_family_lifecycle_state((root, second, duplicate), evaluated_at=latest)

    wrong_retire = _manual_family_event(
        family_authorization(
            family=family,
            action=R7FamilyLifecycleAction.RETIRE,
            subject=evidence_b,
            sequence=2,
            recorded_at=root.recorded_at + timedelta(minutes=1),
            previous=root,
        ),
        evidence_b,
    )
    with pytest.raises(ValueError, match="does not target active"):
        derive_r7_family_lifecycle_state((root, wrong_retire), evaluated_at=latest)

    result_c = family_result("data17-owner-c")
    evidence_c = family_evidence(result_c)
    wrong_rollback = _manual_family_event(
        family_authorization(
            family=family,
            action=R7FamilyLifecycleAction.ROLLBACK,
            subject=evidence_b,
            target=evidence_c,
            sequence=3,
            recorded_at=second.recorded_at + timedelta(minutes=1),
            previous=second,
        ),
        evidence_b,
        evidence_c,
    )
    with pytest.raises(ValueError, match=r"stack\[-2\]"):
        derive_r7_family_lifecycle_state((root, second, wrong_rollback), evaluated_at=latest)

    inactive_rollback = _manual_family_event(
        family_authorization(
            family=family,
            action=R7FamilyLifecycleAction.ROLLBACK,
            subject=evidence_b,
            target=family_evidence(result_a, retire=True, as_of=second.recorded_at),
            sequence=3,
            recorded_at=second.recorded_at + timedelta(minutes=2),
            previous=second,
        ),
        evidence_b,
        family_evidence(result_a, retire=True, as_of=second.recorded_at),
    )
    with pytest.raises(ValueError, match="target cannot activate"):
        derive_r7_family_lifecycle_state((root, second, inactive_rollback), evaluated_at=latest)


def test_data17_sample_policy_authority_and_registration_guards_are_fail_closed() -> None:
    """Require one coherent scope, policy definition, owner approval, and clock."""

    draft = make_draft()
    authorization = make_authorization(draft)
    record = PersistedR7SamplePolicy.create(
        policy_id=draft.policy_id,
        policy_version=draft.policy_version,
        scope=draft.scope,
        policy_definition=draft.policy_definition,
        authorization=authorization,
        recorded_at=RECORDED_AT,
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        replace(record.authorization, issued_at=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="authority"):
        replace(record.authorization, owner="foreign")
    with pytest.raises(ValueError, match="valid_until"):
        replace(record.authorization, valid_until=record.authorization.issued_at)

    with pytest.raises(ValueError, match="policy version mismatch"):
        replace(
            record,
            policy=make_policy_definition(policy_version="r7-sample-policy.v2"),
        )
    foreign_draft = make_draft(policy_id="r7-policy:foreign")
    with pytest.raises(ValueError, match="approval graph"):
        replace(record, authorization=make_authorization(foreign_draft))
    with pytest.raises(ValueError, match="authorization validity"):
        replace(record, recorded_at=record.authorization.valid_until)
    with pytest.raises(ValueError, match="pre-registered"):
        replace(record, recorded_at=record.policy.activated_at + timedelta(seconds=1))
    with pytest.raises(ValueError, match="research-only"):
        replace(record, research_only=False)
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(record, content_hash="0" * 64)

    with pytest.raises(ValueError, match="forecast_horizon mismatch"):
        PersistedR7SamplePolicy.create(
            policy_id=draft.policy_id,
            policy_version=draft.policy_version,
            scope=draft.scope,
            policy_definition=make_policy_definition(
                forecast_horizon=timedelta(days=91),
            ),
            authorization=authorization,
            recorded_at=RECORDED_AT,
        )
    with pytest.raises(ValueError, match="path_horizon_periods mismatch"):
        PersistedR7SamplePolicy.create(
            policy_id=draft.policy_id,
            policy_version=draft.policy_version,
            scope=draft.scope,
            policy_definition=make_policy_definition(path_horizon_periods=4),
            authorization=authorization,
            recorded_at=RECORDED_AT,
        )
    with pytest.raises(ValueError, match="every scope revision"):
        PersistedR7SamplePolicy.create(
            policy_id=draft.policy_id,
            policy_version=draft.policy_version,
            scope=make_scope(path_initial_state_revision_ids=(REVISION_A,)),
            policy_definition=make_policy_definition(),
            authorization=authorization,
            recorded_at=RECORDED_AT,
        )


def test_data17_path_owner_replays_manifest_features_without_aliasing() -> None:
    """Exercise the valid PIT feature copy branch through the public raw-source factory."""

    receipt = _path_receipt()
    manifest = PointInTimeManifestReference.create(
        manifest_id="data17-path-manifest",
        manifest_version="pit-manifest.v1",
        as_of=receipt.source.pit_manifest.as_of,
        manifest_hash="a" * 64,
        features=(
            PointInTimeManifestFeature(
                feature_key="growth",
                source_version="macro-vintage.v1",
                available_at=receipt.source.pit_manifest.as_of - timedelta(hours=2),
                vintage_at=receipt.source.pit_manifest.as_of - timedelta(hours=1),
                content_hash="b" * 64,
            ),
        ),
    )
    source = ScenarioPathRawSource.create(
        pit_manifest=manifest,
        sample_members=receipt.source.sample_members,
        shocks=receipt.source.shocks,
        available_at=receipt.source.available_at,
        evidence_refs=receipt.source.evidence_refs,
    )
    assert source.pit_manifest.features[0].feature_key == "growth"
    assert source.pit_manifest.features[0] is not manifest.features[0]


def test_data17_monitoring_rejects_owner_substitution_and_incomplete_projections() -> None:
    """Bind monitoring projections to the exact promoted result and forecast set."""

    result = make_result()
    stream = _promotion_stream_for_result(result, result_hash="f" * 64)
    with pytest.raises(ValueError, match="result substitution"):
        R7MonitoringActiveResult.from_owner_graph(
            result=result,
            lifecycle_stream=stream,
            lifecycle_owner_evidence=_lifecycle_owner_evidence(stream),
        )

    late_result = materialize_persisted_r7_research_result(
        result_id="data17-late-result",
        result_version=result.result_version,
        policy_record=make_policy_record(),
        evidence_graph=result.evidence_graph,
        evaluated_at=result.evidence_graph.evaluated_at,
        recorded_at=result.recorded_at + timedelta(minutes=2),
    )
    late_stream = _promotion_stream_for_result(
        late_result,
        promoted_at=result.recorded_at + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="predates its result"):
        R7MonitoringActiveResult.from_owner_graph(
            result=late_result,
            lifecycle_stream=late_stream,
            lifecycle_owner_evidence=_lifecycle_owner_evidence(late_stream),
        )

    empty_graph = R7ResearchEvidenceGraph.create(
        scope_content_hash=result.evidence_graph.scope_content_hash,
        evaluated_at=result.evidence_graph.evaluated_at,
        forecast_observations=(),
        historical_analogy=result.evidence_graph.historical_analogy,
        path_study=result.evidence_graph.path_study,
    )
    empty_result = materialize_persisted_r7_research_result(
        result_id="data17-empty-result",
        result_version=result.result_version,
        policy_record=make_policy_record(),
        evidence_graph=empty_graph,
        evaluated_at=empty_graph.evaluated_at,
        recorded_at=result.recorded_at,
    )
    empty_stream = _promotion_stream_for_result(empty_result)
    with pytest.raises(ValueError, match="no forecast predictions"):
        R7MonitoringActiveResult.from_owner_graph(
            result=empty_result,
            lifecycle_stream=empty_stream,
            lifecycle_owner_evidence=_lifecycle_owner_evidence(empty_stream),
        )


def test_data17_monitoring_rejects_post_period_predictions_and_scores_model_owner() -> None:
    """Exercise strict pre-period selection and the complete model scoring branch."""

    active, _, period, fact = _active_period_and_fact()
    source = make_result().evidence_graph.forecast_observations[0]
    post_period = ForecastLedgerOutcomeObservation.create(
        observation_version=source.observation_version,
        entry_id="data17-post-period",
        forecast_group_id=source.forecast_group_id,
        binding=source.binding,
        pit_manifest_id=source.pit_manifest_id,
        pit_manifest_version=source.pit_manifest_version,
        pit_manifest_hash=source.pit_manifest_hash,
        censoring_rule_version=source.censoring_rule_version,
        published_at=period.period_start + timedelta(seconds=1),
        horizon_end=period.period_end,
        scenario_realized=True,
        outcome_recorded_at=period.period_end + timedelta(hours=1),
        outcome_evidence_valid_until=period.period_end + timedelta(days=1),
    )
    post_prediction = R7MonitoringPredictionMember.from_observation(post_period)
    active_with_post = _fresh_active(
        active,
        tuple(
            sorted(
                (*active.predictions, post_prediction),
                key=lambda item: (item.entry_id, item.observation_version),
            )
        ),
    )
    with pytest.raises(ValueError, match="non-pre-period"):
        calculate_r7_forecast_outcome_coverage(
            active=active_with_post,
            period=period,
            realization=fact,
        )

    first, second = active.predictions
    model_first = _fresh_prediction(
        first,
        model_probability=Decimal("0.55"),
        model_probability_source_version="data17-model.v1",
        model_promotion_decision_id="data17-model:1",
    )
    model_second = _fresh_prediction(
        second,
        model_probability=Decimal("0.45"),
        model_probability_source_version="data17-model.v1",
        model_promotion_decision_id="data17-model:1",
    )
    model_active = _fresh_active(active, (model_first, model_second))
    model_fact = _fact_with_members(
        period,
        fact,
        (
            _fresh_member(fact.members[0], prediction_hash=model_first.content_hash),
            _fresh_member(fact.members[1], prediction_hash=model_second.content_hash),
        ),
    )
    score = calculate_r7_brier_score(
        active=model_active,
        period=period,
        realization=model_fact,
        source=ScenarioProbabilitySource.MODEL_INFERRED,
    )
    assert score == Decimal("0.2025")


def test_data17_monitoring_owner_and_contract_seals_reject_public_tampering() -> None:
    """Keep owner record, fact, period, and observation types exact."""

    active, _, period, fact = _active_period_and_fact()
    with pytest.raises(ValueError, match="record version is unsupported"):
        replace(fact.owner_record, record_version="r7-owner.v2")
    with pytest.raises(ValueError, match="fact content hash mismatch"):
        replace(fact, content_hash="0" * 64)
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(period, period_start=datetime(2026, 1, 1))
    with pytest.raises(TypeError, match="exact Forecast Ledger"):
        R7ForecastRealizationMember.from_owner_observation(
            observation=object(),
            available_at=period.period_end,
            recorded_at=period.period_end,
            evidence_ref="research://data17-invalid-observation",
        )
