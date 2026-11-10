"""Read-only adaptation of persisted Data Center disclosure coverage for plans."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Protocol

from apps.data_center.application.security_disclosure_event import (
    QuerySecurityDisclosureListingCoverageUseCase,
)
from apps.data_center.domain.security_disclosure_event import (
    PersistedSecurityDisclosureEvent,
    PersistedSecurityDisclosureListingCoverage,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureListingCoverageReadScope,
    SecurityDisclosureListingCoverageSnapshot,
    SecurityDisclosureListingCoverageStatus,
    SecurityDisclosureSource,
)
from apps.portfolio.application.transition_plan_event_review import (
    TransitionPlanEventSnapshotReader,
    TransitionPlanEventSnapshotReadError,
    TransitionPlanEventSnapshotReadRequest,
)
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventAssetSnapshot,
    TransitionPlanEventCoverageLeasePolicy,
    TransitionPlanEventCoverageStatus,
    TransitionPlanEventRevision,
)
from apps.simulated_trading.application.rebalance_journey_event_coverage import (
    RebalanceJourneyEventCoverageScope,
)


class _ListingCoverageQuery(Protocol):
    """Read the Data Center's persisted listing proof and event facts."""

    def execute(
        self,
        scope: SecurityDisclosureListingCoverageReadScope,
    ) -> SecurityDisclosureListingCoverageSnapshot:
        """Return one typed exact-window snapshot without write side effects."""
        ...


