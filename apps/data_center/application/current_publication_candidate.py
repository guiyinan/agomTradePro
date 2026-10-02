"""Pure candidate construction shared by current publication staging paths."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from uuid import NAMESPACE_URL, uuid5

from apps.data_center.domain.contracts import PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationFactReference,
    PublicationMember,
    PublicationScopeBlock,
    PublicationState,
)
from apps.data_center.domain.publication_evidence import validate_publication_evidence
from apps.data_center.domain.publication_snapshot_policy import publication_selected_source_summary

from .publication_utils import (
    current_publication_id_for_hash,
    publication_hash,
    publication_member_from_reference,
)

_EVIDENCE_ASSET_CODE_LIMIT = 20


@dataclass(frozen=True)
class CurrentPublicationDataset:
    """Static identity for one full-universe current publication."""

    dataset_key: str
    fact_table: str
    created_by: str

    def __post_init__(self) -> None:
        for field_name in ("dataset_key", "fact_table", "created_by"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"CurrentPublicationDataset.{field_name} cannot be empty")


@dataclass(frozen=True)
class CurrentPublicationScopeExclusion:
    """One externally verified asset exclusion for a dataset-specific current scope."""

    asset_code: str
    reason_code: str
    target_trade_date: date
    evidence_source: str

    def __post_init__(self) -> None:
        if not self.asset_code.strip() or self.asset_code != self.asset_code.strip().upper():
            raise ValueError("Current publication scope exclusion asset code is not canonical")
        if not self.reason_code.strip() or self.reason_code != self.reason_code.strip():
            raise ValueError("Current publication scope exclusion reason code is not canonical")
        if not isinstance(self.target_trade_date, date) or isinstance(
            self.target_trade_date, datetime
        ):
            raise ValueError("Current publication scope exclusion target date is invalid")
        if not self.evidence_source.strip() or self.evidence_source != self.evidence_source.strip():
            raise ValueError("Current publication scope exclusion evidence source is required")


@dataclass(frozen=True)
class CurrentPublicationPreview:
    """Read-only coverage evidence for one proposed current publication."""

    dataset_key: str
    requested_asset_count: int
    covered_asset_count: int
    member_count: int
    missing_asset_codes: tuple[str, ...]
    unexpected_asset_codes: tuple[str, ...]
    oldest_observed_at: datetime | None
    newest_observed_at: datetime | None

    @property
    def ready(self) -> bool:
        """Return whether the selection exactly covers a non-empty universe."""

        return (
            self.requested_asset_count > 0
            and self.covered_asset_count == self.requested_asset_count
            and self.member_count > 0
            and not self.missing_asset_codes
            and not self.unexpected_asset_codes
        )

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe preview evidence with bounded code samples."""

        return {
            "dataset_key": self.dataset_key,
            "ready": self.ready,
            "requested_asset_count": self.requested_asset_count,
            "covered_asset_count": self.covered_asset_count,
            "member_count": self.member_count,
            "missing_asset_count": len(self.missing_asset_codes),
            "missing_asset_codes": list(self.missing_asset_codes[:_EVIDENCE_ASSET_CODE_LIMIT]),
            "missing_asset_codes_truncated": (
                len(self.missing_asset_codes) > _EVIDENCE_ASSET_CODE_LIMIT
            ),
            "unexpected_asset_count": len(self.unexpected_asset_codes),
            "unexpected_asset_codes": list(
                self.unexpected_asset_codes[:_EVIDENCE_ASSET_CODE_LIMIT]
            ),
            "unexpected_asset_codes_truncated": (
                len(self.unexpected_asset_codes) > _EVIDENCE_ASSET_CODE_LIMIT
            ),
            "oldest_observed_at": (
                self.oldest_observed_at.isoformat() if self.oldest_observed_at is not None else None
            ),
            "newest_observed_at": (
                self.newest_observed_at.isoformat() if self.newest_observed_at is not None else None
            ),
        }


@dataclass(frozen=True)
class CurrentPublicationCandidateSnapshot:
    """Validated fence-external candidate content before persistence or activation."""

    publication: CanonicalPublication
    members: tuple[PublicationMember, ...]
    policy: PublicationPolicy
    references: tuple[PublicationFactReference, ...]

    def __post_init__(self) -> None:
        if self.publication.state is not PublicationState.CANDIDATE:
            raise ValueError("Current publication staging requires a CANDIDATE publication")
        if len(self.members) != self.publication.member_count:
            raise ValueError("Current publication candidate member count is inconsistent")
        if self.publication.publication_id != self.publication.coverage.publication_id:
            raise ValueError("Current publication candidate coverage identity is inconsistent")
        if self.publication.dataset_key != self.policy.dataset.value:
            raise ValueError("Current publication candidate policy dataset is inconsistent")
        if self.publication.policy_version != self.policy.identity:
            raise ValueError("Current publication candidate policy identity is inconsistent")
        if tuple(member.natural_key for member in self.members) != tuple(
            reference.natural_key for reference in self.references
        ):
            raise ValueError(
                "Current publication candidate members differ from selected references"
            )


