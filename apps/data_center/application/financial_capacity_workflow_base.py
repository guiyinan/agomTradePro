"""Shared checkpoint and budget coordination for financial publication workflows."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from apps.data_center.application.financial_capacity_contracts import (
    _SHA256,
    _SLICE_REQUESTS,
    FinancialCapacityAuthorityValidator,
    FinancialCapacityBinding,
    FinancialCapacityBindingSource,
    FinancialCapacityCheckpoint,
    FinancialCapacityCheckpointRepository,
    FinancialCapacityManifestSource,
    FinancialCapacityPublicationIndeterminateError,
    FinancialCapacityPublisher,
    FinancialCapacityReceipt,
    FinancialCapacityRehearsalCeilingSource,
    FinancialCapacitySliceAttempt,
    FinancialCapacitySliceRunner,
    FinancialCapacityWorkflowError,
    FinancialCapacityWorkflowResult,
    FinancialProductionCeilingSource,
    FinancialPublicationSlice,
    FinancialQualificationCeilingSource,
    FinancialScopeCapacityImportAuthoritySource,
    FinancialWorkflowStage,
    FinancialWorkflowStatus,
    GovernedFinancialCapacityRehearsalCeiling,
    GovernedFinancialProductionCeiling,
    GovernedFinancialQualificationCeiling,
    ProtocolClock,
    _append_evidence_sha256,
    _capacity_rehearsal_ceiling_matches,
    _ceiling_matches,
    _empty_evidence_sha256,
    _evidence_manifest_sha256,
    _freeze_manifest,
    _manifest_sha256,
    _qualification_ceiling_matches,
    _require_token,
    _stable_error_code,
    _valid_attempt,
)
from core.exceptions import DataFetchError, DataValidationError, InvalidInputError

_SLICE_CLAIM_LEASE = timedelta(seconds=3660)


class FinancialCapacityWorkflowBase:
    """Implement shared durable state transitions for isolated and production stages."""

    def __init__(
        self,
        *,
        checkpoint_repository: FinancialCapacityCheckpointRepository,
        binding_source: FinancialCapacityBindingSource,
        manifest_source: FinancialCapacityManifestSource,
        slice_runner: FinancialCapacitySliceRunner,
        publisher: FinancialCapacityPublisher,
        qualification_ceiling_source: FinancialQualificationCeilingSource,
        production_ceiling_source: FinancialProductionCeilingSource,
        authority_validator: FinancialCapacityAuthorityValidator | None,
        clock: ProtocolClock,
        capacity_rehearsal_ceiling_source: FinancialCapacityRehearsalCeilingSource | None = None,
        scope_capacity_import_authority_source: (
            FinancialScopeCapacityImportAuthoritySource | None
        ) = None,
    ) -> None:
        """Inject durable state and exact provider, scope, sync, and activation ports."""

        self._checkpoints = checkpoint_repository
        self._binding_source = binding_source
        self._manifest_source = manifest_source
        self._slice_runner = slice_runner
        self._publisher = publisher
        self._qualification_ceiling_source = qualification_ceiling_source
        self._production_ceiling_source = production_ceiling_source
        self._capacity_rehearsal_ceiling_source = capacity_rehearsal_ceiling_source
        self._scope_capacity_import_authority_source = scope_capacity_import_authority_source
        self._authority_validator = authority_validator
        self._clock = clock

    def get_checkpoint(self, workflow_id: str) -> FinancialCapacityCheckpoint | None:
        """Return one existing checkpoint for receipt handoff between workflow stages."""

        _require_token(workflow_id, "workflow_id")
        return self._checkpoints.get(workflow_id)

    def _run_slices(
        self,
        checkpoint: FinancialCapacityCheckpoint,
        *,
        max_slices: int | None,
        formal: bool,
    ) -> FinancialCapacityWorkflowResult:
        if max_slices is not None and (type(max_slices) is not int or max_slices <= 0):
            raise FinancialCapacityWorkflowError("financial capacity invocation size is invalid")
        if checkpoint.in_flight_slice_index is not None:
            if formal:
                authority_reason = self._resume_block_reason(checkpoint, formal=True)
                if authority_reason is not None:
                    return self._result(checkpoint, blocked_reason=authority_reason)
                if not self._formal_authority_is_current():
                    return self._result(
                        checkpoint,
                        blocked_reason="financial_capacity_authority_not_current",
                    )
            return self._handle_existing_claim(checkpoint)
        if (
            checkpoint.in_flight_claim_token is not None
            or checkpoint.in_flight_claim_expires_at is not None
        ):
            return self._finish(
                checkpoint,
                status="blocked",
                reason="financial_capacity_inflight_claim_invalid",
            )
        if checkpoint.run_id is None:
            return self._finish(
                checkpoint,
                status="blocked",
                reason="financial_capacity_workflow_run_identity_missing",
            )
        if checkpoint.next_slice_index >= checkpoint.manifest_count:
            drift = self._validate_source_snapshot(checkpoint, formal=formal)
            if drift is not None:
                return self._finish(checkpoint, status="blocked", reason=drift)
        processed = 0
        while checkpoint.next_slice_index < checkpoint.manifest_count:
            if max_slices is not None and processed >= max_slices:
                return self._result(checkpoint)
            drift = self._resume_block_reason(checkpoint, formal=formal)
            if drift is not None:
                return self._finish(checkpoint, status="blocked", reason=drift)
            if checkpoint.reserved_provider_requests + _SLICE_REQUESTS > (
                checkpoint.total_provider_request_budget
            ):
                return self._finish(
                    checkpoint,
                    status="blocked",
                    reason="financial_capacity_total_request_budget_exceeded",
                )
            if formal and not self._formal_authority_is_current():
                return self._finish(
                    checkpoint,
                    status="blocked",
                    reason="financial_capacity_authority_not_current",
                )
            item_index = checkpoint.next_slice_index
            try:
                item = self._checkpoints.manifest_item(checkpoint.workflow_id, item_index)
            except (IndexError, KeyError, OSError, RuntimeError, TypeError, ValueError):
                return self._finish(
                    checkpoint,
                    status="blocked",
                    reason="financial_capacity_manifest_snapshot_invalid",
                )
            claimed = replace(
                checkpoint,
                reserved_provider_requests=(
                    checkpoint.reserved_provider_requests + _SLICE_REQUESTS
                ),
                in_flight_slice_index=item_index,
                in_flight_claim_token=str(uuid4()),
                in_flight_claim_expires_at=self._clock() + _SLICE_CLAIM_LEASE,
            )
            try:
                checkpoint = self._save(claimed, expected_revision=checkpoint.revision)
            except FinancialCapacityWorkflowError:
                latest = self._checkpoints.get(checkpoint.workflow_id)
                if latest is not None and latest.revision != checkpoint.revision:
                    if latest.in_flight_slice_index is not None:
                        return self._handle_existing_claim(latest)
                    return self._result(latest)
                raise
            try:
                attempt = self._slice_runner.execute(
                    binding=checkpoint.binding,
                    item=item,
                    run_id=UUID(checkpoint.run_id),
                )
            except (
                DataFetchError,
                DataValidationError,
                InvalidInputError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                return self._record_failure(
                    checkpoint,
                    error_code=_stable_error_code(exc),
                    formal=formal,
                )
            result = attempt.result
            if attempt.observed_provider_requests is None:
                return self._record_failure(
                    checkpoint,
                    error_code="financial_capacity_actual_request_count_unknown",
                    formal=formal,
                    attempt=attempt,
                )
            if not _valid_attempt(checkpoint, item_index, attempt, item):
                return self._record_failure(
                    checkpoint,
                    error_code=(attempt.error_code or "financial_capacity_slice_evidence_invalid"),
                    formal=formal,
                    attempt=attempt,
                )
            if result.outcome != "success" or attempt.evidence is None:
                return self._record_failure(
                    checkpoint,
                    error_code=(
                        attempt.error_code
                        or result.failure_reason
                        or "financial_capacity_slice_failed"
                    ),
                    formal=formal,
                    attempt=attempt,
                )
            evidence = attempt.evidence
            if evidence is None:
                return self._record_failure(
                    checkpoint,
                    error_code=(attempt.error_code or "financial_capacity_slice_evidence_invalid"),
                    formal=formal,
                    attempt=attempt,
                )
            checkpoint = self._save(
                replace(
                    checkpoint,
                    next_slice_index=item_index + 1,
                    in_flight_slice_index=None,
                    in_flight_claim_token=None,
                    in_flight_claim_expires_at=None,
                    requested=checkpoint.requested + result.requested,
                    succeeded=checkpoint.succeeded + result.succeeded,
                    failed=checkpoint.failed + result.failed,
                    stored=checkpoint.stored + result.stored,
                    evidence_count=checkpoint.evidence_count + 1,
                    evidence_previous_sha256=checkpoint.evidence_sha256,
                    evidence_sha256=_append_evidence_sha256(
                        checkpoint.evidence_sha256,
                        index=item_index,
                        evidence=evidence,
                    ),
                    raw_body_count=(
                        checkpoint.raw_body_count
                        + evidence.financial_raw_audit_count
                        + evidence.source_time_raw_audit_count
                    ),
                    raw_audit_count=(
                        checkpoint.raw_audit_count
                        + evidence.financial_raw_audit_count
                        + evidence.source_time_raw_audit_count
                    ),
                    typed_evidence_count=(
                        checkpoint.typed_evidence_count + evidence.typed_financial_evidence_count
                    ),
                    atomic_fact_write_count=(
                        checkpoint.atomic_fact_write_count + evidence.atomic_fact_write_count
                    ),
                    observed_provider_requests=(
                        checkpoint.observed_provider_requests
                        + (
                            attempt.observed_provider_requests
                            if type(attempt.observed_provider_requests) is int
                            else 0
                        )
                    ),
                    evidence_append=evidence,
                ),
                expected_revision=checkpoint.revision,
            )
            processed += 1

        if checkpoint.next_slice_index != checkpoint.manifest_count:
            return self._result(checkpoint)
        drift = self._validate_source_snapshot(checkpoint, formal=formal)
        if drift is not None:
            return self._finish(checkpoint, status="blocked", reason=drift)
        if not formal:
            receipt = self._build_receipt(checkpoint, outcome="success")
            checkpoint = self._save(
                replace(
                    checkpoint,
                    status="success",
                    finished_at=self._clock(),
                    capacity_receipt=receipt,
                ),
                expected_revision=checkpoint.revision,
            )
            return self._result(checkpoint)

        # Persist pointer intent before staging so an interrupted staging call can recover
        # by the fixed workflow run ID without rebuilding mutable live facts.
        drift = self._resume_block_reason(checkpoint, formal=True)
        if drift is not None:
            return self._finish(checkpoint, status="blocked", reason=drift)
        if not self._formal_authority_is_current():
            return self._finish(
                checkpoint,
                status="blocked",
                reason="financial_capacity_authority_not_current",
            )
        if checkpoint.activation_intent is None:
            try:
                intent = self._publisher.begin_activation(
                    binding=checkpoint.binding,
                    run_id=UUID(checkpoint.run_id),
                    evidence=self._checkpoints.stream_evidence(checkpoint.workflow_id),
                )
            except (
                DataFetchError,
                DataValidationError,
                InvalidInputError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                return self._finish(
                    checkpoint,
                    status="failed",
                    reason=_stable_error_code(exc),
                )
            if intent.run_id != UUID(checkpoint.run_id):
                return self._finish(
                    checkpoint,
                    status="failed",
                    reason="financial_capacity_activation_intent_invalid",
                )
            checkpoint = self._save(
                replace(checkpoint, activation_intent=intent),
                expected_revision=checkpoint.revision,
            )

        if checkpoint.activation_intent is None:
            return self._finish(
                checkpoint,
                status="failed",
                reason="financial_capacity_activation_intent_missing",
            )
        if checkpoint.publication_plan is None:
            drift = self._resume_block_reason(checkpoint, formal=True)
            if drift is not None:
                return self._finish(checkpoint, status="blocked", reason=drift)
            if not self._formal_authority_is_current():
                return self._finish(
                    checkpoint,
                    status="blocked",
                    reason="financial_capacity_authority_not_current",
                )
            try:
                plan = self._publisher.stage(
                    binding=checkpoint.binding,
                    intent=checkpoint.activation_intent,
                    asset_codes=tuple(
                        sorted(
                            {
                                item.asset_code
                                for item in self._checkpoints.stream_manifest(
                                    checkpoint.workflow_id
                                )
                            }
                        )
                    ),
                    manifest_sha256=checkpoint.manifest_sha256,
                )
            except FinancialCapacityPublicationIndeterminateError as exc:
                return self._result(
                    checkpoint,
                    blocked_reason=_stable_error_code(exc),
                )
            except (OSError, RuntimeError):
                return self._result(
                    checkpoint,
                    blocked_reason="financial_capacity_publication_staging_outcome_indeterminate",
                )
            except (
                DataFetchError,
                DataValidationError,
                InvalidInputError,
                TypeError,
                ValueError,
            ) as exc:
                return self._finish(
                    checkpoint,
                    status="failed",
                    reason=_stable_error_code(exc),
                )
            if (
                plan.intent != checkpoint.activation_intent
                or plan.manifest_sha256 != checkpoint.manifest_sha256
            ):
                return self._finish(
                    checkpoint,
                    status="failed",
                    reason="financial_capacity_publication_plan_invalid",
                )
            # Keep this save outside the stage exception handler. If it fails after the
            # candidate bundle committed, a retry recovers that bundle by run_id.
            checkpoint = self._save(
                replace(checkpoint, publication_plan=plan, blocked_reason=None),
                expected_revision=checkpoint.revision,
            )

        if checkpoint.publication_plan is None:
            return self._finish(
                checkpoint,
                status="failed",
                reason="financial_capacity_publication_plan_missing",
            )
        # Revalidate exact scope, identity, approval, and authority immediately before
        # the only operation that can switch the production current pointer.
        drift = self._resume_block_reason(checkpoint, formal=True)
        if drift is not None:
            return self._finish(checkpoint, status="blocked", reason=drift)
        if not self._formal_authority_is_current():
            return self._finish(
                checkpoint,
                status="blocked",
                reason="financial_capacity_authority_not_current",
            )
        try:
            publication_hash = self._publisher.activate(
                binding=checkpoint.binding,
                plan=checkpoint.publication_plan,
            )
        except FinancialCapacityPublicationIndeterminateError as exc:
            return self._result(
                checkpoint,
                blocked_reason=_stable_error_code(exc),
            )
        except (OSError, RuntimeError):
            return self._result(
                checkpoint,
                blocked_reason="financial_capacity_publication_activation_outcome_indeterminate",
            )
        except (
            DataFetchError,
            DataValidationError,
            InvalidInputError,
            TypeError,
            ValueError,
        ) as exc:
            return self._finish(
                checkpoint,
                status="failed",
                reason=_stable_error_code(exc),
            )
        if not isinstance(publication_hash, str) or _SHA256.fullmatch(publication_hash) is None:
            return self._finish(
                checkpoint,
                status="failed",
                reason="financial_capacity_publication_hash_invalid",
            )
        checkpoint = self._save(
            replace(
                checkpoint,
                status="success",
                finished_at=self._clock(),
                publication_hash=publication_hash,
                blocked_reason=None,
            ),
            expected_revision=checkpoint.revision,
        )
        return self._result(checkpoint)

    def _record_failure(
        self,
        checkpoint: FinancialCapacityCheckpoint,
        *,
        error_code: str,
        formal: bool,
        attempt: FinancialCapacitySliceAttempt | None = None,
    ) -> FinancialCapacityWorkflowResult:
        result = attempt.result if attempt is not None else None
        invalid_success_claim = error_code == "financial_capacity_slice_evidence_invalid"
        checkpoint = replace(
            checkpoint,
            status=(
                "partial"
                if checkpoint.succeeded
                or (result is not None and result.succeeded and not invalid_success_claim)
                else "failed"
            ),
            in_flight_slice_index=None,
            in_flight_claim_token=None,
            in_flight_claim_expires_at=None,
            requested=checkpoint.requested + (result.requested if result is not None else 1),
            succeeded=checkpoint.succeeded
            + (0 if invalid_success_claim else (result.succeeded if result is not None else 0)),
            failed=checkpoint.failed
            + (1 if invalid_success_claim else (result.failed if result is not None else 1)),
            stored=checkpoint.stored + (result.stored if result is not None else 0),
            atomic_fact_write_count=(
                checkpoint.atomic_fact_write_count
                + (result.atomic_fact_write_count if result is not None else 0)
            ),
            observed_provider_requests=(
                checkpoint.observed_provider_requests
                + (
                    attempt.observed_provider_requests
                    if attempt is not None and type(attempt.observed_provider_requests) is int
                    else 0
                )
            ),
            error_codes=checkpoint.error_codes + (error_code,),
            finished_at=self._clock(),
            blocked_reason=error_code,
        )
        actual_request_budget_exceeded = (
            checkpoint.observed_provider_requests > checkpoint.total_provider_request_budget
        )
        receipt = (
            None
            if formal
            or error_code == "financial_capacity_actual_request_count_unknown"
            or error_code == "financial_capacity_post_write_evidence_invalid"
            or actual_request_budget_exceeded
            else self._build_receipt(checkpoint, outcome=checkpoint.status)
        )
        checkpoint = self._save(
            replace(checkpoint, capacity_receipt=receipt),
            expected_revision=checkpoint.revision,
        )
        return self._result(checkpoint, blocked_reason=error_code)

    def _resume_block_reason(
        self,
        checkpoint: FinancialCapacityCheckpoint,
        *,
        formal: bool,
    ) -> str | None:
        expected_environment = "production" if formal else "isolated"
        try:
            current_binding = self._binding_source.snapshot(
                environment=expected_environment,
                candidate_sha=checkpoint.binding.candidate_sha,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            return "financial_capacity_runtime_binding_unavailable"
        if current_binding != checkpoint.binding:
            return "financial_capacity_runtime_identity_drift"
        if formal:
            ceiling = checkpoint.governed_ceiling
            receipt = checkpoint.capacity_receipt
            if ceiling is None or receipt is None:
                return "financial_capacity_governed_ceiling_missing"
            if receipt.stage != "capacity_rehearsal":
                return "financial_capacity_receipt_stage_not_eligible"
            try:
                current_ceiling = self._production_ceiling_source.get(
                    receipt_sha256=receipt.sha256,
                    candidate_sha=checkpoint.binding.candidate_sha,
                    manifest_sha256=checkpoint.manifest_sha256,
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                return "financial_capacity_governed_ceiling_unavailable"
            if current_ceiling != ceiling:
                return "financial_capacity_governed_ceiling_drift"
            if not _ceiling_matches(
                ceiling=ceiling,
                receipt=receipt,
                binding=checkpoint.binding,
                manifest_sha256=checkpoint.manifest_sha256,
                now=self._clock(),
            ):
                return "financial_capacity_governed_ceiling_expired_or_drifted"
            snapshot_reason = self._validate_source_snapshot(checkpoint, formal=True)
            if snapshot_reason is not None:
                return snapshot_reason
            if checkpoint.active_universe_sha256 is None:
                return "financial_capacity_scope_import_invalid"
            import_reason, persisted_import_sha256 = self._scope_capacity_import_block_reason(
                import_id=checkpoint.scope_capacity_import_id,
                record_sha256=checkpoint.scope_capacity_import_record_sha256,
                workflow_id=checkpoint.workflow_id,
                binding=checkpoint.binding,
                manifest_sha256=checkpoint.manifest_sha256,
                active_universe_sha256=checkpoint.active_universe_sha256,
                source_revision_sha256=checkpoint.source_revision_sha256,
                expected_consumed=True,
            )
            if import_reason is not None or persisted_import_sha256 != (
                checkpoint.scope_capacity_import_record_sha256
            ):
                if import_reason is None:
                    return "financial_capacity_scope_import_invalid"
                return import_reason
        elif checkpoint.stage == "qualification":
            qualification_ceiling = checkpoint.qualification_ceiling
            if qualification_ceiling is None:
                return "financial_capacity_qualification_ceiling_missing"
            try:
                current_qualification_ceiling = (
                    self._qualification_ceiling_source.get_qualification(
                        binding=checkpoint.binding,
                        manifest_sha256=checkpoint.manifest_sha256,
                    )
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                return "financial_capacity_qualification_ceiling_unavailable"
            if current_qualification_ceiling != qualification_ceiling:
                return "financial_capacity_qualification_ceiling_drift"
            if (
                not _qualification_ceiling_matches(
                    ceiling=qualification_ceiling,
                    binding=checkpoint.binding,
                    manifest_sha256=checkpoint.manifest_sha256,
                    maximum_slices=checkpoint.manifest_count,
                    now=self._clock(),
                )
                or checkpoint.total_provider_request_budget
                > qualification_ceiling.maximum_provider_requests
            ):
                return "financial_capacity_qualification_ceiling_expired_or_drifted"
        elif checkpoint.stage == "capacity_rehearsal":
            rehearsal_ceiling = checkpoint.capacity_rehearsal_ceiling
            if rehearsal_ceiling is None:
                return "financial_capacity_rehearsal_ceiling_missing"
            source = self._capacity_rehearsal_ceiling_source
            if source is None:
                return "financial_capacity_rehearsal_ceiling_unavailable"
            try:
                current_rehearsal_ceiling = source.get_capacity_rehearsal(
                    binding=checkpoint.binding,
                    manifest_sha256=checkpoint.manifest_sha256,
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                return "financial_capacity_rehearsal_ceiling_unavailable"
            if current_rehearsal_ceiling != rehearsal_ceiling:
                return "financial_capacity_rehearsal_ceiling_drift"
            if (
                not _capacity_rehearsal_ceiling_matches(
                    ceiling=rehearsal_ceiling,
                    binding=checkpoint.binding,
                    manifest_sha256=checkpoint.manifest_sha256,
                    maximum_slices=checkpoint.manifest_count,
                    now=self._clock(),
                )
                or checkpoint.total_provider_request_budget
                != rehearsal_ceiling.maximum_provider_requests
            ):
                return "financial_capacity_rehearsal_ceiling_expired_or_drifted"
        else:
            return "financial_capacity_checkpoint_stage_invalid"
        return None

    def _validate_source_snapshot(
        self,
        checkpoint: FinancialCapacityCheckpoint,
        *,
        formal: bool,
    ) -> str | None:
        """Recompute the complete DB revision once at a stage boundary."""

        environment: Literal["isolated", "production"] = "production" if formal else "isolated"
        try:
            snapshot = self._manifest_source.freeze(
                stage=checkpoint.stage,
                environment=environment,
                binding=checkpoint.binding,
            )
            current_manifest = _freeze_manifest(snapshot.slices)
        except (OSError, RuntimeError, TypeError, ValueError):
            return "financial_capacity_runtime_binding_unavailable"
        if (
            len(current_manifest) != checkpoint.manifest_count
            or _manifest_sha256(current_manifest) != checkpoint.manifest_sha256
            or snapshot.source_revision_sha256 != checkpoint.source_revision_sha256
        ):
            return "financial_capacity_scope_drift"
        return None

    def _capacity_receipt_ledger_block_reason(
        self,
        receipt: FinancialCapacityReceipt,
    ) -> str | None:
        """Verify the rehearsal's immutable manifest/evidence ledger before formal use."""

        source_checkpoint = self._checkpoints.get(receipt.workflow_id)
        if (
            source_checkpoint is None
            or source_checkpoint.stage != "capacity_rehearsal"
            or source_checkpoint.status != "success"
            or source_checkpoint.capacity_receipt != receipt
            or source_checkpoint.manifest_sha256 != receipt.manifest_sha256
            or source_checkpoint.source_revision_sha256 != receipt.source_revision_sha256
            or source_checkpoint.manifest_count != receipt.manifest_count
            or source_checkpoint.evidence_count != receipt.evidence_count
            or source_checkpoint.evidence_sha256 != receipt.evidence_sha256
        ):
            return "financial_capacity_receipt_ledger_missing_or_drifted"
        try:
            manifest = self._checkpoints.stream_manifest(receipt.workflow_id)
            evidence = self._checkpoints.stream_evidence(receipt.workflow_id)
        except (FinancialCapacityWorkflowError, OSError, RuntimeError, TypeError, ValueError):
            return "financial_capacity_receipt_ledger_invalid"
        if (
            len(manifest) != receipt.manifest_count
            or _manifest_sha256(manifest) != receipt.manifest_sha256
            or len(evidence) != receipt.evidence_count
            or _evidence_manifest_sha256(evidence) != receipt.evidence_sha256
        ):
            return "financial_capacity_receipt_ledger_invalid"
        return None

    def _formal_start_block_reason(
        self,
        *,
        candidate_sha: str,
        binding: FinancialCapacityBinding,
        manifest: tuple[FinancialPublicationSlice, ...],
        source_revision_sha256: str,
        receipt: FinancialCapacityReceipt,
        ceiling: GovernedFinancialProductionCeiling | None,
    ) -> str | None:
        if binding.environment != "production" or binding.candidate_sha != candidate_sha:
            return "financial_capacity_production_candidate_binding_invalid"
        if receipt.outcome != "success" or receipt.review_status != "pending_review":
            return "financial_capacity_receipt_not_qualified"
        if receipt.stage != "capacity_rehearsal":
            return "financial_capacity_receipt_stage_not_eligible"
        manifest_sha256 = _manifest_sha256(manifest)
        if manifest_sha256 != receipt.manifest_sha256:
            return "financial_capacity_scope_drift"
        if source_revision_sha256 != receipt.source_revision_sha256:
            return "financial_capacity_scope_drift"
        if ceiling is None:
            return "financial_capacity_production_ceiling_not_approved"
        if not ceiling.approved:
            return "financial_capacity_production_ceiling_not_approved"
        now = self._clock()
        if ceiling.approved_at > now:
            return "financial_capacity_production_ceiling_approval_not_yet_effective"
        if ceiling.expires_at <= now:
            return "financial_capacity_production_ceiling_expired"
        if ceiling.receipt_sha256 != receipt.sha256:
            return "financial_capacity_receipt_digest_mismatch"
        if ceiling.binding != binding:
            return "financial_capacity_runtime_identity_drift"
        if manifest_sha256 != ceiling.manifest_sha256:
            return "financial_capacity_scope_drift"
        if (
            ceiling.maximum_slices != len(manifest)
            or ceiling.maximum_provider_requests != len(manifest) * _SLICE_REQUESTS
            or receipt.provider_requests != len(manifest) * _SLICE_REQUESTS
            or receipt.manifest_count != len(manifest)
        ):
            return "financial_capacity_approved_ceiling_does_not_cover_exact_workload"
        if receipt.binding.for_environment("production") != binding:
            return "financial_capacity_runtime_identity_drift"
        return None

    def _build_receipt(
        self,
        checkpoint: FinancialCapacityCheckpoint,
        *,
        outcome: FinancialWorkflowStatus,
    ) -> FinancialCapacityReceipt:
        finished_at = checkpoint.finished_at or self._clock()
        return FinancialCapacityReceipt.build(
            workflow_id=checkpoint.workflow_id,
            stage=checkpoint.stage,
            approval_id=(
                checkpoint.qualification_ceiling.approval_id
                if checkpoint.qualification_ceiling is not None
                else (
                    checkpoint.capacity_rehearsal_ceiling.approval_id
                    if checkpoint.capacity_rehearsal_ceiling is not None
                    else "unapproved"
                )
            ),
            binding=checkpoint.binding,
            manifest_count=checkpoint.manifest_count,
            manifest_sha256=checkpoint.manifest_sha256,
            source_revision_sha256=checkpoint.source_revision_sha256,
            outcome=outcome,
            total_provider_request_budget=checkpoint.total_provider_request_budget,
            provider_requests=checkpoint.observed_provider_requests,
            reserved_provider_requests=checkpoint.reserved_provider_requests,
            requested=checkpoint.requested,
            succeeded=checkpoint.succeeded,
            failed=checkpoint.failed,
            stored=checkpoint.stored,
            evidence_count=checkpoint.evidence_count,
            evidence_sha256=checkpoint.evidence_sha256,
            raw_body_count=checkpoint.raw_body_count,
            raw_audit_count=checkpoint.raw_audit_count,
            typed_evidence_count=checkpoint.typed_evidence_count,
            atomic_fact_write_count=checkpoint.atomic_fact_write_count,
            error_codes=checkpoint.error_codes,
            started_at=checkpoint.started_at,
            finished_at=finished_at,
        )

    def _new_checkpoint(
        self,
        *,
        workflow_id: str,
        stage: FinancialWorkflowStage,
        binding: FinancialCapacityBinding,
        manifest: tuple[FinancialPublicationSlice, ...],
        active_universe_sha256: str,
        source_revision_sha256: str,
        total_provider_request_budget: int,
        capacity_receipt: FinancialCapacityReceipt | None = None,
        qualification_ceiling: GovernedFinancialQualificationCeiling | None = None,
        capacity_rehearsal_ceiling: GovernedFinancialCapacityRehearsalCeiling | None = None,
        governed_ceiling: GovernedFinancialProductionCeiling | None = None,
        status: FinancialWorkflowStatus = "running",
        blocked_reason: str | None = None,
        finished_at: datetime | None = None,
        scope_capacity_import_id: str | None = None,
        scope_capacity_import_record_sha256: str | None = None,
    ) -> FinancialCapacityCheckpoint:
        return FinancialCapacityCheckpoint(
            workflow_id=workflow_id,
            stage=stage,
            binding=binding,
            manifest=manifest,
            manifest_count=len(manifest),
            manifest_sha256=_manifest_sha256(manifest),
            active_universe_sha256=active_universe_sha256,
            source_revision_sha256=source_revision_sha256,
            total_provider_request_budget=total_provider_request_budget,
            status=status,
            next_slice_index=0,
            reserved_provider_requests=0,
            observed_provider_requests=0,
            requested=0,
            succeeded=0,
            failed=0,
            stored=0,
            evidence=(),
            evidence_count=0,
            evidence_sha256=_empty_evidence_sha256(),
            raw_body_count=0,
            raw_audit_count=0,
            typed_evidence_count=0,
            atomic_fact_write_count=0,
            error_codes=(),
            started_at=self._clock(),
            finished_at=finished_at,
            run_id=str(uuid4()),
            capacity_receipt=capacity_receipt,
            qualification_ceiling=qualification_ceiling,
            capacity_rehearsal_ceiling=capacity_rehearsal_ceiling,
            governed_ceiling=governed_ceiling,
            blocked_reason=blocked_reason,
            scope_capacity_import_id=scope_capacity_import_id,
            scope_capacity_import_record_sha256=scope_capacity_import_record_sha256,
        )

    def _formal_authority_is_current(self) -> bool:
        """Fail closed unless the caller supplied an active, same-grant validator."""

        return self._authority_validator is not None and self._authority_validator.is_current()

    def _scope_capacity_import_block_reason(
        self,
        *,
        import_id: str | None,
        record_sha256: str | None,
        workflow_id: str,
        binding: FinancialCapacityBinding,
        manifest_sha256: str,
        active_universe_sha256: str,
        source_revision_sha256: str,
        expected_consumed: bool,
    ) -> tuple[str | None, str | None]:
        """Revalidate the exact imported S6 evidence authority at a formal boundary."""

        if import_id is None and record_sha256 is None:
            return "financial_capacity_scope_import_required", None
        if import_id is None:
            return "financial_capacity_scope_import_invalid", None
        try:
            if str(UUID(import_id)) != import_id:
                return "financial_capacity_scope_import_invalid", None
        except (TypeError, ValueError):
            return "financial_capacity_scope_import_invalid", None
        source = self._scope_capacity_import_authority_source
        if source is None:
            return "financial_capacity_scope_import_unavailable", None
        try:
            persisted_record_sha256 = source.load_record_sha256(import_id)
            if (
                persisted_record_sha256 is None
                or _SHA256.fullmatch(persisted_record_sha256) is None
                or (record_sha256 is not None and record_sha256 != persisted_record_sha256)
            ):
                return "financial_capacity_scope_import_invalid", None
            reason = source.validate_current(
                import_id=import_id,
                record_sha256=persisted_record_sha256,
                workflow_id=workflow_id,
                binding=binding,
                manifest_sha256=manifest_sha256,
                active_universe_sha256=active_universe_sha256,
                source_revision_sha256=source_revision_sha256,
                now=self._clock(),
                expected_consumed=expected_consumed,
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            return "financial_capacity_scope_import_unavailable", None
        if reason is not None:
            return reason, None
        return None, persisted_record_sha256

    def _handle_existing_claim(
        self,
        checkpoint: FinancialCapacityCheckpoint,
    ) -> FinancialCapacityWorkflowResult:
        """Return a live claimant read-only, then fail closed after lease expiry."""

        expires_at = checkpoint.in_flight_claim_expires_at
        if expires_at is not None and expires_at > self._clock():
            return self._result(checkpoint)
        return self._finish(
            checkpoint,
            status="blocked",
            reason="financial_capacity_inflight_outcome_indeterminate",
        )

    def _save(
        self,
        checkpoint: FinancialCapacityCheckpoint,
        *,
        expected_revision: int,
    ) -> FinancialCapacityCheckpoint:
        return self._checkpoints.save(checkpoint, expected_revision=expected_revision)

    def _finish(
        self,
        checkpoint: FinancialCapacityCheckpoint,
        *,
        status: Literal["partial", "failed", "blocked"],
        reason: str,
    ) -> FinancialCapacityWorkflowResult:
        finished = replace(
            checkpoint,
            status=status,
            in_flight_slice_index=(
                checkpoint.in_flight_slice_index
                if reason == "financial_capacity_inflight_outcome_indeterminate"
                else None
            ),
            in_flight_claim_token=(
                checkpoint.in_flight_claim_token
                if reason == "financial_capacity_inflight_outcome_indeterminate"
                else None
            ),
            in_flight_claim_expires_at=(
                checkpoint.in_flight_claim_expires_at
                if reason == "financial_capacity_inflight_outcome_indeterminate"
                else None
            ),
            finished_at=self._clock(),
            blocked_reason=reason,
            error_codes=checkpoint.error_codes + (reason,),
        )
        receipt = (
            None
            if checkpoint.stage == "formal_publication"
            else self._build_receipt(finished, outcome=status)
        )
        saved = self._save(
            replace(finished, capacity_receipt=receipt),
            expected_revision=checkpoint.revision,
        )
        return self._result(saved, blocked_reason=reason)

    def _rejected_start(
        self,
        *,
        workflow_id: str,
        stage: FinancialWorkflowStage,
        binding: FinancialCapacityBinding,
        reason: str,
    ) -> FinancialCapacityWorkflowResult:
        checkpoint = self._new_checkpoint(
            workflow_id=workflow_id,
            stage=stage,
            binding=binding,
            manifest=(),
            active_universe_sha256="0" * 64,
            source_revision_sha256="0" * 64,
            total_provider_request_budget=0,
            status="blocked",
            blocked_reason=reason,
            finished_at=self._clock(),
        )
        return self._result(self._checkpoints.create(checkpoint), blocked_reason=reason)

    @staticmethod
    def _result(
        checkpoint: FinancialCapacityCheckpoint,
        *,
        blocked_reason: str | None = None,
    ) -> FinancialCapacityWorkflowResult:
        outcome: FinancialWorkflowStatus = checkpoint.status
        if checkpoint.status == "running":
            outcome = "partial"
        return FinancialCapacityWorkflowResult(
            outcome=outcome,
            checkpoint=checkpoint,
            blocked_reason=blocked_reason or checkpoint.blocked_reason,
            receipt=checkpoint.capacity_receipt,
            publication_hash=checkpoint.publication_hash,
        )
