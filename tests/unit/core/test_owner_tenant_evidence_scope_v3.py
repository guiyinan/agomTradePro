"""Unit contracts for the Authority V3 to Research Evidence read bridge."""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TypeVar, cast

import pytest

from apps.account.application.owner_tenant_authority_v3 import (
    CurrentOwnerTenantAuthorityV3,
    GetCurrentOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    OwnerTenantAuthorityV3Conflict,
    OwnerTenantAuthorityV3Corruption,
    OwnerTenantAuthorityV3Unavailable,
)
from apps.research.application.evidence_scope import (
    EvidenceScopeCorruption,
    EvidenceScopeUnavailable,
)
from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    ClaimKind,
    DecisionPermission,
    DependencyFlag,
    EvidenceEnvelope,
    EvidenceOperatorSpec,
    GovernanceState,
    MethodKind,
    TrackRecordSnapshot,
)
from core.integration.owner_tenant_evidence_scope_v3 import (
    MAX_SCOPE_TTL,
    OwnerTenantAuthorityV3EvidenceReadFacade,
)
from tests.unit.account.test_owner_tenant_authority_v3_application import (
    _current_command,
    _World,
)

_Result = TypeVar("_Result")


class _Clock:
    """Controllable server clock for deterministic scope tests."""

    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        """Return the current test server time."""

        return self.current


class _SequenceClock:
    """Return deterministic server times for boundary and rollback tests."""

    def __init__(self, values: list[datetime]) -> None:
        self.values = values
        self.index = 0

    def now(self) -> datetime:
        """Return the next configured server time, retaining the last value."""

        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return value


class _CurrentReader:
    """Fake Authority V3 facade port retaining callback and final-check events."""

    unit_of_work_key = "django:owner-test"

    def __init__(self, current: CurrentOwnerTenantAuthorityV3 | None) -> None:
        self.current = current
        self.calls: list[GetCurrentOwnerTenantAuthorityV3Command] = []
        self.events: list[str] = []
        self.discard_after_read = False
        self.failure: Exception | None = None

    def with_current(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
        operation: Callable[[CurrentOwnerTenantAuthorityV3], _Result | None],
    ) -> _Result | None:
        """Run the callback while simulating the Authority V3 final recheck."""

        self.calls.append(command)
        self.events.append("authority-enter")
        if self.failure is not None:
            raise self.failure
        if self.current is None:
            self.events.extend(("authority-empty", "authority-exit"))
            return None
        result = operation(self.current)
        self.events.append("authority-final")
        if self.discard_after_read:
            self.events.append("authority-exit")
            return None
        self.events.append("authority-exit")
        return result


