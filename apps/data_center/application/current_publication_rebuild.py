"""Application use cases for rebuilding full-universe current publications."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationFactReference,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.protocols import PublicationPolicyRepositoryProtocol

from .control_plane import CanonicalPublicationRepositoryPort, PublishCanonicalDatasetUseCase
from .publication_utils import publication_hash

_EVIDENCE_ASSET_CODE_LIMIT = 20


class CurrentPublicationCandidateRepositoryProtocol(Protocol):
    """Port selecting the decision-current canonical facts for an asset universe."""

    def list_current_publication_candidates(
        self,
        asset_codes: tuple[str, ...],
    ) -> list[PublicationFactReference]:
        """Return deterministic current fact references for the requested assets."""


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
class _CurrentPublicationSelection:
    """Internal exact selection shared by preview and mutation paths."""

    asset_codes: tuple[str, ...]
    references: tuple[PublicationFactReference, ...]
    preview: CurrentPublicationPreview


class CurrentPublicationRebuildUseCase:
    """Publish one immutable current snapshot only at exact universe coverage."""

    publication_key = "current"

    def __init__(
        self,
        *,
        dataset: CurrentPublicationDataset,
        candidate_repository: CurrentPublicationCandidateRepositoryProtocol,
        publication_repository: CanonicalPublicationRepositoryPort,
        policy_repository: PublicationPolicyRepositoryProtocol,
    ) -> None:
        self.dataset = dataset
        self._candidates = candidate_repository
        self._publications = publication_repository
        self._policies = policy_repository
        self._publisher = PublishCanonicalDatasetUseCase(publication_repository)

    def preview(
        self,
        *,
        asset_codes: Sequence[str],
        published_at: datetime,
    ) -> CurrentPublicationPreview:
        """Inspect exact coverage without writing publication state."""

        return self._select(asset_codes=asset_codes, published_at=published_at).preview

    def execute(
        self,
        *,
        asset_codes: Sequence[str],
        published_at: datetime,
        run_id: str = "",
    ) -> CanonicalPublication:
        """Build and atomically publish a complete current member snapshot."""

        selection = self._select(asset_codes=asset_codes, published_at=published_at)
        if not selection.preview.ready:
            missing = ",".join(selection.preview.missing_asset_codes[:20])
            unexpected = ",".join(selection.preview.unexpected_asset_codes[:20])
            raise ValueError(
                "Current publication is missing active assets or contains unexpected assets: "
                f"missing=[{missing}] unexpected=[{unexpected}]"
            )
        policy = self._policies.get_active(self.dataset.dataset_key)
        if policy is None:
            raise ValueError(f"No active publication policy for {self.dataset.dataset_key}")
        if policy.dataset.value != self.dataset.dataset_key:
            raise ValueError("Publication policy dataset mismatch")
        if "payload_hash" in policy.required_evidence and any(
            not reference.raw_payload_hash.strip() for reference in selection.references
        ):
            raise ValueError("Current publication requires payload_hash evidence")

        digest = publication_hash(selection.references)
        current = self._publications.get_current(
            self.dataset.dataset_key,
            self.publication_key,
        )
        if current is not None and current.publication_hash == digest:
            persisted_members = self._publications.list_members(current.publication_id)
            expected_references = {
                (reference.natural_key, reference.fact_table, reference.fact_pk)
                for reference in selection.references
            }
            persisted_references = {
                (member.natural_key, member.fact_table, member.fact_pk)
                for member in persisted_members
            }
            if (
                current.member_count == len(selection.references)
                and len(persisted_members) == len(selection.references)
                and persisted_references == expected_references
            ):
                return current

        publication_id = str(
            uuid5(
                NAMESPACE_URL,
                (f"agomtradepro:{self.dataset.dataset_key}:" f"{self.publication_key}:{digest}"),
            )
        )
        members = tuple(
            PublicationMember(
                member_id=str(
                    uuid5(
                        uuid5(NAMESPACE_URL, publication_id),
                        reference.natural_key,
                    )
                ),
                publication_id=publication_id,
                dataset_key=self.dataset.dataset_key,
                natural_key=reference.natural_key,
                source=reference.source,
                source_record_id=reference.source_record_id,
                fact_table=reference.fact_table,
                fact_pk=reference.fact_pk,
                observed_at=reference.observed_at,
                raw_payload_hash=reference.raw_payload_hash,
                quality_status=reference.quality_status,
                revision_number=reference.revision_number,
            )
            for reference in selection.references
        )
        as_of = max(reference.observed_at for reference in selection.references)
        source_summary = ",".join(sorted({reference.source for reference in selection.references}))
        if len(source_summary) > 100:
            source_summary = "canonical-multi-source"
        publication = CanonicalPublication(
            publication_id=publication_id,
            dataset_key=self.dataset.dataset_key,
            publication_key=self.publication_key,
            policy_version=f"{policy.dataset.contract_version}:{policy.dataset.schema_version}",
            state=PublicationState.PUBLISHED,
            selected_source=source_summary,
            publication_hash=digest,
            coverage=CoverageSnapshot(
                coverage_id=str(uuid5(NAMESPACE_URL, f"coverage:{publication_id}")),
                publication_id=publication_id,
                requested_count=len(selection.references),
                eligible_count=len(selection.references),
                selected_count=len(selection.references),
                missing_count=0,
                conflict_count=0,
                generated_at=published_at,
            ),
            member_count=len(members),
            conflict_count=0,
            as_of=as_of,
            published_at=published_at,
            created_by=self.dataset.created_by,
            run_id=run_id,
        )
        return self._publisher.execute(
            policy=policy,
            publication=publication,
            members=members,
        )

    def _select(
        self,
        *,
        asset_codes: Sequence[str],
        published_at: datetime,
    ) -> _CurrentPublicationSelection:
        """Normalize a universe and validate deterministic candidate identities."""

        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        normalized_codes = tuple(
            sorted(
                {
                    str(asset_code or "").strip().upper()
                    for asset_code in asset_codes
                    if str(asset_code or "").strip()
                }
            )
        )
        if not normalized_codes:
            raise ValueError("active asset universe cannot be empty")
        requested = set(normalized_codes)
        by_natural_key: dict[str, PublicationFactReference] = {}
        by_fact_reference: dict[tuple[str, str], str] = {}
        for reference in self._candidates.list_current_publication_candidates(normalized_codes):
            if reference.fact_table != self.dataset.fact_table:
                raise ValueError(
                    f"Current publication fact table mismatch for {self.dataset.dataset_key}"
                )
            if reference.observed_at > published_at:
                raise ValueError(
                    f"Current publication contains a future observation for "
                    f"{self.dataset.dataset_key}"
                )
            prior = by_natural_key.get(reference.natural_key)
            if prior is not None and prior.fact_pk != reference.fact_pk:
                raise ValueError("Current publication natural key resolves to multiple facts")
            fact_identity = (reference.fact_table, reference.fact_pk)
            prior_natural_key = by_fact_reference.get(fact_identity)
            if prior_natural_key is not None and prior_natural_key != reference.natural_key:
                raise ValueError("Current publication fact resolves to multiple natural keys")
            by_natural_key[reference.natural_key] = reference
            by_fact_reference[fact_identity] = reference.natural_key

        references = tuple(sorted(by_natural_key.values(), key=lambda item: item.natural_key))
        covered = {
            reference.natural_key.split(":", 1)[0].strip().upper() for reference in references
        }
        missing = tuple(sorted(requested - covered))
        unexpected = tuple(sorted(covered - requested))
        observations = [reference.observed_at for reference in references]
        preview = CurrentPublicationPreview(
            dataset_key=self.dataset.dataset_key,
            requested_asset_count=len(normalized_codes),
            covered_asset_count=len(covered & requested),
            member_count=len(references),
            missing_asset_codes=missing,
            unexpected_asset_codes=unexpected,
            oldest_observed_at=min(observations) if observations else None,
            newest_observed_at=max(observations) if observations else None,
        )
        return _CurrentPublicationSelection(
            asset_codes=normalized_codes,
            references=references,
            preview=preview,
        )


@dataclass(frozen=True)
class CoreCurrentPublicationPreview:
    """Read-only combined preview for all configured core datasets."""

    datasets: tuple[CurrentPublicationPreview, ...]

    @property
    def ready(self) -> bool:
        """Return whether every configured dataset has exact universe coverage."""

        return bool(self.datasets) and all(item.ready for item in self.datasets)

    @property
    def member_count(self) -> int:
        """Return the proposed member count across all datasets."""

        return sum(item.member_count for item in self.datasets)

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe combined preview evidence."""

        return {
            "ready": self.ready,
            "dataset_count": len(self.datasets),
            "member_count": self.member_count,
            "datasets": [item.to_dict() for item in self.datasets],
        }


