"""Component contracts for the R1 forecast-baseline append-only ledger."""

from __future__ import annotations

import hashlib
import inspect
import json
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.equity.application.forecast_baseline import (
    EvidenceIdentity,
    ForecastBaselineConflictError,
    ForecastBaselineEvidenceError,
    VersionRef,
)
from apps.equity.domain.forecast_baseline import (
    ForecastBaselineArtifact,
    ForecastBaselineSpec,
    ForecastBaselineTrialResult,
    ForecastEvaluationPolicy,
)
from apps.equity.domain.forecast_baseline_evidence import _hash_payload
from apps.equity.domain.forecast_baseline_trial import (
    _calculate_invalidation_outcomes,
    _summarize_metric_comparisons,
    _trial_payload,
)
from apps.equity.infrastructure.forecast_baseline_codec import seal_approval_evidence
from apps.equity.infrastructure.forecast_baseline_models import (
    ForecastBaselineApprovalEvidenceModel,
    ForecastBaselineArtifactModel,
    ForecastBaselineSpecModel,
    ForecastBaselineTrialResultModel,
)
from apps.equity.infrastructure.forecast_baseline_repository import (
    DjangoForecastBaselineRepository,
)
from tests.unit.equity.test_forecast_baseline_application import (
    APPROVAL_REF,
    _approval,
    _evaluate_trial,
    _execute,
)

pytestmark = pytest.mark.django_db


def _persist_chain() -> tuple[
    DjangoForecastBaselineRepository,
    object,
    ForecastBaselineSpec,
    object,
    ForecastBaselineTrialResult,
]:
    approval = seal_approval_evidence(_approval())
    spec, artifact, trial, *_ = _evaluate_trial(approval=approval)
    repository = DjangoForecastBaselineRepository()
    with patch(
        "apps.equity.infrastructure.forecast_baseline_models.timezone.now",
        return_value=approval.recorded_at,
    ):
        repository.append_approval(approval)
    repository.append_spec(spec)
    repository.append_artifact(artifact)
    return repository, approval, spec, artifact, trial


def _rehash_trial(
    trial: ForecastBaselineTrialResult,
    **changes: object,
) -> ForecastBaselineTrialResult:
    values = {field.name: getattr(trial, field.name) for field in fields(trial)}
    values.update(changes)
    payload_values = {name: values[name] for name in inspect.signature(_trial_payload).parameters}
    values["content_hash"] = _hash_payload(_trial_payload(**payload_values))
    return ForecastBaselineTrialResult(**values)


def _recreate_spec(
    spec: ForecastBaselineSpec,
    **changes: object,
) -> ForecastBaselineSpec:
    values = {
        name: getattr(spec, name)
        for name in inspect.signature(ForecastBaselineSpec.create).parameters
    }
    values.update(changes)
    return ForecastBaselineSpec.create(**values)


def test_approval_and_spec_round_trip_and_exact_replay() -> None:
    """Persisted approval/spec objects restore exactly and replay idempotently."""

    approval = seal_approval_evidence(_approval())
    spec, *_ = _execute(approval=approval)
    repository = DjangoForecastBaselineRepository()

    with patch(
        "apps.equity.infrastructure.forecast_baseline_models.timezone.now",
        return_value=approval.recorded_at,
    ):
        assert repository.append_approval(approval) == approval
    assert repository.append_approval(approval) == approval
    assert (
        repository.get_approval(
            APPROVAL_REF,
            as_of=approval.recorded_at - timedelta(microseconds=1),
        )
        is None
    )
    assert repository.get_approval(APPROVAL_REF, as_of=approval.recorded_at) == approval

    assert repository.append_spec(spec) == spec
    assert repository.append_spec(spec) == spec
    assert repository.get_spec(spec_ref=approval.spec_ref) == spec
    assert ForecastBaselineApprovalEvidenceModel._default_manager.count() == 1
    assert ForecastBaselineSpecModel._default_manager.count() == 1


