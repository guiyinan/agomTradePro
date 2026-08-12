"""Composition root for read-only canonical Research evidence."""

from apps.research.application.evidence_reads import EvidenceReadFacade


def make_evidence_read_facade() -> EvidenceReadFacade:
    """Inject the Django exact-read repository into the Application facade."""

    from apps.research.infrastructure.evidence_repository import DjangoEvidenceRepository

    return EvidenceReadFacade(DjangoEvidenceRepository())


__all__ = ["make_evidence_read_facade"]
