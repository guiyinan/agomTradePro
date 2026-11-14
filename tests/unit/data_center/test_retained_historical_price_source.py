"""Historical-only reads of explicitly selected retained M1 price publications."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.audit.application.data_publication_audit import (
    DataPublicationManifestAuditObservation,
    DataPublicationRawAuditManifestReference,
    build_data_publication_manifest_audit_event,
)
from apps.audit.application.data_publication_rollback_audit import (
    DataPublicationRollbackAuditObservation,
    build_data_publication_rollback_audit_event,
)
from apps.audit.application.retained_system_audit_pair import RetainedSystemAuditPair
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef, SystemAuditEvent
from apps.data_center.application.published_price_source import PublishedPriceSourceFact
from apps.data_center.application.retained_historical_price_source import (
    ReadRetainedHistoricalPriceSource,
    RetainedHistoricalPriceActivation,
    RetainedHistoricalPriceSourceError,
    RetainedHistoricalPriceSourceRequest,
    RetainedHistoricalPriceSourceResult,
)
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.entities import RawAudit
from apps.data_center.domain.raw_audit_manifest import CandidateRawAuditManifest
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure.publication_read_snapshot import PublicationReadSnapshotError
from core.integration.data_center_audit import (
    SystemAuditEventOutboxCorruption,
    SystemAuditEventOutboxUnavailable,
    SystemAuditQueryCorruption,
    SystemAuditReaderContext,
)
from tests.unit.data_center import test_published_price_source as price_fixtures

_SCOPE = AuditScopeRef(tenant_id="data-center", owner_id="data-center")
_OUTBOX_HASH = "f" * 64


@dataclass
class _Fixture:
    publication: CanonicalPublication
    member: PublicationMember
    fact: PublishedPriceSourceFact
    manifest: CandidateRawAuditManifest
    audit: RawAudit
    activation: RetainedHistoricalPriceActivation
    raw_payload: RawPayload
    cutoff: datetime


class _Publications:
    def __init__(self, fixture: _Fixture) -> None:
        self.publication = fixture.publication
        self.members = (fixture.member,)

    def get_by_id(self, publication_id: str) -> CanonicalPublication | None:
        return self.publication if publication_id == self.publication.publication_id else None

    def list_members(self, publication_id: str) -> list[PublicationMember]:
        return list(self.members) if publication_id == self.publication.publication_id else []


class _Prices:
    def __init__(self, fixture: _Fixture) -> None:
        self.facts = (fixture.fact,)
        self.manifest: CandidateRawAuditManifest | None = fixture.manifest
        self.audit = fixture.audit
        self.raw_payload: RawPayload | None = fixture.raw_payload

    def read_facts(
        self, *, asset_code: str, trade_date: date, fact_pks: tuple[str, ...]
    ) -> tuple[PublishedPriceSourceFact, ...]:
        return self.facts

    def read_manifest(self, publication_id: str) -> CandidateRawAuditManifest | None:
        return self.manifest

    def read_audit(self, raw_audit_id: str) -> RawAudit | None:
        return self.audit if raw_audit_id == self.audit.raw_audit_id else None

    def read_payload(self, payload_hash: str) -> RawPayload | None:
        if self.raw_payload is not None and self.raw_payload.payload_hash == payload_hash:
            return self.raw_payload
        return None


class _Activation:
    def __init__(self, value: RetainedHistoricalPriceActivation | None) -> None:
        self.value = value
        self.calls = 0

    def read_original_activation(
        self, publication_id: str, *, knowledge_cutoff: object
    ) -> RetainedHistoricalPriceActivation | None:
        self.calls += 1
        return self.value


def _fixture() -> _Fixture:
    """Build exact retained source plus the actual manifest activation Audit envelope."""
    source = price_fixtures._make_fixture()
    publication = replace(
        source.publication,
        publication_key="m1-rebalance-reference",
        state=PublicationState.SUPERSEDED,
        superseded_at=source.cutoff - timedelta(minutes=1),
    )
    manifest = CandidateRawAuditManifest.create(
        publication_id=publication.publication_id,
        publication_hash=publication.publication_hash,
        run_id=publication.run_id,
        dataset_key=publication.dataset_key,
        publication_key=publication.publication_key,
        task_attempt_id="m1-reference-price:test-attempt",
        raw_audits=(source.audit_reference,),
        manifest_id="19d6dc1a-4a53-4c3b-8d80-6da584e274f3",
    )
    observation = DataPublicationManifestAuditObservation(
        dataset_key=publication.dataset_key,
        publication_key=publication.publication_key,
        publication_id=publication.publication_id,
        publication_version=publication.policy_version,
        publication_hash=publication.publication_hash,
        provider_key=publication.selected_source,
        run_id=publication.run_id,
        member_count=publication.member_count,
        coverage_requested_count=publication.coverage.requested_count,
        coverage_eligible_count=publication.coverage.eligible_count,
        coverage_selected_count=publication.coverage.selected_count,
        manifest_id=manifest.manifest_id,
        manifest_version=manifest.manifest_version,
        manifest_hash=manifest.manifest_hash,
        raw_audit_count=manifest.raw_audit_count,
        raw_audit_hash=manifest.raw_audit_hash,
        raw_audits=tuple(
            DataPublicationRawAuditManifestReference(
                raw_audit_id=item.raw_audit_id,
                version=item.version,
                content_hash=item.content_hash,
            )
            for item in manifest.raw_audits
        ),
        occurred_at=publication.as_of,
        recorded_at=publication.published_at,
        scope=_SCOPE,
    )
    event = build_data_publication_manifest_audit_event(
        observation,
        sequence_no=1,
        predecessor_hash=None,
    )
    activation_pair = RetainedSystemAuditPair(
        event=event,
        audit_persisted_at=event.recorded_at + timedelta(seconds=1),
        outbox_id="b36a2877-70d3-4cd7-b771-0c4df10db3ed",
        outbox_payload_sha256=_OUTBOX_HASH,
        outbox_created_at=event.recorded_at + timedelta(seconds=2),
    )
    return _Fixture(
        publication=publication,
        member=source.member,
        fact=source.fact,
        manifest=manifest,
        audit=source.audit,
        activation=RetainedHistoricalPriceActivation(activation_pair),
        raw_payload=source.raw_payload,
        cutoff=source.cutoff,
    )


def _read(
    fixture: _Fixture,
    *,
    prices: _Prices | None = None,
    activation: RetainedHistoricalPriceActivation | None = None,
) -> tuple[object, _Prices, _Activation]:
    selected_prices = prices or _Prices(fixture)
    selected_activation = _Activation(activation or fixture.activation)
    result = ReadRetainedHistoricalPriceSource(
        publications=_Publications(fixture),
        prices=selected_prices,
        activations=selected_activation,
    ).execute(
        RetainedHistoricalPriceSourceRequest(
            asset_code=fixture.member.source_record_id.split(":")[0],
            trade_date=fixture.member.observed_at.date(),
            publication_id=fixture.publication.publication_id,
            expected_publication_key=fixture.publication.publication_key,
            knowledge_cutoff=fixture.cutoff,
        )
    )
    return result, selected_prices, selected_activation


def _reader_context(as_of: datetime) -> SystemAuditReaderContext:
    """Build a provider-issued current staff scope for the read-only composition test."""
    return SystemAuditReaderContext._from_authority(
        authority_source_id="test-audit-authority",
        authority_source_version="1",
        actor_id="django-user:17",
        user_id=17,
        tenant_id=_SCOPE.tenant_id,
        owner_id=_SCOPE.owner_id,
        authority_content_hash="9" * 64,
        is_authenticated=True,
        is_staff=True,
        role="staff",
        authority_state="active",
        authority_recorded_at=as_of - timedelta(days=1),
        authority_valid_until=as_of + timedelta(days=1),
    )


def _pair_for(event: SystemAuditEvent) -> RetainedSystemAuditPair:
    """Bind one test event to a valid original persistence and Outbox clock pair."""
    return RetainedSystemAuditPair(
        event=event,
        audit_persisted_at=event.recorded_at + timedelta(seconds=1),
        outbox_id=str(uuid4()),
        outbox_payload_sha256=_OUTBOX_HASH,
        outbox_created_at=event.recorded_at + timedelta(seconds=2),
    )


def _rollback_event(
    fixture: _Fixture,
    *,
    publication_id: str,
    previous_publication_id: str,
    sequence_no: int,
    predecessor_hash: str,
    recorded_at: datetime,
) -> SystemAuditEvent:
    """Build an independently run, canonical rollback in the publication stream."""
    observation = DataPublicationRollbackAuditObservation(
        dataset_key=fixture.publication.dataset_key,
        publication_key=fixture.publication.publication_key,
        publication_id=publication_id,
        publication_version="price-policy-v1",
        publication_hash="3" * 64,
        rollback_id=str(uuid4()),
        rollback_version="1",
        rollback_content_hash="4" * 64,
        previous_publication_id=previous_publication_id,
        previous_publication_version=fixture.publication.policy_version,
        previous_publication_hash=fixture.publication.publication_hash,
        run_id=f"rollback-run-{sequence_no}",
        occurred_at=recorded_at - timedelta(seconds=1),
        recorded_at=recorded_at,
        outcome=AuditOutcome.ROLLED_BACK,
        scope=_SCOPE,
    )
    return build_data_publication_rollback_audit_event(
        observation,
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
    )


def _duplicate_activation_event(fixture: _Fixture) -> SystemAuditEvent:
    """Build a second hash-valid activation identity for the same publication."""
    original = fixture.activation.pair.event
    return SystemAuditEvent.create(
        event_id="duplicate-m1-publication-event",
        event_version=original.event_version,
        schema_version=original.schema_version,
        category=original.category,
        event_type=original.event_type,
        owner=original.owner,
        write_policy=original.write_policy,
        outcome=original.outcome,
        severity=original.severity,
        reason_codes=original.reason_codes,
        occurred_at=original.occurred_at,
        recorded_at=original.recorded_at + timedelta(seconds=1),
        observed_at=original.observed_at,
        actor=original.actor,
        source_app=original.source_app,
        source_component=original.source_component,
        source_surface=original.source_surface,
        correlations=original.correlations,
        resource=original.resource,
        dataset_key=original.dataset_key,
        provider_key=original.provider_key,
        capability=original.capability,
        publication_id=original.publication_id,
        evidence_refs=original.evidence_refs,
        detail_schema=original.detail_schema,
        detail=original.detail,
        stream_id=original.stream_id,
        sequence_no=2,
        predecessor_hash=original.content_hash,
        idempotency_key="duplicate-m1-publication-idempotency-key",
        scope=original.scope,
    )


def _read_composed_activation(
    monkeypatch: pytest.MonkeyPatch,
    fixture: _Fixture,
    pairs: tuple[RetainedSystemAuditPair, ...],
) -> tuple[RetainedHistoricalPriceActivation | None, list[dict[str, object]]]:
    """Exercise the imported Data Center composition with only its Audit port replaced."""
    composition = import_module("apps.data_center.retained_historical_price_source_composition")
    context = _reader_context(fixture.cutoff)
    calls: list[dict[str, object]] = []

    def preflight(**values: object) -> SystemAuditReaderContext:
        if values != {"environment": "test", "using": "default", "as_of": fixture.cutoff}:
            raise AssertionError("composition changed the Audit preflight selector")
        return context

    def read_stream(**values: object) -> tuple[RetainedSystemAuditPair, ...]:
        expected = {
            "stream_id": "data.publication:equity.price.bar",
            "scope": _SCOPE,
            "using": "default",
            "as_of": fixture.cutoff,
        }
        calls.append(values)
        if values != expected:
            raise AssertionError("composition changed the bounded Audit stream selector")
        return pairs

    monkeypatch.setattr(composition, "preflight_data_reliability_audit_runtime", preflight)
    monkeypatch.setattr(composition, "read_data_center_retained_system_audit_stream", read_stream)
    reader = composition._DjangoRetainedHistoricalActivationReader(
        environment="test",
        using="default",
    )
    return (
        reader.read_original_activation(
            fixture.publication.publication_id,
            knowledge_cutoff=fixture.cutoff,
        ),
        calls,
    )


def test_reads_superseded_m1_publication_as_explicitly_historical_only() -> None:
    fixture = _fixture()

    result, _prices, _activation = _read(fixture)

    assert result.evidence is not None
    assert result.blocked_reason == ""
    assert result.must_not_use_for_decision is True
    assert result.evidence.knowledge_semantics == "currently_known_historical"
    assert result.evidence.price.publication_state is PublicationState.SUPERSEDED
    assert result.evidence.price.values.close == price_fixtures.EXPECTED_VALUES.close
    assert result.evidence.price.adjustment.value == "none"
    assert result.evidence.price.source_observed_at is None
    assert result.evidence.price.source_available_at == fixture.raw_payload.fetched_at
    assert result.evidence.activation.pair.outbox_payload_sha256 == _OUTBOX_HASH
    assert result.evidence.activation.pair.outbox_payload_sha256 != (
        result.evidence.activation.pair.event.content_hash
    )


def test_candidate_without_original_activation_is_blocked_before_source_use() -> None:
    fixture = _fixture()
    candidate = replace(
        fixture.publication,
        state=PublicationState.CANDIDATE,
        published_at=None,
        superseded_at=None,
    )
    fixture.publication = candidate
    activation_reader = _Activation(None)
    result = ReadRetainedHistoricalPriceSource(
        publications=_Publications(fixture),
        prices=_Prices(fixture),
        activations=activation_reader,
    ).execute(
        RetainedHistoricalPriceSourceRequest(
            asset_code=fixture.member.source_record_id.split(":")[0],
            trade_date=fixture.member.observed_at.date(),
            publication_id=candidate.publication_id,
            expected_publication_key=candidate.publication_key,
            knowledge_cutoff=fixture.cutoff,
        )
    )

    assert result.evidence is None
    assert result.blocked_reason == "retained_price_publication_invalid"
    assert activation_reader.calls == 0


def test_published_source_without_original_activation_is_not_admitted() -> None:
    fixture = _fixture()
    activation_reader = _Activation(None)
    result = ReadRetainedHistoricalPriceSource(
        publications=_Publications(fixture),
        prices=_Prices(fixture),
        activations=activation_reader,
    ).execute(
        RetainedHistoricalPriceSourceRequest(
            asset_code=fixture.member.source_record_id.split(":")[0],
            trade_date=fixture.member.observed_at.date(),
            publication_id=fixture.publication.publication_id,
            expected_publication_key=fixture.publication.publication_key,
            knowledge_cutoff=fixture.cutoff,
        )
    )

    assert result.evidence is None
    assert result.blocked_reason == "retained_price_original_activation_missing"
    assert activation_reader.calls == 1


def test_changed_original_body_fails_even_with_present_activation_pair() -> None:
    fixture = _fixture()
    prices = _Prices(fixture)
    altered_body = dict(fixture.raw_payload.payload)
    altered_body["retained_response_json"] = "{}"
    prices.raw_payload = replace(fixture.raw_payload, payload=altered_body)

    result, _prices, activation = _read(fixture, prices=prices)

    assert result.evidence is None
    assert result.blocked_reason in {
        "retained_price_response_missing_or_changed",
        "retained_price_original_body_hash_mismatch",
    }
    assert activation.calls == 1


def test_outbox_created_after_explicit_cutoff_is_not_historical_evidence() -> None:
    fixture = _fixture()
    late_pair = replace(
        fixture.activation.pair,
        outbox_created_at=fixture.cutoff + timedelta(seconds=1),
    )
    late_activation = RetainedHistoricalPriceActivation(late_pair)

    result, _prices, _reader = _read(fixture, activation=late_activation)

    assert result.evidence is None
    assert result.blocked_reason == "retained_price_original_activation_unavailable"


@pytest.mark.parametrize("bad_code", ["600000.sh", "600000.SH ", ""])
def test_request_rejects_noncanonical_security_identity(bad_code: str) -> None:
    fixture = _fixture()

    with pytest.raises(RetainedHistoricalPriceSourceError):
        RetainedHistoricalPriceSourceRequest(
            asset_code=bad_code,
            trade_date=fixture.member.observed_at.date(),
            publication_id=fixture.publication.publication_id,
            expected_publication_key=fixture.publication.publication_key,
            knowledge_cutoff=fixture.cutoff,
        )


def test_composition_imports_core_stream_facade_and_selects_exact_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real composition imports the Core stream facade and preserves its pair."""
    fixture = _fixture()

    activation, calls = _read_composed_activation(monkeypatch, fixture, (fixture.activation.pair,))

    assert activation == fixture.activation
    assert len(calls) == 1