def test_artifact_and_trial_round_trip_and_exact_replay() -> None:
    """Artifact/trial rows remain bound to their complete immutable ancestry."""

    approval = seal_approval_evidence(_approval())
    spec, artifact, trial, *_ = _evaluate_trial(approval=approval)
    repository = DjangoForecastBaselineRepository()

    with patch(
        "apps.equity.infrastructure.forecast_baseline_models.timezone.now",
        return_value=approval.recorded_at,
    ):
        repository.append_approval(approval)
    repository.append_spec(spec)

    assert repository.append_artifact(artifact) == artifact
    assert repository.append_artifact(artifact) == artifact
    assert (
        repository.get_artifact(
            artifact_ref=type(approval.spec_ref)(artifact.artifact_id, artifact.artifact_version)
        )
        == artifact
    )

    assert repository.append_trial(trial) == trial
    assert repository.append_trial(trial) == trial
    assert (
        repository.get_trial(
            trial_ref=type(approval.spec_ref)(trial.result_id, trial.result_version)
        )
        == trial
    )
    assert ForecastBaselineArtifactModel._default_manager.count() == 1
    assert ForecastBaselineTrialResultModel._default_manager.count() == 1


def test_spec_rejects_raw_fk_swap_and_approval_configuration_drift() -> None:
    """Spec reads/appends validate the complete canonical approval projection."""

    repository, approval, spec, _, _ = _persist_chain()
    other = seal_approval_evidence(
        replace(
            approval,
            approval=EvidenceIdentity("approval:other", "approval.v1", "0" * 64),
            spec_ref=VersionRef("baseline-spec:other", "spec.v1"),
        )
    )
    with patch(
        "apps.equity.infrastructure.forecast_baseline_models.timezone.now",
        return_value=other.recorded_at,
    ):
        repository.append_approval(other)
    spec_row = ForecastBaselineSpecModel._default_manager.get(
        spec_id=spec.spec_id,
        spec_version=spec.spec_version,
    )
    other_row = ForecastBaselineApprovalEvidenceModel._default_manager.get(
        approval_id=other.approval.stable_id,
        approval_version=other.approval.version,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE equity_forecast_baseline_spec SET approval_id = %s WHERE id = %s",
            [other_row.pk, spec_row.pk],
        )
    with pytest.raises(ForecastBaselineEvidenceError, match="projection|header"):
        repository.get_spec(VersionRef(spec.spec_id, spec.spec_version))

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE equity_forecast_baseline_spec SET approval_id = %s WHERE id = %s",
            [spec_row.approval_id, spec_row.pk],
        )
    create_values = {
        name: getattr(spec, name)
        for name in inspect.signature(ForecastBaselineSpec.create).parameters
    }
    create_values["family_parameter_version"] = "unapproved-params.v2"
    drifted = ForecastBaselineSpec.create(**create_values)
    with pytest.raises(ForecastBaselineEvidenceError, match="approval projection"):
        repository.append_spec(drifted)


def test_trial_rejects_rehashed_paired_row_substitution() -> None:
    """A self-consistent trial hash cannot substitute stored forecast/baseline values."""

    repository, _, spec, _, trial = _persist_chain()
    changed_row = replace(
        trial.paired_rows[0],
        forecast_value=trial.paired_rows[0].forecast_value + Decimal("1"),
    )
    changed_rows = (changed_row, *trial.paired_rows[1:])
    comparisons = _summarize_metric_comparisons(
        expected_period_ends=spec.expected_period_ends,
        metric_rules=spec.metric_rules,
        metric_evaluation_order=spec.metric_evaluation_order,
        tie_break_rule=spec.tie_break_rule,
        rows=changed_rows,
    )
    outcomes = _calculate_invalidation_outcomes(
        invalidation_rules=spec.invalidation_rules,
        metric_rules=spec.metric_rules,
        rows=changed_rows,
    )
    forged = _rehash_trial(
        trial,
        paired_rows=changed_rows,
        metric_comparisons=comparisons,
        invalidation_outcomes=outcomes,
        eligible_for_promotion=(
            all(item.passes for item in comparisons) and all(item.passes for item in outcomes)
        ),
    )
    with pytest.raises(ForecastBaselineEvidenceError, match="cannot be rebuilt"):
        repository.append_trial(forged)


