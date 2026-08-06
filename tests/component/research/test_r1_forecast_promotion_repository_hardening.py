"""Adversarial component coverage for the Research R1 promotion ledger."""

from __future__ import annotations

import inspect
import json
from copy import copy, deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from typing import cast
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.db.models import QuerySet

from apps.equity.application.forecast_baseline_materialize import VersionRef
from apps.equity.application.forecast_baseline_query import (
    ExactForecastBaselineTrialRecord,
)
from apps.equity.infrastructure.forecast_baseline_models import (
    ForecastBaselineTrialResultModel,
)
from apps.research.application.r1_forecast_promotion import (
    AppendR1PromotionLifecycleCommand,
    AppendR1PromotionLifecycleEventUseCase,
    EvaluateR1ForecastPromotionCommand,
    EvaluateR1ForecastPromotionUseCase,
    ExactR1LifecycleAuthorizationEvidence,
    R1ActiveForecastPromotionProvider,
    R1PromotionDecisionReceipt,
    R1PromotionLifecycleAction,
    R1PromotionLifecycleEventBundle,
    R1PromotionScopeRef,
    R1PromotionVersionRef,
)
from apps.research.domain.r1_forecast_promotion import (
    R1ForecastPromotionDecision,
    R1ForecastPromotionPolicy,
    R1PromotionLifecycleAuthorization,
    R1PromotionLifecycleEvent,
    R1PromotionLifecycleEventType,
    create_r1_promotion_lifecycle_event,
)
from apps.research.infrastructure.r1_forecast_promotion_codec import (
    encode_r1_lifecycle_authorization_evidence,
)
from apps.research.infrastructure.r1_forecast_promotion_models import (
    R1_OWNER_RECEIPT_CLOCK_SKEW,
    R1ForecastPromotionDecisionBundleModel,
    R1ForecastPromotionPolicyModel,
    R1PromotionDecisionReceiptModel,
    R1PromotionLifecycleEventBundleModel,
    R1PromotionLifecycleReceiptModel,
)
from apps.research.infrastructure.r1_forecast_promotion_repository import (
    DjangoExactEquityTrialResultProvider,
    DjangoR1DecisionReceiptProvider,
    DjangoR1LifecycleAuthorizationProvider,
    DjangoR1PromotionPolicyProvider,
    R1LifecycleAuthorizationClaim,
    R1PromotionRepositoryConflict,
    R1PromotionRepositoryCorruption,
    _lifecycle_event_model_values,
    r1_lifecycle_authorization_claim_id,
)
from tests.component.research.test_r1_forecast_promotion_repository import (
    _append_lifecycle,
    _AuthorizationSource,
    _evaluate,
    _Runtime,
    _runtime,
)

pytestmark = pytest.mark.django_db


def _raw_update(table: str, column: str, value: object, row_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET {column} = %s WHERE id = %s",  # noqa: S608
            [value, row_id],
        )


def _tagged_fields(payload: object, type_name: str) -> dict[str, object]:
    if isinstance(payload, dict):
        if payload.get("$type") == type_name:
            tagged_fields = payload.get("$fields")
            if isinstance(tagged_fields, dict):
                return cast(dict[str, object], tagged_fields)
        for value in payload.values():
            try:
                return _tagged_fields(value, type_name)
            except KeyError:
                continue
    if isinstance(payload, list):
        for value in payload:
            try:
                return _tagged_fields(value, type_name)
            except KeyError:
                continue
    raise KeyError(type_name)


def _evaluate_command(
    runtime: _Runtime,
    *,
    suffix: str,
    as_of: datetime,
) -> tuple[EvaluateR1ForecastPromotionCommand, R1ForecastPromotionDecision]:
    command = replace(
        runtime.command,
        output_decision_ref=R1PromotionVersionRef(
            f"research-r1-promotion:{suffix}",
            "decision.v1",
        ),
        as_of=as_of,
    )
    receipt_at = as_of + timedelta(minutes=1)
    use_case = EvaluateR1ForecastPromotionUseCase(
        policy_provider=DjangoR1PromotionPolicyProvider(runtime.repository),
        trial_result_provider=runtime.equity_provider,
        receipt_provider=DjangoR1DecisionReceiptProvider(runtime.repository),
        repository=runtime.repository,
    )
    with (
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_repository.timezone.now",
            return_value=receipt_at,
        ),
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_models.timezone.now",
            return_value=receipt_at,
        ),
    ):
        return command, use_case.execute(command)


