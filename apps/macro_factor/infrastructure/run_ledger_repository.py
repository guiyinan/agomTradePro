"""Transactional append-only repository for the reproducible R3 run ledger."""

from __future__ import annotations

import json
from typing import cast

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.macro_factor.domain.dated_outputs import DatedMacroFactorOutput
from apps.macro_factor.domain.lifecycle import (
    MacroFactorLifecycleEvent,
    create_root_lifecycle_event,
    validate_lifecycle_chain,
)
from apps.macro_factor.domain.run_artifacts import ReproducibleMacroFactorRunArtifact
from apps.macro_factor.domain.runner_service import ReproducibleMacroFactorRunBundle

from .models import MacroFactorResearchResultModel
from .repositories import MacroFactorResearchResultRepository
from .run_ledger_models import (
    MacroFactorDatedOutputModel,
    MacroFactorLifecycleEventModel,
    MacroFactorRunArtifactModel,
)


def _payload(canonical_json: str) -> dict[str, object]:
    decoded = json.loads(canonical_json)
    if not isinstance(decoded, dict):
        raise ValueError("canonical evidence payload must be an object")
    return cast(dict[str, object], decoded)


def _artifact_model(
    artifact: ReproducibleMacroFactorRunArtifact,
    source: MacroFactorResearchResultModel,
) -> MacroFactorRunArtifactModel:
    return MacroFactorRunArtifactModel(
        artifact_id=artifact.artifact_id,
        run_key=artifact.run_key,
        run_version=artifact.run_version,
        factor_version=artifact.factor_version,
        target_code=artifact.target_code,
        output_role=artifact.output_role.value,
        produced_at=artifact.produced_at,
        source_result=source,
        source_result_hash=artifact.source_result_hash,
        external_evidence_id=artifact.external_evidence_id,
        external_producer_ref=artifact.external_producer_ref,
        external_artifact_hash=artifact.external_artifact_hash,
        external_artifact_media_type=artifact.external_artifact_media_type,
        external_artifact_content_length=artifact.external_artifact_content_length,
        external_artifact_bytes=artifact.external_artifact_bytes,
        request_hash=artifact.request_hash,
        pit_manifest_id=artifact.pit_manifest_id,
        pit_manifest_hash=artifact.pit_manifest_hash,
        dataset_hash=artifact.dataset_hash,
        benchmark_version=artifact.benchmark_version,
        benchmark_hash=artifact.benchmark_hash,
        fixed_fmp_version=artifact.fixed_fmp_version,
        fixed_fmp_hash=artifact.fixed_fmp_hash,
        cost_model_version=artifact.cost_model_version,
        cost_model_hash=artifact.cost_model_hash,
        split_contract_version=artifact.split_contract_version,
        split_contract_hash=artifact.split_contract_hash,
        plan_hash=artifact.plan_hash,
        selection_protocol_version=artifact.selection_protocol_version,
        selection_protocol_hash=artifact.selection_protocol_hash,
        metrics_protocol_version=artifact.metrics_protocol_version,
        metrics_protocol_hash=artifact.metrics_protocol_hash,
        timing_policy_version=artifact.timing_policy_version,
        timing_policy_hash=artifact.timing_policy_hash,
        code_version=artifact.code_version,
        dependency_lock_hash=artifact.dependency_lock_hash,
        parameter_version=artifact.parameter_version,
        parameter_hash=artifact.parameter_hash,
        random_seed=artifact.random_seed,
        content_hash=artifact.content_hash,
        payload=_payload(artifact.canonical_json),
        research_only=artifact.research_only,
        must_not_use_for_decision=artifact.must_not_use_for_decision,
        must_not_execute=artifact.must_not_execute,
    )


def _output_model(
    output: DatedMacroFactorOutput,
    artifact: MacroFactorRunArtifactModel,
) -> MacroFactorDatedOutputModel:
    return MacroFactorDatedOutputModel(
        output_id=output.output_id,
        artifact=artifact,
        artifact_hash=output.artifact_hash,
        factor_version=output.factor_version,
        target_code=output.target_code,
        output_role=output.output_role.value,
        observation_date=output.observation_date,
        target_period_start=output.target_period_start,
        target_period_end=output.target_period_end,
        horizon_periods=output.horizon_periods,
        horizon_unit=output.horizon_unit,
        knowledge_as_of=output.knowledge_as_of,
        produced_at=output.produced_at,
        valid_until=output.valid_until,
        value=output.value,
        unit=output.unit,
        pit_manifest_id=output.pit_manifest_id,
        pit_manifest_hash=output.pit_manifest_hash,
        content_hash=output.content_hash,
        payload=_payload(output.canonical_json),
        research_only=output.research_only,
        must_not_use_for_decision=output.must_not_use_for_decision,
        must_not_execute=output.must_not_execute,
    )