def test_trial_rejects_rehashed_research_authority_drift() -> None:
    """Derived split/parameter/policy authority cannot drift behind a new result hash."""

    repository, _, _, _, trial = _persist_chain()
    authorization = trial.research_trial
    policy = authorization.evaluation_policy
    drifted_policy = ForecastEvaluationPolicy.create(
        policy_id=policy.policy_id,
        policy_version="policy.drifted",
        owner=policy.owner,
        actual_dataset="research.drifted-actual.v1",
        actual_knowledge_scope=policy.actual_knowledge_scope,
        actual_revision_rule=policy.actual_revision_rule,
        actual_vintage_rule=policy.actual_vintage_rule,
        forecast_freeze_rule=policy.forecast_freeze_rule,
        forecast_knowledge_cutoff_at=policy.forecast_knowledge_cutoff_at,
        forecast_submission_deadline_at=policy.forecast_submission_deadline_at,
        valid_until=policy.valid_until,
    )
    forged_authorities = (
        replace(authorization, split_spec_hash="0" * 64),
        replace(authorization, parameter_hash="1" * 64),
        replace(authorization, evaluation_policy=drifted_policy),
    )
    for forged_authority in forged_authorities:
        forged = _rehash_trial(trial, research_trial=forged_authority)
        with pytest.raises(ForecastBaselineEvidenceError, match="rebuilt|projection"):
            repository.append_trial(forged)


def test_approval_conflicts_and_first_lookup_miss_replay_one_winner() -> None:
    """Identity/hash collisions fail and the uniqueness-race loser replays one row."""

    approval = seal_approval_evidence(_approval())
    repository = DjangoForecastBaselineRepository()
    with patch(
        "apps.equity.infrastructure.forecast_baseline_models.timezone.now",
        return_value=approval.recorded_at,
    ):
        repository.append_approval(approval)

    changed = seal_approval_evidence(
        replace(
            approval,
            invalidation_not_applicable_reason="Conflicting immutable approval content.",
        )
    )
    with pytest.raises(ForecastBaselineConflictError, match="conflicting"):
        repository.append_approval(changed)
    same_hash_other_identity = replace(
        approval,
        approval=EvidenceIdentity(
            "approval:collision", "approval.v1", approval.approval.content_hash
        ),
    )
    with pytest.raises(ForecastBaselineConflictError, match="conflicting"):
        repository.append_approval(same_hash_other_identity)

    original_lookup = repository._lock_approval_candidates
    lookup_count = 0

    def simulate_first_lookup_miss(value: object) -> object:
        nonlocal lookup_count
        lookup_count += 1
        return [] if lookup_count == 1 else original_lookup(value)

    with (
        patch.object(
            repository,
            "_lock_approval_candidates",
            side_effect=simulate_first_lookup_miss,
        ),
        patch(
            "apps.equity.infrastructure.forecast_baseline_models.timezone.now",
            return_value=approval.recorded_at,
        ),
    ):
        assert repository.append_approval(approval) == approval
    assert lookup_count == 2
    assert ForecastBaselineApprovalEvidenceModel._default_manager.count() == 1


def test_bundle_failure_rolls_back_every_partial_ledger_row() -> None:
    """A mid-bundle failure leaves no approval, spec, artifact or trial residue."""

    approval = seal_approval_evidence(_approval())
    spec, artifact, trial, *_ = _evaluate_trial(approval=approval)
    repository = DjangoForecastBaselineRepository()
    with (
        patch(
            "apps.equity.infrastructure.forecast_baseline_models.timezone.now",
            return_value=approval.recorded_at,
        ),
        patch.object(repository, "append_artifact", side_effect=RuntimeError("injected")),
        pytest.raises(RuntimeError, match="injected"),
    ):
        repository.append_bundle(
            approval=approval,
            spec=spec,
            artifact=artifact,
            trial=trial,
        )
    assert ForecastBaselineApprovalEvidenceModel._default_manager.count() == 0
    assert ForecastBaselineSpecModel._default_manager.count() == 0
    assert ForecastBaselineArtifactModel._default_manager.count() == 0
    assert ForecastBaselineTrialResultModel._default_manager.count() == 0


