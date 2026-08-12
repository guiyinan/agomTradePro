"""Application owner-boundary tests for R6 activation and exact rollback."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from apps.research.application.state_model_activation import (
    ApplyR6Activation,
    ApplyR6ActivationCommand,
    GetActiveR6StateModel,
    R6ActivationCorruption,
    R6ActivationUnavailable,
    R6ActiveStateModelProjection,
    R6PersistedActivationEvent,
)
from apps.research.application.state_model_monitoring import ActiveR6QualificationEvidence
from apps.research.domain.state_model_activation import (
    R6ActivationAction,
    R6ActivationApproval,
    R6ActivationApprovalOutcome,
    R6ActivationApprovalRef,
    R6ActivationAuthorization,
    R6ActivationAuthorizationRef,
    R6ActivationEvent,
    R6ActivationScope,
    R6ActivationScopeRef,
    R6MonitoringActivationEvidence,
    R6MonitoringActivationRef,
    R6MonitoringActivationStatus,
    create_r6_activation_event,
)
from apps.research.domain.state_model_qualification_lifecycle import R6QualificationRef

NOW = datetime(2026, 8, 9, 12, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64


@dataclass
class MutableClock:
    """Deterministic trusted server clock."""

    value: datetime = NOW

    def now(self) -> datetime:
        """Return the configured aware time."""

        return self.value


@dataclass
class ApprovalProvider:
    """Exact canonical activation-approval provider double."""

    items: dict[R6ActivationApprovalRef, object]
    unit_of_work_key: str = "research:test-uow"

    def get_exact(
        self,
        *,
        approval_ref: R6ActivationApprovalRef,
        as_of: datetime,
    ) -> R6ActivationApproval | None:
        """Return the item stored under the exact reference."""

        item = self.items.get(approval_ref)
        return item if isinstance(item, R6ActivationApproval) else item  # type: ignore[return-value]


@dataclass
class QualificationProvider:
    """Exact active qualification owner double."""

    items: dict[R6QualificationRef, object]
    unit_of_work_key: str = "research:test-uow"

    def get_exact_active(
        self,
        *,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> ActiveR6QualificationEvidence | None:
        """Return the item stored under the exact reference."""

        item = self.items.get(qualification_ref)
        return item if isinstance(item, ActiveR6QualificationEvidence) else item  # type: ignore[return-value]


@dataclass
class MonitoringProvider:
    """Exact persisted monitoring projection owner double."""

    items: dict[R6MonitoringActivationRef, object]
    unit_of_work_key: str = "research:test-uow"

    def get_exact(
        self,
        *,
        monitoring_ref: R6MonitoringActivationRef,
        as_of: datetime,
    ) -> R6MonitoringActivationEvidence | None:
        """Return the item stored under the exact reference."""

        item = self.items.get(monitoring_ref)
        return item if isinstance(item, R6MonitoringActivationEvidence) else item  # type: ignore[return-value]


@dataclass
class AuthorizationProvider:
    """Exact manual transition-authorization provider double."""

    items: dict[R6ActivationAuthorizationRef, object]
    unit_of_work_key: str = "research:test-uow"

    def get_exact(
        self,
        *,
        authorization_ref: R6ActivationAuthorizationRef,
        scope_ref: R6ActivationScopeRef,
        action: R6ActivationAction,
        subject: R6ActivationApprovalRef,
        rollback_target: R6ActivationApprovalRef | None,
        as_of: datetime,
    ) -> R6ActivationAuthorization | None:
        """Return the item stored under the exact reference."""

        item = self.items.get(authorization_ref)
        return item if isinstance(item, R6ActivationAuthorization) else item  # type: ignore[return-value]


@dataclass
class MemoryRepository:
    """Append-only in-memory repository Protocol double."""

    streams: dict[R6ActivationScopeRef, list[R6ActivationEvent]] = field(default_factory=dict)
    unit_of_work_key: str = "research:test-uow"

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Rollback the in-memory stream when the use case exits with an error."""

        before = {scope_ref: list(events) for scope_ref, events in self.streams.items()}
        try:
            yield
        except Exception:
            self.streams = before
            raise

    def load_stream(
        self,
        *,
        scope_ref: R6ActivationScopeRef,
        as_of: datetime,
    ) -> tuple[R6ActivationEvent, ...]:
        """Return the exact PIT prefix for one scope."""

        return tuple(
            event for event in self.streams.get(scope_ref, []) if event.recorded_at <= as_of
        )

    def get_by_authorization(
        self,
        *,
        authorization_ref: R6ActivationAuthorizationRef,
    ) -> R6PersistedActivationEvent | None:
        """Return the unique event for one authorization identity."""

        matches = [
            event
            for stream in self.streams.values()
            for event in stream
            if (event.authorization_id, event.authorization_version)
            == (
                authorization_ref.authorization_id,
                authorization_ref.authorization_version,
            )
        ]
        assert len(matches) <= 1
        if not matches:
            return None
        record = object.__new__(R6PersistedActivationEvent)
        object.__setattr__(record, "event", matches[0])
        object.__setattr__(record, "ledger_recorded_at", matches[0].recorded_at)
        return record

    def append_event(
        self,
        *,
        authorization: R6ActivationAuthorization,
        event: R6ActivationEvent,
    ) -> R6ActivationEvent:
        """Append one immutable event."""

        assert event.authorization_hash == authorization.content_hash
        self.streams.setdefault(event.scope_ref, []).append(event)
        return event


