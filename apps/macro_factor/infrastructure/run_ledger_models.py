"""Append-only ORM ledger for reproducible R3 runs, outputs, and lifecycle."""

from __future__ import annotations

from decimal import Decimal
from typing import NoReturn, cast

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.macro_factor.domain._runner_support import hash_payload, utc_text
from apps.macro_factor.domain.baselines import DeterministicErrorMetrics, FoldBenchmarkResult
from apps.macro_factor.domain.dated_outputs import DatedMacroFactorOutput
from apps.macro_factor.domain.entities import FactorOutputRole
from apps.macro_factor.domain.lifecycle import (
    MacroFactorLifecycleEvent,
    MacroFactorLifecycleEventType,
)
from apps.macro_factor.domain.lifecycle_stream import (
    MacroFactorLifecycleStreamCommit,
    MacroFactorLifecycleStreamHead,
)
from apps.macro_factor.domain.run_artifacts import ReproducibleMacroFactorRunArtifact

from .append_only import MacroFactorAppendOnlyModel
from .lifecycle_head_guard import LifecycleHeadGuardedModel
from .models import MacroFactorResearchResultModel


def _validate_artifact_source_binding(
    artifact: ReproducibleMacroFactorRunArtifact,
    source: MacroFactorResearchResultModel,
) -> None:
    """Require artifact columns to identify the exact sealed source result."""

    source.to_domain()
    source_payload = _mapping(source.payload, "source result payload")
    target = _mapping(source_payload.get("target"), "source result target")
    reproducibility = _mapping(
        source_payload.get("reproducibility"),
        "source result reproducibility",
    )
    selection = _mapping(source_payload.get("selection"), "source result selection")
    weights = _mapping(source_payload.get("weights"), "source result weights")
    if (
        source.result_id != artifact.source_result_id
        or source.content_hash != artifact.source_result_hash
        or source.factor_version != artifact.factor_version
        or source.factor_version != source_payload.get("factor_version")
        or source.target_code != artifact.target_code
        or source.target_code != target.get("target_code")
        or target.get("output_role") != artifact.output_role.value
        or source.evidence_produced_at != artifact.produced_at
        or weights.get("calculated_at") != utc_text(artifact.produced_at)
        or source.pit_manifest_id != artifact.pit_manifest_id
        or source.pit_manifest_id != source_payload.get("pit_manifest_id")
        or source.pit_manifest_hash != artifact.pit_manifest_hash
        or source.pit_manifest_hash != source_payload.get("pit_manifest_hash")
        or source.code_version != artifact.code_version
        or source.code_version != reproducibility.get("code_version")
        or source.parameter_version != artifact.parameter_version
        or source.parameter_version != reproducibility.get("parameter_version")
        or reproducibility.get("dependency_lock_hash") != artifact.dependency_lock_hash
        or reproducibility.get("parameter_hash") != artifact.parameter_hash
        or source.external_evidence_id != selection.get("evidence_id")
    ):
        raise ValueError("run artifact does not exactly bind its source result")


def _validate_output_artifact_binding(
    output: DatedMacroFactorOutput,
    artifact: ReproducibleMacroFactorRunArtifact,
    source: MacroFactorResearchResultModel,
) -> None:
    """Require a dated output to preserve every artifact and target identity."""

    source_payload = _mapping(source.payload, "source result payload")
    target = _mapping(source_payload.get("target"), "source result target")
    try:
        target_horizon_periods = int(str(target.get("horizon_periods")))
    except ValueError as exc:
        raise ValueError("source result target horizon is invalid") from exc
    if (
        output.artifact_id != artifact.artifact_id
        or output.artifact_hash != artifact.content_hash
        or output.factor_version != artifact.factor_version
        or output.target_code != artifact.target_code
        or output.output_role is not artifact.output_role
        or output.produced_at != artifact.produced_at
        or output.pit_manifest_id != artifact.pit_manifest_id
        or output.pit_manifest_hash != artifact.pit_manifest_hash
        or output.horizon_periods != target_horizon_periods
        or output.horizon_unit != target.get("horizon_unit")
        or output.unit != target.get("unit")
    ):
        raise ValueError("dated output does not exactly bind its run artifact")


