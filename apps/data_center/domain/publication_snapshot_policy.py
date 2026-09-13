"""Shared policy checks for canonical publication snapshots."""

from __future__ import annotations

from collections.abc import Sequence

from .contracts import PublicationPolicy
from .control_plane import (
    CanonicalPublication,
    PublicationFactReference,
    PublicationMember,
)

SourceSelectionItem = PublicationFactReference | PublicationMember | str


def publication_selected_source_summary(
    items: Sequence[SourceSelectionItem],
) -> str:
    """Return the deterministic selected-source label for frozen members.

    Publication writers select facts from one or more providers.  The
    resulting label is the sorted, comma-separated set of the actual fact
    sources; unusually long labels use the existing canonical multi-source
    sentinel.  Accepting both member and reference value objects keeps the
    rule at the Domain boundary while allowing application rebuild and
    repository validation to share one implementation.
    """

    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
        raise TypeError("publication source items must be a sequence")
    sources: set[str] = set()
    for item in items:
        if isinstance(item, str):
            source = item
        elif isinstance(item, (PublicationFactReference, PublicationMember)):
            source = item.source
        else:
            raise TypeError("publication source items must contain source-bearing values")
        if not source.strip():
            raise ValueError("publication source cannot be blank")
        sources.add(source)
    source_summary = ",".join(sorted(sources))
    return "canonical-multi-source" if len(source_summary) > 100 else source_summary


def validate_publication_snapshot_policy(
    policy: PublicationPolicy,
    publication: CanonicalPublication,
    *,
    members: Sequence[PublicationMember] | None = None,
) -> None:
    """Validate policy identity, coverage and selected-source metadata.

    The coverage and conflict rules intentionally mirror the existing
    application publication use case: partial snapshots are allowed when
    their ratio meets ``minimum_coverage_ratio``, and conflicts are rejected
    only when the policy action is ``block``.  Source-summary validation is
    enabled for versioned evidence because p2 publication metadata must agree
    with the immutable selected members; legacy publication hash semantics
    remain unchanged.
    """

    if not isinstance(policy, PublicationPolicy):
        raise TypeError("policy must be a PublicationPolicy")
    if not isinstance(publication, CanonicalPublication):
        raise TypeError("publication must be a CanonicalPublication")
    if publication.dataset_key != policy.dataset.value:
        raise ValueError("Publication policy dataset mismatch")
    if publication.policy_version != policy.identity:
        raise ValueError("Publication policy identity mismatch")
    if publication.coverage.coverage_ratio < policy.minimum_coverage_ratio:
        raise ValueError("Publication coverage is below policy threshold")
    if publication.conflict_count > 0 and policy.conflict_action == "block":
        raise ValueError("Publication contains conflicts blocked by policy")
    if not policy.uses_versioned_evidence or members is None:
        return
    if not isinstance(members, Sequence) or isinstance(members, (str, bytes, bytearray)):
        raise TypeError("versioned publication members must be a sequence")
    source_summary = publication_selected_source_summary(members)
    if publication.selected_source != source_summary:
        raise ValueError("Publication selected_source does not match member sources")


__all__ = [
    "publication_selected_source_summary",
    "validate_publication_snapshot_policy",
]
