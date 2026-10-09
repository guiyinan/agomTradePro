"""Public application entrypoint for capacity qualification and formal publication."""

from __future__ import annotations

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityActivationIntent,
    FinancialCapacityAuthorityValidator,
    FinancialCapacityBinding,
    FinancialCapacityBindingSource,
    FinancialCapacityBuildIdentitySource,
    FinancialCapacityCheckpoint,
    FinancialCapacityCheckpointRepository,
    FinancialCapacityManifestSnapshot,
    FinancialCapacityManifestSource,
    FinancialCapacityPublicationIndeterminateError,
    FinancialCapacityPublicationPlan,
    FinancialCapacityPublisher,
    FinancialCapacityReceipt,
    FinancialCapacityRehearsalCeilingSource,
    FinancialCapacitySliceAttempt,
    FinancialCapacitySliceEvidence,
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
    InMemoryFinancialCapacityCheckpointRepository,
    ProtocolClock,
    _append_evidence_sha256,
    _empty_evidence_sha256,
    _evidence_manifest_sha256,
    _manifest_sha256,
)
from apps.data_center.application.financial_capacity_formal_publication import (
    FinancialCapacityFormalPublicationWorkflow,
)
from apps.data_center.application.financial_capacity_qualification import (
    FinancialCapacityQualificationWorkflow,
)
from apps.data_center.application.financial_capacity_rehearsal import (
    FinancialCapacityRehearsalWorkflow,
)


class FinancialCapacityWorkflow(
    FinancialCapacityQualificationWorkflow,
    FinancialCapacityRehearsalWorkflow,
    FinancialCapacityFormalPublicationWorkflow,
):
    """Unified API backed by separately maintained qualification and formal workflows."""


__all__ = [
    "FinancialCapacityActivationIntent",
    "FinancialCapacityBinding",
    "FinancialCapacityBindingSource",
    "FinancialCapacityBuildIdentitySource",
    "FinancialCapacityAuthorityValidator",
    "FinancialCapacityCheckpoint",
    "FinancialCapacityCheckpointRepository",
    "FinancialCapacityFormalPublicationWorkflow",
    "FinancialCapacityManifestSource",
    "FinancialCapacityManifestSnapshot",
    "FinancialCapacityPublisher",
    "FinancialCapacityPublicationIndeterminateError",
    "FinancialCapacityPublicationPlan",
    "FinancialCapacityQualificationWorkflow",
    "FinancialCapacityRehearsalWorkflow",
    "FinancialCapacityRehearsalCeilingSource",
    "FinancialCapacityReceipt",
    "FinancialCapacitySliceAttempt",
    "FinancialCapacitySliceEvidence",
    "FinancialCapacitySliceRunner",
    "FinancialScopeCapacityImportAuthoritySource",
    "FinancialCapacityWorkflow",
    "FinancialCapacityWorkflowError",
    "FinancialCapacityWorkflowResult",
    "FinancialProductionCeilingSource",
    "FinancialQualificationCeilingSource",
    "FinancialPublicationSlice",
    "FinancialWorkflowStage",
    "FinancialWorkflowStatus",
    "GovernedFinancialProductionCeiling",
    "GovernedFinancialCapacityRehearsalCeiling",
    "GovernedFinancialQualificationCeiling",
    "InMemoryFinancialCapacityCheckpointRepository",
    "ProtocolClock",
    "_append_evidence_sha256",
    "_empty_evidence_sha256",
    "_evidence_manifest_sha256",
    "_manifest_sha256",
]