def test_bundle_rejects_unrelated_preexisting_ancestry_before_any_write() -> None:
    """An unrelated approval cannot be presented as the head of a stored B chain."""

    repository, approval, spec, artifact, trial = _persist_chain()
    repository.append_trial(trial)
    unrelated = seal_approval_evidence(
        replace(
            approval,
            approval=EvidenceIdentity("approval:unrelated", "approval.v1", "0" * 64),
            spec_ref=VersionRef("baseline-spec:unrelated", "spec.v1"),
        )
    )
    unrelated_spec = _recreate_spec(
        spec,
        spec_id=unrelated.spec_ref.stable_id,
        spec_version=unrelated.spec_ref.version,
        approval_evidence_id=unrelated.approval.stable_id,
        approval_evidence_version=unrelated.approval.version,
        approval_evidence_content_hash=unrelated.approval.content_hash,
        approval_recorded_at=unrelated.recorded_at,
    )
    unrelated_artifact = ForecastBaselineArtifact.create(
        artifact_id="baseline-artifact:unrelated",
        artifact_version="artifact.v1",
        owner="equity",
        spec=unrelated_spec,
        forecasts=artifact.forecasts,
        predictions=artifact.predictions,
        knowledge_as_of=artifact.knowledge_as_of,
        produced_at=artifact.produced_at,
        valid_until=artifact.valid_until,
    )
    unrelated_trial = _rehash_trial(
        trial,
        baseline_artifact_id=unrelated_artifact.artifact_id,
        baseline_artifact_version=unrelated_artifact.artifact_version,
        baseline_artifact_content_hash=unrelated_artifact.content_hash,
    )
    counts_before = (
        ForecastBaselineApprovalEvidenceModel._default_manager.count(),
        ForecastBaselineSpecModel._default_manager.count(),
        ForecastBaselineArtifactModel._default_manager.count(),
        ForecastBaselineTrialResultModel._default_manager.count(),
    )
    mixed_bundles = (
        (unrelated, spec, artifact, trial),
        (approval, unrelated_spec, artifact, trial),
        (approval, spec, unrelated_artifact, trial),
        (approval, spec, artifact, unrelated_trial),
    )
    for mixed_approval, mixed_spec, mixed_artifact, mixed_trial in mixed_bundles:
        with pytest.raises(ForecastBaselineEvidenceError, match="projection|rebuilt"):
            repository.append_bundle(
                approval=mixed_approval,
                spec=mixed_spec,
                artifact=mixed_artifact,
                trial=mixed_trial,
            )
    assert (
        ForecastBaselineApprovalEvidenceModel._default_manager.count(),
        ForecastBaselineSpecModel._default_manager.count(),
        ForecastBaselineArtifactModel._default_manager.count(),
        ForecastBaselineTrialResultModel._default_manager.count(),
    ) == counts_before


def test_raw_header_payload_and_payload_hash_tamper_fail_on_read() -> None:
    """Independent header, JSON body and embedded hash substitutions fail closed."""

    repository, _, spec, _, _ = _persist_chain()
    row = ForecastBaselineSpecModel._default_manager.get(spec_id=spec.spec_id)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE equity_forecast_baseline_spec SET content_hash = %s WHERE id = %s",
            ["f" * 64, row.pk],
        )
    with pytest.raises(ForecastBaselineEvidenceError, match="header/payload"):
        repository.get_spec(VersionRef(spec.spec_id, spec.spec_version))
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE equity_forecast_baseline_spec SET content_hash = %s WHERE id = %s",
            [spec.content_hash, row.pk],
        )

    original_payload = row.canonical_payload
    substituted = deepcopy(original_payload)
    substituted["payload"]["subject_code"] = "SUBSTITUTED"
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE equity_forecast_baseline_spec SET canonical_payload = %s WHERE id = %s",
            [json.dumps(substituted), row.pk],
        )
    with pytest.raises(ValueError, match="typed contract"):
        repository.get_spec(VersionRef(spec.spec_id, spec.spec_version))

    hash_tampered = deepcopy(original_payload)
    hash_tampered["payload"]["content_hash"] = "0" * 64
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE equity_forecast_baseline_spec SET canonical_payload = %s WHERE id = %s",
            [json.dumps(hash_tampered), row.pk],
        )
    with pytest.raises(ValueError, match="typed contract"):
        repository.get_spec(VersionRef(spec.spec_id, spec.spec_version))


