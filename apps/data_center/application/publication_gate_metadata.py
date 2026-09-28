"""Stable metadata projection for current-publication decision gates."""

from __future__ import annotations

from apps.data_center.domain.control_plane import CanonicalPublication


def publication_gate_metadata(
    publication: CanonicalPublication,
    *,
    requested_dataset_key: str,
    requested_publication_key: str,
) -> dict[str, object]:
    """Project publication identity, scope, policy, and business outcome."""

    publication_as_of = publication.as_of
    return {
        "publication_id": publication.publication_id,
        "dataset_key": getattr(publication, "dataset_key", requested_dataset_key),
        "publication_key": getattr(publication, "publication_key", requested_publication_key),
        "published_at": publication.published_at.isoformat() if publication.published_at else None,
        "as_of": publication_as_of.isoformat() if publication_as_of else None,
        "must_not_use_for_decision": publication.must_not_use_for_decision,
        "blocked_reason": publication.blocked_reason,
        "policy_identity": publication.policy_version,
        "policy_version": publication.policy_version,
        "selected_source": publication.selected_source,
        "publication_run_id": publication.run_id,
        "coverage_requested_count": publication.coverage.requested_count,
        "coverage_eligible_count": publication.coverage.eligible_count,
        "coverage_selected_count": publication.coverage.selected_count,
        "coverage_missing_count": publication.coverage.missing_count,
        "publication_outcome": ("partial" if publication.coverage.missing_count else "success"),
    }


__all__ = ["publication_gate_metadata"]
