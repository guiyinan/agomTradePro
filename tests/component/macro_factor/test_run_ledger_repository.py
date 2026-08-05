"""Component tests for the append-only reproducible R3 run ledger."""

import json
from dataclasses import replace
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.macro_factor.domain.entities import RetirementEvidence
from apps.macro_factor.domain.lifecycle import append_retirement_event
from apps.macro_factor.domain.runner_service import build_reproducible_run
from apps.macro_factor.infrastructure.models import MacroFactorResearchResultModel
from apps.macro_factor.infrastructure.run_ledger_models import (
    MacroFactorDatedOutputModel,
    MacroFactorLifecycleEventModel,
    MacroFactorRunArtifactModel,
)
from apps.macro_factor.infrastructure.run_ledger_repository import (
    DjangoMacroFactorRunLedgerRepository,
)
from tests.unit.macro_factor.factories import complete_manifest
from tests.unit.macro_factor.runner_factories import (
    external_runner_artifact,
    retirement_owner_attestation,
    runner_dataset,
    runner_spec,
)

pytestmark = pytest.mark.django_db


def _bundle():  # type: ignore[no-untyped-def]
    return build_reproducible_run(
        runner_spec(),
        runner_dataset(),
        complete_manifest(),
        external_runner_artifact(),
    )


def test_repository_round_trips_source_run_outputs_and_root_event() -> None:
    repository = DjangoMacroFactorRunLedgerRepository()
    bundle = _bundle()

    stored = repository.append_bundle(bundle)

    assert stored is bundle
    assert repository.get_artifact(bundle.artifact.artifact_id) == bundle.artifact
    assert repository.list_outputs(bundle.artifact.artifact_id) == bundle.outputs
    assert repository.list_lifecycle_events(bundle.artifact.artifact_id) == (
        bundle.lifecycle_events
    )
    assert MacroFactorResearchResultModel._default_manager.count() == 1
    assert MacroFactorRunArtifactModel._default_manager.count() == 1
    assert MacroFactorDatedOutputModel._default_manager.count() == 1
    assert MacroFactorLifecycleEventModel._default_manager.count() == 1


def test_exact_replay_is_idempotent_and_conflicting_run_identity_is_rejected() -> None:
    repository = DjangoMacroFactorRunLedgerRepository()
    bundle = _bundle()
    repository.append_bundle(bundle)

    replay = repository.append_bundle(bundle)

    assert replay is bundle
    assert MacroFactorRunArtifactModel._default_manager.count() == 1
    assert MacroFactorDatedOutputModel._default_manager.count() == 1
    assert MacroFactorLifecycleEventModel._default_manager.count() == 1

    conflicting_artifact = replace(bundle.artifact, benchmark_hash="8" * 64)
    with pytest.raises(ValueError):
        repository.append_bundle(replace(bundle, artifact=conflicting_artifact))


def test_repository_rejects_validly_rehashed_cross_identity_bundle_members() -> None:
    repository = DjangoMacroFactorRunLedgerRepository()
    bundle = _bundle()
    invalid_bundles = (
        replace(
            bundle,
            artifact=replace(bundle.artifact, factor_version="macro-growth-crossed"),
        ),
        replace(
            bundle,
            outputs=(replace(bundle.outputs[0], target_code="crossed-target"),),
        ),
        replace(
            bundle,
            lifecycle_events=(
                replace(bundle.lifecycle_events[0], factor_version="macro-growth-crossed"),
            ),
        ),
    )

    for invalid_bundle in invalid_bundles:
        with pytest.raises(ValueError):
            repository.append_bundle(invalid_bundle)

    assert MacroFactorResearchResultModel._default_manager.count() == 0
    assert MacroFactorRunArtifactModel._default_manager.count() == 0
    assert MacroFactorDatedOutputModel._default_manager.count() == 0
    assert MacroFactorLifecycleEventModel._default_manager.count() == 0