@dataclass(frozen=True)
class OwnerGraph:
    """One complete exact owner graph for an approved candidate."""

    qualification: ActiveR6QualificationEvidence
    monitoring: R6MonitoringActivationEvidence
    approval: R6ActivationApproval


def _scope() -> R6ActivationScope:
    return R6ActivationScope(
        scope_id="r6-state-model-advisory",
        scope_version="scope.v1",
        purpose="state-model-advisory",
        label_protocol_version="labels.v1",
    )


def _graph(
    suffix: str,
    *,
    status: R6MonitoringActivationStatus = R6MonitoringActivationStatus.HEALTHY,
    evaluated_at: datetime = NOW - timedelta(hours=2),
    maximum_age_seconds: int = 86_400,
) -> OwnerGraph:
    qualification_ref = R6QualificationRef(
        assessment_id=f"qualification-{suffix}",
        assessment_hash=HASH_A if suffix == "a" else HASH_B,
    )
    qualification = ActiveR6QualificationEvidence(
        qualification_ref=qualification_ref,
        candidate_id=f"candidate-{suffix}",
        candidate_version="candidate.v1",
        assessed_at=NOW - timedelta(days=3),
        known_at=NOW - timedelta(days=2),
        research_only=True,
        must_not_use_for_decision=True,
        must_not_replace_regime=True,
    )
    monitoring = R6MonitoringActivationEvidence(
        assessment_id=f"monitoring-{suffix}",
        assessment_hash=HASH_B if suffix == "a" else HASH_A,
        qualification_ref=qualification_ref,
        policy_id="monitor-policy",
        policy_version="policy.v1",
        policy_hash=HASH_A,
        label_protocol_version="labels.v1",
        label_set_hash=HASH_B,
        status=status,
        evaluated_at=evaluated_at,
        recorded_at=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(days=7),
        owner="research",
        evidence_ref=f"research:r6-monitoring:{suffix}",
        retirement_review_required=(
            status is R6MonitoringActivationStatus.RETIREMENT_REVIEW_REQUIRED
        ),
    )
    approval = R6ActivationApproval(
        approval_id=f"activation-{suffix}",
        approval_version="approval.v1",
        scope=_scope(),
        qualification_ref=qualification_ref,
        active_qualification_hash=qualification.content_hash,
        candidate_id=qualification.candidate_id,
        candidate_version=qualification.candidate_version,
        monitoring_ref=monitoring.ref,
        monitoring_evidence_hash=monitoring.content_hash,
        required_monitoring_policy_id=monitoring.policy_id,
        required_monitoring_policy_version=monitoring.policy_version,
        required_monitoring_policy_hash=monitoring.policy_hash,
        required_label_protocol_version=monitoring.label_protocol_version,
        required_label_set_hash=monitoring.label_set_hash,
        maximum_monitoring_age_seconds=maximum_age_seconds,
        outcome=R6ActivationApprovalOutcome.APPROVED,
        owner="research",
        decided_at=NOW - timedelta(minutes=30),
        recorded_at=NOW - timedelta(minutes=20),
        valid_until=NOW + timedelta(days=2),
        reason_codes=("qualified_and_healthy",),
        evidence_ref=f"research:r6-activation:{suffix}",
    )
    return OwnerGraph(qualification, monitoring, approval)


