"""Compatibility exports for the Risk Center-owned composition root.

New callers should import the composition from ``apps.risk_center``. This
module intentionally contains no concrete infrastructure imports so the core
integration package remains a dependency-neutral compatibility boundary.
"""

from apps.risk_center.evidence_operator_spec_approval_composition import (
    EvidenceOperatorSpecApprovalWriteRuntime,
    build_evidence_operator_spec_approval_write_runtime,
)

__all__ = [
    "EvidenceOperatorSpecApprovalWriteRuntime",
    "build_evidence_operator_spec_approval_write_runtime",
]