def test_model_clean_rejects_validly_rehashed_cross_identity_rows() -> None:
    repository = DjangoMacroFactorRunLedgerRepository()
    bundle = _bundle()
    repository.append_bundle(bundle)

    artifact_model = MacroFactorRunArtifactModel._default_manager.select_related(
        "source_result"
    ).get()
    forged_artifact = replace(bundle.artifact, factor_version="macro-growth-crossed")
    artifact_model.factor_version = forged_artifact.factor_version
    artifact_model.content_hash = forged_artifact.content_hash
    artifact_model.payload = json.loads(forged_artifact.canonical_json)
    with pytest.raises(ValidationError, match="invalid macro-factor run artifact"):
        artifact_model.full_clean()

    output_model = MacroFactorDatedOutputModel._default_manager.select_related(
        "artifact__source_result"
    ).get()
    forged_output = replace(bundle.outputs[0], target_code="crossed-target")
    output_model.target_code = forged_output.target_code
    output_model.content_hash = forged_output.content_hash
    output_model.payload = json.loads(forged_output.canonical_json)
    with pytest.raises(ValidationError, match="invalid macro-factor dated output"):
        output_model.full_clean()

    event_model = MacroFactorLifecycleEventModel._default_manager.select_related(
        "artifact__source_result"
    ).get()
    forged_event = replace(
        bundle.lifecycle_events[0],
        factor_version="macro-growth-crossed",
    )
    event_model.factor_version = forged_event.factor_version
    event_model.content_hash = forged_event.content_hash
    event_model.payload = json.loads(forged_event.canonical_json)
    with pytest.raises(ValidationError, match="invalid macro-factor lifecycle event"):
        event_model.full_clean()


