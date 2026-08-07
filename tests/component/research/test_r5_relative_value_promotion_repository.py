"""Component coverage for the five Research R5 promotion ledgers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.fixed_income.application.relative_value_persistence import (
    R5PersistedRelativeValueBundle,
)
from apps.research.application.r5_relative_value_promotion_decision import (
    EvaluateR5RelativeValuePromotionCommand,
    R5RelativeValueDecisionAuthorization,
    R5RelativeValuePromotionEvidenceError,
    R5RelativeValuePromotionRef,
)
from apps.research.application.r5_relative_value_promotion_lifecycle import (
    ApplyR5RelativeValueLifecycleCommand,
    R5RelativeValueLifecycleAction,
    R5RelativeValueLifecycleAuthorizationEvidence,
    R5RelativeValueLifecycleScopeRef,
)
from apps.research.application.r5_relative_value_promotion_persistence import (
    R5PromotionArtifact,
    R5PromotionArtifactKind,
    RegisterR5PromotionArtifactCommand,
)
from apps.research.domain.r5_relative_value_portfolio_outcome import (
    R5PortfolioOutcomeSeal,
)
from apps.research.domain.r5_relative_value_promotion_decision import (
    r5_relative_value_promotion_decision_valid_until,
)
from apps.research.domain.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueLifecycleAuthorization,
    R5RelativeValueLifecycleEventType,
    create_r5_relative_value_lifecycle_root,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionPolicy,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
)
from apps.research.infrastructure.r5_relative_value_promotion_models import (
    R5PromotionArtifactModel,
    R5PromotionDecisionAuthorizationModel,
    R5PromotionDecisionBundleModel,
    R5PromotionLifecycleAuthorizationModel,
    R5PromotionLifecycleEventModel,
)
from apps.research.infrastructure.r5_relative_value_promotion_repository import (
    DjangoR5PromotionRepository,
    R5PromotionRepositoryConflict,
    R5PromotionRepositoryCorruption,
)
from apps.research.r5_relative_value_promotion_composition import (
    DjangoR5PromotionRuntime,
    build_django_r5_promotion_runtime,
)
from tests.unit.research.r5_relative_value_promotion_factories import (
    BASE_TIME,
    make_observations,
    make_persisted_bundles,
    make_policy,
    make_trial,
)

pytestmark = pytest.mark.django_db(transaction=True)


class _Clock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


@dataclass
class _ArtifactSource:
    policy: R5RelativeValuePromotionPolicy
    trial: R5RelativeValuePromotionTrial
    unit_of_work_key: str = "django:default"

    def get_exact(
        self,
        *,
        artifact_kind: R5PromotionArtifactKind,
        artifact_ref: R5RelativeValuePromotionRef,
        as_of: datetime,
    ) -> R5PromotionArtifact | None:
        candidate: R5PromotionArtifact = (
            self.policy if artifact_kind is R5PromotionArtifactKind.POLICY else self.trial
        )
        actual_ref = (
            R5RelativeValuePromotionRef(candidate.policy_id, candidate.policy_version)
            if isinstance(candidate, R5RelativeValuePromotionPolicy)
            else R5RelativeValuePromotionRef(candidate.trial_id, candidate.trial_version)
        )
        return candidate if actual_ref == artifact_ref and candidate.is_active_at(as_of) else None


class _RecordProvider:
    unit_of_work_key = "django:default"

    def __init__(self, bundles: tuple[R5PersistedRelativeValueBundle, ...]) -> None:
        self.items = {
            (item.result.result_id, item.result.result_version, item.result.record_hash): item
            for item in bundles
        }
        self.enabled = True

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_record_hash: str,
        as_of: datetime,
    ) -> R5PersistedRelativeValueBundle | None:
        if not self.enabled:
            return None
        return self.items.get((result_id, result_version, expected_record_hash))


class _OutcomeProvider:
    unit_of_work_key = "django:default"

    def __init__(self, outcomes: tuple[R5PortfolioOutcomeSeal, ...]) -> None:
        self.items = {
            (item.outcome_id, item.outcome_version, item.owner_record_hash): item
            for item in outcomes
        }

    def get_exact(
        self,
        *,
        outcome_ref: R5RelativeValuePromotionRef,
        expected_owner_record_hash: str,
        as_of: datetime,
    ) -> R5PortfolioOutcomeSeal | None:
        item = self.items.get(
            (outcome_ref.stable_id, outcome_ref.version, expected_owner_record_hash)
        )
        return item if item is not None and item.is_active_at(as_of) else None


@dataclass
class _DecisionAuthorizationSource:
    item: R5RelativeValueDecisionAuthorization
    unit_of_work_key: str = "django:default"

    def get_exact(
        self,
        *,
        authorization_ref: R5RelativeValuePromotionRef,
        policy_ref: R5RelativeValuePromotionRef,
        trial_ref: R5RelativeValuePromotionRef,
        as_of: datetime,
    ) -> R5RelativeValueDecisionAuthorization | None:
        return (
            self.item
            if (
                (self.item.authorization_id, self.item.authorization_version)
                == (authorization_ref.stable_id, authorization_ref.version)
                and self.item.policy_ref == policy_ref
                and self.item.trial_ref == trial_ref
                and self.item.is_active_at(as_of)
            )
            else None
        )


@dataclass
class _LifecycleAuthorizationSource:
    item: R5RelativeValueLifecycleAuthorizationEvidence | None = None
    unit_of_work_key: str = "django:default"

    def get_exact(
        self,
        *,
        authorization_ref: R5RelativeValuePromotionRef,
        scope_ref: R5RelativeValueLifecycleScopeRef,
        action: R5RelativeValueLifecycleAction,
        decision_ref: R5RelativeValuePromotionRef,
        rollback_target_ref: R5RelativeValuePromotionRef | None,
    ) -> R5RelativeValueLifecycleAuthorizationEvidence | None:
        if self.item is None:
            return None
        return (
            self.item
            if (self.item.evidence_id, self.item.evidence_version)
            == (authorization_ref.stable_id, authorization_ref.version)
            else None
        )


@dataclass(frozen=True)
class _Graph:
    runtime: DjangoR5PromotionRuntime
    policy: R5RelativeValuePromotionPolicy
    trial: R5RelativeValuePromotionTrial
    decision_command: EvaluateR5RelativeValuePromotionCommand
    lifecycle_source: _LifecycleAuthorizationSource
    records: _RecordProvider
    clock: _Clock


def _graph(monkeypatch: pytest.MonkeyPatch) -> _Graph:
    bundles = make_persisted_bundles(monkeypatch)
    observations = make_observations(monkeypatch, bundles=bundles)
    policy = make_policy()
    trial = make_trial(monkeypatch, policy=policy, observations=observations)
    decided_at = BASE_TIME + timedelta(hours=3, minutes=1)
    policy_ref = R5RelativeValuePromotionRef(policy.policy_id, policy.policy_version)
    trial_ref = R5RelativeValuePromotionRef(trial.trial_id, trial.trial_version)
    decision_authorization = R5RelativeValueDecisionAuthorization.create(
        authorization_version="decision-auth-v1",
        scope_id=policy.scope.scope_id,
        scope_content_hash=policy.scope.content_hash,
        policy_ref=policy_ref,
        trial_ref=trial_ref,
        issued_at=decided_at - timedelta(minutes=1),
        recorded_at=decided_at,
        decided_at=decided_at,
        decision_recorded_at=decided_at + timedelta(minutes=1),
        decision_valid_until=r5_relative_value_promotion_decision_valid_until(
            policy=policy,
            trial=trial,
            decided_at=decided_at,
        ),
        valid_until=trial.valid_until,
    )
    lifecycle_source = _LifecycleAuthorizationSource()
    records = _RecordProvider(bundles)
    clock = _Clock(BASE_TIME + timedelta(hours=2))
    runtime = build_django_r5_promotion_runtime(
        artifact_source=_ArtifactSource(policy, trial),
        owner_record_provider=records,
        portfolio_outcome_provider=_OutcomeProvider(
            tuple(item.portfolio_outcome for item in trial.observations)
        ),
        decision_authorization_source=_DecisionAuthorizationSource(decision_authorization),
        lifecycle_authorization_source=lifecycle_source,
        clock=clock,
    )
    return _Graph(
        runtime=runtime,
        policy=policy,
        trial=trial,
        decision_command=EvaluateR5RelativeValuePromotionCommand(
            policy_ref=policy_ref,
            trial_ref=trial_ref,
            authorization_ref=R5RelativeValuePromotionRef(
                decision_authorization.authorization_id,
                decision_authorization.authorization_version,
            ),
            as_of=decided_at,
        ),
        lifecycle_source=lifecycle_source,
        records=records,
        clock=clock,
    )


def _register_graph(graph: _Graph) -> None:
    graph.clock.current = BASE_TIME + timedelta(hours=2)
    graph.runtime.register_artifact.execute(
        RegisterR5PromotionArtifactCommand(
            R5PromotionArtifactKind.POLICY,
            R5RelativeValuePromotionRef(
                graph.policy.policy_id,
                graph.policy.policy_version,
            ),
        )
    )
    graph.clock.current = BASE_TIME + timedelta(hours=3)
    graph.runtime.register_artifact.execute(
        RegisterR5PromotionArtifactCommand(
            R5PromotionArtifactKind.TRIAL,
            R5RelativeValuePromotionRef(
                graph.trial.trial_id,
                graph.trial.trial_version,
            ),
        )
    )


def _lifecycle_command(graph: _Graph) -> ApplyR5RelativeValueLifecycleCommand:
    graph.clock.current = graph.decision_command.as_of + timedelta(seconds=30)
    decision = graph.runtime.evaluate.execute(graph.decision_command)
    occurred_at = decision.recorded_at + timedelta(minutes=1)
    reasons = ("research_owner_approved",)
    authorization = R5RelativeValueLifecycleAuthorization.create(
        authorization_version="lifecycle-auth-v1",
        event_type=R5RelativeValueLifecycleEventType.PROMOTED,
        decision=decision,
        rollback_target=None,
        reason_codes=reasons,
        issued_at=occurred_at - timedelta(seconds=20),
        recorded_at=occurred_at - timedelta(seconds=10),
        valid_until=occurred_at + timedelta(hours=1),
    )
    event = create_r5_relative_value_lifecycle_root(
        event_version="event-v1",
        decision=decision,
        authorization=authorization,
        reason_codes=reasons,
        occurred_at=occurred_at,
        recorded_at=occurred_at + timedelta(seconds=5),
    )
    evidence = R5RelativeValueLifecycleAuthorizationEvidence.from_event(
        evidence_version="lifecycle-evidence-v1",
        event=event,
        receipt_recorded_at=occurred_at - timedelta(seconds=5),
    )
    graph.lifecycle_source.item = evidence
    graph.clock.current = occurred_at + timedelta(seconds=1)
    return ApplyR5RelativeValueLifecycleCommand(
        scope_ref=R5RelativeValueLifecycleScopeRef(graph.policy.scope.scope_id),
        action=R5RelativeValueLifecycleAction.PROMOTE,
        decision_ref=R5RelativeValuePromotionRef(
            decision.decision_id,
            decision.decision_version,
        ),
        authorization_ref=R5RelativeValuePromotionRef(
            evidence.evidence_id,
            evidence.evidence_version,
        ),
    )


def test_id_only_graph_persists_receipt_children_and_replays_active_pit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registration, decision and lifecycle remain exact and idempotent."""

    graph = _graph(monkeypatch)
    _register_graph(graph)
    command = _lifecycle_command(graph)
    decision_again = graph.runtime.evaluate.execute(graph.decision_command)
    event = graph.runtime.apply_lifecycle.execute(command)
    event_again = graph.runtime.apply_lifecycle.execute(command)
    active_as_of = event.recorded_at + timedelta(seconds=1)
    graph.clock.current = active_as_of
    active = graph.runtime.get_active.get_active(
        command.scope_ref,
        as_of=active_as_of,
    )

    assert decision_again.decision_id == command.decision_ref.stable_id
    assert event_again == event
    assert active is not None and active.decision == decision_again
    assert R5PromotionArtifactModel._default_manager.count() == 2
    assert R5PromotionDecisionAuthorizationModel._default_manager.count() == 1
    assert R5PromotionDecisionBundleModel._default_manager.count() == 1
    assert R5PromotionLifecycleAuthorizationModel._default_manager.count() == 1
    assert R5PromotionLifecycleEventModel._default_manager.count() == 1