class _EvidenceReads:
    """Fake same-alias Research port that records exact selectors."""

    unit_of_work_key = "django:owner-test"

    def __init__(
        self,
        operator: object,
        track: object,
        envelope: object,
    ) -> None:
        self.operator = operator
        self.track = track
        self.envelope = envelope
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.after_read: Callable[[], None] | None = None

    def get_operator_spec(
        self,
        *,
        operator_id: str,
        operator_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> object:
        """Return a configured OperatorSpec or substitution fixture."""

        self.calls.append(
            (
                "operator",
                {
                    "operator_id": operator_id,
                    "operator_version": operator_version,
                    "expected_content_hash": expected_content_hash,
                    "as_of": as_of,
                },
            )
        )
        if self.after_read is not None:
            self.after_read()
        return self.operator

    def get_track_record(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> object:
        """Return a configured TrackRecord snapshot or substitution fixture."""

        self.calls.append(
            (
                "track",
                {
                    "snapshot_id": snapshot_id,
                    "snapshot_version": snapshot_version,
                    "expected_content_hash": expected_content_hash,
                    "as_of": as_of,
                },
            )
        )
        if self.after_read is not None:
            self.after_read()
        return self.track

    def get_envelope(
        self,
        *,
        output_owner: str,
        output_artifact_type: str,
        output_artifact_id: str,
        output_artifact_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> object:
        """Return a configured EvidenceEnvelope or substitution fixture."""

        self.calls.append(
            (
                "envelope",
                {
                    "output_owner": output_owner,
                    "output_artifact_type": output_artifact_type,
                    "output_artifact_id": output_artifact_id,
                    "output_artifact_version": output_artifact_version,
                    "expected_content_hash": expected_content_hash,
                    "as_of": as_of,
                },
            )
        )
        if self.after_read is not None:
            self.after_read()
        return self.envelope


def _operator(anchor: datetime) -> EvidenceOperatorSpec:
    """Build one valid OperatorSpec fixture."""

    return EvidenceOperatorSpec.create(
        operator_id="operator-1",
        operator_version="v1",
        research_family="family-1",
        output_artifact_type="model-output",
        claim_kind=ClaimKind.OBSERVATION,
        method_kind=MethodKind.DETERMINISTIC,
        required_input_roles=("price",),
        dependency_flags=frozenset({DependencyFlag.ESTIMATED_INPUT}),
        maximum_permission=DecisionPermission.DECISION_ELIGIBLE,
        requires_track_record=False,
        activated_at=anchor - timedelta(hours=1),
        valid_until=anchor + timedelta(hours=4),
    )


def _track(anchor: datetime) -> TrackRecordSnapshot:
    """Build one valid empty TrackRecord snapshot fixture."""

    return TrackRecordSnapshot(
        snapshot_id="track-1",
        snapshot_version="v1",
        artifact=ArtifactRef(
            owner="research",
            artifact_type="track_record_snapshot",
            artifact_id="track-1",
            artifact_version="v1",
            content_hash="b" * 64,
        ),
        target="target-1",
        horizon="1d",
        sample_policy_id="sample-policy-1",
        sample_policy_version="v1",
        evaluated_at=anchor - timedelta(hours=1),
        valid_until=anchor + timedelta(hours=4),
        eligible=0,
        resolved=0,
        unresolved=0,
        censored=0,
        invalidated=0,
        n_eff=Decimal("0"),
        coverage=Decimal("0"),
        market_regimes=(),
        primary_metric_code=None,
        primary_metric_unit=None,
        metric_direction=None,
        primary_metric_value=None,
        benchmark_metric_value=None,
        skill_delta=None,
        confidence_interval_low=None,
        confidence_interval_high=None,
        drift_detected=False,
        promotion_ref=ArtifactRef(
            owner="research",
            artifact_type="promotion",
            artifact_id="promotion-1",
            artifact_version="v1",
            content_hash="c" * 64,
        ),
        outcome_refs=(),
        content_hash="",
    )


def _envelope(operator: EvidenceOperatorSpec, anchor: datetime) -> EvidenceEnvelope:
    """Build one valid output EvidenceEnvelope fixture."""

    return EvidenceEnvelope(
        output_artifact=ArtifactRef(
            owner="portfolio-output",
            artifact_type="model-output",
            artifact_id="output-1",
            artifact_version="v1",
            content_hash="d" * 64,
        ),
        operator_spec_ref=operator.artifact_ref,
        claim_kind=ClaimKind.OBSERVATION,
        method_kind=MethodKind.DETERMINISTIC,
        research_family="family-1",
        governance_state=GovernanceState.RESEARCH_ONLY,
        permission=DecisionPermission.DISPLAY_ONLY,
        lineage=(operator.artifact_ref,),
        dependency_flags=frozenset({DependencyFlag.ESTIMATED_INPUT}),
        track_record_ref=None,
        blockers=(),
        evaluated_at=anchor - timedelta(hours=1),
        valid_until=anchor + timedelta(hours=4),
        content_hash="",
    )


@pytest.fixture
def evidence_world() -> tuple[
    _World,
    CurrentOwnerTenantAuthorityV3,
    GetCurrentOwnerTenantAuthorityV3Command,
]:
    """Issue one V3 authority and obtain its current observation."""

    world = _World()
    decision = world.service().issue(world.issue_command())
    world.repository.clocks = [decision.recorded_at + timedelta(seconds=1)]
    current = world.service().get_current(_current_command(decision))
    assert current is not None
    return world, current, _current_command(decision)


@pytest.fixture
def read_fixtures(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
) -> tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope]:
    """Build all three exact Research DTO fixtures around the live observation."""

    anchor = evidence_world[1].observed_at
    operator = _operator(anchor)
    track = _track(anchor)
    return operator, track, _envelope(operator, anchor)


def _bound_envelope(envelope: EvidenceEnvelope) -> ArtifactRef:
    """Build the server-bound envelope identity from its own content hash."""

    return ArtifactRef(
        owner=envelope.output_artifact.owner,
        artifact_type=envelope.output_artifact.artifact_type,
        artifact_id=envelope.output_artifact.artifact_id,
        artifact_version=envelope.output_artifact.artifact_version,
        content_hash=envelope.content_hash,
    )


def _facade(
    *,
    current: CurrentOwnerTenantAuthorityV3 | None,
    selector: GetCurrentOwnerTenantAuthorityV3Command,
    reads: _EvidenceReads,
    clock: object,
    artifacts: frozenset[ArtifactRef],
    scope_ttl: timedelta = timedelta(minutes=5),
) -> tuple[OwnerTenantAuthorityV3EvidenceReadFacade, _CurrentReader]:
    """Compose the V3 bridge with fake same-alias ports."""

    authority = _CurrentReader(current)
    facade = OwnerTenantAuthorityV3EvidenceReadFacade(
        authority_reader=authority,
        evidence_reader=reads,
        authority_command=selector,
        server_bound_artifacts=artifacts,
        scope_ttl=scope_ttl,
        using="owner-test",
        clock=cast(object, clock),
    )
    return facade, authority


def test_current_v3_authorizes_all_exact_historical_reads(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """Materialize Operator, TrackRecord, and Envelope only inside V3 callback."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    cutoff = current.observed_at - timedelta(seconds=1)
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({operator.artifact_ref, track.artifact_ref, _bound_envelope(envelope)}),
    )

    assert (
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=cutoff,
        )
        is operator
    )
    assert (
        facade.get_track_record(
            snapshot_id=track.snapshot_id,
            snapshot_version=track.snapshot_version,
            expected_content_hash=track.content_hash,
            evidence_as_of=cutoff,
        )
        is track
    )
    assert (
        facade.get_envelope(
            output_owner=envelope.output_artifact.owner,
            output_artifact_type=envelope.output_artifact.artifact_type,
            output_artifact_id=envelope.output_artifact.artifact_id,
            output_artifact_version=envelope.output_artifact.artifact_version,
            expected_content_hash=envelope.content_hash,
            evidence_as_of=cutoff,
        )
        is envelope
    )
    assert authority.calls == [selector, selector, selector]
    assert [call[1]["as_of"] for call in reads.calls] == [cutoff, cutoff, cutoff]


def test_unknown_allowlist_artifact_is_rejected_before_authorization(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """A client-selected identity outside the server allowlist cannot read."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({operator.artifact_ref}),
    )

    assert (
        facade.get_track_record(
            snapshot_id=track.snapshot_id,
            snapshot_version=track.snapshot_version,
            expected_content_hash=track.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
        is None
    )
    assert authority.calls == []
    assert reads.calls == []


def test_allowlist_requires_nonempty_exact_artifact_refs_and_short_ttl(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """Construction freezes exact artifacts and enforces the five-minute cap."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    with pytest.raises(TypeError, match="nonempty"):
        _facade(
            current=current,
            selector=selector,
            reads=reads,
            clock=_Clock(current.observed_at),
            artifacts=frozenset(),
        )
    with pytest.raises(ValueError, match="five-minute"):
        _facade(
            current=current,
            selector=selector,
            reads=reads,
            clock=_Clock(current.observed_at),
            artifacts=frozenset({operator.artifact_ref}),
            scope_ttl=MAX_SCOPE_TTL + timedelta(microseconds=1),
        )
    with pytest.raises(TypeError, match="exact ArtifactRef"):
        _facade(
            current=current,
            selector=selector,
            reads=reads,
            clock=_Clock(current.observed_at),
            artifacts=cast(frozenset[ArtifactRef], frozenset({object()})),
        )
    assert track is not None and envelope is not None


def test_future_or_naive_pit_cutoff_is_rejected_without_current_read(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """An explicit aware PIT cutoff cannot select future evidence or future time."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({operator.artifact_ref}),
    )
    assert (
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at + timedelta(seconds=1),
        )
        is None
    )
    with pytest.raises(TypeError, match="timezone-aware"):
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at.replace(tzinfo=None),
        )
    assert authority.calls == []
    assert reads.calls == []
    assert track is not None and envelope is not None


def test_missing_current_authority_never_touches_evidence(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """An absent, expired, or revoked current V3 observation fails closed."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    facade, authority = _facade(
        current=None,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({operator.artifact_ref}),
    )
    assert (
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
        is None
    )
    assert authority.calls == [selector]
    assert reads.calls == []
    assert track is not None and envelope is not None


@pytest.mark.parametrize(
    "failure",
    [OwnerTenantAuthorityV3Unavailable("offline"), OwnerTenantAuthorityV3Conflict("race")],
)
def test_authority_unavailable_or_conflict_maps_to_none(
    failure: Exception,
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """The V3 authority failure classes never expose provider details."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({operator.artifact_ref}),
    )
    authority.failure = failure

    assert (
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
        is None
    )
    assert reads.calls == []
    assert track is not None and envelope is not None


def test_authority_corruption_maps_to_scope_corruption(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """Persisted or source corruption remains distinguishable from unavailability."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({operator.artifact_ref}),
    )
    authority.failure = OwnerTenantAuthorityV3Corruption("sensitive provider detail")

    with pytest.raises(EvidenceScopeCorruption, match="corrupt") as error:
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
    assert "sensitive provider detail" not in str(error.value)
    assert reads.calls == []
    assert track is not None and envelope is not None


def test_v3_current_authority_selector_and_type_substitution_are_corruption(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """V2/V4 or another Authority V3 identity cannot cross the current port."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    substituted_authority = replace(
        current.authority,
        authority_id="other-authority",
        identity_hash="",
        content_hash="",
    )
    facade, authority = _facade(
        current=replace(current, authority=substituted_authority),
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({operator.artifact_ref}),
    )
    with pytest.raises(EvidenceScopeCorruption, match="selector"):
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
    assert authority.calls == [selector]
    assert reads.calls == []

    invalid_current = cast(CurrentOwnerTenantAuthorityV3, object())
    facade, authority = _facade(
        current=invalid_current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({operator.artifact_ref}),
    )
    with pytest.raises(EvidenceScopeCorruption, match="type substitution"):
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
    assert authority.calls == [selector]
    assert track is not None and envelope is not None


def test_authority_source_recheck_discards_materialized_result(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """A source or actor substitution detected by Authority final recheck discards DTO."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({operator.artifact_ref}),
    )
    authority.discard_after_read = True

    assert (
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
        is None
    )
    assert authority.events == ["authority-enter", "authority-final", "authority-exit"]
    assert len(reads.calls) == 1
    assert track is not None and envelope is not None


def test_evidence_result_identity_and_type_substitution_are_corruption(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """Research cannot substitute an immutable DTO or its exact artifact identity."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    foreign = replace(operator, operator_id="operator-other", content_hash="")
    reads = _EvidenceReads(foreign, track, envelope)
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({operator.artifact_ref}),
    )
    with pytest.raises(EvidenceScopeCorruption, match="selector"):
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
    assert authority.calls == [selector]
    assert len(reads.calls) == 1

    reads = _EvidenceReads(cast(object, object()), track, envelope)
    facade, _ = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({operator.artifact_ref}),
    )
    with pytest.raises(EvidenceScopeCorruption, match="invalid Operator type"):
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )


