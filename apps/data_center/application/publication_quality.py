"""Exact member-snapshot projection for canonical publication quality."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from apps.audit.application.data_quality_audit import (
    DataQualityAuditObservation,
    DataQualityState,
    DataQualityStatusCount,
)
from apps.data_center.application.publication_utils import publication_hash
from apps.data_center.application.sync_transaction import (
    DataCenterSyncClock,
    DataQualityAuditWriter,
)
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationFactReference,
    PublicationMember,
    PublicationState,
)

_ACCEPTED_MEMBER_STATUSES: Final[frozenset[str]] = frozenset({"accepted", "valid", "verified"})
_DEGRADED_MEMBER_STATUSES: Final[frozenset[str]] = frozenset(
    {"available_at_unverified", "error", "estimated", "missing"}
)


def _require_token(value: object, field_name: str) -> str:
    """Return one bounded non-whitespace token or raise."""

    if (
        type(value) is not str
        or not value
        or len(value) > 256
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _normalize_member_quality_status(value: object) -> DataQualityState:
    """Map only the explicitly governed member-quality vocabulary."""

    if type(value) is not str or value.strip() != value or not value:
        raise ValueError("member quality_status must be a non-empty canonical value")
    if value in _ACCEPTED_MEMBER_STATUSES:
        return "accepted"
    if value in _DEGRADED_MEMBER_STATUSES:
        return "degraded"
    if value == "stale":
        raise ValueError("stale is governed by freshness, not publication quality")
    raise ValueError("member quality_status is not registered")


@dataclass(frozen=True, slots=True)
class PublicationQualityStatusCount:
    """Count publication members in one normalized quality bucket."""

    status: DataQualityState
    count: int

    def __post_init__(self) -> None:
        if self.status not in {"accepted", "degraded"}:
            raise ValueError("status must be accepted or degraded")
        if not isinstance(self.count, int) or isinstance(self.count, bool) or self.count < 1:
            raise ValueError("count must be a positive integer")


@dataclass(frozen=True, slots=True)
class PublicationQualityProjection:
    """Verified aggregate quality bound to one exact publication snapshot."""

    publication_id: str
    dataset_key: str
    publication_key: str
    publication_version: str
    publication_hash: str
    quality_state: DataQualityState
    member_count: int
    quality_status_counts: tuple[PublicationQualityStatusCount, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "publication_id",
            "dataset_key",
            "publication_key",
            "publication_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        if len(self.publication_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.publication_hash
        ):
            raise ValueError("publication_hash must be a lowercase sha256 digest")
        if self.quality_state not in {"accepted", "degraded"}:
            raise ValueError("quality_state must be accepted or degraded")
        if (
            not isinstance(self.member_count, int)
            or isinstance(self.member_count, bool)
            or self.member_count < 1
        ):
            raise ValueError("member_count must be a positive integer")
        if not self.quality_status_counts:
            raise ValueError("quality_status_counts cannot be empty")
        if any(
            not isinstance(item, PublicationQualityStatusCount)
            for item in self.quality_status_counts
        ):
            raise TypeError("quality_status_counts contains an invalid value")
        statuses = tuple(item.status for item in self.quality_status_counts)
        if statuses != tuple(sorted(statuses)) or len(set(statuses)) != len(statuses):
            raise ValueError("quality_status_counts must be unique and canonically ordered")
        if sum(item.count for item in self.quality_status_counts) != self.member_count:
            raise ValueError("quality_status_counts must account for every member")
        projected_state: DataQualityState = "degraded" if "degraded" in statuses else "accepted"
        if projected_state != self.quality_state:
            raise ValueError("quality_state differs from quality_status_counts")


class PublicationQualityReader(Protocol):
    """Read one exact canonical publication and its complete member snapshot."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the transaction identity shared with the audit writer."""

    def get_by_id(self, publication_id: str) -> CanonicalPublication | None:
        """Return the exact publication or ``None``."""

    def list_members(self, publication_id: str) -> Sequence[PublicationMember]:
        """Return the complete persisted member snapshot."""


def _member_reference(member: PublicationMember) -> PublicationFactReference:
    """Restore one canonical publication-hash input from its persisted member."""

    if member.observed_at is None:
        raise ValueError("published member requires observed_at")
    return PublicationFactReference(
        natural_key=member.natural_key,
        source=member.source,
        source_record_id=member.source_record_id,
        fact_table=member.fact_table,
        fact_pk=member.fact_pk,
        observed_at=member.observed_at,
        raw_payload_hash=member.raw_payload_hash,
        quality_status=member.quality_status,
        revision_number=member.revision_number,
    )