class DataCenterTransitionPlanEventSnapshotReader(TransitionPlanEventSnapshotReader):
    """Adapt persisted official SZSE listing coverage to Portfolio's snapshot port."""

    def __init__(self, *, query_use_case: QuerySecurityDisclosureListingCoverageUseCase) -> None:
        """Inject the Data Center read use case; this adapter has no repository or write path."""

        self._query_use_case: _ListingCoverageQuery = query_use_case

    def read_snapshot(
        self,
        request: TransitionPlanEventSnapshotReadRequest,
    ) -> TransitionPlanEventAssetSnapshot | None:
        """Map one exact proof and its as-of event revisions without deriving security identity."""

        if type(request) is not TransitionPlanEventSnapshotReadRequest:
            raise TransitionPlanEventSnapshotReadError(
                "Transition-plan event snapshot request is invalid."
            )
        if request.source_id != SecurityDisclosureSource.SZSE_OFFICIAL.value:
            raise TransitionPlanEventSnapshotReadError(
                "Only the official SZSE disclosure source is supported."
            )

        data_center_scope = SecurityDisclosureListingCoverageReadScope(
            asset_code=request.asset_code,
            start_on=request.start_on,
            end_on=request.end_on,
            as_of=request.as_of,
        )
        result = self._query_use_case.execute(data_center_scope)
        if type(result) is not SecurityDisclosureListingCoverageSnapshot:
            raise TransitionPlanEventSnapshotReadError(
                "Data Center returned an untyped listing-coverage result."
            )
        if result.scope != data_center_scope:
            raise TransitionPlanEventSnapshotReadError(
                "Data Center returned coverage outside the requested exact window."
            )

        persisted = result.proof
        if persisted is None:
            if result.coverage_status is SecurityDisclosureListingCoverageStatus.MISSING:
                return None
            raise TransitionPlanEventSnapshotReadError(
                "Data Center returned a non-missing status without a persisted listing proof."
            )
        if result.coverage_status is SecurityDisclosureListingCoverageStatus.MISSING:
            raise TransitionPlanEventSnapshotReadError(
                "Data Center marked a persisted listing proof as missing."
            )

        self._validate_persisted_proof(persisted, request)
        revisions = tuple(
            self._map_event_revision(item, request=request, proof=persisted)
            for item in result.events
        )
        self._reject_ambiguous_revisions(revisions)

        coverage_status = _portfolio_coverage_status(result.coverage_status)
        if any(item.event_type == SecurityDisclosureEventType.UNKNOWN.value for item in revisions):
            coverage_status = TransitionPlanEventCoverageStatus.UNKNOWN
        if not _events_match_listed_entries(result.events, persisted):
            coverage_status = TransitionPlanEventCoverageStatus.UNKNOWN
        if persisted.recorded_at != request.as_of:
            coverage_status = TransitionPlanEventCoverageStatus.UNKNOWN
        if result.coverage_status is SecurityDisclosureListingCoverageStatus.COMPLETE:
            self._validate_complete_listing(result, persisted, revisions, request)
            if persisted.recorded_at != request.as_of:
                coverage_status = TransitionPlanEventCoverageStatus.UNKNOWN

        try:
            return TransitionPlanEventAssetSnapshot(
                asset_code=request.asset_code,
                security_id=request.security_id,
                source_id=request.source_id,
                start_on=request.start_on,
                end_on=request.end_on,
                as_of=request.as_of,
                first_observed_at=persisted.proof.first_observed_at,
                source_observed_at=persisted.proof.verified_at,
                proof_recorded_at=persisted.recorded_at,
                coverage_status=coverage_status,
                source_scope_sha256=persisted.proof.coverage_manifest_sha256,
                events=revisions,
            )
        except (TypeError, ValueError) as error:
            raise TransitionPlanEventSnapshotReadError(
                "Persisted Data Center coverage cannot form a valid Portfolio snapshot."
            ) from error

    @staticmethod
    def _validate_persisted_proof(
        persisted: PersistedSecurityDisclosureListingCoverage,
        request: TransitionPlanEventSnapshotReadRequest,
    ) -> None:
        """Reject a proof that does not bind the official source, asset, window, and cutoff."""

        if type(persisted) is not PersistedSecurityDisclosureListingCoverage:
            raise TransitionPlanEventSnapshotReadError(
                "Data Center returned an untyped persisted listing proof."
            )
        proof = persisted.proof
        if (
            proof.source is not SecurityDisclosureSource.SZSE_OFFICIAL
            or proof.exchange is not SecurityDisclosureExchange.SZSE
            or proof.source.exchange is not proof.exchange
            or proof.asset_code != request.asset_code
            or proof.start_on != request.start_on
            or proof.end_on != request.end_on
        ):
            raise TransitionPlanEventSnapshotReadError(
                "Persisted proof does not match the official SZSE security and exact window."
            )
        if persisted.recorded_at > request.as_of:
            raise TransitionPlanEventSnapshotReadError(
                "Persisted listing proof is later than the requested knowledge cutoff."
            )

    @staticmethod
    def _map_event_revision(
        persisted: PersistedSecurityDisclosureEvent,
        *,
        request: TransitionPlanEventSnapshotReadRequest,
        proof: PersistedSecurityDisclosureListingCoverage,
    ) -> TransitionPlanEventRevision:
        """Preserve event revision, source clocks, first-seen time, and both source hashes."""

        if type(persisted) is not PersistedSecurityDisclosureEvent:
            raise TransitionPlanEventSnapshotReadError(
                "Data Center returned an untyped persisted disclosure event."
            )
        event = persisted.event
        if (
            event.source is not SecurityDisclosureSource.SZSE_OFFICIAL
            or event.exchange is not SecurityDisclosureExchange.SZSE
            or event.source.exchange is not event.exchange
            or event.asset_code != request.asset_code
            or event.source_security_code != request.asset_code[:6]
            or event.source_event_id not in proof.proof.source_document_ids
            or persisted.recorded_at > request.as_of
        ):
            raise TransitionPlanEventSnapshotReadError(
                "Persisted disclosure event is outside the exact official source scope."
            )
        entries_by_document_id = {entry.source_document_id: entry for entry in proof.proof.entries}
        entry = entries_by_document_id[event.source_event_id]
        if event.source_url != entry.source_url:
            raise TransitionPlanEventSnapshotReadError(
                "Persisted disclosure event does not match its exact listing identity."
            )

        return TransitionPlanEventRevision(
            asset_code=request.asset_code,
            security_id=request.security_id,
            source_id=request.source_id,
            source_event_id=event.source_event_id,
            source_revision_id=event.source_revision_id,
            event_type=event.event_type.value,
            announced_at=event.announced_at,
            available_at=event.first_seen_at,
            known_at=persisted.recorded_at,
            effective_at=event.effective_at,
            body_sha256=event.source_body_sha256,
            manifest_sha256=event.content_hash,
        )

    @staticmethod
    def _reject_ambiguous_revisions(
        revisions: tuple[TransitionPlanEventRevision, ...],
    ) -> None:
        """Reject multiple source revisions for one native event identity."""

        event_ids = tuple(item.source_event_id for item in revisions)
        if len(event_ids) != len(set(event_ids)):
            raise TransitionPlanEventSnapshotReadError(
                "Data Center returned ambiguous revisions for one source event."
            )

    @staticmethod
    def _validate_complete_listing(
        result: SecurityDisclosureListingCoverageSnapshot,
        persisted: PersistedSecurityDisclosureListingCoverage,
        revisions: tuple[TransitionPlanEventRevision, ...],
        request: TransitionPlanEventSnapshotReadRequest,
    ) -> None:
        """Require a complete response to represent every exact listed PDF once."""

        expected_ids = set(persisted.proof.source_document_ids)
        represented_ids = {item.source_event_id for item in revisions}
        if (
            result.scope.as_of != persisted.recorded_at
            or persisted.recorded_at != request.as_of
            or represented_ids != expected_ids
            or any(
                item.event_type == SecurityDisclosureEventType.UNKNOWN.value for item in revisions
            )
        ):
            raise TransitionPlanEventSnapshotReadError(
                "Data Center COMPLETE coverage does not match its exact persisted proof."
            )