def _event_model(
    event: MacroFactorLifecycleEvent,
    artifact: MacroFactorRunArtifactModel,
) -> MacroFactorLifecycleEventModel:
    return MacroFactorLifecycleEventModel(
        event_id=event.event_id,
        artifact=artifact,
        artifact_hash=event.artifact_hash,
        factor_version=event.factor_version,
        event_type=event.event_type.value,
        sequence=event.sequence,
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
        policy_version=event.policy_version,
        policy_hash=event.policy_hash,
        reason_codes=list(event.reason_codes),
        evidence_hash=event.evidence_hash,
        previous_event_hash=event.previous_event_hash,
        owner_attestation_id=event.owner_attestation_id,
        owner_attestation_hash=event.owner_attestation_hash,
        owner_attestation_owner_ref=event.owner_attestation_owner_ref,
        owner_attestation_media_type=event.owner_attestation_media_type,
        owner_attestation_content_length=event.owner_attestation_content_length,
        owner_attestation_issued_at=event.owner_attestation_issued_at,
        owner_attestation_bytes=event.owner_attestation_bytes,
        content_hash=event.content_hash,
        payload=_payload(event.canonical_json),
        research_only=event.research_only,
        must_not_use_for_decision=event.must_not_use_for_decision,
        must_not_execute=event.must_not_execute,
    )


def _validate_bundle(bundle: ReproducibleMacroFactorRunBundle) -> None:
    artifact = bundle.artifact
    source = bundle.source_result
    if (
        source.result_id != artifact.source_result_id
        or source.content_hash != artifact.source_result_hash
        or source.factor_version != artifact.factor_version
        or source.target.target_code != artifact.target_code
        or source.target.output_role is not artifact.output_role
        or source.weights.calculated_at != artifact.produced_at
        or source.pit_manifest_id != artifact.pit_manifest_id
        or source.pit_manifest_hash != artifact.pit_manifest_hash
        or source.reproducibility.code_version != artifact.code_version
        or source.reproducibility.dependency_lock_hash != artifact.dependency_lock_hash
        or source.reproducibility.parameter_version != artifact.parameter_version
        or source.reproducibility.parameter_hash != artifact.parameter_hash
    ):
        raise ValueError("run bundle source result does not match artifact")
    if not bundle.outputs:
        raise ValueError("run bundle must include at least one dated output")
    if len(bundle.lifecycle_events) != 1 or bundle.lifecycle_events[0].sequence != 1:
        raise ValueError("new run bundle requires exactly one lifecycle root")
    for output in bundle.outputs:
        if (
            output.artifact_id != artifact.artifact_id
            or output.artifact_hash != artifact.content_hash
            or output.factor_version != artifact.factor_version
            or output.target_code != artifact.target_code
            or output.output_role is not artifact.output_role
            or output.produced_at != artifact.produced_at
            or output.pit_manifest_id != artifact.pit_manifest_id
            or output.pit_manifest_hash != artifact.pit_manifest_hash
            or output.horizon_periods != source.target.horizon_periods
            or output.horizon_unit != source.target.horizon_unit
            or output.unit != source.target.unit
        ):
            raise ValueError("run bundle output does not match artifact")
    root = bundle.lifecycle_events[0]
    validate_lifecycle_chain(artifact.artifact_id, artifact.content_hash, (root,))
    if root != create_root_lifecycle_event(artifact, source):
        raise ValueError("run bundle lifecycle root does not match artifact and source")