def test_artifact_and_trial_reject_raw_fk_and_upstream_header_swaps() -> None:
    """Artifact/trial loads decode canonical FKs and reject unrelated ancestry."""

    repository, approval, spec, artifact, trial = _persist_chain()
    repository.append_trial(trial)
    other_approval = seal_approval_evidence(
        replace(
            approval,
            approval=EvidenceIdentity("approval:other-chain", "approval.v1", "0" * 64),
            spec_ref=VersionRef("baseline-spec:other-chain", "spec.v1"),
        )
    )
    other_spec = _recreate_spec(
        spec,
        spec_id=other_approval.spec_ref.stable_id,
        spec_version=other_approval.spec_ref.version,
        approval_evidence_id=other_approval.approval.stable_id,
        approval_evidence_version=other_approval.approval.version,
        approval_evidence_content_hash=other_approval.approval.content_hash,
        approval_recorded_at=other_approval.recorded_at,
    )
    other_artifact = ForecastBaselineArtifact.create(
        artifact_id="baseline-artifact:other-chain",
        artifact_version="artifact.v1",
        owner="equity",
        spec=other_spec,
        forecasts=artifact.forecasts,
        predictions=artifact.predictions,
        knowledge_as_of=artifact.knowledge_as_of,
        produced_at=artifact.produced_at,
        valid_until=artifact.valid_until,
    )
    with patch(
        "apps.equity.infrastructure.forecast_baseline_models.timezone.now",
        return_value=other_approval.recorded_at,
    ):
        repository.append_approval(other_approval)
    repository.append_spec(other_spec)
    repository.append_artifact(other_artifact)

    artifact_row = ForecastBaselineArtifactModel._default_manager.get(
        artifact_id=artifact.artifact_id
    )
    other_spec_row = ForecastBaselineSpecModel._default_manager.get(spec_id=other_spec.spec_id)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE equity_forecast_baseline_artifact SET spec_id = %s WHERE id = %s",
            [other_spec_row.pk, artifact_row.pk],
        )
    with pytest.raises(ForecastBaselineEvidenceError, match="projection|header"):
        repository.get_artifact(VersionRef(artifact.artifact_id, artifact.artifact_version))
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE equity_forecast_baseline_artifact SET spec_id = %s WHERE id = %s",
            [artifact_row.spec_id, artifact_row.pk],
        )
        cursor.execute(
            "UPDATE equity_forecast_baseline_artifact "
            "SET spec_evidence_content_hash = %s WHERE id = %s",
            ["e" * 64, artifact_row.pk],
        )
    with pytest.raises(ForecastBaselineEvidenceError, match="header/payload"):
        repository.get_artifact(VersionRef(artifact.artifact_id, artifact.artifact_version))
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE equity_forecast_baseline_artifact "
            "SET spec_evidence_content_hash = %s WHERE id = %s",
            [artifact.spec_content_hash, artifact_row.pk],
        )

    trial_row = ForecastBaselineTrialResultModel._default_manager.get(result_id=trial.result_id)
    other_artifact_row = ForecastBaselineArtifactModel._default_manager.get(
        artifact_id=other_artifact.artifact_id
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE equity_forecast_baseline_trial_result SET spec_id = %s WHERE id = %s",
            [other_spec_row.pk, trial_row.pk],
        )
    with pytest.raises(ForecastBaselineEvidenceError, match="projection|header|rebuilt"):
        repository.get_trial(VersionRef(trial.result_id, trial.result_version))
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE equity_forecast_baseline_trial_result SET spec_id = %s WHERE id = %s",
            [trial_row.spec_id, trial_row.pk],
        )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE equity_forecast_baseline_trial_result " "SET artifact_id = %s WHERE id = %s",
            [other_artifact_row.pk, trial_row.pk],
        )
    with pytest.raises(ForecastBaselineEvidenceError, match="projection|header|rebuilt"):
        repository.get_trial(VersionRef(trial.result_id, trial.result_version))
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE equity_forecast_baseline_trial_result "
            "SET artifact_id = %s, artifact_evidence_content_hash = %s WHERE id = %s",
            [trial_row.artifact_id, "d" * 64, trial_row.pk],
        )
    with pytest.raises(ForecastBaselineEvidenceError, match="header/payload"):
        repository.get_trial(VersionRef(trial.result_id, trial.result_version))


