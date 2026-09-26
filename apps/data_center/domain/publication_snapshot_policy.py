"""Shared policy checks for canonical publication snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

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
    if publication.coverage.coverage_ratio < 1.0 and not policy.allow_partial:
        raise ValueError("Publication policy does not allow partial coverage")
    if publication.scope_blocks and (
        len(publication.scope_blocks) != publication.coverage.missing_count
    ):
        raise ValueError("Publication scope blocks do not match missing coverage")
    if (
        publication.dataset_key == "equity.valuation.fact"
        and publication.publication_key == "current"
        and publication.coverage.missing_count > 0
        and len(publication.scope_blocks) != publication.coverage.missing_count
    ):
        raise ValueError("Partial current valuation requires per-asset scope blocks")
    if (
        publication.dataset_key == "equity.valuation.fact"
        and publication.publication_key == "current"
        and publication.coverage.missing_count > 0
    ):
        _validate_current_valuation_scope_blocks(publication, members)
    if publication.conflict_count > 0 and policy.conflict_action == "block":
        raise ValueError("Publication contains conflicts blocked by policy")
    if not policy.uses_versioned_evidence or members is None:
        return
    if not isinstance(members, Sequence) or isinstance(members, (str, bytes, bytearray)):
        raise TypeError("versioned publication members must be a sequence")
    source_summary = publication_selected_source_summary(members)
    if publication.selected_source != source_summary:
        raise ValueError("Publication selected_source does not match member sources")


def _validate_current_valuation_scope_blocks(
    publication: CanonicalPublication,
    members: Sequence[PublicationMember] | None,
) -> None:
    """Require a complete and aligned trace for every current valuation gap."""

    if members is None or not members:
        raise ValueError("Partial current valuation requires selected members")
    if not publication.run_id.strip():
        raise ValueError("Partial current valuation requires publication run id")
    target_trade_dates: set[date] = set()
    blocked_codes = {block.asset_code.strip().upper() for block in publication.scope_blocks}
    for block in publication.scope_blocks:
        if (
            block.target_trade_date is None
            or not block.source
            or not block.publication_run_id
            or not block.policy_version
            or not block.publication_id
        ):
            raise ValueError("Partial current valuation scope block evidence is incomplete")
        if (
            block.source != publication.selected_source
            or block.publication_run_id != publication.run_id
            or block.policy_version != publication.policy_version
            or block.publication_id != publication.publication_id
        ):
            raise ValueError("Partial current valuation scope block identity differs")
        if block.reason_code != "valuation_source_data_unavailable":
            raise ValueError("Partial current valuation has an unsupported block reason")
        target_trade_dates.add(block.target_trade_date)
    if len(target_trade_dates) != 1:
        raise ValueError("Partial current valuation scope blocks must share one trade date")
    target_trade_date = next(iter(target_trade_dates))

    member_codes: set[str] = set()
    for member in members:
        parts = member.natural_key.split(":")
        if len(parts) < 3:
            raise ValueError("Current valuation member natural key lacks date and source")
        try:
            member_trade_date = date.fromisoformat(parts[1])
        except ValueError as exc:
            raise ValueError("Current valuation member natural key has invalid date") from exc
        if (
            member_trade_date != target_trade_date
            or member_trade_date.isoformat() != parts[1]
            or ":".join(parts[2:]) != member.source
        ):
            raise ValueError("Current valuation member differs from scope-block identity")
        member_codes.add(parts[0].strip().upper())
    if blocked_codes & member_codes:
        raise ValueError("Partial current valuation block overlaps selected members")


__all__ = [
    "publication_selected_source_summary",
    "validate_publication_snapshot_policy",
]