def _validate_event_artifact_binding(
    event: MacroFactorLifecycleEvent,
    artifact: ReproducibleMacroFactorRunArtifact,
    source: MacroFactorResearchResultModel,
) -> None:
    """Require lifecycle links to preserve artifact, factor, and policy identity."""

    source_payload = _mapping(source.payload, "source result payload")
    policy = _mapping(
        source_payload.get("retirement_policy"),
        "source result retirement policy",
    )
    if (
        event.artifact_id != artifact.artifact_id
        or event.artifact_hash != artifact.content_hash
        or event.factor_version != artifact.factor_version
        or event.policy_version != policy.get("policy_version")
        or event.policy_hash != hash_payload(policy)
    ):
        raise ValueError("lifecycle event does not exactly bind its run artifact")


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return cast(dict[str, object], value)


def _decimal(value: object, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field_name} must be decimal text") from exc
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _metrics(value: object, field_name: str) -> DeterministicErrorMetrics:
    payload = _mapping(value, field_name)
    raw_r_squared = payload.get("r_squared")
    return DeterministicErrorMetrics(
        sample_count=int(str(payload.get("sample_count"))),
        mean_squared_error=_decimal(
            payload.get("mean_squared_error"),
            f"{field_name}.mean_squared_error",
        ),
        mean_absolute_error=_decimal(
            payload.get("mean_absolute_error"),
            f"{field_name}.mean_absolute_error",
        ),
        r_squared=(
            None if raw_r_squared is None else _decimal(raw_r_squared, f"{field_name}.r_squared")
        ),
    )


def _fold_benchmarks(payload: dict[str, object]) -> tuple[FoldBenchmarkResult, ...]:
    raw = payload.get("fold_benchmarks")
    if not isinstance(raw, list) or not raw:
        raise ValueError("fold_benchmarks must be a non-empty array")
    results: list[FoldBenchmarkResult] = []
    for index, item in enumerate(raw):
        row = _mapping(item, f"fold_benchmarks[{index}]")
        results.append(
            FoldBenchmarkResult(
                fold_id=str(row.get("fold_id")),
                historical_mean=_metrics(
                    row.get("historical_mean"),
                    f"fold_benchmarks[{index}].historical_mean",
                ),
                fixed_fmp=_metrics(
                    row.get("fixed_fmp"),
                    f"fold_benchmarks[{index}].fixed_fmp",
                ),
                external_model=_metrics(
                    row.get("external_model"),
                    f"fold_benchmarks[{index}].external_model",
                ),
            )
        )
    return tuple(results)


