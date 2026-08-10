"""Transactional append-only repository for the reproducible R3 run ledger."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction

from apps.macro_factor.domain._runner_support import decimal_text, hash_payload, utc_text
from apps.macro_factor.domain.dated_outputs import DatedMacroFactorOutput
from apps.macro_factor.domain.entities import ImmutableMacroFactorResearchRecord
from apps.macro_factor.domain.lifecycle import (
    MacroFactorLifecycleEvent,
    MacroFactorLifecycleEventType,
    create_root_lifecycle_event,
    validate_lifecycle_chain,
)
from apps.macro_factor.domain.lifecycle_stream import (
    MacroFactorLifecycleStreamCommit,
    MacroFactorLifecycleStreamHead,
    build_lifecycle_stream_commits,
    build_lifecycle_stream_head,
)
from apps.macro_factor.domain.run_artifacts import ReproducibleMacroFactorRunArtifact
from apps.macro_factor.domain.runner_service import ReproducibleMacroFactorRunBundle

from .lifecycle_head_guard import (
    _activate_lifecycle_head_uow,
    _claim_lifecycle_head_write,
)
from .models import MacroFactorResearchResultModel
from .repositories import MacroFactorResearchResultRepository
from .run_ledger_models import (
    MacroFactorDatedOutputModel,
    MacroFactorLifecycleEventModel,
    MacroFactorLifecycleStreamCommitModel,
    MacroFactorLifecycleStreamHeadModel,
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


def _stream_commit_model(
    commit: MacroFactorLifecycleStreamCommit,
    artifact: MacroFactorRunArtifactModel,
    event: MacroFactorLifecycleEventModel,
) -> MacroFactorLifecycleStreamCommitModel:
    return MacroFactorLifecycleStreamCommitModel(
        commit_id=commit.commit_id,
        artifact=artifact,
        event=event,
        artifact_hash=commit.artifact_hash,
        event_hash=commit.event_hash,
        sequence=commit.sequence,
        event_count=commit.event_count,
        head_event_hash=commit.head_event_hash,
        previous_commit_hash=commit.previous_commit_hash,
        stream_hash=commit.stream_hash,
        content_hash=commit.content_hash,
        payload=_payload(commit.canonical_json),
        research_only=commit.research_only,
        must_not_use_for_decision=commit.must_not_use_for_decision,
        must_not_execute=commit.must_not_execute,
    )


def _stream_head_values(head: MacroFactorLifecycleStreamHead) -> dict[str, object]:
    return {
        "artifact_id": head.artifact_id,
        "artifact_hash": head.artifact_hash,
        "latest_sequence": head.latest_sequence,
        "event_count": head.event_count,
        "latest_event_hash": head.latest_event_hash,
        "latest_commit_hash": head.latest_commit_hash,
        "stream_hash": head.stream_hash,
        "content_hash": head.content_hash,
        "payload": _payload(head.canonical_json),
        "research_only": head.research_only,
        "must_not_use_for_decision": head.must_not_use_for_decision,
        "must_not_execute": head.must_not_execute,
    }


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


class MacroFactorRunLedgerCorruption(ValueError):
    """Raised when persisted R3 run rows do not form one exact sealed bundle."""


@dataclass(frozen=True)
class _RestoredMacroFactorRunBundle:
    """Infrastructure projection used only after every persisted row is verified."""

    source_record: ImmutableMacroFactorResearchRecord
    artifact: ReproducibleMacroFactorRunArtifact
    outputs: tuple[DatedMacroFactorOutput, ...]
    lifecycle_events: tuple[MacroFactorLifecycleEvent, ...]
    lifecycle_stream_commits: tuple[MacroFactorLifecycleStreamCommit, ...]
    lifecycle_stream_head: MacroFactorLifecycleStreamHead


def _external_output_projection(output: DatedMacroFactorOutput) -> dict[str, object]:
    """Project one local output onto the exact external-artifact output schema."""

    return {
        "output_role": output.output_role.value,
        "observation_date": output.observation_date.isoformat(),
        "target_period_start": output.target_period_start.isoformat(),
        "target_period_end": output.target_period_end.isoformat(),
        "horizon_periods": output.horizon_periods,
        "horizon_unit": output.horizon_unit,
        "knowledge_as_of": utc_text(output.knowledge_as_of),
        "valid_until": utc_text(output.valid_until),
        "value": decimal_text(output.value),
        "unit": output.unit,
    }


def _output_sort_key(payload: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(payload["output_role"]),
        str(payload["observation_date"]),
        str(payload["target_period_start"]),
        str(payload["target_period_end"]),
    )


def _validate_restored_bundle(bundle: _RestoredMacroFactorRunBundle) -> None:
    """Validate completeness and cross-row identity before exposing any projection."""

    artifact = bundle.artifact
    source = bundle.source_record
    if (
        source.result_id != artifact.source_result_id
        or source.content_hash != artifact.source_result_hash
        or source.factor_version != artifact.factor_version
        or source.target_code != artifact.target_code
        or source.evidence_produced_at != artifact.produced_at
        or source.pit_manifest_id != artifact.pit_manifest_id
        or source.pit_manifest_hash != artifact.pit_manifest_hash
        or source.code_version != artifact.code_version
        or source.parameter_version != artifact.parameter_version
    ):
        raise ValueError("restored run source does not exactly match artifact")

    external_payload = _payload(artifact.external_artifact_bytes.decode("utf-8"))
    raw_external_outputs = external_payload.get("dated_outputs")
    if not isinstance(raw_external_outputs, list) or not raw_external_outputs:
        raise ValueError("sealed external artifact has no dated-output manifest")
    required_output_keys = {
        "output_role",
        "observation_date",
        "target_period_start",
        "target_period_end",
        "horizon_periods",
        "horizon_unit",
        "knowledge_as_of",
        "valid_until",
        "value",
        "unit",
    }
    external_outputs: list[dict[str, object]] = []
    for raw_output in raw_external_outputs:
        if not isinstance(raw_output, dict) or set(raw_output) != required_output_keys:
            raise ValueError("sealed external dated-output manifest is malformed")
        external_outputs.append(cast(dict[str, object], raw_output))
    actual_outputs = [_external_output_projection(output) for output in bundle.outputs]
    if sorted(actual_outputs, key=_output_sort_key) != sorted(
        external_outputs,
        key=_output_sort_key,
    ):
        raise ValueError("persisted dated outputs do not match sealed external manifest")

    if not bundle.lifecycle_events:
        raise ValueError("persisted lifecycle chain has no root")
    validate_lifecycle_chain(
        artifact.artifact_id,
        artifact.content_hash,
        bundle.lifecycle_events,
    )
    source_payload = _payload(source.payload_json)
    raw_policy = source_payload.get("retirement_policy")
    if not isinstance(raw_policy, dict):
        raise ValueError("source retirement policy is malformed")
    policy = cast(dict[str, object], raw_policy)
    root = bundle.lifecycle_events[0]
    if (
        root.event_id != f"record-{artifact.artifact_id}"
        or root.event_type is not MacroFactorLifecycleEventType.RECORDED
        or root.sequence != 1
        or root.occurred_at != artifact.produced_at
        or root.recorded_at != artifact.produced_at
        or root.policy_version != policy.get("policy_version")
        or root.policy_hash != hash_payload(policy)
        or root.reason_codes != ("run_recorded",)
        or root.evidence_hash != artifact.content_hash
        or root.previous_event_hash is not None
        or root.owner_attestation_id is not None
        or root.owner_attestation_hash is not None
        or root.owner_attestation_owner_ref is not None
        or root.owner_attestation_media_type is not None
        or root.owner_attestation_content_length is not None
        or root.owner_attestation_issued_at is not None
        or root.owner_attestation_bytes is not None
    ):
        raise ValueError("persisted lifecycle root does not match artifact and source")
    expected_commits = build_lifecycle_stream_commits(artifact, bundle.lifecycle_events)
    if bundle.lifecycle_stream_commits != expected_commits:
        raise ValueError("persisted lifecycle stream commits do not match the exact event stream")
    expected_head = build_lifecycle_stream_head(
        artifact,
        bundle.lifecycle_events,
        expected_commits,
    )
    if bundle.lifecycle_stream_head != expected_head:
        raise ValueError("persisted lifecycle stream head does not match exact latest prefix")


class DjangoMacroFactorRunLedgerReadRepository:
    """Exact read-only view of the immutable R3 run and lifecycle ledgers."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        if type(using) is not str or not using.strip():
            raise ValueError("macro-factor run ledger database alias is invalid")
        self._using = using

    def get_artifact(
        self,
        artifact_id: str,
    ) -> ReproducibleMacroFactorRunArtifact | None:
        """Return and integrity-check one immutable run artifact."""

        bundle = self._restore_bundle(artifact_id)
        return None if bundle is None else bundle.artifact

    def list_outputs(self, artifact_id: str) -> tuple[DatedMacroFactorOutput, ...]:
        """Return integrity-checked outputs in deterministic order."""

        bundle = self._restore_bundle(artifact_id)
        return () if bundle is None else bundle.outputs

    def list_lifecycle_events(
        self,
        artifact_id: str,
    ) -> tuple[MacroFactorLifecycleEvent, ...]:
        """Return and verify the ordered lifecycle hash chain."""

        bundle = self._restore_bundle(artifact_id)
        return () if bundle is None else bundle.lifecycle_events

    def _restore_bundle(self, artifact_id: str) -> _RestoredMacroFactorRunBundle | None:
        """Restore all related rows in one database unit and validate before projection."""

        try:
            with transaction.atomic(using=self._using):
                artifact_model = (
                    MacroFactorRunArtifactModel._default_manager.using(self._using)
                    .select_related("source_result")
                    .filter(artifact_id=artifact_id)
                    .first()
                )
                if artifact_model is None:
                    has_orphan = (
                        MacroFactorDatedOutputModel._default_manager.using(self._using)
                        .filter(artifact_id=artifact_id)
                        .exists()
                        or MacroFactorLifecycleEventModel._default_manager.using(self._using)
                        .filter(artifact_id=artifact_id)
                        .exists()
                        or MacroFactorLifecycleStreamCommitModel._default_manager.using(self._using)
                        .filter(artifact_id=artifact_id)
                        .exists()
                        or MacroFactorLifecycleStreamHeadModel._default_manager.using(self._using)
                        .filter(artifact_id=artifact_id)
                        .exists()
                    )
                    if has_orphan:
                        raise MacroFactorRunLedgerCorruption(
                            "macro-factor run artifact is missing while child rows remain"
                        )
                    return None
                artifact = artifact_model.to_domain()
                source_record = artifact_model.source_result.to_domain()
                output_models = (
                    MacroFactorDatedOutputModel._default_manager.using(self._using)
                    .select_related("artifact__source_result")
                    .filter(artifact_id=artifact_id)
                    .order_by("output_id")
                )
                outputs = tuple(item.to_domain() for item in output_models)
                event_models = (
                    MacroFactorLifecycleEventModel._default_manager.using(self._using)
                    .select_related("artifact__source_result")
                    .filter(artifact_id=artifact_id)
                    .order_by("sequence")
                )
                events = tuple(item.to_domain() for item in event_models)
                commit_models = (
                    MacroFactorLifecycleStreamCommitModel._default_manager.using(self._using)
                    .select_related("artifact__source_result")
                    .filter(artifact_id=artifact_id)
                    .order_by("sequence")
                )
                try:
                    commits = tuple(item.to_domain() for item in commit_models)
                except (
                    AttributeError,
                    LookupError,
                    ObjectDoesNotExist,
                    TypeError,
                    ValueError,
                ) as exc:
                    raise MacroFactorRunLedgerCorruption(
                        "lifecycle stream commit is orphaned or invalid"
                    ) from exc
                head_models = tuple(
                    MacroFactorLifecycleStreamHeadModel._default_manager.using(self._using)
                    .select_related("artifact__source_result")
                    .filter(artifact_id=artifact_id)
                )
                if len(head_models) != 1:
                    raise MacroFactorRunLedgerCorruption(
                        "lifecycle stream head is missing or duplicated"
                    )
                head = head_models[0].to_domain()
                bundle = _RestoredMacroFactorRunBundle(
                    source_record=source_record,
                    artifact=artifact,
                    outputs=outputs,
                    lifecycle_events=events,
                    lifecycle_stream_commits=commits,
                    lifecycle_stream_head=head,
                )
                _validate_restored_bundle(bundle)
                return bundle
        except MacroFactorRunLedgerCorruption:
            raise
        except (AttributeError, LookupError, ObjectDoesNotExist, TypeError, ValueError) as exc:
            raise MacroFactorRunLedgerCorruption(
                f"macro-factor run ledger corruption: {exc}"
            ) from exc


