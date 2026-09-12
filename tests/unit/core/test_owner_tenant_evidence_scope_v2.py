"""TDD contracts for current owner authorization around historical Evidence reads."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TypeVar

import pytest

from apps.account.application.owner_tenant_authority_v2 import (
    CurrentOwnerTenantAuthorityV2,
    GetCurrentOwnerTenantAuthorityV2Command,
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
from core.integration.owner_tenant_evidence_scope_v2 import (
    OwnerTenantAuthorityV2EvidenceReadFacade,
)
from tests.unit.account.test_owner_tenant_authority_v2_application import (
    _selector,
    _World,
)

_Result = TypeVar("_Result")


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        """Return the controllable server clock used by this unit test."""

        return self.current


class _SequenceClock:
    def __init__(self, values: list[datetime]) -> None:
        self.values = values
        self.index = 0

    def now(self) -> datetime:
        """Return the next deterministic server timestamp."""

        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return value


class _CurrentReader:
    unit_of_work_key = "django:owner-test"

    def __init__(self, current: CurrentOwnerTenantAuthorityV2 | None) -> None:
        self.current = current
        self.calls: list[GetCurrentOwnerTenantAuthorityV2Command] = []
        self.events: list[str] = []
        self.discard_after_read = False
        self.failure: Exception | None = None

    def with_current(
        self,
        command: GetCurrentOwnerTenantAuthorityV2Command,
        operation: Callable[[CurrentOwnerTenantAuthorityV2], _Result],
    ) -> _Result | None:
        """Keep the callback inside the fake source lock and final recheck."""

        self.calls.append(command)
        self.events.append("authority-enter")
        if self.failure is not None:
            raise self.failure
        if self.current is None:
            self.events.append("authority-empty")
            self.events.append("authority-exit")
            return None
        result = operation(self.current)
        self.events.append("authority-final")
        if self.discard_after_read:
            self.events.append("authority-exit")
            return None
        self.events.append("authority-exit")
        return result


class _EvidenceReads:
    unit_of_work_key = "django:owner-test"

    def __init__(
        self,
        operator: EvidenceOperatorSpec,
        track: TrackRecordSnapshot,
        envelope: EvidenceEnvelope,
    ) -> None:
        self.operator = operator
        self.track = track
        self.envelope = envelope
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.events: list[str] = []
        self.after_read: Callable[[], None] | None = None

    def get_operator_spec(
        self,
        *,
        operator_id: str,
        operator_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpec:
        """Return the exact operator fixture and retain all selector arguments."""

        self.events.append("evidence-operator")
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
    ) -> TrackRecordSnapshot:
        """Return the exact Track Record fixture and retain all selector arguments."""

        self.events.append("evidence-track")
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
    ) -> EvidenceEnvelope:
        """Return the exact output envelope and retain its complete selector."""

        self.events.append("evidence-envelope")
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
def evidence_world() -> (
    tuple[_World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command]
):
    world = _World()
    decision = world.service().issue(world.issue_command())
    current = world.service().get_current(_selector(decision))
    assert current is not None
    return world, current, _selector(decision)


@pytest.fixture
def read_fixtures(
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
) -> tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope]:
    anchor = evidence_world[1].observed_at
    operator = _operator(anchor)
    track = _track(anchor)
    return operator, track, _envelope(operator, anchor)


def _facade(
    *,
    current: CurrentOwnerTenantAuthorityV2 | None,
    selector: GetCurrentOwnerTenantAuthorityV2Command,
    reads: _EvidenceReads,
    clock: _Clock,
    artifacts: frozenset[ArtifactRef],
    scope_ttl: timedelta = timedelta(minutes=5),
) -> tuple[OwnerTenantAuthorityV2EvidenceReadFacade, _CurrentReader]:
    authority = _CurrentReader(current)
    facade = OwnerTenantAuthorityV2EvidenceReadFacade(
        authority_reader=authority,
        evidence_reader=reads,
        authority_command=selector,
        server_bound_artifacts=artifacts,
        scope_ttl=scope_ttl,
        using="owner-test",
        clock=clock,
    )
    return facade, authority


def test_historical_reads_use_current_authorization_and_exact_artifacts(
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """A current V2 decision gates a historical PIT query without time conflation."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    clock = _Clock(current.observed_at)
    requested = frozenset(
        {
            operator.artifact_ref,
            track.artifact_ref,
            ArtifactRef(
                owner=envelope.output_artifact.owner,
                artifact_type=envelope.output_artifact.artifact_type,
                artifact_id=envelope.output_artifact.artifact_id,
                artifact_version=envelope.output_artifact.artifact_version,
                content_hash=envelope.content_hash,
            ),
        }
    )
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=clock,
        artifacts=requested,
    )
    historical = current.observed_at - timedelta(seconds=1)

    assert (
        facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=historical,
        )
        is operator
    )
    assert (
        facade.get_track_record(
            snapshot_id=track.snapshot_id,
            snapshot_version=track.snapshot_version,
            expected_content_hash=track.content_hash,
            evidence_as_of=historical,
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
            evidence_as_of=historical,
        )
        is envelope
    )

    assert authority.calls == [selector, selector, selector]
    assert [call[1]["as_of"] for call in reads.calls] == [historical] * 3
    assert reads.calls[2][1]["expected_content_hash"] == envelope.content_hash
    assert envelope.output_artifact.content_hash != envelope.content_hash


