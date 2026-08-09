"""Component coverage for the append-only governed R8 result ledger."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models.deletion import Collector

from apps.portfolio.application.governed_optimization import GovernedOptimizationRunBundle
from apps.portfolio.domain._optimization_canonical import hash_components
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.domain.optimization_input_receipt import (
    GovernedOptimizationInputReceipt,
)
from apps.portfolio.domain.optimization_lifecycle import (
    OptimizationLifecycleEventType,
    OptimizationLifecycleOwnerAttestation,
    create_optimization_lifecycle_event,
    create_optimization_lifecycle_root,
    derive_optimization_lifecycle_state,
)
from apps.portfolio.domain.optimization_research_result import (
    GovernedOptimizationResearchResult,
    governed_result_hash_values,
)
from apps.portfolio.infrastructure.optimization_input_receipt_repository import (
    DjangoGovernedOptimizationInputReceiptRepository,
    DjangoGovernedOptimizationUnitOfWork,
)
from apps.portfolio.infrastructure.optimization_research_codec import (
    _result_payload,
    result_model,
)
from apps.portfolio.infrastructure.optimization_research_models import (
    GovernedOptimizationInputReceiptModel,
    GovernedOptimizationResearchResultModel,
    OptimizationAppendOnlyQuerySet,
    OptimizationResearchLifecycleEventModel,
    _claim_governed_optimization_insert,
)
from apps.portfolio.infrastructure.optimization_research_repository import (
    DjangoGovernedOptimizationResearchRepository,
    _insert_values,
)
from tests.unit.portfolio.test_governed_optimization_inputs import _input_set

NOW = datetime(2026, 8, 5, 9, tzinfo=UTC)
LATER = NOW + timedelta(days=30)
INPUT_SET = _input_set()
INPUT_RECEIPT = GovernedOptimizationInputReceipt.record(
    input_set=INPUT_SET,
    server_recorded_at=NOW,
)


class _Clock:
    def now(self) -> datetime:
        return NOW


def _repository() -> DjangoGovernedOptimizationResearchRepository:
    unit_of_work = DjangoGovernedOptimizationUnitOfWork()
    receipts = DjangoGovernedOptimizationInputReceiptRepository(
        unit_of_work=unit_of_work,
        clock=_Clock(),
    )
    with unit_of_work.atomic():
        receipts._store_verified(INPUT_SET, NOW)
    return DjangoGovernedOptimizationResearchRepository(
        unit_of_work=unit_of_work,
        receipt_provider=receipts,
    )


def _result(*, blocker: str = "external_evidence_missing") -> GovernedOptimizationResearchResult:
    return GovernedOptimizationResearchResult.create(
        run_key="governed-r8-run",
        run_version="run.v1",
        assembly_hash="1" * 64,
        problem_id="problem:r8:v1",
        problem_hash="2" * 64,
        input_set_id=INPUT_SET.input_set_id,
        input_set_hash=INPUT_SET.content_hash,
        input_receipt_id=INPUT_RECEIPT.receipt_id,
        input_receipt_hash=INPUT_RECEIPT.content_hash,
        input_receipt_schema_version=INPUT_RECEIPT.receipt_version,
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


def _legacy_result() -> GovernedOptimizationResearchResult:
    source = _result()
    content_hash = governed_result_hash_values(
        result_version="governed-optimization-result.v1",
        run_key=source.run_key,
        run_version=source.run_version,
        assembly_hash=source.assembly_hash,
        problem_id=source.problem_id,
        problem_hash=source.problem_hash,
        input_set_id=source.input_set_id,
        input_set_hash=source.input_set_hash,
        input_receipt_id=None,
        input_receipt_hash=None,
        input_receipt_schema_version=None,
        status=source.status,
        candidates=source.candidates,
        selected_candidate=source.selected_candidate,
        problem_blockers=source.problem_blockers,
        evaluated_at=source.evaluated_at,
        valid_until=source.valid_until,
    )
    return replace(
        source,
        result_id=f"governed_optimization_result:{content_hash[:24]}",
        result_version="governed-optimization-result.v1",
        input_receipt_id=None,
        input_receipt_hash=None,
        input_receipt_schema_version=None,
        content_hash=content_hash,
    )


@pytest.mark.django_db
def test_bundle_round_trip_is_exact_idempotent_and_hash_chained() -> None:
    repository = _repository()
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
    repository = _repository()
    repository.append_bundle(_bundle())

    with pytest.raises(ValueError, match="conflicts with different result evidence"):
        repository.append_bundle(_bundle(blocker="different_external_blocker"))


@pytest.mark.django_db
def test_exact_r8_promotion_and_owner_attested_retirement_extend_chain() -> None:
    repository = _repository()
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
    repository = _repository()
    bundle = _bundle()
    repository.append_bundle(bundle)
    receipt = GovernedOptimizationInputReceiptModel._default_manager.get()
    result = GovernedOptimizationResearchResultModel._default_manager.get()
    event = OptimizationResearchLifecycleEventModel._default_manager.get()

    for manager, row in (
        (GovernedOptimizationInputReceiptModel._default_manager, receipt),
        (GovernedOptimizationInputReceiptModel._base_manager, receipt),
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
        with pytest.raises(ValidationError, match="requires exact appends"):
            manager.all().bulk_create(
                [type(row)()],
                update_conflicts=True,
                update_fields=["content_hash"],
                unique_fields=[row._meta.pk.name],
            )
        with pytest.raises(ValidationError, match="requires exact appends"):
            manager.all().bulk_create(
                [type(row)()],
                ignore_conflicts=True,
            )
        with pytest.raises(ValidationError, match="requires exact appends"):
            manager.all().bulk_create([type(row)()])
        with pytest.raises(ValidationError, match="cannot be updated"):
            manager.all()._update([])
        with pytest.raises(ValidationError, match="cannot be deleted"):
            manager.all()._raw_delete("default")
        with pytest.raises(ValidationError, match="private bulk insert is forbidden"):
            manager.all()._batched_insert([], [], None)
        with pytest.raises(ValidationError, match="get_or_create is forbidden"):
            manager.get_or_create(pk=row.pk)
        with pytest.raises(ValidationError, match="update_or_create is forbidden"):
            manager.update_or_create(pk=row.pk, defaults={"content_hash": "0" * 64})
        with pytest.raises(ValidationError, match="raw manager queries are forbidden"):
            tuple(manager.raw(f"SELECT * FROM {row._meta.db_table}"))
        with pytest.raises(ValidationError, match="requires an exact insert claim"):
            manager.all()._insert([row], [])
    with pytest.raises(ValidationError, match="cannot be updated"):
        result.lifecycle_events.all().update(content_hash="0" * 64)
    with pytest.raises(ValidationError, match="cannot be updated"):
        receipt.research_results.all().update(content_hash="0" * 64)
    with pytest.raises(ValidationError, match="get_or_create is forbidden"):
        receipt.research_results.get_or_create(pk=result.pk)
    with pytest.raises(ValidationError, match="update_or_create is forbidden"):
        result.lifecycle_events.update_or_create(
            pk=event.pk,
            defaults={"content_hash": "0" * 64},
        )
    with pytest.raises(ValidationError, match="append-only"):
        receipt.save()
    with pytest.raises(ValidationError, match="append-only"):
        result.save()
    with pytest.raises(ValidationError, match="append-only"):
        result.save_base(force_update=True)
    with pytest.raises(ValidationError, match="append-only"):
        event.delete()
    collector = Collector(using="default")
    collector.collect([event])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        collector.delete()


@pytest.mark.django_db
def test_concurrent_first_lookup_miss_rechecks_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository()
    bundle = _bundle()
    repository.append_bundle(bundle)
    original_filter = OptimizationAppendOnlyQuerySet.filter
    result_lookup_calls = 0

    def first_two_result_lookups_miss(
        self: OptimizationAppendOnlyQuerySet[GovernedOptimizationResearchResultModel],
        *args: object,
        **kwargs: object,
    ):
        nonlocal result_lookup_calls
        queryset = original_filter(self, *args, **kwargs)
        if self.model is GovernedOptimizationResearchResultModel and {
            "run_key",
            "run_version",
        } <= set(kwargs):
            result_lookup_calls += 1
            if result_lookup_calls <= 2:
                return queryset.none()
        return queryset

    monkeypatch.setattr(
        OptimizationAppendOnlyQuerySet,
        "filter",
        first_two_result_lookups_miss,
    )

    assert repository.append_bundle(bundle) == bundle
    assert GovernedOptimizationResearchResultModel._default_manager.count() == 1
    assert result_lookup_calls >= 3


@pytest.mark.django_db
def test_child_failure_rolls_back_result_and_raw_tamper_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository()
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


@pytest.mark.django_db
def test_valid_legacy_null_result_requires_explicit_research_read_only() -> None:
    unit_of_work = DjangoGovernedOptimizationUnitOfWork()
    receipts = DjangoGovernedOptimizationInputReceiptRepository(
        unit_of_work=unit_of_work,
        clock=_Clock(),
    )
    with unit_of_work.atomic():
        receipts._store_verified(INPUT_SET, NOW)
    repository = DjangoGovernedOptimizationResearchRepository(
        unit_of_work=unit_of_work,
        receipt_provider=receipts,
    )
    receipt_row = GovernedOptimizationInputReceiptModel._default_manager.get()
    current = _result()
    legacy = _legacy_result()
    row = result_model(current, receipt_row)
    row.input_receipt = None
    row.result_id = legacy.result_id
    row.result_version = legacy.result_version
    row.content_hash = legacy.content_hash
    row.canonical_payload = _result_payload(legacy)
    with (
        unit_of_work.atomic(),
        _claim_governed_optimization_insert(
            token=unit_of_work._insert_claim_token(),
            model_type=GovernedOptimizationResearchResultModel,
            expected_values=_insert_values(row),
        ),
    ):
        row.save(force_insert=True)

    assert repository.get_legacy_research_result(legacy.result_id) == legacy
    with pytest.raises(ValueError, match="explicit research-only read"):
        repository.get_result(legacy.result_id)
    with pytest.raises(ValueError, match="explicit research-only read"):
        repository.list_lifecycle_events(legacy.result_id)
    with pytest.raises(ValueError, match="different input receipt"):
        repository.append_bundle(_bundle())


@pytest.mark.django_db
def test_null_or_legacy_alias_receipt_relation_is_corruption_on_normal_reads() -> None:
    repository = _repository()
    bundle = _bundle()
    repository.append_bundle(bundle)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_governed_optimization_result "
            "SET input_receipt_id = NULL WHERE result_id = %s",
            [bundle.result.result_id],
        )

    with pytest.raises(ValueError, match="explicit research-only read"):
        repository.get_result(bundle.result.result_id)
    with pytest.raises(ValueError, match="null input receipt"):
        repository.get_legacy_research_result(bundle.result.result_id)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_governed_optimization_result "
            "SET input_receipt_id = %s, result_version = %s WHERE result_id = %s",
            [
                INPUT_RECEIPT.receipt_id,
                "governed-optimization-result.v1",
                bundle.result.result_id,
            ],
        )

    with pytest.raises(ValueError, match="legacy optimization result cannot alias"):
        repository.get_result(bundle.result.result_id)
    with pytest.raises(ValueError, match="legacy optimization result cannot alias"):
        repository.get_legacy_research_result(bundle.result.result_id)


def test_lifecycle_and_result_tamper_are_rejected_in_memory() -> None:
    bundle = _bundle()
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(bundle.result, problem_hash="9" * 64)
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(bundle.lifecycle_root, result_hash="9" * 64)
