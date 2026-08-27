"""RED contracts for replaying the canonical Data Reliability chain."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from apps.audit.application.data_decision_read_audit import (
    DataDecisionReadAuditObservation,
    build_data_decision_read_audit_event,
)
from apps.audit.application.data_failover_audit import (
    DataFailoverAuditObservation,
    build_data_failover_audit_event,
)
from apps.audit.application.data_fetch_audit import (
    DataFetchAuditObservation,
    build_data_fetch_audit_event,
)
from apps.audit.application.data_freshness_audit import (
    DataFreshnessAuditObservation,
    build_data_freshness_audit_event,
)
from apps.audit.application.data_publication_audit import (
    DataPublicationAuditObservation,
    build_data_publication_audit_event,
)
from apps.audit.application.data_publication_rollback_audit import (
    DataPublicationRollbackAuditObservation,
    build_data_publication_rollback_audit_event,
)
from apps.audit.application.data_quality_audit import (
    DataQualityAuditObservation,
    DataQualityState,
    DataQualityStatusCount,
    build_data_quality_audit_event,
)
from apps.audit.application.data_validation_audit import (
    DataValidationRejectedObservation,
    build_data_validation_rejected_event,
)
from apps.audit.application.system_audit_query import (
    ListCorrelatedSystemAuditEventsUseCase,
    SystemAuditReaderContext,
)
from apps.audit.domain.system_audit_event import (
    AuditOutcome,
    AuditScopeRef,
    SystemAuditEvent,
)
from apps.data_center.application.control_plane import (
    publication_rollback_evidence_content_hash,
)
from apps.data_center.application.data_chain_replay import (
    DataChainReplayCommand,
    DataChainReplayResult,
    ReplayCorruption,
    ReplayDataChainUseCase,
    ReplayMemberPersistenceEvidence,
    ReplayUnavailable,
)
from apps.data_center.application.publication_utils import publication_hash
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationFactReference,
    PublicationMember,
    PublicationRollback,
    PublicationState,
)
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
AS_OF = NOW + timedelta(minutes=10)
RUN_ID = "run-1"
INGESTED_RUN_ID = "ingested-1"
PUBLICATION_ID = "00000000-0000-4000-8000-000000000001"
ROLLBACK_ID = "00000000-0000-4000-8000-000000000002"
PREVIOUS_PUBLICATION_ID = "00000000-0000-4000-8000-000000000003"
PREVIOUS_PUBLICATION_HASH = "d" * 64
SCOPE = AuditScopeRef("tenant:primary", "owner:research")
_UNSET = object()
_RAW_AUDIT = RawAudit(
    provider_name="provider-main",
    capability="historical_price",
    request_params={"asset_code": "000001.SZ"},
    status="ok",
    row_count=1,
    fetched_at=NOW,
    redacted=True,
    raw_audit_id="raw-1",
    run_id=RUN_ID,
    ingested_run_id=INGESTED_RUN_ID,
)
RAW_HASH = raw_audit_content_hash(_RAW_AUDIT)
_VERIFIER_RAW_AUDIT = RawAudit(
    provider_name="provider-verifier",
    capability="historical_price",
    request_params={"asset_code": "000001.SZ"},
    status="ok",
    row_count=1,
    fetched_at=NOW + timedelta(seconds=10),
    redacted=True,
    raw_audit_id="raw-2",
    run_id=RUN_ID,
    ingested_run_id=INGESTED_RUN_ID,
)
VERIFIER_RAW_HASH = raw_audit_content_hash(_VERIFIER_RAW_AUDIT)
PUBLICATION_HASH = publication_hash(
    (
        PublicationFactReference(
            natural_key="000001.SZ:2026-08-27:1d:none:provider-main",
            source="provider-main",
            source_record_id="source-1",
            fact_table="data_center_price_bar",
            fact_pk="fact-1",
            observed_at=NOW,
            raw_payload_hash=RAW_HASH,
        ),
    )
)


def _fetch_event() -> SystemAuditEvent:
    return build_data_fetch_audit_event(
        DataFetchAuditObservation(
            provider_key="provider-main",
            capability="historical_price",
            dataset_key="equity.price.bar",
            run_id=RUN_ID,
            ingested_run_id=INGESTED_RUN_ID,
            raw_audit_id="raw-1",
            raw_audit_version="1",
            raw_audit_content_hash=RAW_HASH,
            outcome=AuditOutcome.SUCCESS,
            row_count=1,
            occurred_at=NOW,
            recorded_at=NOW,
            scope=SCOPE,
        ),
        sequence_no=1,
        predecessor_hash=None,
    )


def _verification_fetch_event() -> SystemAuditEvent:
    return build_data_fetch_audit_event(
        DataFetchAuditObservation(
            provider_key="provider-verifier",
            capability="historical_price",
            dataset_key="equity.price.bar",
            run_id=RUN_ID,
            ingested_run_id=INGESTED_RUN_ID,
            raw_audit_id="raw-2",
            raw_audit_version="1",
            raw_audit_content_hash=VERIFIER_RAW_HASH,
            outcome=AuditOutcome.SUCCESS,
            row_count=1,
            occurred_at=NOW + timedelta(seconds=10),
            recorded_at=NOW + timedelta(seconds=10),
            scope=SCOPE,
        ),
        sequence_no=1,
        predecessor_hash=None,
    )


def _failover_events(
    *, terminal_outcome: AuditOutcome = AuditOutcome.SUCCESS
) -> tuple[SystemAuditEvent, SystemAuditEvent]:
    """Build one hash-valid failover start and terminal pair."""

    started = build_data_failover_audit_event(
        DataFailoverAuditObservation(
            dataset_key="equity.price.bar",
            capability="historical_price",
            from_provider="provider-primary",
            to_provider="provider-main",
            run_id=RUN_ID,
            ingested_run_id=INGESTED_RUN_ID,
            raw_audit_id="raw-1",
            raw_audit_version="1",
            raw_audit_content_hash=RAW_HASH,
            tolerance=0.01,
            observed_deviation=None,
            reason_code="primary_unavailable_fallback_verified",
            outcome=AuditOutcome.STARTED,
            occurred_at=NOW + timedelta(seconds=30),
            recorded_at=NOW + timedelta(seconds=30),
            scope=SCOPE,
        ),
        sequence_no=1,
        predecessor_hash=None,
    )
    observed_deviation = {
        AuditOutcome.SUCCESS: 0.005,
        AuditOutcome.BLOCKED: 0.02,
    }.get(terminal_outcome)
    terminal = build_data_failover_audit_event(
        DataFailoverAuditObservation(
            dataset_key="equity.price.bar",
            capability="historical_price",
            from_provider="provider-primary",
            to_provider="provider-main",
            run_id=RUN_ID,
            ingested_run_id=INGESTED_RUN_ID,
            raw_audit_id="raw-1",
            raw_audit_version="1",
            raw_audit_content_hash=RAW_HASH,
            tolerance=0.01,
            observed_deviation=observed_deviation,
            reason_code="primary_unavailable_fallback_verified",
            outcome=terminal_outcome,
            occurred_at=NOW + timedelta(minutes=1, seconds=1),
            recorded_at=NOW + timedelta(minutes=1, seconds=1),
            error_class=("ValueError" if terminal_outcome is AuditOutcome.BLOCKED else None),
            scope=SCOPE,
        ),
        sequence_no=2,
        predecessor_hash=started.content_hash,
    )
    return started, terminal


def _exhausted_failover_events() -> tuple[SystemAuditEvent, SystemAuditEvent]:
    """Build one hash-valid start and exhausted terminal pair."""

    started, _ = _failover_events()
    exhausted = build_data_failover_audit_event(
        DataFailoverAuditObservation(
            dataset_key="equity.price.bar",
            capability="historical_price",
            from_provider="provider-primary",
            to_provider="provider-main",
            run_id=RUN_ID,
            ingested_run_id=INGESTED_RUN_ID,
            raw_audit_id="raw-1",
            raw_audit_version="1",
            raw_audit_content_hash=RAW_HASH,
            tolerance=0.01,
            observed_deviation=None,
            reason_code="failover_candidates_exhausted",
            outcome=AuditOutcome.BLOCKED,
            occurred_at=NOW + timedelta(minutes=1, seconds=1),
            recorded_at=NOW + timedelta(minutes=1, seconds=1),
            error_class="LookupError",
            scope=SCOPE,
        ),
        sequence_no=2,
        predecessor_hash=started.content_hash,
    )
    return started, exhausted


def _publication_event(*, publication_hash_value: str = PUBLICATION_HASH) -> SystemAuditEvent:
    return build_data_publication_audit_event(
        DataPublicationAuditObservation(
            dataset_key="equity.price.bar",
            publication_key="current",
            publication_id=PUBLICATION_ID,
            publication_version="1.0:1.0",
            publication_hash=publication_hash_value,
            provider_key="provider-main",
            run_id=RUN_ID,
            ingested_run_id=INGESTED_RUN_ID,
            member_count=1,
            coverage_requested_count=1,
            coverage_eligible_count=1,
            coverage_selected_count=1,
            outcome=AuditOutcome.PUBLISHED,
            raw_audit_id="raw-1",
            raw_audit_version="1",
            raw_audit_content_hash=RAW_HASH,
            occurred_at=NOW + timedelta(minutes=2),
            recorded_at=NOW + timedelta(minutes=2),
            scope=SCOPE,
        ),
        sequence_no=1,
        predecessor_hash=None,
    )


def _decision_read_event(*, publication_hash_value: str = PUBLICATION_HASH) -> SystemAuditEvent:
    return build_data_decision_read_audit_event(
        DataDecisionReadAuditObservation(
            dataset_key="equity.price.bar",
            publication_key="current",
            publication_id=PUBLICATION_ID,
            publication_version="1.0:1.0",
            publication_hash=publication_hash_value,
            provider_key="provider-main",
            run_id=RUN_ID,
            ingested_run_id=INGESTED_RUN_ID,
            decision_key="portfolio-readiness",
            freshness_status="fresh",
            outcome=AuditOutcome.RECOVERED,
            occurred_at=NOW + timedelta(minutes=3),
            recorded_at=NOW + timedelta(minutes=3),
            scope=SCOPE,
        ),
        sequence_no=1,
        predecessor_hash=None,
    )


def _freshness_event(
    *,
    publication_hash_value: str = PUBLICATION_HASH,
    freshness_status: str = "fresh",
    must_not_use_for_decision: bool = False,
    blocked_reason: str | None = None,
) -> SystemAuditEvent:
    return build_data_freshness_audit_event(
        DataFreshnessAuditObservation(
            dataset_key="equity.price.bar",
            publication_key="current",
            publication_id=PUBLICATION_ID,
            publication_version="1.0:1.0",
            publication_hash=publication_hash_value,
            provider_key="provider-main",
            run_id=RUN_ID,
            ingested_run_id=INGESTED_RUN_ID,
            freshness_status=freshness_status,
            must_not_use_for_decision=must_not_use_for_decision,
            blocked_reason=blocked_reason,
            occurred_at=NOW + timedelta(minutes=2, seconds=30),
            recorded_at=NOW + timedelta(minutes=2, seconds=30),
            scope=SCOPE,
        ),
        previous_freshness_status="unknown",
        previous_must_not_use_for_decision=None,
        previous_blocked_reason=None,
        sequence_no=1,
        predecessor_hash=None,
    )


def _quality_event(*, quality_state: str = "accepted") -> SystemAuditEvent:
    previous_state = "degraded" if quality_state == "accepted" else "accepted"
    normalized_state = cast(DataQualityState, quality_state)
    normalized_previous = cast(DataQualityState, previous_state)
    event = build_data_quality_audit_event(
        DataQualityAuditObservation(
            dataset_key="equity.price.bar",
            publication_key="current",
            publication_id=PUBLICATION_ID,
            publication_version="1.0:1.0",
            publication_hash=PUBLICATION_HASH,
            provider_key="provider-main",
            run_id=RUN_ID,
            ingested_run_id=INGESTED_RUN_ID,
            quality_state=normalized_state,
            member_count=1,
            quality_status_counts=(
                DataQualityStatusCount(
                    status=normalized_state,
                    count=1,
                ),
            ),
            occurred_at=NOW + timedelta(minutes=2),
            recorded_at=NOW + timedelta(minutes=2),
            scope=SCOPE,
        ),
        previous_quality_state=normalized_previous,
        sequence_no=2,
        predecessor_hash="e" * 64,
    )
    assert event is not None
    return event


def _rollback_evidence() -> PublicationRollback:
    return PublicationRollback(
        target_publication_id=PUBLICATION_ID,
        previous_publication_id=PREVIOUS_PUBLICATION_ID,
        rollback_id=ROLLBACK_ID,
        reason="restore verified prior snapshot",
        operator="operator-1",
        observed_at=NOW + timedelta(minutes=4),
    )


def _rollback_event(*, rollback_content_hash: str | None = None) -> SystemAuditEvent:
    evidence = _rollback_evidence()
    publication_event = _publication_event()
    return build_data_publication_rollback_audit_event(
        DataPublicationRollbackAuditObservation(
            dataset_key="equity.price.bar",
            publication_key="current",
            publication_id=PUBLICATION_ID,
            publication_version="1.0:1.0",
            publication_hash=PUBLICATION_HASH,
            rollback_id=ROLLBACK_ID,
            rollback_version="1",
            rollback_content_hash=(
                rollback_content_hash or publication_rollback_evidence_content_hash(evidence)
            ),
            previous_publication_id=PREVIOUS_PUBLICATION_ID,
            previous_publication_version="1.0:2.0",
            previous_publication_hash=PREVIOUS_PUBLICATION_HASH,
            run_id=RUN_ID,
            occurred_at=evidence.observed_at,
            recorded_at=evidence.observed_at,
            outcome=AuditOutcome.ROLLED_BACK,
            scope=SCOPE,
        ),
        sequence_no=2,
        predecessor_hash=publication_event.content_hash,
    )


def _validation_event() -> SystemAuditEvent:
    return build_data_validation_rejected_event(
        DataValidationRejectedObservation(
            dataset_key="equity.price.bar",
            validator_key="price.v1",
            provider_key="provider-main",
            run_id=RUN_ID,
            ingested_run_id=INGESTED_RUN_ID,
            raw_audit_id="raw-1",
            raw_audit_version="1",
            raw_audit_content_hash=RAW_HASH,
            rejection_reason="schema_rejected",
            error_class="ValueError",
            rejected_count=1,
            occurred_at=NOW + timedelta(seconds=15),
            recorded_at=NOW + timedelta(seconds=15),
            scope=SCOPE,
        ),
        sequence_no=1,
        predecessor_hash=None,
    )


def _raw_audit() -> RawAudit:
    return replace(_RAW_AUDIT, content_hash=RAW_HASH)


def _publication() -> CanonicalPublication:
    return CanonicalPublication(
        publication_id=PUBLICATION_ID,
        dataset_key="equity.price.bar",
        publication_key="current",
        policy_version="1.0:1.0",
        state=PublicationState.PUBLISHED,
        selected_source="provider-main",
        publication_hash=PUBLICATION_HASH,
        coverage=CoverageSnapshot(
            coverage_id="coverage-1",
            publication_id=PUBLICATION_ID,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            generated_at=NOW + timedelta(minutes=2),
        ),
        member_count=1,
        as_of=NOW + timedelta(minutes=1),
        published_at=NOW + timedelta(minutes=2),
        run_id=RUN_ID,
    )


def _previous_publication() -> CanonicalPublication:
    return CanonicalPublication(
        publication_id=PREVIOUS_PUBLICATION_ID,
        dataset_key="equity.price.bar",
        publication_key="current",
        policy_version="1.0:2.0",
        state=PublicationState.SUPERSEDED,
        selected_source="provider-main",
        publication_hash=PREVIOUS_PUBLICATION_HASH,
        coverage=CoverageSnapshot(
            coverage_id="coverage-previous",
            publication_id=PREVIOUS_PUBLICATION_ID,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            generated_at=NOW + timedelta(minutes=3),
        ),
        member_count=1,
        as_of=NOW + timedelta(minutes=2),
        published_at=NOW + timedelta(minutes=3),
        superseded_at=NOW + timedelta(minutes=4),
        run_id="run-previous",
    )


def _rolled_back_publication() -> CanonicalPublication:
    return replace(
        _publication(),
        reinstated_at=NOW + timedelta(minutes=4),
    )


def _member() -> PublicationMember:
    return PublicationMember(
        member_id="member-1",
        publication_id=PUBLICATION_ID,
        dataset_key="equity.price.bar",
        natural_key="000001.SZ:2026-08-27:1d:none:provider-main",
        source="provider-main",
        source_record_id="source-1",
        fact_table="data_center_price_bar",
        fact_pk="fact-1",
        observed_at=NOW,
        raw_payload_hash=RAW_HASH,
    )


class _CorrelationRepository:
    def __init__(self, events: tuple[SystemAuditEvent, ...]) -> None:
        self.events = events

    def list_correlated_events(
        self,
        _run_id: str | None,
        _publication_id: str | None,
        _as_of: datetime,
        _scope: AuditScopeRef,
    ) -> tuple[SystemAuditEvent, ...]:
        return self.events


class _RawReader:
    def __init__(self, audit: RawAudit | None | dict[str, RawAudit]) -> None:
        self.audit = audit

    def get_by_id(self, raw_audit_id: str) -> RawAudit | None:
        if isinstance(self.audit, dict):
            return self.audit.get(raw_audit_id)
        return self.audit


class _PublicationReader:
    def __init__(
        self,
        publication: CanonicalPublication | None,
        members: list[PublicationMember],
        previous_publication: CanonicalPublication | None,
        rollback_evidence: PublicationRollback | None,
    ) -> None:
        self.publication = publication
        self.members = members
        self.previous_publication = previous_publication
        self.rollback_evidence = rollback_evidence

    def get_by_id(self, publication_id: str) -> CanonicalPublication | None:
        if publication_id == PREVIOUS_PUBLICATION_ID:
            return self.previous_publication
        return self.publication

    def list_members(self, _publication_id: str) -> list[PublicationMember]:
        return list(self.members)

    def get_rollback_by_id(self, _rollback_id: str) -> PublicationRollback | None:
        return self.rollback_evidence


class _FactReader:
    def __init__(self, evidence: tuple[ReplayMemberPersistenceEvidence, ...]) -> None:
        self.evidence = evidence

    def list_member_evidence(
        self, _members: tuple[PublicationMember, ...]
    ) -> tuple[ReplayMemberPersistenceEvidence, ...]:
        return self.evidence


def _use_case(
    events: tuple[SystemAuditEvent, ...],
    *,
    raw: RawAudit | None | dict[str, RawAudit] | object = _UNSET,
    publication: CanonicalPublication | None | object = _UNSET,
    members: list[PublicationMember] | object = _UNSET,
    fact_evidence: tuple[ReplayMemberPersistenceEvidence, ...] | object = _UNSET,
    previous_publication: CanonicalPublication | None | object = _UNSET,
    rollback_evidence: PublicationRollback | None | object = _UNSET,
) -> ReplayDataChainUseCase:
    resolved_raw = (
        _raw_audit() if raw is _UNSET else cast(RawAudit | None | dict[str, RawAudit], raw)
    )
    resolved_publication = (
        (
            _rolled_back_publication()
            if any(event.event_type == "data.publication.rolled_back" for event in events)
            else _publication()
        )
        if publication is _UNSET
        else cast(CanonicalPublication | None, publication)
    )
    resolved_members = [_member()] if members is _UNSET else cast(list[PublicationMember], members)
    resolved_fact_evidence = (
        (
            ReplayMemberPersistenceEvidence(
                fact_table="data_center_price_bar",
                fact_pk="fact-1",
                ingested_run_id=INGESTED_RUN_ID,
            ),
        )
        if fact_evidence is _UNSET
        else cast(tuple[ReplayMemberPersistenceEvidence, ...], fact_evidence)
    )
    resolved_previous_publication = (
        _previous_publication()
        if previous_publication is _UNSET
        else cast(CanonicalPublication | None, previous_publication)
    )
    resolved_rollback_evidence = (
        _rollback_evidence()
        if rollback_evidence is _UNSET
        else cast(PublicationRollback | None, rollback_evidence)
    )
    return ReplayDataChainUseCase(
        correlation_query=ListCorrelatedSystemAuditEventsUseCase(_CorrelationRepository(events)),
        raw_audit_reader=_RawReader(resolved_raw),
        publication_reader=_PublicationReader(
            resolved_publication,
            resolved_members,
            resolved_previous_publication,
            resolved_rollback_evidence,
        ),
        fact_evidence_reader=_FactReader(resolved_fact_evidence),
    )


def _command(
    *, run_id: str | None = None, publication_id: str | None = PUBLICATION_ID
) -> DataChainReplayCommand:
    return DataChainReplayCommand(
        run_id=run_id,
        publication_id=publication_id,
        as_of=AS_OF,
        reader=SystemAuditReaderContext._from_authority(
            authority_source_id="authority:7",
            authority_source_version="v1",
            actor_id="django-user:7",
            user_id=7,
            tenant_id=SCOPE.tenant_id,
            owner_id=SCOPE.owner_id,
            authority_content_hash="c" * 64,
            is_authenticated=True,
            is_staff=True,
            role="admin",
            authority_state="active",
            authority_recorded_at=NOW - timedelta(minutes=1),
            authority_valid_until=AS_OF + timedelta(hours=1),
        ),
    )


def test_publication_selector_replays_all_stages_and_exact_member_ingestion() -> None:
    events = (
        _fetch_event(),
        *_failover_events(),
        _publication_event(),
        _decision_read_event(),
    )

    result: DataChainReplayResult = _use_case(events).execute(_command())

    assert result.resolved_run_id == RUN_ID
    assert result.publication_id == PUBLICATION_ID
    assert result.dataset_key == "equity.price.bar"
    assert result.member_count == 1
    assert result.ordered_stage_keys == (
        "data.fetch.completed",
        "data.failover.started",
        "data.failover.succeeded",
        "data.publication.published",
        "data.decision_read.recovered",
    )


def test_replay_validates_exact_publication_rollback_evidence() -> None:
    events = (
        _fetch_event(),
        _publication_event(),
        _decision_read_event(),
        _rollback_event(),
    )

    result = _use_case(events).execute(_command())

    assert result.rollback_ids == (ROLLBACK_ID,)
    assert result.ordered_stage_keys == (
        "data.fetch.completed",
        "data.publication.published",
        "data.decision_read.recovered",
        "data.publication.rolled_back",
    )


def test_replay_rejects_missing_publication_rollback_evidence() -> None:
    events = (
        _fetch_event(),
        _publication_event(),
        _decision_read_event(),
        _rollback_event(),
    )

    with pytest.raises(ReplayUnavailable):
        _use_case(events, rollback_evidence=None).execute(_command())


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {"rollback_evidence": replace(_rollback_evidence(), reason="different")},
            ReplayCorruption,
        ),
        ({"previous_publication": None}, ReplayUnavailable),
        (
            {"previous_publication": replace(_previous_publication(), publication_hash="e" * 64)},
            ReplayCorruption,
        ),
    ],
)
def test_replay_rejects_rollback_evidence_drift(
    changes: dict[str, object], expected: type[Exception]
) -> None:
    events = (
        _fetch_event(),
        _publication_event(),
        _decision_read_event(),
        _rollback_event(),
    )

    with pytest.raises(expected):
        _use_case(events, **changes).execute(_command())


def test_replay_rejects_rollback_event_hash_reference_drift() -> None:
    events = (
        _fetch_event(),
        _publication_event(),
        _decision_read_event(),
        _rollback_event(rollback_content_hash="e" * 64),
    )

    with pytest.raises(ReplayCorruption):
        _use_case(events).execute(_command())


def test_run_selector_replays_the_same_chain() -> None:
    events = (
        _fetch_event(),
        *_failover_events(),
        _publication_event(),
        _decision_read_event(),
    )

    result = _use_case(events).execute(_command(run_id=RUN_ID, publication_id=None))

    assert result.resolved_run_id == RUN_ID
    assert result.publication_id == PUBLICATION_ID
    assert result.member_count == 1


def test_replay_validates_optional_freshness_transition_against_decision_gate() -> None:
    events = (
        _fetch_event(),
        *_failover_events(),
        _publication_event(),
        _freshness_event(),
        _decision_read_event(),
    )

    result = _use_case(events).execute(_command())

    assert result.ordered_stage_keys == (
        "data.fetch.completed",
        "data.failover.started",
        "data.failover.succeeded",
        "data.publication.published",
        "data.freshness.changed",
        "data.decision_read.recovered",
    )


def test_replay_validates_optional_quality_transition_against_member_snapshot() -> None:
    events = (
        _fetch_event(),
        _publication_event(),
        _quality_event(),
        _decision_read_event(),
    )

    result = _use_case(events).execute(_command())

    assert result.quality_state == "accepted"
    assert result.ordered_stage_keys == (
        "data.fetch.completed",
        "data.publication.published",
        "data.quality.changed",
        "data.decision_read.recovered",
    )


def test_replay_rejects_quality_state_drift_from_member_snapshot() -> None:
    events = (
        _fetch_event(),
        _publication_event(),
        _quality_event(quality_state="degraded"),
        _decision_read_event(),
    )

    with pytest.raises(ReplayCorruption):
        _use_case(events).execute(_command())


def test_replay_rejects_degraded_snapshot_without_required_quality_event() -> None:
    degraded_member = replace(_member(), quality_status="error")
    degraded_hash = publication_hash(
        (
            PublicationFactReference(
                natural_key=degraded_member.natural_key,
                source=degraded_member.source,
                source_record_id=degraded_member.source_record_id,
                fact_table=degraded_member.fact_table,
                fact_pk=degraded_member.fact_pk,
                observed_at=NOW,
                raw_payload_hash=degraded_member.raw_payload_hash,
                quality_status=degraded_member.quality_status,
                revision_number=degraded_member.revision_number,
            ),
        )
    )
    degraded_publication = replace(_publication(), publication_hash=degraded_hash)
    events = (
        _fetch_event(),
        _publication_event(publication_hash_value=degraded_hash),
        _decision_read_event(publication_hash_value=degraded_hash),
    )

    with pytest.raises(ReplayCorruption):
        _use_case(
            events,
            publication=degraded_publication,
            members=[degraded_member],
        ).execute(_command())


@pytest.mark.parametrize(
    "freshness_event",
    [
        _freshness_event(publication_hash_value="d" * 64),
        _freshness_event(
            freshness_status="stale",
            must_not_use_for_decision=True,
            blocked_reason="canonical_publication_stale",
        ),
    ],
)
def test_replay_rejects_freshness_evidence_or_state_drift(
    freshness_event: SystemAuditEvent,
) -> None:
    events = (
        _fetch_event(),
        *_failover_events(),
        _publication_event(),
        freshness_event,
        _decision_read_event(),
    )

    with pytest.raises(ReplayCorruption):
        _use_case(events).execute(_command())


def test_failover_replay_accepts_and_revalidates_the_verification_fetch() -> None:
    events = (
        _fetch_event(),
        _verification_fetch_event(),
        *_failover_events(),
        _publication_event(),
        _decision_read_event(),
    )

    result = _use_case(
        events,
        raw={
            "raw-1": _raw_audit(),
            "raw-2": replace(_VERIFIER_RAW_AUDIT, content_hash=VERIFIER_RAW_HASH),
        },
    ).execute(_command())

    assert result.publication_id == PUBLICATION_ID
    assert result.ordered_stage_keys[0] == "data.fetch.completed"


@pytest.mark.parametrize(
    "events,raw,publication,members,fact_evidence",
    [
        ((_publication_event(), _decision_read_event()), _UNSET, _UNSET, _UNSET, _UNSET),
        (
            (_fetch_event(), *_failover_events(), _decision_read_event()),
            _UNSET,
            _UNSET,
            _UNSET,
            _UNSET,
        ),
        (
            (_fetch_event(), *_failover_events(), _publication_event()),
            _UNSET,
            _UNSET,
            _UNSET,
            _UNSET,
        ),
        (
            (
                _fetch_event(),
                *_failover_events(),
                _publication_event(),
                _decision_read_event(),
            ),
            None,
            _UNSET,
            _UNSET,
            _UNSET,
        ),
        (
            (
                _fetch_event(),
                *_failover_events(),
                _publication_event(),
                _decision_read_event(),
            ),
            replace(_raw_audit(), content_hash="d" * 64),
            _UNSET,
            _UNSET,
            _UNSET,
        ),
        (
            (
                _fetch_event(),
                *_failover_events(),
                _publication_event(),
                _decision_read_event(),
            ),
            replace(_raw_audit(), run_id="run-2"),
            _UNSET,
            _UNSET,
            _UNSET,
        ),
        (
            (
                _fetch_event(),
                *_failover_events(),
                _publication_event(),
                _decision_read_event(),
            ),
            _UNSET,
            None,
            _UNSET,
            _UNSET,
        ),
        (
            (
                _fetch_event(),
                *_failover_events(),
                _publication_event(),
                _decision_read_event(),
            ),
            _UNSET,
            replace(_publication(), publication_hash="d" * 64),
            _UNSET,
            _UNSET,
        ),
        (
            (
                _fetch_event(),
                *_failover_events(),
                _publication_event(),
                _decision_read_event(),
            ),
            _UNSET,
            replace(_publication(), policy_version="other"),
            _UNSET,
            _UNSET,
        ),
        (
            (
                _fetch_event(),
                *_failover_events(),
                _publication_event(),
                _decision_read_event(),
            ),
            _UNSET,
            replace(_publication(), run_id="run-2"),
            _UNSET,
            _UNSET,
        ),
        (
            (
                _fetch_event(),
                *_failover_events(),
                _publication_event(),
                _decision_read_event(),
            ),
            _UNSET,
            _UNSET,
            [],
            _UNSET,
        ),
        (
            (
                _fetch_event(),
                *_failover_events(),
                _publication_event(),
                _decision_read_event(),
            ),
            _UNSET,
            _UNSET,
            [_member(), _member()],
            _UNSET,
        ),
        (
            (
                _fetch_event(),
                *_failover_events(),
                _publication_event(),
                _decision_read_event(),
            ),
            _UNSET,
            _UNSET,
            _UNSET,
            (),
        ),
        (
            (
                _fetch_event(),
                *_failover_events(),
                _publication_event(),
                _decision_read_event(),
            ),
            _UNSET,
            _UNSET,
            _UNSET,
            (ReplayMemberPersistenceEvidence("data_center_price_bar", "fact-1", "run-2"),),
        ),
        (
            (
                _fetch_event(),
                _validation_event(),
                *_failover_events(),
                _publication_event(),
                _decision_read_event(),
            ),
            _UNSET,
            _UNSET,
            _UNSET,
            _UNSET,
        ),
        (
            (
                _fetch_event(),
                _failover_events()[0],
                _publication_event(),
                _decision_read_event(),
            ),
            _UNSET,
            _UNSET,
            _UNSET,
            _UNSET,
        ),
        (
            (
                _fetch_event(),
                *_failover_events(terminal_outcome=AuditOutcome.BLOCKED),
                _publication_event(),
                _decision_read_event(),
            ),
            _UNSET,
            _UNSET,
            _UNSET,
            _UNSET,
        ),
        (
            (
                _fetch_event(),
                *_exhausted_failover_events(),
                _publication_event(),
                _decision_read_event(),
            ),
            _UNSET,
            _UNSET,
            _UNSET,
            _UNSET,
        ),
    ],
)
def test_missing_or_tampered_chain_evidence_fails_closed(
    events: tuple[SystemAuditEvent, ...],
    raw: object,
    publication: object,
    members: object,
    fact_evidence: object,
) -> None:
    with pytest.raises((ReplayUnavailable, ReplayCorruption)):
        _use_case(
            events,
            raw=raw,
            publication=publication,
            members=members,
            fact_evidence=fact_evidence,
        ).execute(_command())


@pytest.mark.parametrize(
    "run_id,publication_id",
    [(None, None), ("", None), (" run-1", None), ("run-1", PUBLICATION_ID)],
)
def test_replay_command_requires_one_valid_selector(
    run_id: str | None, publication_id: str | None
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _command(run_id=run_id, publication_id=publication_id)


def test_pit_cutoff_and_reader_authority_are_enforced() -> None:
    future_event = replace(_fetch_event(), recorded_at=AS_OF + timedelta(minutes=1))
    with pytest.raises((ReplayUnavailable, ReplayCorruption)):
        _use_case(
            (
                future_event,
                *_failover_events(),
                _publication_event(),
                _decision_read_event(),
            )
        ).execute(_command())