@dataclass(frozen=True)
class CoreCurrentPublicationRebuildResult:
    """Exact publication identities committed by one coordinated rebuild."""

    publications: tuple[CanonicalPublication, ...]

    @property
    def published_count(self) -> int:
        """Return the committed member count across all publications."""

        return sum(publication.member_count for publication in self.publications)

    @property
    def publication_ids(self) -> tuple[str, ...]:
        """Return committed immutable publication ids."""

        return tuple(publication.publication_id for publication in self.publications)

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe publication evidence."""

        return {
            "published_count": self.published_count,
            "publication_ids": list(self.publication_ids),
            "datasets": [
                {
                    "dataset_key": publication.dataset_key,
                    "publication_id": publication.publication_id,
                    "publication_hash": publication.publication_hash,
                    "member_count": publication.member_count,
                    "as_of": publication.as_of.isoformat() if publication.as_of else None,
                    "published_at": (
                        publication.published_at.isoformat() if publication.published_at else None
                    ),
                }
                for publication in self.publications
            ],
        }


class CoreCurrentPublicationRebuildUseCase:
    """Preview or atomically publish all configured core current datasets."""

    def __init__(
        self,
        *,
        rebuilders: tuple[CurrentPublicationRebuildUseCase, ...],
        transaction: Callable[[], AbstractContextManager[None]],
    ) -> None:
        if not rebuilders:
            raise ValueError("At least one current-publication rebuilder is required")
        dataset_keys = [rebuilder.dataset.dataset_key for rebuilder in rebuilders]
        if len(dataset_keys) != len(set(dataset_keys)):
            raise ValueError("Current-publication rebuilders must have unique datasets")
        self._rebuilders = rebuilders
        self._transaction = transaction

    def preview(
        self,
        *,
        asset_codes: Sequence[str],
        published_at: datetime | None = None,
    ) -> CoreCurrentPublicationPreview:
        """Return one consistent read-only coverage preview."""

        observed_at = published_at or datetime.now(UTC)
        with self._transaction():
            previews = tuple(
                rebuilder.preview(
                    asset_codes=asset_codes,
                    published_at=observed_at,
                )
                for rebuilder in self._rebuilders
            )
        return CoreCurrentPublicationPreview(datasets=previews)

    def execute(
        self,
        *,
        asset_codes: Sequence[str],
        published_at: datetime | None = None,
        run_id: str = "",
    ) -> CoreCurrentPublicationRebuildResult:
        """Publish all datasets in one transaction or leave all current rows intact."""

        observed_at = published_at or datetime.now(UTC)
        with self._transaction():
            publications = tuple(
                rebuilder.execute(
                    asset_codes=asset_codes,
                    published_at=observed_at,
                    run_id=run_id,
                )
                for rebuilder in self._rebuilders
            )
        return CoreCurrentPublicationRebuildResult(publications=publications)


__all__ = [
    "CoreCurrentPublicationPreview",
    "CoreCurrentPublicationRebuildResult",
    "CoreCurrentPublicationRebuildUseCase",
    "CurrentPublicationCandidateRepositoryProtocol",
    "CurrentPublicationDataset",
    "CurrentPublicationPreview",
    "CurrentPublicationRebuildUseCase",
]