class MacroFactorRunArtifactModel(MacroFactorAppendOnlyModel):
    """Complete local manifest for one canonical external nested-CV run."""

    artifact_id = models.CharField(max_length=64, primary_key=True)
    run_key = models.CharField(max_length=160, db_index=True)
    run_version = models.PositiveIntegerField()
    factor_version = models.CharField(max_length=160, db_index=True)
    target_code = models.CharField(max_length=160, db_index=True)
    output_role = models.CharField(
        max_length=32,
        choices=[(item.value, item.value) for item in FactorOutputRole],
        db_index=True,
    )
    produced_at = models.DateTimeField(db_index=True)
    source_result = models.ForeignKey(
        MacroFactorResearchResultModel,
        on_delete=models.PROTECT,
        related_name="run_artifacts",
    )
    source_result_hash = models.CharField(max_length=64)
    external_evidence_id = models.CharField(max_length=160, db_index=True)
    external_producer_ref = models.CharField(max_length=500)
    external_artifact_hash = models.CharField(max_length=64)
    external_artifact_media_type = models.CharField(max_length=100)
    external_artifact_content_length = models.PositiveBigIntegerField()
    external_artifact_bytes = models.BinaryField()
    request_hash = models.CharField(max_length=64, unique=True)
    pit_manifest_id = models.CharField(max_length=160, db_index=True)
    pit_manifest_hash = models.CharField(max_length=64)
    dataset_hash = models.CharField(max_length=64)
    benchmark_version = models.CharField(max_length=160)
    benchmark_hash = models.CharField(max_length=64)
    fixed_fmp_version = models.CharField(max_length=160)
    fixed_fmp_hash = models.CharField(max_length=64)
    cost_model_version = models.CharField(max_length=160)
    cost_model_hash = models.CharField(max_length=64)
    split_contract_version = models.CharField(max_length=160)
    split_contract_hash = models.CharField(max_length=64)
    plan_hash = models.CharField(max_length=64)
    selection_protocol_version = models.CharField(max_length=160)
    selection_protocol_hash = models.CharField(max_length=64)
    metrics_protocol_version = models.CharField(max_length=160)
    metrics_protocol_hash = models.CharField(max_length=64)
    timing_policy_version = models.CharField(max_length=160)
    timing_policy_hash = models.CharField(max_length=64)
    code_version = models.CharField(max_length=160)
    dependency_lock_hash = models.CharField(max_length=64)
    parameter_version = models.CharField(max_length=160)
    parameter_hash = models.CharField(max_length=64)
    random_seed = models.PositiveBigIntegerField()
    content_hash = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()
    research_only = models.BooleanField(default=True, editable=False)
    must_not_use_for_decision = models.BooleanField(default=True, editable=False)
    must_not_execute = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "macro_factor_run_artifact"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["run_key", "run_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["run_key", "run_version"],
                name="macro_factor_run_key_version_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="macro_factor_run_research_blocked_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["target_code", "output_role", "-produced_at"],
                name="mf_run_target_time_idx",
            ),
            models.Index(
                fields=["factor_version", "-produced_at"],
                name="mf_run_factor_time_idx",
            ),
        ]

    def to_domain(self) -> ReproducibleMacroFactorRunArtifact:
        """Restore and verify the full hash-sealed run artifact."""

        payload = _mapping(self.payload, "run artifact payload")
        artifact = ReproducibleMacroFactorRunArtifact(
            artifact_id=self.artifact_id,
            run_key=self.run_key,
            run_version=self.run_version,
            factor_version=self.factor_version,
            target_code=self.target_code,
            output_role=FactorOutputRole(self.output_role),
            produced_at=self.produced_at,
            source_result_id=self.source_result_id,
            source_result_hash=self.source_result_hash,
            external_evidence_id=self.external_evidence_id,
            external_producer_ref=self.external_producer_ref,
            external_artifact_hash=self.external_artifact_hash,
            external_artifact_media_type=self.external_artifact_media_type,
            external_artifact_content_length=self.external_artifact_content_length,
            external_artifact_bytes=bytes(self.external_artifact_bytes),
            request_hash=self.request_hash,
            pit_manifest_id=self.pit_manifest_id,
            pit_manifest_hash=self.pit_manifest_hash,
            dataset_hash=self.dataset_hash,
            benchmark_version=self.benchmark_version,
            benchmark_hash=self.benchmark_hash,
            fixed_fmp_version=self.fixed_fmp_version,
            fixed_fmp_hash=self.fixed_fmp_hash,
            cost_model_version=self.cost_model_version,
            cost_model_hash=self.cost_model_hash,
            split_contract_version=self.split_contract_version,
            split_contract_hash=self.split_contract_hash,
            plan_hash=self.plan_hash,
            selection_protocol_version=self.selection_protocol_version,
            selection_protocol_hash=self.selection_protocol_hash,
            metrics_protocol_version=self.metrics_protocol_version,
            metrics_protocol_hash=self.metrics_protocol_hash,
            timing_policy_version=self.timing_policy_version,
            timing_policy_hash=self.timing_policy_hash,
            code_version=self.code_version,
            dependency_lock_hash=self.dependency_lock_hash,
            parameter_version=self.parameter_version,
            parameter_hash=self.parameter_hash,
            random_seed=self.random_seed,
            fold_benchmarks=_fold_benchmarks(payload),
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_execute=self.must_not_execute,
        )
        if artifact.canonical_payload != payload or artifact.content_hash != self.content_hash:
            raise ValueError("run artifact payload/hash does not match columns")
        _validate_artifact_source_binding(artifact, self.source_result)
        return artifact

    def clean(self) -> None:
        """Reject column/payload/hash or source-result mismatches."""

        super().clean()
        try:
            artifact = self.to_domain()
        except (TypeError, ValueError) as exc:
            raise ValidationError("invalid macro-factor run artifact") from exc
        if self.source_result.content_hash != artifact.source_result_hash:
            raise ValidationError("run artifact source-result hash mismatch")