def test_future_evidence_dto_is_rejected_at_historical_cutoff(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """A future activated Operator result cannot be made historical by current V3 auth."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    future = _operator(current.observed_at + timedelta(hours=1))
    reads = _EvidenceReads(future, track, envelope)
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({future.artifact_ref}),
    )
    with pytest.raises(EvidenceScopeCorruption, match="PIT"):
        facade.get_operator_spec(
            operator_id=future.operator_id,
            operator_version=future.operator_version,
            expected_content_hash=future.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
    assert authority.calls == [selector]
    assert len(reads.calls) == 1
    assert operator is not future and track is not None and envelope is not None


def test_clock_expiry_before_and_after_materialization_fails_closed(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """The request TTL is checked before the repository call and on return."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    clock = _SequenceClock(
        [
            current.observed_at,
            current.observed_at + timedelta(seconds=2),
        ]
    )
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=clock,
        artifacts=frozenset({operator.artifact_ref}),
        scope_ttl=timedelta(seconds=1),
    )
    assert (
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
        is None
    )
    assert authority.calls == [selector]
    assert reads.calls == []

    reads = _EvidenceReads(operator, track, envelope)
    clock = _Clock(current.observed_at)

    def expire() -> None:
        """Advance the server clock while Research is materializing."""

        clock.current = current.observed_at + timedelta(seconds=2)

    reads.after_read = expire
    facade, _ = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=clock,
        artifacts=frozenset({operator.artifact_ref}),
        scope_ttl=timedelta(seconds=1),
    )
    assert (
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
        is None
    )
    assert track is not None and envelope is not None


