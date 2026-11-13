"""Read-only current official-window evidence for simulated corporate actions."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from apps.portfolio.application.transition_plan_event_review import (
    TransitionPlanEventSnapshotReadRequest,
)
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventAssetSnapshot,
    TransitionPlanEventCoverageLeasePolicy,
    TransitionPlanEventCoverageStatus,
    TransitionPlanEventRevision,
)
from apps.simulated_trading.application.corporate_action_current_official_window import (
    CorporateActionCurrentOfficialWindowReader,
    CorporateActionCurrentOfficialWindowReason,
)
from apps.simulated_trading.application.corporate_action_current_official_window_contracts import (
    TransitionPlanDisclosureRuntimePolicy,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    QualifiedExchangeTimezone,
    VerifiedSimulatedAccountOriginCalendar,
)

_NOW = datetime(2026, 11, 13, 4, 0, tzinfo=UTC)
_ASSET = "000001.SZ"
_EVENT_ID = "szse-pdf-event-1"
_REVISION_ID = "revision-1"
_BODY_SHA = "a" * 64
_HASH = "b" * 64
_WINDOW_START = date(2026, 10, 1)
_WINDOW_END = _NOW.astimezone(ZoneInfo("Asia/Shanghai")).date()
_LISTED_AT = _NOW - timedelta(seconds=20)
_FIRST_SEEN_AT = _NOW - timedelta(seconds=15)
_PROOF_AT = _NOW - timedelta(seconds=10)


def _request(**overrides: object) -> CorporateActionStageRequest:
    """Build one exact synthetic request with valid domain-stage fields."""

    values: dict[str, object] = {
        "account_id": 17,
        "owner_user_id": 23,
        "security_id": _ASSET,
        "asset_code": _ASSET,
        "asset_name": "Synthetic security",
        "source_namespace": "exchange_official_disclosure",
        "source_record_id": _EVENT_ID,
        "source_event_id": _EVENT_ID,
        "source_revision_id": _REVISION_ID,
        "source_payload_sha256": _BODY_SHA,
        "qualification_sha256": "c" * 64,
        "qualifier_identity": "test-qualifier-v1",
        "source_observed_at": _FIRST_SEEN_AT,
        "qualified_at": _NOW - timedelta(seconds=2),
        "posted_at": _NOW,
        "action_kind": CorporateActionKind.CASH_DIVIDEND,
        "stage": CorporateActionStage.CASH_ENTITLEMENT,
        "entry_kind": CorporateActionEntryKind.POSTING,
        "record_date": date(2026, 10, 30),
        "effective_date": date(2026, 11, 2),
        "stage_date": date(2026, 11, 2),
        "cash_amount": Decimal("100.00"),
        "tax_treatment": "deferred_withholding",
        "ownership_snapshot_id": "ownership:17:2026-10-30",
        "ownership_snapshot_sha256": "d" * 64,
        "ownership_snapshot_as_of_date": date(2026, 10, 30),
        "ownership_snapshot_observed_at": _FIRST_SEEN_AT,
        "eligible_quantity": Decimal("1000.000000"),
        "entitlement_calculation_sha256": "e" * 64,
    }
    values.update(overrides)
    return cast(CorporateActionStageRequest, CorporateActionStageRequest(**values))


def _event(
    *,
    event_id: str = _EVENT_ID,
    revision_id: str = _REVISION_ID,
    body_sha256: str = _BODY_SHA,
    available_at: datetime = _FIRST_SEEN_AT,
    known_at: datetime = _PROOF_AT,
    event_type: str = "cash_dividend",
) -> TransitionPlanEventRevision:
    """Create one exact source member as exposed by the Portfolio snapshot port."""

    return TransitionPlanEventRevision(
        asset_code=_ASSET,
        security_id=_ASSET,
        source_id="szse_official",
        source_event_id=event_id,
        source_revision_id=revision_id,
        event_type=event_type,
        announced_at=_WINDOW_END,
        available_at=available_at,
        known_at=known_at,
        effective_at=date(2026, 11, 2),
        body_sha256=body_sha256,
        manifest_sha256="f" * 64,
    )


def _snapshot(
    *,
    events: tuple[TransitionPlanEventRevision, ...] | None = None,
    coverage_status: TransitionPlanEventCoverageStatus = TransitionPlanEventCoverageStatus.COMPLETE,
    source_scope_sha256: str | None = _HASH,
    first_observed_at: datetime | None = None,
    source_observed_at: datetime = _LISTED_AT,
    proof_recorded_at: datetime = _PROOF_AT,
    end_on: date = _WINDOW_END,
) -> TransitionPlanEventAssetSnapshot:
    """Build a certified latest-to-exact snapshot with original source clocks."""

    return TransitionPlanEventAssetSnapshot(
        asset_code=_ASSET,
        security_id=_ASSET,
        source_id="szse_official",
        start_on=_WINDOW_START,
        end_on=end_on,
        as_of=proof_recorded_at,
        first_observed_at=(
            _FIRST_SEEN_AT - timedelta(seconds=5)
            if first_observed_at is None
            else first_observed_at
        ),
        source_observed_at=source_observed_at,
        proof_recorded_at=proof_recorded_at,
        coverage_status=coverage_status,
        source_scope_sha256=source_scope_sha256,
        events=(_event(known_at=proof_recorded_at),) if events is None else events,
    )


def _calendar(as_of: datetime = _NOW) -> VerifiedSimulatedAccountOriginCalendar:
    """Bind the exact SZSE decision day to verified account-origin timezone evidence."""

    return VerifiedSimulatedAccountOriginCalendar(
        origin_on=_WINDOW_START,
        decision_on=as_of.astimezone(ZoneInfo("Asia/Shanghai")).date(),
        timezone_policy=QualifiedExchangeTimezone(
            exchange="SZSE",
            timezone_name="Asia/Shanghai",
            policy_id="szse-timezone-v1",
            policy_sha256="1" * 64,
        ),
        as_of=as_of,
    )


def _policy(as_of: datetime = _NOW) -> TransitionPlanDisclosureRuntimePolicy:
    """Bind explicit configured policy, body root, provenance, and finite lease."""

    return TransitionPlanDisclosureRuntimePolicy(
        source_id="szse_official",
        start_on=_WINDOW_START,
        end_on=as_of.astimezone(ZoneInfo("Asia/Shanghai")).date(),
        body_store_root=Path(__file__).resolve().parent / "synthetic-official-pdf-store",
        lease_policy=TransitionPlanEventCoverageLeasePolicy(
            policy_version="szse-window-v1",
            ttl=timedelta(seconds=60),
            maximum_ttl=timedelta(seconds=60),
        ),
        policy_version="szse-window-v1",
        runtime_environment="test",
        profile_id="profile-1",
        profile_key="profile-key",
        profile_version=1,
        profile_content_hash="2" * 64,
        snapshot_id="snapshot-1",
        snapshot_content_hash="3" * 64,
        known_at=as_of - timedelta(days=2),
        effective_at=as_of - timedelta(days=1),
        read_at=as_of,
        policy_content_hash="4" * 64,
    )


class _OriginReader:
    def __init__(self, calendars: tuple[VerifiedSimulatedAccountOriginCalendar, ...]) -> None:
        self.calendars = calendars
        self.calls: list[tuple[int, int, str, datetime]] = []

    def read_verified_zero_origin_calendar(
        self, *, account_id: int, owner_user_id: int, exchange: str, as_of: datetime
    ) -> VerifiedSimulatedAccountOriginCalendar:
        self.calls.append((account_id, owner_user_id, exchange, as_of))
        selected = self.calendars[min(len(self.calls) - 1, len(self.calendars) - 1)]
        return replace(selected, as_of=as_of)


class _PolicyReader:
    def __init__(self, policies: tuple[TransitionPlanDisclosureRuntimePolicy, ...]) -> None:
        self.policies = policies
        self.calls: list[tuple[date, date, datetime]] = []

    def read_policy(
        self, *, decision_on: date, earliest_required_on: date, as_of: datetime
    ) -> TransitionPlanDisclosureRuntimePolicy | None:
        self.calls.append((decision_on, earliest_required_on, as_of))
        selected = self.policies[min(len(self.calls) - 1, len(self.policies) - 1)]
        return replace(selected, read_at=as_of)


class _SnapshotReader:
    def __init__(self, snapshots: tuple[TransitionPlanEventAssetSnapshot | None, ...]) -> None:
        self.snapshots = snapshots
        self.requests: list[TransitionPlanEventSnapshotReadRequest] = []

    def read_latest_snapshot(
        self, request: TransitionPlanEventSnapshotReadRequest
    ) -> TransitionPlanEventAssetSnapshot | None:
        self.requests.append(request)
        return self.snapshots[min(len(self.requests) - 1, len(self.snapshots) - 1)]


class _BodyVerifier:
    def __init__(self, rejected_event_ids: frozenset[str] = frozenset()) -> None:
        self.rejected_event_ids = rejected_event_ids
        self.calls: list[tuple[str, str, Path]] = []

    def verify_original_body(
        self, *, event: TransitionPlanEventRevision, body_store_root: Path
    ) -> bool:
        self.calls.append((event.source_event_id, event.body_sha256, body_store_root))
        return event.source_event_id not in self.rejected_event_ids


class _Clock:
    def __init__(self, values: tuple[datetime, ...]) -> None:
        self.values = values
        self.calls = 0

    def now(self) -> datetime:
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


def _reader(
    *,
    request: CorporateActionStageRequest | None = None,
    snapshots: tuple[TransitionPlanEventAssetSnapshot | None, ...] | None = None,
    policies: tuple[TransitionPlanDisclosureRuntimePolicy, ...] | None = None,
    calendars: tuple[VerifiedSimulatedAccountOriginCalendar, ...] | None = None,
    verifier: _BodyVerifier | None = None,
    clock: _Clock | None = None,
) -> tuple[CorporateActionCurrentOfficialWindowReader, _SnapshotReader, _BodyVerifier]:
    """Compose the application reader with explicit pure evidence ports."""

    selected_verifier = _BodyVerifier() if verifier is None else verifier
    snapshot_reader = _SnapshotReader(
        (_snapshot(), _snapshot()) if snapshots is None else snapshots
    )
    origin_reader = _OriginReader((_calendar(), _calendar()) if calendars is None else calendars)
    policy_reader = _PolicyReader((_policy(), _policy()) if policies is None else policies)
    current_clock = _Clock((_NOW, _NOW + timedelta(seconds=1))) if clock is None else clock
    reader = CorporateActionCurrentOfficialWindowReader(
        origin_reader=origin_reader,
        policy_reader=policy_reader,
        snapshot_reader=snapshot_reader,
        original_body_verifier=selected_verifier,
        runtime_environment="test",
        clock=current_clock,
    )
    return reader, snapshot_reader, selected_verifier


def test_read_current_requires_all_member_bodies_and_returns_window_only_evidence() -> None:
    second_event = _event(event_id="other-listed-pdf", body_sha256="5" * 64)
    snapshot = _snapshot(events=(_event(), second_event))
    reader, snapshot_reader, verifier = _reader(snapshots=(snapshot, snapshot))

    result = reader.read_current(_request(), as_of=_NOW)

    assert result.window_ready is True
    assert result.must_not_use_for_decision is True
    assert (
        result.reason_code
        is CorporateActionCurrentOfficialWindowReason.WINDOW_READY_PREREQUISITE_ONLY
    )
    assert result.freshness_status == "current"
    assert result.reliability_status == "verified"
    with pytest.raises(ValueError, match="status is inconsistent"):
        replace(result, freshness_status="unknown")
    assert result.original_first_observed_at == snapshot.first_observed_at
    assert result.original_listing_verified_at == snapshot.source_observed_at
    assert result.original_proof_recorded_at == snapshot.proof_recorded_at
    assert result.checked_at == _NOW + timedelta(seconds=1)
    assert result.expires_at == _LISTED_AT + timedelta(seconds=60)
    assert result.policy_sha256 == _policy().policy_content_hash
    assert result.scope_sha256 == snapshot.source_scope_sha256
    assert result.selected_event_sha256 == snapshot.events[0].manifest_sha256
    assert tuple(item[0] for item in verifier.calls) == (_EVENT_ID, "other-listed-pdf") * 2
    assert len(snapshot_reader.requests) == 3
    assert all(
        item.asset_code == _ASSET and item.security_id == _ASSET
        for item in snapshot_reader.requests
    )
    assert all(
        item.start_on == _WINDOW_START and item.end_on == _WINDOW_END
        for item in snapshot_reader.requests
    )


@pytest.mark.parametrize(
    ("request_overrides", "events", "coverage", "scope_hash", "reason"),
    [
        (
            {"security_id": "SZSE:000001"},
            (_event(),),
            TransitionPlanEventCoverageStatus.COMPLETE,
            _HASH,
            "REQUEST_INVALID",
        ),
        (
            {},
            (_event(revision_id="new-revision"),),
            TransitionPlanEventCoverageStatus.COMPLETE,
            _HASH,
            "SOURCE_EVENT_CHANGED",
        ),
        (
            {},
            (_event(body_sha256="6" * 64),),
            TransitionPlanEventCoverageStatus.COMPLETE,
            _HASH,
            "SOURCE_EVENT_CHANGED",
        ),
        (
            {},
            (_event(available_at=_FIRST_SEEN_AT - timedelta(seconds=1)),),
            TransitionPlanEventCoverageStatus.COMPLETE,
            _HASH,
            "SOURCE_EVENT_CHANGED",
        ),
        (
            {},
            (_event(event_type="unknown"),),
            TransitionPlanEventCoverageStatus.COMPLETE,
            _HASH,
            "SNAPSHOT_INCOMPLETE",
        ),
        (
            {},
            (_event(event_id="other-listed-pdf"),),
            TransitionPlanEventCoverageStatus.COMPLETE,
            _HASH,
            "SOURCE_EVENT_MISSING",
        ),
        ({}, (_event(),), TransitionPlanEventCoverageStatus.PARTIAL, _HASH, "SNAPSHOT_INCOMPLETE"),
    ],
)
def test_read_current_fails_closed_for_request_or_snapshot_mismatch(
    request_overrides: dict[str, object],
    events: tuple[TransitionPlanEventRevision, ...],
    coverage: TransitionPlanEventCoverageStatus,
    scope_hash: str | None,
    reason: str,
) -> None:
    request = _request(**request_overrides)
    snapshot = _snapshot(events=events, coverage_status=coverage, source_scope_sha256=scope_hash)
    reader, _, _ = _reader(snapshots=(snapshot, snapshot))

    result = reader.read_current(request, as_of=_NOW)

    assert result.window_ready is False
    assert result.must_not_use_for_decision is True
    assert result.freshness_status == "unknown"
    assert result.reliability_status == "unverified"
    assert result.reason_code.value == reason


def test_read_current_blocks_missing_or_bad_original_body_verifier() -> None:
    origin_reader = _OriginReader((_calendar(), _calendar()))
    policy_reader = _PolicyReader((_policy(), _policy()))
    snapshot_reader = _SnapshotReader((_snapshot(), _snapshot()))
    missing_verifier = CorporateActionCurrentOfficialWindowReader(
        origin_reader=origin_reader,
        policy_reader=policy_reader,
        snapshot_reader=snapshot_reader,
        original_body_verifier=None,
        runtime_environment="test",
        clock=_Clock((_NOW, _NOW + timedelta(seconds=1))),
    )
    result = missing_verifier.read_current(_request(), as_of=_NOW)
    assert result.window_ready is False
    assert (
        result.reason_code
        is CorporateActionCurrentOfficialWindowReason.ORIGINAL_BODY_VERIFIER_UNAVAILABLE
    )

    reader, _, _ = _reader()
    rejecting = _BodyVerifier(frozenset({_EVENT_ID}))
    reader, _, verifier = _reader(verifier=rejecting)
    result = reader.read_current(_request(), as_of=_NOW)

    assert result.window_ready is False
    assert result.reason_code is CorporateActionCurrentOfficialWindowReason.ORIGINAL_BODY_UNVERIFIED
    assert verifier.calls and verifier.calls[0][0] == _EVENT_ID


def test_read_current_requires_current_window_policy_environment_and_owner_scope() -> None:
    wrong_policy = replace(_policy(), end_on=_WINDOW_END - timedelta(days=1))
    reader, _, _ = _reader(policies=(wrong_policy, wrong_policy))
    result = reader.read_current(_request(), as_of=_NOW)
    assert result.reason_code is CorporateActionCurrentOfficialWindowReason.POLICY_UNAVAILABLE

    wrong_environment = replace(_policy(), runtime_environment="production")
    reader, _, _ = _reader(policies=(wrong_environment, wrong_environment))
    result = reader.read_current(_request(), as_of=_NOW)
    assert result.reason_code is CorporateActionCurrentOfficialWindowReason.POLICY_UNAVAILABLE


def test_read_current_checks_original_expiry_not_a_renewed_checked_at_lease() -> None:
    almost_expired = _snapshot(
        events=(
            _event(
                available_at=_NOW - timedelta(seconds=59),
                known_at=_NOW - timedelta(seconds=58),
            ),
        ),
        first_observed_at=_NOW - timedelta(seconds=60),
        source_observed_at=_NOW - timedelta(seconds=59),
        proof_recorded_at=_NOW - timedelta(seconds=58),
    )
    reader, _, _ = _reader(
        snapshots=(almost_expired, almost_expired),
        clock=_Clock((_NOW, _NOW + timedelta(seconds=2))),
    )

    almost_expired_request = _request(
        source_observed_at=_NOW - timedelta(seconds=59),
        qualified_at=_NOW - timedelta(seconds=2),
        posted_at=_NOW,
        ownership_snapshot_observed_at=_NOW - timedelta(seconds=59),
    )
    result = reader.read_current(almost_expired_request, as_of=_NOW)

    assert result.window_ready is False
    assert result.reason_code is CorporateActionCurrentOfficialWindowReason.WINDOW_EXPIRED
    assert result.freshness_status == "stale"


def test_read_current_rejects_policy_or_snapshot_changes_before_return() -> None:
    original = _policy()
    changed_policy = replace(original, profile_content_hash="9" * 64)
    reader, _, _ = _reader(policies=(original, changed_policy))
    result = reader.read_current(_request(), as_of=_NOW)
    assert result.reason_code is CorporateActionCurrentOfficialWindowReason.POLICY_CHANGED

    original_snapshot = _snapshot()
    changed_snapshot = _snapshot(source_scope_sha256="8" * 64)
    reader, _, _ = _reader(snapshots=(original_snapshot, changed_snapshot))
    result = reader.read_current(_request(), as_of=_NOW)
    assert result.reason_code is CorporateActionCurrentOfficialWindowReason.SNAPSHOT_CHANGED


def test_read_current_rechecks_policy_and_snapshot_metadata_after_body_io() -> None:
    original_policy = _policy()
    changed_policy = replace(original_policy, profile_content_hash="9" * 64)
    reader, _, verifier = _reader(policies=(original_policy, original_policy, changed_policy))

    result = reader.read_current(_request(), as_of=_NOW)

    assert result.reason_code is CorporateActionCurrentOfficialWindowReason.POLICY_CHANGED
    assert len(verifier.calls) == 2

    original_snapshot = _snapshot()
    changed_snapshot = _snapshot(source_scope_sha256="8" * 64)
    reader, _, verifier = _reader(
        snapshots=(original_snapshot, original_snapshot, changed_snapshot)
    )

    result = reader.read_current(_request(), as_of=_NOW)

    assert result.reason_code is CorporateActionCurrentOfficialWindowReason.SNAPSHOT_CHANGED
    assert len(verifier.calls) == 2


def test_read_current_checks_expiry_after_final_body_and_metadata_io() -> None:
    reader, _, _ = _reader(
        clock=_Clock(
            (
                _NOW,
                _NOW + timedelta(seconds=1),
                _NOW + timedelta(seconds=42),
            )
        )
    )

    result = reader.read_current(_request(), as_of=_NOW)

    assert result.window_ready is False
    assert result.reason_code is CorporateActionCurrentOfficialWindowReason.WINDOW_EXPIRED
    assert result.freshness_status == "stale"

    reader, _, _ = _reader(
        clock=_Clock(
            (
                _NOW,
                _NOW + timedelta(seconds=1),
                _NOW + timedelta(seconds=2),
                _NOW + timedelta(seconds=42),
            )
        )
    )

    result = reader.read_current(_request(), as_of=_NOW)

    assert result.window_ready is False
    assert result.reason_code is CorporateActionCurrentOfficialWindowReason.WINDOW_EXPIRED


def test_read_current_rejects_future_or_backward_clock_and_day_rollover() -> None:
    reader, _, _ = _reader(clock=_Clock((_NOW - timedelta(seconds=1), _NOW)))
    result = reader.read_current(_request(), as_of=_NOW)
    assert (
        result.reason_code is CorporateActionCurrentOfficialWindowReason.CLOCK_AHEAD_OF_TRUSTED_NOW
    )

    reader, _, _ = _reader(clock=_Clock((_NOW, _NOW - timedelta(seconds=1))))
    result = reader.read_current(_request(), as_of=_NOW)
    assert result.reason_code is CorporateActionCurrentOfficialWindowReason.CLOCK_MOVED_BACKWARDS

    reader, _, _ = _reader(clock=_Clock((_NOW, _NOW + timedelta(seconds=1), _NOW)))
    result = reader.read_current(_request(), as_of=_NOW)
    assert result.reason_code is CorporateActionCurrentOfficialWindowReason.CLOCK_MOVED_BACKWARDS

    boundary_start = datetime(2026, 11, 13, 15, 59, 55, tzinfo=UTC)
    boundary_finish = boundary_start + timedelta(seconds=10)
    boundary_seen = boundary_start - timedelta(seconds=15)
    initial_snapshot = _snapshot(
        events=(
            _event(available_at=boundary_seen, known_at=boundary_start - timedelta(seconds=1)),
        ),
        first_observed_at=boundary_start - timedelta(seconds=20),
        source_observed_at=boundary_start - timedelta(seconds=5),
        proof_recorded_at=boundary_start - timedelta(seconds=1),
        end_on=_calendar(boundary_start).decision_on,
    )
    boundary_request = _request(
        source_observed_at=boundary_seen,
        qualified_at=boundary_start - timedelta(seconds=2),
        posted_at=boundary_start,
        ownership_snapshot_observed_at=boundary_seen,
    )
    reader, _, _ = _reader(
        calendars=(_calendar(boundary_start), _calendar(boundary_start)),
        policies=(_policy(boundary_start), _policy(boundary_start)),
        snapshots=(initial_snapshot, initial_snapshot),
        clock=_Clock((boundary_start, boundary_start + timedelta(seconds=1), boundary_finish)),
    )
    result = reader.read_current(boundary_request, as_of=boundary_start)
    assert result.reason_code is CorporateActionCurrentOfficialWindowReason.CURRENT_DAY_CHANGED
    assert result.freshness_status == "stale"

    old_now = _NOW - timedelta(days=1)
    old_seen = _FIRST_SEEN_AT - timedelta(days=1)
    old_snapshot = _snapshot(
        events=(_event(available_at=old_seen, known_at=old_now - timedelta(seconds=10)),),
        first_observed_at=old_now - timedelta(seconds=30),
        source_observed_at=old_now - timedelta(seconds=20),
        proof_recorded_at=old_now - timedelta(seconds=10),
        end_on=old_now.astimezone(ZoneInfo("Asia/Shanghai")).date(),
    )
    reader, _, _ = _reader(
        calendars=(_calendar(old_now), _calendar(old_now)),
        policies=(_policy(old_now), _policy(old_now)),
        snapshots=(old_snapshot, old_snapshot),
        clock=_Clock((_NOW, _NOW + timedelta(seconds=1))),
    )
    stale_request = _request(
        source_observed_at=old_seen,
        qualified_at=old_seen + timedelta(seconds=2),
        posted_at=old_seen + timedelta(seconds=3),
        ownership_snapshot_observed_at=old_seen,
    )
    result = reader.read_current(stale_request, as_of=old_now)
    assert result.reason_code is CorporateActionCurrentOfficialWindowReason.CURRENT_DAY_CHANGED
