"""Pure validation of the evidence behind a current publication snapshot."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Final

from apps.data_center.application.publication_utils import member_reference, publication_hash
from apps.data_center.domain.contracts import PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.publication_evidence import validate_publication_evidence
from apps.data_center.domain.publication_snapshot_policy import (
    validate_publication_snapshot_policy,
)

_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}")


def current_publication_evidence_blocked_reason(
    publication: CanonicalPublication,
    *,
    policy: PublicationPolicy | None,
    members: Sequence[PublicationMember],
    fact_content_hashes: Mapping[tuple[str, str], str],
    knowledge_cutoff: datetime,
) -> str | None:
    """Return a stable blocker reason for an unusable current publication.

    The helper performs no I/O.  ``fact_content_hashes`` is an exact,
    caller-supplied snapshot keyed by ``(fact_table, fact_pk)``; a missing or
    changed value fails closed before a current decision can consume mutable
    fact rows.  Historical legacy publications remain hash-compatible, but a
    current member must still carry a normalized SHA-256 proof.
    """

    if not isinstance(publication, CanonicalPublication):
        return "publication_member_snapshot_invalid"
    if policy is None:
        return "publication_policy_missing"
    if not isinstance(policy, PublicationPolicy):
        return "publication_policy_missing"
    if publication.policy_version != policy.identity:
        return "publication_policy_changed"
    if publication.dataset_key != policy.dataset.value:
        return "publication_policy_dataset_mismatch"
    if not _is_aware(knowledge_cutoff):
        return "publication_knowledge_unavailable"
    published_at = publication.published_at
    if published_at is None or not _is_aware(published_at) or published_at > knowledge_cutoff:
        return "publication_knowledge_unavailable"
    as_of = publication.as_of
    if as_of is None or not _is_aware(as_of) or as_of > published_at:
        return "publication_knowledge_unavailable"
    if publication.state is not PublicationState.PUBLISHED:
        return "publication_member_snapshot_invalid"
    if publication.must_not_use_for_decision:
        return "publication_knowledge_unavailable"
    if publication.coverage.publication_id != publication.publication_id:
        return "publication_member_snapshot_invalid"
    if publication.coverage.selected_count != publication.member_count:
        return "publication_member_snapshot_invalid"
    if not isinstance(members, Sequence) or isinstance(members, (str, bytes, bytearray)):
        return "publication_member_snapshot_invalid"
    if len(members) != publication.member_count or not members:
        return "publication_member_snapshot_invalid"

    snapshot_reason = _validate_member_snapshot(publication, members)
    if snapshot_reason is not None:
        return snapshot_reason
    try:
        validate_publication_snapshot_policy(policy, publication, members=members)
    except (TypeError, ValueError):
        return "publication_policy_violation"
    if any(
        member.observed_at is None
        or not _is_aware(member.observed_at)
        or member.observed_at > as_of
        for member in members
    ):
        return "publication_knowledge_unavailable"
    fact_reason = _validate_fact_hashes(members, fact_content_hashes)
    if fact_reason is not None:
        return fact_reason

    try:
        validate_publication_evidence(
            policy,
            members,
            published_at=published_at,
            knowledge_cutoff=knowledge_cutoff,
        )
    except (TypeError, ValueError):
        return "publication_member_evidence_missing"

    try:
        references = tuple(
            member_reference(member)
            for member in sorted(members, key=lambda item: item.natural_key)
        )
    except (TypeError, ValueError):
        return "publication_member_evidence_missing"
    policy_identity = policy.identity if policy.uses_versioned_evidence else None
    try:
        digest = publication_hash(references, policy_identity=policy_identity)
    except (TypeError, ValueError):
        return "publication_member_snapshot_invalid"
    if digest != publication.publication_hash:
        return "publication_member_snapshot_invalid"
    return None


def _validate_member_snapshot(
    publication: CanonicalPublication,
    members: Sequence[PublicationMember],
) -> str | None:
    """Validate member count, publication identity and unique references."""

    if any(not isinstance(member, PublicationMember) for member in members):
        return "publication_member_snapshot_invalid"
    natural_keys = [member.natural_key for member in members]
    member_ids = [member.member_id for member in members]
    fact_keys = [(member.fact_table, member.fact_pk) for member in members]
    if len(set(natural_keys)) != len(members):
        return "publication_member_snapshot_invalid"
    if len(set(member_ids)) != len(members):
        return "publication_member_snapshot_invalid"
    if len(set(fact_keys)) != len(members):
        return "publication_member_snapshot_invalid"
    if any(
        member.publication_id != publication.publication_id
        or member.dataset_key != publication.dataset_key
        or not member.fact_table.strip()
        or not member.fact_pk.strip()
        for member in members
    ):
        return "publication_member_snapshot_invalid"
    return None


def _validate_fact_hashes(
    members: Sequence[PublicationMember],
    fact_content_hashes: Mapping[tuple[str, str], str],
) -> str | None:
    """Require exact normalized-row hashes for every selected fact."""

    if not isinstance(fact_content_hashes, Mapping):
        return "publication_member_evidence_missing"
    member_keys = {(member.fact_table, member.fact_pk) for member in members}
    provided_keys = set(fact_content_hashes)
    if not member_keys.issubset(provided_keys):
        return "publication_member_evidence_missing"
    if provided_keys != member_keys:
        return "publication_member_snapshot_invalid"
    for member in members:
        member_hash = member.fact_content_hash
        fact_hash = fact_content_hashes[(member.fact_table, member.fact_pk)]
        if not _is_sha256(member_hash):
            return "publication_member_evidence_missing"
        if not _is_sha256(fact_hash):
            return "publication_member_fact_changed"
        if member_hash != fact_hash:
            return "publication_member_fact_changed"
    return None


def _is_sha256(value: object) -> bool:
    """Return whether a value is an exact lowercase SHA-256 digest."""

    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _is_aware(value: object) -> bool:
    """Return whether a timestamp has an unambiguous UTC offset."""

    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


__all__ = ["current_publication_evidence_blocked_reason"]