def _authorization(
    suffix: str,
    *,
    action: R6ActivationAction,
    subject: R6ActivationApproval,
    sequence: int,
    target: R6ActivationApproval | None = None,
    expected_previous_event_hash: str | None = None,
    issued_at_override: datetime | None = None,
) -> R6ActivationAuthorization:
    recorded_at = NOW - timedelta(minutes=4) + timedelta(minutes=(sequence - 1) * 10)
    return R6ActivationAuthorization(
        authorization_id=f"authorization-{suffix}",
        authorization_version="authorization.v1",
        event_id=f"event-{suffix}",
        event_version="event.v1",
        scope_ref=subject.scope_ref,
        action=action,
        subject=subject.ref,
        rollback_target=None if target is None else target.ref,
        expected_sequence=sequence,
        expected_previous_event_hash=expected_previous_event_hash,
        owner="research",
        issued_at=issued_at_override or recorded_at - timedelta(minutes=1),
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(hours=1),
        reason_codes=(f"manual_{action.value}",),
        evidence_ref=f"research:r6-activation-authorization:{suffix}",
    )


def _runtime(
    *graphs: OwnerGraph,
    authorizations: tuple[R6ActivationAuthorization, ...],
) -> tuple[
    ApplyR6Activation,
    GetActiveR6StateModel,
    ApprovalProvider,
    QualificationProvider,
    MonitoringProvider,
    AuthorizationProvider,
    MemoryRepository,
    MutableClock,
]:
    approvals = ApprovalProvider({item.approval.ref: item.approval for item in graphs})
    qualifications = QualificationProvider(
        {item.qualification.qualification_ref: item.qualification for item in graphs}
    )
    monitoring = MonitoringProvider({item.monitoring.ref: item.monitoring for item in graphs})
    authorization_provider = AuthorizationProvider({item.ref: item for item in authorizations})
    repository = MemoryRepository()
    clock = MutableClock()
    apply = ApplyR6Activation(
        approval_provider=approvals,
        qualification_provider=qualifications,
        monitoring_provider=monitoring,
        authorization_provider=authorization_provider,
        repository=repository,
        clock=clock,
    )
    active = GetActiveR6StateModel(
        approval_provider=approvals,
        qualification_provider=qualifications,
        monitoring_provider=monitoring,
        repository=repository,
        clock=clock,
    )
    return (
        apply,
        active,
        approvals,
        qualifications,
        monitoring,
        authorization_provider,
        repository,
        clock,
    )


def _command(
    authorization: R6ActivationAuthorization,
) -> ApplyR6ActivationCommand:
    return ApplyR6ActivationCommand(
        scope_ref=authorization.scope_ref,
        action=authorization.action,
        subject=authorization.subject,
        rollback_target=authorization.rollback_target,
        authorization_ref=authorization.ref,
    )


def test_exact_owner_graph_activates_and_rolls_back_without_consumer_authority() -> None:
    """A→B→A revalidates exact owners and yields a non-consuming active projection."""

    graph_a = _graph("a")
    graph_b = _graph("b")
    activate_a = _authorization(
        "activate-a",
        action=R6ActivationAction.ACTIVATE,
        subject=graph_a.approval,
        sequence=1,
    )
    expected_a = create_r6_activation_event(
        authorization=activate_a,
        previous_events=(),
        applied_at=NOW,
    )
    activate_b = _authorization(
        "activate-b",
        action=R6ActivationAction.ACTIVATE,
        subject=graph_b.approval,
        sequence=2,
        expected_previous_event_hash=expected_a.content_hash,
    )
    expected_b = create_r6_activation_event(
        authorization=activate_b,
        previous_events=(expected_a,),
        applied_at=NOW + timedelta(minutes=10),
    )
    rollback = _authorization(
        "rollback-b-to-a",
        action=R6ActivationAction.ROLLBACK,
        subject=graph_b.approval,
        sequence=3,
        target=graph_a.approval,
        expected_previous_event_hash=expected_b.content_hash,
    )
    apply, active, *_, clock = _runtime(
        graph_a,
        graph_b,
        authorizations=(activate_a, activate_b, rollback),
    )

    apply.execute(_command(activate_a))
    clock.value = NOW + timedelta(minutes=10)
    apply.execute(_command(activate_b))
    clock.value = NOW + timedelta(minutes=20)
    applied_rollback = apply.execute(_command(rollback))
    projection = active.get_active(
        scope_ref=graph_a.approval.scope_ref,
        as_of=clock.value,
    )

    assert applied_rollback.rollback_target == graph_a.approval.ref
    assert projection is not None
    assert projection.approval == graph_a.approval
    assert projection.qualification == graph_a.qualification
    assert projection.monitoring == graph_a.monitoring
    assert projection.head_event_hash == applied_rollback.content_hash
    assert projection.must_not_replace_regime is True
    assert projection.must_not_publish_current is True
    assert projection.must_not_use_for_decision is True
    assert projection.must_not_execute is True