def _lifecycle_command(
    *,
    decision: R1ForecastPromotionDecision,
    event_id: str,
    action: R1PromotionLifecycleAction,
    occurred_at: datetime,
    reasons: tuple[str, ...],
    rollback_target: R1ForecastPromotionDecision | None = None,
) -> tuple[
    AppendR1PromotionLifecycleCommand,
    _AuthorizationSource,
]:
    event_ref = R1PromotionVersionRef(event_id, "event.v1")
    provisional = R1PromotionLifecycleAuthorization.create(
        authorization_id=f"provisional:{event_id}",
        authorization_version="authorization.v1",
        owner="research",
        capability="r1",
        purpose="valuation",
        event_type=action.event_type,
        decision=decision,
        rollback_target=rollback_target,
        reason_codes=reasons,
        issued_at=occurred_at - timedelta(minutes=2),
        recorded_at=occurred_at - timedelta(minutes=1),
        valid_until=occurred_at + timedelta(hours=1),
    )
    authorization = R1PromotionLifecycleAuthorization.create(
        authorization_id=r1_lifecycle_authorization_claim_id(
            event_ref=event_ref,
            authorization=provisional,
        ),
        authorization_version="authorization.v1",
        owner="research",
        capability="r1",
        purpose="valuation",
        event_type=action.event_type,
        decision=decision,
        rollback_target=rollback_target,
        reason_codes=reasons,
        issued_at=provisional.issued_at,
        recorded_at=provisional.recorded_at,
        valid_until=provisional.valid_until,
    )
    command = AppendR1PromotionLifecycleCommand(
        output_event_ref=event_ref,
        scope_ref=R1PromotionScopeRef(decision.promotion_scope.scope_id),
        action=action,
        decision_ref=R1PromotionVersionRef(
            decision.decision_id,
            decision.decision_version,
        ),
        authorization_ref=R1PromotionVersionRef(
            authorization.authorization_id,
            authorization.authorization_version,
        ),
        rollback_target_ref=(
            R1PromotionVersionRef(
                rollback_target.decision_id,
                rollback_target.decision_version,
            )
            if rollback_target is not None
            else None
        ),
    )
    return command, _AuthorizationSource(R1LifecycleAuthorizationClaim(authorization, reasons))


def _append_command(
    runtime: _Runtime,
    command: AppendR1PromotionLifecycleCommand,
    source: _AuthorizationSource,
    *,
    occurred_at: datetime,
) -> R1PromotionLifecycleEvent:
    use_case = AppendR1PromotionLifecycleEventUseCase(
        authorization_provider=DjangoR1LifecycleAuthorizationProvider(
            runtime.repository,
            owner_source=source,
        ),
        repository=runtime.repository,
    )
    with (
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_repository.timezone.now",
            return_value=occurred_at,
        ),
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_models.timezone.now",
            return_value=occurred_at,
        ),
    ):
        return use_case.execute(command)


def _second_decision(runtime: _Runtime) -> R1ForecastPromotionDecision:
    _, decision = _evaluate_command(
        runtime,
        suffix="component-second",
        as_of=runtime.command.as_of + timedelta(minutes=5),
    )
    return decision


def _recreate_policy(
    policy: R1ForecastPromotionPolicy,
    *,
    policy_id: str,
) -> R1ForecastPromotionPolicy:
    values = {
        name: getattr(policy, name)
        for name in inspect.signature(R1ForecastPromotionPolicy.create).parameters
    }
    values["policy_id"] = policy_id
    return R1ForecastPromotionPolicy.create(**values)


def test_concrete_equity_query_hides_future_and_missing_owner_rows() -> None:
    """Knowledge-time reads expose neither future nor absent Equity evidence."""

    runtime = _runtime()
    assert (
        runtime.equity_provider.get_exact(
            runtime.command.equity_result_ref,
            as_of=runtime.trial_recorded_at - timedelta(microseconds=1),
        )
        is None
    )
    exact = runtime.equity_provider.get_exact(
        runtime.command.equity_result_ref,
        as_of=runtime.trial_recorded_at,
    )
    assert exact is not None
    assert exact.result == runtime.trial
    assert exact.recorded_at == runtime.trial_recorded_at
    assert (
        runtime.equity_provider.get_exact(
            R1PromotionVersionRef("missing-trial", "result.v1"),
            as_of=runtime.command.as_of,
        )
        is None
    )


class _SubstitutingEquityQuery:
    unit_of_work_key = "django:default"

    def __init__(self, runtime: _Runtime) -> None:
        self._runtime = runtime

    def get_exact(
        self,
        trial_ref: VersionRef,
        *,
        as_of: datetime,
    ) -> ExactForecastBaselineTrialRecord | None:
        del trial_ref, as_of
        row = ForecastBaselineTrialResultModel._default_manager.get(
            result_id=self._runtime.trial.result_id
        )
        return ExactForecastBaselineTrialRecord(
            result=self._runtime.trial,
            recorded_at=self._runtime.trial_recorded_at,
            owner_record_key=cast(int, row.pk),
        )


def test_equity_adapter_rejects_substituted_identity_and_typed_row_tamper() -> None:
    """The cross-app adapter and Equity typed restore both fail closed."""

    runtime = _runtime()
    substituting = DjangoExactEquityTrialResultProvider(_SubstitutingEquityQuery(runtime))
    with pytest.raises(R1PromotionRepositoryCorruption, match="substituted trial identity"):
        substituting.get_exact(
            R1PromotionVersionRef("another-result", "result.v1"),
            as_of=runtime.command.as_of,
        )

    row = ForecastBaselineTrialResultModel._default_manager.get(result_id=runtime.trial.result_id)
    _raw_update(
        "equity_forecast_baseline_trial_result",
        "content_hash",
        "f" * 64,
        cast(int, row.pk),
    )
    with pytest.raises(ValueError, match="header/payload"):
        runtime.equity_provider.get_exact(
            runtime.command.equity_result_ref,
            as_of=runtime.command.as_of,
        )


