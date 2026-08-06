"""Component coverage for persisted Research R4 promotion workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.db.models import QuerySet

from apps.portfolio.application.r4_rolling_research_query import (
    R4RollingResearchOwnerRecord,
)
from apps.portfolio.domain.r4_rolling_evidence import ExactR3PromotionAttestation
from apps.research.application.r4_promotion_decision import (
    EvaluateR4PromotionCommand,
    R4PromotionVersionRef,
)
from apps.research.application.r4_promotion_lifecycle import (
    AppendR4PromotionLifecycleCommand,
)
from apps.research.application.r4_promotion_lifecycle_evidence import (
    R4PromotionLifecycleAction,
    R4PromotionLifecycleEventBundle,
    R4PromotionScopeRef,
)
from apps.research.application.r4_promotion_registration import (
    R4PromotionPolicyRegistrationDraft,
)
from apps.research.domain.r4_promotion_lifecycle import (
    R4PromotionLifecycleAuthorization,
    R4PromotionLifecycleEventType,
    create_r4_promotion_lifecycle_event,
)
from apps.research.infrastructure.r4_promotion_codec import R4PromotionCodecError
from apps.research.infrastructure.r4_promotion_models import (
    R4PromotionDecisionBundleModel,
    R4PromotionDecisionReceiptModel,
    R4PromotionLifecycleAuthorizationReceiptModel,
    R4PromotionLifecycleEventModel,
    R4PromotionPolicyModel,
    _claim_r4_promotion_insert,
)
from apps.research.infrastructure.r4_promotion_providers import (
    R4LifecycleAuthorizationClaim,
    R4PromotionRepositoryConflict,
    R4PromotionRepositoryCorruption,
    r4_lifecycle_authorization_claim_id,
)
from apps.research.infrastructure.r4_promotion_repository import (
    _lifecycle_event_model_values,
)
from apps.research.r4_promotion_composition import (
    DjangoR4PromotionRuntime,
    build_django_r4_promotion_runtime,
)
from tests.unit.portfolio.macro_risk_rolling_factories import (
    build_study,
    promotion_attestation,
)
from tests.unit.research.r4_promotion_factories import (
    DECIDED_AT,
    DECISION_RECORDED_AT,
    POLICY_ACTIVE_FROM,
    POLICY_ACTIVE_UNTIL,
    POLICY_RECORDED_AT,
    portfolio_record,
    promotion_policy,
)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class PortfolioQuery:
    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.owner_record = R4RollingResearchOwnerRecord.create(portfolio_record())
        self.calls: list[datetime] = []

    def get_exact(
        self,
        *,
        record_id: str,
        expected_record_hash: str,
        as_of: datetime,
    ) -> R4RollingResearchOwnerRecord | None:
        self.calls.append(as_of)
        record = self.owner_record.record
        if (
            record.record_id != record_id
            or record.record_hash != expected_record_hash
            or not record.recorded_at <= as_of < record.valid_until
        ):
            return None
        return self.owner_record


class CurrentR3Provider:
    def __init__(self) -> None:
        self.attestation = promotion_attestation()
        self.calls: list[datetime] = []

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
        self.calls.append(as_of)
        item = self.attestation
        if (
            capability_key != "macro_factor_r3"
            or (item.artifact_id, item.artifact_version, item.artifact_content_hash)
            != (artifact_id, artifact_version, artifact_content_hash)
            or (item.decision_id, item.decision_version, item.decision_content_hash)
            != (decision_id, decision_version, decision_content_hash)
            or not item.is_active_at(as_of)
        ):
            return None
        return item


class AuthorizationSource:
    def __init__(self) -> None:
        self.claim: R4LifecycleAuthorizationClaim | None = None

    def get_exact(
        self,
        *,
        authorization_ref: R4PromotionVersionRef,
        event_ref: R4PromotionVersionRef,
        scope_ref: R4PromotionScopeRef,
        action: R4PromotionLifecycleAction,
        decision_ref: R4PromotionVersionRef,
        rollback_target_ref: R4PromotionVersionRef | None,
    ) -> R4LifecycleAuthorizationClaim | None:
        return self.claim


@dataclass
class RuntimeFixture:
    runtime: DjangoR4PromotionRuntime
    clock: FixedClock
    portfolio: PortfolioQuery
    r3: CurrentR3Provider
    authorization_source: AuthorizationSource


def _runtime() -> RuntimeFixture:
    clock = FixedClock(POLICY_RECORDED_AT)
    portfolio = PortfolioQuery()
    r3 = CurrentR3Provider()
    source = AuthorizationSource()
    runtime = build_django_r4_promotion_runtime(
        portfolio_query=portfolio,
        current_r3_provider=r3,
        lifecycle_authorization_source=source,
        clock=clock,
    )
    return RuntimeFixture(runtime, clock, portfolio, r3, source)


def _register_policy(fixture: RuntimeFixture) -> None:
    persisted = fixture.runtime.repository.append_policy(
        R4PromotionPolicyRegistrationDraft.from_policy(promotion_policy())
    )
    assert persisted == promotion_policy()


def _evaluate(
    fixture: RuntimeFixture,
    *,
    suffix: str = "main",
    decided_at: datetime = DECIDED_AT,
    recorded_at: datetime = DECISION_RECORDED_AT,
):
    fixture.clock.value = recorded_at
    record = fixture.portfolio.owner_record.record
    return fixture.runtime.evaluate.execute(
        EvaluateR4PromotionCommand(
            output_decision_ref=R4PromotionVersionRef(
                f"r4-persisted-decision-{suffix}",
                "decision.v1",
            ),
            output_trial_ref=R4PromotionVersionRef(
                f"r4-persisted-trial-{suffix}",
                "trial.v1",
            ),
            policy_ref=R4PromotionVersionRef(
                "r4-promotion-policy-main",
                "policy.v1",
            ),
            portfolio_record_id=record.record_id,
            expected_portfolio_record_hash=record.record_hash,
            as_of=decided_at,
        )
    )


def _promote_root(fixture: RuntimeFixture, decision):
    command = _prepare_root(fixture, decision)
    return fixture.runtime.append_lifecycle.execute(command), command


def _prepare_root(fixture: RuntimeFixture, decision):
    event_ref = R4PromotionVersionRef("r4-persisted-event-root", "event.v1")
    reasons = ("research_policy_approved",)
    issued_at = decision.recorded_at + timedelta(minutes=1)
    placeholder = R4PromotionLifecycleAuthorization.create(
        authorization_id="placeholder",
        authorization_version="authorization.v1",
        event_type=R4PromotionLifecycleEventType.PROMOTED,
        decision=decision,
        rollback_target=None,
        reason_codes=reasons,
        issued_at=issued_at,
        recorded_at=issued_at + timedelta(minutes=1),
        valid_until=issued_at + timedelta(hours=1),
    )
    authorization_id = r4_lifecycle_authorization_claim_id(
        event_ref=event_ref,
        authorization=placeholder,
    )
    authorization = R4PromotionLifecycleAuthorization.create(
        authorization_id=authorization_id,
        authorization_version="authorization.v1",
        event_type=R4PromotionLifecycleEventType.PROMOTED,
        decision=decision,
        rollback_target=None,
        reason_codes=reasons,
        issued_at=issued_at,
        recorded_at=issued_at + timedelta(minutes=1),
        valid_until=issued_at + timedelta(hours=1),
    )
    fixture.authorization_source.claim = R4LifecycleAuthorizationClaim(
        authorization=authorization,
        reason_codes=reasons,
    )
    fixture.clock.value = issued_at + timedelta(minutes=2)
    command = AppendR4PromotionLifecycleCommand(
        output_event_ref=event_ref,
        scope_ref=R4PromotionScopeRef(decision.scope.scope_id),
        action=R4PromotionLifecycleAction.PROMOTE,
        decision_ref=R4PromotionVersionRef(
            decision.decision_id,
            decision.decision_version,
        ),
        authorization_ref=R4PromotionVersionRef(
            authorization.authorization_id,
            authorization.authorization_version,
        ),
        rollback_target_ref=None,
    )
    return command


def _append_action(
    fixture: RuntimeFixture,
    *,
    event_id: str,
    action: R4PromotionLifecycleAction,
    decision,
    after: datetime,
    rollback_target=None,
):
    command = _prepare_action(
        fixture,
        event_id=event_id,
        action=action,
        decision=decision,
        after=after,
        rollback_target=rollback_target,
    )
    return fixture.runtime.append_lifecycle.execute(command)


def _prepare_action(
    fixture: RuntimeFixture,
    *,
    event_id: str,
    action: R4PromotionLifecycleAction,
    decision,
    after: datetime,
    rollback_target=None,
):
    event_ref = R4PromotionVersionRef(event_id, "event.v1")
    reasons = (
        (
            "replacement_policy_approved"
            if action is R4PromotionLifecycleAction.PROMOTE
            else "replacement_regression"
        ),
    )
    issued_at = max(
        after,
        decision.recorded_at,
        decision.recorded_at if rollback_target is None else rollback_target.recorded_at,
    ) + timedelta(minutes=1)
    placeholder = R4PromotionLifecycleAuthorization.create(
        authorization_id="placeholder",
        authorization_version="authorization.v1",
        event_type=action.event_type,
        decision=decision,
        rollback_target=rollback_target,
        reason_codes=reasons,
        issued_at=issued_at,
        recorded_at=issued_at + timedelta(minutes=1),
        valid_until=issued_at + timedelta(hours=1),
    )
    authorization = R4PromotionLifecycleAuthorization.create(
        authorization_id=r4_lifecycle_authorization_claim_id(
            event_ref=event_ref,
            authorization=placeholder,
        ),
        authorization_version="authorization.v1",
        event_type=action.event_type,
        decision=decision,
        rollback_target=rollback_target,
        reason_codes=reasons,
        issued_at=issued_at,
        recorded_at=issued_at + timedelta(minutes=1),
        valid_until=issued_at + timedelta(hours=1),
    )
    fixture.authorization_source.claim = R4LifecycleAuthorizationClaim(
        authorization=authorization,
        reason_codes=reasons,
    )
    fixture.clock.value = issued_at + timedelta(minutes=2)
    command = AppendR4PromotionLifecycleCommand(
        output_event_ref=event_ref,
        scope_ref=R4PromotionScopeRef(decision.scope.scope_id),
        action=action,
        decision_ref=R4PromotionVersionRef(
            decision.decision_id,
            decision.decision_version,
        ),
        authorization_ref=R4PromotionVersionRef(
            authorization.authorization_id,
            authorization.authorization_version,
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
    return command


@pytest.mark.django_db(transaction=True)
def test_persisted_decision_lifecycle_and_active_replay_are_exact() -> None:
    fixture = _runtime()
    _register_policy(fixture)

    with fixture.runtime.repository.atomic():
        ref = R4PromotionVersionRef("r4-promotion-policy-main", "policy.v1")
        assert (
            fixture.runtime.policy_provider.get_exact(
                ref,
                as_of=POLICY_ACTIVE_FROM - timedelta(microseconds=1),
            )
            is None
        )
        assert fixture.runtime.policy_provider.get_exact(ref, as_of=POLICY_ACTIVE_FROM)
        assert fixture.runtime.policy_provider.get_exact(ref, as_of=POLICY_ACTIVE_UNTIL) is None

    decision = _evaluate(fixture)
    event, command = _promote_root(fixture, decision)
    active = fixture.runtime.active.get_active(
        command.scope_ref,
        as_of=event.recorded_at,
    )

    assert active is not None
    assert active.decision == decision
    assert R4PromotionPolicyModel._default_manager.count() == 1
    assert R4PromotionDecisionReceiptModel._default_manager.count() == 1
    assert R4PromotionDecisionBundleModel._default_manager.count() == 1
    assert R4PromotionLifecycleAuthorizationReceiptModel._default_manager.count() == 1
    assert R4PromotionLifecycleEventModel._default_manager.count() == 1
    assert fixture.portfolio.calls
    assert fixture.r3.calls


@pytest.mark.django_db(transaction=True)
def test_policy_registration_discards_caller_receipt_and_replays_first_clock_winner() -> None:
    fixture = _runtime()
    caller_policy = promotion_policy()
    draft = R4PromotionPolicyRegistrationDraft.from_policy(caller_policy)
    assert "recorded_at" not in {item.name for item in fields(draft)}
    assert "content_hash" not in {item.name for item in fields(draft)}
    first_clock = POLICY_RECORDED_AT + timedelta(days=1)
    fixture.clock.value = first_clock

    first = fixture.runtime.repository.append_policy(draft)

    assert first.recorded_at == first_clock
    assert first.recorded_at != caller_policy.recorded_at
    assert first.content_hash != caller_policy.content_hash
    fixture.clock.value = POLICY_RECORDED_AT + timedelta(days=2)
    assert fixture.runtime.repository.append_policy(draft) == first
    assert R4PromotionPolicyModel._default_manager.count() == 1

    late = replace(draft, policy_id="r4-policy-late-clock")
    fixture.clock.value = draft.active_from + timedelta(microseconds=1)
    with pytest.raises(ValueError, match="receipt/active window"):
        fixture.runtime.repository.append_policy(late)
    assert R4PromotionPolicyModel._default_manager.count() == 1


@pytest.mark.django_db(transaction=True)
def test_all_five_tables_reject_every_direct_mutation_path() -> None:
    fixture = _runtime()
    _register_policy(fixture)
    decision = _evaluate(fixture)
    _promote_root(fixture, decision)
    model_types = (
        R4PromotionPolicyModel,
        R4PromotionDecisionReceiptModel,
        R4PromotionDecisionBundleModel,
        R4PromotionLifecycleAuthorizationReceiptModel,
        R4PromotionLifecycleEventModel,
    )

    for model_type in model_types:
        row = model_type._default_manager.first()
        assert row is not None
        with pytest.raises(ValidationError, match="(?i)append-only"):
            model_type._default_manager.filter(pk=row.pk).update(persisted_at=row.persisted_at)
        with pytest.raises(ValidationError, match="(?i)append-only"):
            model_type._base_manager.filter(pk=row.pk).update(persisted_at=row.persisted_at)
        with pytest.raises(ValidationError, match="(?i)append-only"):
            model_type._default_manager.filter(pk=row.pk).delete()
        with pytest.raises(ValidationError, match="(?i)append-only"):
            model_type._base_manager.filter(pk=row.pk).delete()
        with pytest.raises(ValidationError, match="cannot be deleted"):
            row.delete()
        with pytest.raises(ValidationError, match="(?i)append-only"):
            row.save()
        with pytest.raises(ValidationError, match="(?i)append-only"):
            row.save(force_update=True)
        with pytest.raises(ValidationError, match="(?i)append-only"):
            row.save(update_fields=["persisted_at"])
        with pytest.raises(ValidationError, match="bulk updated"):
            model_type._default_manager.bulk_update([row], ["persisted_at"])
        with pytest.raises(ValidationError, match="bulk updated"):
            model_type._base_manager.all().bulk_update([row], ["persisted_at"])
        row.pk = 0
        with pytest.raises(ValidationError, match="(?i)append-only"):
            row.save()
        with pytest.raises(ValidationError, match="exact repository insert claim"):
            model_type._default_manager.create()
        with pytest.raises(ValidationError, match="exact append operations"):
            model_type._default_manager.bulk_create([model_type()])
        with pytest.raises(ValidationError, match="exact append operations"):
            model_type._base_manager.bulk_create(
                [model_type()],
                ignore_conflicts=True,
            )
        with pytest.raises(ValidationError, match="exact append operations"):
            model_type._default_manager.bulk_create(
                [model_type()],
                update_conflicts=True,
                update_fields=["id"],
                unique_fields=["id"],
            )

    policy = R4PromotionPolicyModel._default_manager.get()
    decision_row = R4PromotionDecisionBundleModel._default_manager.get()
    with pytest.raises(ValidationError, match="(?i)append-only"):
        policy.decision_receipts.all().update(owner="forged")
    with pytest.raises(ValidationError, match="(?i)append-only"):
        decision_row.lifecycle_events.all().delete()
    with pytest.raises(ValidationError, match="bulk updated"):
        policy.decision_receipts.bulk_update([], ["owner"])
    with pytest.raises(ValidationError, match="exact append operations"):
        decision_row.lifecycle_events.bulk_create(
            [R4PromotionLifecycleEventModel()],
            ignore_conflicts=True,
        )


@pytest.mark.django_db(transaction=True)
def test_child_failure_rolls_back_server_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _runtime()
    _register_policy(fixture)

    def fail_child(bundle):
        raise RuntimeError("simulated child failure")

    monkeypatch.setattr(fixture.runtime.repository, "append_decision_bundle", fail_child)
    with pytest.raises(RuntimeError, match="child failure"):
        _evaluate(fixture, suffix="rollback")

    assert R4PromotionDecisionReceiptModel._default_manager.count() == 0
    assert R4PromotionDecisionBundleModel._default_manager.count() == 0


@pytest.mark.django_db(transaction=True)
def test_lifecycle_child_failure_rolls_back_authorization_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _runtime()
    _register_policy(fixture)
    decision = _evaluate(fixture)
    command = _prepare_root(fixture, decision)

    def fail_child(bundle):
        raise RuntimeError("simulated lifecycle child failure")

    monkeypatch.setattr(
        fixture.runtime.repository,
        "append_lifecycle_event_bundle",
        fail_child,
    )
    with pytest.raises(RuntimeError, match="lifecycle child failure"):
        fixture.runtime.append_lifecycle.execute(command)

    assert R4PromotionLifecycleAuthorizationReceiptModel._default_manager.count() == 0
    assert R4PromotionLifecycleEventModel._default_manager.count() == 0


@pytest.mark.django_db(transaction=True)
def test_persisted_a_b_c_stack_allows_only_consecutive_exact_rollbacks() -> None:
    fixture = _runtime()
    _register_policy(fixture)
    first = _evaluate(fixture, suffix="stack-a")
    second = _evaluate(
        fixture,
        suffix="stack-b",
        decided_at=DECIDED_AT + timedelta(minutes=10),
        recorded_at=DECISION_RECORDED_AT + timedelta(minutes=10),
    )
    third = _evaluate(
        fixture,
        suffix="stack-c",
        decided_at=DECIDED_AT + timedelta(minutes=20),
        recorded_at=DECISION_RECORDED_AT + timedelta(minutes=20),
    )
    root, command = _promote_root(fixture, first)
    promoted_second = _append_action(
        fixture,
        event_id="r4-persisted-stack-b",
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=second,
        after=root.recorded_at,
    )
    promoted_third = _append_action(
        fixture,
        event_id="r4-persisted-stack-c",
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=third,
        after=promoted_second.recorded_at,
    )
    receipts_before = R4PromotionLifecycleAuthorizationReceiptModel._default_manager.count()
    with pytest.raises(ValueError, match=r"exactly stack\[-2\]"):
        _append_action(
            fixture,
            event_id="r4-persisted-stack-skip",
            action=R4PromotionLifecycleAction.ROLLBACK,
            decision=third,
            rollback_target=first,
            after=promoted_third.recorded_at,
        )
    assert R4PromotionLifecycleAuthorizationReceiptModel._default_manager.count() == receipts_before

    rolled_back_second = _append_action(
        fixture,
        event_id="r4-persisted-stack-to-b",
        action=R4PromotionLifecycleAction.ROLLBACK,
        decision=third,
        rollback_target=second,
        after=promoted_third.recorded_at,
    )
    rolled_back_first = _append_action(
        fixture,
        event_id="r4-persisted-stack-to-a",
        action=R4PromotionLifecycleAction.ROLLBACK,
        decision=second,
        rollback_target=first,
        after=rolled_back_second.recorded_at,
    )
    active = fixture.runtime.active.get_active(
        command.scope_ref,
        as_of=rolled_back_first.recorded_at,
    )

    assert active is not None
    assert active.decision == first
    assert R4PromotionLifecycleEventModel._default_manager.count() == 5


@pytest.mark.django_db(transaction=True)
def test_policy_decision_and_lifecycle_first_miss_races_replay_exact_winners() -> None:
    fixture = _runtime()
    draft = R4PromotionPolicyRegistrationDraft.from_policy(promotion_policy())
    first_policy = fixture.runtime.repository.append_policy(draft)
    fixture.clock.value = POLICY_RECORDED_AT + timedelta(days=1)
    with patch.object(
        fixture.runtime.repository,
        "_get_policy_by_identity",
        return_value=None,
    ):
        assert fixture.runtime.repository.append_policy(draft) == first_policy

    decision = _evaluate(fixture, suffix="race")
    decision_ref = R4PromotionVersionRef(decision.decision_id, decision.decision_version)
    with fixture.runtime.repository.atomic():
        bundle = fixture.runtime.repository.get_decision_bundle(
            decision_ref,
            as_of=decision.recorded_at,
        )
    assert bundle is not None
    original_first = QuerySet.first
    receipt_missed = False

    def miss_receipt_once(queryset):
        nonlocal receipt_missed
        if queryset.model is R4PromotionDecisionReceiptModel and not receipt_missed:
            receipt_missed = True
            return None
        return original_first(queryset)

    fixture.clock.value = bundle.receipt.recorded_at + timedelta(microseconds=1)
    with (
        patch.object(QuerySet, "first", new=miss_receipt_once),
        fixture.runtime.repository.atomic(),
    ):
        replayed_receipt = fixture.runtime.repository.claim_decision_receipt(
            decision_ref=decision_ref,
            trial_ref=R4PromotionVersionRef(
                decision.trial.trial_id,
                decision.trial.trial_version,
            ),
            policy_ref=R4PromotionVersionRef(
                decision.policy.policy_id,
                decision.policy.policy_version,
            ),
            policy_content_hash=decision.policy.content_hash,
            portfolio_record_id=decision.trial.portfolio_record.record_id,
            portfolio_record_hash=decision.trial.portfolio_record.record_hash,
            portfolio_owner_record_key=decision.trial.portfolio_record.owner_record_key,
            portfolio_recorded_at=decision.trial.portfolio_record.recorded_at,
            current_r3_content_hash=decision.trial.current_r3_attestation.content_hash,
            decided_at=decision.decided_at,
            decision_valid_until=decision.valid_until,
        )
    assert replayed_receipt == bundle.receipt
    decision_row = R4PromotionDecisionBundleModel._default_manager.get()
    with (
        patch.object(
            fixture.runtime.repository,
            "_get_decision_bundle_collision",
            side_effect=[None, decision_row],
        ),
        fixture.runtime.repository.atomic(),
    ):
        assert fixture.runtime.repository.append_decision_bundle(bundle) == bundle

    event, _ = _promote_root(fixture, decision)
    event_ref = R4PromotionVersionRef(event.event_id, event.event_version)
    with fixture.runtime.repository.atomic():
        event_bundle = fixture.runtime.repository.get_lifecycle_event_bundle(event_ref)
    assert event_bundle is not None
    lifecycle_missed = False

    def miss_lifecycle_once(queryset):
        nonlocal lifecycle_missed
        if queryset.model is R4PromotionLifecycleAuthorizationReceiptModel and not lifecycle_missed:
            lifecycle_missed = True
            return None
        return original_first(queryset)

    fixture.clock.value = event.occurred_at + timedelta(microseconds=1)
    with (
        patch.object(QuerySet, "first", new=miss_lifecycle_once),
        fixture.runtime.repository.atomic(),
    ):
        replayed_evidence = fixture.runtime.repository.claim_lifecycle_authorization(
            event_ref=event_ref,
            authorization=event_bundle.evidence.authorization,
            reason_codes=event_bundle.evidence.reason_codes,
        )
    assert replayed_evidence == event_bundle.evidence
    event_row = R4PromotionLifecycleEventModel._default_manager.get()
    with (
        patch.object(
            fixture.runtime.repository,
            "_get_lifecycle_event_collision",
            side_effect=[None, event_row],
        ),
        fixture.runtime.repository.atomic(),
    ):
        assert (
            fixture.runtime.repository.append_lifecycle_event_bundle(event_bundle) == event_bundle
        )
    assert R4PromotionPolicyModel._default_manager.count() == 1
    assert R4PromotionDecisionReceiptModel._default_manager.count() == 1
    assert R4PromotionDecisionBundleModel._default_manager.count() == 1
    assert R4PromotionLifecycleAuthorizationReceiptModel._default_manager.count() == 1
    assert R4PromotionLifecycleEventModel._default_manager.count() == 1


@pytest.mark.django_db(transaction=True)
def test_same_output_or_event_identity_with_different_evidence_conflicts() -> None:
    fixture = _runtime()
    _register_policy(fixture)
    decision = _evaluate(fixture, suffix="identity-conflict")
    fixture.clock.value = DECISION_RECORDED_AT + timedelta(minutes=2)
    record = fixture.portfolio.owner_record.record
    conflicting = EvaluateR4PromotionCommand(
        output_decision_ref=R4PromotionVersionRef(
            decision.decision_id,
            decision.decision_version,
        ),
        output_trial_ref=R4PromotionVersionRef(
            decision.trial.trial_id,
            decision.trial.trial_version,
        ),
        policy_ref=R4PromotionVersionRef(
            decision.policy.policy_id,
            decision.policy.policy_version,
        ),
        portfolio_record_id=record.record_id,
        expected_portfolio_record_hash=record.record_hash,
        as_of=DECIDED_AT + timedelta(minutes=1),
    )
    with pytest.raises(R4PromotionRepositoryConflict, match="identity conflict"):
        fixture.runtime.evaluate.execute(conflicting)

    event, _ = _promote_root(fixture, decision)
    event_ref = R4PromotionVersionRef(event.event_id, event.event_version)
    with fixture.runtime.repository.atomic():
        bundle = fixture.runtime.repository.get_lifecycle_event_bundle(event_ref)
    assert bundle is not None
    changed_reasons = ("substituted_owner_reason",)
    original = bundle.evidence.authorization
    changed = R4PromotionLifecycleAuthorization.create(
        authorization_id=original.authorization_id,
        authorization_version=original.authorization_version,
        event_type=original.event_type,
        decision=decision,
        rollback_target=None,
        reason_codes=changed_reasons,
        issued_at=original.issued_at,
        recorded_at=original.recorded_at,
        valid_until=original.valid_until,
    )
    with (
        fixture.runtime.repository.atomic(),
        pytest.raises(R4PromotionRepositoryConflict, match="identity conflict"),
    ):
        fixture.runtime.repository.claim_lifecycle_authorization(
            event_ref=event_ref,
            authorization=changed,
            reason_codes=changed_reasons,
        )
    assert R4PromotionDecisionReceiptModel._default_manager.count() == 1
    assert R4PromotionLifecycleAuthorizationReceiptModel._default_manager.count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("collision", ("sequence", "previous"))
def test_stream_fork_unique_collision_rolls_back_loser_receipt(collision: str) -> None:
    fixture = _runtime()
    _register_policy(fixture)
    first = _evaluate(fixture, suffix=f"fork-a-{collision}")
    second = _evaluate(
        fixture,
        suffix=f"fork-b-{collision}",
        decided_at=DECIDED_AT + timedelta(minutes=10),
        recorded_at=DECISION_RECORDED_AT + timedelta(minutes=10),
    )
    third = _evaluate(
        fixture,
        suffix=f"fork-c-{collision}",
        decided_at=DECIDED_AT + timedelta(minutes=20),
        recorded_at=DECISION_RECORDED_AT + timedelta(minutes=20),
    )
    root, _ = _promote_root(fixture, first)
    winner = _append_action(
        fixture,
        event_id=f"r4-fork-winner-{collision}",
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=second,
        after=root.recorded_at,
    )
    loser_command = _prepare_action(
        fixture,
        event_id=f"r4-fork-loser-{collision}",
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=third,
        after=winner.recorded_at,
    )
    claim = fixture.authorization_source.claim
    assert claim is not None
    receipts_before = R4PromotionLifecycleAuthorizationReceiptModel._default_manager.count()
    events_before = R4PromotionLifecycleEventModel._default_manager.count()

    with pytest.raises(IntegrityError), fixture.runtime.repository.atomic():
        evidence = fixture.runtime.repository.claim_lifecycle_authorization(
            event_ref=loser_command.output_event_ref,
            authorization=claim.authorization,
            reason_codes=claim.reason_codes,
        )
        stale_event = create_r4_promotion_lifecycle_event(
            event_id=loser_command.output_event_ref.stable_id,
            event_version=loser_command.output_event_ref.version,
            previous_events=(root,),
            event_type=R4PromotionLifecycleEventType.PROMOTED,
            decision=third,
            rollback_target=None,
            authorization=evidence.authorization,
            reason_codes=evidence.reason_codes,
            occurred_at=evidence.occurred_at,
            recorded_at=evidence.event_recorded_at,
        )
        stale_bundle = R4PromotionLifecycleEventBundle.create(
            event=stale_event,
            evidence=evidence,
        )
        receipt_model = R4PromotionLifecycleAuthorizationReceiptModel._default_manager.get(
            event_id=stale_event.event_id
        )
        root_model = R4PromotionLifecycleEventModel._default_manager.get(event_id=root.event_id)
        winner_model = R4PromotionLifecycleEventModel._default_manager.get(event_id=winner.event_id)
        values = _lifecycle_event_model_values(stale_bundle)
        previous_model = root_model
        if collision == "sequence":
            previous_model = winner_model
        else:
            values["sequence"] = 3
        claim_values = {
            **values,
            "receipt_id": receipt_model.pk,
            "decision_id": receipt_model.decision_id,
            "rollback_target_id": None,
            "previous_event_id": previous_model.pk,
        }
        with _claim_r4_promotion_insert(
            token=fixture.runtime.repository._unit_of_work_token,
            model_type=R4PromotionLifecycleEventModel,
            expected_values=claim_values,
        ):
            R4PromotionLifecycleEventModel._default_manager.create(
                receipt=receipt_model,
                decision=receipt_model.decision,
                rollback_target=None,
                previous_event=previous_model,
                **values,
            )

    assert R4PromotionLifecycleAuthorizationReceiptModel._default_manager.count() == receipts_before
    assert R4PromotionLifecycleEventModel._default_manager.count() == events_before


@pytest.mark.django_db(transaction=True)
def test_raw_header_tamper_fails_closed_on_decision_and_lifecycle_restore() -> None:
    fixture = _runtime()
    _register_policy(fixture)
    decision = _evaluate(fixture)
    event, command = _promote_root(fixture, decision)
    decision_row = R4PromotionDecisionBundleModel._default_manager.get()
    event_row = R4PromotionLifecycleEventModel._default_manager.get()

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r4_promotion_decision_bundle "
            "SET portfolio_record_hash = %s WHERE id = %s",
            ["0" * 64, decision_row.pk],
        )
    with fixture.runtime.repository.atomic():
        with pytest.raises(R4PromotionRepositoryCorruption, match="header"):
            fixture.runtime.repository.get_decision_bundle(
                R4PromotionVersionRef(decision.decision_id, decision.decision_version),
                as_of=event.recorded_at,
            )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r4_promotion_decision_bundle "
            "SET portfolio_record_hash = %s WHERE id = %s",
            [decision.trial.portfolio_record.record_hash, decision_row.pk],
        )
        cursor.execute(
            "UPDATE research_r4_promotion_lifecycle_event "
            "SET scope_content_hash = %s WHERE id = %s",
            ["f" * 64, event_row.pk],
        )
    with fixture.runtime.repository.atomic():
        with pytest.raises(R4PromotionRepositoryCorruption, match="header"):
            fixture.runtime.repository.load_lifecycle_history(
                command.scope_ref,
                as_of=event.recorded_at,
            )


@pytest.mark.django_db(transaction=True)
def test_active_dynamic_reread_fails_closed_and_expired_decision_can_retire() -> None:
    fixture = _runtime()
    _register_policy(fixture)
    decision = _evaluate(fixture, suffix="dynamic")
    root, command = _promote_root(fixture, decision)

    fixture.r3.attestation = promotion_attestation(retired_at=root.recorded_at)
    assert fixture.runtime.active.get_active(command.scope_ref, as_of=root.recorded_at) is None
    fixture.r3.attestation = promotion_attestation()
    original_record = fixture.portfolio.owner_record
    fixture.portfolio.owner_record = R4RollingResearchOwnerRecord.create(
        portfolio_record(study=build_study(minimum_regime_windows=3))
    )
    assert fixture.runtime.active.get_active(command.scope_ref, as_of=root.recorded_at) is None
    fixture.portfolio.owner_record = original_record

    retired = _append_action(
        fixture,
        event_id="r4-persisted-expired-retire",
        action=R4PromotionLifecycleAction.RETIRE,
        decision=decision,
        after=decision.valid_until + timedelta(minutes=1),
    )
    assert retired.event_type is R4PromotionLifecycleEventType.RETIRED
    assert retired.occurred_at > decision.valid_until
    assert (
        fixture.runtime.active.get_active(
            command.scope_ref,
            as_of=retired.recorded_at,
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_payload_receipt_fk_and_previous_fk_tamper_each_fail_closed() -> None:
    fixture = _runtime()
    _register_policy(fixture)
    decision = _evaluate(fixture, suffix="deep-tamper-a")
    root, command = _promote_root(fixture, decision)
    policy_row = R4PromotionPolicyModel._default_manager.get()
    original_payload = policy_row.canonical_payload
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r4_promotion_policy SET canonical_payload = %s WHERE id = %s",
            [json.dumps({}), policy_row.pk],
        )
    with fixture.runtime.repository.atomic():
        with pytest.raises(R4PromotionCodecError):
            fixture.runtime.policy_provider.get_exact(
                R4PromotionVersionRef(policy_row.policy_id, policy_row.policy_version),
                as_of=POLICY_ACTIVE_FROM,
            )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r4_promotion_policy SET canonical_payload = %s WHERE id = %s",
            [json.dumps(original_payload), policy_row.pk],
        )

    other_draft = replace(
        R4PromotionPolicyRegistrationDraft.from_policy(promotion_policy()),
        policy_id="r4-promotion-policy-tamper-other",
    )
    fixture.clock.value = POLICY_RECORDED_AT + timedelta(days=1)
    fixture.runtime.repository.append_policy(other_draft)
    other_policy = R4PromotionPolicyModel._default_manager.get(policy_id=other_draft.policy_id)
    receipt_row = R4PromotionDecisionReceiptModel._default_manager.get()
    original_policy_id = receipt_row.policy_id
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r4_promotion_decision_receipt SET policy_id = %s WHERE id = %s",
            [other_policy.pk, receipt_row.pk],
        )
    with fixture.runtime.repository.atomic():
        with pytest.raises(R4PromotionRepositoryCorruption, match="policy FK"):
            fixture.runtime.repository.get_decision_bundle(
                R4PromotionVersionRef(decision.decision_id, decision.decision_version),
                as_of=root.recorded_at,
            )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r4_promotion_decision_receipt SET policy_id = %s WHERE id = %s",
            [original_policy_id, receipt_row.pk],
        )

    second = _evaluate(
        fixture,
        suffix="deep-tamper-b",
        decided_at=DECIDED_AT + timedelta(minutes=10),
        recorded_at=DECISION_RECORDED_AT + timedelta(minutes=10),
    )
    promoted = _append_action(
        fixture,
        event_id="r4-persisted-deep-tamper-b",
        action=R4PromotionLifecycleAction.PROMOTE,
        decision=second,
        after=root.recorded_at,
    )
    promoted_row = R4PromotionLifecycleEventModel._default_manager.get(event_id=promoted.event_id)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r4_promotion_lifecycle_event "
            "SET previous_event_id = %s WHERE id = %s",
            [promoted_row.pk, promoted_row.pk],
        )
    with fixture.runtime.repository.atomic():
        with pytest.raises(R4PromotionRepositoryCorruption, match="previous FK"):
            fixture.runtime.repository.load_lifecycle_stream(command.scope_ref)
