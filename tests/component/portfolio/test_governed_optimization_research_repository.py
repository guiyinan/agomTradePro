"""Component coverage for the append-only governed R8 result ledger."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.portfolio.application.governed_optimization import GovernedOptimizationRunBundle
from apps.portfolio.domain._optimization_canonical import hash_components
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.domain.optimization_lifecycle import (
    OptimizationLifecycleEventType,
    OptimizationLifecycleOwnerAttestation,
    create_optimization_lifecycle_event,
    create_optimization_lifecycle_root,
    derive_optimization_lifecycle_state,
)
from apps.portfolio.domain.optimization_research_result import (
    GovernedOptimizationResearchResult,
)
from apps.portfolio.infrastructure.optimization_research_models import (
    GovernedOptimizationResearchResultModel,
    OptimizationResearchLifecycleEventModel,
)
from apps.portfolio.infrastructure.optimization_research_repository import (
    DjangoGovernedOptimizationResearchRepository,
)

NOW = datetime(2026, 8, 5, 9, tzinfo=UTC)
LATER = NOW + timedelta(days=30)


def _result(*, blocker: str = "external_evidence_missing") -> GovernedOptimizationResearchResult:
    return GovernedOptimizationResearchResult.create(
        run_key="governed-r8-run",
        run_version="run.v1",
        assembly_hash="1" * 64,
        problem_id="problem:r8:v1",
        problem_hash="2" * 64,
        input_set_id="input-set:r8:v1",
        input_set_hash="3" * 64,
        candidate_evaluations=(),
        problem_blockers=(("optimization_problem.blocked", blocker),),
        evaluated_at=NOW,
        valid_until=LATER,
    )


def _bundle(*, blocker: str = "external_evidence_missing") -> GovernedOptimizationRunBundle:
    result = _result(blocker=blocker)
    return GovernedOptimizationRunBundle(
        result=result,
        lifecycle_root=create_optimization_lifecycle_root(result),
    )


@pytest.mark.django_db
def test_bundle_round_trip_is_exact_idempotent_and_hash_chained() -> None:
    repository = DjangoGovernedOptimizationResearchRepository()
    bundle = _bundle()

    assert repository.append_bundle(bundle) == bundle
    assert repository.append_bundle(bundle) == bundle
    assert repository.get_result(bundle.result.result_id) == bundle.result
    events = repository.list_lifecycle_events(bundle.result.result_id)
    assert events == (bundle.lifecycle_root,)
    assert derive_optimization_lifecycle_state(events).value == "research"
    assert GovernedOptimizationResearchResultModel._default_manager.count() == 1
    assert OptimizationResearchLifecycleEventModel._default_manager.count() == 1


@pytest.mark.django_db
def test_same_run_identity_with_different_evidence_is_rejected() -> None:
    repository = DjangoGovernedOptimizationResearchRepository()
    repository.append_bundle(_bundle())

    with pytest.raises(ValueError, match="conflicts with different result evidence"):
        repository.append_bundle(_bundle(blocker="different_external_blocker"))


@pytest.mark.django_db
def test_exact_r8_promotion_and_owner_attested_retirement_extend_chain() -> None:
    repository = DjangoGovernedOptimizationResearchRepository()
    bundle = _bundle()
    repository.append_bundle(bundle)
    promotion = ExactPromotionAttestation.create(
        capability_key="r8",
        artifact_id=bundle.result.result_id,
        artifact_version=bundle.result.result_version,
        artifact_content_hash=bundle.result.content_hash,
        decision_id="promotion:r8:v1",
        decision_content_hash="4" * 64,
        owner="research",
        approved_at=NOW + timedelta(hours=1),
        valid_until=LATER,
    )
    promoted = create_optimization_lifecycle_event(
        result=bundle.result,
        previous_events=repository.list_lifecycle_events(bundle.result.result_id),
        event_type=OptimizationLifecycleEventType.PROMOTION_ATTESTED,
        occurred_at=NOW + timedelta(hours=1),
        recorded_at=NOW + timedelta(hours=1),
        reason_codes=("research_promotion_approved",),
        promotion_attestation=promotion,
    )
    repository.append_lifecycle_event(promoted)
    reasons = ("methodology_retired",)
    owner = OptimizationLifecycleOwnerAttestation.create(
        attestation_id="owner-attestation:r8:retire:v1",
        owner="portfolio",
        result_id=bundle.result.result_id,
        result_hash=bundle.result.content_hash,
        event_type=OptimizationLifecycleEventType.RETIRED,
        reason_hash=hash_components("optimization-lifecycle-reasons.v1", *reasons),
        issued_at=NOW + timedelta(hours=2),
    )
    retired = create_optimization_lifecycle_event(
        result=bundle.result,
        previous_events=repository.list_lifecycle_events(bundle.result.result_id),
        event_type=OptimizationLifecycleEventType.RETIRED,
        occurred_at=NOW + timedelta(hours=2),
        recorded_at=NOW + timedelta(hours=2),
        reason_codes=reasons,
        owner_attestation=owner,
    )
    repository.append_lifecycle_event(retired)

    events = repository.list_lifecycle_events(bundle.result.result_id)
    assert [item.sequence for item in events] == [1, 2, 3]
    assert derive_optimization_lifecycle_state(events).value == "retired"


@pytest.mark.django_db
def test_default_base_related_and_conflict_update_paths_are_append_only() -> None:
    repository = DjangoGovernedOptimizationResearchRepository()
    bundle = _bundle()
    repository.append_bundle(bundle)
    result = GovernedOptimizationResearchResultModel._default_manager.get()
    event = OptimizationResearchLifecycleEventModel._default_manager.get()

    for manager, row in (
        (GovernedOptimizationResearchResultModel._default_manager, result),
        (GovernedOptimizationResearchResultModel._base_manager, result),
        (OptimizationResearchLifecycleEventModel._default_manager, event),
        (OptimizationResearchLifecycleEventModel._base_manager, event),
    ):
        with pytest.raises(ValidationError, match="cannot be updated"):
            manager.filter(pk=row.pk).update(content_hash="0" * 64)
        with pytest.raises(ValidationError, match="cannot be deleted"):
            manager.filter(pk=row.pk).delete()
        with pytest.raises(ValidationError, match="bulk updated"):
            manager.bulk_update([row], ["content_hash"])
        with pytest.raises(ValidationError, match="update on conflict"):
            manager.all().bulk_create(
                [type(row)()],
                update_conflicts=True,
                update_fields=["content_hash"],
                unique_fields=[row._meta.pk.name],
            )
        with pytest.raises(ValidationError, match="ignore or update on conflict"):
            manager.all().bulk_create(
                [type(row)()],
                ignore_conflicts=True,
            )
    with pytest.raises(ValidationError, match="cannot be updated"):
        result.lifecycle_events.all().update(content_hash="0" * 64)
    with pytest.raises(ValidationError, match="append-only"):
        result.save()
    with pytest.raises(ValidationError, match="append-only"):
        event.delete()


@pytest.mark.django_db
def test_concurrent_first_lookup_miss_rechecks_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = DjangoGovernedOptimizationResearchRepository()
    bundle = _bundle()
    repository.append_bundle(bundle)
    manager = GovernedOptimizationResearchResultModel._default_manager
    original_filter = manager.filter
    first_call = True

    def first_lookup_misses(*args: object, **kwargs: object):
        nonlocal first_call
        queryset = original_filter(*args, **kwargs)
        if first_call:
            first_call = False
            return queryset.none()
        return queryset

    monkeypatch.setattr(manager, "filter", first_lookup_misses)

    assert repository.append_bundle(bundle) == bundle
    assert GovernedOptimizationResearchResultModel._default_manager.count() == 1


@pytest.mark.django_db
def test_child_failure_rolls_back_result_and_raw_tamper_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = DjangoGovernedOptimizationResearchRepository()
    original_save = OptimizationResearchLifecycleEventModel.save

    def fail_save(self, *args: object, **kwargs: object) -> None:
        raise ValidationError("fault injection")

    monkeypatch.setattr(OptimizationResearchLifecycleEventModel, "save", fail_save)
    with pytest.raises(ValueError, match="invalid governed optimization result bundle"):
        repository.append_bundle(_bundle())
    assert GovernedOptimizationResearchResultModel._default_manager.count() == 0
    assert OptimizationResearchLifecycleEventModel._default_manager.count() == 0

    monkeypatch.setattr(OptimizationResearchLifecycleEventModel, "save", original_save)
    bundle = _bundle()
    repository.append_bundle(bundle)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_governed_optimization_result "
            "SET problem_hash = %s WHERE result_id = %s",
            ["9" * 64, bundle.result.result_id],
        )
    with pytest.raises(ValueError, match="content hash mismatch"):
        repository.get_result(bundle.result.result_id)


def test_lifecycle_and_result_tamper_are_rejected_in_memory() -> None:
    bundle = _bundle()
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(bundle.result, problem_hash="9" * 64)
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(bundle.lifecycle_root, result_hash="9" * 64)