def test_exact_retry_and_first_miss_receipt_and_bundle_races_replay_winner() -> None:
    """Stable retries and both first-miss race windows return one complete winner."""

    runtime = _runtime()
    first = _evaluate(runtime)
    second = _evaluate(runtime)
    assert second == first
    assert R1PromotionDecisionReceiptModel._default_manager.count() == 1
    assert R1ForecastPromotionDecisionBundleModel._default_manager.count() == 1
    bundle = runtime.repository.get_decision_bundle(
        runtime.command.output_decision_ref,
        as_of=first.recorded_at,
    )
    assert bundle is not None

    original_first = QuerySet.first
    receipt_missed = False

    def miss_receipt_once(queryset: QuerySet[object]) -> object | None:
        nonlocal receipt_missed
        if queryset.model is R1PromotionDecisionReceiptModel and not receipt_missed:
            receipt_missed = True
            return None
        return original_first(queryset)

    with (
        patch.object(QuerySet, "first", new=miss_receipt_once),
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_repository.timezone.now",
            return_value=bundle.receipt.recorded_at,
        ),
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_models.timezone.now",
            return_value=bundle.receipt.recorded_at,
        ),
        runtime.repository.atomic(),
    ):
        replayed_receipt = runtime.repository.claim_decision_receipt(
            decision_ref=runtime.command.output_decision_ref,
            policy_ref=runtime.command.policy_ref,
            policy_content_hash=runtime.policy.content_hash,
            result_ref=runtime.command.equity_result_ref,
            result_content_hash=runtime.trial.content_hash,
            equity_result_recorded_at=bundle.receipt.equity_result_recorded_at,
            equity_result_record_hash=bundle.receipt.equity_result_record_hash,
            decided_at=first.decided_at,
            decision_valid_until=first.valid_until,
        )
    assert replayed_receipt == bundle.receipt
    assert receipt_missed

    bundle_missed = False

    def miss_bundle_once(queryset: QuerySet[object]) -> object | None:
        nonlocal bundle_missed
        if queryset.model is R1ForecastPromotionDecisionBundleModel and not bundle_missed:
            bundle_missed = True
            return None
        return original_first(queryset)

    with (
        patch.object(QuerySet, "first", new=miss_bundle_once),
        runtime.repository.atomic(),
    ):
        replayed_bundle = runtime.repository.append_decision_bundle(bundle)
    assert replayed_bundle == bundle
    assert bundle_missed
    assert R1PromotionDecisionReceiptModel._default_manager.count() == 1
    assert R1ForecastPromotionDecisionBundleModel._default_manager.count() == 1


def test_same_output_identity_with_different_evidence_conflicts_without_partial_rows() -> None:
    """A stable output identity cannot be rebound to a later decision clock."""

    runtime = _runtime()
    first = _evaluate(runtime)
    conflicting = replace(
        runtime.command,
        as_of=runtime.command.as_of + timedelta(minutes=2),
    )
    receipt_at = conflicting.as_of + timedelta(minutes=1)
    use_case = EvaluateR1ForecastPromotionUseCase(
        policy_provider=DjangoR1PromotionPolicyProvider(runtime.repository),
        trial_result_provider=runtime.equity_provider,
        receipt_provider=DjangoR1DecisionReceiptProvider(runtime.repository),
        repository=runtime.repository,
    )
    with (
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_repository.timezone.now",
            return_value=receipt_at,
        ),
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_models.timezone.now",
            return_value=receipt_at,
        ),
        pytest.raises(R1PromotionRepositoryConflict, match="identity conflict"),
    ):
        use_case.execute(conflicting)
    stored = runtime.repository.get_decision_bundle(
        runtime.command.output_decision_ref,
        as_of=first.recorded_at,
    )
    assert stored is not None and stored.decision == first
    assert R1PromotionDecisionReceiptModel._default_manager.count() == 1
    assert R1ForecastPromotionDecisionBundleModel._default_manager.count() == 1


def test_lifecycle_receipt_and_event_first_miss_race_windows_replay_winner() -> None:
    """Both lifecycle first-miss race windows replay the complete stored winner."""

    runtime = _runtime()
    decision = _evaluate(runtime)
    event = _append_lifecycle(runtime, decision)
    event_ref = R1PromotionVersionRef(event.event_id, event.event_version)
    bundle = runtime.repository.get_lifecycle_event_bundle(event_ref)
    assert bundle is not None
    original_first = QuerySet.first
    receipt_missed = False

    def miss_receipt_once(queryset: QuerySet[object]) -> object | None:
        nonlocal receipt_missed
        if queryset.model is R1PromotionLifecycleReceiptModel and not receipt_missed:
            receipt_missed = True
            return None
        return original_first(queryset)

    with (
        patch.object(QuerySet, "first", new=miss_receipt_once),
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_repository.timezone.now",
            return_value=event.occurred_at,
        ),
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_models.timezone.now",
            return_value=event.occurred_at,
        ),
        runtime.repository.atomic(),
    ):
        replayed_evidence = runtime.repository.claim_lifecycle_authorization(
            event_ref=event_ref,
            authorization=bundle.evidence.authorization,
            reason_codes=bundle.evidence.reason_codes,
        )
    assert replayed_evidence == bundle.evidence
    assert receipt_missed

    event_missed = False

    def miss_event_once(queryset: QuerySet[object]) -> object | None:
        nonlocal event_missed
        if queryset.model is R1PromotionLifecycleEventBundleModel and not event_missed:
            event_missed = True
            return None
        return original_first(queryset)

    with (
        patch.object(QuerySet, "first", new=miss_event_once),
        runtime.repository.atomic(),
    ):
        replayed_bundle = runtime.repository.append_lifecycle_event_bundle(bundle)
    assert replayed_bundle == bundle
    assert event_missed
    assert R1PromotionLifecycleReceiptModel._default_manager.count() == 1
    assert R1PromotionLifecycleEventBundleModel._default_manager.count() == 1