@pytest.mark.parametrize(
    "graph",
    [
        _graph("breached", status=R6MonitoringActivationStatus.BREACHED),
        _graph(
            "stale",
            evaluated_at=NOW - timedelta(days=2),
            maximum_age_seconds=86_400,
        ),
    ],
)
def test_nonhealthy_or_stale_monitoring_blocks_before_append(graph: OwnerGraph) -> None:
    """Activation never turns breached or stale monitoring into an active model."""

    authorization = _authorization(
        "blocked",
        action=R6ActivationAction.ACTIVATE,
        subject=graph.approval,
        sequence=1,
    )
    apply, _, *_, repository, _ = _runtime(
        graph,
        authorizations=(authorization,),
    )

    with pytest.raises(R6ActivationUnavailable, match="monitoring"):
        apply.execute(_command(authorization))

    assert repository.streams == {}


def test_owner_substitution_and_malformed_live_seal_are_normalized() -> None:
    """Provider substitution and a frozen-object hash attack fail closed."""

    graph_a = _graph("a")
    graph_b = _graph("b")
    authorization = _authorization(
        "activate-a",
        action=R6ActivationAction.ACTIVATE,
        subject=graph_a.approval,
        sequence=1,
    )
    apply, _, approvals, *_rest = _runtime(
        graph_a,
        graph_b,
        authorizations=(authorization,),
    )
    approvals.items[graph_a.approval.ref] = graph_b.approval
    with pytest.raises(R6ActivationUnavailable, match="approval"):
        apply.execute(_command(authorization))

    approvals.items[graph_a.approval.ref] = graph_a.approval
    object.__setattr__(graph_a.approval, "content_hash", object())
    with pytest.raises(R6ActivationUnavailable, match="approval"):
        apply.execute(_command(authorization))


def test_manual_retire_can_close_stale_active_state_without_current_graph() -> None:
    """Expired evidence cannot deadlock a manual retirement of the active stack."""

    graph = _graph("a")
    activate = _authorization(
        "activate",
        action=R6ActivationAction.ACTIVATE,
        subject=graph.approval,
        sequence=1,
    )
    expected_activate = create_r6_activation_event(
        authorization=activate,
        previous_events=(),
        applied_at=NOW,
    )
    retire = _authorization(
        "retire",
        action=R6ActivationAction.RETIRE,
        subject=graph.approval,
        sequence=2,
        expected_previous_event_hash=expected_activate.content_hash,
    )
    (
        apply,
        active,
        approvals,
        qualifications,
        monitoring,
        _,
        repository,
        clock,
    ) = _runtime(graph, authorizations=(activate, retire))
    apply.execute(_command(activate))
    clock.value = NOW + timedelta(minutes=10)
    approvals.items.clear()
    qualifications.items.clear()
    monitoring.items.clear()

    retired = apply.execute(_command(retire))

    assert retired.action is R6ActivationAction.RETIRE
    assert len(repository.streams[graph.approval.scope_ref]) == 2
    assert active.get_active(scope_ref=graph.approval.scope_ref, as_of=clock.value) is None


def test_future_active_query_and_cross_uow_provider_fail_closed() -> None:
    """Caller-selected future time and fake transaction ownership never publish active."""

    graph = _graph("a")
    authorization = _authorization(
        "activate",
        action=R6ActivationAction.ACTIVATE,
        subject=graph.approval,
        sequence=1,
    )
    apply, active, approvals, qualifications, monitoring, auths, repository, _ = _runtime(
        graph,
        authorizations=(authorization,),
    )
    apply.execute(_command(authorization))

    assert (
        active.get_active(
            scope_ref=graph.approval.scope_ref,
            as_of=NOW + timedelta(microseconds=1),
        )
        is None
    )
    monitoring.unit_of_work_key = "research:attacker-uow"
    with pytest.raises(ValueError, match="different units of work"):
        ApplyR6Activation(
            approval_provider=approvals,
            qualification_provider=qualifications,
            monitoring_provider=monitoring,
            authorization_provider=auths,
            repository=repository,
            clock=MutableClock(),
        )


