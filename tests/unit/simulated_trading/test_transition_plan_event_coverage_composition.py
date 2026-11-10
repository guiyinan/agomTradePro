"""Fail-closed tests for request-scoped official event scope selection."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from apps.portfolio.application.transition_plan_event_review import (
    TransitionPlanEventSnapshotReadRequest,
    TransitionPlanEventSourceRevisionChanged,
)
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventAssetSnapshot,
    TransitionPlanEventCoverageLeasePolicy,
    TransitionPlanEventCoverageStatus,
)
from apps.simulated_trading.application.rebalance_journey_event_coverage import (
    PinRebalanceJourneyEventCoverage,
)
from apps.simulated_trading.application.rebalance_journey_event_refresh import (
    RebalanceJourneyOfficialEventRefreshReceipt,
)
from apps.simulated_trading.application.rebalance_journey_event_request_scope import (
    RebalanceJourneyEventRequestScope,
)
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyUnavailable
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    QualifiedExchangeTimezone,
    VerifiedSimulatedAccountOriginCalendar,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    TransitionPlanDisclosureRuntimePolicy,
)
from apps.simulated_trading.transition_plan_event_coverage_composition import (
    ConfiguredRebalanceJourneyEventCoverageScopeReader,
)
from apps.simulated_trading.transition_plan_official_disclosure_source import (
    transition_plan_disclosure_fingerprint,
)

_AS_OF = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
_PROOF_AT = _AS_OF - timedelta(seconds=10)
_REQUEST_SCOPE = RebalanceJourneyEventRequestScope(
    actor_user_id=9,
    account_id=12,
    owner_user_id=9,
)
_ASSET_PAIR = ("002727.SZ", "SZSE:002727")
_ASSET_PAIRS = (_ASSET_PAIR,)
_WINDOW_START = date(2026, 10, 1)
_WINDOW_END = date(2026, 11, 11)
_HASH = "a" * 64


class _OriginReader:
    def __init__(self, calendar: VerifiedSimulatedAccountOriginCalendar) -> None:
        self.calendar = calendar
        self.calls: list[tuple[int, int, str, datetime]] = []

    def read_verified_zero_origin_calendar(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        exchange: str,
        as_of: datetime,
    ) -> VerifiedSimulatedAccountOriginCalendar:
        self.calls.append((account_id, owner_user_id, exchange, as_of))
        return replace(self.calendar, as_of=as_of)


class _PolicyReader:
    def __init__(self, policy: TransitionPlanDisclosureRuntimePolicy | None) -> None:
        self.policy = policy
        self.calls: list[tuple[date, date, datetime]] = []

    def read_policy(
        self,
        *,
        decision_on: date,
        earliest_required_on: date,
        as_of: datetime,
    ) -> TransitionPlanDisclosureRuntimePolicy | None:
        self.calls.append((decision_on, earliest_required_on, as_of))
        if self.policy is None:
            return None
        return replace(self.policy, read_at=as_of)


class _SnapshotReader:
    def __init__(
        self,
        latest: TransitionPlanEventAssetSnapshot | None,
        *,
        late_change: bool = False,
    ) -> None:
        self.latest = latest
        self.late_change = late_change
        self.latest_requests: list[TransitionPlanEventSnapshotReadRequest] = []
        self.exact_requests: list[TransitionPlanEventSnapshotReadRequest] = []

    def read_latest_snapshot(
        self, request: TransitionPlanEventSnapshotReadRequest
    ) -> TransitionPlanEventAssetSnapshot | None:
        self.latest_requests.append(request)
        if self.late_change and self.latest is not None:
            raise TransitionPlanEventSourceRevisionChanged(
                self.latest, "event revision was appended after the captured proof"
            )
        return self.latest

    def read_snapshot(
        self, request: TransitionPlanEventSnapshotReadRequest
    ) -> TransitionPlanEventAssetSnapshot | None:
        self.exact_requests.append(request)
        if self.latest is None or request.as_of != self.latest.proof_recorded_at:
            return None
        return self.latest


def _calendar(
    *,
    decision_on: date = _WINDOW_END,
    timezone_policy_id: str = "szse-zone-v1",
    timezone_policy_hash: str = _HASH,
) -> VerifiedSimulatedAccountOriginCalendar:
    return VerifiedSimulatedAccountOriginCalendar(
        origin_on=_WINDOW_START,
        decision_on=decision_on,
        timezone_policy=QualifiedExchangeTimezone(
            exchange="SZSE",
            timezone_name="Asia/Shanghai",
            policy_id=timezone_policy_id,
            policy_sha256=timezone_policy_hash,
        ),
        as_of=_AS_OF,
    )


def _policy(
    *,
    end_on: date = _WINDOW_END,
    profile_content_hash: str = "b" * 64,
    snapshot_id: str = "snapshot-1",
) -> TransitionPlanDisclosureRuntimePolicy:
    return TransitionPlanDisclosureRuntimePolicy(
        source_id="szse_official",
        start_on=_WINDOW_START,
        end_on=end_on,
        body_store_root=Path.cwd() / "official-pdf-test-store",
        lease_policy=TransitionPlanEventCoverageLeasePolicy(
            policy_version="configured-window-v1",
            ttl=timedelta(seconds=60),
            maximum_ttl=timedelta(seconds=60),
        ),
        policy_version="configured-window-v1",
        runtime_environment="development",
        profile_id="profile-1",
        profile_key="profile-key",
        profile_version=1,
        profile_content_hash=profile_content_hash,
        snapshot_id=snapshot_id,
        snapshot_content_hash="c" * 64,
        known_at=_AS_OF - timedelta(days=1),
        effective_at=_AS_OF - timedelta(hours=1),
        read_at=_AS_OF,
        policy_content_hash="d" * 64,
    )


def _snapshot(
    *,
    proof_at: datetime = _PROOF_AT,
    coverage_status: TransitionPlanEventCoverageStatus = TransitionPlanEventCoverageStatus.COMPLETE,
) -> TransitionPlanEventAssetSnapshot:
    return TransitionPlanEventAssetSnapshot(
        asset_code=_ASSET_PAIR[0],
        security_id=_ASSET_PAIR[1],
        source_id="szse_official",
        start_on=_WINDOW_START,
        end_on=_WINDOW_END,
        as_of=proof_at,
        first_observed_at=proof_at - timedelta(minutes=1),
        source_observed_at=proof_at - timedelta(seconds=1),
        proof_recorded_at=proof_at,
        coverage_status=coverage_status,
        source_scope_sha256=_HASH,
        events=(),
    )


def _receipt(
    *,
    calendar: VerifiedSimulatedAccountOriginCalendar | None = None,
    policy: TransitionPlanDisclosureRuntimePolicy | None = None,
) -> RebalanceJourneyOfficialEventRefreshReceipt:
    selected_calendar = _calendar() if calendar is None else calendar
    selected_policy = _policy() if policy is None else policy
    fingerprint = transition_plan_disclosure_fingerprint(
        request_scope=_REQUEST_SCOPE,
        calendar=selected_calendar,
        policy=selected_policy,
    )
    return RebalanceJourneyOfficialEventRefreshReceipt(
        request_scope=_REQUEST_SCOPE,
        asset_pairs=_ASSET_PAIRS,
        source_id="szse_official",
        start_on=selected_policy.start_on,
        end_on=selected_policy.end_on,
        policy_fingerprint=fingerprint,
        lease_policy=TransitionPlanEventCoverageLeasePolicy(
            policy_version=fingerprint,
            ttl=selected_policy.lease_policy.ttl,
            maximum_ttl=selected_policy.lease_policy.maximum_ttl,
        ),
    )


def _scope_reader(
    *,
    calendar: VerifiedSimulatedAccountOriginCalendar | None = None,
    policy: TransitionPlanDisclosureRuntimePolicy | None = None,
    snapshot_reader: _SnapshotReader,
) -> ConfiguredRebalanceJourneyEventCoverageScopeReader:
    return ConfiguredRebalanceJourneyEventCoverageScopeReader(
        origin_reader=_OriginReader(_calendar() if calendar is None else calendar),
        policy_reader=_PolicyReader(_policy() if policy is None else policy),
        snapshot_reader=snapshot_reader,
        runtime_environment="development",
    )


def test_scope_reader_uses_latest_proof_then_pinner_rereads_exact_durable_clock() -> None:
    snapshot_reader = _SnapshotReader(_snapshot())
    scope_reader = _scope_reader(snapshot_reader=snapshot_reader)
    receipt = _receipt()
    pinner = PinRebalanceJourneyEventCoverage(
        scope_reader=scope_reader,
        snapshot_reader=snapshot_reader,
        lease_policy=None,
    )

    bindings = pinner.pin(
        asset_identities=_ASSET_PAIRS,
        request_scope=_REQUEST_SCOPE,
        as_of=_AS_OF,
        parent=None,
        refresh_receipt=receipt,
    )

    assert snapshot_reader.latest_requests == [
        TransitionPlanEventSnapshotReadRequest(
            asset_code=_ASSET_PAIR[0],
            security_id=_ASSET_PAIR[1],
            source_id="szse_official",
            start_on=_WINDOW_START,
            end_on=_WINDOW_END,
            as_of=_AS_OF,
        )
    ]
    assert snapshot_reader.exact_requests == [
        replace(snapshot_reader.latest_requests[0], as_of=_PROOF_AT)
    ]
    coverage_pin = next(item for item in bindings if item.source_record_id == "__coverage__")
    assert coverage_pin.coverage_policy_version == receipt.policy_fingerprint
    assert coverage_pin.known_at == _PROOF_AT
    assert coverage_pin.coverage_lease_issued_at == _PROOF_AT


@pytest.mark.parametrize(
    "policy,calendar,as_of",
    [
        (replace(_policy(), snapshot_id="snapshot-2"), _calendar(), _AS_OF),
        (_policy(), _calendar(timezone_policy_id="szse-zone-v2"), _AS_OF),
        (
            _policy(end_on=date(2026, 11, 12)),
            _calendar(decision_on=date(2026, 11, 12)),
            _AS_OF + timedelta(days=1),
        ),
    ],
)
def test_scope_reader_blocks_config_or_timezone_fingerprint_change_before_data_center(
    policy: TransitionPlanDisclosureRuntimePolicy,
    calendar: VerifiedSimulatedAccountOriginCalendar,
    as_of: datetime,
) -> None:
    snapshot_reader = _SnapshotReader(_snapshot())
    reader = _scope_reader(policy=policy, calendar=calendar, snapshot_reader=snapshot_reader)
    receipt = _receipt()
    pinner = PinRebalanceJourneyEventCoverage(
        scope_reader=reader,
        snapshot_reader=snapshot_reader,
        lease_policy=None,
    )

    with pytest.raises(RebalanceJourneyUnavailable):
        pinner.pin(
            asset_identities=_ASSET_PAIRS,
            request_scope=_REQUEST_SCOPE,
            as_of=as_of,
            parent=None,
            refresh_receipt=receipt,
        )

    assert snapshot_reader.latest_requests == []
    assert snapshot_reader.exact_requests == []


def test_scope_reader_fails_closed_on_late_event_revision_or_expired_latest_proof() -> None:
    receipt = _receipt()
    late_reader = _SnapshotReader(_snapshot(), late_change=True)
    late_pinner = PinRebalanceJourneyEventCoverage(
        scope_reader=_scope_reader(snapshot_reader=late_reader),
        snapshot_reader=late_reader,
        lease_policy=None,
    )
    with pytest.raises(RebalanceJourneyUnavailable):
        late_pinner.pin(
            asset_identities=_ASSET_PAIRS,
            request_scope=_REQUEST_SCOPE,
            as_of=_AS_OF,
            parent=None,
            refresh_receipt=receipt,
        )
    assert late_reader.exact_requests == []

    expired_reader = _SnapshotReader(_snapshot(proof_at=_AS_OF - timedelta(seconds=60)))
    expired_pinner = PinRebalanceJourneyEventCoverage(
        scope_reader=_scope_reader(snapshot_reader=expired_reader),
        snapshot_reader=expired_reader,
        lease_policy=None,
    )
    with pytest.raises(RebalanceJourneyUnavailable):
        expired_pinner.pin(
            asset_identities=_ASSET_PAIRS,
            request_scope=_REQUEST_SCOPE,
            as_of=_AS_OF,
            parent=None,
            refresh_receipt=receipt,
        )
    assert expired_reader.exact_requests == []


def test_receipt_cannot_replace_complete_durable_data_center_proof() -> None:
    snapshot_reader = _SnapshotReader(None)
    pinner = PinRebalanceJourneyEventCoverage(
        scope_reader=_scope_reader(snapshot_reader=snapshot_reader),
        snapshot_reader=snapshot_reader,
        lease_policy=None,
    )

    with pytest.raises(RebalanceJourneyUnavailable):
        pinner.pin(
            asset_identities=_ASSET_PAIRS,
            request_scope=_REQUEST_SCOPE,
            as_of=_AS_OF,
            parent=None,
            refresh_receipt=_receipt(),
        )

    assert len(snapshot_reader.latest_requests) == 1
    assert snapshot_reader.exact_requests == []
