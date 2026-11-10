"""Tests for the read-only Data Center event coverage adapter."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest

from apps.data_center.application.security_disclosure_event import (
    QuerySecurityDisclosureEventsUseCase,
    QuerySecurityDisclosureListingCoverageUseCase,
)
from apps.data_center.domain.security_disclosure_event import (
    PersistedSecurityDisclosureEvent,
    PersistedSecurityDisclosureListingCoverage,
    SecurityDisclosureEvent,
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureListingCoverageProof,
    SecurityDisclosureListingCoverageReadScope,
    SecurityDisclosureListingCoverageSnapshot,
    SecurityDisclosureListingCoverageStatus,
    SecurityDisclosureListingEntry,
    SecurityDisclosureSource,
)
from apps.portfolio.application.transition_plan_event_review import (
    TransitionPlanEventSnapshotReadError,
    TransitionPlanEventSnapshotReadRequest,
    TransitionPlanEventSourceRevisionChanged,
)
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventCoverageLeasePolicy,
    TransitionPlanEventCoverageStatus,
)
from apps.simulated_trading.application.rebalance_journey_event_coverage import (
    RebalanceJourneyEventCoverageScope,
)
from apps.simulated_trading.transition_plan_event_coverage_adapter import (
    DataCenterTransitionPlanEventSnapshotReader,
    translate_persisted_listing_coverage_to_scope,
)

ASSET_CODE = "300750.SZ"
SECURITY_ID = "trusted-security-identity-42"
SOURCE_ID = SecurityDisclosureSource.SZSE_OFFICIAL.value
START_ON = date(2026, 10, 14)
END_ON = date(2026, 10, 15)
FIRST_OBSERVED_AT = datetime(2026, 11, 11, 8, 0, tzinfo=UTC)
EVENT_FIRST_SEEN_AT = datetime(2026, 11, 11, 8, 1, tzinfo=UTC)
VERIFIED_AT = datetime(2026, 11, 11, 8, 3, tzinfo=UTC)
PROOF_RECORDED_AT = datetime(2026, 11, 11, 8, 4, tzinfo=UTC)
PDF_ID = str(UUID("6f8c5bba-88b5-4e1f-9413-38a2b7a2bfa1"))
NEW_PDF_ID = str(UUID("9b512198-c6e6-4f72-8efa-41d6e3dd9802"))
LISTING_ID = str(UUID("c5e48890-eeb8-4cd3-9f66-2e2ef61b1014"))
SOURCE_BODY = b"official disclosure PDF bytes"


class _QueryUseCaseStub:
    """Return one configured Data Center result and retain the requested scope."""

    def __init__(self, result: SecurityDisclosureListingCoverageSnapshot) -> None:
        self.result = result
        self.scopes: list[SecurityDisclosureListingCoverageReadScope] = []

    def execute(
        self, scope: SecurityDisclosureListingCoverageReadScope
    ) -> SecurityDisclosureListingCoverageSnapshot:
        self.scopes.append(scope)
        return self.result


class _EventQueryUseCaseStub:
    """Return the selected immutable action-time revisions and retain the exact scope."""

    def __init__(self, records: tuple[PersistedSecurityDisclosureEvent, ...]) -> None:
        self.records = records
        self.scopes: list[SecurityDisclosureEventReadScope] = []

    def execute(
        self,
        scope: SecurityDisclosureEventReadScope,
    ) -> tuple[PersistedSecurityDisclosureEvent, ...]:
        """Serve the typed source revisions available at the requested action time."""

        self.scopes.append(scope)
        return self.records


class _CutoffQueryUseCaseStub:
    """Return the exact prepared read result for each requested knowledge cutoff."""

    def __init__(
        self,
        results: tuple[SecurityDisclosureListingCoverageSnapshot, ...],
    ) -> None:
        self.results = {result.scope.as_of: result for result in results}
        self.scopes: list[SecurityDisclosureListingCoverageReadScope] = []

    def execute(
        self,
        scope: SecurityDisclosureListingCoverageReadScope,
    ) -> SecurityDisclosureListingCoverageSnapshot:
        """Record the exact scope and return only its explicitly configured result."""

        self.scopes.append(scope)
        if scope.as_of not in self.results:
            raise AssertionError("unexpected Data Center coverage cutoff")
        return self.results[scope.as_of]


def _entry(
    *,
    published_on: date = END_ON,
    source_document_id: str = PDF_ID,
) -> SecurityDisclosureListingEntry:
    """Build one valid official SZSE listing row."""

    return SecurityDisclosureListingEntry(
        listing_id=LISTING_ID,
        announcement_id=80812001,
        title="2026 third-quarter report",
        published_on=published_on,
        raw_publish_time=f"{published_on.isoformat()} 18:00:00",
        source_document_id=source_document_id,
        source_url=(
            "https://www.szse.cn/api/disc/disk03/finalpage/2026-10-15/" f"{source_document_id}.PDF"
        ),
    )


def _persisted_coverage(
    *,
    asset_code: str = ASSET_CODE,
    start_on: date = START_ON,
    end_on: date = END_ON,
    recorded_at: datetime = PROOF_RECORDED_AT,
) -> PersistedSecurityDisclosureListingCoverage:
    """Build a persisted exact-window official proof with distinct source clocks."""

    proof = SecurityDisclosureListingCoverageProof(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code=asset_code,
        start_on=start_on,
        end_on=end_on,
        first_observed_at=FIRST_OBSERVED_AT,
        verified_at=VERIFIED_AT,
        announcement_count=1,
        entries=(_entry(published_on=end_on),),
        first_pass_page_body_sha256=("a" * 64,),
        second_pass_page_body_sha256=("b" * 64,),
    )
    return PersistedSecurityDisclosureListingCoverage(proof=proof, recorded_at=recorded_at)


def _event(
    *,
    event_type: SecurityDisclosureEventType = SecurityDisclosureEventType.FINANCIAL_REPORT,
    source_event_id: str = PDF_ID,
    source_revision_id: str = "revision-1",
    source_body: bytes = SOURCE_BODY,
    announced_at: date | datetime | None = END_ON,
    recorded_at: datetime = PROOF_RECORDED_AT,
    supersedes_source_event_id: str | None = None,
    supersedes_source_revision_id: str | None = None,
) -> PersistedSecurityDisclosureEvent:
    """Build one typed event revision matching the official listing row."""

    event = SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code=ASSET_CODE,
        source_security_code=ASSET_CODE[:6],
        source_event_id=source_event_id,
        source_revision_id=source_revision_id,
        raw_event_type=event_type.value,
        event_type=event_type,
        source_url=_entry(source_document_id=source_event_id).source_url,
        source_document_body=source_body,
        first_seen_at=EVENT_FIRST_SEEN_AT,
        announced_at=announced_at,
        effective_at=datetime(2026, 10, 16, tzinfo=UTC),
        supersedes_source_event_id=supersedes_source_event_id,
        supersedes_source_revision_id=supersedes_source_revision_id,
    )
    return PersistedSecurityDisclosureEvent(event=event, recorded_at=recorded_at)


def _coverage_result(
    *,
    status: SecurityDisclosureListingCoverageStatus = SecurityDisclosureListingCoverageStatus.COMPLETE,
    persisted: PersistedSecurityDisclosureListingCoverage | None = None,
    events: tuple[PersistedSecurityDisclosureEvent, ...] | None = None,
    as_of: datetime = PROOF_RECORDED_AT,
    start_on: date = START_ON,
    end_on: date = END_ON,
) -> SecurityDisclosureListingCoverageSnapshot:
    """Create a Data Center result for the exact supplied read scope."""

    selected_persisted = _persisted_coverage() if persisted is None else persisted
    selected_events = (_event(),) if events is None else events
    scope = SecurityDisclosureListingCoverageReadScope(
        asset_code=ASSET_CODE,
        start_on=start_on,
        end_on=end_on,
        as_of=as_of,
    )
    return SecurityDisclosureListingCoverageSnapshot(
        scope=scope,
        proof=selected_persisted,
        events=selected_events,
        coverage_status=status,
        reason_code="TEST_COVERAGE_RESULT",
    )


def _reader(
    result: SecurityDisclosureListingCoverageSnapshot,
) -> tuple[DataCenterTransitionPlanEventSnapshotReader, _QueryUseCaseStub]:
    """Bind a typed test double to the concrete Data Center query-use-case port."""

    stub = _QueryUseCaseStub(result)
    query = cast(QuerySecurityDisclosureListingCoverageUseCase, stub)
    return (
        DataCenterTransitionPlanEventSnapshotReader(
            query_use_case=query,
        ),
        stub,
    )


def _read_request(
    *,
    source_id: str = SOURCE_ID,
    as_of: datetime = PROOF_RECORDED_AT,
    start_on: date = START_ON,
    end_on: date = END_ON,
) -> TransitionPlanEventSnapshotReadRequest:
    """Build one exact Portfolio read request with a trusted caller identity pair."""

    return TransitionPlanEventSnapshotReadRequest(
        asset_code=ASSET_CODE,
        security_id=SECURITY_ID,
        source_id=source_id,
        start_on=start_on,
        end_on=end_on,
        as_of=as_of,
    )


def _lease_policy() -> TransitionPlanEventCoverageLeasePolicy:
    """Supply the approved lease bound explicitly at the test boundary."""

    return TransitionPlanEventCoverageLeasePolicy(
        policy_version="test-policy-2026-11-11",
        ttl=timedelta(seconds=60),
        maximum_ttl=timedelta(seconds=60),
    )


def test_reader_preserves_trusted_identity_source_clocks_and_hashes() -> None:
    result = _coverage_result()
    reader, stub = _reader(result)

    snapshot = reader.read_snapshot(_read_request())

    assert snapshot is not None
    assert snapshot.coverage_status is TransitionPlanEventCoverageStatus.COMPLETE
    assert (snapshot.asset_code, snapshot.security_id) == (ASSET_CODE, SECURITY_ID)
    assert snapshot.source_id == SOURCE_ID
    assert snapshot.start_on is START_ON
    assert snapshot.end_on is END_ON
    assert snapshot.as_of == PROOF_RECORDED_AT
    assert snapshot.first_observed_at == FIRST_OBSERVED_AT
    assert snapshot.source_observed_at == VERIFIED_AT
    assert snapshot.proof_recorded_at == PROOF_RECORDED_AT
    assert stub.scopes == [result.scope]

    event = snapshot.events[0]
    persisted_event = result.events[0]
    assert event.source_revision_id == persisted_event.event.source_revision_id
    assert event.announced_at is END_ON
    assert event.effective_at == persisted_event.event.effective_at
    assert event.available_at == EVENT_FIRST_SEEN_AT
    assert event.known_at == PROOF_RECORDED_AT
    assert event.body_sha256 == persisted_event.event.source_body_sha256
    assert event.manifest_sha256 == persisted_event.event.content_hash
    assert snapshot.source_scope_sha256 == result.source_scope_sha256


def test_reader_rechecks_latest_action_time_proof_at_exact_recorded_at() -> None:
    """A normal older proof is read again at its durable clock and remains complete."""

    action_at = PROOF_RECORDED_AT + timedelta(seconds=10)
    persisted = _persisted_coverage()
    latest = _coverage_result(
        status=SecurityDisclosureListingCoverageStatus.UNKNOWN,
        persisted=persisted,
        events=(),
        as_of=action_at,
    )
    exact = _coverage_result(
        persisted=persisted,
        as_of=PROOF_RECORDED_AT,
    )
    stub = _CutoffQueryUseCaseStub((latest, exact))
    event_stub = _EventQueryUseCaseStub((_event(),))
    reader = DataCenterTransitionPlanEventSnapshotReader(
        query_use_case=cast(QuerySecurityDisclosureListingCoverageUseCase, stub),
        event_query_use_case=cast(QuerySecurityDisclosureEventsUseCase, event_stub),
    )

    snapshot = reader.read_latest_snapshot(_read_request(as_of=action_at))

    assert snapshot is not None
    assert snapshot.coverage_status is TransitionPlanEventCoverageStatus.COMPLETE
    assert snapshot.as_of == PROOF_RECORDED_AT
    assert snapshot.proof_recorded_at == PROOF_RECORDED_AT
    assert [scope.as_of for scope in stub.scopes] == [action_at, PROOF_RECORDED_AT]
    assert event_stub.scopes == [
        SecurityDisclosureEventReadScope(
            as_of=action_at,
            exchange=SecurityDisclosureExchange.SZSE,
            asset_code=ASSET_CODE,
        )
    ]


def test_reader_blocks_when_exact_reread_changes_the_latest_proof_identity() -> None:
    """The exact reread must return the same immutable proof selected at action time."""

    action_at = PROOF_RECORDED_AT + timedelta(seconds=10)
    latest_proof = _persisted_coverage()
    changed_proof = replace(
        latest_proof,
        proof=replace(
            latest_proof.proof,
            second_pass_page_body_sha256=("d" * 64,),
        ),
    )
    latest = _coverage_result(
        status=SecurityDisclosureListingCoverageStatus.UNKNOWN,
        persisted=latest_proof,
        events=(),
        as_of=action_at,
    )
    exact = _coverage_result(persisted=changed_proof, as_of=PROOF_RECORDED_AT)
    stub = _CutoffQueryUseCaseStub((latest, exact))
    event_stub = _EventQueryUseCaseStub((_event(),))
    reader = DataCenterTransitionPlanEventSnapshotReader(
        query_use_case=cast(QuerySecurityDisclosureListingCoverageUseCase, stub),
        event_query_use_case=cast(QuerySecurityDisclosureEventsUseCase, event_stub),
    )

    with pytest.raises(TransitionPlanEventSnapshotReadError):
        reader.read_latest_snapshot(_read_request(as_of=action_at))


@pytest.mark.parametrize("change_kind", ("append", "correction"))
def test_reader_signals_confirmed_action_time_event_append_or_correction(
    change_kind: str,
) -> None:
    """A proven in-window source revision after the proof requires successor review."""

    action_at = PROOF_RECORDED_AT + timedelta(seconds=10)
    persisted = _persisted_coverage()
    original = _event()
    changed = (
        _event(
            source_event_id=NEW_PDF_ID,
            source_revision_id="revision-new",
            source_body=b"new official disclosure PDF bytes",
            recorded_at=PROOF_RECORDED_AT + timedelta(seconds=5),
        )
        if change_kind == "append"
        else _event(
            source_revision_id="revision-2",
            source_body=b"corrected official disclosure PDF bytes",
            recorded_at=PROOF_RECORDED_AT + timedelta(seconds=5),
            supersedes_source_event_id=PDF_ID,
            supersedes_source_revision_id="revision-1",
        )
    )
    latest = _coverage_result(
        status=SecurityDisclosureListingCoverageStatus.UNKNOWN,
        persisted=persisted,
        events=(),
        as_of=action_at,
    )
    exact = _coverage_result(persisted=persisted, as_of=PROOF_RECORDED_AT)
    listing_stub = _CutoffQueryUseCaseStub((latest, exact))
    event_stub = _EventQueryUseCaseStub((original, changed))
    reader = DataCenterTransitionPlanEventSnapshotReader(
        query_use_case=cast(QuerySecurityDisclosureListingCoverageUseCase, listing_stub),
        event_query_use_case=cast(QuerySecurityDisclosureEventsUseCase, event_stub),
    )

    with pytest.raises(TransitionPlanEventSourceRevisionChanged):
        reader.read_latest_snapshot(_read_request(as_of=action_at))


def test_latest_reader_fails_closed_without_action_time_event_query() -> None:
    """Exact snapshot reads remain available when the latest-only guard is not injected."""

    reader, stub = _reader(_coverage_result())

    with pytest.raises(TransitionPlanEventSnapshotReadError):
        reader.read_latest_snapshot(_read_request())

    assert stub.scopes == []


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (
            SecurityDisclosureListingCoverageStatus.PARTIAL,
            TransitionPlanEventCoverageStatus.PARTIAL,
        ),
        (
            SecurityDisclosureListingCoverageStatus.UNKNOWN,
            TransitionPlanEventCoverageStatus.UNKNOWN,
        ),
    ),
)
def test_reader_keeps_incomplete_status_fail_closed(
    status: SecurityDisclosureListingCoverageStatus,
    expected: TransitionPlanEventCoverageStatus,
) -> None:
    reader, _ = _reader(_coverage_result(status=status))

    snapshot = reader.read_snapshot(_read_request())

    assert snapshot is not None
    assert snapshot.coverage_status is expected


def test_reader_returns_none_for_missing_proof() -> None:
    missing = SecurityDisclosureListingCoverageSnapshot(
        scope=SecurityDisclosureListingCoverageReadScope(
            asset_code=ASSET_CODE,
            start_on=START_ON,
            end_on=END_ON,
            as_of=PROOF_RECORDED_AT,
        ),
        proof=None,
        events=(),
        coverage_status=SecurityDisclosureListingCoverageStatus.MISSING,
        reason_code="LISTING_PROOF_NOT_KNOWN_AT_CUTOFF",
    )
    reader, _ = _reader(missing)

    assert reader.read_snapshot(_read_request()) is None


def test_reader_rejects_non_szse_source_without_querying_data_center() -> None:
    reader, stub = _reader(_coverage_result())

    with pytest.raises(TransitionPlanEventSnapshotReadError):
        reader.read_snapshot(_read_request(source_id="sse_official"))

    assert stub.scopes == []


def test_reader_rejects_proof_for_a_different_exact_window() -> None:
    result = _coverage_result(
        status=SecurityDisclosureListingCoverageStatus.UNKNOWN,
        persisted=_persisted_coverage(start_on=date(2026, 10, 13)),
    )
    reader, _ = _reader(result)

    with pytest.raises(TransitionPlanEventSnapshotReadError):
        reader.read_snapshot(_read_request())


def test_reader_rejects_proof_for_a_different_asset_identity() -> None:
    result = _coverage_result(
        status=SecurityDisclosureListingCoverageStatus.UNKNOWN,
        persisted=_persisted_coverage(asset_code="300751.SZ"),
    )
    reader, _ = _reader(result)

    with pytest.raises(TransitionPlanEventSnapshotReadError):
        reader.read_snapshot(_read_request())


def test_reader_preserves_incomplete_status_from_exact_proof_reread() -> None:
    """An exact durable reread cannot promote a partial proof to complete."""

    later_cutoff = PROOF_RECORDED_AT + timedelta(seconds=10)
    persisted = _persisted_coverage()
    latest = _coverage_result(
        status=SecurityDisclosureListingCoverageStatus.UNKNOWN,
        persisted=persisted,
        as_of=later_cutoff,
    )
    exact = _coverage_result(
        status=SecurityDisclosureListingCoverageStatus.PARTIAL,
        persisted=persisted,
        events=(),
    )
    stub = _CutoffQueryUseCaseStub((latest, exact))
    event_stub = _EventQueryUseCaseStub(())
    reader = DataCenterTransitionPlanEventSnapshotReader(
        query_use_case=cast(QuerySecurityDisclosureListingCoverageUseCase, stub),
        event_query_use_case=cast(QuerySecurityDisclosureEventsUseCase, event_stub),
    )

    snapshot = reader.read_latest_snapshot(_read_request(as_of=later_cutoff))

    assert snapshot is not None
    assert snapshot.coverage_status is TransitionPlanEventCoverageStatus.PARTIAL
    assert snapshot.as_of == PROOF_RECORDED_AT
    assert snapshot.proof_recorded_at == PROOF_RECORDED_AT
    assert [scope.as_of for scope in stub.scopes] == [later_cutoff, PROOF_RECORDED_AT]


def test_reader_keeps_later_exact_cutoff_unknown_and_original_recorded_at() -> None:
    """The exact-cutoff API never upgrades an older proof into fresh COMPLETE coverage."""

    later_cutoff = PROOF_RECORDED_AT + timedelta(seconds=10)
    result = _coverage_result(
        status=SecurityDisclosureListingCoverageStatus.UNKNOWN,
        as_of=later_cutoff,
    )
    reader, stub = _reader(result)

    snapshot = reader.read_snapshot(_read_request(as_of=later_cutoff))

    assert snapshot is not None
    assert snapshot.coverage_status is TransitionPlanEventCoverageStatus.UNKNOWN
    assert snapshot.as_of == later_cutoff
    assert snapshot.proof_recorded_at == PROOF_RECORDED_AT
    assert stub.scopes == [result.scope]


def test_reader_rejects_ambiguous_event_revisions() -> None:
    ambiguous_events = (_event(), _event(source_revision_id="revision-2", source_body=b"corrected"))
    result = _coverage_result(
        status=SecurityDisclosureListingCoverageStatus.UNKNOWN,
        events=ambiguous_events,
    )
    reader, _ = _reader(result)

    with pytest.raises(TransitionPlanEventSnapshotReadError):
        reader.read_snapshot(_read_request())


def test_reader_downgrades_unknown_event_classification() -> None:
    result = _coverage_result(
        status=SecurityDisclosureListingCoverageStatus.PARTIAL,
        events=(_event(event_type=SecurityDisclosureEventType.UNKNOWN),),
    )
    reader, _ = _reader(result)

    snapshot = reader.read_snapshot(_read_request())

    assert snapshot is not None
    assert snapshot.coverage_status is TransitionPlanEventCoverageStatus.UNKNOWN
    assert snapshot.events[0].event_type == SecurityDisclosureEventType.UNKNOWN.value


def test_reader_preserves_datetime_precision_for_incomplete_events() -> None:
    announced_at = datetime(2026, 10, 15, 17, 30, tzinfo=UTC)
    result = _coverage_result(
        status=SecurityDisclosureListingCoverageStatus.UNKNOWN,
        events=(_event(announced_at=announced_at),),
    )
    reader, _ = _reader(result)

    snapshot = reader.read_snapshot(_read_request())

    assert snapshot is not None
    assert snapshot.coverage_status is TransitionPlanEventCoverageStatus.UNKNOWN
    assert type(snapshot.events[0].announced_at) is datetime
    assert snapshot.events[0].announced_at == announced_at


def test_scope_translator_issues_lease_from_persisted_clock_and_injected_policy() -> None:
    persisted = _persisted_coverage()
    policy = _lease_policy()
    cutoff = PROOF_RECORDED_AT + timedelta(seconds=15)

    scope = translate_persisted_listing_coverage_to_scope(
        asset_identity=(ASSET_CODE, SECURITY_ID),
        source_id=SOURCE_ID,
        start_on=START_ON,
        end_on=END_ON,
        decision_cutoff=cutoff,
        persisted_coverage=persisted,
        lease_policy=policy,
    )

    assert isinstance(scope, RebalanceJourneyEventCoverageScope)
    assert (scope.asset_code, scope.security_id) == (ASSET_CODE, SECURITY_ID)
    assert scope.source_id == SOURCE_ID
    assert scope.first_observed_at == FIRST_OBSERVED_AT
    assert scope.source_observed_at == VERIFIED_AT
    assert scope.proof_recorded_at == PROOF_RECORDED_AT
    assert scope.lease_policy_version == policy.policy_version
    assert scope.lease_issued_at == persisted.recorded_at
    assert scope.lease_expires_at == persisted.recorded_at + policy.ttl
    assert scope.lease_issued_at < cutoff < scope.lease_expires_at


@pytest.mark.parametrize(
    "cutoff_delta",
    (timedelta(seconds=60), timedelta(seconds=61)),
)
def test_scope_translator_rejects_proof_at_or_beyond_lease_expiry(
    cutoff_delta: timedelta,
) -> None:
    scope = translate_persisted_listing_coverage_to_scope(
        asset_identity=(ASSET_CODE, SECURITY_ID),
        source_id=SOURCE_ID,
        start_on=START_ON,
        end_on=END_ON,
        decision_cutoff=PROOF_RECORDED_AT + cutoff_delta,
        persisted_coverage=_persisted_coverage(),
        lease_policy=_lease_policy(),
    )

    assert scope is None


def test_scope_translator_rejects_missing_policy_and_mismatched_identity() -> None:
    common = {
        "source_id": SOURCE_ID,
        "start_on": START_ON,
        "end_on": END_ON,
        "decision_cutoff": PROOF_RECORDED_AT + timedelta(seconds=1),
        "persisted_coverage": _persisted_coverage(),
    }

    missing_policy = translate_persisted_listing_coverage_to_scope(
        asset_identity=(ASSET_CODE, SECURITY_ID),
        lease_policy=None,
        **common,
    )
    wrong_asset = translate_persisted_listing_coverage_to_scope(
        asset_identity=("300751.SZ", SECURITY_ID),
        lease_policy=_lease_policy(),
        **common,
    )
    wrong_source = translate_persisted_listing_coverage_to_scope(
        asset_identity=(ASSET_CODE, SECURITY_ID),
        source_id="sse_official",
        start_on=START_ON,
        end_on=END_ON,
        decision_cutoff=PROOF_RECORDED_AT + timedelta(seconds=1),
        persisted_coverage=_persisted_coverage(),
        lease_policy=_lease_policy(),
    )

    assert missing_policy is None
    assert wrong_asset is None
    assert wrong_source is None


def test_scope_translator_rejects_proof_persisted_after_decision_cutoff() -> None:
    cutoff = PROOF_RECORDED_AT
    persisted = _persisted_coverage(recorded_at=cutoff + timedelta(seconds=1))

    scope = translate_persisted_listing_coverage_to_scope(
        asset_identity=(ASSET_CODE, SECURITY_ID),
        source_id=SOURCE_ID,
        start_on=START_ON,
        end_on=END_ON,
        decision_cutoff=cutoff,
        persisted_coverage=persisted,
        lease_policy=_lease_policy(),
    )

    assert scope is None
