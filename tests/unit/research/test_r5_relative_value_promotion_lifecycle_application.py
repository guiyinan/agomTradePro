"""ID-only lifecycle orchestration and PIT active-provider tests for R5."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import pytest

from apps.fixed_income.application.relative_value_persistence import (
    R5PersistedRelativeValueBundle,
)
from apps.research.application.r5_relative_value_promotion_decision import (
    R5RelativeValueDecisionAuthorization,
    R5RelativeValuePromotionDecisionBundle,
    R5RelativeValuePromotionEvidenceError,
    R5RelativeValuePromotionRef,
)
from apps.research.application.r5_relative_value_promotion_lifecycle import (
    ApplyR5RelativeValueLifecycleCommand,
    ApplyR5RelativeValuePromotionLifecycle,
    GetActiveR5RelativeValuePromotion,
    R5RelativeValueLifecycleAction,
    R5RelativeValueLifecycleAuthorizationEvidence,
    R5RelativeValueLifecycleEventBundle,
    R5RelativeValueLifecycleScopeRef,
)
from apps.research.domain.r5_relative_value_portfolio_outcome import (
    R5PortfolioOutcomeSeal,
)
from apps.research.domain.r5_relative_value_promotion_decision import (
    create_r5_relative_value_promotion_decision,
    r5_relative_value_promotion_decision_valid_until,
)
from apps.research.domain.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueLifecycleAuthorization,
    R5RelativeValueLifecycleEvent,
    R5RelativeValueLifecycleEventType,
    create_r5_relative_value_lifecycle_event,
    create_r5_relative_value_lifecycle_root,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionPolicy,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
)
from tests.unit.research.r5_relative_value_promotion_factories import (
    BASE_TIME,
    make_observations,
    make_persisted_bundles,
    make_policy,
    make_trial,
)


@dataclass
class _PolicyProvider:
    item: R5RelativeValuePromotionPolicy | None
    unit_of_work_key: str = "uow"

    def get_exact(
        self,
        policy_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionPolicy | None:
        return self.item


@dataclass
class _TrialProvider:
    item: R5RelativeValuePromotionTrial | None
    unit_of_work_key: str = "uow"

    def get_exact(
        self,
        trial_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionTrial | None:
        return self.item


class _RecordProvider:
    unit_of_work_key = "uow"

    def __init__(
        self,
        bundles: tuple[R5PersistedRelativeValueBundle, ...],
    ) -> None:
        self._items = {
            (
                item.result.result_id,
                item.result.result_version,
                item.result.record_hash,
            ): item
            for item in bundles
        }
        self.calls = 0

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_record_hash: str,
        as_of: datetime,
    ) -> R5PersistedRelativeValueBundle | None:
        self.calls += 1
        return self._items.get((result_id, result_version, expected_record_hash))


class _OutcomeProvider:
    unit_of_work_key = "uow"

    def __init__(self, outcomes: tuple[R5PortfolioOutcomeSeal, ...]) -> None:
        self._items = {
            (
                item.outcome_id,
                item.outcome_version,
                item.owner_record_hash,
            ): item
            for item in outcomes
        }
        self.calls = 0

    def get_exact(
        self,
        *,
        outcome_ref: R5RelativeValuePromotionRef,
        expected_owner_record_hash: str,
        as_of: datetime,
    ) -> R5PortfolioOutcomeSeal | None:
        self.calls += 1
        return self._items.get(
            (
                outcome_ref.stable_id,
                outcome_ref.version,
                expected_owner_record_hash,
            )
        )


class _SubstitutingOutcomeProvider:
    unit_of_work_key = "uow"

    def __init__(self, item: R5PortfolioOutcomeSeal) -> None:
        self._item = item

    def get_exact(
        self,
        *,
        outcome_ref: R5RelativeValuePromotionRef,
        expected_owner_record_hash: str,
        as_of: datetime,
    ) -> R5PortfolioOutcomeSeal | None:
        return self._item


class _DecisionAuthorizationProvider:
    unit_of_work_key = "uow"

    def __init__(
        self,
        authorizations: tuple[R5RelativeValueDecisionAuthorization, ...],
    ) -> None:
        self._items = {
            (item.authorization_id, item.authorization_version): item for item in authorizations
        }

    def get_exact(
        self,
        *,
        authorization_ref: R5RelativeValuePromotionRef,
        policy_ref: R5RelativeValuePromotionRef,
        trial_ref: R5RelativeValuePromotionRef,
        as_of: datetime,
    ) -> R5RelativeValueDecisionAuthorization | None:
        return self._items.get((authorization_ref.stable_id, authorization_ref.version))


class _LifecycleAuthorizationProvider:
    unit_of_work_key = "uow"

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], R5RelativeValueLifecycleAuthorizationEvidence] = {}

    def add(self, evidence: R5RelativeValueLifecycleAuthorizationEvidence) -> None:
        self.items[(evidence.evidence_id, evidence.evidence_version)] = evidence

    def get_exact(
        self,
        *,
        authorization_ref: R5RelativeValuePromotionRef,
        scope_ref: R5RelativeValueLifecycleScopeRef,
        action: R5RelativeValueLifecycleAction,
        decision_ref: R5RelativeValuePromotionRef,
        rollback_target_ref: R5RelativeValuePromotionRef | None,
    ) -> R5RelativeValueLifecycleAuthorizationEvidence | None:
        return self.items.get((authorization_ref.stable_id, authorization_ref.version))


@dataclass(frozen=True)
class _Clock:
    item: datetime = BASE_TIME + timedelta(days=10)

    def now(self) -> datetime:
        return self.item


class _Repository:
    unit_of_work_key = "uow"

    def __init__(
        self,
        decisions: tuple[R5RelativeValuePromotionDecisionBundle, ...],
    ) -> None:
        self._decisions = {
            (item.decision.decision_id, item.decision.decision_version): item for item in decisions
        }
        self.events: list[R5RelativeValueLifecycleEventBundle] = []
        self.winners: dict[tuple[str, str], R5RelativeValueLifecycleEventBundle] = {}
        self.stream_override: tuple[R5RelativeValueLifecycleEventBundle, ...] | None = None
        self.active = False

    @contextmanager
    def atomic(self) -> Iterator[None]:
        assert not self.active
        self.active = True
        try:
            yield
        finally:
            self.active = False

    def get_decision_bundle(
        self,
        decision_ref: R5RelativeValuePromotionRef,
        *,
        as_of: datetime,
    ) -> R5RelativeValuePromotionDecisionBundle | None:
        item = self._decisions.get((decision_ref.stable_id, decision_ref.version))
        if item is None or item.decision.recorded_at > as_of:
            return None
        return item

    def load_lifecycle_stream(
        self,
        scope_ref: R5RelativeValueLifecycleScopeRef,
    ) -> tuple[R5RelativeValueLifecycleEventBundle, ...]:
        if self.stream_override is not None:
            return self.stream_override
        return tuple(self.events)

    def get_event_bundle_by_authorization(
        self,
        authorization_ref: R5RelativeValuePromotionRef,
    ) -> R5RelativeValueLifecycleEventBundle | None:
        return self.winners.get((authorization_ref.stable_id, authorization_ref.version))

    def append_lifecycle_event_bundle(
        self,
        bundle: R5RelativeValueLifecycleEventBundle,
    ) -> R5RelativeValueLifecycleEventBundle:
        assert self.active
        evidence = bundle.authorization_evidence
        key = (evidence.evidence_id, evidence.evidence_version)
        existing = self.winners.get(key)
        if existing is not None:
            return existing
        self.events.append(bundle)
        self.winners[key] = bundle
        return bundle


@dataclass(frozen=True)
class _Graph:
    persisted: tuple[
        R5PersistedRelativeValueBundle,
        R5PersistedRelativeValueBundle,
    ]
    policy: R5RelativeValuePromotionPolicy
    trial: R5RelativeValuePromotionTrial
    decisions: tuple[
        R5RelativeValuePromotionDecisionBundle,
        R5RelativeValuePromotionDecisionBundle,
        R5RelativeValuePromotionDecisionBundle,
    ]


@dataclass(frozen=True)
class _Ports:
    policy: _PolicyProvider
    trial: _TrialProvider
    records: _RecordProvider
    outcomes: _OutcomeProvider | _SubstitutingOutcomeProvider
    decisions: _DecisionAuthorizationProvider
    lifecycle: _LifecycleAuthorizationProvider


def _graph(monkeypatch: pytest.MonkeyPatch) -> _Graph:
    persisted = make_persisted_bundles(monkeypatch)
    observations = make_observations(monkeypatch, bundles=persisted)
    policy = make_policy()
    trial = make_trial(monkeypatch, policy=policy, observations=observations)
    bundles: list[R5RelativeValuePromotionDecisionBundle] = []
    for index, minute in enumerate((181, 186, 191), start=1):
        decided_at = BASE_TIME + timedelta(minutes=minute)
        policy_ref = R5RelativeValuePromotionRef(
            policy.policy_id,
            policy.policy_version,
        )
        trial_ref = R5RelativeValuePromotionRef(
            trial.trial_id,
            trial.trial_version,
        )
        authorization = R5RelativeValueDecisionAuthorization.create(
            authorization_version=f"decision-auth-v{index}",
            scope_id=policy.scope.scope_id,
            scope_content_hash=policy.scope.content_hash,
            policy_ref=policy_ref,
            trial_ref=trial_ref,
            issued_at=decided_at - timedelta(minutes=1),
            recorded_at=decided_at,
            decided_at=decided_at,
            decision_recorded_at=decided_at + timedelta(seconds=30),
            decision_valid_until=(
                r5_relative_value_promotion_decision_valid_until(
                    policy=policy,
                    trial=trial,
                    decided_at=decided_at,
                )
            ),
            valid_until=trial.valid_until,
        )
        decision = create_r5_relative_value_promotion_decision(
            policy=policy,
            trial=trial,
            decided_at=decided_at,
            recorded_at=authorization.decision_recorded_at,
        )
        bundles.append(
            R5RelativeValuePromotionDecisionBundle.create(
                decision=decision,
                authorization=authorization,
            )
        )
    return _Graph(
        persisted=persisted,
        policy=policy,
        trial=trial,
        decisions=(bundles[0], bundles[1], bundles[2]),
    )


def _ports(graph: _Graph) -> _Ports:
    return _Ports(
        policy=_PolicyProvider(graph.policy),
        trial=_TrialProvider(graph.trial),
        records=_RecordProvider(graph.persisted),
        outcomes=_OutcomeProvider(
            tuple(item.portfolio_outcome for item in graph.trial.observations)
        ),
        decisions=_DecisionAuthorizationProvider(
            tuple(item.authorization for item in graph.decisions)
        ),
        lifecycle=_LifecycleAuthorizationProvider(),
    )


def _apply(
    ports: _Ports,
    repository: _Repository,
) -> ApplyR5RelativeValuePromotionLifecycle:
    return ApplyR5RelativeValuePromotionLifecycle(
        policy_provider=ports.policy,
        trial_provider=ports.trial,
        owner_record_provider=ports.records,
        portfolio_outcome_provider=ports.outcomes,
        decision_authorization_provider=ports.decisions,
        lifecycle_authorization_provider=ports.lifecycle,
        repository=repository,
    )


def _active(
    ports: _Ports,
    repository: _Repository,
    *,
    clock: _Clock | None = None,
) -> GetActiveR5RelativeValuePromotion:
    return GetActiveR5RelativeValuePromotion(
        policy_provider=ports.policy,
        trial_provider=ports.trial,
        owner_record_provider=ports.records,
        portfolio_outcome_provider=ports.outcomes,
        decision_authorization_provider=ports.decisions,
        repository=repository,
        clock=clock or _Clock(),
    )


def _authorize_event(
    *,
    repository: _Repository,
    decision_bundle: R5RelativeValuePromotionDecisionBundle,
    action: R5RelativeValueLifecycleAction,
    occurred_at: datetime,
    rollback_target: R5RelativeValuePromotionDecisionBundle | None = None,
    previous_events: tuple[R5RelativeValueLifecycleEvent, ...] | None = None,
) -> tuple[
    R5RelativeValueLifecycleAuthorizationEvidence,
    ApplyR5RelativeValueLifecycleCommand,
    R5RelativeValueLifecycleEvent,
]:
    event_type = {
        R5RelativeValueLifecycleAction.PROMOTE: (R5RelativeValueLifecycleEventType.PROMOTED),
        R5RelativeValueLifecycleAction.RETIRE: (R5RelativeValueLifecycleEventType.RETIRED),
        R5RelativeValueLifecycleAction.ROLLBACK: (R5RelativeValueLifecycleEventType.ROLLED_BACK),
    }[action]
    reason_codes = ("research_owner_approved",)
    authorization = R5RelativeValueLifecycleAuthorization.create(
        authorization_version="lifecycle-auth-v1",
        event_type=event_type,
        decision=decision_bundle.decision,
        rollback_target=(None if rollback_target is None else rollback_target.decision),
        reason_codes=reason_codes,
        issued_at=occurred_at - timedelta(seconds=20),
        recorded_at=occurred_at - timedelta(seconds=10),
        valid_until=occurred_at + timedelta(hours=1),
    )
    history = (
        tuple(item.event for item in repository.events)
        if previous_events is None
        else previous_events
    )
    if not history:
        event = create_r5_relative_value_lifecycle_root(
            event_version="event-v1",
            decision=decision_bundle.decision,
            authorization=authorization,
            reason_codes=reason_codes,
            occurred_at=occurred_at,
            recorded_at=occurred_at + timedelta(seconds=5),
        )
    else:
        event = create_r5_relative_value_lifecycle_event(
            event_version="event-v1",
            previous_events=history,
            event_type=event_type,
            decision=decision_bundle.decision,
            rollback_target=(None if rollback_target is None else rollback_target.decision),
            authorization=authorization,
            reason_codes=reason_codes,
            occurred_at=occurred_at,
            recorded_at=occurred_at + timedelta(seconds=5),
        )
    evidence = R5RelativeValueLifecycleAuthorizationEvidence.from_event(
        evidence_version="lifecycle-evidence-v1",
        event=event,
        receipt_recorded_at=occurred_at - timedelta(seconds=5),
    )
    command = ApplyR5RelativeValueLifecycleCommand(
        scope_ref=R5RelativeValueLifecycleScopeRef(decision_bundle.decision.scope.scope_id),
        action=action,
        decision_ref=R5RelativeValuePromotionRef(
            decision_bundle.decision.decision_id,
            decision_bundle.decision.decision_version,
        ),
        authorization_ref=R5RelativeValuePromotionRef(
            evidence.evidence_id,
            evidence.evidence_version,
        ),
        rollback_target_ref=(
            None
            if rollback_target is None
            else R5RelativeValuePromotionRef(
                rollback_target.decision.decision_id,
                rollback_target.decision.decision_version,
            )
        ),
    )
    return evidence, command, event


def test_id_only_promotion_idempotency_and_active_dynamic_reread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One ID-only promotion is appended once and active rereads every owner."""

    graph = _graph(monkeypatch)
    ports = _ports(graph)
    repository = _Repository(graph.decisions)
    decision = graph.decisions[0]
    evidence, command, expected = _authorize_event(
        repository=repository,
        decision_bundle=decision,
        action=R5RelativeValueLifecycleAction.PROMOTE,
        occurred_at=decision.decision.recorded_at + timedelta(minutes=1),
    )
    ports.lifecycle.add(evidence)

    event = _apply(ports, repository).execute(command)
    active = _active(ports, repository).get_active(
        command.scope_ref,
        as_of=event.recorded_at + timedelta(seconds=1),
    )

    assert event == expected
    assert active == decision
    assert set(vars(command)) == {
        "scope_ref",
        "action",
        "decision_ref",
        "authorization_ref",
        "rollback_target_ref",
    }
    assert ports.records.calls == 4
    assert ports.outcomes.calls == 4
    assert _apply(ports, repository).execute(command) == event
    assert len(repository.events) == 1
    with pytest.raises(ValueError, match="content hash|identity"):
        replace(
            evidence,
            event_recorded_at=evidence.event_recorded_at + timedelta(seconds=1),
        )