def test_future_idempotency_winner_is_corruption_not_a_replay() -> None:
    """An authorization lookup cannot replay an event not yet known to the server."""

    graph = _graph("a")
    authorization = _authorization(
        "future-winner",
        action=R6ActivationAction.ACTIVATE,
        subject=graph.approval,
        sequence=1,
    )
    apply, _, *_, repository, _ = _runtime(
        graph,
        authorizations=(authorization,),
    )
    future = create_r6_activation_event(
        authorization=authorization,
        previous_events=(),
        applied_at=NOW + timedelta(microseconds=1),
    )
    repository.streams[graph.approval.scope_ref] = [future]

    with pytest.raises(R6ActivationCorruption, match="future evidence"):
        apply.execute(_command(authorization))


def test_exact_canonical_existing_winner_replays_idempotently() -> None:
    """A winner replays only after its complete canonical prefix is derived again."""

    graph = _graph("exact-replay")
    authorization = _authorization(
        "exact-replay",
        action=R6ActivationAction.ACTIVATE,
        subject=graph.approval,
        sequence=1,
    )
    apply, _, *_, repository, _ = _runtime(
        graph,
        authorizations=(authorization,),
    )

    first = apply.execute(_command(authorization))
    replayed = apply.execute(_command(authorization))

    assert replayed == first
    assert repository.streams[graph.approval.scope_ref] == [first]


def test_orphan_existing_winner_cannot_bypass_canonical_stream_replay() -> None:
    """A sealed sequence-two winner is corrupt when its canonical prefix is absent."""

    graph = _graph("orphan")
    authorization = _authorization(
        "orphan-sequence-two",
        action=R6ActivationAction.ACTIVATE,
        subject=graph.approval,
        sequence=2,
        expected_previous_event_hash=HASH_A,
    )
    apply, _, *_, repository, clock = _runtime(
        graph,
        authorizations=(authorization,),
    )
    clock.value = NOW + timedelta(minutes=10)
    orphan = R6ActivationEvent(
        event_id=authorization.event_id,
        event_version=authorization.event_version,
        scope_ref=authorization.scope_ref,
        action=authorization.action,
        subject=authorization.subject,
        rollback_target=authorization.rollback_target,
        authorization_id=authorization.authorization_id,
        authorization_version=authorization.authorization_version,
        authorization_hash=authorization.content_hash,
        sequence=authorization.expected_sequence,
        occurred_at=clock.value,
        recorded_at=clock.value,
        previous_event_hash=authorization.expected_previous_event_hash,
        reason_codes=authorization.reason_codes,
    )
    repository.streams[graph.approval.scope_ref] = [orphan]

    with pytest.raises(R6ActivationCorruption, match="exact replay"):
        apply.execute(_command(authorization))


def test_existing_winner_seal_is_checked_before_its_recorded_clock() -> None:
    """A frozen-object seal attack cannot supply the idempotency cutoff."""

    graph = _graph("winner-seal")
    authorization = _authorization(
        "winner-seal",
        action=R6ActivationAction.ACTIVATE,
        subject=graph.approval,
        sequence=1,
    )
    apply, _, *_, repository, _ = _runtime(
        graph,
        authorizations=(authorization,),
    )
    winner = create_r6_activation_event(
        authorization=authorization,
        previous_events=(),
        applied_at=NOW,
    )
    repository.streams[graph.approval.scope_ref] = [winner]
    object.__setattr__(winner, "content_hash", object())

    with pytest.raises(R6ActivationCorruption, match="malformed"):
        apply.execute(_command(authorization))


