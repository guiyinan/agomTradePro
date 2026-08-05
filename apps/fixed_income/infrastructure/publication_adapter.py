"""Adapter from Data Center publication evidence to R5 domain references."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.data_center.domain.control_plane import CanonicalPublication, PublicationState
from apps.fixed_income.domain.entities import (
    CanonicalPublicationReference,
    CurveKind,
    InputRole,
)


class DatasetFreshnessPolicyReaderProtocol(Protocol):
    """Read the governed freshness horizon for one canonical dataset."""

    def get_freshness_seconds(self, dataset_key: str) -> int | None: ...


class CanonicalPublicationReaderProtocol(Protocol):
    """Narrow Data Center Application facade consumed by this adapter."""

    def get_as_of(
        self,
        dataset_key: str,
        publication_key: str,
        as_of: datetime,
    ) -> CanonicalPublication | None: ...

    def get_oldest_member_observed_at(self, publication_id: str) -> datetime | None: ...


@dataclass(frozen=True)
class CanonicalDatasetSemantic:
    """Immutable Data Center projection of governed fixed-income semantics."""

    dataset_key: str
    semantic_version: str
    role: InputRole
    currency: str
    curve_kind: CurveKind | None

    def __post_init__(self) -> None:
        if (
            not self.dataset_key.strip()
            or not self.semantic_version.strip()
            or not self.currency.strip()
        ):
            raise ValueError("canonical dataset semantic metadata cannot be blank")


class CanonicalDatasetSemanticReaderProtocol(Protocol):
    """Read canonical role/currency/curve-kind metadata from Data Center Application."""

    def get_semantic(self, dataset_key: str) -> CanonicalDatasetSemantic | None: ...


@dataclass(frozen=True)
class PublishedDatasetRequest:
    """Explicit Data Center scope and semantic role requested by R5."""

    dataset_key: str
    publication_key: str

    def __post_init__(self) -> None:
        if not self.dataset_key.strip() or not self.publication_key.strip():
            raise ValueError("published dataset scope cannot be empty")


@dataclass(frozen=True)
class PublishedInputResolution:
    """Resolved reference or a stable fail-closed reason."""

    reference: CanonicalPublicationReference | None
    blocked_reason: str | None

    def __post_init__(self) -> None:
        if (self.reference is None) == (self.blocked_reason is None):
            raise ValueError("resolution must contain exactly one of reference or blocked_reason")


class DataCenterPublishedInputAdapter:
    """Resolve PIT-visible publication metadata with member freshness evidence."""

    def __init__(
        self,
        publication_repository: CanonicalPublicationReaderProtocol,
        freshness_policy_reader: DatasetFreshnessPolicyReaderProtocol,
        semantic_reader: CanonicalDatasetSemanticReaderProtocol,
    ) -> None:
        self._publication_repository = publication_repository
        self._freshness_policy_reader = freshness_policy_reader
        self._semantic_reader = semantic_reader

    def resolve(
        self,
        request: PublishedDatasetRequest,
        *,
        as_of: datetime,
    ) -> PublishedInputResolution:
        """Return a canonical input reference only when Publication and freshness pass."""

        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        semantic = self._semantic_reader.get_semantic(request.dataset_key)
        if semantic is None:
            return PublishedInputResolution(None, "canonical_dataset_semantic_missing")
        if semantic.dataset_key != request.dataset_key:
            return PublishedInputResolution(None, "canonical_dataset_semantic_mismatch")
        publication = self._publication_repository.get_as_of(
            request.dataset_key,
            request.publication_key,
            as_of,
        )
        if publication is None:
            return PublishedInputResolution(None, "canonical_publication_missing")
        if publication.dataset_key != semantic.dataset_key:
            return PublishedInputResolution(None, "canonical_publication_dataset_mismatch")
        if publication.state not in {PublicationState.PUBLISHED, PublicationState.SUPERSEDED}:
            return PublishedInputResolution(None, "canonical_publication_not_visible")
        if publication.must_not_use_for_decision:
            return PublishedInputResolution(None, "canonical_publication_blocked")
        if publication.published_at is None or publication.published_at > as_of:
            return PublishedInputResolution(None, "canonical_publication_from_future")
        if publication.conflict_count > 0 or publication.member_count <= 0:
            return PublishedInputResolution(None, "canonical_publication_coverage_invalid")
        observed_at = self._publication_repository.get_oldest_member_observed_at(
            publication.publication_id
        )
        if observed_at is None:
            return PublishedInputResolution(None, "canonical_publication_observation_missing")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            return PublishedInputResolution(None, "canonical_publication_observation_invalid")
        if publication.as_of is not None:
            observed_at = min(observed_at, publication.as_of)
        if observed_at > as_of:
            return PublishedInputResolution(None, "canonical_publication_observation_from_future")
        freshness_seconds = self._freshness_policy_reader.get_freshness_seconds(request.dataset_key)
        if freshness_seconds is None or freshness_seconds <= 0:
            return PublishedInputResolution(None, "canonical_publication_freshness_policy_missing")
        valid_until = observed_at + timedelta(seconds=freshness_seconds)
        if valid_until <= as_of:
            return PublishedInputResolution(None, "canonical_publication_stale")
        try:
            reference = CanonicalPublicationReference(
                role=semantic.role,
                currency=semantic.currency,
                curve_kind=semantic.curve_kind,
                semantic_version=semantic.semantic_version,
                owner="data_center",
                dataset_key=publication.dataset_key,
                publication_key=publication.publication_key,
                publication_id=publication.publication_id,
                policy_version=publication.policy_version,
                content_hash=publication.publication_hash,
                observed_at=observed_at,
                published_at=publication.published_at,
                valid_until=valid_until,
            )
        except ValueError:
            return PublishedInputResolution(None, "canonical_publication_metadata_invalid")
        return PublishedInputResolution(reference=reference, blocked_reason=None)