class MacroFactorDatedOutputModel(MacroFactorAppendOnlyModel):
    """One immutable current-state or forward-expectation research output."""

    output_id = models.CharField(max_length=64, primary_key=True)
    artifact = models.ForeignKey(
        MacroFactorRunArtifactModel,
        on_delete=models.PROTECT,
        related_name="dated_outputs",
    )
    artifact_hash = models.CharField(max_length=64)
    factor_version = models.CharField(max_length=160, db_index=True)
    target_code = models.CharField(max_length=160, db_index=True)
    output_role = models.CharField(
        max_length=32,
        choices=[(item.value, item.value) for item in FactorOutputRole],
        db_index=True,
    )
    observation_date = models.DateField(db_index=True)
    target_period_start = models.DateField()
    target_period_end = models.DateField()
    horizon_periods = models.PositiveIntegerField()
    horizon_unit = models.CharField(max_length=160)
    knowledge_as_of = models.DateTimeField(db_index=True)
    produced_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    value = models.DecimalField(max_digits=38, decimal_places=18)
    unit = models.CharField(max_length=160)
    pit_manifest_id = models.CharField(max_length=160, db_index=True)
    pit_manifest_hash = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()
    research_only = models.BooleanField(default=True, editable=False)
    must_not_use_for_decision = models.BooleanField(default=True, editable=False)
    must_not_execute = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "macro_factor_dated_output"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["artifact_id", "output_role", "observation_date"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "artifact",
                    "output_role",
                    "observation_date",
                    "target_period_start",
                    "target_period_end",
                ],
                name="macro_factor_output_identity_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(target_period_end__gte=models.F("target_period_start")),
                name="macro_factor_output_period_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(produced_at__gte=models.F("knowledge_as_of")),
                name="macro_factor_output_knowledge_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_until__gt=models.F("produced_at")),
                name="macro_factor_output_validity_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(output_role="current_state", horizon_periods=0)
                    | models.Q(output_role="forward_expectation", horizon_periods__gt=0)
                ),
                name="macro_factor_output_horizon_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="macro_factor_output_research_blocked_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["target_code", "output_role", "-observation_date"],
                name="macro_factor_output_target_idx",
            ),
            models.Index(
                fields=["valid_until", "output_role"],
                name="macro_factor_output_valid_idx",
            ),
        ]

    def to_domain(self) -> DatedMacroFactorOutput:
        """Restore and verify one dated output."""

        output = DatedMacroFactorOutput(
            output_id=self.output_id,
            artifact_id=self.artifact_id,
            artifact_hash=self.artifact_hash,
            factor_version=self.factor_version,
            target_code=self.target_code,
            output_role=FactorOutputRole(self.output_role),
            observation_date=self.observation_date,
            target_period_start=self.target_period_start,
            target_period_end=self.target_period_end,
            horizon_periods=self.horizon_periods,
            horizon_unit=self.horizon_unit,
            knowledge_as_of=self.knowledge_as_of,
            produced_at=self.produced_at,
            valid_until=self.valid_until,
            value=self.value,
            unit=self.unit,
            pit_manifest_id=self.pit_manifest_id,
            pit_manifest_hash=self.pit_manifest_hash,
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_execute=self.must_not_execute,
        )
        payload = _mapping(self.payload, "dated output payload")
        if output.canonical_payload != payload or output.content_hash != self.content_hash:
            raise ValueError("dated output payload/hash does not match columns")
        artifact = self.artifact.to_domain()
        _validate_output_artifact_binding(output, artifact, self.artifact.source_result)
        return output

    def clean(self) -> None:
        """Reject artifact or canonical output mismatches."""

        super().clean()
        try:
            output = self.to_domain()
        except (TypeError, ValueError) as exc:
            raise ValidationError("invalid macro-factor dated output") from exc
        if self.artifact.content_hash != output.artifact_hash:
            raise ValidationError("dated output artifact hash mismatch")