def test_same_event_identity_with_different_owner_evidence_conflicts() -> None:
    """A canonical event ID cannot be rebound to different reasons or authorization."""

    runtime = _runtime()
    decision = _evaluate(runtime)
    event = _append_lifecycle(runtime, decision)
    bundle = runtime.repository.get_lifecycle_event_bundle(
        R1PromotionVersionRef(event.event_id, event.event_version)
    )
    assert bundle is not None
    original = bundle.evidence.authorization
    changed_reasons = ("substituted_owner_reason",)
    changed_authorization = R1PromotionLifecycleAuthorization.create(
        authorization_id=original.authorization_id,
        authorization_version=original.authorization_version,
        owner=original.owner,
        capability=original.capability,
        purpose=original.purpose,
        event_type=original.event_type,
        decision=decision,
        rollback_target=None,
        reason_codes=changed_reasons,
        issued_at=original.issued_at,
        recorded_at=original.recorded_at,
        valid_until=original.valid_until,
    )
    with (
        runtime.repository.atomic(),
        pytest.raises(R1PromotionRepositoryConflict, match="identity conflict"),
    ):
        runtime.repository.claim_lifecycle_authorization(
            event_ref=bundle.evidence.event_ref,
            authorization=changed_authorization,
            reason_codes=changed_reasons,
        )
    assert R1PromotionLifecycleReceiptModel._default_manager.count() == 1
    assert R1PromotionLifecycleEventBundleModel._default_manager.count() == 1


@pytest.mark.parametrize("collision", ("sequence", "previous"))
def test_stream_fork_loser_rolls_back_its_receipt(collision: str) -> None:
    """Each stream uniqueness race rolls back its receipt and preserves the winner."""

    runtime = _runtime()
    first = _evaluate(runtime)
    root_event = _append_lifecycle(runtime, first)
    second = _second_decision(runtime)
    second_at = max(root_event.recorded_at, second.recorded_at) + timedelta(minutes=10)
    second_command, second_source = _lifecycle_command(
        decision=second,
        event_id="research-r1-promotion-event:fork-winner",
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=second_at,
        reasons=("replacement_promotion_approved",),
    )
    winner_event = _append_command(
        runtime,
        second_command,
        second_source,
        occurred_at=second_at,
    )
    _, third = _evaluate_command(
        runtime,
        suffix="component-fork-loser",
        as_of=runtime.command.as_of + timedelta(minutes=15),
    )
    loser_at = max(winner_event.recorded_at, third.recorded_at) + timedelta(minutes=10)
    loser_command, loser_source = _lifecycle_command(
        decision=third,
        event_id=f"research-r1-promotion-event:fork-loser:{collision}",
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=loser_at,
        reasons=("stale_prefix_replacement",),
    )
    receipts_before = R1PromotionLifecycleReceiptModel._default_manager.count()
    events_before = R1PromotionLifecycleEventBundleModel._default_manager.count()
    with (
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_repository.timezone.now",
            return_value=loser_at,
        ),
        patch(
            "apps.research.infrastructure.r1_forecast_promotion_models.timezone.now",
            return_value=loser_at,
        ),
        pytest.raises(IntegrityError),
        runtime.repository.atomic(),
    ):
        evidence = runtime.repository.claim_lifecycle_authorization(
            event_ref=loser_command.output_event_ref,
            authorization=loser_source.claim.authorization,
            reason_codes=loser_source.claim.reason_codes,
        )
        stale_candidate = create_r1_promotion_lifecycle_event(
            event_id=loser_command.output_event_ref.stable_id,
            event_version=loser_command.output_event_ref.version,
            previous_events=(root_event,),
            event_type=R1PromotionLifecycleEventType.PROMOTED,
            decision=third,
            rollback_target=None,
            authorization=evidence.authorization,
            reason_codes=evidence.reason_codes,
            occurred_at=evidence.occurred_at,
            recorded_at=evidence.event_recorded_at,
        )
        stale_bundle = R1PromotionLifecycleEventBundle.create(
            event=stale_candidate,
            evidence=evidence,
        )
        receipt_model = R1PromotionLifecycleReceiptModel._default_manager.get(
            event_id=stale_candidate.event_id
        )
        root_model = R1PromotionLifecycleEventBundleModel._default_manager.get(
            event_id=root_event.event_id
        )
        winner_model = R1PromotionLifecycleEventBundleModel._default_manager.get(
            event_id=winner_event.event_id
        )
        model_values = _lifecycle_event_model_values(stale_bundle)
        previous_model = root_model
        if collision == "sequence":
            previous_model = winner_model
        else:
            model_values["sequence"] = 3
        R1PromotionLifecycleEventBundleModel._default_manager.create(
            receipt=receipt_model,
            decision=receipt_model.decision,
            rollback_target=None,
            previous_event=previous_model,
            **model_values,
        )
    assert R1PromotionLifecycleReceiptModel._default_manager.count() == receipts_before
    assert R1PromotionLifecycleEventBundleModel._default_manager.count() == events_before
    assert runtime.repository.load_lifecycle_stream(
        R1PromotionScopeRef(first.promotion_scope.scope_id)
    ) == (root_event, winner_event)


