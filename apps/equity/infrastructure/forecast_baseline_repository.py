"""Django append-only repository for R1 forecast-baseline evidence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.equity.application.forecast_baseline_evaluation import (
    forecast_baseline_trial_parameter_hash,
    forecast_baseline_trial_split_hash,
)
from apps.equity.application.forecast_baseline_materialize import (
    BaselineApprovalEvidence,
    ForecastBaselineConflictError,
    ForecastBaselineEvidenceError,
    VersionRef,
)
from apps.equity.domain.forecast_baseline import (
    BaselineCostRule,
    BaselineInvalidationRule,
    BaselineMetricRule,
    ForecastBaselineArtifact,
    ForecastBaselineSpec,
    ForecastBaselineTrialResult,
)

from .forecast_baseline_codec import (
    APPROVAL_PAYLOAD_SCHEMA,
    ARTIFACT_PAYLOAD_SCHEMA,
    SPEC_PAYLOAD_SCHEMA,
    TRIAL_PAYLOAD_SCHEMA,
    decode_approval_evidence,
    decode_forecast_baseline_artifact,
    decode_forecast_baseline_spec,
    decode_forecast_baseline_trial,
    encode_approval_evidence,
    encode_forecast_baseline_artifact,
    encode_forecast_baseline_spec,
    encode_forecast_baseline_trial,
)
from .forecast_baseline_models import (
    ForecastBaselineApprovalEvidenceModel,
    ForecastBaselineArtifactModel,
    ForecastBaselineSpecModel,
    ForecastBaselineTrialResultModel,
)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ForecastBaselineEvidenceError(f"{field_name} must be timezone-aware")


class DjangoForecastBaselineRepository:
    """Persist and exactly restore owner approval plus Domain baseline records."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the canonical database identity for authoritative evaluation."""

        return "django:default"

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared transaction used by exact owner reads and trial append."""

        return transaction.atomic()

    @transaction.atomic
    def append_approval(
        self,
        evidence: BaselineApprovalEvidence,
    ) -> BaselineApprovalEvidence:
        """Append one server-timestamped approval or replay identical evidence."""

        existing = self._lock_approval_candidates(evidence)
        if existing:
            return self._replay_approval(existing, evidence)
        payload = encode_approval_evidence(evidence)
        try:
            with transaction.atomic():
                ForecastBaselineApprovalEvidenceModel._default_manager.create(
                    approval_id=evidence.approval.stable_id,
                    approval_version=evidence.approval.version,
                    content_hash=evidence.approval.content_hash,
                    owner=evidence.approval_owner,
                    status=evidence.approval_status.value,
                    forecast_origin_at=evidence.forecast_origin_at,
                    approved_at=evidence.approved_at,
                    valid_until=evidence.valid_until,
                    payload_schema=APPROVAL_PAYLOAD_SCHEMA,
                    canonical_payload=payload,
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                    recorded_at=evidence.recorded_at,
                )
        except IntegrityError as error:
            candidates = self._lock_approval_candidates(evidence)
            if not candidates:
                raise ForecastBaselineConflictError(
                    "approval append violated immutable ledger constraints"
                ) from error
            return self._replay_approval(candidates, evidence)
        stored = self.get_approval(evidence.approval.version_ref, as_of=evidence.recorded_at)
        if stored != evidence:
            raise ForecastBaselineEvidenceError(
                "approval repository did not preserve the exact evidence"
            )
        return stored

    @transaction.atomic
    def append_bundle(
        self,
        *,
        approval: BaselineApprovalEvidence,
        spec: ForecastBaselineSpec,
        artifact: ForecastBaselineArtifact,
        trial: ForecastBaselineTrialResult,
    ) -> tuple[
        BaselineApprovalEvidence,
        ForecastBaselineSpec,
        ForecastBaselineArtifact,
        ForecastBaselineTrialResult,
    ]:
        """Atomically append one complete approval→spec→artifact→trial bundle."""

        encode_approval_evidence(approval)
        self._validate_spec_projection(approval, spec)
        self._validate_artifact_projection(spec, artifact)
        self._validate_trial_projection(spec, artifact, trial)
        stored_approval = self.append_approval(approval)
        stored_spec = self.append_spec(spec)
        stored_artifact = self.append_artifact(artifact)
        stored_trial = self.append_trial(trial)
        return stored_approval, stored_spec, stored_artifact, stored_trial

    def get_approval(
        self,
        approval_ref: VersionRef,
        *,
        as_of: datetime,
    ) -> BaselineApprovalEvidence | None:
        """Read an exact approval only after its owner receipt and while active."""

        _require_aware(as_of, "approval as_of")
        model = (
            ForecastBaselineApprovalEvidenceModel._default_manager.filter(
                approval_id=approval_ref.stable_id,
                approval_version=approval_ref.version,
                recorded_at__lte=as_of,
                approved_at__lte=as_of,
                valid_until__gt=as_of,
            )
            .order_by("pk")
            .first()
        )
        return None if model is None else self._approval_from_model(model)

    @transaction.atomic
    def append_spec(self, spec: ForecastBaselineSpec) -> ForecastBaselineSpec:
        """Append one spec only beneath its exact canonical approval row."""

        payload = encode_forecast_baseline_spec(spec)
        approval = (
            ForecastBaselineApprovalEvidenceModel._default_manager.select_for_update()
            .filter(
                approval_id=spec.approval_evidence_id,
                approval_version=spec.approval_evidence_version,
                content_hash=spec.approval_evidence_content_hash,
            )
            .first()
        )
        if approval is None or self._approval_from_model(approval).recorded_at != (
            spec.approval_recorded_at
        ):
            raise ForecastBaselineEvidenceError("exact canonical approval is unavailable")
        approval_evidence = self._approval_from_model(approval)
        self._validate_spec_projection(approval_evidence, spec)
        existing = self._lock_spec_candidates(spec)
        if existing:
            return self._replay_spec(existing, spec)
        forecast_origin_at = spec.period_horizons[0].forecast_origin_at
        try:
            with transaction.atomic():
                ForecastBaselineSpecModel._default_manager.create(
                    approval=approval,
                    spec_id=spec.spec_id,
                    spec_version=spec.spec_version,
                    content_hash=spec.content_hash,
                    owner=spec.owner,
                    approval_evidence_id=spec.approval_evidence_id,
                    approval_evidence_version=spec.approval_evidence_version,
                    approval_evidence_content_hash=spec.approval_evidence_content_hash,
                    approval_recorded_at=spec.approval_recorded_at,
                    forecast_origin_at=forecast_origin_at,
                    approved_at=spec.approved_at,
                    valid_until=spec.valid_until,
                    payload_schema=SPEC_PAYLOAD_SCHEMA,
                    canonical_payload=payload,
                    research_only=spec.research_only,
                    must_not_use_for_decision=spec.must_not_use_for_decision,
                    must_not_execute=spec.must_not_execute,
                )
        except IntegrityError as error:
            candidates = self._lock_spec_candidates(spec)
            if not candidates:
                raise ForecastBaselineConflictError(
                    "spec append violated immutable ledger constraints"
                ) from error
            return self._replay_spec(candidates, spec)
        stored = self.get_spec(VersionRef(spec.spec_id, spec.spec_version))
        if stored != spec:
            raise ForecastBaselineEvidenceError("spec repository did not preserve the exact object")
        return stored

    def get_spec(self, spec_ref: VersionRef) -> ForecastBaselineSpec | None:
        """Restore one immutable spec through the typed codec."""

        model = (
            ForecastBaselineSpecModel._default_manager.select_related("approval")
            .filter(spec_id=spec_ref.stable_id, spec_version=spec_ref.version)
            .first()
        )
        return None if model is None else self._spec_from_model(model)

    @transaction.atomic
    def append_artifact(
        self,
        artifact: ForecastBaselineArtifact,
    ) -> ForecastBaselineArtifact:
        """Append one artifact beneath its exact immutable baseline spec."""

        payload = encode_forecast_baseline_artifact(artifact)
        spec_model = (
            ForecastBaselineSpecModel._default_manager.select_for_update()
            .select_related("approval")
            .filter(
                spec_id=artifact.spec_id,
                spec_version=artifact.spec_version,
                content_hash=artifact.spec_content_hash,
            )
            .first()
        )
        if spec_model is None:
            raise ForecastBaselineEvidenceError("exact canonical baseline spec is unavailable")
        spec = self._spec_from_model(spec_model)
        self._validate_artifact_projection(spec, artifact)
        existing = self._lock_artifact_candidates(artifact)
        if existing:
            return self._replay_artifact(existing, artifact)
        try:
            with transaction.atomic():
                ForecastBaselineArtifactModel._default_manager.create(
                    spec=spec_model,
                    artifact_id=artifact.artifact_id,
                    artifact_version=artifact.artifact_version,
                    content_hash=artifact.content_hash,
                    owner=artifact.owner,
                    spec_evidence_id=artifact.spec_id,
                    spec_evidence_version=artifact.spec_version,
                    spec_evidence_content_hash=artifact.spec_content_hash,
                    knowledge_as_of=artifact.knowledge_as_of,
                    produced_at=artifact.produced_at,
                    valid_until=artifact.valid_until,
                    payload_schema=ARTIFACT_PAYLOAD_SCHEMA,
                    canonical_payload=payload,
                    research_only=artifact.research_only,
                    must_not_use_for_decision=artifact.must_not_use_for_decision,
                    must_not_execute=artifact.must_not_execute,
                )
        except IntegrityError as error:
            candidates = self._lock_artifact_candidates(artifact)
            if not candidates:
                raise ForecastBaselineConflictError(
                    "artifact append violated immutable ledger constraints"
                ) from error
            return self._replay_artifact(candidates, artifact)
        stored = self.get_artifact(VersionRef(artifact.artifact_id, artifact.artifact_version))
        if stored != artifact:
            raise ForecastBaselineEvidenceError(
                "artifact repository did not preserve the exact object"
            )
        return stored

    def get_artifact(
        self,
        artifact_ref: VersionRef,
    ) -> ForecastBaselineArtifact | None:
        """Restore one immutable baseline artifact through the typed codec."""

        model = (
            ForecastBaselineArtifactModel._default_manager.select_related(
                "spec",
                "spec__approval",
            )
            .filter(
                artifact_id=artifact_ref.stable_id,
                artifact_version=artifact_ref.version,
            )
            .first()
        )
        return None if model is None else self._artifact_from_model(model)

    @transaction.atomic
    def append_trial(
        self,
        trial: ForecastBaselineTrialResult,
    ) -> ForecastBaselineTrialResult:
        """Append one trial beneath exact spec and artifact ledger rows."""

        payload = encode_forecast_baseline_trial(trial)
        spec_model = (
            ForecastBaselineSpecModel._default_manager.select_for_update()
            .select_related("approval")
            .filter(
                spec_id=trial.spec_id,
                spec_version=trial.spec_version,
                content_hash=trial.spec_content_hash,
            )
            .first()
        )
        artifact_model = (
            ForecastBaselineArtifactModel._default_manager.select_for_update()
            .select_related("spec", "spec__approval")
            .filter(
                artifact_id=trial.baseline_artifact_id,
                artifact_version=trial.baseline_artifact_version,
                content_hash=trial.baseline_artifact_content_hash,
            )
            .first()
        )
        if spec_model is None or artifact_model is None or artifact_model.spec_id != spec_model.pk:
            raise ForecastBaselineEvidenceError("exact spec/artifact trial ancestry is unavailable")
        spec = self._spec_from_model(spec_model)
        artifact = self._artifact_from_model(artifact_model)
        self._validate_trial_projection(spec, artifact, trial)
        existing = self._lock_trial_candidates(trial)
        if existing:
            return self._replay_trial(existing, trial)
        try:
            with transaction.atomic():
                ForecastBaselineTrialResultModel._default_manager.create(
                    spec=spec_model,
                    artifact=artifact_model,
                    result_id=trial.result_id,
                    result_version=trial.result_version,
                    content_hash=trial.content_hash,
                    owner=trial.owner,
                    spec_evidence_id=trial.spec_id,
                    spec_evidence_version=trial.spec_version,
                    spec_evidence_content_hash=trial.spec_content_hash,
                    artifact_evidence_id=trial.baseline_artifact_id,
                    artifact_evidence_version=trial.baseline_artifact_version,
                    artifact_evidence_content_hash=trial.baseline_artifact_content_hash,
                    actual_manifest_id=trial.actual_manifest.manifest_id,
                    actual_manifest_version=trial.actual_manifest.manifest_version,
                    actual_manifest_content_hash=trial.actual_manifest.manifest_content_hash,
                    research_trial_id=trial.research_trial.trial_id,
                    research_trial_version=trial.research_trial.trial_version,
                    research_trial_content_hash=trial.research_trial.trial_content_hash,
                    evaluated_at=trial.evaluated_at,
                    valid_until=trial.valid_until,
                    payload_schema=TRIAL_PAYLOAD_SCHEMA,
                    canonical_payload=payload,
                    research_only=trial.research_only,
                    must_not_use_for_decision=trial.must_not_use_for_decision,
                    must_not_execute=trial.must_not_execute,
                )
        except IntegrityError as error:
            candidates = self._lock_trial_candidates(trial)
            if not candidates:
                raise ForecastBaselineConflictError(
                    "trial append violated immutable ledger constraints"
                ) from error
            return self._replay_trial(candidates, trial)
        stored = self.get_trial(VersionRef(trial.result_id, trial.result_version))
        if stored != trial:
            raise ForecastBaselineEvidenceError(
                "trial repository did not preserve the exact object"
            )
        return stored

    def get_trial(
        self,
        trial_ref: VersionRef,
    ) -> ForecastBaselineTrialResult | None:
        """Restore one immutable trial through the typed codec."""

        model = (
            ForecastBaselineTrialResultModel._default_manager.select_related(
                "spec",
                "spec__approval",
                "artifact",
                "artifact__spec",
                "artifact__spec__approval",
            )
            .filter(result_id=trial_ref.stable_id, result_version=trial_ref.version)
            .first()
        )
        return None if model is None else self._trial_from_model(model)

    @staticmethod
    def _lock_approval_candidates(
        evidence: BaselineApprovalEvidence,
    ) -> list[ForecastBaselineApprovalEvidenceModel]:
        return list(
            ForecastBaselineApprovalEvidenceModel._default_manager.select_for_update()
            .filter(
                Q(
                    approval_id=evidence.approval.stable_id,
                    approval_version=evidence.approval.version,
                )
                | Q(content_hash=evidence.approval.content_hash)
            )
            .order_by("pk")
        )

    @staticmethod
    def _lock_spec_candidates(spec: ForecastBaselineSpec) -> list[ForecastBaselineSpecModel]:
        return list(
            ForecastBaselineSpecModel._default_manager.select_for_update()
            .filter(
                Q(spec_id=spec.spec_id, spec_version=spec.spec_version)
                | Q(content_hash=spec.content_hash)
            )
            .order_by("pk")
        )

    @staticmethod
    def _lock_artifact_candidates(
        artifact: ForecastBaselineArtifact,
    ) -> list[ForecastBaselineArtifactModel]:
        return list(
            ForecastBaselineArtifactModel._default_manager.select_for_update()
            .select_related("spec", "spec__approval")
            .filter(
                Q(
                    artifact_id=artifact.artifact_id,
                    artifact_version=artifact.artifact_version,
                )
                | Q(content_hash=artifact.content_hash)
            )
            .order_by("pk")
        )

    @staticmethod
    def _lock_trial_candidates(
        trial: ForecastBaselineTrialResult,
    ) -> list[ForecastBaselineTrialResultModel]:
        return list(
            ForecastBaselineTrialResultModel._default_manager.select_for_update()
            .select_related(
                "spec",
                "spec__approval",
                "artifact",
                "artifact__spec",
                "artifact__spec__approval",
            )
            .filter(
                Q(result_id=trial.result_id, result_version=trial.result_version)
                | Q(content_hash=trial.content_hash)
            )
            .order_by("pk")
        )

    def _replay_approval(
        self,
        candidates: list[ForecastBaselineApprovalEvidenceModel],
        expected: BaselineApprovalEvidence,
    ) -> BaselineApprovalEvidence:
        if len(candidates) != 1:
            raise ForecastBaselineConflictError("approval identity maps to multiple ledger rows")
        restored = self._approval_from_model(candidates[0])
        if restored != expected:
            raise ForecastBaselineConflictError(
                "approval identity already has conflicting immutable content"
            )
        return restored

    def _replay_spec(
        self,
        candidates: list[ForecastBaselineSpecModel],
        expected: ForecastBaselineSpec,
    ) -> ForecastBaselineSpec:
        if len(candidates) != 1:
            raise ForecastBaselineConflictError("spec identity maps to multiple ledger rows")
        restored = self._spec_from_model(candidates[0])
        if restored != expected:
            raise ForecastBaselineConflictError(
                "spec identity already has conflicting immutable content"
            )
        return restored

    def _replay_artifact(
        self,
        candidates: list[ForecastBaselineArtifactModel],
        expected: ForecastBaselineArtifact,
    ) -> ForecastBaselineArtifact:
        if len(candidates) != 1:
            raise ForecastBaselineConflictError("artifact identity maps to multiple ledger rows")
        restored = self._artifact_from_model(candidates[0])
        if restored != expected:
            raise ForecastBaselineConflictError(
                "artifact identity already has conflicting immutable content"
            )
        return restored

    def _replay_trial(
        self,
        candidates: list[ForecastBaselineTrialResultModel],
        expected: ForecastBaselineTrialResult,
    ) -> ForecastBaselineTrialResult:
        if len(candidates) != 1:
            raise ForecastBaselineConflictError("trial identity maps to multiple ledger rows")
        restored = self._trial_from_model(candidates[0])
        if restored != expected:
            raise ForecastBaselineConflictError(
                "trial identity already has conflicting immutable content"
            )
        return restored

    @staticmethod
    def _approval_from_model(
        model: ForecastBaselineApprovalEvidenceModel,
    ) -> BaselineApprovalEvidence:
        evidence = decode_approval_evidence(model.canonical_payload)
        if (
            model.payload_schema != APPROVAL_PAYLOAD_SCHEMA
            or model.approval_id != evidence.approval.stable_id
            or model.approval_version != evidence.approval.version
            or model.content_hash != evidence.approval.content_hash
            or model.owner != evidence.approval_owner
            or model.status != evidence.approval_status.value
            or model.forecast_origin_at != evidence.forecast_origin_at
            or model.approved_at != evidence.approved_at
            or model.recorded_at != evidence.recorded_at
            or model.valid_until != evidence.valid_until
            or not model.research_only
            or not model.must_not_use_for_decision
            or not model.must_not_execute
        ):
            raise ForecastBaselineEvidenceError("approval ledger header/payload mismatch")
        return evidence

    @staticmethod
    def _spec_from_model(model: ForecastBaselineSpecModel) -> ForecastBaselineSpec:
        spec = decode_forecast_baseline_spec(model.canonical_payload)
        approval = DjangoForecastBaselineRepository._approval_from_model(model.approval)
        DjangoForecastBaselineRepository._validate_spec_projection(approval, spec)
        forecast_origin_at = spec.period_horizons[0].forecast_origin_at
        if (
            model.payload_schema != SPEC_PAYLOAD_SCHEMA
            or model.spec_id != spec.spec_id
            or model.spec_version != spec.spec_version
            or model.content_hash != spec.content_hash
            or model.owner != spec.owner
            or model.approval_evidence_id != spec.approval_evidence_id
            or model.approval_evidence_version != spec.approval_evidence_version
            or model.approval_evidence_content_hash != spec.approval_evidence_content_hash
            or model.approval_recorded_at != spec.approval_recorded_at
            or model.forecast_origin_at != forecast_origin_at
            or model.approved_at != spec.approved_at
            or model.valid_until != spec.valid_until
            or model.research_only != spec.research_only
            or model.must_not_use_for_decision != spec.must_not_use_for_decision
            or model.must_not_execute != spec.must_not_execute
            or model.approval.approval_id != spec.approval_evidence_id
            or model.approval.approval_version != spec.approval_evidence_version
            or model.approval.content_hash != spec.approval_evidence_content_hash
            or model.approval.recorded_at != spec.approval_recorded_at
        ):
            raise ForecastBaselineEvidenceError("spec ledger header/payload mismatch")
        return spec

    @staticmethod
    def _artifact_from_model(
        model: ForecastBaselineArtifactModel,
    ) -> ForecastBaselineArtifact:
        artifact = decode_forecast_baseline_artifact(model.canonical_payload)
        spec = DjangoForecastBaselineRepository._spec_from_model(model.spec)
        DjangoForecastBaselineRepository._validate_artifact_projection(spec, artifact)
        if (
            model.payload_schema != ARTIFACT_PAYLOAD_SCHEMA
            or model.artifact_id != artifact.artifact_id
            or model.artifact_version != artifact.artifact_version
            or model.content_hash != artifact.content_hash
            or model.owner != artifact.owner
            or model.spec_evidence_id != artifact.spec_id
            or model.spec_evidence_version != artifact.spec_version
            or model.spec_evidence_content_hash != artifact.spec_content_hash
            or model.knowledge_as_of != artifact.knowledge_as_of
            or model.produced_at != artifact.produced_at
            or model.valid_until != artifact.valid_until
            or model.research_only != artifact.research_only
            or model.must_not_use_for_decision != artifact.must_not_use_for_decision
            or model.must_not_execute != artifact.must_not_execute
            or model.spec.spec_id != artifact.spec_id
            or model.spec.spec_version != artifact.spec_version
            or model.spec.content_hash != artifact.spec_content_hash
        ):
            raise ForecastBaselineEvidenceError("artifact ledger header/payload mismatch")
        return artifact

    @staticmethod
    def _trial_from_model(
        model: ForecastBaselineTrialResultModel,
    ) -> ForecastBaselineTrialResult:
        trial = decode_forecast_baseline_trial(model.canonical_payload)
        spec = DjangoForecastBaselineRepository._spec_from_model(model.spec)
        artifact = DjangoForecastBaselineRepository._artifact_from_model(model.artifact)
        DjangoForecastBaselineRepository._validate_trial_projection(spec, artifact, trial)
        if (
            model.payload_schema != TRIAL_PAYLOAD_SCHEMA
            or model.result_id != trial.result_id
            or model.result_version != trial.result_version
            or model.content_hash != trial.content_hash
            or model.owner != trial.owner
            or model.spec_evidence_id != trial.spec_id
            or model.spec_evidence_version != trial.spec_version
            or model.spec_evidence_content_hash != trial.spec_content_hash
            or model.artifact_evidence_id != trial.baseline_artifact_id
            or model.artifact_evidence_version != trial.baseline_artifact_version
            or model.artifact_evidence_content_hash != trial.baseline_artifact_content_hash
            or model.actual_manifest_id != trial.actual_manifest.manifest_id
            or model.actual_manifest_version != trial.actual_manifest.manifest_version
            or model.actual_manifest_content_hash != trial.actual_manifest.manifest_content_hash
            or model.research_trial_id != trial.research_trial.trial_id
            or model.research_trial_version != trial.research_trial.trial_version
            or model.research_trial_content_hash != trial.research_trial.trial_content_hash
            or model.evaluated_at != trial.evaluated_at
            or model.valid_until != trial.valid_until
            or model.research_only != trial.research_only
            or model.must_not_use_for_decision != trial.must_not_use_for_decision
            or model.must_not_execute != trial.must_not_execute
            or model.spec.spec_id != trial.spec_id
            or model.spec.spec_version != trial.spec_version
            or model.spec.content_hash != trial.spec_content_hash
            or model.artifact.artifact_id != trial.baseline_artifact_id
            or model.artifact.artifact_version != trial.baseline_artifact_version
            or model.artifact.content_hash != trial.baseline_artifact_content_hash
            or model.artifact.spec_id != model.spec_id
        ):
            raise ForecastBaselineEvidenceError("trial ledger header/payload mismatch")
        return trial

    @staticmethod
    def _validate_artifact_projection(
        spec: ForecastBaselineSpec,
        artifact: ForecastBaselineArtifact,
    ) -> None:
        """Require the artifact's spec-derived surface to be byte-for-byte exact."""

        if (
            (artifact.spec_id, artifact.spec_version, artifact.spec_content_hash)
            != (spec.spec_id, spec.spec_version, spec.content_hash)
            or artifact.owner != spec.owner
            or artifact.evaluation_policy != spec.evaluation_policy
            or artifact.subject_code != spec.subject_code
            or artifact.industry_code != spec.industry_code
            or artifact.candidate_scenario is not spec.candidate_scenario
            or artifact.horizon_quarters != spec.horizon_quarters
            or artifact.calendar_schedule != spec.calendar_schedule
            or artifact.period_horizons != spec.period_horizons
            or artifact.family is not spec.family
            or artifact.computation_method is not spec.computation_method
            or artifact.computation_code_version != spec.computation_code_version
            or artifact.family_parameter_version != spec.family_parameter_version
            or artifact.family_parameter_hash != spec.family_parameter_hash
            or artifact.seasonal_lag_periods != spec.seasonal_lag_periods
            or artifact.pit_inputs != spec.pit_inputs
            or artifact.expected_period_ends != spec.expected_period_ends
            or artifact.metric_codes != tuple(item.metric_code for item in spec.metric_rules)
            or artifact.valid_until > spec.valid_until
        ):
            raise ForecastBaselineEvidenceError(
                "baseline artifact is not the exact canonical spec projection"
            )

    @staticmethod
    def _validate_trial_projection(
        spec: ForecastBaselineSpec,
        artifact: ForecastBaselineArtifact,
        trial: ForecastBaselineTrialResult,
    ) -> None:
        """Require trial ancestry and every inherited evaluation rule to match."""

        try:
            rebuilt = ForecastBaselineTrialResult.create(
                result_id=trial.result_id,
                result_version=trial.result_version,
                owner=trial.owner,
                research_trial=trial.research_trial,
                spec=spec,
                artifact=artifact,
                paired_rows=trial.paired_rows,
                actual_manifest=trial.actual_manifest,
                evaluated_at=trial.evaluated_at,
                valid_until=trial.valid_until,
            )
        except ValueError as error:
            raise ForecastBaselineEvidenceError(
                "baseline trial cannot be rebuilt from canonical ancestry"
            ) from error
        if (
            rebuilt != trial
            or (trial.spec_id, trial.spec_version, trial.spec_content_hash)
            != (spec.spec_id, spec.spec_version, spec.content_hash)
            or (
                trial.baseline_artifact_id,
                trial.baseline_artifact_version,
                trial.baseline_artifact_content_hash,
            )
            != (artifact.artifact_id, artifact.artifact_version, artifact.content_hash)
            or trial.owner != spec.owner
            or trial.expected_period_ends != spec.expected_period_ends
            or trial.metric_rules != spec.metric_rules
            or trial.metric_evaluation_order != spec.metric_evaluation_order
            or trial.tie_break_rule is not spec.tie_break_rule
            or trial.cost_rule != spec.cost_rule
            or trial.invalidation_applicability is not spec.invalidation_applicability
            or trial.invalidation_rules != spec.invalidation_rules
            or trial.invalidation_not_applicable_reason != spec.invalidation_not_applicable_reason
            or trial.forecasts != artifact.forecasts
            or trial.research_trial.split_spec_hash != forecast_baseline_trial_split_hash(spec)
            or trial.research_trial.parameter_hash != forecast_baseline_trial_parameter_hash(spec)
            or trial.valid_until > min(spec.valid_until, artifact.valid_until)
        ):
            raise ForecastBaselineEvidenceError(
                "baseline trial is not the exact canonical spec/artifact projection"
            )

    @staticmethod
    def _validate_spec_projection(
        approval: BaselineApprovalEvidence,
        spec: ForecastBaselineSpec,
    ) -> None:
        """Require every approval-derived spec field to remain an exact projection."""

        approved_metrics = tuple(
            sorted(
                (
                    BaselineMetricRule(
                        metric_code=item.metric_code,
                        error_metric=item.error_metric,
                        maximum_forecast_error=item.maximum_forecast_error,
                        minimum_improvement=item.minimum_improvement,
                        minimum_sample_count=item.minimum_sample_count,
                        minimum_coverage=item.minimum_coverage,
                        mape_zero_actual_rule=item.mape_zero_actual_rule,
                    )
                    for item in approval.metric_rules
                ),
                key=lambda item: item.metric_code,
            )
        )
        approved_invalidations = tuple(
            sorted(
                (
                    BaselineInvalidationRule(
                        rule_code=item.rule_code,
                        metric_code=item.metric_code,
                        operator=item.operator,
                        threshold=item.threshold,
                        consecutive_periods=item.consecutive_periods,
                    )
                    for item in approval.invalidation_rules
                ),
                key=lambda item: item.rule_code,
            )
        )
        cost_model = approval.cost_rule.cost_model
        approved_cost = BaselineCostRule(
            applicability=approval.cost_rule.applicability,
            cost_model_version=cost_model.version if cost_model is not None else "",
            cost_model_content_hash=cost_model.content_hash if cost_model is not None else "",
            not_applicable_reason=approval.cost_rule.not_applicable_reason,
        )
        requested_inputs = {item.input_role: item for item in approval.pit_inputs}
        projected_inputs = {item.input_role: item for item in spec.pit_inputs}
        input_projection_matches = (
            len(requested_inputs) == len(approval.pit_inputs)
            and len(projected_inputs) == len(spec.pit_inputs)
            and set(requested_inputs) == set(projected_inputs)
            and all(
                projected.dataset == requested.dataset
                and projected.metric_code == requested.metric_code
                and projected.unit == requested.unit
                and projected.manifest_knowledge_scope == requested.knowledge_scope
                and projected.pit_manifest_id == requested.manifest.stable_id
                and projected.pit_manifest_version == requested.manifest.version
                and projected.pit_manifest_hash == requested.manifest.content_hash
                for role, requested in requested_inputs.items()
                for projected in (projected_inputs[role],)
            )
        )
        calendar_identity = (
            spec.calendar_schedule.calendar_id,
            spec.calendar_schedule.calendar_version,
            spec.calendar_schedule.calendar_content_hash,
        )
        approval_identity = (
            approval.approval.stable_id,
            approval.approval.version,
            approval.approval.content_hash,
        )
        if (
            (
                spec.approval_evidence_id,
                spec.approval_evidence_version,
                spec.approval_evidence_content_hash,
            )
            != approval_identity
            or (spec.spec_id, spec.spec_version)
            != (approval.spec_ref.stable_id, approval.spec_ref.version)
            or spec.approval_owner != approval.approval_owner
            or spec.approval_status is not approval.approval_status
            or spec.approval_recorded_at != approval.recorded_at
            or spec.evaluation_policy != approval.evaluation_policy
            or spec.subject_code != approval.subject_code
            or spec.industry_code != approval.industry_code
            or spec.candidate_scenario is not approval.candidate_scenario
            or spec.horizon_quarters != approval.horizon_quarters
            or spec.family is not approval.family
            or spec.computation_method is not approval.computation_method
            or spec.computation_code_version != approval.computation_code_version
            or spec.family_parameter_version != approval.family_parameter_version
            or spec.family_parameter_hash != approval.family_parameter_hash
            or spec.seasonal_lag_periods != approval.seasonal_lag_periods
            or spec.training_window_start != approval.training_window_start
            or spec.training_window_end != approval.training_window_end
            or spec.expected_period_ends != approval.expected_period_ends
            or calendar_identity
            != (
                approval.calendar.stable_id,
                approval.calendar.version,
                approval.calendar.content_hash,
            )
            or any(
                item.forecast_origin_at != approval.forecast_origin_at
                for item in spec.period_horizons
            )
            or spec.metric_rules != approved_metrics
            or spec.metric_evaluation_order != approval.metric_evaluation_order
            or spec.tie_break_rule is not approval.tie_break_rule
            or spec.cost_rule != approved_cost
            or spec.invalidation_applicability is not approval.invalidation_applicability
            or spec.invalidation_rules != approved_invalidations
            or spec.invalidation_not_applicable_reason
            != approval.invalidation_not_applicable_reason
            or spec.approved_at != approval.approved_at
            or spec.valid_until != approval.valid_until
            or not input_projection_matches
        ):
            raise ForecastBaselineEvidenceError(
                "baseline spec is not the exact canonical approval projection"
            )