class MacroFactorLifecycleEventModel(MacroFactorAppendOnlyModel):
    """Immutable root or retirement link in one artifact lifecycle chain."""

    event_id = models.CharField(max_length=160, primary_key=True)
    artifact = models.ForeignKey(
        MacroFactorRunArtifactModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_events",
    )
    artifact_hash = models.CharField(max_length=64)
    factor_version = models.CharField(max_length=160, db_index=True)
    event_type = models.CharField(
        max_length=24,
        choices=[(item.value, item.value) for item in MacroFactorLifecycleEventType],
        db_index=True,
    )
    sequence = models.PositiveIntegerField()
    occurred_at = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField()
    policy_version = models.CharField(max_length=160)
    policy_hash = models.CharField(max_length=64)
    reason_codes = models.JSONField()
    evidence_hash = models.CharField(max_length=64)
    previous_event_hash = models.CharField(max_length=64, null=True, blank=True)
    owner_attestation_id = models.CharField(max_length=160, null=True, blank=True)
    owner_attestation_hash = models.CharField(max_length=64, null=True, blank=True)
    owner_attestation_owner_ref = models.CharField(max_length=160, null=True, blank=True)
    owner_attestation_media_type = models.CharField(max_length=100, null=True, blank=True)
    owner_attestation_content_length = models.PositiveBigIntegerField(null=True, blank=True)
    owner_attestation_issued_at = models.DateTimeField(null=True, blank=True)
    owner_attestation_bytes = models.BinaryField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()
    research_only = models.BooleanField(default=True, editable=False)
    must_not_use_for_decision = models.BooleanField(default=True, editable=False)
    must_not_execute = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "macro_factor_lifecycle_event"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["artifact_id", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["artifact", "sequence"],
                name="macro_factor_lifecycle_sequence_uniq",
            ),
            models.UniqueConstraint(
                fields=["artifact", "event_type"],
                name="macro_factor_lifecycle_type_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        sequence=1,
                        event_type="recorded",
                        previous_event_hash__isnull=True,
                        owner_attestation_id__isnull=True,
                        owner_attestation_hash__isnull=True,
                        owner_attestation_owner_ref__isnull=True,
                        owner_attestation_media_type__isnull=True,
                        owner_attestation_content_length__isnull=True,
                        owner_attestation_issued_at__isnull=True,
                        owner_attestation_bytes__isnull=True,
                    )
                    | models.Q(
                        sequence__gt=1,
                        event_type="retired",
                        previous_event_hash__isnull=False,
                        owner_attestation_id__isnull=False,
                        owner_attestation_hash__isnull=False,
                        owner_attestation_owner_ref__isnull=False,
                        owner_attestation_media_type__isnull=False,
                        owner_attestation_content_length__isnull=False,
                        owner_attestation_issued_at__isnull=False,
                        owner_attestation_bytes__isnull=False,
                    )
                ),
                name="macro_factor_lifecycle_chain_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(recorded_at__gte=models.F("occurred_at")),
                name="macro_factor_lifecycle_recorded_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        event_type="recorded",
                        owner_attestation_issued_at__isnull=True,
                    )
                    | models.Q(
                        event_type="retired",
                        owner_attestation_issued_at__gte=models.F("occurred_at"),
                        owner_attestation_issued_at__lte=models.F("recorded_at"),
                    )
                ),
                name="macro_factor_lifecycle_attested_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="macro_factor_lifecycle_research_blocked_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["artifact", "occurred_at"],
                name="mf_lifecycle_time_idx",
            )
        ]

    def to_domain(self) -> MacroFactorLifecycleEvent:
        """Restore and verify one lifecycle chain link."""

        raw_reasons = self.reason_codes
        if not isinstance(raw_reasons, list) or not all(
            isinstance(item, str) for item in raw_reasons
        ):
            raise ValueError("lifecycle reason_codes must be a string array")
        event = MacroFactorLifecycleEvent(
            event_id=self.event_id,
            artifact_id=self.artifact_id,
            artifact_hash=self.artifact_hash,
            factor_version=self.factor_version,
            event_type=MacroFactorLifecycleEventType(self.event_type),
            sequence=self.sequence,
            occurred_at=self.occurred_at,
            recorded_at=self.recorded_at,
            policy_version=self.policy_version,
            policy_hash=self.policy_hash,
            reason_codes=tuple(cast(list[str], raw_reasons)),
            evidence_hash=self.evidence_hash,
            previous_event_hash=self.previous_event_hash,
            owner_attestation_id=self.owner_attestation_id,
            owner_attestation_hash=self.owner_attestation_hash,
            owner_attestation_owner_ref=self.owner_attestation_owner_ref,
            owner_attestation_media_type=self.owner_attestation_media_type,
            owner_attestation_content_length=self.owner_attestation_content_length,
            owner_attestation_issued_at=self.owner_attestation_issued_at,
            owner_attestation_bytes=(
                None
                if self.owner_attestation_bytes is None
                else bytes(self.owner_attestation_bytes)
            ),
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_execute=self.must_not_execute,
        )
        payload = _mapping(self.payload, "lifecycle event payload")
        if event.canonical_payload != payload or event.content_hash != self.content_hash:
            raise ValueError("lifecycle event payload/hash does not match columns")
        artifact = self.artifact.to_domain()
        _validate_event_artifact_binding(event, artifact, self.artifact.source_result)
        return event

    def clean(self) -> None:
        """Reject artifact or canonical lifecycle mismatches."""

        super().clean()
        try:
            event = self.to_domain()
        except (TypeError, ValueError) as exc:
            raise ValidationError("invalid macro-factor lifecycle event") from exc
        if self.artifact.content_hash != event.artifact_hash:
            raise ValidationError("lifecycle event artifact hash mismatch")