def test_server_receipt_clocks_reject_stale_and_future_direct_rows() -> None:
    """Direct inserts cannot forge decision or either lifecycle server clock."""

    runtime = _runtime()
    decision = _evaluate(runtime)
    _append_lifecycle(runtime, decision)
    decision_row = R1PromotionDecisionReceiptModel._default_manager.get()
    decision_now = decision_row.recorded_at
    for invalid_clock in (
        decision_now - R1_OWNER_RECEIPT_CLOCK_SKEW - timedelta(microseconds=1),
        decision_now + timedelta(microseconds=1),
    ):
        forged_decision = copy(decision_row)
        forged_decision.pk = None
        forged_decision._state.adding = True
        forged_decision.recorded_at = invalid_clock
        with (
            patch(
                "apps.research.infrastructure.r1_forecast_promotion_models.timezone.now",
                return_value=decision_now,
            ),
            pytest.raises(ValidationError, match="Research owner repository"),
        ):
            forged_decision.save()

    lifecycle_row = R1PromotionLifecycleReceiptModel._default_manager.get()
    lifecycle_now = lifecycle_row.event_recorded_at
    for field_name in ("occurred_at", "event_recorded_at"):
        for invalid_clock in (
            lifecycle_now - R1_OWNER_RECEIPT_CLOCK_SKEW - timedelta(microseconds=1),
            lifecycle_now + timedelta(microseconds=1),
        ):
            forged_lifecycle = copy(lifecycle_row)
            forged_lifecycle.pk = None
            forged_lifecycle._state.adding = True
            forged_lifecycle.occurred_at = lifecycle_now
            forged_lifecycle.event_recorded_at = lifecycle_now
            setattr(forged_lifecycle, field_name, invalid_clock)
            with (
                patch(
                    "apps.research.infrastructure.r1_forecast_promotion_models.timezone.now",
                    return_value=lifecycle_now,
                ),
                pytest.raises(ValidationError, match="Research owner repository"),
            ):
                forged_lifecycle.save()
    assert R1PromotionDecisionReceiptModel._default_manager.count() == 1
    assert R1PromotionLifecycleReceiptModel._default_manager.count() == 1


def test_all_managers_and_explicit_zero_pk_cannot_bypass_append_only_guards() -> None:
    """Default/base/related managers reject every mutation and bulk shortcut."""

    runtime = _runtime()
    decision = _evaluate(runtime)
    _append_lifecycle(runtime, decision)
    model_types = (
        R1ForecastPromotionPolicyModel,
        R1PromotionDecisionReceiptModel,
        R1ForecastPromotionDecisionBundleModel,
        R1PromotionLifecycleReceiptModel,
        R1PromotionLifecycleEventBundleModel,
    )
    for model_type in model_types:
        row = model_type._default_manager.first()
        assert row is not None
        for manager in (model_type._default_manager, model_type._base_manager):
            with pytest.raises(ValidationError, match="(?i)append-only"):
                manager.filter(pk=row.pk).update(owner="tampered")
            with pytest.raises(ValidationError, match="(?i)append-only"):
                manager.bulk_update([row], ["owner"])
            with pytest.raises(ValidationError, match="cannot be deleted"):
                manager.filter(pk=row.pk).delete()
            for kwargs in (
                {},
                {"ignore_conflicts": True},
                {
                    "update_conflicts": True,
                    "update_fields": ["owner"],
                    "unique_fields": ["id"],
                },
            ):
                with pytest.raises(ValidationError, match="exact append"):
                    manager.bulk_create([row], **kwargs)
        explicit_zero = copy(row)
        explicit_zero.pk = 0
        explicit_zero._state.adding = True
        owner_clock = getattr(
            row,
            "event_recorded_at",
            getattr(row, "recorded_at", datetime.now().astimezone()),
        )
        with (
            patch(
                "apps.research.infrastructure.r1_forecast_promotion_models.timezone.now",
                return_value=owner_clock,
            ),
            pytest.raises(ValidationError, match="(?i)append-only"),
        ):
            explicit_zero.save()
        with pytest.raises(ValidationError, match="(?i)append-only"):
            row.save()
        with pytest.raises(ValidationError, match="(?i)append-only"):
            row.save(force_update=True)
        with pytest.raises(ValidationError, match="(?i)append-only"):
            row.save(update_fields=["owner"])
        with pytest.raises(ValidationError, match="cannot be deleted"):
            row.delete()

    policy = R1ForecastPromotionPolicyModel._default_manager.get()
    receipt = R1PromotionDecisionReceiptModel._default_manager.get()
    with pytest.raises(ValidationError, match="(?i)append-only"):
        policy.decision_receipts.update(owner="tampered")
    with pytest.raises(ValidationError, match="(?i)append-only"):
        policy.decision_receipts.bulk_update([receipt], ["owner"])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        policy.decision_receipts.all().delete()
    with pytest.raises(ValidationError, match="(?i)append-only"):
        policy.decision_receipts.add(receipt, bulk=True)
    with pytest.raises(ValidationError, match="(?i)append-only"):
        policy.decision_receipts.add(receipt, bulk=False)