def test_missing_owner_broken_stream_and_absent_winner_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing Portfolio evidence and non-prefix streams never remain active."""

    graph = _graph(monkeypatch)
    repository = _Repository(graph.decisions)
    ports = _ports(graph)
    first = graph.decisions[0]
    evidence, command, _ = _authorize_event(
        repository=repository,
        decision_bundle=first,
        action=R5RelativeValueLifecycleAction.PROMOTE,
        occurred_at=first.decision.recorded_at + timedelta(minutes=1),
    )
    ports.lifecycle.add(evidence)
    ports = replace(ports, outcomes=_OutcomeProvider(()))
    with pytest.raises(R5RelativeValuePromotionEvidenceError) as missing:
        _apply(ports, repository).execute(command)
    assert missing.value.reason_code == "r5_lifecycle.portfolio_outcome_missing"
    assert not repository.events

    ports = _ports(graph)
    ports.lifecycle.add(evidence)
    _apply(ports, repository).execute(command)
    repository.stream_override = ()
    with pytest.raises(R5RelativeValuePromotionEvidenceError) as absent:
        _apply(ports, repository).execute(command)
    assert absent.value.reason_code == "r5_lifecycle.repository_conflict"
    assert (
        _active(ports, repository).get_active(
            command.scope_ref,
            as_of=evidence.event_recorded_at + timedelta(seconds=1),
        )
        is None
    )


def test_stack_local_rollback_then_expired_retirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rollback is exactly stack[-2], and an expired top can still retire."""

    graph = _graph(monkeypatch)
    ports = _ports(graph)
    repository = _Repository(graph.decisions)
    use_case = _apply(ports, repository)
    commands: list[ApplyR5RelativeValueLifecycleCommand] = []
    for decision_bundle, action_time in (
        (
            graph.decisions[0],
            graph.decisions[0].decision.recorded_at + timedelta(minutes=1),
        ),
        (
            graph.decisions[1],
            graph.decisions[1].decision.recorded_at + timedelta(minutes=1),
        ),
        (
            graph.decisions[2],
            graph.decisions[2].decision.recorded_at + timedelta(minutes=1),
        ),
    ):
        evidence, command, _ = _authorize_event(
            repository=repository,
            decision_bundle=decision_bundle,
            action=R5RelativeValueLifecycleAction.PROMOTE,
            occurred_at=action_time,
        )
        ports.lifecycle.add(evidence)
        use_case.execute(command)
        commands.append(command)

    root_event = repository.events[0].event
    third = graph.decisions[2]
    first = graph.decisions[0]
    alternative_evidence, _, _ = _authorize_event(
        repository=repository,
        decision_bundle=third,
        action=R5RelativeValueLifecycleAction.PROMOTE,
        occurred_at=third.decision.recorded_at + timedelta(seconds=45),
        previous_events=(root_event,),
    )
    alternative_promote = create_r5_relative_value_lifecycle_event(
        event_version=alternative_evidence.event_ref.version,
        previous_events=(root_event,),
        event_type=R5RelativeValueLifecycleEventType.PROMOTED,
        decision=third.decision,
        rollback_target=None,
        authorization=alternative_evidence.authorization,
        reason_codes=alternative_evidence.reason_codes,
        occurred_at=alternative_evidence.occurred_at,
        recorded_at=alternative_evidence.event_recorded_at,
    )
    invalid_at = repository.events[-1].event.recorded_at + timedelta(minutes=1)
    invalid_evidence, invalid_command, _ = _authorize_event(
        repository=repository,
        decision_bundle=third,
        action=R5RelativeValueLifecycleAction.ROLLBACK,
        occurred_at=invalid_at,
        rollback_target=first,
        previous_events=(root_event, alternative_promote),
    )
    ports.lifecycle.add(invalid_evidence)
    with pytest.raises(R5RelativeValuePromotionEvidenceError) as invalid:
        use_case.execute(invalid_command)
    assert invalid.value.reason_code == "r5_lifecycle.transition_invalid"

    second = graph.decisions[1]
    valid_evidence, valid_command, _ = _authorize_event(
        repository=repository,
        decision_bundle=third,
        action=R5RelativeValueLifecycleAction.ROLLBACK,
        occurred_at=invalid_at + timedelta(minutes=1),
        rollback_target=second,
    )
    ports.lifecycle.add(valid_evidence)
    rollback_event = use_case.execute(valid_command)
    active = _active(ports, repository).get_active(
        valid_command.scope_ref,
        as_of=rollback_event.recorded_at + timedelta(seconds=1),
    )
    assert active == second

    retired_at = second.decision.valid_until + timedelta(minutes=1)
    retire_evidence, retire_command, _ = _authorize_event(
        repository=repository,
        decision_bundle=second,
        action=R5RelativeValueLifecycleAction.RETIRE,
        occurred_at=retired_at,
    )
    ports.lifecycle.add(retire_evidence)
    retire_event = use_case.execute(retire_command)
    assert (
        _active(ports, repository).get_active(
            retire_command.scope_ref,
            as_of=retire_event.recorded_at + timedelta(seconds=1),
        )
        is None
    )