def test_cross_run_rollback_naming_selected_previous_publication_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later unrelated run can roll back to this publication by previous ID."""
    fixture = _fixture()
    activation_event = fixture.activation.pair.event
    rollback = _rollback_event(
        fixture,
        publication_id="8bbf5eef-ed66-4b92-9aab-a0c9c8f7e22d",
        previous_publication_id=fixture.publication.publication_id,
        sequence_no=2,
        predecessor_hash=activation_event.content_hash,
        recorded_at=activation_event.recorded_at + timedelta(minutes=1),
    )
    assert rollback.correlations.run_id != activation_event.correlations.run_id

    with pytest.raises(SystemAuditQueryCorruption):
        _read_composed_activation(
            monkeypatch,
            fixture,
            (fixture.activation.pair, _pair_for(rollback)),
        )


def test_target_rollback_naming_selected_publication_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A direct rollback target is rejected from the complete Audit stream."""
    fixture = _fixture()
    activation_event = fixture.activation.pair.event
    rollback = _rollback_event(
        fixture,
        publication_id=fixture.publication.publication_id,
        previous_publication_id="8bbf5eef-ed66-4b92-9aab-a0c9c8f7e22d",
        sequence_no=2,
        predecessor_hash=activation_event.content_hash,
        recorded_at=activation_event.recorded_at + timedelta(minutes=1),
    )

    with pytest.raises(SystemAuditQueryCorruption):
        _read_composed_activation(
            monkeypatch,
            fixture,
            (fixture.activation.pair, _pair_for(rollback)),
        )