def test_read_is_materialized_inside_current_callback_and_final_failure_discards_it(
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """A short scope cannot escape when the source recheck fails after the read."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    authority = _CurrentReader(current)
    authority.discard_after_read = True
    clock = _Clock(current.observed_at)
    facade = OwnerTenantAuthorityV2EvidenceReadFacade(
        authority_reader=authority,
        evidence_reader=reads,
        authority_command=selector,
        server_bound_artifacts=frozenset({operator.artifact_ref}),
        scope_ttl=timedelta(minutes=5),
        using="owner-test",
        clock=clock,
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
    assert authority.events == ["authority-enter", "authority-final", "authority-exit"]
    assert reads.events == ["evidence-operator"]


@pytest.mark.parametrize("kind", ["operator", "track", "envelope"])
def test_missing_current_authority_never_touches_evidence_repository(
    kind: str,
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """Revocation, expiry or missing V2 current state cannot grant a historical read."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    facade, authority = _facade(
        current=None,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset(
            {
                operator.artifact_ref,
                track.artifact_ref,
                ArtifactRef(
                    owner=envelope.output_artifact.owner,
                    artifact_type=envelope.output_artifact.artifact_type,
                    artifact_id=envelope.output_artifact.artifact_id,
                    artifact_version=envelope.output_artifact.artifact_version,
                    content_hash=envelope.content_hash,
                ),
            }
        ),
    )

    if kind == "operator":
        result = facade.get_operator_spec(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
    elif kind == "track":
        result = facade.get_track_record(
            snapshot_id=track.snapshot_id,
            snapshot_version=track.snapshot_version,
            expected_content_hash=track.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
    else:
        result = facade.get_envelope(
            output_owner=envelope.output_artifact.owner,
            output_artifact_type=envelope.output_artifact.artifact_type,
            output_artifact_id=envelope.output_artifact.artifact_id,
            output_artifact_version=envelope.output_artifact.artifact_version,
            expected_content_hash=envelope.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )

    assert result is None
    assert authority.calls == [selector]
    assert reads.calls == []


@pytest.mark.parametrize(
    ("kind", "identity_change"),
    [
        ("operator", {"operator_id": "operator-other"}),
        ("track", {"snapshot_version": "v2"}),
        ("envelope", {"output_owner": "research"}),
    ],
)
def test_client_selector_must_match_server_bound_artifact_exactly(
    kind: str,
    identity_change: dict[str, str],
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """An id, version, hash or output owner substitution cannot reach Research."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    bound_envelope = ArtifactRef(
        owner=envelope.output_artifact.owner,
        artifact_type=envelope.output_artifact.artifact_type,
        artifact_id=envelope.output_artifact.artifact_id,
        artifact_version=envelope.output_artifact.artifact_version,
        content_hash=envelope.content_hash,
    )
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({operator.artifact_ref, track.artifact_ref, bound_envelope}),
    )
    if kind == "operator":
        result = facade.get_operator_spec(
            operator_id=identity_change.get("operator_id", operator.operator_id),
            operator_version=operator.operator_version,
            expected_content_hash=operator.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
    elif kind == "track":
        result = facade.get_track_record(
            snapshot_id=track.snapshot_id,
            snapshot_version=identity_change.get("snapshot_version", track.snapshot_version),
            expected_content_hash=track.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
    else:
        result = facade.get_envelope(
            output_owner=identity_change.get("output_owner", envelope.output_artifact.owner),
            output_artifact_type=envelope.output_artifact.artifact_type,
            output_artifact_id=envelope.output_artifact.artifact_id,
            output_artifact_version=envelope.output_artifact.artifact_version,
            expected_content_hash=envelope.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )

    assert result is None
    assert authority.calls == []
    assert reads.calls == []


def test_nonresearch_envelope_owner_is_allowed_only_when_exactly_bound(
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """Envelope output ownership stays generic while its full address remains sealed."""

    _, current, selector = evidence_world
    operator, _, envelope = read_fixtures
    reads = _EvidenceReads(operator, _track(current.observed_at), envelope)
    bound = ArtifactRef(
        owner="portfolio-output",
        artifact_type="model-output",
        artifact_id="output-1",
        artifact_version="v1",
        content_hash=envelope.content_hash,
    )
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({bound}),
    )

    assert (
        facade.get_envelope(
            output_owner=bound.owner,
            output_artifact_type=bound.artifact_type,
            output_artifact_id=bound.artifact_id,
            output_artifact_version=bound.artifact_version,
            expected_content_hash=bound.content_hash,
            evidence_as_of=current.observed_at - timedelta(seconds=1),
        )
        is envelope
    )
    assert authority.calls == [selector]
    assert len(reads.calls) == 1


def test_each_request_revalidates_current_authority_without_cached_scope(
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """A renewed authentication must be observed on every request."""

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

    for _ in range(2):
        assert (
            facade.get_operator_spec(
                operator_id=operator.operator_id,
                operator_version=operator.operator_version,
                expected_content_hash=operator.content_hash,
                evidence_as_of=current.observed_at - timedelta(seconds=1),
            )
            is operator
        )

    assert len(authority.calls) == 2
    assert len(reads.calls) == 2
    assert track is not None and envelope is not None


def test_short_scope_clock_expiry_after_materialization_returns_none(
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """The trusted Core clock must reject a result that crosses its request TTL."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    clock = _Clock(current.observed_at)
    authority = _CurrentReader(current)

    def after_read() -> None:
        """Advance the trusted clock beyond the configured short scope."""

        clock.current = current.observed_at + timedelta(seconds=2)

    reads.after_read = after_read
    facade = OwnerTenantAuthorityV2EvidenceReadFacade(
        authority_reader=authority,
        evidence_reader=reads,
        authority_command=selector,
        server_bound_artifacts=frozenset({operator.artifact_ref}),
        scope_ttl=timedelta(seconds=1),
        using="owner-test",
        clock=clock,
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


def test_short_scope_expiry_before_repository_call_is_fail_closed(
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """A second trusted-clock check prevents a read after a short scope expires."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    clock = _SequenceClock([current.observed_at, current.observed_at + timedelta(seconds=2)])
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
    assert track is not None and envelope is not None


def test_current_authority_selector_substitution_is_corruption(
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """A current row for another decision cannot satisfy the server selector."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    substituted_authority = replace(
        current.authority,
        authority_id="other-decision",
        identity_hash="",
        content_hash="",
    )
    substituted_current = replace(current, authority=substituted_authority)
    reads = _EvidenceReads(operator, track, envelope)
    facade, authority = _facade(
        current=substituted_current,
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
    assert track is not None and envelope is not None


def test_unexpected_authority_failure_is_sanitized(
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """Provider implementation details never cross the owner-scoped boundary."""

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


def test_future_evidence_dto_is_rejected_without_current_eligibility_upgrade(
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """A repository result with an obvious future activation is corrupt."""

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


def test_historical_expired_evidence_remains_readable_under_current_authority(
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """Historical knowability is preserved even after the DTO's validity window ends."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    expired = replace(
        operator,
        valid_until=current.observed_at - timedelta(seconds=1),
        content_hash="",
    )
    reads = _EvidenceReads(expired, track, envelope)
    facade, authority = _facade(
        current=current,
        selector=selector,
        reads=reads,
        clock=_Clock(current.observed_at),
        artifacts=frozenset({expired.artifact_ref}),
    )
    cutoff = current.observed_at - timedelta(microseconds=500_000)

    assert (
        facade.get_operator_spec(
            operator_id=expired.operator_id,
            operator_version=expired.operator_version,
            expected_content_hash=expired.content_hash,
            evidence_as_of=cutoff,
        )
        is expired
    )
    assert authority.calls == [selector]
    assert len(reads.calls) == 1
    assert expired.valid_until < cutoff
    assert track is not None and envelope is not None


def test_future_pit_cutoff_is_rejected_before_current_authorization(
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """An impossible historical cutoff cannot trigger even a current authority read."""

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
    assert authority.calls == []
    assert reads.calls == []
    assert track is not None and envelope is not None


def test_repository_result_identity_substitution_is_corruption(
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """A repository result with another immutable identity cannot cross the bridge."""

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
    assert track is not None and envelope is not None


def test_alias_mismatch_is_rejected_before_any_read(
    evidence_world: tuple[
        _World, CurrentOwnerTenantAuthorityV2, GetCurrentOwnerTenantAuthorityV2Command
    ],
    read_fixtures: tuple[EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope],
) -> None:
    """The bridge cannot combine source locks and Evidence reads from different aliases."""

    _, current, selector = evidence_world
    operator, track, envelope = read_fixtures
    reads = _EvidenceReads(operator, track, envelope)
    reads.unit_of_work_key = "django:other"

    with pytest.raises(ValueError, match="alias"):
        _facade(
            current=current,
            selector=selector,
            reads=reads,
            clock=_Clock(current.observed_at),
            artifacts=frozenset({operator.artifact_ref}),
        )
    assert track is not None and envelope is not None
