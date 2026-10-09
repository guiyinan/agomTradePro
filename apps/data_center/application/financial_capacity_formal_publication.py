"""Receipt and governance-gated formal financial publication workflow."""

from __future__ import annotations

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityReceipt,
    FinancialCapacityWorkflowError,
    FinancialCapacityWorkflowResult,
    GovernedFinancialProductionCeiling,
    _freeze_manifest,
    _manifest_sha256,
    _require_token,
)
from apps.data_center.application.financial_capacity_workflow_base import (
    FinancialCapacityWorkflowBase,
)


class FinancialCapacityFormalPublicationWorkflow(FinancialCapacityWorkflowBase):
    """Run approved exact-scope AKShare slices and publish only after total success."""

    def start_formal_publication(
        self,
        *,
        workflow_id: str,
        candidate_sha: str,
        capacity_receipt: FinancialCapacityReceipt | None,
        scope_capacity_import_id: str | None = None,
        scope_capacity_import_record_sha256: str | None = None,
    ) -> FinancialCapacityWorkflowResult:
        """Start only with an approved, unexpired ceiling bound to this exact scope."""

        _require_token(workflow_id, "workflow_id")
        authority_current = self._formal_authority_is_current()

        binding = self._binding_source.snapshot(
            environment="production",
            candidate_sha=candidate_sha,
        )

        snapshot = self._manifest_source.freeze(
            stage="formal_publication",
            environment="production",
            binding=binding,
        )
        manifest = _freeze_manifest(snapshot.slices)
        manifest_sha256 = _manifest_sha256(manifest)
        scope_import_reason, persisted_import_sha256 = self._scope_capacity_import_block_reason(
            import_id=scope_capacity_import_id,
            record_sha256=scope_capacity_import_record_sha256,
            workflow_id=workflow_id,
            binding=binding,
            manifest_sha256=manifest_sha256,
            active_universe_sha256=snapshot.active_universe_sha256,
            source_revision_sha256=snapshot.source_revision_sha256,
            expected_consumed=False,
        )
        receipt_stage_eligible = (
            capacity_receipt is not None and capacity_receipt.stage == "capacity_rehearsal"
        )
        ledger_block_reason = (
            self._capacity_receipt_ledger_block_reason(capacity_receipt)
            if receipt_stage_eligible and capacity_receipt is not None
            else "financial_capacity_receipt_stage_not_eligible"
        )
        scope_drift = (
            capacity_receipt is None or manifest_sha256 != capacity_receipt.manifest_sha256
        )
        ceiling_source_error = False
        ceiling: GovernedFinancialProductionCeiling | None = None
        if (
            capacity_receipt is not None
            and not scope_drift
            and receipt_stage_eligible
            and ledger_block_reason is None
        ):
            try:
                ceiling = self._production_ceiling_source.get(
                    receipt_sha256=capacity_receipt.sha256,
                    candidate_sha=candidate_sha,
                    manifest_sha256=manifest_sha256,
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                ceiling_source_error = True
        reason: str | None
        if not authority_current:
            reason = "financial_capacity_authority_not_current"
        elif capacity_receipt is None:
            reason = "financial_capacity_receipt_not_qualified"
        elif not receipt_stage_eligible:
            reason = "financial_capacity_receipt_stage_not_eligible"
        elif ledger_block_reason is not None:
            reason = ledger_block_reason
        elif scope_drift:
            reason = "financial_capacity_scope_drift"
        elif ceiling_source_error:
            reason = "financial_capacity_production_ceiling_unavailable"
        else:
            reason = self._formal_start_block_reason(
                candidate_sha=candidate_sha,
                binding=binding,
                manifest=manifest,
                source_revision_sha256=snapshot.source_revision_sha256,
                receipt=capacity_receipt,
                ceiling=ceiling,
            )
            if reason is None and scope_import_reason is not None:
                reason = scope_import_reason
        approved_ceiling: GovernedFinancialProductionCeiling | None = (
            ceiling if reason is None else None
        )

        checkpoint = self._new_checkpoint(
            workflow_id=workflow_id,
            stage="formal_publication",
            binding=binding,
            manifest=manifest,
            active_universe_sha256=snapshot.active_universe_sha256,
            source_revision_sha256=snapshot.source_revision_sha256,
            total_provider_request_budget=(
                approved_ceiling.maximum_provider_requests if approved_ceiling is not None else 0
            ),
            capacity_receipt=capacity_receipt,
            governed_ceiling=approved_ceiling,
            status="running" if reason is None else "blocked",
            blocked_reason=reason,
            finished_at=self._clock() if reason is not None else None,
            scope_capacity_import_id=(scope_capacity_import_id if reason is None else None),
            scope_capacity_import_record_sha256=(
                persisted_import_sha256 if reason is None else None
            ),
        )

        return self._result(self._checkpoints.create(checkpoint))

    def run_formal_publication(
        self,
        *,
        workflow_id: str,
        max_slices: int | None = None,
    ) -> FinancialCapacityWorkflowResult:
        """Resume exact approved AKShare slices and atomically publish after full success."""

        checkpoint = self._checkpoints.get(_require_token(workflow_id, "workflow_id"))
        if checkpoint is None or checkpoint.stage != "formal_publication":
            raise FinancialCapacityWorkflowError(
                "financial capacity workflow checkpoint is missing"
            )
        if checkpoint.status != "running":
            return self._result(checkpoint)
        return self._run_slices(checkpoint, max_slices=max_slices, formal=True)