def test_missing_or_duplicate_activation_does_not_select_a_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The selected source requires exactly one original activation pair."""
    fixture = _fixture()
    missing, _missing_calls = _read_composed_activation(monkeypatch, fixture, ())
    duplicate_pair = _pair_for(_duplicate_activation_event(fixture))
    duplicate, _duplicate_calls = _read_composed_activation(
        monkeypatch,
        fixture,
        (fixture.activation.pair, duplicate_pair),
    )

    assert missing is None
    assert duplicate is None


def test_composition_rejects_a_retained_pair_after_the_knowledge_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every pair in the scoped source prefix must be known by the exact cutoff."""
    fixture = _fixture()
    late_event = replace(
        fixture.activation.pair.event,
        recorded_at=fixture.cutoff + timedelta(seconds=1),
        occurred_at=fixture.cutoff,
    )
    late_pair = _pair_for(late_event)

    with pytest.raises(SystemAuditEventOutboxCorruption):
        _read_composed_activation(monkeypatch, fixture, (late_pair,))


def test_composition_preserves_audit_stream_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unavailable complete stream never falls back to the activation-only query."""
    fixture = _fixture()
    composition = import_module("apps.data_center.retained_historical_price_source_composition")
    context = _reader_context(fixture.cutoff)
    monkeypatch.setattr(
        composition,
        "preflight_data_reliability_audit_runtime",
        lambda **_values: context,
    )

    def unavailable(**_values: object) -> tuple[RetainedSystemAuditPair, ...]:
        raise SystemAuditEventOutboxUnavailable("retained publication stream unavailable")

    monkeypatch.setattr(
        composition,
        "read_data_center_retained_system_audit_stream",
        unavailable,
    )
    reader = composition._DjangoRetainedHistoricalActivationReader(
        environment="test",
        using="default",
    )

    with pytest.raises(SystemAuditEventOutboxUnavailable):
        reader.read_original_activation(
            fixture.publication.publication_id,
            knowledge_cutoff=fixture.cutoff,
        )


def _exercise_public_reader_boundary(
    monkeypatch: pytest.MonkeyPatch,
    fixture: _Fixture,
    *,
    outer_transaction: bool,
    atomic_depth: int,
    read_only: bool,
) -> tuple[
    RetainedHistoricalPriceSourceResult,
    list[str],
    list[str],
    list[str],
]:
    """Exercise public snapshot ordering with a structurally faithful DB context."""
    composition = import_module("apps.data_center.retained_historical_price_source_composition")
    connection = SimpleNamespace(
        in_atomic_block=outer_transaction,
        atomic_blocks=[object() for _ in range(atomic_depth)],
        read_only=read_only,
    )
    monkeypatch.setattr(composition, "connections", {"default": connection})
    atomic_calls: list[str] = []
    stabilization_calls: list[str] = []
    read_calls: list[str] = []
    order: list[str] = []

    @contextmanager
    def atomic(*, using: str) -> Iterator[None]:
        atomic_calls.append(using)
        previous_depth = len(connection.atomic_blocks)
        was_active = connection.in_atomic_block
        connection.in_atomic_block = True
        connection.atomic_blocks.append(object())
        try:
            yield None
        finally:
            connection.atomic_blocks = connection.atomic_blocks[:previous_depth]
            connection.in_atomic_block = was_active

    def stabilize(dataset_key: str) -> None:
        order.append("stabilize")
        stabilization_calls.append(dataset_key)
        if connection.in_atomic_block and (
            len(connection.atomic_blocks) != 1 or connection.read_only
        ):
            raise PublicationReadSnapshotError("publication read context is not writable outermost")

    observed = RetainedHistoricalPriceSourceResult(None, "fixture-source-block")

    def read_source(*_args: object, **_kwargs: object) -> RetainedHistoricalPriceSourceResult:
        order.append("read")
        read_calls.append("source")
        return observed

    start_at = fixture.cutoff + timedelta(days=1)
    clock_values = iter((start_at, start_at + timedelta(seconds=1)))
    monkeypatch.setattr(composition.timezone, "now", lambda: next(clock_values))
    monkeypatch.setattr(composition.transaction, "atomic", atomic)
    monkeypatch.setattr(
        composition,
        "stabilize_caller_owned_publication_read",
        stabilize,
    )
    monkeypatch.setattr(composition, "_read_retained_source_snapshot", read_source)
    result = composition.read_retained_historical_price_source(
        "600000.SH",
        trade_date=fixture.member.observed_at.date(),
        publication_id=fixture.publication.publication_id,
        expected_publication_key=fixture.publication.publication_key,
        knowledge_cutoff=fixture.cutoff,
        environment="test",
    )
    return result, atomic_calls, stabilization_calls, order + read_calls


def test_public_reader_opens_one_outer_writable_boundary_before_any_source_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Standalone reads own one outer transaction and stabilize before Audit access."""
    fixture = _fixture()

    result, atomic_calls, stabilization_calls, order = _exercise_public_reader_boundary(
        monkeypatch,
        fixture,
        outer_transaction=False,
        atomic_depth=0,
        read_only=False,
    )

    assert result.blocked_reason == "fixture-source-block"
    assert atomic_calls == ["default"]
    assert stabilization_calls == ["equity.price.bar"]
    assert order == ["stabilize", "read", "source"]


