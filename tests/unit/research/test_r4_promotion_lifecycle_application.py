"""Unit coverage for exact R4 lifecycle application orchestration."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import fields
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from apps.portfolio.application.r4_rolling_research_query import (
    R4RollingResearchOwnerRecord,
)
from apps.portfolio.domain.r4_rolling_evidence import ExactR3PromotionAttestation
from apps.research.application.r4_promotion_decision import (
    R4PromotionDecisionBundle,
    R4PromotionDecisionReceipt,
    R4PromotionEvidenceError,
    R4PromotionVersionRef,
)
from apps.research.application.r4_promotion_lifecycle import (
    AppendR4PromotionLifecycleCommand,
    AppendR4PromotionLifecycleEventUseCase,
    R4ActivePromotionProvider,
)
from apps.research.application.r4_promotion_lifecycle_evidence import (
    ExactR4LifecycleAuthorizationEvidence,
    R4PromotionLifecycleAction,
    R4PromotionLifecycleEventBundle,
    R4PromotionScopeRef,
)
from apps.research.domain.r4_promotion_decision import R4PromotionDecision
from apps.research.domain.r4_promotion_lifecycle import (
    R4PromotionLifecycleAuthorization,
    R4PromotionLifecycleEvent,
    R4PromotionLifecycleEventType,
    R4PromotionLifecycleState,
    derive_r4_promotion_lifecycle_state,
)
from apps.research.domain.r4_promotion_scope_policy import R4PromotionPolicy
from tests.unit.portfolio.macro_risk_rolling_factories import (
    build_study,
    promotion_attestation,
)
from tests.unit.research.r4_promotion_factories import (
    DECIDED_AT,
    DECISION_RECORDED_AT,
    portfolio_record,
    promotion_decision,
    promotion_policy,
)


class AtomicState:
    """Shared assertion state for fake transactional ports."""

    def __init__(self) -> None:
        self.depth = 0

    def require_atomic(self) -> None:
        assert self.depth == 1


class PolicyProvider:
    def __init__(self, policy: R4PromotionPolicy | None, state: AtomicState) -> None:
        self.policy = policy
        self.state = state
        self.calls = 0
        self.as_of_calls: list[datetime] = []

    def get_exact(
        self,
        policy_ref: R4PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R4PromotionPolicy | None:
        self.state.require_atomic()
        self.calls += 1
        self.as_of_calls.append(as_of)
        return self.policy


class PortfolioQuery:
    unit_of_work_key = "django:default"

    def __init__(
        self,
        owner_record: R4RollingResearchOwnerRecord | None,
        state: AtomicState,
    ) -> None:
        self.owner_record = owner_record
        self.state = state
        self.calls = 0
        self.as_of_calls: list[datetime] = []

    def get_exact(
        self,
        *,
        record_id: str,
        expected_record_hash: str,
        as_of: datetime,
    ) -> R4RollingResearchOwnerRecord | None:
        self.state.require_atomic()
        self.calls += 1
        self.as_of_calls.append(as_of)
        return self.owner_record


class CurrentR3Provider:
    def __init__(
        self,
        attestation: ExactR3PromotionAttestation | None,
        state: AtomicState,
    ) -> None:
        self.attestation = attestation
        self.state = state
        self.calls = 0
        self.as_of_calls: list[datetime] = []

    def get_exact(
        self,
        *,
        capability_key: str,
        artifact_id: str,
        artifact_version: str,
        artifact_content_hash: str,
        decision_id: str,
        decision_version: str,
        decision_content_hash: str,
        as_of: datetime,
    ) -> ExactR3PromotionAttestation | None:
        self.state.require_atomic()
        self.calls += 1
        self.as_of_calls.append(as_of)
        return self.attestation


class AuthorizationProvider:
    unit_of_work_key = "django:default"

    def __init__(
        self,
        evidence: ExactR4LifecycleAuthorizationEvidence,
        state: AtomicState,
    ) -> None:
        self.evidence = evidence
        self.state = state
        self.calls = 0

    def get_exact(
        self,
        *,
        authorization_ref: R4PromotionVersionRef,
        event_ref: R4PromotionVersionRef,
        scope_ref: R4PromotionScopeRef,
        action: R4PromotionLifecycleAction,
        decision_ref: R4PromotionVersionRef,
        rollback_target_ref: R4PromotionVersionRef | None,
    ) -> ExactR4LifecycleAuthorizationEvidence | None:
        self.state.require_atomic()
        self.calls += 1
        return self.evidence


class Repository:
    unit_of_work_key = "django:default"

    def __init__(self, bundle: R4PromotionDecisionBundle, state: AtomicState) -> None:
        self.state = state
        decision = bundle.decision
        self.decisions = {
            (decision.decision_id, decision.decision_version): bundle,
        }
        self.lifecycle: list[R4PromotionLifecycleEventBundle] = []
        self.decision_reads: list[R4PromotionVersionRef] = []

    @contextmanager
    def atomic(self) -> Iterator[None]:
        assert self.state.depth == 0
        self.state.depth = 1
        try:
            yield
        finally:
            self.state.depth = 0

    def append_decision_bundle(
        self,
        bundle: R4PromotionDecisionBundle,
    ) -> R4PromotionDecisionBundle:
        raise AssertionError("decision append is outside lifecycle tests")

    def get_decision_bundle(
        self,
        decision_ref: R4PromotionVersionRef,
        *,
        as_of: datetime,
    ) -> R4PromotionDecisionBundle | None:
        self.state.require_atomic()
        self.decision_reads.append(decision_ref)
        bundle = self.decisions.get((decision_ref.stable_id, decision_ref.version))
        if bundle is None or bundle.decision.recorded_at > as_of:
            return None
        return bundle

    def load_lifecycle_history(
        self,
        scope_ref: R4PromotionScopeRef,
        *,
        as_of: datetime,
    ) -> tuple[R4PromotionLifecycleEvent, ...]:
        self.state.require_atomic()
        return tuple(
            item.event
            for item in self.lifecycle
            if item.event.scope.scope_id == scope_ref.scope_id and item.event.recorded_at <= as_of
        )

    def get_lifecycle_event_bundle(
        self,
        event_ref: R4PromotionVersionRef,
    ) -> R4PromotionLifecycleEventBundle | None:
        self.state.require_atomic()
        return next(
            (
                item
                for item in self.lifecycle
                if (item.event.event_id, item.event.event_version)
                == (event_ref.stable_id, event_ref.version)
            ),
            None,
        )

    def load_lifecycle_stream(
        self,
        scope_ref: R4PromotionScopeRef,
    ) -> tuple[R4PromotionLifecycleEvent, ...]:
        self.state.require_atomic()
        return tuple(
            item.event for item in self.lifecycle if item.event.scope.scope_id == scope_ref.scope_id
        )

    def append_lifecycle_event_bundle(
        self,
        bundle: R4PromotionLifecycleEventBundle,
    ) -> R4PromotionLifecycleEventBundle:
        self.state.require_atomic()
        existing = self.get_lifecycle_event_bundle(
            R4PromotionVersionRef(bundle.event.event_id, bundle.event.event_version)
        )
        if existing is not None:
            return existing
        self.lifecycle.append(bundle)
        return bundle


def _decision_bundle(decision: R4PromotionDecision) -> R4PromotionDecisionBundle:
    record = decision.trial.portfolio_record
    receipt = R4PromotionDecisionReceipt.create(
        receipt_id=f"receipt:{decision.decision_id}",
        receipt_version="receipt.v1",
        decision_ref=R4PromotionVersionRef(
            decision.decision_id,
            decision.decision_version,
        ),
        trial_ref=R4PromotionVersionRef(
            decision.trial.trial_id,
            decision.trial.trial_version,
        ),
        policy_ref=R4PromotionVersionRef(
            decision.policy.policy_id,
            decision.policy.policy_version,
        ),
        policy_content_hash=decision.policy.content_hash,
        portfolio_record_id=record.record_id,
        portfolio_record_hash=record.record_hash,
        portfolio_owner_record_key=record.owner_record_key,
        portfolio_recorded_at=record.recorded_at,
        current_r3_content_hash=decision.trial.current_r3_attestation.content_hash,
        decided_at=decision.decided_at,
        recorded_at=decision.recorded_at,
        decision_valid_until=decision.valid_until,
    )
    return R4PromotionDecisionBundle.create(decision=decision, receipt=receipt)


def _authorization_evidence(
    *,
    event_ref: R4PromotionVersionRef,
    action: R4PromotionLifecycleAction,
    decision: R4PromotionDecision,
    rollback_target: R4PromotionDecision | None = None,
    after: datetime | None = None,
) -> ExactR4LifecycleAuthorizationEvidence:
    base = max(
        value
        for value in (
            decision.recorded_at,
            None if rollback_target is None else rollback_target.recorded_at,
            after,
        )
        if value is not None
    ) + timedelta(minutes=1)
    reasons = (
        (
            "research_policy_approved"
            if action is R4PromotionLifecycleAction.PROMOTE
            else (
                "methodology_retired"
                if action is R4PromotionLifecycleAction.RETIRE
                else "replacement_regression"
            )
        ),
    )
    authorization = R4PromotionLifecycleAuthorization.create(
        authorization_id=f"authorization:{event_ref.stable_id}",
        authorization_version="authorization.v1",
        event_type=action.event_type,
        decision=decision,
        rollback_target=rollback_target,
        reason_codes=reasons,
        issued_at=base,
        recorded_at=base + timedelta(minutes=1),
        valid_until=base + timedelta(hours=1),
    )
    return ExactR4LifecycleAuthorizationEvidence.create(
        event_ref=event_ref,
        authorization=authorization,
        reason_codes=reasons,
        occurred_at=base + timedelta(minutes=2),
        event_recorded_at=base + timedelta(minutes=3),
    )


def _command(
    *,
    event_ref: R4PromotionVersionRef,
    action: R4PromotionLifecycleAction,
    decision: R4PromotionDecision,
    rollback_target: R4PromotionDecision | None = None,
) -> AppendR4PromotionLifecycleCommand:
    return AppendR4PromotionLifecycleCommand(
        output_event_ref=event_ref,
        scope_ref=R4PromotionScopeRef(decision.scope.scope_id),
        action=action,
        decision_ref=R4PromotionVersionRef(
            decision.decision_id,
            decision.decision_version,
        ),
        authorization_ref=R4PromotionVersionRef(
            f"authorization:{event_ref.stable_id}",
            "authorization.v1",
        ),
        rollback_target_ref=(
            None
            if rollback_target is None
            else R4PromotionVersionRef(
                rollback_target.decision_id,
                rollback_target.decision_version,
            )
        ),
    )


def _ports(
    *,
    decision: R4PromotionDecision,
    evidence: ExactR4LifecycleAuthorizationEvidence,
) -> tuple[
    PolicyProvider,
    PortfolioQuery,
    CurrentR3Provider,
    AuthorizationProvider,
    Repository,
]:
    state = AtomicState()
    policy = PolicyProvider(decision.policy, state)
    portfolio = PortfolioQuery(
        R4RollingResearchOwnerRecord.create(portfolio_record()),
        state,
    )
    r3 = CurrentR3Provider(promotion_attestation(), state)
    authorization = AuthorizationProvider(evidence, state)
    repository = Repository(_decision_bundle(decision), state)
    return policy, portfolio, r3, authorization, repository


def _use_case(
    policy: PolicyProvider,
    portfolio: PortfolioQuery,
    r3: CurrentR3Provider,
    authorization: AuthorizationProvider,
    repository: Repository,
) -> AppendR4PromotionLifecycleEventUseCase:
    return AppendR4PromotionLifecycleEventUseCase(
        policy_provider=policy,
        portfolio_query=portfolio,
        current_r3_provider=r3,
        authorization_provider=authorization,
        repository=repository,
    )


def test_id_only_command_appends_root_and_active_provider_rereads_every_owner() -> None:
    decision = promotion_decision()
    event_ref = R4PromotionVersionRef("r4-lifecycle-root-app", "event.v1")
    evidence = _authorization_evidence(
        event_ref=event_ref,
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=decision,
    )
    policy, portfolio, r3, authorization, repository = _ports(
        decision=decision,
        evidence=evidence,
    )
    command = _command(
        event_ref=event_ref,
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=decision,
    )

    event = _use_case(policy, portfolio, r3, authorization, repository).execute(command)

    assert {item.name for item in fields(AppendR4PromotionLifecycleCommand)} == {
        "output_event_ref",
        "scope_ref",
        "action",
        "decision_ref",
        "authorization_ref",
        "rollback_target_ref",
    }
    assert event.event_type is R4PromotionLifecycleEventType.PROMOTED
    assert (policy.calls, portfolio.calls, r3.calls, authorization.calls) == (1, 1, 1, 1)

    active = R4ActivePromotionProvider(
        policy_provider=policy,
        portfolio_query=portfolio,
        current_r3_provider=r3,
        repository=repository,
    ).get_active(command.scope_ref, as_of=event.recorded_at)

    assert active == _decision_bundle(decision)
    assert (policy.calls, portfolio.calls, r3.calls) == (2, 2, 2)


@pytest.mark.parametrize("missing", ("policy", "portfolio", "r3"))
def test_lifecycle_action_fails_before_append_when_dynamic_owner_is_missing(
    missing: str,
) -> None:
    decision = promotion_decision()
    event_ref = R4PromotionVersionRef(f"r4-lifecycle-missing-{missing}", "event.v1")
    evidence = _authorization_evidence(
        event_ref=event_ref,
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=decision,
    )
    policy, portfolio, r3, authorization, repository = _ports(
        decision=decision,
        evidence=evidence,
    )
    if missing == "policy":
        policy.policy = None
    elif missing == "portfolio":
        portfolio.owner_record = None
    else:
        r3.attestation = None

    with pytest.raises(R4PromotionEvidenceError, match=missing):
        _use_case(policy, portfolio, r3, authorization, repository).execute(
            _command(
                event_ref=event_ref,
                action=R4PromotionLifecycleAction.PROMOTE,
                decision=decision,
            )
        )
    assert repository.lifecycle == []


def test_active_provider_fails_closed_on_substituted_policy_portfolio_or_r3() -> None:
    decision = promotion_decision()
    event_ref = R4PromotionVersionRef("r4-lifecycle-active-exact", "event.v1")
    evidence = _authorization_evidence(
        event_ref=event_ref,
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=decision,
    )
    policy, portfolio, r3, authorization, repository = _ports(
        decision=decision,
        evidence=evidence,
    )
    command = _command(
        event_ref=event_ref,
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=decision,
    )
    event = _use_case(policy, portfolio, r3, authorization, repository).execute(command)
    provider = R4ActivePromotionProvider(
        policy_provider=policy,
        portfolio_query=portfolio,
        current_r3_provider=r3,
        repository=repository,
    )

    original_policy = policy.policy
    policy.policy = promotion_policy(minimum_relative_net_return=Decimal("0.5"))
    assert provider.get_active(command.scope_ref, as_of=event.recorded_at) is None
    policy.policy = original_policy

    original_record = portfolio.owner_record
    portfolio.owner_record = R4RollingResearchOwnerRecord.create(
        portfolio_record(study=build_study(minimum_regime_windows=3))
    )
    assert provider.get_active(command.scope_ref, as_of=event.recorded_at) is None
    portfolio.owner_record = original_record

    r3.attestation = promotion_attestation(retired_at=event.recorded_at)
    assert provider.get_active(command.scope_ref, as_of=event.recorded_at) is None


def test_application_replays_a_b_c_and_rolls_back_only_by_exact_target_refs() -> None:
    first = promotion_decision()
    second = promotion_decision(
        decision_id="r4-promotion-decision-app-second",
        decision_version="decision.v2",
        decided_at=DECIDED_AT + timedelta(minutes=10),
        recorded_at=DECISION_RECORDED_AT + timedelta(minutes=10),
    )
    third = promotion_decision(
        decision_id="r4-promotion-decision-app-third",
        decision_version="decision.v3",
        decided_at=DECIDED_AT + timedelta(minutes=20),
        recorded_at=DECISION_RECORDED_AT + timedelta(minutes=20),
    )
    root_ref = R4PromotionVersionRef("r4-app-stack-a", "event.v1")
    root_evidence = _authorization_evidence(
        event_ref=root_ref,
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=first,
    )
    policy, portfolio, r3, authorization, repository = _ports(
        decision=first,
        evidence=root_evidence,
    )
    for decision in (second, third):
        repository.decisions[(decision.decision_id, decision.decision_version)] = _decision_bundle(
            decision
        )
    use_case = _use_case(policy, portfolio, r3, authorization, repository)

    def append(
        *,
        suffix: str,
        action: R4PromotionLifecycleAction,
        decision: R4PromotionDecision,
        target: R4PromotionDecision | None = None,
        after: datetime | None = None,
    ) -> R4PromotionLifecycleEvent:
        event_ref = R4PromotionVersionRef(f"r4-app-stack-{suffix}", "event.v1")
        authorization.evidence = _authorization_evidence(
            event_ref=event_ref,
            action=action,
            decision=decision,
            rollback_target=target,
            after=after,
        )
        return use_case.execute(
            _command(
                event_ref=event_ref,
                action=action,
                decision=decision,
                rollback_target=target,
            )
        )

    root = append(
        suffix="a",
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=first,
    )
    promoted_second = append(
        suffix="b",
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=second,
        after=root.recorded_at,
    )
    promoted_third = append(
        suffix="c",
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=third,
        after=promoted_second.recorded_at,
    )

    lifecycle_count = len(repository.lifecycle)
    with pytest.raises(ValueError, match=r"exactly stack\[-2\]"):
        append(
            suffix="skip-to-a",
            action=R4PromotionLifecycleAction.ROLLBACK,
            decision=third,
            target=first,
            after=promoted_third.recorded_at,
        )
    assert len(repository.lifecycle) == lifecycle_count

    rolled_back_to_second = append(
        suffix="rollback-to-b",
        action=R4PromotionLifecycleAction.ROLLBACK,
        decision=third,
        target=second,
        after=promoted_third.recorded_at,
    )
    rolled_back_to_first = append(
        suffix="rollback-to-a",
        action=R4PromotionLifecycleAction.ROLLBACK,
        decision=second,
        target=first,
        after=rolled_back_to_second.recorded_at,
    )
    snapshot = derive_r4_promotion_lifecycle_state(
        tuple(item.event for item in repository.lifecycle),
        evaluated_at=rolled_back_to_first.recorded_at,
    )

    assert snapshot.state is R4PromotionLifecycleState.ROLLED_BACK
    assert snapshot.active_decision == root.decision
    assert repository.decision_reads == [
        R4PromotionVersionRef(first.decision_id, first.decision_version),
        R4PromotionVersionRef(second.decision_id, second.decision_version),
        R4PromotionVersionRef(third.decision_id, third.decision_version),
        R4PromotionVersionRef(third.decision_id, third.decision_version),
        R4PromotionVersionRef(first.decision_id, first.decision_version),
        R4PromotionVersionRef(third.decision_id, third.decision_version),
        R4PromotionVersionRef(second.decision_id, second.decision_version),
        R4PromotionVersionRef(second.decision_id, second.decision_version),
        R4PromotionVersionRef(first.decision_id, first.decision_version),
    ]


def test_retire_clears_active_and_all_transactional_ports_must_share_uow() -> None:
    decision = promotion_decision()
    root_ref = R4PromotionVersionRef("r4-lifecycle-root-retire", "event.v1")
    root_evidence = _authorization_evidence(
        event_ref=root_ref,
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=decision,
    )
    policy, portfolio, r3, authorization, repository = _ports(
        decision=decision,
        evidence=root_evidence,
    )
    use_case = _use_case(policy, portfolio, r3, authorization, repository)
    use_case.execute(
        _command(
            event_ref=root_ref,
            action=R4PromotionLifecycleAction.PROMOTE,
            decision=decision,
        )
    )
    retire_ref = R4PromotionVersionRef("r4-lifecycle-retire", "event.v1")
    authorization.evidence = _authorization_evidence(
        event_ref=retire_ref,
        action=R4PromotionLifecycleAction.RETIRE,
        decision=decision,
        after=decision.valid_until + timedelta(minutes=1),
    )
    retire_command = _command(
        event_ref=retire_ref,
        action=R4PromotionLifecycleAction.RETIRE,
        decision=decision,
    )

    retired = use_case.execute(retire_command)

    assert retired.event_type is R4PromotionLifecycleEventType.RETIRED
    assert retired.occurred_at > decision.valid_until
    assert policy.as_of_calls[-1] == decision.decided_at
    assert portfolio.as_of_calls[-1] == decision.decided_at
    assert r3.as_of_calls[-1] == decision.decided_at
    assert (
        R4ActivePromotionProvider(
            policy_provider=policy,
            portfolio_query=portfolio,
            current_r3_provider=r3,
            repository=repository,
        ).get_active(retire_command.scope_ref, as_of=retired.recorded_at)
        is None
    )

    portfolio.unit_of_work_key = "django:other"
    with pytest.raises(ValueError, match="different units of work"):
        _use_case(policy, portfolio, r3, authorization, repository)