def test_constructed_runtime_rejects_later_shared_uow_identity_drift() -> None:
    """Even coordinated key replacement cannot escape the captured UoW identity."""

    graph = _graph("uow-drift")
    authorization = _authorization(
        "uow-drift",
        action=R6ActivationAction.ACTIVATE,
        subject=graph.approval,
        sequence=1,
    )
    apply, _, approvals, qualifications, monitoring, auths, repository, _ = _runtime(
        graph,
        authorizations=(authorization,),
    )
    for provider in (approvals, qualifications, monitoring, auths, repository):
        provider.unit_of_work_key = "research:replacement-uow"

    with pytest.raises(R6ActivationUnavailable, match="identity changed"):
        apply.execute(_command(authorization))
    assert repository.streams == {}

    active_graph = _graph("active-uow-drift")
    active_authorization = _authorization(
        "active-uow-drift",
        action=R6ActivationAction.ACTIVATE,
        subject=active_graph.approval,
        sequence=1,
    )
    (
        active_apply,
        active_query,
        active_approvals,
        active_qualifications,
        active_monitoring,
        _,
        active_repository,
        _,
    ) = _runtime(active_graph, authorizations=(active_authorization,))
    active_apply.execute(_command(active_authorization))
    for provider in (
        active_approvals,
        active_qualifications,
        active_monitoring,
        active_repository,
    ):
        provider.unit_of_work_key = "research:replacement-query-uow"
    assert (
        active_query.get_active(
            scope_ref=active_graph.approval.scope_ref,
            as_of=NOW,
        )
        is None
    )


def test_owner_overflow_and_repository_failure_are_normalized_and_rolled_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed owner math and a post-write repository error remain fail-closed."""

    boundary_graph = _graph("boundary-error")
    boundary_authorization = _authorization(
        "boundary-error",
        action=R6ActivationAction.ACTIVATE,
        subject=boundary_graph.approval,
        sequence=1,
    )
    (
        boundary_apply,
        _,
        boundary_approvals,
        _,
        _,
        _,
        boundary_repository,
        boundary_clock,
    ) = _runtime(boundary_graph, authorizations=(boundary_authorization,))

    def unavailable_clock() -> datetime:
        raise RuntimeError("simulated clock failure")

    monkeypatch.setattr(boundary_clock, "now", unavailable_clock)
    with pytest.raises(R6ActivationUnavailable, match="server clock"):
        boundary_apply.execute(_command(boundary_authorization))
    assert boundary_repository.streams == {}

    monkeypatch.undo()

    def unavailable_approval(**_kwargs: object) -> R6ActivationApproval | None:
        raise RuntimeError("simulated owner failure")

    monkeypatch.setattr(boundary_approvals, "get_exact", unavailable_approval)
    with pytest.raises(R6ActivationUnavailable, match="approval"):
        boundary_apply.execute(_command(boundary_authorization))
    assert boundary_repository.streams == {}

    monkeypatch.undo()

    overflow_graph = _graph("overflow", maximum_age_seconds=10**100)
    overflow_authorization = _authorization(
        "overflow",
        action=R6ActivationAction.ACTIVATE,
        subject=overflow_graph.approval,
        sequence=1,
    )
    overflow_apply, _, *_, overflow_repository, _ = _runtime(
        overflow_graph,
        authorizations=(overflow_authorization,),
    )
    with pytest.raises(R6ActivationUnavailable, match="monitoring"):
        overflow_apply.execute(_command(overflow_authorization))
    assert overflow_repository.streams == {}

    graph = _graph("append-failure")
    authorization = _authorization(
        "append-failure",
        action=R6ActivationAction.ACTIVATE,
        subject=graph.approval,
        sequence=1,
    )
    apply, _, *_, repository, _ = _runtime(
        graph,
        authorizations=(authorization,),
    )

    def append_then_fail(
        *,
        authorization: R6ActivationAuthorization,
        event: R6ActivationEvent,
    ) -> R6ActivationEvent:
        assert event.authorization_hash == authorization.content_hash
        repository.streams.setdefault(event.scope_ref, []).append(event)
        raise RuntimeError("simulated repository failure")

    monkeypatch.setattr(repository, "append_event", append_then_fail)
    with pytest.raises(R6ActivationCorruption, match="event append"):
        apply.execute(_command(authorization))
    assert repository.streams == {}


def test_projection_cannot_be_self_minted_without_replayed_state() -> None:
    """A caller cannot construct an active-looking projection from arbitrary evidence."""

    graph = _graph("projection-mint")
    with pytest.raises(ValueError, match="exact replay minting"):
        R6ActiveStateModelProjection(
            scope_ref=graph.approval.scope_ref,
            approval=graph.approval,
            qualification=graph.qualification,
            monitoring=graph.monitoring,
            head_event_hash=HASH_A,
            _mint_token=object(),
        )
