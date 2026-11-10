"""Fail-closed tests for exact retained event coverage pins and leases."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest

from apps.portfolio.application.transition_plan_event_review import (
    TransitionPlanEventSnapshotReadRequest,
)
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventAssetSnapshot,
    TransitionPlanEventCoverageLeasePolicy,
    TransitionPlanEventCoverageStatus,
    TransitionPlanEventRevision,
    transition_plan_event_revision_sha256,
)
from apps.portfolio.domain.transition_plan_revision import TransitionPlanRevision
from apps.simulated_trading.application.rebalance_journey_event_coverage import (
    PinRebalanceJourneyEventCoverage,
    RebalanceJourneyEventCoverageScope,
    RebalanceJourneyEventCoverageScopeSelection,
)
from apps.simulated_trading.application.rebalance_journey_event_refresh import (
    RebalanceJourneyOfficialEventRefreshReceipt,
)
from apps.simulated_trading.application.rebalance_journey_event_request_scope import (
    RebalanceJourneyEventRequestScope,
)
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable

_AS_OF = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
_ASSET = "600000.SH"
_SECURITY = "SSE:600000"
_START = date(2026, 10, 1)
_END = date(2026, 11, 5)
_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


def _scope(
    *,
    source_id: str = "official-szse",
    proof_recorded_at: datetime = _AS_OF - timedelta(seconds=30),
    lease_issued_at: datetime = _AS_OF - timedelta(seconds=20),
    ttl: timedelta = timedelta(seconds=30),
    start_on: date = _START,
    end_on: date = _END,
    lease_policy_version: str = "lease-r1",
) -> RebalanceJourneyEventCoverageScope:
    """Create one explicit source scope and already-issued lease from retained evidence."""

    return RebalanceJourneyEventCoverageScope(
        asset_code=_ASSET,
        security_id=_SECURITY,
        source_id=source_id,
        start_on=start_on,
        end_on=end_on,
        first_observed_at=proof_recorded_at - timedelta(minutes=3),
        source_observed_at=proof_recorded_at - timedelta(seconds=10),
        proof_recorded_at=proof_recorded_at,
        lease_policy_version=lease_policy_version,
        lease_issued_at=lease_issued_at,
        lease_ttl_microseconds=_duration_microseconds(ttl),
        lease_expires_at=lease_issued_at + ttl,
    )


def _snapshot(
    scope: RebalanceJourneyEventCoverageScope,
    *,
    event: TransitionPlanEventRevision | None = None,
    as_of: datetime | None = None,
    start_on: date | None = None,
) -> TransitionPlanEventAssetSnapshot:
    """Build one complete proof whose exact recorded timestamp is not request time."""

    proof_at = scope.proof_recorded_at if as_of is None else as_of
    return TransitionPlanEventAssetSnapshot(
        asset_code=scope.asset_code,
        security_id=scope.security_id,
        source_id=scope.source_id,
        start_on=scope.start_on if start_on is None else start_on,
        end_on=scope.end_on,
        as_of=proof_at,
        first_observed_at=scope.first_observed_at,
        source_observed_at=scope.source_observed_at,
        proof_recorded_at=proof_at,
        coverage_status=TransitionPlanEventCoverageStatus.COMPLETE,
        source_scope_sha256=_HASH_A,
        events=() if event is None else (event,),
    )


def _event(
    *,
    source_id: str = "official-szse",
    source_revision_id: str = "revision-1",
    body_sha256: str = _HASH_B,
    event_type: str = "OTHER",
) -> TransitionPlanEventRevision:
    """Build a retained event with older publication and knowledge clocks."""

    known = _AS_OF - timedelta(hours=2)
    return TransitionPlanEventRevision(
        asset_code=_ASSET,
        security_id=_SECURITY,
        source_id=source_id,
        source_event_id="szse-event-1",
        source_revision_id=source_revision_id,
        event_type=event_type,
        announced_at=_AS_OF.date() - timedelta(days=2),
        available_at=known - timedelta(minutes=1),
        known_at=known,
        effective_at=None,
        body_sha256=body_sha256,
        manifest_sha256=_HASH_C,
    )


class _Scopes:
    """Return a fixed closed-world scope collection."""

    def __init__(
        self,
        scopes: (
            tuple[RebalanceJourneyEventCoverageScope, ...]
            | RebalanceJourneyEventCoverageScopeSelection
            | None
        ),
    ) -> None:
        self.scopes = scopes
        self.request_scopes: list[RebalanceJourneyEventRequestScope] = []
        self.refresh_receipts: list[RebalanceJourneyOfficialEventRefreshReceipt | None] = []

    def read_scopes(
        self,
        *,
        asset_identities: tuple[tuple[str, str], ...],
        request_scope: RebalanceJourneyEventRequestScope,
        as_of: datetime,
        refresh_receipt: RebalanceJourneyOfficialEventRefreshReceipt | None = None,
    ) -> (
        tuple[RebalanceJourneyEventCoverageScope, ...]
        | RebalanceJourneyEventCoverageScopeSelection
        | None
    ):
        assert asset_identities == ((_ASSET, _SECURITY),)
        assert as_of >= _AS_OF
        assert type(request_scope) is RebalanceJourneyEventRequestScope
        self.request_scopes.append(request_scope)
        self.refresh_receipts.append(refresh_receipt)
        return self.scopes


class _Snapshots:
    """Return snapshots by exact source/window/proof cutoff and retain requests."""

    def __init__(self, snapshots: tuple[TransitionPlanEventAssetSnapshot, ...]) -> None:
        self.snapshots = {
            (item.source_id, item.start_on, item.end_on, item.as_of): item for item in snapshots
        }
        self.requests: list[TransitionPlanEventSnapshotReadRequest] = []

    def read_snapshot(
        self, request: TransitionPlanEventSnapshotReadRequest
    ) -> TransitionPlanEventAssetSnapshot | None:
        self.requests.append(request)
        return self.snapshots.get(
            (request.source_id, request.start_on, request.end_on, request.as_of)
        )


def _policy(
    *, version: str = "lease-r1", ttl: timedelta = timedelta(seconds=30)
) -> TransitionPlanEventCoverageLeasePolicy:
    """Supply the explicitly injected versioned lease and maximum bound."""

    return TransitionPlanEventCoverageLeasePolicy(
        policy_version=version,
        ttl=ttl,
        maximum_ttl=timedelta(seconds=60),
    )


def _request_scope() -> RebalanceJourneyEventRequestScope:
    """Supply one exact authenticated actor/account/owner scope for the tests."""

    return RebalanceJourneyEventRequestScope(
        actor_user_id=41,
        account_id=52,
        owner_user_id=63,
    )


def _pinner(
    scopes: tuple[RebalanceJourneyEventCoverageScope, ...] | None,
    snapshots: tuple[TransitionPlanEventAssetSnapshot, ...],
    *,
    policy: TransitionPlanEventCoverageLeasePolicy | None = None,
) -> tuple[PinRebalanceJourneyEventCoverage, _Snapshots]:
    """Compose the pure pinning use case from exact synthetic read contracts."""

    reader = _Snapshots(snapshots)
    return (
        PinRebalanceJourneyEventCoverage(
            scope_reader=_Scopes(scopes),
            snapshot_reader=reader,
            lease_policy=_policy() if policy is None else policy,
        ),
        reader,
    )


def _duration_microseconds(value: timedelta) -> int:
    return (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds


def test_pin_uses_exact_proof_cutoff_and_keeps_refresh_lease_and_plan_clocks_distinct() -> None:
    """The latest listing verification is not substituted for older event knowledge."""

    scope = _scope()
    event = _event()
    snapshot = _snapshot(scope, event=event)
    pinner, reader = _pinner((scope,), (snapshot,))

    bindings = pinner.pin(
        asset_identities=((_ASSET, _SECURITY),),
        request_scope=_request_scope(),
        as_of=_AS_OF,
        parent=None,
    )

    coverage = next(item for item in bindings if item.source_record_id == "__coverage__")
    event_binding = next(
        item for item in bindings if item.source_record_id == event.source_event_id
    )
    assert reader.requests == [
        TransitionPlanEventSnapshotReadRequest(
            asset_code=_ASSET,
            security_id=_SECURITY,
            source_id=scope.source_id,
            start_on=_START,
            end_on=_END,
            as_of=scope.proof_recorded_at,
        )
    ]
    assert coverage.source_first_observed_at == scope.first_observed_at
    assert coverage.observed_at == scope.source_observed_at
    assert coverage.known_at == scope.proof_recorded_at
    assert coverage.coverage_lease_issued_at == scope.lease_issued_at
    assert coverage.decision_cutoff == _AS_OF
    assert coverage.admission_until == scope.lease_expires_at
    assert event_binding.source_record_id == "szse-event-1"
    assert event_binding.observed_at == event.available_at
    assert event_binding.known_at == event.known_at
    assert event_binding.observed_at < event_binding.known_at
    assert event_binding.coverage_start_on == _START
    assert event_binding.coverage_end_on == _END
    assert event_binding.coverage_lease_issued_at is None
    assert event_binding.qualification_proof_hash == transition_plan_event_revision_sha256(event)


def test_pin_passes_request_account_and_owner_context_to_scope_reader() -> None:
    """The scope lookup must receive request identity rather than shared adapter state."""

    scope = _scope()
    captured_scopes: list[object] = []

    class RequestScopedReader:
        def read_scopes(
            self,
            *,
            asset_identities: tuple[tuple[str, str], ...],
            request_scope: object,
            as_of: datetime,
        ) -> tuple[RebalanceJourneyEventCoverageScope, ...]:
            assert asset_identities == ((_ASSET, _SECURITY),)
            assert as_of == _AS_OF
            captured_scopes.append(request_scope)
            return (scope,)

    pinner = PinRebalanceJourneyEventCoverage(
        scope_reader=RequestScopedReader(),
        snapshot_reader=_Snapshots((_snapshot(scope),)),
        lease_policy=_policy(),
    )
    request_scope = _request_scope()

    pinner.pin(
        asset_identities=((_ASSET, _SECURITY),),
        request_scope=request_scope,
        as_of=_AS_OF,
        parent=None,
    )

    assert captured_scopes == [request_scope]


def test_refresh_receipt_binds_fingerprint_but_pinner_still_reads_durable_proof() -> None:
    fingerprint = _HASH_C
    policy = _policy(version=fingerprint, ttl=timedelta(seconds=30))
    receipt = RebalanceJourneyOfficialEventRefreshReceipt(
        request_scope=_request_scope(),
        asset_pairs=((_ASSET, _SECURITY),),
        source_id="szse_official",
        start_on=_START,
        end_on=_END,
        policy_fingerprint=fingerprint,
        lease_policy=policy,
    )
    scope = _scope(
        source_id="szse_official",
        lease_policy_version=fingerprint,
        ttl=policy.ttl,
    )
    snapshots = _Snapshots((_snapshot(scope),))
    scopes = _Scopes(
        RebalanceJourneyEventCoverageScopeSelection(
            scopes=(scope,),
            policy_fingerprint=fingerprint,
            lease_policy=policy,
        )
    )
    pinner = PinRebalanceJourneyEventCoverage(
        scope_reader=scopes,
        snapshot_reader=snapshots,
        lease_policy=None,
    )

    bindings = pinner.pin(
        asset_identities=((_ASSET, _SECURITY),),
        request_scope=_request_scope(),
        as_of=_AS_OF,
        parent=None,
        refresh_receipt=receipt,
    )

    coverage_binding = next(item for item in bindings if item.source_record_id == "__coverage__")
    assert coverage_binding.coverage_policy_version == fingerprint
    assert scopes.refresh_receipts == [receipt]
    assert snapshots.requests == [
        TransitionPlanEventSnapshotReadRequest(
            asset_code=_ASSET,
            security_id=_SECURITY,
            source_id="szse_official",
            start_on=_START,
            end_on=_END,
            as_of=scope.proof_recorded_at,
        )
    ]
    assert not hasattr(receipt, "proof_recorded_at")


def test_pinner_blocks_policy_fingerprint_change_before_durable_reread() -> None:
    fingerprint = _HASH_C
    policy = _policy(version=fingerprint, ttl=timedelta(seconds=30))
    receipt = RebalanceJourneyOfficialEventRefreshReceipt(
        request_scope=_request_scope(),
        asset_pairs=((_ASSET, _SECURITY),),
        source_id="szse_official",
        start_on=_START,
        end_on=_END,
        policy_fingerprint=fingerprint,
        lease_policy=policy,
    )
    scope = _scope(
        source_id="szse_official",
        lease_policy_version=_HASH_B,
        ttl=policy.ttl,
    )
    snapshots = _Snapshots((_snapshot(scope),))
    pinner = PinRebalanceJourneyEventCoverage(
        scope_reader=_Scopes(
            RebalanceJourneyEventCoverageScopeSelection(
                scopes=(scope,),
                policy_fingerprint=_HASH_B,
                lease_policy=_policy(version=_HASH_B, ttl=policy.ttl),
            )
        ),
        snapshot_reader=snapshots,
        lease_policy=None,
    )

    with pytest.raises(RebalanceJourneyUnavailable):
        pinner.pin(
            asset_identities=((_ASSET, _SECURITY),),
            request_scope=_request_scope(),
            as_of=_AS_OF,
            parent=None,
            refresh_receipt=receipt,
        )

    assert snapshots.requests == []


@pytest.mark.parametrize(
    "snapshot_change",
    ("wrong_window", "wrong_proof_time", "unknown_event"),
)
def test_pin_blocks_incomplete_or_mismatched_exact_proof(snapshot_change: str) -> None:
    """Wrong window, proof clock or UNKNOWN event cannot become a successful pin."""

    scope = _scope()
    if snapshot_change == "wrong_window":
        snapshot = _snapshot(scope, start_on=date(2026, 9, 30))
    elif snapshot_change == "wrong_proof_time":
        snapshot = _snapshot(scope, as_of=scope.proof_recorded_at - timedelta(seconds=1))
    else:
        snapshot = _snapshot(scope, event=_event(event_type="UNKNOWN"))
    pinner, _reader = _pinner((scope,), (snapshot,))

    with pytest.raises(RebalanceJourneyUnavailable):
        pinner.pin(
            asset_identities=((_ASSET, _SECURITY),),
            request_scope=_request_scope(),
            as_of=_AS_OF,
            parent=None,
        )


def test_pin_blocks_expired_persisted_lease_and_missing_versioned_policy() -> None:
    """A stale scope lease or absent policy cannot be replaced by an in-memory default."""

    expired_scope = _scope(
        proof_recorded_at=_AS_OF - timedelta(seconds=10),
        lease_issued_at=_AS_OF - timedelta(seconds=5),
        ttl=timedelta(seconds=3),
    )
    expired_snapshot = _snapshot(expired_scope)
    pinner, _reader = _pinner(
        (expired_scope,), (expired_snapshot,), policy=_policy(ttl=timedelta(seconds=3))
    )
    with pytest.raises(RebalanceJourneyUnavailable):
        pinner.pin(
            asset_identities=((_ASSET, _SECURITY),),
            request_scope=_request_scope(),
            as_of=_AS_OF,
            parent=None,
        )

    scope = _scope()
    no_policy = PinRebalanceJourneyEventCoverage(
        scope_reader=_Scopes((scope,)),
        snapshot_reader=_Snapshots((_snapshot(scope),)),
        lease_policy=None,
    )
    with pytest.raises(RebalanceJourneyUnavailable):
        no_policy.pin(
            asset_identities=((_ASSET, _SECURITY),),
            request_scope=_request_scope(),
            as_of=_AS_OF,
            parent=None,
        )


def test_pin_allows_multiple_sources_for_one_asset_without_aliasing_scope_identity() -> None:
    """The source id remains part of each exact per-window pin identity."""

    first = _scope(source_id="official-szse")
    second = _scope(source_id="official-sse")
    snapshots = (
        _snapshot(first, event=_event(source_id=first.source_id)),
        _snapshot(second, event=_event(source_id=second.source_id)),
    )
    pinner, _reader = _pinner((first, second), snapshots)

    bindings = pinner.pin(
        asset_identities=((_ASSET, _SECURITY),),
        request_scope=_request_scope(),
        as_of=_AS_OF,
        parent=None,
    )

    coverage = [item for item in bindings if item.source_record_id == "__coverage__"]
    assert {
        (item.source_id, item.coverage_start_on, item.coverage_end_on) for item in coverage
    } == {
        ("official-szse", _START, _END),
        ("official-sse", _START, _END),
    }


def test_successor_uses_new_proof_even_when_parent_lease_expired_and_event_was_corrected() -> None:
    """New source proof forms a new immutable revision instead of freezing successors."""

    old_scope = _scope()
    old_snapshot = _snapshot(old_scope, event=_event(source_revision_id="r1"))
    first_pinner, _reader = _pinner((old_scope,), (old_snapshot,))
    old_bindings = first_pinner.pin(
        asset_identities=((_ASSET, _SECURITY),),
        request_scope=_request_scope(),
        as_of=_AS_OF,
        parent=None,
    )
    parent = cast(
        TransitionPlanRevision,
        SimpleNamespace(basis=SimpleNamespace(source_bindings=old_bindings)),
    )

    next_at = _AS_OF + timedelta(minutes=2)
    next_scope = _scope(
        proof_recorded_at=next_at - timedelta(seconds=20),
        lease_issued_at=next_at - timedelta(seconds=10),
    )
    next_snapshot = _snapshot(
        next_scope, event=_event(source_revision_id="r2", body_sha256=_HASH_C)
    )
    next_pinner, _reader = _pinner((next_scope,), (next_snapshot,))

    successor_bindings = next_pinner.pin(
        asset_identities=((_ASSET, _SECURITY),),
        request_scope=_request_scope(),
        as_of=next_at,
        parent=parent,
    )

    assert (
        next(
            item for item in successor_bindings if item.source_record_id == "szse-event-1"
        ).qualification_proof_hash
        != next(
            item for item in old_bindings if item.source_record_id == "szse-event-1"
        ).qualification_proof_hash
    )


def test_successor_can_upgrade_legacy_parent_but_rejects_legacy_event_marker() -> None:
    """A pre-pin M1 parent can gain fresh proof; malformed old event pins stay blocked."""

    scope = _scope()
    pinner, _reader = _pinner((scope,), (_snapshot(scope),))
    legacy_parent = cast(
        TransitionPlanRevision,
        SimpleNamespace(basis=SimpleNamespace(source_bindings=())),
    )

    upgraded = pinner.pin(
        asset_identities=((_ASSET, _SECURITY),),
        request_scope=_request_scope(),
        as_of=_AS_OF,
        parent=legacy_parent,
    )
    assert any(item.source_record_id == "__coverage__" for item in upgraded)

    good_marker = next(item for item in upgraded if item.source_record_id == "__coverage__")
    bad_marker = replace(
        good_marker,
        coverage_start_on=None,
        coverage_end_on=None,
        coverage_policy_version=None,
        coverage_lease_issued_at=None,
        coverage_lease_ttl_microseconds=None,
        source_first_observed_at=None,
    )
    malformed_parent = cast(
        TransitionPlanRevision,
        SimpleNamespace(basis=SimpleNamespace(source_bindings=(bad_marker,))),
    )
    with pytest.raises(RebalanceJourneyUnavailable):
        pinner.pin(
            asset_identities=((_ASSET, _SECURITY),),
            request_scope=_request_scope(),
            as_of=_AS_OF,
            parent=malformed_parent,
        )