def test_public_reader_reuses_an_existing_outer_transaction_without_savepoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An outer owner transaction is reused instead of nesting a savepoint."""
    fixture = _fixture()

    result, atomic_calls, stabilization_calls, order = _exercise_public_reader_boundary(
        monkeypatch,
        fixture,
        outer_transaction=True,
        atomic_depth=1,
        read_only=False,
    )

    assert result.blocked_reason == "fixture-source-block"
    assert atomic_calls == []
    assert stabilization_calls == ["equity.price.bar"]
    assert order == ["stabilize", "read", "source"]


@pytest.mark.parametrize(
    ("atomic_depth", "read_only"),
    ((2, False), (1, True)),
)
def test_public_reader_fails_closed_for_nested_or_readonly_outer_context(
    monkeypatch: pytest.MonkeyPatch,
    atomic_depth: int,
    read_only: bool,
) -> None:
    """Nested savepoints and PostgreSQL read-only transactions cannot read Audit pairs."""
    fixture = _fixture()

    result, atomic_calls, stabilization_calls, order = _exercise_public_reader_boundary(
        monkeypatch,
        fixture,
        outer_transaction=True,
        atomic_depth=atomic_depth,
        read_only=read_only,
    )

    assert result.blocked_reason == "retained_price_read_unavailable"
    assert atomic_calls == []
    assert stabilization_calls == ["equity.price.bar"]
    assert order == ["stabilize"]


def test_public_reader_rejects_nondefault_alias_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publication and retained Audit readers share only the supported default alias."""
    composition = import_module("apps.data_center.retained_historical_price_source_composition")
    observed = composition.read_retained_historical_price_source(
        "600000.SH",
        trade_date=date(2026, 10, 26),
        publication_id="19d6dc1a-4a53-4c3b-8d80-6da584e274f3",
        expected_publication_key="m1-rebalance-reference",
        knowledge_cutoff=datetime(2026, 11, 15, tzinfo=UTC),
        environment="test",
        using="other",
    )

    assert observed.evidence is None
    assert observed.blocked_reason == "retained_price_alias_unsupported"