def build_current_publication_candidate_snapshot(
    *,
    dataset: CurrentPublicationDataset,
    publication_key: str,
    asset_codes: tuple[str, ...],
    references: tuple[PublicationFactReference, ...],
    preview: CurrentPublicationPreview,
    policy: PublicationPolicy,
    published_at: datetime,
    run_id: str,
    scope_exclusions: tuple[CurrentPublicationScopeExclusion, ...],
    suspension_scope_allowed: bool,
) -> CurrentPublicationCandidateSnapshot:
    """Apply current policy rules and produce one immutable candidate snapshot."""

    if policy.dataset.value != dataset.dataset_key:
        raise ValueError("Publication policy dataset mismatch")
    if preview.dataset_key != dataset.dataset_key:
        raise ValueError("Current publication preview dataset mismatch")
    if published_at.tzinfo is None or published_at.utcoffset() is None:
        raise ValueError("published_at must be timezone-aware")

    coverage_ratio = preview.covered_asset_count / preview.requested_asset_count
    partial_valuation_allowed = (
        dataset.dataset_key == "equity.valuation.fact"
        and policy.allow_partial
        and policy.uses_versioned_evidence
        and coverage_ratio >= policy.minimum_coverage_ratio
        and preview.member_count > 0
        and not preview.unexpected_asset_codes
    )
    if not preview.ready and not (partial_valuation_allowed or suspension_scope_allowed):
        missing = ",".join(preview.missing_asset_codes[:20])
        unexpected = ",".join(preview.unexpected_asset_codes[:20])
        raise ValueError(
            "Current publication is missing active assets or contains unexpected assets: "
            f"missing=[{missing}] unexpected=[{unexpected}]"
        )
    if "payload_hash" in policy.required_evidence and any(
        not reference.raw_payload_hash.strip() for reference in references
    ):
        raise ValueError("Current publication requires payload_hash evidence")

    validate_publication_evidence(policy, references, published_at=published_at)
    is_valuation_partial = bool(preview.missing_asset_codes) and not scope_exclusions
    source_summary = publication_selected_source_summary(references)
    block_target_trade_date = (
        _valuation_target_trade_date(references) if is_valuation_partial else None
    )
    if is_valuation_partial and not run_id.strip():
        raise ValueError("Partial current valuation requires publication run id")
    block_drafts = (
        tuple(
            PublicationScopeBlock(
                asset_code=item.asset_code,
                reason_code=item.reason_code,
                target_trade_date=item.target_trade_date,
                source=source_summary,
                publication_run_id=run_id,
                policy_version=policy.identity,
                evidence_source=item.evidence_source,
            )
            for item in scope_exclusions
        )
        if scope_exclusions
        else tuple(
            PublicationScopeBlock(
                asset_code=asset_code,
                reason_code="valuation_source_data_unavailable",
                target_trade_date=block_target_trade_date,
                source=source_summary,
                publication_run_id=run_id,
                policy_version=policy.identity,
            )
            for asset_code in preview.missing_asset_codes
        )
    )
    digest = publication_hash(
        references,
        policy_identity=policy.identity if policy.uses_versioned_evidence else None,
        scope_blocks=block_drafts,
    )
    publication_id = current_publication_id_for_hash(
        dataset.dataset_key,
        publication_key,
        digest,
    )
    scope_blocks = tuple(replace(block, publication_id=publication_id) for block in block_drafts)
    members = tuple(
        publication_member_from_reference(
            reference,
            member_id=str(uuid5(uuid5(NAMESPACE_URL, publication_id), reference.natural_key)),
            publication_id=publication_id,
            dataset_key=dataset.dataset_key,
        )
        for reference in references
    )
    if not members:
        raise ValueError("Current publication candidate must contain members")
    as_of = max(reference.observed_at for reference in references)
    has_scope_blocks = bool(scope_blocks)
    coverage_requested = len(asset_codes) if has_scope_blocks else len(references)
    coverage_eligible = preview.covered_asset_count if has_scope_blocks else len(references)
    publication = CanonicalPublication(
        publication_id=publication_id,
        dataset_key=dataset.dataset_key,
        publication_key=publication_key,
        policy_version=policy.identity,
        state=PublicationState.CANDIDATE,
        selected_source=source_summary,
        publication_hash=digest,
        coverage=CoverageSnapshot(
            coverage_id=str(uuid5(NAMESPACE_URL, f"coverage:{publication_id}")),
            publication_id=publication_id,
            requested_count=coverage_requested,
            eligible_count=coverage_eligible,
            selected_count=len(members),
            missing_count=len(scope_blocks),
            conflict_count=0,
            generated_at=published_at,
        ),
        member_count=len(members),
        conflict_count=0,
        as_of=as_of,
        published_at=None,
        created_by=dataset.created_by,
        run_id=run_id,
        scope_blocks=scope_blocks,
    )
    return CurrentPublicationCandidateSnapshot(
        publication=publication,
        members=members,
        policy=policy,
        references=references,
    )


def _valuation_reference_trade_date(reference: PublicationFactReference) -> date:
    """Return the validated trade date encoded by one valuation natural key."""

    parts = reference.natural_key.split(":")
    if len(parts) < 3:
        raise ValueError("Current valuation natural key lacks its trade date and source")
    asset_code, raw_trade_date = parts[0], parts[1]
    try:
        target_trade_date = date.fromisoformat(raw_trade_date)
    except ValueError as exc:
        raise ValueError("Current valuation natural key has an invalid trade date") from exc
    natural_key_source = ":".join(parts[2:])
    if (
        target_trade_date.isoformat() != raw_trade_date
        or not asset_code.strip()
        or natural_key_source != reference.source
    ):
        raise ValueError("Current valuation natural key identity is inconsistent")
    return target_trade_date


def _valuation_target_trade_date(references: Sequence[PublicationFactReference]) -> date:
    """Return the one trade date shared by selected valuation facts."""

    if not references:
        raise ValueError("Partial current valuation requires selected valuation facts")
    target_dates = {_valuation_reference_trade_date(reference) for reference in references}
    if len(target_dates) != 1:
        raise ValueError("Current valuation candidates must share one target trade date")
    return next(iter(target_dates))


__all__ = [
    "CurrentPublicationCandidateSnapshot",
    "CurrentPublicationDataset",
    "CurrentPublicationPreview",
    "CurrentPublicationScopeExclusion",
    "build_current_publication_candidate_snapshot",
]
