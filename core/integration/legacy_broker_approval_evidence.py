"""App-neutral registry for the legacy Broker approval Evidence projector."""

from __future__ import annotations

from collections.abc import Callable, Mapping

LegacyBrokerApprovalEvidenceProjector = Callable[[Mapping[str, object]], Mapping[str, object]]

_projector: LegacyBrokerApprovalEvidenceProjector | None = None


class LegacyBrokerApprovalEvidenceProjectorUnavailable(RuntimeError):
    """Raised when the Research-owned projector has not been registered."""


def configure_legacy_broker_approval_evidence_projector(
    projector: LegacyBrokerApprovalEvidenceProjector,
) -> None:
    """Register the Research-owned pure projector without performing I/O."""

    if not callable(projector):
        raise TypeError("legacy broker approval Evidence projector must be callable")
    global _projector
    _projector = projector


def project_legacy_broker_approval_evidence(
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    """Project one closed payload or fail with a stable unavailable error."""

    if _projector is None:
        raise LegacyBrokerApprovalEvidenceProjectorUnavailable(
            "legacy_broker_approval_evidence_projector_unconfigured"
        )
    return _projector(payload)


__all__ = [
    "LegacyBrokerApprovalEvidenceProjector",
    "LegacyBrokerApprovalEvidenceProjectorUnavailable",
    "configure_legacy_broker_approval_evidence_projector",
    "project_legacy_broker_approval_evidence",
]