class DjangoForecastBaselineEvaluationClock:
    """Django-backed trusted clock for R1 trial evaluation."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the canonical database identity used by the repository."""

        return "django:default"

    def now(self) -> datetime:
        """Return one timezone-aware server evaluation timestamp."""

        return timezone.now()


class DjangoForecastBaselineEvaluationReadRepository:
    """Read-only spec/artifact UoW for the production preflight surface."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        if type(using) is not str or not using.strip() or len(using) > 192:
            raise ValueError("forecast baseline read database alias is invalid")
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact shared database identity."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Open one shared transaction without retaining a write capability."""

        return transaction.atomic(using=self._using)

    def server_now(self) -> datetime:
        """Return the trusted server clock used by the read-only preflight."""

        return timezone.now()

    def get_spec(self, spec_ref: VersionRef) -> ForecastBaselineSpec | None:
        """Restore one exact immutable spec through its full approval ancestry."""

        if type(spec_ref) is not VersionRef:
            raise ForecastBaselineEvidenceError("baseline spec reference type differs")
        VersionRef.__post_init__(spec_ref)
        model = (
            ForecastBaselineSpecModel._default_manager.using(self._using)
            .select_related("approval")
            .filter(
                spec_id=spec_ref.stable_id,
                spec_version=spec_ref.version,
            )
            .first()
        )
        return None if model is None else DjangoForecastBaselineRepository._spec_from_model(model)

    def get_artifact(
        self,
        artifact_ref: VersionRef,
    ) -> ForecastBaselineArtifact | None:
        """Restore one exact immutable artifact through its full spec ancestry."""

        if type(artifact_ref) is not VersionRef:
            raise ForecastBaselineEvidenceError("baseline artifact reference type differs")
        VersionRef.__post_init__(artifact_ref)
        model = (
            ForecastBaselineArtifactModel._default_manager.using(self._using)
            .select_related("spec", "spec__approval")
            .filter(
                artifact_id=artifact_ref.stable_id,
                artifact_version=artifact_ref.version,
            )
            .first()
        )
        return (
            None if model is None else DjangoForecastBaselineRepository._artifact_from_model(model)
        )


__all__ = [
    "DjangoForecastBaselineEvaluationClock",
    "DjangoForecastBaselineEvaluationReadRepository",
    "DjangoForecastBaselineRepository",
]