class MacroFactorLifecycleStreamCommitModel(MacroFactorAppendOnlyModel):
    """Immutable cumulative anchor paired one-to-one with a lifecycle event."""

    commit_id = models.CharField(max_length=64, primary_key=True)
    artifact = models.ForeignKey(
        MacroFactorRunArtifactModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_stream_commits",
    )
    event = models.OneToOneField(
        MacroFactorLifecycleEventModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_stream_commit",
    )
    artifact_hash = models.CharField(max_length=64)
    event_hash = models.CharField(max_length=64)
    sequence = models.PositiveIntegerField()
    event_count = models.PositiveIntegerField()
    head_event_hash = models.CharField(max_length=64)
    previous_commit_hash = models.CharField(max_length=64, null=True, blank=True)
    stream_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()
    research_only = models.BooleanField(default=True, editable=False)
    must_not_use_for_decision = models.BooleanField(default=True, editable=False)
    must_not_execute = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "macro_factor_lifecycle_stream_commit"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["artifact_id", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["artifact", "sequence"],
                name="mf_lifecycle_commit_seq_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(event_count=models.F("sequence")),
                name="mf_lifecycle_commit_count_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(head_event_hash=models.F("event_hash")),
                name="mf_lifecycle_commit_head_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(sequence=1, previous_commit_hash__isnull=True)
                    | models.Q(sequence__gt=1, previous_commit_hash__isnull=False)
                ),
                name="mf_lifecycle_commit_prev_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="mf_lifecycle_commit_blocked_ck",
            ),
        ]

    def to_domain(self) -> MacroFactorLifecycleStreamCommit:
        """Restore and verify one cumulative lifecycle stream commitment."""

        commit = MacroFactorLifecycleStreamCommit(
            commit_id=self.commit_id,
            artifact_id=self.artifact_id,
            artifact_hash=self.artifact_hash,
            event_id=self.event_id,
            event_hash=self.event_hash,
            sequence=self.sequence,
            event_count=self.event_count,
            head_event_hash=self.head_event_hash,
            previous_commit_hash=self.previous_commit_hash,
            stream_hash=self.stream_hash,
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_execute=self.must_not_execute,
        )
        payload = _mapping(self.payload, "lifecycle stream commit payload")
        if commit.canonical_payload != payload or commit.content_hash != self.content_hash:
            raise ValueError("lifecycle stream commit payload/hash does not match columns")
        artifact = self.artifact.to_domain()
        event = self.event.to_domain()
        if (
            commit.artifact_id != artifact.artifact_id
            or commit.artifact_hash != artifact.content_hash
            or commit.event_id != event.event_id
            or commit.event_hash != event.content_hash
            or commit.sequence != event.sequence
            or commit.head_event_hash != event.content_hash
        ):
            raise ValueError("lifecycle stream commit does not exactly bind artifact/event")
        return commit

    def clean(self) -> None:
        """Reject stream commitments that do not match their exact parent rows."""

        super().clean()
        try:
            self.to_domain()
        except (TypeError, ValueError) as exc:
            raise ValidationError("invalid macro-factor lifecycle stream commit") from exc