def test_stable_public_port_preserves_exact_archive_selectors_and_unknown_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.data_center.application.public_published_queries import (
        get_retained_historical_price_source,
    )
    from apps.data_center.application.retained_historical_price_source import (
        RetainedHistoricalPriceSourceResult,
    )

    composition = import_module("apps.data_center.retained_historical_price_source_composition")
    fixture = _fixture()
    expected = {
        "trade_date": fixture.fact.trade_date,
        "publication_id": fixture.publication.publication_id,
        "expected_publication_key": fixture.publication.publication_key,
        "knowledge_cutoff": fixture.cutoff,
        "environment": "test",
        "using": "default",
    }
    blocked = RetainedHistoricalPriceSourceResult(None, "synthetic-missing-original")
    calls: list[tuple[str, dict[str, object]]] = []

    def read_exact(asset_code: str, **values: object) -> RetainedHistoricalPriceSourceResult:
        calls.append((asset_code, values))
        return blocked

    monkeypatch.setattr(composition, "read_retained_historical_price_source", read_exact)
    result = get_retained_historical_price_source(fixture.fact.asset_code, **expected)
    assert result is blocked and result.must_not_use_for_decision is True
    assert calls == [(fixture.fact.asset_code, expected)]


def test_hash_valid_activation_without_publication_resource_fails_closed() -> None:
    from apps.audit.domain.system_audit_event import SystemAuditEvent
    from apps.audit.infrastructure.system_audit_event_codec import decode, encode

    fixture = _fixture()
    event = fixture.activation.pair.event
    # Rebuild with the original public factory so this tests semantic binding,
    # rather than a stale hash that the generic codec already rejects.
    import inspect

    arguments = {
        name: getattr(event, name)
        for name in inspect.signature(SystemAuditEvent.create).parameters
        if hasattr(event, name)
    }
    arguments["resource"] = None
    changed = SystemAuditEvent.create(**arguments)
    assert decode(encode(changed)) == changed
    activation = RetainedHistoricalPriceActivation(replace(fixture.activation.pair, event=changed))
    result, _, _ = _read(fixture, activation=activation)
    assert result.evidence is None
    assert result.blocked_reason == "retained_price_activation_identity_mismatch"