def test_clock_regression_is_scope_corruption_and_never_returns_dto(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """Every server sample must be monotonic across the callback boundary."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    now = current.observed_at
    reads = _EvidenceReads(operator, track, envelope)
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_SequenceClock(
            [
                now,
                now + timedelta(seconds=5),
                now + timedelta(seconds=1),
            ]
        ),
        artifacts=frozenset({operator.artifact_ref}),
    )
    result = facade.get_operator_spec(
        operator_id=operator.operator_id,
        operator_version=operator.operator_version,
        expected_content_hash=operator.content_hash,
        evidence_as_of=now - timedelta(seconds=1),
    )
    assert result is None
    assert authority.calls == [selector]
    assert len(reads.calls) == 1
    assert track is not None and envelope is not None


def test_clock_watermark_is_request_local_and_does_not_poison_the_next_read(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """A later request may use a fresh lower clock without shared facade state."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    clock = _SequenceClock(
        [
            current.observed_at,
            current.observed_at,
            current.observed_at + timedelta(seconds=1),
            current.observed_at + timedelta(seconds=1),
        ]
    )
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=clock,
        artifacts=frozenset({operator.artifact_ref}),
    )
    kwargs = {
        "operator_id": operator.operator_id,
        "operator_version": operator.operator_version,
        "expected_content_hash": operator.content_hash,
        "evidence_as_of": current.observed_at - timedelta(seconds=1),
    }
    assert facade.get_operator_spec(**kwargs) is operator

    clock.values = [current.observed_at] * 4
    clock.index = 0
    assert facade.get_operator_spec(**kwargs) is operator
    assert authority.calls == [selector, selector]
    assert len(reads.calls) == 2
    assert track is not None and envelope is not None