@pytest.mark.parametrize(
    ("column", "value"),
    (("receipt_id", "forged-receipt"), ("receipt_version", "receipt.v999")),
)
def test_decision_receipt_rejects_forged_deterministic_identity(
    column: str,
    value: str,
) -> None:
    """Raw rows cannot choose a noncanonical decision receipt ID/version."""

    runtime = _runtime()
    decision = _evaluate(runtime)
    bundle = runtime.repository.get_decision_bundle(
        runtime.command.output_decision_ref,
        as_of=decision.recorded_at,
    )
    assert bundle is not None
    original = bundle.receipt
    forged = R1PromotionDecisionReceipt.create(
        receipt_id=value if column == "receipt_id" else original.receipt_id,
        receipt_version=(value if column == "receipt_version" else original.receipt_version),
        decision_ref=original.decision_ref,
        policy_ref=original.policy_ref,
        policy_content_hash=original.policy_content_hash,
        result_ref=original.result_ref,
        result_content_hash=original.result_content_hash,
        equity_result_recorded_at=original.equity_result_recorded_at,
        equity_result_record_hash=original.equity_result_record_hash,
        decided_at=original.decided_at,
        recorded_at=original.recorded_at,
        decision_valid_until=original.decision_valid_until,
    )
    row = R1PromotionDecisionReceiptModel._default_manager.get()
    for forged_column, forged_value in (
        ("receipt_id", forged.receipt_id),
        ("receipt_version", forged.receipt_version),
        ("content_hash", forged.content_hash),
    ):
        _raw_update(
            row._meta.db_table,
            forged_column,
            forged_value,
            cast(int, row.pk),
        )
    with pytest.raises(R1PromotionRepositoryCorruption, match="claim identity"):
        runtime.repository.get_decision_bundle(
            runtime.command.output_decision_ref,
            as_of=decision.recorded_at,
        )


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("authorization_id", "forged-authorization"),
        ("authorization_version", "authorization.v999"),
    ),
)
def test_lifecycle_receipt_rejects_forged_deterministic_identity(
    column: str,
    value: str,
) -> None:
    """Raw rows cannot choose a noncanonical lifecycle authorization identity."""

    runtime = _runtime()
    decision = _evaluate(runtime)
    event = _append_lifecycle(runtime, decision)
    row = R1PromotionLifecycleReceiptModel._default_manager.get()
    bundle = runtime.repository.get_lifecycle_event_bundle(
        R1PromotionVersionRef(event.event_id, event.event_version)
    )
    assert bundle is not None
    original = bundle.evidence.authorization
    forged_authorization = R1PromotionLifecycleAuthorization.create(
        authorization_id=(value if column == "authorization_id" else original.authorization_id),
        authorization_version=(
            value if column == "authorization_version" else original.authorization_version
        ),
        owner=original.owner,
        capability=original.capability,
        purpose=original.purpose,
        event_type=original.event_type,
        decision=decision,
        rollback_target=None,
        reason_codes=bundle.evidence.reason_codes,
        issued_at=original.issued_at,
        recorded_at=original.recorded_at,
        valid_until=original.valid_until,
    )
    forged_evidence = ExactR1LifecycleAuthorizationEvidence.create(
        event_ref=bundle.evidence.event_ref,
        authorization=forged_authorization,
        reason_codes=bundle.evidence.reason_codes,
        occurred_at=bundle.evidence.occurred_at,
        event_recorded_at=bundle.evidence.event_recorded_at,
    )
    for forged_column, forged_value in (
        ("authorization_id", forged_authorization.authorization_id),
        ("authorization_version", forged_authorization.authorization_version),
        ("authorization_content_hash", forged_authorization.content_hash),
        ("evidence_content_hash", forged_evidence.content_hash),
        (
            "canonical_payload",
            json.dumps(encode_r1_lifecycle_authorization_evidence(forged_evidence)),
        ),
    ):
        _raw_update(
            row._meta.db_table,
            forged_column,
            forged_value,
            cast(int, row.pk),
        )
    with pytest.raises(R1PromotionRepositoryCorruption, match="claim identity"):
        runtime.repository.get_lifecycle_event_bundle(
            R1PromotionVersionRef(event.event_id, event.event_version)
        )