def test_uow_scope_auth_reseal_and_full_stream_attacks_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TOCTOU ports, reseals, missing prefixes, forks and scope swaps fail closed."""

    graph = _graph(monkeypatch)
    repository = _Repository(graph.decisions)
    ports = _ports(graph)
    mismatched = replace(
        ports,
        policy=replace(ports.policy, unit_of_work_key="other"),
    )
    with pytest.raises(ValueError, match="units of work"):
        _apply(mismatched, repository)

    first = graph.decisions[0]
    evidence, command, _ = _authorize_event(
        repository=repository,
        decision_bundle=first,
        action=R5RelativeValueLifecycleAction.PROMOTE,
        occurred_at=first.decision.recorded_at + timedelta(minutes=1),
    )
    ports.lifecycle.add(evidence)
    with pytest.raises(ValueError, match="reasons|content hash|identity"):
        replace(evidence, reason_codes=("substituted_reason",))
    with pytest.raises(ValueError, match="content hash|identity"):
        replace(
            evidence,
            event_ref=R5RelativeValuePromotionRef(
                "r5-rv-event:substituted",
                evidence.event_ref.version,
            ),
        )
    use_case = _apply(ports, repository)
    use_case.execute(command)

    cross_scope = replace(
        command,
        scope_ref=R5RelativeValueLifecycleScopeRef("other-scope"),
    )
    with pytest.raises(R5RelativeValuePromotionEvidenceError) as scope_error:
        use_case.execute(cross_scope)
    assert scope_error.value.reason_code == "r5_lifecycle.evidence_substituted"

    second = graph.decisions[1]
    second_evidence, second_command, _ = _authorize_event(
        repository=repository,
        decision_bundle=second,
        action=R5RelativeValueLifecycleAction.PROMOTE,
        occurred_at=second.decision.recorded_at + timedelta(minutes=1),
    )
    ports.lifecycle.add(second_evidence)
    use_case.execute(second_command)
    root_bundle, second_bundle = repository.events
    repository.stream_override = (second_bundle,)
    assert (
        _active(ports, repository).get_active(
            command.scope_ref,
            as_of=second_bundle.event.recorded_at + timedelta(seconds=1),
        )
        is None
    )

    third = graph.decisions[2]
    fork_evidence, _, fork_event = _authorize_event(
        repository=repository,
        decision_bundle=third,
        action=R5RelativeValueLifecycleAction.PROMOTE,
        occurred_at=third.decision.recorded_at + timedelta(minutes=1),
        previous_events=(root_bundle.event,),
    )
    fork_bundle = R5RelativeValueLifecycleEventBundle.create(
        event=fork_event,
        authorization_evidence=fork_evidence,
    )
    repository.stream_override = (root_bundle, second_bundle, fork_bundle)
    assert (
        _active(ports, repository).get_active(
            command.scope_ref,
            as_of=fork_event.recorded_at + timedelta(seconds=1),
        )
        is None
    )


def test_active_reread_returns_none_for_each_missing_owner_or_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Active never trusts cached lifecycle identity when one owner disappears."""

    graph = _graph(monkeypatch)
    repository = _Repository(graph.decisions)
    ports = _ports(graph)
    first = graph.decisions[0]
    evidence, command, event = _authorize_event(
        repository=repository,
        decision_bundle=first,
        action=R5RelativeValueLifecycleAction.PROMOTE,
        occurred_at=first.decision.recorded_at + timedelta(minutes=1),
    )
    ports.lifecycle.add(evidence)
    _apply(ports, repository).execute(command)
    as_of = event.recorded_at + timedelta(seconds=1)
    missing_ports = (
        replace(ports, policy=_PolicyProvider(None)),
        replace(ports, trial=_TrialProvider(None)),
        replace(ports, records=_RecordProvider(())),
        replace(ports, outcomes=_OutcomeProvider(())),
        replace(
            ports,
            outcomes=_SubstitutingOutcomeProvider(graph.trial.observations[1].portfolio_outcome),
        ),
        replace(ports, decisions=_DecisionAuthorizationProvider(())),
    )
    for missing in missing_ports:
        assert (
            _active(missing, repository).get_active(
                command.scope_ref,
                as_of=as_of,
            )
            is None
        )
    assert (
        _active(ports, repository).get_active(
            command.scope_ref,
            as_of=first.decision.valid_until,
        )
        is None
    )


def test_active_replay_rejects_a_future_cutoff_before_repository_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller cannot turn future-dated evidence into a PIT active result."""

    graph = _graph(monkeypatch)
    ports = _ports(graph)
    repository = _Repository(graph.decisions)
    future_as_of = BASE_TIME + timedelta(hours=4)

    assert (
        _active(
            ports,
            repository,
            clock=_Clock(future_as_of - timedelta(microseconds=1)),
        ).get_active(
            R5RelativeValueLifecycleScopeRef(graph.policy.scope.scope_id),
            as_of=future_as_of,
        )
        is None
    )
    assert repository.active is False
    assert ports.records.calls == 0