def test_direct_bulk_related_and_raw_tamper_paths_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ORM bypasses are blocked and raw SQL header tampering is detected."""

    graph = _graph(monkeypatch)
    assert not hasattr(DjangoR5PromotionRepository, "append_artifact")
    _register_graph(graph)
    command = _lifecycle_command(graph)
    graph.runtime.apply_lifecycle.execute(command)
    artifact = R5PromotionArtifactModel._default_manager.get(artifact_kind="policy")

    artifact.scope_id = "tampered"
    with pytest.raises(ValidationError):
        artifact.save()
    with pytest.raises(ValidationError):
        artifact.save_base(raw=True)
    with pytest.raises(ValidationError):
        R5PromotionArtifactModel._default_manager.filter(pk=artifact.pk).update(scope_id="tampered")
    with pytest.raises(ValidationError):
        R5PromotionArtifactModel._default_manager.filter(pk=artifact.pk).delete()
    with pytest.raises(ValidationError):
        R5PromotionArtifactModel._default_manager.bulk_create([R5PromotionArtifactModel()])
    decision = R5PromotionDecisionBundleModel._default_manager.get()
    with pytest.raises(ValidationError):
        artifact.r5_policy_decision_bundles.add(decision, bulk=True)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r5_promotion_artifact SET scope_id = %s WHERE id = %s",
            ["raw-tampered", artifact.pk],
        )
    with pytest.raises(R5PromotionRepositoryCorruption):
        graph.runtime.evaluate.execute(graph.decision_command)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r5_promotion_artifact SET scope_id = %s WHERE id = %s",
            [graph.policy.scope.scope_id, artifact.pk],
        )
        cursor.execute(
            "UPDATE research_r5_promotion_artifact "
            "SET stable_id = %s, version = %s WHERE id = %s",
            ["raw-hidden", "raw-version", artifact.pk],
        )
    with pytest.raises(R5PromotionRepositoryCorruption):
        graph.runtime.evaluate.execute(graph.decision_command)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r5_promotion_artifact "
            "SET stable_id = %s, version = %s WHERE id = %s",
            [graph.policy.policy_id, graph.policy.policy_version, artifact.pk],
        )

    decision = R5PromotionDecisionBundleModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r5_promotion_decision_bundle "
            "SET decision_id = %s, decision_version = %s WHERE id = %s",
            ["raw-hidden", "raw-version", decision.pk],
        )
    with pytest.raises(R5PromotionRepositoryCorruption):
        graph.runtime.evaluate.execute(graph.decision_command)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r5_promotion_decision_bundle "
            "SET decision_id = %s, decision_version = %s WHERE id = %s",
            [command.decision_ref.stable_id, command.decision_ref.version, decision.pk],
        )

    authorization = R5PromotionDecisionAuthorizationModel._default_manager.get()
    trial_artifact = R5PromotionArtifactModel._default_manager.get(artifact_kind="trial")
    policy_artifact = R5PromotionArtifactModel._default_manager.get(artifact_kind="policy")
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r5_promotion_decision_auth " "SET policy_id = %s WHERE id = %s",
            [trial_artifact.pk, authorization.pk],
        )
    with pytest.raises(R5PromotionRepositoryCorruption):
        graph.runtime.evaluate.execute(graph.decision_command)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r5_promotion_decision_auth " "SET policy_id = %s WHERE id = %s",
            [policy_artifact.pk, authorization.pk],
        )

    event = R5PromotionLifecycleEventModel._default_manager.get()
    active_as_of = event.recorded_at + timedelta(seconds=1)
    graph.clock.current = active_as_of
    assert graph.runtime.get_active.get_active(command.scope_ref, as_of=active_as_of) is not None
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r5_promotion_lifecycle_event "
            "SET scope_id = %s, stream_id = %s WHERE id = %s",
            ["raw-hidden", "raw-hidden-stream", event.pk],
        )
    assert graph.runtime.get_active.get_active(command.scope_ref, as_of=active_as_of) is None


def test_receipt_child_failure_rolls_back_and_missing_owner_blocks_trial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No orphan receipt survives child failure; owner loss blocks registration."""

    graph = _graph(monkeypatch)
    graph.clock.current = BASE_TIME + timedelta(hours=2)
    graph.runtime.register_artifact.execute(
        RegisterR5PromotionArtifactCommand(
            R5PromotionArtifactKind.POLICY,
            R5RelativeValuePromotionRef(
                graph.policy.policy_id,
                graph.policy.policy_version,
            ),
        )
    )
    graph.records.enabled = False
    graph.clock.current = BASE_TIME + timedelta(hours=3)
    with pytest.raises(R5PromotionRepositoryConflict):
        graph.runtime.register_artifact.execute(
            RegisterR5PromotionArtifactCommand(
                R5PromotionArtifactKind.TRIAL,
                R5RelativeValuePromotionRef(
                    graph.trial.trial_id,
                    graph.trial.trial_version,
                ),
            )
        )
    assert R5PromotionArtifactModel._default_manager.count() == 1

    fresh = _graph(monkeypatch)
    _register_graph(fresh)
    fresh.clock.current = fresh.decision_command.as_of + timedelta(seconds=30)
    with patch.object(
        R5PromotionDecisionBundleModel,
        "save",
        autospec=True,
        side_effect=ValidationError("forced child failure"),
    ):
        with pytest.raises(R5PromotionRepositoryConflict):
            fresh.runtime.evaluate.execute(fresh.decision_command)
    assert R5PromotionDecisionAuthorizationModel._default_manager.count() == 0
    assert R5PromotionDecisionBundleModel._default_manager.count() == 0


def test_future_pit_cutoffs_fail_before_repository_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision and active replay reject a caller-supplied future cutoff."""

    graph = _graph(monkeypatch)
    _register_graph(graph)
    future_as_of = BASE_TIME + timedelta(hours=5)
    graph.clock.current = future_as_of - timedelta(microseconds=1)

    with pytest.raises(R5RelativeValuePromotionEvidenceError) as error:
        graph.runtime.evaluate.execute(
            replace(graph.decision_command, as_of=future_as_of),
        )
    assert error.value.reason_code == "r5_promotion.future_cutoff"
    assert (
        graph.runtime.get_active.get_active(
            R5RelativeValueLifecycleScopeRef(graph.policy.scope.scope_id),
            as_of=future_as_of,
        )
        is None
    )