class MacroFactorLifecycleStreamHeadModel(LifecycleHeadGuardedModel):
    """Repository-owned latest head that cannot silently regress with an append tail."""

    artifact = models.OneToOneField(
        MacroFactorRunArtifactModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_stream_head",
        primary_key=True,
    )
    artifact_hash = models.CharField(max_length=64)
    latest_sequence = models.PositiveIntegerField()
    event_count = models.PositiveIntegerField()
    latest_event_hash = models.CharField(max_length=64)
    latest_commit_hash = models.CharField(max_length=64)
    stream_hash = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    payload = models.JSONField()
    research_only = models.BooleanField(default=True, editable=False)
    must_not_use_for_decision = models.BooleanField(default=True, editable=False)
    must_not_execute = models.BooleanField(default=True, editable=False)

    class Meta:
        db_table = "macro_factor_lifecycle_stream_head"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(event_count=models.F("latest_sequence")),
                name="mf_lifecycle_head_count_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="mf_lifecycle_head_blocked_ck",
            ),
        ]

    def to_domain(self) -> MacroFactorLifecycleStreamHead:
        """Restore and verify the independent latest-head seal."""

        head = MacroFactorLifecycleStreamHead(
            artifact_id=self.artifact_id,
            artifact_hash=self.artifact_hash,
            latest_sequence=self.latest_sequence,
            event_count=self.event_count,
            latest_event_hash=self.latest_event_hash,
            latest_commit_hash=self.latest_commit_hash,
            stream_hash=self.stream_hash,
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_execute=self.must_not_execute,
        )
        payload = _mapping(self.payload, "lifecycle stream head payload")
        if head.canonical_payload != payload or head.content_hash != self.content_hash:
            raise ValueError("lifecycle stream head payload/hash does not match columns")
        artifact = self.artifact.to_domain()
        if head.artifact_id != artifact.artifact_id or head.artifact_hash != artifact.content_hash:
            raise ValueError("lifecycle stream head does not exactly bind artifact")
        return head

    def clean(self) -> None:
        """Reject a latest head that is not exactly sealed to its artifact."""

        super().clean()
        try:
            self.to_domain()
        except (TypeError, ValueError) as exc:
            raise ValidationError("invalid macro-factor lifecycle stream head") from exc


@receiver(pre_delete, sender=MacroFactorLifecycleStreamHeadModel, weak=False)
def _reject_lifecycle_head_collector_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Collector and direct delete paths for the authoritative head."""

    raise ValidationError("Macro-factor lifecycle stream head cannot be deleted")


__all__ = [
    "MacroFactorDatedOutputModel",
    "MacroFactorLifecycleEventModel",
    "MacroFactorLifecycleStreamCommitModel",
    "MacroFactorLifecycleStreamHeadModel",
    "MacroFactorRunArtifactModel",
]