def project_publication_quality(
    publication: CanonicalPublication,
    members: Sequence[PublicationMember],
) -> PublicationQualityProjection:
    """Verify a complete member snapshot and derive its canonical quality state."""

    if not isinstance(publication, CanonicalPublication):
        raise TypeError("publication must be a CanonicalPublication")
    if publication.state is not PublicationState.PUBLISHED:
        raise ValueError("quality projection requires a published publication")
    if not isinstance(members, Sequence) or isinstance(members, (str, bytes, bytearray)):
        raise TypeError("members must be a sequence of PublicationMember values")
    member_snapshot = tuple(members)
    if not member_snapshot:
        raise ValueError("quality projection requires a non-empty member snapshot")
    if any(not isinstance(member, PublicationMember) for member in member_snapshot):
        raise TypeError("members contains an invalid value")
    if len(member_snapshot) != publication.member_count:
        raise ValueError("member snapshot count differs from publication.member_count")
    if any(
        member.publication_id != publication.publication_id
        or member.dataset_key != publication.dataset_key
        for member in member_snapshot
    ):
        raise ValueError("member snapshot identity differs from its publication")
    natural_keys = tuple(member.natural_key for member in member_snapshot)
    member_ids = tuple(member.member_id for member in member_snapshot)
    fact_keys = tuple((member.fact_table, member.fact_pk) for member in member_snapshot)
    if (
        len(set(natural_keys)) != len(member_snapshot)
        or len(set(member_ids)) != len(member_snapshot)
        or len(set(fact_keys)) != len(member_snapshot)
    ):
        raise ValueError("member snapshot contains duplicate identities")

    ordered_members = tuple(sorted(member_snapshot, key=lambda member: member.natural_key))
    references = tuple(_member_reference(member) for member in ordered_members)
    if publication_hash(references) != publication.publication_hash:
        raise ValueError("member snapshot hash differs from publication.publication_hash")

    counts: Counter[DataQualityState] = Counter()
    for member in ordered_members:
        counts[_normalize_member_quality_status(member.quality_status)] += 1
    status_counts = tuple(
        PublicationQualityStatusCount(status=status, count=counts[status])
        for status in sorted(counts)
    )
    quality_state: DataQualityState = "degraded" if counts["degraded"] else "accepted"
    return PublicationQualityProjection(
        publication_id=publication.publication_id,
        dataset_key=publication.dataset_key,
        publication_key=publication.publication_key,
        publication_version=publication.policy_version,
        publication_hash=publication.publication_hash,
        quality_state=quality_state,
        member_count=len(ordered_members),
        quality_status_counts=status_counts,
    )


class RecordPublicationQualityUseCase:
    """Reload, verify, and audit one publication-quality state in the active UOW."""

    __slots__ = ("_clock", "_publication_reader", "_quality_writer")

    def __init__(
        self,
        *,
        publication_reader: PublicationQualityReader,
        quality_writer: DataQualityAuditWriter,
        clock: DataCenterSyncClock,
    ) -> None:
        expected_uow_key = f"django:{quality_writer.database_alias}"
        if publication_reader.unit_of_work_key != expected_uow_key:
            raise ValueError("publication reader and quality writer use different transactions")
        self._publication_reader = publication_reader
        self._quality_writer = quality_writer
        self._clock = clock

    @property
    def database_alias(self) -> str:
        """Return the database alias used by the canonical quality writer."""

        return self._quality_writer.database_alias

    def execute(
        self,
        *,
        publication_id: str,
        run_id: str,
        ingested_run_id: str,
        provider_key: str,
    ) -> DataQualityAuditObservation:
        """Audit the exact persisted member snapshot or fail without fallback."""

        for field_name, value in (
            ("publication_id", publication_id),
            ("run_id", run_id),
            ("ingested_run_id", ingested_run_id),
            ("provider_key", provider_key),
        ):
            _require_token(value, field_name)
        publication = self._publication_reader.get_by_id(publication_id)
        if publication is None:
            raise ValueError("canonical publication evidence is unavailable")
        if publication.publication_id != publication_id:
            raise ValueError("publication reader substituted the requested identity")
        if publication.selected_source != provider_key:
            raise ValueError("publication selected source differs from provider_key")
        members = tuple(self._publication_reader.list_members(publication_id))
        projection = project_publication_quality(publication, members)
        if publication.published_at is None:
            raise ValueError("published publication requires published_at")
        observation = DataQualityAuditObservation(
            dataset_key=projection.dataset_key,
            publication_key=projection.publication_key,
            publication_id=projection.publication_id,
            publication_version=projection.publication_version,
            publication_hash=projection.publication_hash,
            provider_key=provider_key,
            run_id=run_id,
            ingested_run_id=ingested_run_id,
            quality_state=projection.quality_state,
            member_count=projection.member_count,
            quality_status_counts=tuple(
                DataQualityStatusCount(status=item.status, count=item.count)
                for item in projection.quality_status_counts
            ),
            occurred_at=publication.published_at,
            recorded_at=self._clock.now(),
        )
        self._quality_writer.write(observation)
        return observation


__all__ = [
    "project_publication_quality",
    "PublicationQualityProjection",
    "PublicationQualityReader",
    "PublicationQualityStatusCount",
    "RecordPublicationQualityUseCase",
]