def test_concurrent_run_winner_is_rechecked_under_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = DjangoMacroFactorRunLedgerRepository()
    bundle = _bundle()
    repository.append_bundle(bundle)
    manager = MacroFactorRunArtifactModel._default_manager
    original_filter = manager.filter
    first_call = True

    def first_lookup_misses(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal first_call
        queryset = original_filter(*args, **kwargs)
        if first_call:
            first_call = False
            return queryset.none()
        return queryset

    monkeypatch.setattr(manager, "filter", first_lookup_misses)

    assert repository.append_bundle(bundle) is bundle
    assert MacroFactorRunArtifactModel._default_manager.count() == 1


def test_default_base_and_related_manager_mutations_are_blocked() -> None:
    repository = DjangoMacroFactorRunLedgerRepository()
    bundle = _bundle()
    repository.append_bundle(bundle)
    artifact_model = MacroFactorRunArtifactModel._default_manager.get()
    output_model = MacroFactorDatedOutputModel._default_manager.get()
    event_model = MacroFactorLifecycleEventModel._default_manager.get()

    guarded_models = (
        MacroFactorResearchResultModel,
        MacroFactorRunArtifactModel,
        MacroFactorDatedOutputModel,
        MacroFactorLifecycleEventModel,
    )
    for model in guarded_models:
        with pytest.raises(ValidationError, match="cannot be updated"):
            model._default_manager.all().update(content_hash="7" * 64)
        with pytest.raises(ValidationError, match="cannot be deleted"):
            model._base_manager.all().delete()

    with pytest.raises(ValidationError, match="cannot be updated"):
        artifact_model.dated_outputs.all().update(content_hash="6" * 64)
    with pytest.raises(ValidationError, match="append-only"):
        output_model.save()
    with pytest.raises(ValidationError, match="append-only"):
        event_model.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        artifact_model.delete()


def test_bundle_insert_rolls_back_every_table_on_child_failure(monkeypatch) -> None:
    repository = DjangoMacroFactorRunLedgerRepository()

    def _fail_save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValidationError("fault injection")

    monkeypatch.setattr(MacroFactorDatedOutputModel, "save", _fail_save)

    with pytest.raises(ValueError, match="invalid macro-factor run bundle"):
        repository.append_bundle(_bundle())

    assert MacroFactorResearchResultModel._default_manager.count() == 0
    assert MacroFactorRunArtifactModel._default_manager.count() == 0
    assert MacroFactorDatedOutputModel._default_manager.count() == 0
    assert MacroFactorLifecycleEventModel._default_manager.count() == 0


def test_retirement_appends_one_hash_chain_event_and_exact_replay_is_idempotent() -> None:
    repository = DjangoMacroFactorRunLedgerRepository()
    bundle = _bundle()
    repository.append_bundle(bundle)
    result = bundle.source_result
    retirement = RetirementEvidence(
        event_id="retire-growth-run-v1",
        retired_at=bundle.artifact.produced_at + timedelta(days=1),
        policy_version=result.retirement_policy.policy_version,
        reason_codes=(result.retirement_policy.rules[0].rule_id,),
        evidence_hash="9" * 64,
    )
    event = append_retirement_event(
        artifact=bundle.artifact,
        source_result=result,
        retirement=retirement,
        owner_attestation=retirement_owner_attestation(
            bundle.artifact,
            result,
            retirement,
        ),
        previous_event=bundle.lifecycle_events[0],
        recorded_at=retirement.retired_at,
    )

    stored = repository.append_lifecycle_event(event)
    replay = repository.append_lifecycle_event(event)

    assert stored == replay == event
    assert stored.owner_attestation_issued_at == retirement.retired_at
    assert repository.list_lifecycle_events(bundle.artifact.artifact_id) == (
        bundle.lifecycle_events[0],
        event,
    )
    assert MacroFactorLifecycleEventModel._default_manager.count() == 2
    assert MacroFactorRunArtifactModel._default_manager.get().content_hash == (
        bundle.artifact.content_hash
    )
    assert MacroFactorResearchResultModel._default_manager.get().lifecycle_status == (
        "research_only"
    )

    wrong_retirement = replace(retirement, evidence_hash="8" * 64)
    wrong_attestation = retirement_owner_attestation(
        bundle.artifact,
        result,
        wrong_retirement,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE macro_factor_lifecycle_event
            SET owner_attestation_hash = %s,
                owner_attestation_content_length = %s,
                owner_attestation_bytes = %s
            WHERE event_id = %s
            """,
            [
                wrong_attestation.attestation_hash,
                len(wrong_attestation.artifact_bytes),
                wrong_attestation.artifact_bytes,
                event.event_id,
            ],
        )
    with pytest.raises(ValueError, match="canonical bytes"):
        repository.list_lifecycle_events(bundle.artifact.artifact_id)


def test_concurrent_retirement_winner_is_rechecked_after_artifact_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = DjangoMacroFactorRunLedgerRepository()
    bundle = _bundle()
    repository.append_bundle(bundle)
    result = bundle.source_result
    retirement = RetirementEvidence(
        event_id="retire-growth-run-v1",
        retired_at=bundle.artifact.produced_at + timedelta(days=1),
        policy_version=result.retirement_policy.policy_version,
        reason_codes=(result.retirement_policy.rules[0].rule_id,),
        evidence_hash="9" * 64,
    )
    event = append_retirement_event(
        artifact=bundle.artifact,
        source_result=result,
        retirement=retirement,
        owner_attestation=retirement_owner_attestation(
            bundle.artifact,
            result,
            retirement,
        ),
        previous_event=bundle.lifecycle_events[0],
        recorded_at=retirement.retired_at,
    )
    repository.append_lifecycle_event(event)
    manager = MacroFactorLifecycleEventModel._default_manager
    original_filter = manager.filter
    first_call = True

    def first_lookup_misses(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal first_call
        queryset = original_filter(*args, **kwargs)
        if first_call:
            first_call = False
            return queryset.none()
        return queryset

    monkeypatch.setattr(manager, "filter", first_lookup_misses)

    assert repository.append_lifecycle_event(event) == event
    assert MacroFactorLifecycleEventModel._default_manager.count() == 2


def test_tampered_raw_payload_is_detected_on_read() -> None:
    repository = DjangoMacroFactorRunLedgerRepository()
    bundle = _bundle()
    repository.append_bundle(bundle)
    model = MacroFactorRunArtifactModel._default_manager.get()
    payload = dict(model.payload)
    payload["benchmark"] = {"version": "tampered", "hash": "1" * 64}

    # Use SQL only to simulate storage corruption; normal ORM paths are guarded.
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE macro_factor_run_artifact SET payload = %s WHERE artifact_id = %s",
            [json.dumps(payload), model.artifact_id],
        )

    with pytest.raises(ValueError, match="payload/hash"):
        repository.get_artifact(bundle.artifact.artifact_id)


def test_tampered_source_payload_is_detected_before_artifact_binding() -> None:
    repository = DjangoMacroFactorRunLedgerRepository()
    bundle = _bundle()
    repository.append_bundle(bundle)
    source = MacroFactorResearchResultModel._default_manager.get()
    payload = json.loads(json.dumps(source.payload))
    payload["evaluation"]["economic_interpretation"] = "tampered but non-identity"

    # Simulate raw storage corruption; guarded model managers cannot perform this update.
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE macro_factor_research_result SET payload = %s WHERE result_id = %s",
            [json.dumps(payload), source.result_id],
        )

    with pytest.raises(ValueError, match="content_hash"):
        repository.get_artifact(bundle.artifact.artifact_id)
