"""RED contracts for replaying one canonical repair parent run."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Protocol

import pytest

from apps.audit.application.data_repair_audit import (
    DataRepairAuditObservation,
    RepairPublicationEvidence,
    RepairSectionEvidence,
    build_data_repair_audit_event,
)
from apps.audit.application.system_audit_query import SystemAuditReaderContext
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef, SystemAuditEvent
from apps.data_center.application.data_chain_replay import (
    DataChainReplayResult,
    ReplayCorruption,
    ReplayUnavailable,
)
from apps.data_center.application.repair_run_replay import (
    RepairRunReplayCommand,
    RepairRunReplayCorruption,
    RepairRunReplayUnavailable,
    ReplayRepairRunUseCase,
)
from apps.data_center.application.sync_identity import (
    SyncExecutionIdentity,
    build_sync_execution_identity,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
SCOPE = AuditScopeRef("tenant:research", "owner:alice")
IDENTITY = build_sync_execution_identity(
    run_id="00000000-0000-4000-8000-000000000001",
    ingested_run_id="00000000-0000-4000-8000-000000000002",
    batch_id="00000000-0000-4000-8000-000000000003",
    dataset_key="decision.reliability.repair",
    provider_name="data-center-repair",
)


def _reader() -> SystemAuditReaderContext:
    """Build the valid staff reader context required by PIT audit queries."""

    return SystemAuditReaderContext._from_authority(
        authority_source_id="authority-source",
        authority_source_version="1",
        actor_id="actor-1",
        user_id=1,
        tenant_id="tenant:research",
        owner_id="owner:alice",
        authority_content_hash="a" * 64,
        is_authenticated=True,
        is_staff=True,
        role="staff",
        authority_state="active",
        authority_recorded_at=datetime(2026, 8, 27, 10, 0, tzinfo=UTC),
        authority_valid_until=datetime(2026, 8, 27, 18, 0, tzinfo=UTC),
    )


def _event(
    *,
    publication_id: str | None = None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
) -> SystemAuditEvent:
    """Build a valid parent completion event with optional publication evidence."""

    publications = ()
    if publication_id is not None:
        publications = (
            RepairPublicationEvidence(
                publication_id=publication_id,
                publication_version="7",
                publication_hash="b" * 64,
                dataset_key="equity.price.bar",
            ),
        )
    blocked = outcome is not AuditOutcome.SUCCESS
    section_status = (
        "failed" if outcome is AuditOutcome.FAILED else ("blocked" if blocked else "ready")
    )
    observation = DataRepairAuditObservation(
        identity=IDENTITY,
        target_date=date(2026, 8, 27),
        sections=(
            RepairSectionEvidence(
                section_key="macro",
                status=section_status,
                must_not_use_for_decision=blocked,
                remaining_blocker_count=1 if blocked else 0,
            ),
        ),
        publications=publications,
        outcome=outcome,
        occurred_at=NOW,
        recorded_at=NOW,
        scope=SCOPE,
    )
    return build_data_repair_audit_event(observation, sequence_no=1, predecessor_hash=None)


@dataclass(frozen=True)
class _Correlation:
    events: tuple[SystemAuditEvent, ...]
    resolved_run_id: str


class _CorrelationQuery(Protocol):
    def execute(self, command: object) -> _Correlation:
        """Return the parent-run event set at the requested PIT."""


class _IdentityReader(Protocol):
    def get_by_identity_hash(self, identity_hash: str) -> SyncExecutionIdentity | None:
        """Return the persisted identity selected by exact hash."""


class _PublicationReplay(Protocol):
    def execute(self, command: object) -> DataChainReplayResult:
        """Replay one child canonical publication."""


@dataclass
class _FakeCorrelationQuery:
    correlation: _Correlation
    commands: list[object]

    def execute(self, command: object) -> _Correlation:
        self.commands.append(command)
        return self.correlation


@dataclass
class _FakeIdentityReader:
    identity: SyncExecutionIdentity | None
    hashes: list[str]

    def get_by_identity_hash(self, identity_hash: str) -> SyncExecutionIdentity | None:
        self.hashes.append(identity_hash)
        return self.identity


@dataclass
class _FakePublicationReplay:
    result: DataChainReplayResult
    commands: list[object]
    failure: BaseException | None = None

    def execute(self, command: object) -> DataChainReplayResult:
        self.commands.append(command)
        if self.failure is not None:
            raise self.failure
        return self.result


def _use_case(
    event: SystemAuditEvent,
    *,
    identity: SyncExecutionIdentity | None = IDENTITY,
    publication_result: DataChainReplayResult | None = None,
    publication_failure: BaseException | None = None,
) -> tuple[
    ReplayRepairRunUseCase, _FakeCorrelationQuery, _FakeIdentityReader, _FakePublicationReplay
]:
    """Build the intended replay composition entirely with typed fakes."""

    correlation = _FakeCorrelationQuery(_Correlation((event,), IDENTITY.run_id), [])
    identity_reader = _FakeIdentityReader(identity, [])
    child_result = publication_result or DataChainReplayResult(
        resolved_run_id="00000000-0000-4000-8000-000000000005",
        ingested_run_id="00000000-0000-4000-8000-000000000006",
        publication_id="00000000-0000-4000-8000-000000000004",
        publication_version="7",
        publication_hash="b" * 64,
        dataset_key="equity.price.bar",
        member_count=1,
        decision_outcome="recovered",
        ordered_stage_keys=("fetch", "persist", "publish", "read"),
    )
    publication_replay = _FakePublicationReplay(child_result, [], publication_failure)
    use_case = ReplayRepairRunUseCase(
        correlation_query=correlation,
        identity_reader=identity_reader,
        publication_replay=publication_replay,
    )
    return use_case, correlation, identity_reader, publication_replay


def test_repair_run_replay_requires_exact_parent_and_identity_evidence() -> None:
    """A parent run replay must verify the persisted identity before children."""

    publication_id = "00000000-0000-4000-8000-000000000004"
    use_case, correlation, identity_reader, publication_replay = _use_case(
        _event(publication_id=publication_id)
    )

    result = use_case.execute(RepairRunReplayCommand(IDENTITY.run_id, NOW, _reader()))

    assert result.resolved_run_id == IDENTITY.run_id
    assert result.identity_hash == IDENTITY.identity_hash
    assert result.publication_ids == (publication_id,)
    assert correlation.commands
    assert identity_reader.hashes == [IDENTITY.identity_hash]
    assert len(publication_replay.commands) == 1


@pytest.mark.parametrize("outcome", ["partial", "failed"])
def test_partial_or_failed_parent_may_have_zero_publications(outcome: str) -> None:
    """Incomplete repair outcomes remain replayable without publication children."""

    event = _event(outcome=AuditOutcome(outcome))
    use_case, _, _, publication_replay = _use_case(event)

    result = use_case.execute(RepairRunReplayCommand(IDENTITY.run_id, NOW, _reader()))

    assert result.publication_ids == ()
    assert publication_replay.commands == []


def test_success_parent_without_publication_fails_closed() -> None:
    """A successful repair must not replay as complete without publication evidence."""

    use_case, _, _, _ = _use_case(_event())

    with pytest.raises(RepairRunReplayCorruption):
        use_case.execute(RepairRunReplayCommand(IDENTITY.run_id, NOW, _reader()))


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("publication_id", "00000000-0000-4000-8000-000000000099"),
        ("publication_version", "8"),
        ("publication_hash", "c" * 64),
        ("dataset_key", "equity.quote.snapshot"),
    ],
)
def test_child_replay_must_match_every_parent_publication_field(
    field_name: str,
    value: str,
) -> None:
    """A child replay cannot substitute any exact publication coordinate."""

    publication_id = "00000000-0000-4000-8000-000000000004"
    base = DataChainReplayResult(
        resolved_run_id="00000000-0000-4000-8000-000000000005",
        ingested_run_id="00000000-0000-4000-8000-000000000006",
        publication_id=publication_id,
        publication_version="7",
        publication_hash="b" * 64,
        dataset_key="equity.price.bar",
        member_count=1,
        decision_outcome="recovered",
        ordered_stage_keys=("fetch", "publish", "read"),
    )
    use_case, _, _, _ = _use_case(
        _event(publication_id=publication_id),
        publication_result=replace(base, **{field_name: value}),
    )

    with pytest.raises(RepairRunReplayCorruption):
        use_case.execute(RepairRunReplayCommand(IDENTITY.run_id, NOW, _reader()))


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (ReplayUnavailable(), RepairRunReplayUnavailable),
        (ReplayCorruption(), RepairRunReplayCorruption),
    ],
)
def test_child_replay_failures_are_mapped_fail_closed(
    failure: BaseException,
    expected: type[BaseException],
) -> None:
    """A missing or corrupt child prevents a verified parent replay."""

    use_case, _, _, _ = _use_case(
        _event(publication_id="00000000-0000-4000-8000-000000000004"),
        publication_failure=failure,
    )

    with pytest.raises(expected):
        use_case.execute(RepairRunReplayCommand(IDENTITY.run_id, NOW, _reader()))


@pytest.mark.parametrize("tamper", ["identity", "hash", "scope", "missing", "duplicate"])
def test_parent_or_child_tampering_fails_closed(tamper: str) -> None:
    """Missing, duplicate, scope-crossed, and hash-tampered evidence is rejected."""

    event = _event(publication_id="00000000-0000-4000-8000-000000000004")
    identity: SyncExecutionIdentity | None = IDENTITY
    if tamper == "identity":
        identity = None
    if tamper == "hash":
        event = replace(event, content_hash="c" * 64)
    if tamper == "scope":
        event = replace(event, scope=AuditScopeRef("tenant:other", "owner:alice"))
    if tamper == "missing":
        event = replace(event, evidence_refs=())
    if tamper == "duplicate":
        event = replace(event, detail={**event.detail, "publications": []})
    use_case, _, _, _ = _use_case(event, identity=identity)

    with pytest.raises((RepairRunReplayCorruption, RepairRunReplayUnavailable)):
        use_case.execute(RepairRunReplayCommand(IDENTITY.run_id, NOW, _reader()))


def test_replay_command_rejects_invalid_selector_or_pit() -> None:
    """Replay selectors and PIT boundaries must be canonical and aware."""

    with pytest.raises(ValueError):
        RepairRunReplayCommand("", NOW, _reader())
    with pytest.raises(ValueError):
        RepairRunReplayCommand(IDENTITY.run_id, datetime(2026, 8, 27, 12, 0), _reader())