class DjangoMacroFactorRunLedgerRepository:
    """Store source result, run, outputs, and events in one atomic append."""

    __slots__ = ("_head_token",)

    def __init__(self) -> None:
        self._head_token = object()

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
                expected_commits = build_lifecycle_stream_commits(
                    bundle.artifact,
                    bundle.lifecycle_events,
                )
                for event, commit in zip(
                    bundle.lifecycle_events,
                    expected_commits,
                    strict=True,
                ):
                    event_model = _event_model(event, artifact)
                    event_model.full_clean()
                    event_model.save(force_insert=True)
                    commit_model = _stream_commit_model(commit, artifact, event_model)
                    commit_model.full_clean()
                    commit_model.save(force_insert=True)
                head = build_lifecycle_stream_head(
                    bundle.artifact,
                    bundle.lifecycle_events,
                    expected_commits,
                )
                self._write_stream_head(head, insert=True)
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
        restored_artifact = DjangoMacroFactorRunLedgerReadRepository().get_artifact(
            model.artifact_id
        )
        if restored_artifact != bundle.artifact:
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
        commit_hashes = tuple(
            MacroFactorLifecycleStreamCommitModel._default_manager.filter(artifact=model)
            .order_by("sequence")
            .values_list("content_hash", flat=True)
        )
        expected_commit_hashes = tuple(
            item.content_hash
            for item in build_lifecycle_stream_commits(
                bundle.artifact,
                bundle.lifecycle_events,
            )
        )
        if commit_hashes != expected_commit_hashes:
            raise ValueError("persisted lifecycle stream commits do not match replay")

    def _write_stream_head(
        self,
        head: MacroFactorLifecycleStreamHead,
        *,
        insert: bool,
    ) -> None:
        values = _stream_head_values(head)
        if insert:
            model = MacroFactorLifecycleStreamHeadModel(**values)
            update_fields: tuple[str, ...] | None = None
        else:
            model = MacroFactorLifecycleStreamHeadModel._default_manager.select_for_update().get(
                artifact_id=head.artifact_id
            )
            for field_name, value in values.items():
                setattr(model, field_name, value)
            update_fields = tuple(name for name in values if name != "artifact_id")
        model.full_clean()
        with _activate_lifecycle_head_uow(self._head_token):
            with _claim_lifecycle_head_write(
                token=self._head_token,
                model_type=MacroFactorLifecycleStreamHeadModel,
                operation="insert" if insert else "replace",
                expected_values=values,
            ):
                model.save(
                    force_insert=insert,
                    force_update=not insert,
                    update_fields=update_fields,
                )

    def get_artifact(
        self,
        artifact_id: str,
    ) -> ReproducibleMacroFactorRunArtifact | None:
        """Return one artifact projected from an exact validated ledger bundle."""

        return DjangoMacroFactorRunLedgerReadRepository().get_artifact(artifact_id)

    def list_outputs(self, artifact_id: str) -> tuple[DatedMacroFactorOutput, ...]:
        """Return outputs projected from an exact validated ledger bundle."""

        return DjangoMacroFactorRunLedgerReadRepository().list_outputs(artifact_id)

    def list_lifecycle_events(
        self,
        artifact_id: str,
    ) -> tuple[MacroFactorLifecycleEvent, ...]:
        """Return lifecycle projected from an exact validated ledger bundle."""

        return DjangoMacroFactorRunLedgerReadRepository().list_lifecycle_events(artifact_id)

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
            if event not in self.list_lifecycle_events(event.artifact_id):
                raise ValueError("lifecycle event is not part of the exact committed stream")
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
                    if event not in self.list_lifecycle_events(event.artifact_id):
                        raise ValueError(
                            "lifecycle event is not part of the exact committed stream"
                        )
                    return event
                current_events = self.list_lifecycle_events(artifact.artifact_id)
                if not current_events or event.sequence != current_events[-1].sequence + 1:
                    raise ValueError("lifecycle event does not extend the current chain")
                if event.previous_event_hash != current_events[-1].content_hash:
                    raise ValueError("lifecycle previous-event hash mismatch")
                complete_events = (*current_events, event)
                validate_lifecycle_chain(
                    artifact.artifact_id,
                    artifact.content_hash,
                    complete_events,
                )
                model = _event_model(event, artifact)
                model.full_clean()
                model.save(force_insert=True)
                artifact_domain = artifact.to_domain()
                complete_commits = build_lifecycle_stream_commits(
                    artifact_domain,
                    complete_events,
                )
                commit = complete_commits[-1]
                commit_model = _stream_commit_model(commit, artifact, model)
                commit_model.full_clean()
                commit_model.save(force_insert=True)
                head = build_lifecycle_stream_head(
                    artifact_domain,
                    complete_events,
                    complete_commits,
                )
                self._write_stream_head(head, insert=False)
        except MacroFactorRunArtifactModel.DoesNotExist as exc:
            raise ValueError("run artifact does not exist") from exc
        except (IntegrityError, ValidationError, ValueError) as exc:
            winner = MacroFactorLifecycleEventModel._default_manager.filter(
                event_id=event.event_id
            ).first()
            if (
                winner is None
                or winner.to_domain() != event
                or event not in self.list_lifecycle_events(event.artifact_id)
            ):
                raise ValueError("invalid macro-factor lifecycle event") from exc
        return event


__all__ = [
    "DjangoMacroFactorRunLedgerReadRepository",
    "DjangoMacroFactorRunLedgerRepository",
    "MacroFactorRunLedgerCorruption",
]