class DjangoMacroFactorRunLedgerRepository:
    """Store source result, run, outputs, and events in one atomic append."""

    def append_bundle(
        self,
        bundle: ReproducibleMacroFactorRunBundle,
    ) -> ReproducibleMacroFactorRunBundle:
        """Append once, returning exact idempotent replays after verification."""

        _validate_bundle(bundle)
        existing = MacroFactorRunArtifactModel._default_manager.filter(
            run_key=bundle.artifact.run_key,
            run_version=bundle.artifact.run_version,
        ).first()
        if existing is not None:
            self._verify_exact_bundle(existing, bundle)
            return bundle
        try:
            with transaction.atomic():
                concurrent_winner = (
                    MacroFactorRunArtifactModel._default_manager.select_for_update()
                    .filter(
                        run_key=bundle.artifact.run_key,
                        run_version=bundle.artifact.run_version,
                    )
                    .first()
                )
                if concurrent_winner is not None:
                    self._verify_exact_bundle(concurrent_winner, bundle)
                    return bundle
                source = MacroFactorResearchResultModel._default_manager.filter(
                    result_id=bundle.source_result.result_id
                ).first()
                if source is None:
                    MacroFactorResearchResultRepository().add(bundle.source_result.to_record())
                    source = MacroFactorResearchResultModel._default_manager.get(
                        result_id=bundle.source_result.result_id
                    )
                elif source.content_hash != bundle.source_result.content_hash:
                    raise ValueError("source result identity conflicts with persisted evidence")
                artifact = _artifact_model(bundle.artifact, source)
                artifact.full_clean()
                artifact.save(force_insert=True)
                for output in bundle.outputs:
                    output_model = _output_model(output, artifact)
                    output_model.full_clean()
                    output_model.save(force_insert=True)
                for event in bundle.lifecycle_events:
                    event_model = _event_model(event, artifact)
                    event_model.full_clean()
                    event_model.save(force_insert=True)
        except (IntegrityError, ValidationError, ValueError) as exc:
            winner = MacroFactorRunArtifactModel._default_manager.filter(
                run_key=bundle.artifact.run_key,
                run_version=bundle.artifact.run_version,
            ).first()
            if winner is None:
                raise ValueError("invalid macro-factor run bundle") from exc
            self._verify_exact_bundle(winner, bundle)
        return bundle

    def _verify_exact_bundle(
        self,
        model: MacroFactorRunArtifactModel,
        bundle: ReproducibleMacroFactorRunBundle,
    ) -> None:
        if model.to_domain() != bundle.artifact:
            raise ValueError("run key/version conflicts with different artifact evidence")
        output_hashes = dict(
            MacroFactorDatedOutputModel._default_manager.filter(artifact=model).values_list(
                "output_id", "content_hash"
            )
        )
        expected_outputs = {item.output_id: item.content_hash for item in bundle.outputs}
        if output_hashes != expected_outputs:
            raise ValueError("persisted dated outputs do not match idempotent replay")
        event_hashes = tuple(
            MacroFactorLifecycleEventModel._default_manager.filter(artifact=model)
            .order_by("sequence")
            .values_list("content_hash", flat=True)
        )
        expected_events = tuple(item.content_hash for item in bundle.lifecycle_events)
        if event_hashes != expected_events:
            raise ValueError("persisted lifecycle root does not match idempotent replay")

    def get_artifact(
        self,
        artifact_id: str,
    ) -> ReproducibleMacroFactorRunArtifact | None:
        """Return and integrity-check one immutable run artifact."""

        model = (
            MacroFactorRunArtifactModel._default_manager.select_related("source_result")
            .filter(artifact_id=artifact_id)
            .first()
        )
        return None if model is None else model.to_domain()

    def list_outputs(self, artifact_id: str) -> tuple[DatedMacroFactorOutput, ...]:
        """Return integrity-checked outputs in deterministic order."""

        models = MacroFactorDatedOutputModel._default_manager.select_related("artifact").filter(
            artifact_id=artifact_id
        )
        return tuple(item.to_domain() for item in models.order_by("output_id"))

    def list_lifecycle_events(
        self,
        artifact_id: str,
    ) -> tuple[MacroFactorLifecycleEvent, ...]:
        """Return and verify the ordered lifecycle hash chain."""

        models = MacroFactorLifecycleEventModel._default_manager.select_related("artifact").filter(
            artifact_id=artifact_id
        )
        events = tuple(item.to_domain() for item in models.order_by("sequence"))
        artifact = self.get_artifact(artifact_id)
        if artifact is not None:
            validate_lifecycle_chain(artifact.artifact_id, artifact.content_hash, events)
        return events

    def append_lifecycle_event(
        self,
        event: MacroFactorLifecycleEvent,
    ) -> MacroFactorLifecycleEvent:
        """Append one exact chain link with race-safe idempotency."""

        existing = MacroFactorLifecycleEventModel._default_manager.filter(
            event_id=event.event_id
        ).first()
        if existing is not None:
            if existing.to_domain() != event:
                raise ValueError("lifecycle event identity conflicts with different evidence")
            return event
        try:
            with transaction.atomic():
                artifact = MacroFactorRunArtifactModel._default_manager.select_for_update().get(
                    artifact_id=event.artifact_id
                )
                concurrent_winner = MacroFactorLifecycleEventModel._default_manager.filter(
                    event_id=event.event_id
                ).first()
                if concurrent_winner is not None:
                    if concurrent_winner.to_domain() != event:
                        raise ValueError(
                            "lifecycle event identity conflicts with different evidence"
                        )
                    return event
                latest = (
                    MacroFactorLifecycleEventModel._default_manager.filter(artifact=artifact)
                    .order_by("-sequence")
                    .first()
                )
                if latest is None or event.sequence != latest.sequence + 1:
                    raise ValueError("lifecycle event does not extend the current chain")
                if event.previous_event_hash != latest.content_hash:
                    raise ValueError("lifecycle previous-event hash mismatch")
                validate_lifecycle_chain(
                    artifact.artifact_id,
                    artifact.content_hash,
                    (*self.list_lifecycle_events(artifact.artifact_id), event),
                )
                model = _event_model(event, artifact)
                model.full_clean()
                model.save(force_insert=True)
        except MacroFactorRunArtifactModel.DoesNotExist as exc:
            raise ValueError("run artifact does not exist") from exc
        except (IntegrityError, ValidationError, ValueError) as exc:
            winner = MacroFactorLifecycleEventModel._default_manager.filter(
                event_id=event.event_id
            ).first()
            if winner is None or winner.to_domain() != event:
                raise ValueError("invalid macro-factor lifecycle event") from exc
        return event


__all__ = ["DjangoMacroFactorRunLedgerRepository"]