def test_policy_decision_and_event_headers_and_payloads_fail_closed() -> None:
    """Independent policy, decision and event raw substitutions are detected."""

    runtime = _runtime()
    decision = _evaluate(runtime)
    event = _append_lifecycle(runtime, decision)

    policy_row = R1ForecastPromotionPolicyModel._default_manager.get()
    _raw_update(
        policy_row._meta.db_table,
        "status",
        "inactive",
        cast(int, policy_row.pk),
    )
    with pytest.raises(R1PromotionRepositoryCorruption, match="header/payload"):
        runtime.repository.get_exact_policy(
            runtime.command.policy_ref,
            as_of=runtime.command.as_of,
        )

    _raw_update(
        policy_row._meta.db_table,
        "status",
        runtime.policy.status.value,
        cast(int, policy_row.pk),
    )
    decision_row = R1ForecastPromotionDecisionBundleModel._default_manager.get()
    original_decision_payload = deepcopy(decision_row.canonical_payload)
    decision_payload = deepcopy(original_decision_payload)
    _tagged_fields(decision_payload, "R1ForecastPromotionDecisionBundle")["content_hash"] = "0" * 64
    _raw_update(
        decision_row._meta.db_table,
        "canonical_payload",
        json.dumps(decision_payload),
        cast(int, decision_row.pk),
    )
    with pytest.raises(ValueError, match="validation|restore|hash"):
        runtime.repository.get_decision_bundle(
            runtime.command.output_decision_ref,
            as_of=decision.recorded_at,
        )

    _raw_update(
        decision_row._meta.db_table,
        "canonical_payload",
        json.dumps(original_decision_payload),
        cast(int, decision_row.pk),
    )
    event_row = R1PromotionLifecycleEventBundleModel._default_manager.get(event_id=event.event_id)
    original_event_payload = deepcopy(event_row.canonical_payload)
    event_payload = deepcopy(original_event_payload)
    _tagged_fields(event_payload, "R1PromotionLifecycleEventBundle")["content_hash"] = "0" * 64
    _raw_update(
        event_row._meta.db_table,
        "canonical_payload",
        json.dumps(event_payload),
        cast(int, event_row.pk),
    )
    with pytest.raises(ValueError, match="validation|restore|hash"):
        runtime.repository.get_lifecycle_event_bundle(
            R1PromotionVersionRef(event.event_id, event.event_version)
        )
    _raw_update(
        event_row._meta.db_table,
        "canonical_payload",
        json.dumps(original_event_payload),
        cast(int, event_row.pk),
    )
    _raw_update(
        event_row._meta.db_table,
        "scope_content_hash",
        "f" * 64,
        cast(int, event_row.pk),
    )
    with pytest.raises(R1PromotionRepositoryCorruption, match="header/payload"):
        runtime.repository.get_lifecycle_event_bundle(
            R1PromotionVersionRef(event.event_id, event.event_version)
        )


def test_decision_and_event_foreign_key_substitution_fails_closed() -> None:
    """Decision/event FKs cannot disagree with their receipts or payload identities."""

    runtime = _runtime()
    first = _evaluate(runtime)
    second = _second_decision(runtime)
    event = _append_lifecycle(runtime, first)
    first_bundle = R1ForecastPromotionDecisionBundleModel._default_manager.get(
        decision_id=first.decision_id
    )
    second_bundle = R1ForecastPromotionDecisionBundleModel._default_manager.get(
        decision_id=second.decision_id
    )
    other_policy = _recreate_policy(
        runtime.policy,
        policy_id="research-r1-forecast-promotion:other",
    )
    runtime.repository.append_policy(other_policy)
    other_policy_row = R1ForecastPromotionPolicyModel._default_manager.get(
        policy_id=other_policy.policy_id
    )

    _raw_update(
        first_bundle._meta.db_table,
        "policy_id",
        other_policy_row.pk,
        cast(int, first_bundle.pk),
    )
    with pytest.raises(R1PromotionRepositoryCorruption, match="foreign keys"):
        runtime.repository.get_decision_bundle(
            runtime.command.output_decision_ref,
            as_of=first.recorded_at,
        )

    _raw_update(
        first_bundle._meta.db_table,
        "policy_id",
        first_bundle.receipt.policy_id,
        cast(int, first_bundle.pk),
    )
    event_row = R1PromotionLifecycleEventBundleModel._default_manager.get(event_id=event.event_id)
    _raw_update(
        event_row._meta.db_table,
        "decision_id",
        second_bundle.pk,
        cast(int, event_row.pk),
    )
    with pytest.raises(R1PromotionRepositoryCorruption, match="foreign keys"):
        runtime.repository.get_lifecycle_event_bundle(
            R1PromotionVersionRef(event.event_id, event.event_version)
        )

    _raw_update(
        event_row._meta.db_table,
        "decision_id",
        first_bundle.pk,
        cast(int, event_row.pk),
    )
    _raw_update(
        event_row._meta.db_table,
        "rollback_target_id",
        second_bundle.pk,
        cast(int, event_row.pk),
    )
    with pytest.raises(R1PromotionRepositoryCorruption, match="foreign keys"):
        runtime.repository.get_lifecycle_event_bundle(
            R1PromotionVersionRef(event.event_id, event.event_version)
        )