def test_nonresearch_envelope_requires_full_server_bound_identity(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """Envelope output ownership may vary only through a complete allowlist entry."""

    _, current, selector = evidence_world
    operator, _, envelope = read_fixtures
    output = _bound_envelope(envelope)
    reads = _EvidenceReads(operator, _track(current.observed_at), envelope)
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({output}),
    )
    assert (
        facade.get_envelope(
            output_owner=output.owner,
            output_artifact_type=output.artifact_type,
            output_artifact_id=output.artifact_id,
            output_artifact_version=output.artifact_version,
            expected_content_hash=output.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
        is envelope
    )
    assert authority.calls == [selector]
    assert len(reads.calls) == 1


def test_unexpected_provider_failure_is_sanitized(
    evidence_world: tuple[
        _World,
        CurrentOwnerTenantAuthorityV3,
        GetCurrentOwnerTenantAuthorityV3Command,
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """Implementation exceptions cannot cross the stable Evidence scope boundary."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({operator.artifact_ref}),
    )
    authority.failure = RuntimeError("session secret must not escape")
    with pytest.raises(EvidenceScopeUnavailable, match="unavailable") as error:
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
    assert "session secret" not in str(error.value)
    assert reads.calls == []
    assert track is not None and envelope is not None


def test_scope_integration_source_has_no_account_infrastructure_or_old_versions() -> None:
    """Keep the Core boundary on V3 application ports and Research DTOs only."""

    path = Path("core/integration/owner_tenant_evidence_scope_v3.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not any("infrastructure" in module for module in imported_modules)
    assert not any(module.endswith("_v2") or module.endswith("_v4") for module in imported_modules)
    assert "EvidenceScopeGrant" not in source
    assert "mode" not in source
