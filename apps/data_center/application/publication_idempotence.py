"""Validate immutable publication replay before a writer returns current early."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from apps.data_center.domain.contracts import PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationFactReference,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.publication_evidence import validate_publication_evidence
from apps.data_center.domain.publication_snapshot_policy import (
    validate_publication_snapshot_policy,
)

from .publication_utils import member_reference, publication_hash


def publication_replay_matches(
    policy: PublicationPolicy,
    current: CanonicalPublication,
    references: Sequence[PublicationFactReference],
    members: Sequence[PublicationMember],
    *,
    knowledge_cutoff: datetime,
) -> bool:
    """Return exact replay only after validating policy and the complete frozen snapshot."""

    identity = policy.identity if policy.uses_versioned_evidence else None
    expected = publication_hash(references, policy_identity=identity)
    if current.policy_version != policy.identity or current.publication_hash != expected:
        return False
    if (
        current.dataset_key != policy.dataset.value
        or current.state is not PublicationState.PUBLISHED
        or current.must_not_use_for_decision
    ):
        raise ValueError("Current publication is blocked or has inconsistent identity")
    if (
        current.coverage.publication_id != current.publication_id
        or current.coverage.selected_count != current.member_count
    ):
        raise ValueError("Current publication frozen coverage is inconsistent")
    if current.published_at is None or current.published_at > knowledge_cutoff:
        raise ValueError("Current publication is unavailable at the publication cutoff")
    if current.member_count != len(references) or len(members) != len(references):
        raise ValueError("Current publication frozen snapshot is incomplete")
    if any(
        member.publication_id != current.publication_id or member.dataset_key != current.dataset_key
        for member in members
    ):
        raise ValueError("Current publication frozen member identity mismatch")
    for keys in (
        [member.member_id for member in members],
        [member.natural_key for member in members],
        [(member.fact_table, member.fact_pk) for member in members],
    ):
        if len(set(keys)) != len(members):
            raise ValueError("Current publication frozen members contain duplicate identities")
    try:
        validate_publication_snapshot_policy(policy, current, members=members)
    except (TypeError, ValueError):
        # A matching member hash is insufficient when the persisted snapshot
        # violates the active policy.  Let the caller rebuild or fail through
        # the normal publication path instead of returning an unsafe replay.
        return False
    validate_publication_evidence(
        policy, members, published_at=current.published_at, knowledge_cutoff=knowledge_cutoff
    )
    if (
        current.as_of is None
        or current.as_of > current.published_at
        or any(
            member.observed_at is None or member.observed_at > current.as_of for member in members
        )
    ):
        raise ValueError("Current publication frozen observation boundary is inconsistent")
    restored = [
        member_reference(member) for member in sorted(members, key=lambda item: item.natural_key)
    ]
    if publication_hash(restored, policy_identity=identity) != expected:
        raise ValueError("Current publication frozen member hash mismatch")
    return True