def test_non_tail_retry_prefix_visibility_retirement_and_expiry() -> None:
    """Full replay accepts non-tail retries while knowledge-time reads use prefixes."""

    runtime = _runtime()
    first = _evaluate(runtime)
    first_event = _append_lifecycle(runtime, first)
    second = _second_decision(runtime)
    promote_at = max(first_event.recorded_at, second.recorded_at) + timedelta(minutes=10)
    promote_command, promote_source = _lifecycle_command(
        decision=second,
        event_id="research-r1-promotion-event:second",
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=promote_at,
        reasons=("replacement_promotion_approved",),
    )
    second_event = _append_command(
        runtime,
        promote_command,
        promote_source,
        occurred_at=promote_at,
    )
    retire_at = second_event.recorded_at + timedelta(minutes=10)
    retire_command, retire_source = _lifecycle_command(
        decision=second,
        event_id="research-r1-promotion-event:retire",
        action=R1PromotionLifecycleAction.RETIRE,
        occurred_at=retire_at,
        reasons=("research_promotion_retired",),
    )
    retire_event = _append_command(
        runtime,
        retire_command,
        retire_source,
        occurred_at=retire_at,
    )

    root_command, root_source = _lifecycle_command(
        decision=first,
        event_id=first_event.event_id,
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=first_event.occurred_at,
        reasons=first_event.reason_codes,
    )
    assert (
        _append_command(
            runtime,
            root_command,
            root_source,
            occurred_at=first_event.occurred_at,
        )
        == first_event
    )
    active_provider = R1ActiveForecastPromotionProvider(
        policy_provider=DjangoR1PromotionPolicyProvider(runtime.repository),
        trial_result_provider=runtime.equity_provider,
        repository=runtime.repository,
    )
    before_retire = active_provider.get_active(
        R1PromotionScopeRef(first.promotion_scope.scope_id),
        as_of=retire_event.recorded_at - timedelta(microseconds=1),
    )
    assert before_retire is not None and before_retire.decision == second
    assert (
        active_provider.get_active(
            R1PromotionScopeRef(first.promotion_scope.scope_id),
            as_of=retire_event.recorded_at,
        )
        is None
    )
    assert runtime.repository.load_lifecycle_stream(
        R1PromotionScopeRef(first.promotion_scope.scope_id)
    ) == (first_event, second_event, retire_event)
    assert (
        active_provider.get_active(
            R1PromotionScopeRef(first.promotion_scope.scope_id),
            as_of=second.valid_until,
        )
        is None
    )


def test_unretired_active_decision_expires_at_exact_valid_until_boundary() -> None:
    """Expiry, independently of retirement, changes active to absent at the boundary."""

    runtime = _runtime()
    decision = _evaluate(runtime)
    _append_lifecycle(runtime, decision)
    provider = R1ActiveForecastPromotionProvider(
        policy_provider=DjangoR1PromotionPolicyProvider(runtime.repository),
        trial_result_provider=runtime.equity_provider,
        repository=runtime.repository,
    )
    scope_ref = R1PromotionScopeRef(decision.promotion_scope.scope_id)
    before_expiry = provider.get_active(
        scope_ref,
        as_of=decision.valid_until - timedelta(microseconds=1),
    )
    assert before_expiry is not None and before_expiry.decision == decision
    assert provider.get_active(scope_ref, as_of=decision.valid_until) is None


def test_exact_rollback_restores_previous_decision_and_previous_fk_tamper_fails() -> None:
    """Rollback restores the exact stack target and stream FK rewrites fail closed."""

    runtime = _runtime()
    first = _evaluate(runtime)
    first_event = _append_lifecycle(runtime, first)
    second = _second_decision(runtime)
    promote_at = max(first_event.recorded_at, second.recorded_at) + timedelta(minutes=10)
    promote_command, promote_source = _lifecycle_command(
        decision=second,
        event_id="research-r1-promotion-event:second-for-rollback",
        action=R1PromotionLifecycleAction.PROMOTE,
        occurred_at=promote_at,
        reasons=("replacement_promotion_approved",),
    )
    second_event = _append_command(
        runtime,
        promote_command,
        promote_source,
        occurred_at=promote_at,
    )
    rollback_at = second_event.recorded_at + timedelta(minutes=10)
    rollback_command, rollback_source = _lifecycle_command(
        decision=second,
        event_id="research-r1-promotion-event:rollback",
        action=R1PromotionLifecycleAction.ROLLBACK,
        occurred_at=rollback_at,
        reasons=("replacement_failed_validation",),
        rollback_target=first,
    )
    rollback_event = _append_command(
        runtime,
        rollback_command,
        rollback_source,
        occurred_at=rollback_at,
    )
    active_provider = R1ActiveForecastPromotionProvider(
        policy_provider=DjangoR1PromotionPolicyProvider(runtime.repository),
        trial_result_provider=runtime.equity_provider,
        repository=runtime.repository,
    )
    active = active_provider.get_active(
        R1PromotionScopeRef(first.promotion_scope.scope_id),
        as_of=rollback_event.recorded_at,
    )
    assert active is not None and active.decision == first

    second_row = R1PromotionLifecycleEventBundleModel._default_manager.get(
        event_id=second_event.event_id
    )
    rollback_row = R1PromotionLifecycleEventBundleModel._default_manager.get(
        event_id=rollback_event.event_id
    )
    _raw_update(
        second_row._meta.db_table,
        "previous_event_id",
        rollback_row.pk,
        cast(int, second_row.pk),
    )
    with pytest.raises(R1PromotionRepositoryCorruption, match="previous-event FK"):
        runtime.repository.get_lifecycle_event_bundle(
            R1PromotionVersionRef(rollback_event.event_id, rollback_event.event_version)
        )
