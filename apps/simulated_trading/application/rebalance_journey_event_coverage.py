"""Pin exact retained disclosure coverage and event revisions for a plan."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

from apps.portfolio.application.transition_plan_event_review import (
    TransitionPlanEventSnapshotReader,
    TransitionPlanEventSnapshotReadRequest,
)
from apps.portfolio.domain.transition_plan_event_review import (
    SECURITY_DISCLOSURE_EVENT_COVERAGE_RECORD_ID,
    SECURITY_DISCLOSURE_EVENT_SOURCE_KIND,
    TransitionPlanEventAssetSnapshot,
    TransitionPlanEventCoverageLeasePolicy,
    TransitionPlanEventCoverageStatus,
    has_transition_plan_event_bindings,
    transition_plan_event_coverage_bindings,
    transition_plan_event_revision_sha256,
    transition_plan_event_snapshot_sha256,
)
from apps.portfolio.domain.transition_plan_revision import TransitionPlanRevision
from apps.portfolio.domain.transition_plan_revision_basis import TransitionPlanSourceBinding
from apps.simulated_trading.application.rebalance_journey_event_request_scope import (
    RebalanceJourneyEventRequestScope,
)
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable


@dataclass(frozen=True, slots=True)
class RebalanceJourneyEventCoverageScope:
    """Exact source window and durable proof clock selected for one security."""

    asset_code: str
    security_id: str
    source_id: str
    start_on: date
    end_on: date
    first_observed_at: datetime
    source_observed_at: datetime
    proof_recorded_at: datetime
    lease_policy_version: str
    lease_issued_at: datetime
    lease_ttl_microseconds: int
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        """Reject aliases, malformed windows, and naive proof timestamps."""

        for name in ("asset_code", "security_id", "source_id"):
            value = getattr(self, name)
            if type(value) is not str or not value or value.strip() != value:
                raise ValueError(f"{name} must be a canonical non-empty token")
        if (
            type(self.start_on) is not date
            or type(self.start_on) is datetime
            or type(self.end_on) is not date
            or type(self.end_on) is datetime
            or self.start_on > self.end_on
        ):
            raise ValueError("event coverage scope requires an ordered exact date window")
        for name in ("first_observed_at", "source_observed_at", "proof_recorded_at"):
            value = getattr(self, name)
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if type(self.lease_policy_version) is not str or not self.lease_policy_version:
            raise ValueError("lease_policy_version must be a non-empty version token")
        for name in ("lease_issued_at", "lease_expires_at"):
            value = getattr(self, name)
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if (
            type(self.lease_ttl_microseconds) is not int
            or self.lease_ttl_microseconds <= 0
            or self.lease_ttl_microseconds > timedelta.max // timedelta(microseconds=1)
        ):
            raise ValueError("lease_ttl_microseconds must be a bounded positive integer")
        try:
            expected_expiry = self.lease_issued_at + timedelta(
                microseconds=self.lease_ttl_microseconds
            )
        except OverflowError as error:
            raise ValueError("lease expiry exceeds the datetime range") from error
        if (
            expected_expiry != self.lease_expires_at
            or self.first_observed_at > self.source_observed_at
            or self.source_observed_at > self.proof_recorded_at
            or self.proof_recorded_at > self.lease_issued_at
        ):
            raise ValueError("coverage lease must follow its proof and match its exact expiry")


class RebalanceJourneyEventCoverageScopeReader(Protocol):
    """Select exact retained source windows and their durable proof cutoffs."""

    def read_scopes(
        self,
        *,
        asset_identities: tuple[tuple[str, str], ...],
        request_scope: RebalanceJourneyEventRequestScope,
        as_of: datetime,
    ) -> tuple[RebalanceJourneyEventCoverageScope, ...] | None:
        """Return every exact source window or None when closed-world scope is unavailable."""
        ...


class RebalanceJourneyEventCoveragePinner(Protocol):
    """Create exact event bindings before any plan content hashes or basis construction."""

    def pin(
        self,
        *,
        asset_identities: tuple[tuple[str, str], ...],
        request_scope: RebalanceJourneyEventRequestScope,
        as_of: datetime,
        parent: TransitionPlanRevision | None,
    ) -> tuple[TransitionPlanSourceBinding, ...]:
        """Fail closed unless every required event scope has complete durable proof."""
        ...


class PinRebalanceJourneyEventCoverage:
    """Build source bindings from injected exact-scope and read-only proof providers."""

    def __init__(
        self,
        *,
        scope_reader: RebalanceJourneyEventCoverageScopeReader | None,
        snapshot_reader: TransitionPlanEventSnapshotReader | None,
        lease_policy: TransitionPlanEventCoverageLeasePolicy | None,
    ) -> None:
        """Retain required providers; there are no implicit source or lease defaults."""

        self._scope_reader = scope_reader
        self._snapshot_reader = snapshot_reader
        self._lease_policy = lease_policy

    def pin(
        self,
        *,
        asset_identities: tuple[tuple[str, str], ...],
        request_scope: RebalanceJourneyEventRequestScope,
        as_of: datetime,
        parent: TransitionPlanRevision | None,
    ) -> tuple[TransitionPlanSourceBinding, ...]:
        """Pin all exact security/source/windows before downstream hashing or persistence."""

        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_CUTOFF_INVALID")
        if type(request_scope) is not RebalanceJourneyEventRequestScope:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_REQUEST_SCOPE_INVALID")
        if self._scope_reader is None or self._snapshot_reader is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_PROVIDER_UNAVAILABLE")
        if self._lease_policy is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_LEASE_POLICY_UNAVAILABLE")
        identities = _validated_identities(asset_identities)
        scopes = self._scope_reader.read_scopes(
            asset_identities=identities,
            request_scope=request_scope,
            as_of=as_of,
        )
        if type(scopes) is not tuple or not scopes:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_SCOPE_UNAVAILABLE")
        if any(type(scope) is not RebalanceJourneyEventCoverageScope for scope in scopes):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_SCOPE_INVALID")
        ordered_scopes = tuple(sorted(scopes, key=_scope_sort_key))
        scope_keys = tuple(_scope_key(scope) for scope in ordered_scopes)
        if len(scope_keys) != len(set(scope_keys)):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_SCOPE_AMBIGUOUS")
        expected_identities = set(identities)
        if any(
            (scope.asset_code, scope.security_id) not in expected_identities
            or scope.proof_recorded_at > as_of
            or scope.lease_policy_version != self._lease_policy.policy_version
            or scope.lease_ttl_microseconds != _timedelta_microseconds(self._lease_policy.ttl)
            or timedelta(microseconds=scope.lease_ttl_microseconds) > self._lease_policy.maximum_ttl
            or scope.lease_issued_at < scope.proof_recorded_at
            or scope.lease_issued_at > as_of
            or scope.lease_expires_at <= as_of
            for scope in ordered_scopes
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_SCOPE_MISMATCH")
        if {
            (scope.asset_code, scope.security_id) for scope in ordered_scopes
        } != expected_identities:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_SCOPE_INCOMPLETE")

        snapshots = tuple(self._read_exact_scope(scope) for scope in ordered_scopes)
        self._validate_parent(parent)

        output: list[TransitionPlanSourceBinding] = []
        for scope, snapshot in zip(ordered_scopes, snapshots, strict=True):
            output.extend(
                _bindings_for_scope(
                    scope=scope,
                    snapshot=snapshot,
                    policy=self._lease_policy,
                    decision_cutoff=as_of,
                )
            )
        return tuple(output)

    def _read_exact_scope(
        self, scope: RebalanceJourneyEventCoverageScope
    ) -> TransitionPlanEventAssetSnapshot:
        """Read only a durable proof at its exact recorded knowledge timestamp."""

        if self._snapshot_reader is None:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_PROVIDER_UNAVAILABLE")
        snapshot = self._snapshot_reader.read_snapshot(
            TransitionPlanEventSnapshotReadRequest(
                asset_code=scope.asset_code,
                security_id=scope.security_id,
                source_id=scope.source_id,
                start_on=scope.start_on,
                end_on=scope.end_on,
                as_of=scope.proof_recorded_at,
            )
        )
        if type(snapshot) is not TransitionPlanEventAssetSnapshot:
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_PROOF_INVALID")
        if (
            snapshot.asset_code != scope.asset_code
            or snapshot.security_id != scope.security_id
            or snapshot.source_id != scope.source_id
            or snapshot.start_on != scope.start_on
            or snapshot.end_on != scope.end_on
            or snapshot.as_of != scope.proof_recorded_at
            or snapshot.proof_recorded_at != scope.proof_recorded_at
            or snapshot.first_observed_at != scope.first_observed_at
            or snapshot.source_observed_at != scope.source_observed_at
            or snapshot.coverage_status is not TransitionPlanEventCoverageStatus.COMPLETE
            or snapshot.source_scope_sha256 is None
            or any(event.event_type.upper() == "UNKNOWN" for event in snapshot.events)
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_PROOF_INCOMPLETE")
        return snapshot

    def _validate_parent(
        self,
        parent: TransitionPlanRevision | None,
    ) -> None:
        """Allow pre-pin parent upgrades and reject structurally incomplete event markers."""

        if parent is None:
            return
        bindings = parent.basis.source_bindings
        if not has_transition_plan_event_bindings(bindings):
            return
        previous = transition_plan_event_coverage_bindings(bindings)
        if not previous or any(
            item.coverage_start_on is None
            or item.coverage_end_on is None
            or item.coverage_policy_version is None
            or item.coverage_lease_issued_at is None
            or item.coverage_lease_ttl_microseconds is None
            for item in previous
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_PARENT_PIN_AMBIGUOUS")


def _bindings_for_scope(
    *,
    scope: RebalanceJourneyEventCoverageScope,
    snapshot: TransitionPlanEventAssetSnapshot,
    policy: TransitionPlanEventCoverageLeasePolicy,
    decision_cutoff: datetime,
) -> tuple[TransitionPlanSourceBinding, ...]:
    """Build one explicit window pin plus every source revision pin in its proof."""

    if type(snapshot) is not TransitionPlanEventAssetSnapshot:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_PROOF_INVALID")
    ttl_microseconds = _timedelta_microseconds(policy.ttl)
    coverage_hash = transition_plan_event_snapshot_sha256(snapshot)
    coverage = TransitionPlanSourceBinding(
        kind=SECURITY_DISCLOSURE_EVENT_SOURCE_KIND,
        asset_code=scope.asset_code,
        security_id=scope.security_id,
        source_id=scope.source_id,
        source_record_id=SECURITY_DISCLOSURE_EVENT_COVERAGE_RECORD_ID,
        manifest_sha256=snapshot.source_scope_sha256 or "",
        body_sha256=coverage_hash,
        observation_precision="timestamp",
        observed_at=snapshot.source_observed_at,
        observed_on=None,
        available_at=snapshot.proof_recorded_at,
        known_at=snapshot.proof_recorded_at,
        decision_cutoff=decision_cutoff,
        decision_date_cutoff=None,
        source_valid_until=None,
        admission_until=scope.lease_expires_at,
        qualification_proof_hash=_proof_hash(
            {
                "scope_hash": snapshot.source_scope_sha256,
                "coverage_hash": coverage_hash,
                "observed_at": snapshot.source_observed_at.isoformat(),
                "first_observed_at": snapshot.first_observed_at.isoformat(),
                "proof_recorded_at": snapshot.proof_recorded_at.isoformat(),
                "decision_cutoff": decision_cutoff.isoformat(),
                "lease_issued_at": scope.lease_issued_at.isoformat(),
                "lease_until": scope.lease_expires_at.isoformat(),
                "policy_version": policy.policy_version,
                "ttl_microseconds": ttl_microseconds,
            }
        ),
        source_purpose="official_disclosure_event_coverage",
        requested_purpose="transition_plan",
        allowed_purposes=("transition_plan",),
        restrictions=(),
        coverage_status="complete",
        qualified=True,
        coverage_start_on=scope.start_on,
        coverage_end_on=scope.end_on,
        coverage_policy_version=policy.policy_version,
        coverage_lease_issued_at=scope.lease_issued_at,
        coverage_lease_ttl_microseconds=ttl_microseconds,
        source_first_observed_at=snapshot.first_observed_at,
    )
    event_bindings = tuple(
        TransitionPlanSourceBinding(
            kind=SECURITY_DISCLOSURE_EVENT_SOURCE_KIND,
            asset_code=event.asset_code,
            security_id=event.security_id,
            source_id=event.source_id,
            source_record_id=event.source_event_id,
            manifest_sha256=event.manifest_sha256,
            body_sha256=event.body_sha256,
            observation_precision="timestamp",
            observed_at=event.available_at,
            observed_on=None,
            available_at=event.available_at,
            known_at=event.known_at,
            decision_cutoff=decision_cutoff,
            decision_date_cutoff=None,
            source_valid_until=None,
            admission_until=scope.lease_expires_at,
            qualification_proof_hash=transition_plan_event_revision_sha256(event),
            source_purpose="official_exchange_disclosure",
            requested_purpose="transition_plan",
            allowed_purposes=("transition_plan",),
            restrictions=(),
            coverage_status="complete",
            qualified=True,
            coverage_start_on=scope.start_on,
            coverage_end_on=scope.end_on,
        )
        for event in sorted(snapshot.events, key=lambda item: item.source_event_id)
    )
    return (coverage, *event_bindings)


def _validated_identities(
    values: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """Require sorted unique exact asset/security identity pairs."""

    if type(values) is not tuple or not values:
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_ASSETS_UNAVAILABLE")
    for pair in values:
        if (
            type(pair) is not tuple
            or len(pair) != 2
            or any(type(item) is not str or not item or item.strip() != item for item in pair)
        ):
            raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_ASSETS_INVALID")
    if len(values) != len(set(values)):
        raise RebalanceJourneyUnavailable(code="REBALANCE_PLAN_EVENT_ASSETS_AMBIGUOUS")
    return tuple(sorted(values))


def _scope_key(scope: RebalanceJourneyEventCoverageScope) -> tuple[str, str, str, date, date]:
    """Return the full registered exact source-window identity."""

    return (scope.asset_code, scope.security_id, scope.source_id, scope.start_on, scope.end_on)


def _scope_sort_key(
    scope: RebalanceJourneyEventCoverageScope,
) -> tuple[str, str, str, date, date, datetime]:
    """Provide deterministic ordering independent of repository row order."""

    return (*_scope_key(scope), scope.proof_recorded_at)


def _timedelta_microseconds(value: timedelta) -> int:
    """Convert an injected bounded duration without floating-point rounding."""

    return ((value.days * 86_400 + value.seconds) * 1_000_000) + value.microseconds


def _proof_hash(payload: dict[str, object]) -> str:
    """Hash the exact source clocks and lease identity as one deterministic proof."""

    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "PinRebalanceJourneyEventCoverage",
    "RebalanceJourneyEventCoveragePinner",
    "RebalanceJourneyEventCoverageScope",
    "RebalanceJourneyEventCoverageScopeReader",
]