def translate_persisted_listing_coverage_to_scope(
    *,
    asset_identity: tuple[str, str],
    source_id: str,
    start_on: date,
    end_on: date,
    decision_cutoff: datetime,
    persisted_coverage: PersistedSecurityDisclosureListingCoverage | None,
    lease_policy: TransitionPlanEventCoverageLeasePolicy | None,
) -> RebalanceJourneyEventCoverageScope | None:
    """Build a fresh exact proof scope using its original durable clock and injected lease."""

    if (
        type(asset_identity) is not tuple
        or len(asset_identity) != 2
        or any(
            type(value) is not str or not value or value.strip() != value
            for value in asset_identity
        )
        or type(source_id) is not str
        or source_id != SecurityDisclosureSource.SZSE_OFFICIAL.value
        or type(start_on) is not date
        or type(start_on) is datetime
        or type(end_on) is not date
        or type(end_on) is datetime
        or start_on > end_on
        or type(decision_cutoff) is not datetime
        or decision_cutoff.tzinfo is None
        or decision_cutoff.utcoffset() is None
        or type(persisted_coverage) is not PersistedSecurityDisclosureListingCoverage
        or type(lease_policy) is not TransitionPlanEventCoverageLeasePolicy
    ):
        return None

    asset_code, security_id = asset_identity
    proof = persisted_coverage.proof
    if (
        proof.source is not SecurityDisclosureSource.SZSE_OFFICIAL
        or proof.exchange is not SecurityDisclosureExchange.SZSE
        or proof.asset_code != asset_code
        or proof.start_on != start_on
        or proof.end_on != end_on
        or proof.first_observed_at > proof.verified_at
        or proof.verified_at > persisted_coverage.recorded_at
        or persisted_coverage.recorded_at > decision_cutoff
    ):
        return None

    policy_version = lease_policy.policy_version
    ttl = lease_policy.ttl
    maximum_ttl = lease_policy.maximum_ttl
    if (
        type(policy_version) is not str
        or not policy_version
        or policy_version.strip() != policy_version
        or type(ttl) is not timedelta
        or type(maximum_ttl) is not timedelta
        or ttl <= timedelta(0)
        or ttl > maximum_ttl
    ):
        return None
    try:
        expires_at = persisted_coverage.recorded_at + ttl
    except OverflowError:
        return None
    if not persisted_coverage.recorded_at <= decision_cutoff < expires_at:
        return None

    try:
        return RebalanceJourneyEventCoverageScope(
            asset_code=asset_code,
            security_id=security_id,
            source_id=source_id,
            start_on=start_on,
            end_on=end_on,
            first_observed_at=proof.first_observed_at,
            source_observed_at=proof.verified_at,
            proof_recorded_at=persisted_coverage.recorded_at,
            lease_policy_version=policy_version,
            lease_issued_at=persisted_coverage.recorded_at,
            lease_ttl_microseconds=_timedelta_microseconds(ttl),
            lease_expires_at=expires_at,
        )
    except (TypeError, ValueError):
        return None


def _portfolio_coverage_status(
    status: SecurityDisclosureListingCoverageStatus,
) -> TransitionPlanEventCoverageStatus:
    """Convert Data Center result states without promoting incomplete evidence."""

    if status is SecurityDisclosureListingCoverageStatus.COMPLETE:
        return TransitionPlanEventCoverageStatus.COMPLETE
    if status is SecurityDisclosureListingCoverageStatus.PARTIAL:
        return TransitionPlanEventCoverageStatus.PARTIAL
    if status is SecurityDisclosureListingCoverageStatus.UNKNOWN:
        return TransitionPlanEventCoverageStatus.UNKNOWN
    return TransitionPlanEventCoverageStatus.MISSING


def _events_match_listed_entries(
    events: tuple[PersistedSecurityDisclosureEvent, ...],
    persisted: PersistedSecurityDisclosureListingCoverage,
) -> bool:
    """Check that returned events retain each listing's date-precision identity."""

    entries_by_document_id = {entry.source_document_id: entry for entry in persisted.proof.entries}
    return all(
        item.event.source_url == entries_by_document_id[item.event.source_event_id].source_url
        and type(item.event.announced_at) is date
        and item.event.announced_at
        == entries_by_document_id[item.event.source_event_id].published_on
        for item in events
    )


def _timedelta_microseconds(value: timedelta) -> int:
    """Convert a duration exactly without float rounding."""

    return ((value.days * 86_400 + value.seconds) * 1_000_000) + value.microseconds


__all__ = [
    "DataCenterTransitionPlanEventSnapshotReader",
    "translate_persisted_listing_coverage_to_scope",
]