def test_append_only_guards_cover_default_base_related_and_pk_zero() -> None:
    """No Django manager or falsey-primary-key path can mutate ledger history."""

    repository, approval, spec, artifact, trial = _persist_chain()
    repository.append_trial(trial)
    approval_row = ForecastBaselineApprovalEvidenceModel._default_manager.get(
        approval_id=approval.approval.stable_id
    )
    spec_row = ForecastBaselineSpecModel._default_manager.get(spec_id=spec.spec_id)

    for manager in (
        ForecastBaselineSpecModel._default_manager,
        ForecastBaselineSpecModel._base_manager,
    ):
        with pytest.raises(ValidationError, match="exact append"):
            manager.bulk_create([], ignore_conflicts=True)
        with pytest.raises(ValidationError, match="exact append"):
            manager.bulk_create(
                [],
                update_conflicts=True,
                update_fields=["owner"],
                unique_fields=["spec_id", "spec_version"],
            )
    with pytest.raises(ValidationError, match="exact append"):
        approval_row.spec_records.bulk_create([], ignore_conflicts=True)
    with pytest.raises(ValidationError, match="updated"):
        ForecastBaselineSpecModel._default_manager.bulk_update([spec_row], ["owner"])
    with pytest.raises(ValidationError, match="updated"):
        ForecastBaselineSpecModel._base_manager.filter(pk=spec_row.pk).update(owner="other")
    with pytest.raises(ValidationError, match="deleted"):
        ForecastBaselineSpecModel._default_manager.filter(pk=spec_row.pk).delete()
    with pytest.raises(ValidationError, match="deleted"):
        spec_row.delete()

    rows_and_identities = (
        (approval_row, "approval_id", "approval_version"),
        (spec_row, "spec_id", "spec_version"),
        (
            ForecastBaselineArtifactModel._default_manager.get(artifact_id=artifact.artifact_id),
            "artifact_id",
            "artifact_version",
        ),
        (
            ForecastBaselineTrialResultModel._default_manager.get(result_id=trial.result_id),
            "result_id",
            "result_version",
        ),
    )
    for row, id_field, version_field in rows_and_identities:
        model_type = type(row)
        values = {
            field.attname: getattr(row, field.attname)
            for field in model_type._meta.concrete_fields
            if not field.primary_key
        }
        values[id_field] = f"{values[id_field]}:pk-zero"
        values[version_field] = f"{values[version_field]}:pk-zero"
        values["content_hash"] = hashlib.sha256(
            f"pk-zero:{model_type._meta.db_table}".encode()
        ).hexdigest()
        context = (
            patch(
                "apps.equity.infrastructure.forecast_baseline_models.timezone.now",
                return_value=approval.recorded_at,
            )
            if model_type is ForecastBaselineApprovalEvidenceModel
            else nullcontext()
        )
        with context:
            zero_row = model_type._default_manager.create(id=0, **values)
        zero_row.owner = "tampered"
        with pytest.raises(ValidationError, match="immutable"):
            zero_row.save()
