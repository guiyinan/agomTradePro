"""Full-universe isolated financial capacity rehearsal workflow."""

from __future__ import annotations

from dataclasses import replace

from apps.data_center.application.financial_capacity_contracts import (
    _SLICE_REQUESTS,
    FinancialCapacityWorkflowError,
    FinancialCapacityWorkflowResult,
    _capacity_rehearsal_ceiling_matches,
    _freeze_manifest,
    _manifest_sha256,
    _require_token,
)
from apps.data_center.application.financial_capacity_workflow_base import (
    FinancialCapacityWorkflowBase,
)


class FinancialCapacityRehearsalWorkflow(FinancialCapacityWorkflowBase):
    """Measure a complete active-universe workload in the isolated environment."""

    def start_capacity_rehearsal(
        self,
        *,
        workflow_id: str,
        candidate_sha: str,
        total_provider_request_budget: int,
    ) -> FinancialCapacityWorkflowResult:
        """Freeze the full isolated manifest and require an exact reviewed ceiling."""

        _require_token(workflow_id, "workflow_id")
        if type(total_provider_request_budget) is not int or total_provider_request_budget < 0:
            raise FinancialCapacityWorkflowError("financial capacity request budget is invalid")

        binding = self._binding_source.snapshot(
            environment="isolated",
            candidate_sha=candidate_sha,
        )
        if binding.environment != "isolated" or binding.candidate_sha != candidate_sha:
            return self._rejected_start(
                workflow_id=workflow_id,
                stage="capacity_rehearsal",
                binding=binding,
                reason="financial_capacity_isolated_environment_required",
            )

        snapshot = self._manifest_source.freeze(
            stage="capacity_rehearsal",
            environment="isolated",
            binding=binding,
        )
        manifest = _freeze_manifest(snapshot.slices)
        if not manifest:
            return self._rejected_start(
                workflow_id=workflow_id,
                stage="capacity_rehearsal",
                binding=binding,
                reason="financial_capacity_manifest_empty",
            )

        manifest_sha256 = _manifest_sha256(manifest)
        source = self._capacity_rehearsal_ceiling_source
        try:
            ceiling = (
                source.get_capacity_rehearsal(
                    binding=binding,
                    manifest_sha256=manifest_sha256,
                )
                if source is not None
                else None
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            ceiling = None
            reason = "financial_capacity_rehearsal_ceiling_unavailable"
        else:
            reason = ""
            required_budget = len(manifest) * _SLICE_REQUESTS
            if ceiling is None or not _capacity_rehearsal_ceiling_matches(
                ceiling=ceiling,
                binding=binding,
                manifest_sha256=manifest_sha256,
                maximum_slices=len(manifest),
                now=self._clock(),
            ):
                reason = "financial_capacity_rehearsal_ceiling_not_approved"
            elif ceiling.maximum_slices != len(manifest):
                reason = "financial_capacity_rehearsal_ceiling_not_approved"
            elif total_provider_request_budget < required_budget:
                reason = "financial_capacity_total_request_budget_insufficient"
            elif (
                total_provider_request_budget != required_budget
                or total_provider_request_budget != ceiling.maximum_provider_requests
            ):
                reason = "financial_capacity_rehearsal_budget_not_exact"

        checkpoint = self._new_checkpoint(
            workflow_id=workflow_id,
            stage="capacity_rehearsal",
            binding=binding,
            manifest=manifest,
            active_universe_sha256=snapshot.active_universe_sha256,
            source_revision_sha256=snapshot.source_revision_sha256,
            total_provider_request_budget=total_provider_request_budget,
            capacity_rehearsal_ceiling=ceiling if not reason else None,
        )
        if reason:
            checkpoint = replace(
                checkpoint,
                status="blocked",
                blocked_reason=reason,
                finished_at=self._clock(),
            )
        return self._result(self._checkpoints.create(checkpoint))

    def run_capacity_rehearsal(
        self,
        *,
        workflow_id: str,
        max_slices: int | None = None,
    ) -> FinancialCapacityWorkflowResult:
        """Resume the exact full isolated workload without publishing production data."""

        checkpoint = self._checkpoints.get(_require_token(workflow_id, "workflow_id"))
        if checkpoint is None or checkpoint.stage != "capacity_rehearsal":
            raise FinancialCapacityWorkflowError(
                "financial capacity workflow checkpoint is missing"
            )
        if checkpoint.status != "running":
            return self._result(checkpoint)
        return self._run_slices(checkpoint, max_slices=max_slices, formal=False)
