"""Exact Research/PIT bindings and durable final-OOS claims."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from typing import Protocol, cast

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.data_center.application.pit_provider import (
    get_verified_pit_manifest_binding,
)
from apps.research.domain.event_study_control import (
    EventStudyBinding,
    EventStudyBindingRequest,
    EventStudyControlError,
    FinalOOSClaim,
)
from apps.research.domain.institutional_event_study import WalkForwardPolicy
from apps.research.infrastructure.event_study_control_models import (
    EventStudyBindingModel,
    EventStudyFinalOOSClaimModel,
    EventStudySpecModel,
)
from apps.research.infrastructure.models import (
    DatasetSplitSpec,
    ExperimentTrial,
    MetricObservation,
    MultipleTestFamily,
    ResearchExperiment,
)
from shared.numeric import safe_float


class _TrialLifecycleWriter(Protocol):
    def save(self, *, update_fields: list[str]) -> None:
        """Narrow the legacy ORM save boundary without bypassing its guards."""
        ...


def _hash(value: object) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise EventStudyControlError("SNAPSHOT_JSON_INVALID") from exc
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise EventStudyControlError("SPEC_OBJECT_REQUIRED")
    return cast(dict[str, object], value)


def _text(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 128:
        raise EventStudyControlError("IDENTITY_INVALID")
    return value


def _digest(value: str, *, commit: bool = False) -> None:
    pattern = r"(?:[a-f0-9]{40}|[a-f0-9]{64})" if commit else r"[a-f0-9]{64}"
    if not re.fullmatch(pattern, value):
        raise EventStudyControlError("DIGEST_INVALID")


def _integer(value: object) -> int:
    if type(value) is not int:
        raise EventStudyControlError("SPEC_INTEGER_REQUIRED")
    return value


def _spec(document: str) -> dict[str, object]:
    if len(document.encode("utf-8")) > 65_536:
        raise EventStudyControlError("SPEC_TOO_LARGE")
    try:
        parsed: object = json.loads(document)
    except json.JSONDecodeError as exc:
        raise EventStudyControlError("SPEC_JSON_INVALID") from exc
    doc = _object(parsed)
    _hash(doc)  # Reject non-finite constants even in unused document sections.
    if doc.get("status") != "frozen_before_oos" or doc.get("oos_results_inspected") is not False:
        raise EventStudyControlError("SPEC_NOT_PREREGISTERED")
    _text(doc.get("spec_id"))
    try:
        frozen_at = datetime.fromisoformat(_text(doc.get("frozen_at")))
    except ValueError as exc:
        raise EventStudyControlError("SPEC_FREEZE_TIME_INVALID") from exc
    if frozen_at.tzinfo is None or frozen_at.utcoffset() is None or frozen_at > timezone.now():
        raise EventStudyControlError("SPEC_FREEZE_TIME_INVALID")
    temporal = _object(doc.get("temporal_split"))
    history = _object(temporal.get("minimum_history"))
    purge = _object(temporal.get("purge"))
    embargo = _object(temporal.get("embargo"))
    samples = _object(doc.get("sample_gates"))
    coverage = samples.get("target_expected_session_coverage_min")
    parsed_coverage = safe_float(coverage)
    if type(coverage) not in (float, int) or parsed_coverage is None:
        raise EventStudyControlError("SPEC_COVERAGE_INVALID")
    WalkForwardPolicy(
        minimum_history_years=_integer(history.get("consecutive_calendar_years")),
        minimum_complete_rows=_integer(history.get("complete_daily_rows_per_target")),
        first_training_years=_integer(temporal.get("first_training_window_years")),
        validation_sessions=_integer(temporal.get("validation_trading_days_per_fold")),
        minimum_folds=_integer(temporal.get("minimum_walk_forward_folds")),
        final_oos_sessions=_integer(temporal.get("total_oos_trading_days")),
        minimum_separation_sessions=_integer(purge.get("minimum_separation_trading_days")),
        embargo_sessions=_integer(embargo.get("trading_days")),
        minimum_coverage=parsed_coverage,
    )
    if temporal.get("final_oos_use") != "once":
        raise EventStudyControlError("SPEC_FINAL_OOS_MUST_BE_ONCE")
    return doc


def _actor(actor_user_id: int, *, operator: bool = False) -> None:
    if type(actor_user_id) is not int or actor_user_id < 1:
        raise EventStudyControlError("AUTHENTICATED_ACTOR_REQUIRED")
    user = get_user_model()._default_manager.filter(pk=actor_user_id, is_active=True).first()
    if user is None or (operator and not user.is_staff):
        raise EventStudyControlError("RESEARCH_ACCESS_DENIED")


def _trial(
    trial_id: str, actor_user_id: int
) -> tuple[ExperimentTrial, ResearchExperiment, MultipleTestFamily, DatasetSplitSpec]:
    try:
        initial = ExperimentTrial._default_manager.get(pk=trial_id)
        experiment = ResearchExperiment._default_manager.select_for_update().get(
            pk=initial.experiment_id
        )
        family = MultipleTestFamily._default_manager.select_for_update().get(pk=initial.family_id)
        trial = ExperimentTrial._default_manager.select_for_update().get(pk=trial_id)
        split = DatasetSplitSpec._default_manager.select_for_update().get(pk=trial_id)
    except (
        ExperimentTrial.DoesNotExist,
        ResearchExperiment.DoesNotExist,
        MultipleTestFamily.DoesNotExist,
        DatasetSplitSpec.DoesNotExist,
    ) as exc:
        raise EventStudyControlError("RESEARCH_IDENTITY_MISSING") from exc
    if experiment.owner_id != actor_user_id:
        raise EventStudyControlError("RESEARCH_ACCESS_DENIED")
    if (
        trial.experiment_id != experiment.pk
        or trial.family_id != family.pk
        or family.experiment_id != experiment.pk
    ):
        raise EventStudyControlError("RESEARCH_RELATIONSHIP_MISMATCH")
    return trial, experiment, family, split


def _snapshot(
    trial: ExperimentTrial,
    experiment: ResearchExperiment,
    family: MultipleTestFamily,
    split: DatasetSplitSpec,
    spec: EventStudySpecModel,
    registered_trials: tuple[tuple[str, str], ...] | None = None,
) -> dict[str, object]:
    doc = _spec(spec.document)
    if hashlib.sha256(spec.document.encode("utf-8")).hexdigest() != spec.document_sha256:
        raise EventStudyControlError("SPEC_DIGEST_MISMATCH")
    params = _object(trial.parameters)
    testing = _object(doc.get("multiple_testing"))
    exploratory = _object(testing.get("secondary_exploratory"))
    if family.fdr_threshold != exploratory.get("q"):
        raise EventStudyControlError("FROZEN_FAMILY_THRESHOLD_MISMATCH")
    if (
        params.get("event_study_spec") != doc
        or params.get("event_study_spec_sha256") != spec.document_sha256
    ):
        raise EventStudyControlError("FROZEN_SPEC_MISMATCH")
    if _hash(params) != trial.parameter_hash:
        raise EventStudyControlError("PARAMETER_DIGEST_MISMATCH")
    temporal = _object(doc["temporal_split"])
    if split.embargo_days != _object(temporal["embargo"])["trading_days"]:
        raise EventStudyControlError("FROZEN_EMBARGO_MISMATCH")
    if len(split.walk_forward_windows) < _integer(temporal["minimum_walk_forward_folds"]):
        raise EventStudyControlError("FROZEN_FOLDS_INSUFFICIENT")
    training = _object(split.training_window)
    validation = _object(split.validation_window)
    final = _object(split.out_of_sample_window)
    if (
        training.get("minimum_calendar_years") != temporal["first_training_window_years"]
        or validation.get("trading_days_per_fold") != temporal["validation_trading_days_per_fold"]
        or final.get("trading_days") != temporal["total_oos_trading_days"]
        or final.get("use") != temporal["final_oos_use"]
        or any(
            _object(window).get("validation_sessions")
            != temporal["validation_trading_days_per_fold"]
            for window in split.walk_forward_windows
        )
    ):
        raise EventStudyControlError("FROZEN_SPLIT_MISMATCH")
    try:
        manifest = get_verified_pit_manifest_binding(trial.pit_manifest_id)
    except (ValueError, RuntimeError) as exc:
        raise EventStudyControlError("PIT_MANIFEST_UNVERIFIED") from exc
    _digest(manifest.manifest_hash)
    _digest(manifest.versions_sha256)
    if (
        manifest.as_of_time.tzinfo is None
        or manifest.as_of_time.utcoffset() is None
        or manifest.as_of_time > timezone.now()
        or not manifest.calendar_version.strip()
        or manifest.knowledge_scope not in ("public", "system")
        or not manifest.coverage
        or any(
            type(dataset) is not str
            or not dataset.strip()
            or type(value) not in (int, float)
            or not math.isfinite(value)
            or value != 1.0
            for dataset, value in manifest.coverage
        )
    ):
        raise EventStudyControlError("PIT_MANIFEST_UNVERIFIED")
    if (
        training.get("calendar_version") != manifest.calendar_version
        or final.get("calendar_version") != manifest.calendar_version
    ):
        raise EventStudyControlError("SPLIT_CALENDAR_MISMATCH")
    current_members = dict(
        ExperimentTrial._default_manager.filter(family=family).values_list(
            "trial_id", "parameter_hash"
        )
    )
    members = (
        registered_trials
        if registered_trials is not None
        else tuple(sorted(current_members.items()))
    )
    if any(current_members.get(trial_id) != digest for trial_id, digest in members):
        raise EventStudyControlError("FAMILY_REGISTERED_ATTEMPT_CHANGED")
    return {
        "spec_sha256": spec.document_sha256,
        "experiment": {
            "id": experiment.pk,
            "question": experiment.question,
            "hypothesis": experiment.hypothesis,
            "owner_id": experiment.owner_id,
        },
        "family": {
            "id": family.pk,
            "planned_trial_count": family.planned_trial_count,
            "fdr_threshold": family.fdr_threshold,
            "registered_trials": list(members),
        },
        "trial": {
            key: getattr(trial, key) for key in ("trial_id", *ExperimentTrial.IMMUTABLE_FIELDS)
        },
        "split": {
            key: getattr(split, key)
            for key in (
                "training_window",
                "validation_window",
                "out_of_sample_window",
                "walk_forward_windows",
                "embargo_days",
            )
        },
        "manifest": {
            "id": manifest.manifest_id,
            "sha256": manifest.manifest_hash,
            "versions_sha256": manifest.versions_sha256,
            "calendar_version": manifest.calendar_version,
            "as_of_time": manifest.as_of_time.astimezone(UTC).isoformat(),
            "knowledge_scope": manifest.knowledge_scope,
            "coverage": list(manifest.coverage),
        },
    }


def _view(binding: EventStudyBindingModel) -> EventStudyBinding:
    return EventStudyBinding(
        study_key=binding.study_key,
        trial_id=binding.trial_id,
        experiment_id=binding.experiment_id,
        family_id=binding.family_id,
        spec_sha256=binding.spec.document_sha256,
        manifest_id=binding.manifest_id,
        manifest_sha256=binding.manifest_sha256,
        snapshot_sha256=binding.snapshot_sha256,
    )


def _members(binding: EventStudyBindingModel) -> tuple[tuple[str, str], ...]:
    family = _object(_object(binding.snapshot)["family"])
    values = family.get("registered_trials")
    if not isinstance(values, list) or not values:
        raise EventStudyControlError("FAMILY_REGISTERED_ATTEMPT_CHANGED")
    result: list[tuple[str, str]] = []
    for value in values:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise EventStudyControlError("FAMILY_REGISTERED_ATTEMPT_CHANGED")
        trial_id, digest = _text(value[0]), _text(value[1])
        _digest(digest)
        result.append((trial_id, digest))
    return tuple(result)


class DjangoEventStudyRegistry:
    """Append immutable bindings to existing Research records and consume once."""

    @transaction.atomic
    def register_spec(self, document: str, expected_sha256: str, *, actor_user_id: int) -> str:
        """Require an active staff initializer and exact retained original bytes."""
        _actor(actor_user_id, operator=True)
        _digest(expected_sha256)
        if hashlib.sha256(document.encode("utf-8")).hexdigest() != expected_sha256:
            raise EventStudyControlError("SPEC_DIGEST_MISMATCH")
        doc = _spec(document)
        spec, _ = EventStudySpecModel.objects.get_or_create(
            spec_id=_text(doc["spec_id"]),
            defaults={
                "document": document,
                "document_sha256": expected_sha256,
                "registered_by_id": actor_user_id,
                "registered_at": timezone.now(),
            },
        )
        if spec.document != document or spec.document_sha256 != expected_sha256:
            raise EventStudyControlError("FROZEN_SPEC_CONFLICT")
        return spec.document_sha256

    @transaction.atomic
    def bind(self, request: EventStudyBindingRequest, *, actor_user_id: int) -> EventStudyBinding:
        """Freeze one draft trial and its exact full registry/PIT/config/code snapshot."""
        _actor(actor_user_id)
        _text(request.study_key)
        for value in (
            request.spec_sha256,
            request.manifest_sha256,
            request.parameter_sha256,
            request.dependency_sha256,
        ):
            _digest(value)
        _digest(request.code_commit, commit=True)
        trial, experiment, family, split = _trial(request.trial_id, actor_user_id)
        try:
            spec = EventStudySpecModel.objects.get(spec_id=request.spec_id)
        except EventStudySpecModel.DoesNotExist as exc:
            raise EventStudyControlError("FROZEN_SPEC_MISSING") from exc
        existing = EventStudyBindingModel.objects.filter(experiment=experiment).first()
        if existing is not None and (
            existing.study_key != request.study_key
            or existing.trial_id != trial.pk
            or existing.family_id != family.pk
            or existing.spec_id != spec.pk
        ):
            raise EventStudyControlError("PREREGISTRATION_CONFLICT")
        snapshot = _snapshot(
            trial, experiment, family, split, spec, _members(existing) if existing else None
        )
        manifest = _object(snapshot["manifest"])
        if (
            spec.document_sha256 != request.spec_sha256
            or manifest["sha256"] != request.manifest_sha256
            or trial.parameter_hash != request.parameter_sha256
            or trial.code_commit != request.code_commit
            or trial.dependency_lock_hash != request.dependency_sha256
        ):
            raise EventStudyControlError("BINDING_IDENTITY_MISMATCH")
        digest = _hash(snapshot)
        if existing is not None:
            if (
                existing.study_key != request.study_key
                or existing.snapshot_sha256 != digest
                or _hash(existing.snapshot) != digest
            ):
                raise EventStudyControlError("PREREGISTRATION_CONFLICT")
            return _view(existing)
        if (
            trial.status != "draft"
            or trial.started_at is not None
            or trial.completed_at is not None
            or MetricObservation._default_manager.filter(trial=trial).exists()
        ):
            raise EventStudyControlError("TRIAL_ALREADY_EXECUTED")
        try:
            with transaction.atomic():
                binding = EventStudyBindingModel.objects.create(
                    study_key=request.study_key,
                    spec=spec,
                    experiment=experiment,
                    family=family,
                    trial=trial,
                    manifest_id=trial.pit_manifest_id,
                    manifest_sha256=request.manifest_sha256,
                    snapshot=snapshot,
                    snapshot_sha256=digest,
                    bound_by_id=actor_user_id,
                    bound_at=timezone.now(),
                )
        except IntegrityError as exc:
            raise EventStudyControlError("PREREGISTRATION_CONFLICT") from exc
        trial.status = "running"
        trial.started_at = timezone.now()
        cast(_TrialLifecycleWriter, trial).save(update_fields=["status", "started_at"])
        return _view(binding)

    def claim(self, study_key: str, *, actor_user_id: int) -> FinalOOSClaim:
        """Commit irrevocable use before returning; reject enclosing transactions."""
        # durable=True prevents an evaluator's outer rollback from refunding use.
        if transaction.get_connection().in_atomic_block:
            raise EventStudyControlError("OOS_REQUIRES_DURABLE_BOUNDARY")
        with transaction.atomic(durable=True):
            _actor(actor_user_id)
            try:
                binding = (
                    EventStudyBindingModel.objects.select_for_update()
                    .select_related("spec")
                    .get(study_key=study_key)
                )
            except EventStudyBindingModel.DoesNotExist as exc:
                raise EventStudyControlError("PREREGISTRATION_MISSING") from exc
            trial, experiment, family, split = _trial(binding.trial_id, actor_user_id)
            if EventStudyFinalOOSClaimModel.objects.filter(binding=binding).exists():
                raise EventStudyControlError("FINAL_OOS_ALREADY_USED")
            actual = _snapshot(trial, experiment, family, split, binding.spec, _members(binding))
            if (
                _hash(binding.snapshot) != binding.snapshot_sha256
                or _hash(actual) != binding.snapshot_sha256
                or trial.status != "running"
                or trial.completed_at is not None
            ):
                raise EventStudyControlError("PREREGISTRATION_CHANGED")
            attempts = ExperimentTrial._default_manager.filter(family=family).count()
            if attempts > family.planned_trial_count:
                raise EventStudyControlError("FAMILY_ATTEMPT_LIMIT_EXCEEDED")
            row = EventStudyFinalOOSClaimModel.objects.create(
                binding=binding,
                actor_user_id=actor_user_id,
                cumulative_family_trials=attempts,
                claimed_at=timezone.now(),
            )
            receipt = FinalOOSClaim(row.pk, _view(binding), row.claimed_at, actor_user_id, attempts)
        return receipt
