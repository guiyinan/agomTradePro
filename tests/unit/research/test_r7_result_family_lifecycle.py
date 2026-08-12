"""R7 family lifecycle keeps rollback internal, exact, and research-only."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from apps.research.application.r7_research_result_persistence import (
    materialize_persisted_r7_research_result,
)
from apps.research.application.r7_result_family_lifecycle import (
    ApplyR7FamilyLifecycle,
    ApplyR7FamilyLifecycleCommand,
    R7FamilyAuthorizationRef,
    R7FamilyLifecycleUnavailable,
    R7FamilyOwnerSourceGraph,
    R7FamilyResultIdRef,
    R7ResultFamilyRef,
)
from apps.research.domain.r7_research_result_lifecycle import (
    R7ResearchResultRef,
    R7ResultLifecycleAction,
    R7ResultLifecycleEvent,
    R7ResultPromotionAuthorization,
    create_r7_result_lifecycle_event,
)
from apps.research.domain.r7_research_result_persistence import (
    PersistedR7ResearchResult,
)
from apps.research.domain.r7_result_family_lifecycle import (
    R7FamilyLifecycleAction,
    R7FamilyLifecycleAuthorization,
    R7FamilyLifecycleEvent,
    R7FamilyLifecycleStatus,
    R7FamilyResultOwnerEvidence,
    R7LocalLifecycleStreamAttestation,
    R7ResultFamilyIdentity,
    create_r7_family_lifecycle_event,
    derive_r7_family_lifecycle_state,
)
from tests.unit.research.r7_research_result_factories import (
    RESULT_RECORDED_AT,
    make_evidence_graph,
    make_policy_record,
    make_result,
)


def _result(name: str) -> PersistedR7ResearchResult:
    return materialize_persisted_r7_research_result(
        result_id=f"r7-family-result:{name}",
        result_version="r7-result.v1",
        policy_record=make_policy_record(),
        evidence_graph=make_evidence_graph(),
        evaluated_at=make_evidence_graph().evaluated_at,
        recorded_at=RESULT_RECORDED_AT,
    )


def _local_stream(
    result: PersistedR7ResearchResult,
    *,
    retire: bool = False,
) -> tuple[R7ResultLifecycleEvent, ...]:
    result_ref = R7ResearchResultRef(
        result.result_id,
        result.result_version,
        result.content_hash,
    )
    promoted_at = result.recorded_at + timedelta(minutes=1)
    promotion = R7ResultPromotionAuthorization(
        authorization_id=f"local-promotion:{result.result_id}",
        authorization_version="r7-result-authorization.v1",
        result_ref=result_ref,
        event_id=f"local-promotion-event:{result.result_id}",
        event_version="r7-result-lifecycle-event.v1",
        action=R7ResultLifecycleAction.PROMOTE,
        expected_sequence=1,
        owner="research",
        issued_at=promoted_at - timedelta(seconds=1),
        recorded_at=promoted_at,
        valid_until=promoted_at + timedelta(days=30),
        reason_codes=("research-owner-approved",),
        evidence_ref=f"research://local-promotion/{result.result_id}",
    )
    root = create_r7_result_lifecycle_event(
        authorization=promotion,
        occurred_at=promoted_at,
        recorded_at=promoted_at + timedelta(seconds=1),
        previous_event_hash=None,
    )
    if not retire:
        return (root,)
    retired_at = root.recorded_at + timedelta(minutes=1)
    retirement = R7ResultPromotionAuthorization(
        authorization_id=f"local-retirement:{result.result_id}",
        authorization_version="r7-result-authorization.v1",
        result_ref=result_ref,
        event_id=f"local-retirement-event:{result.result_id}",
        event_version="r7-result-lifecycle-event.v1",
        action=R7ResultLifecycleAction.RETIRE,
        expected_sequence=2,
        owner="research",
        issued_at=retired_at - timedelta(seconds=1),
        recorded_at=retired_at,
        valid_until=retired_at + timedelta(days=30),
        reason_codes=("research-owner-retired",),
        evidence_ref=f"research://local-retirement/{result.result_id}",
    )
    tail = create_r7_result_lifecycle_event(
        authorization=retirement,
        occurred_at=retired_at,
        recorded_at=retired_at + timedelta(seconds=1),
        previous_event_hash=root.content_hash,
    )
    return (root, tail)


def _evidence(
    result: PersistedR7ResearchResult,
    *,
    retire: bool = False,
    as_of: datetime | None = None,
) -> R7FamilyResultOwnerEvidence:
    stream = _local_stream(result, retire=retire)
    return R7FamilyResultOwnerEvidence.from_owner_graph(
        result=result,
        complete_local_lifecycle_stream=stream,
        local_lifecycle_attestation=R7LocalLifecycleStreamAttestation.from_stream(
            attestation_id=f"r7-local-lifecycle-attestation:{result.result_id}",
            attestation_version="r7-local-lifecycle-attestation.v1",
            complete_local_lifecycle_stream=stream,
            recorded_at=stream[-1].recorded_at,
        ),
        evaluated_at=as_of or stream[-1].recorded_at,
    )


def _authorization(
    *,
    family: R7ResultFamilyIdentity,
    action: R7FamilyLifecycleAction,
    subject: R7FamilyResultOwnerEvidence,
    sequence: int,
    recorded_at: datetime,
    previous: R7FamilyLifecycleEvent | None,
    target: R7FamilyResultOwnerEvidence | None = None,
) -> R7FamilyLifecycleAuthorization:
    previous_hash = None if previous is None else previous.content_hash
    previous_id = None if previous is None else previous.event_id
    previous_version = None if previous is None else previous.event_version
    return R7FamilyLifecycleAuthorization.create(
        authorization_id=f"r7-family-authorization:{sequence}",
        authorization_version="r7-family-authorization.v1",
        family=family,
        event_id=f"r7-family-event:{sequence}",
        event_version="r7-family-event.v1",
        action=action,
        subject_ref=subject.result_ref,
        subject_owner_attestation_hash=(subject.local_lifecycle_attestation.content_hash),
        rollback_target_ref=None if target is None else target.result_ref,
        rollback_target_owner_attestation_hash=(
            None if target is None else target.local_lifecycle_attestation.content_hash
        ),
        expected_sequence=sequence,
        expected_previous_event_id=previous_id,
        expected_previous_event_version=previous_version,
        expected_previous_event_hash=previous_hash,
        owner="research",
        issued_at=recorded_at - timedelta(seconds=1),
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(days=1),
        reason_codes=("manual-research-governance",),
        evidence_ref=f"research://r7-family-authorization/{sequence}",
    )


def _event(
    *,
    previous_events: tuple[R7FamilyLifecycleEvent, ...],
    authorization: R7FamilyLifecycleAuthorization,
    subject: R7FamilyResultOwnerEvidence,
    target: R7FamilyResultOwnerEvidence | None = None,
) -> R7FamilyLifecycleEvent:
    return create_r7_family_lifecycle_event(
        previous_events=previous_events,
        authorization=authorization,
        subject_evidence=subject,
        rollback_target_evidence=target,
        occurred_at=authorization.recorded_at + timedelta(seconds=1),
        recorded_at=authorization.recorded_at + timedelta(seconds=2),
    )


def test_family_rollback_restores_only_exact_approved_stack_minus_two() -> None:
    result_a = _result("a")
    result_b = _result("b")
    evidence_a = _evidence(result_a)
    evidence_b = _evidence(result_b)
    family = R7ResultFamilyIdentity.from_result(result_a)
    assert R7ResultFamilyIdentity.from_result(result_b) == family

    auth_a = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence_a,
        sequence=1,
        recorded_at=evidence_a.evaluated_at + timedelta(minutes=1),
        previous=None,
    )
    event_a = _event(previous_events=(), authorization=auth_a, subject=evidence_a)
    auth_b = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence_b,
        sequence=2,
        recorded_at=event_a.recorded_at + timedelta(minutes=1),
        previous=event_a,
    )
    event_b = _event(previous_events=(event_a,), authorization=auth_b, subject=evidence_b)
    rollback_auth = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.ROLLBACK,
        subject=evidence_b,
        target=evidence_a,
        sequence=3,
        recorded_at=event_b.recorded_at + timedelta(minutes=1),
        previous=event_b,
    )
    rollback = _event(
        previous_events=(event_a, event_b),
        authorization=rollback_auth,
        subject=evidence_b,
        target=evidence_a,
    )

    state = derive_r7_family_lifecycle_state(
        (event_a, event_b, rollback),
        evaluated_at=rollback.recorded_at,
    )
    assert state.status is R7FamilyLifecycleStatus.ROLLED_BACK
    assert state.active_result_ref == evidence_a.result_ref
    assert state.approved_stack == (evidence_a.result_ref,)

    result_c = _result("c")
    evidence_c = _evidence(result_c)
    wrong = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.ROLLBACK,
        subject=evidence_b,
        target=evidence_c,
        sequence=3,
        recorded_at=event_b.recorded_at + timedelta(minutes=1),
        previous=event_b,
    )
    with pytest.raises(ValueError, match=r"stack\[-2\]"):
        _event(
            previous_events=(event_a, event_b),
            authorization=wrong,
            subject=evidence_b,
            target=evidence_c,
        )


def test_expired_or_locally_retired_result_can_only_be_cleaned_up() -> None:
    result = make_result()
    promoted = _evidence(result)
    family = R7ResultFamilyIdentity.from_result(result)
    promote_auth = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=promoted,
        sequence=1,
        recorded_at=promoted.evaluated_at + timedelta(minutes=1),
        previous=None,
    )
    promoted_event = _event(
        previous_events=(),
        authorization=promote_auth,
        subject=promoted,
    )
    retired = _evidence(
        result,
        retire=True,
        as_of=_local_stream(result, retire=True)[-1].recorded_at,
    )
    retire_auth = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.RETIRE,
        subject=retired,
        sequence=2,
        recorded_at=promoted_event.recorded_at + timedelta(minutes=2),
        previous=promoted_event,
    )
    retired_event = _event(
        previous_events=(promoted_event,),
        authorization=retire_auth,
        subject=retired,
    )
    state = derive_r7_family_lifecycle_state(
        (promoted_event, retired_event),
        evaluated_at=retired_event.recorded_at,
    )
    assert state.status is R7FamilyLifecycleStatus.RETIRED
    assert state.active_result_ref is None

    with pytest.raises(ValueError, match="cannot activate"):
        _event(
            previous_events=(),
            authorization=_authorization(
                family=family,
                action=R7FamilyLifecycleAction.PROMOTE,
                subject=retired,
                sequence=1,
                recorded_at=retired.evaluated_at + timedelta(minutes=1),
                previous=None,
            ),
            subject=retired,
        )


def test_authorization_binds_previous_head_and_all_outputs_are_research_only() -> None:
    result_a = _result("a")
    result_b = _result("b")
    evidence_a = _evidence(result_a)
    evidence_b = _evidence(result_b)
    family = R7ResultFamilyIdentity.from_result(result_a)
    root_auth = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence_a,
        sequence=1,
        recorded_at=evidence_a.evaluated_at + timedelta(minutes=1),
        previous=None,
    )
    root = _event(previous_events=(), authorization=root_auth, subject=evidence_a)
    stale = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence_b,
        sequence=2,
        recorded_at=root.recorded_at,
        previous=root,
    )
    with pytest.raises(ValueError, match="strictly follow"):
        _event(previous_events=(root,), authorization=stale, subject=evidence_b)

    for item in (evidence_a, root_auth, root):
        assert item.research_only is True
        assert item.publishes_model_probability is False
        assert item.publishes_probability_current is False
        assert item.produces_decision is False
        assert item.executes_orders is False
        assert item.must_not_use_for_decision is True
        assert item.must_not_execute is True


def test_owner_evidence_rejects_truncated_stream_against_authoritative_head() -> None:
    result = _result("truncated-owner-stream")
    complete = _local_stream(result, retire=True)
    attestation = R7LocalLifecycleStreamAttestation.from_stream(
        attestation_id="r7-local-attestation:truncated-owner-stream",
        attestation_version="r7-local-lifecycle-attestation.v1",
        complete_local_lifecycle_stream=complete,
        recorded_at=complete[-1].recorded_at,
    )

    with pytest.raises(ValueError, match="attestation|truncated|stream"):
        R7FamilyResultOwnerEvidence.from_owner_graph(
            result=result,
            complete_local_lifecycle_stream=(complete[0],),
            local_lifecycle_attestation=attestation,
            evaluated_at=complete[-1].recorded_at,
        )


def test_family_rejects_repromoting_any_result_already_in_approved_stack() -> None:
    result_a = _result("duplicate-stack-a")
    result_b = _result("duplicate-stack-b")
    evidence_a = _evidence(result_a)
    evidence_b = _evidence(result_b)
    family = R7ResultFamilyIdentity.from_result(result_a)
    auth_a = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence_a,
        sequence=1,
        recorded_at=evidence_a.evaluated_at + timedelta(minutes=1),
        previous=None,
    )
    event_a = _event(previous_events=(), authorization=auth_a, subject=evidence_a)
    auth_b = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence_b,
        sequence=2,
        recorded_at=event_a.recorded_at + timedelta(minutes=1),
        previous=event_a,
    )
    event_b = _event(previous_events=(event_a,), authorization=auth_b, subject=evidence_b)
    duplicate = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence_a,
        sequence=3,
        recorded_at=event_b.recorded_at + timedelta(minutes=1),
        previous=event_b,
    )

    with pytest.raises(ValueError, match="approved stack"):
        _event(
            previous_events=(event_a, event_b),
            authorization=duplicate,
            subject=evidence_a,
        )


class _ResultProvider:
    def __init__(self, results: tuple[PersistedR7ResearchResult, ...]) -> None:
        self.unit_of_work_key = "research-uow"
        self.results = {(item.result_id, item.result_version): item for item in results}
        self.calls: list[tuple[R7FamilyResultIdRef, datetime]] = []
        self.replacement_after_calls: int | None = None
        self.replacement: PersistedR7ResearchResult | None = None

    def get_exact(
        self,
        *,
        result_ref: R7FamilyResultIdRef,
        as_of: datetime,
    ) -> PersistedR7ResearchResult | None:
        self.calls.append((result_ref, as_of))
        value = (
            self.replacement
            if self.replacement_after_calls is not None
            and len(self.calls) > self.replacement_after_calls
            else self.results.get((result_ref.result_id, result_ref.result_version))
        )
        return value if value is not None and value.recorded_at <= as_of else None


class _LocalLifecycleProvider:
    def __init__(
        self,
        streams: dict[tuple[str, str], tuple[R7ResultLifecycleEvent, ...]],
    ) -> None:
        self.unit_of_work_key = "research-uow"
        self.streams = streams
        self.calls: list[tuple[R7FamilyResultIdRef, datetime]] = []
        self.replacement_after_load_calls: int | None = None
        self.replacement_stream: tuple[R7ResultLifecycleEvent, ...] | None = None

    def _stream_at(
        self,
        result_ref: R7FamilyResultIdRef,
        as_of: datetime,
    ) -> tuple[R7ResultLifecycleEvent, ...]:
        source = (
            self.replacement_stream
            if self.replacement_after_load_calls is not None
            and len(self.calls) > self.replacement_after_load_calls
            and self.replacement_stream is not None
            else self.streams.get((result_ref.result_id, result_ref.result_version), ())
        )
        return tuple(event for event in source if event.recorded_at <= as_of)

    def load_complete(
        self,
        *,
        result_ref: R7FamilyResultIdRef,
        as_of: datetime,
    ) -> tuple[R7ResultLifecycleEvent, ...]:
        self.calls.append((result_ref, as_of))
        return self._stream_at(result_ref, as_of)

    def get_attestation(
        self,
        *,
        result_ref: R7FamilyResultIdRef,
        as_of: datetime,
    ) -> R7LocalLifecycleStreamAttestation | None:
        stream = self._stream_at(result_ref, as_of)
        if not stream:
            return None
        return R7LocalLifecycleStreamAttestation.from_stream(
            attestation_id=f"r7-local-lifecycle-attestation:{result_ref.result_id}",
            attestation_version="r7-local-lifecycle-attestation.v1",
            complete_local_lifecycle_stream=stream,
            recorded_at=stream[-1].recorded_at,
        )


class _AuthorizationProvider:
    def __init__(self) -> None:
        self.unit_of_work_key = "research-uow"
        self.value: R7FamilyLifecycleAuthorization | None = None
        self.calls: list[datetime] = []
        self.replacement_after_calls: int | None = None
        self.replacement: R7FamilyLifecycleAuthorization | None = None

    def get_exact(
        self,
        *,
        authorization_ref: R7FamilyAuthorizationRef,
        family_ref: R7ResultFamilyRef,
        action: R7FamilyLifecycleAction,
        subject_ref: R7FamilyResultIdRef,
        rollback_target_ref: R7FamilyResultIdRef | None,
        as_of: datetime,
    ) -> R7FamilyLifecycleAuthorization | None:
        del authorization_ref, family_ref, action, subject_ref, rollback_target_ref
        self.calls.append(as_of)
        value = (
            self.replacement
            if self.replacement_after_calls is not None
            and len(self.calls) > self.replacement_after_calls
            else self.value
        )
        if value is None or value.recorded_at > as_of:
            return None
        return value


class _FamilyRepository:
    def __init__(self, now: datetime) -> None:
        self.unit_of_work_key = "research-uow"
        self.now = now
        self.stream: list[R7FamilyLifecycleEvent] = []
        self.append_calls = 0
        self.rolled_back = False

    @contextmanager
    def atomic(self) -> Iterator[None]:
        before = list(self.stream)
        try:
            yield
        except Exception:
            self.stream = before
            self.rolled_back = True
            raise

    def server_now(self) -> datetime:
        return self.now

    def load_complete(
        self,
        *,
        family_ref: R7ResultFamilyRef,
        as_of: datetime,
    ) -> tuple[R7FamilyLifecycleEvent, ...]:
        del family_ref
        return tuple(event for event in self.stream if event.recorded_at <= as_of)

    def get_by_authorization(
        self,
        *,
        authorization_ref: R7FamilyAuthorizationRef,
    ) -> R7FamilyLifecycleEvent | None:
        return next(
            (
                event
                for event in self.stream
                if (
                    event.authorization.authorization_id,
                    event.authorization.authorization_version,
                )
                == (
                    authorization_ref.authorization_id,
                    authorization_ref.authorization_version,
                )
            ),
            None,
        )

    def append(
        self,
        *,
        authorization: R7FamilyLifecycleAuthorization,
        event: R7FamilyLifecycleEvent,
        subject_source: R7FamilyOwnerSourceGraph,
        rollback_target_source: R7FamilyOwnerSourceGraph | None,
    ) -> R7FamilyLifecycleEvent:
        assert event.authorization == authorization
        assert subject_source.evidence == event.subject_evidence
        assert (
            None if rollback_target_source is None else rollback_target_source.evidence
        ) == event.rollback_target_evidence
        self.append_calls += 1
        self.stream.append(event)
        return event


def _family_command(
    authorization: R7FamilyLifecycleAuthorization,
) -> ApplyR7FamilyLifecycleCommand:
    return ApplyR7FamilyLifecycleCommand(
        family_ref=R7ResultFamilyRef(
            authorization.family.family_id,
            authorization.family.family_version,
        ),
        action=authorization.action,
        subject_ref=R7FamilyResultIdRef(
            authorization.subject_ref.result_id,
            authorization.subject_ref.result_version,
        ),
        rollback_target_ref=(
            None
            if authorization.rollback_target_ref is None
            else R7FamilyResultIdRef(
                authorization.rollback_target_ref.result_id,
                authorization.rollback_target_ref.result_version,
            )
        ),
        authorization_ref=R7FamilyAuthorizationRef(
            authorization.authorization_id,
            authorization.authorization_version,
        ),
        as_of=authorization.recorded_at,
    )


def _replace_authorization(
    value: R7FamilyLifecycleAuthorization,
) -> R7FamilyLifecycleAuthorization:
    return R7FamilyLifecycleAuthorization.create(
        authorization_id=value.authorization_id,
        authorization_version=value.authorization_version,
        family=value.family,
        event_id=value.event_id,
        event_version=value.event_version,
        action=value.action,
        subject_ref=value.subject_ref,
        subject_owner_attestation_hash=value.subject_owner_attestation_hash,
        rollback_target_ref=value.rollback_target_ref,
        rollback_target_owner_attestation_hash=(value.rollback_target_owner_attestation_hash),
        expected_sequence=value.expected_sequence,
        expected_previous_event_id=value.expected_previous_event_id,
        expected_previous_event_version=value.expected_previous_event_version,
        expected_previous_event_hash=value.expected_previous_event_hash,
        owner=value.owner,
        issued_at=value.issued_at,
        recorded_at=value.recorded_at,
        valid_until=value.valid_until,
        reason_codes=value.reason_codes,
        evidence_ref=f"{value.evidence_ref}:replacement",
    )


def _application_fixture(
    *results: PersistedR7ResearchResult,
) -> tuple[
    ApplyR7FamilyLifecycle,
    _ResultProvider,
    _LocalLifecycleProvider,
    _AuthorizationProvider,
    _FamilyRepository,
]:
    result_provider = _ResultProvider(results)
    local_provider = _LocalLifecycleProvider(
        {(item.result_id, item.result_version): _local_stream(item) for item in results}
    )
    authorization_provider = _AuthorizationProvider()
    repository = _FamilyRepository(RESULT_RECORDED_AT + timedelta(days=1))
    use_case = ApplyR7FamilyLifecycle(
        result_provider=result_provider,
        local_lifecycle_provider=local_provider,
        authorization_provider=authorization_provider,
        repository=repository,
    )
    return (
        use_case,
        result_provider,
        local_provider,
        authorization_provider,
        repository,
    )


def test_application_rereads_exact_owner_graph_and_applies_family_rollback() -> None:
    result_a = _result("app-a")
    result_b = _result("app-b")
    use_case, result_owner, local_owner, authorization_owner, repository = _application_fixture(
        result_a, result_b
    )
    evidence_a = _evidence(result_a)
    evidence_b = _evidence(result_b)
    family = R7ResultFamilyIdentity.from_result(result_a)
    auth_a = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence_a,
        sequence=1,
        recorded_at=evidence_a.evaluated_at + timedelta(minutes=1),
        previous=None,
    )
    authorization_owner.value = auth_a
    repository.now = auth_a.recorded_at + timedelta(seconds=1)
    event_a = use_case.execute(_family_command(auth_a))

    auth_b = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence_b,
        sequence=2,
        recorded_at=event_a.recorded_at + timedelta(minutes=1),
        previous=event_a,
    )
    authorization_owner.value = auth_b
    repository.now = auth_b.recorded_at + timedelta(seconds=1)
    event_b = use_case.execute(_family_command(auth_b))
    rollback = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.ROLLBACK,
        subject=evidence_b,
        target=evidence_a,
        sequence=3,
        recorded_at=event_b.recorded_at + timedelta(minutes=1),
        previous=event_b,
    )
    authorization_owner.value = rollback
    repository.now = rollback.recorded_at + timedelta(seconds=1)
    rolled_back = use_case.execute(_family_command(rollback))

    state = derive_r7_family_lifecycle_state(
        tuple(repository.stream),
        evaluated_at=rolled_back.recorded_at,
    )
    assert state.status is R7FamilyLifecycleStatus.ROLLED_BACK
    assert state.active_result_ref == evidence_a.result_ref
    expected_rollback_reads = [
        (
            R7FamilyResultIdRef(result_b.result_id, result_b.result_version),
            rollback.issued_at,
        ),
        (
            R7FamilyResultIdRef(result_a.result_id, result_a.result_version),
            rollback.issued_at,
        ),
    ]
    assert result_owner.calls[-6:-4] == expected_rollback_reads
    expected_current_reads = [
        (expected_rollback_reads[0][0], rolled_back.recorded_at),
        (expected_rollback_reads[1][0], rolled_back.recorded_at),
    ]
    assert result_owner.calls[-4:-2] == expected_current_reads
    assert result_owner.calls[-2:] == expected_current_reads
    assert local_owner.calls[-6:] == result_owner.calls[-6:]
    assert authorization_owner.calls[-2:] == [
        rollback.recorded_at,
        rolled_back.recorded_at,
    ]


def test_application_allows_retired_cleanup_but_never_activation() -> None:
    result = _result("app-retired")
    use_case, _, local_owner, authorization_owner, repository = _application_fixture(result)
    promoted = _evidence(result)
    family = R7ResultFamilyIdentity.from_result(result)
    root_authorization = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=promoted,
        sequence=1,
        recorded_at=promoted.evaluated_at + timedelta(minutes=1),
        previous=None,
    )
    authorization_owner.value = root_authorization
    repository.now = root_authorization.recorded_at + timedelta(seconds=1)
    root = use_case.execute(_family_command(root_authorization))

    retired_stream = _local_stream(result, retire=True)
    local_owner.streams[(result.result_id, result.result_version)] = retired_stream
    retired = _evidence(result, retire=True, as_of=retired_stream[-1].recorded_at)
    cleanup = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.RETIRE,
        subject=retired,
        sequence=2,
        recorded_at=root.recorded_at + timedelta(minutes=2),
        previous=root,
    )
    authorization_owner.value = cleanup
    repository.now = cleanup.recorded_at + timedelta(seconds=1)
    cleaned = use_case.execute(_family_command(cleanup))
    assert cleaned.action is R7FamilyLifecycleAction.RETIRE

    fresh_use_case, _, fresh_local, fresh_auth_owner, fresh_repository = _application_fixture(
        result
    )
    fresh_local.streams[(result.result_id, result.result_version)] = retired_stream
    invalid_promotion = _authorization(
        family=family,
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=retired,
        sequence=1,
        recorded_at=retired.evaluated_at + timedelta(minutes=1),
        previous=None,
    )
    fresh_auth_owner.value = invalid_promotion
    fresh_repository.now = invalid_promotion.recorded_at + timedelta(seconds=1)
    with pytest.raises(R7FamilyLifecycleUnavailable, match="cannot activate"):
        fresh_use_case.execute(_family_command(invalid_promotion))
    assert fresh_repository.stream == []
    assert fresh_repository.rolled_back is True


def test_application_rejects_future_cutoff_and_changed_shared_uow() -> None:
    result = _result("app-uow")
    use_case, result_owner, _, authorization_owner, repository = _application_fixture(result)
    evidence = _evidence(result)
    authorization = _authorization(
        family=R7ResultFamilyIdentity.from_result(result),
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence,
        sequence=1,
        recorded_at=evidence.evaluated_at + timedelta(minutes=1),
        previous=None,
    )
    authorization_owner.value = authorization
    command = _family_command(authorization)
    repository.now = command.as_of - timedelta(microseconds=1)
    with pytest.raises(R7FamilyLifecycleUnavailable, match="future"):
        use_case.execute(command)
    assert result_owner.calls == []

    repository.now = command.as_of + timedelta(seconds=1)
    result_owner.unit_of_work_key = "changed-uow"
    with pytest.raises(R7FamilyLifecycleUnavailable, match="units of work|identity"):
        use_case.execute(command)
    assert repository.stream == []


def test_application_blocks_promotion_retired_after_authorization() -> None:
    result = _result("app-retired-after-authorization")
    use_case, _, local_owner, authorization_owner, repository = _application_fixture(result)
    evidence = _evidence(result)
    authorization = _authorization(
        family=R7ResultFamilyIdentity.from_result(result),
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence,
        sequence=1,
        recorded_at=evidence.evaluated_at + timedelta(seconds=30),
        previous=None,
    )
    retired_stream = _local_stream(result, retire=True)
    assert retired_stream[-1].recorded_at > authorization.recorded_at
    local_owner.streams[(result.result_id, result.result_version)] = retired_stream
    authorization_owner.value = authorization
    repository.now = retired_stream[-1].recorded_at + timedelta(seconds=1)

    with pytest.raises(R7FamilyLifecycleUnavailable, match="cannot activate"):
        use_case.execute(_family_command(authorization))
    assert repository.stream == []
    assert repository.rolled_back is True


def test_application_final_reread_blocks_authorization_replacement() -> None:
    result = _result("authorization-race")
    use_case, _, _, authorization_owner, repository = _application_fixture(result)
    evidence = _evidence(result)
    authorization = _authorization(
        family=R7ResultFamilyIdentity.from_result(result),
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence,
        sequence=1,
        recorded_at=evidence.evaluated_at + timedelta(minutes=1),
        previous=None,
    )
    authorization_owner.value = authorization
    authorization_owner.replacement_after_calls = 1
    authorization_owner.replacement = _replace_authorization(authorization)
    repository.now = authorization.recorded_at + timedelta(seconds=1)

    with pytest.raises(R7FamilyLifecycleUnavailable, match="authorization changed"):
        use_case.execute(_family_command(authorization))
    assert repository.stream == []
    assert repository.append_calls == 0


def test_application_final_owner_reread_blocks_local_retirement_window() -> None:
    result = _result("local-retirement-race")
    use_case, _, local_owner, authorization_owner, repository = _application_fixture(result)
    evidence = _evidence(result)
    authorization = _authorization(
        family=R7ResultFamilyIdentity.from_result(result),
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence,
        sequence=1,
        recorded_at=evidence.evaluated_at + timedelta(seconds=30),
        previous=None,
    )
    retired_stream = _local_stream(result, retire=True)
    local_owner.replacement_after_load_calls = 2
    local_owner.replacement_stream = retired_stream
    authorization_owner.value = authorization
    repository.now = retired_stream[-1].recorded_at + timedelta(seconds=1)

    with pytest.raises(R7FamilyLifecycleUnavailable, match="owner graph"):
        use_case.execute(_family_command(authorization))
    assert repository.stream == []
    assert repository.append_calls == 0


def test_application_final_owner_reread_compares_result_content_identity() -> None:
    result = _result("result-content-race")
    use_case, result_owner, _, authorization_owner, repository = _application_fixture(result)
    evidence = _evidence(result)
    authorization = _authorization(
        family=R7ResultFamilyIdentity.from_result(result),
        action=R7FamilyLifecycleAction.PROMOTE,
        subject=evidence,
        sequence=1,
        recorded_at=evidence.evaluated_at + timedelta(minutes=1),
        previous=None,
    )
    graph = make_evidence_graph()
    replacement = materialize_persisted_r7_research_result(
        result_id=result.result_id,
        result_version=result.result_version,
        policy_record=make_policy_record(),
        evidence_graph=graph,
        evaluated_at=graph.evaluated_at,
        recorded_at=result.recorded_at + timedelta(microseconds=1),
    )
    assert replacement.content_hash != result.content_hash
    result_owner.replacement_after_calls = 2
    result_owner.replacement = replacement
    authorization_owner.value = authorization
    repository.now = authorization.recorded_at + timedelta(seconds=1)

    with pytest.raises(R7FamilyLifecycleUnavailable, match="owner graph"):
        use_case.execute(_family_command(authorization))
    assert repository.stream == []
    assert repository.append_calls == 0
