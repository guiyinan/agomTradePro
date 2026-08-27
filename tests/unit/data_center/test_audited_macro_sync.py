"""Contract tests for the Data Center macro sync audit transaction."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime

import pytest

from apps.audit.application.data_failover_audit import DataFailoverAuditObservation
from apps.audit.application.data_fetch_audit import DataFetchAuditObservation
from apps.audit.application.data_provider_health_audit import (
    DataProviderHealthAuditObservation,
)
from apps.audit.application.data_publication_audit import DataPublicationAuditObservation
from apps.audit.application.data_validation_audit import DataValidationRejectedObservation
from apps.audit.domain.system_audit_event import AuditOutcome
from apps.data_center.application.dtos import SyncMacroRequest
from apps.data_center.application.sync_identity import (
    SyncExecutionIdentity,
)
from apps.data_center.application.sync_use_cases import MacroFailoverDecision, SyncMacroUseCase
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationState,
)
from apps.data_center.domain.entities import (
    IndicatorCatalog,
    IndicatorUnitRule,
    MacroFact,
    ProviderConfig,
    RawAudit,
)
from apps.data_center.domain.enums import DataCapability
from apps.data_center.infrastructure.provider_registry import ProviderRegistry

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _identity(provider_name: str = "provider-main") -> SyncExecutionIdentity:
    material = {
        "batch_id": "33333333-3333-4333-8333-333333333333",
        "dataset_key": "macro.fact",
        "ingested_run_id": "22222222-2222-4222-8222-222222222222",
        "provider_name": provider_name,
        "run_id": "11111111-1111-4111-8111-111111111111",
    }
    identity_hash = hashlib.sha256(
        b"agomtradepro:data-center:sync-execution-identity:v1\0"
        + json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return SyncExecutionIdentity(
        run_id=material["run_id"],
        ingested_run_id=material["ingested_run_id"],
        batch_id=material["batch_id"],
        dataset_key=material["dataset_key"],
        provider_name=material["provider_name"],
        identity_hash=identity_hash,
    )


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        id=1,
        name="provider-main",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )


class _Provider:
    def __init__(self, facts: list[MacroFact]) -> None:
        self._facts = facts

    def provider_name(self) -> str:
        return "provider-main"

    def supports(self, capability: DataCapability) -> bool:
        return capability is DataCapability.MACRO

    def fetch_macro_series(self, _indicator_code: str, _start: date, _end: date) -> list[MacroFact]:
        return list(self._facts)


class _ProviderRepository:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.config = _provider_config()

    def get_by_id(self, _provider_id: int) -> ProviderConfig:
        return self.config

    def save(self, config: ProviderConfig) -> ProviderConfig:
        self.events.append("health")
        self.config = config
        return config


class _ProviderRegistry:
    def __init__(self, provider: _Provider) -> None:
        self.provider = provider

    def get_by_id(self, _provider_id: int) -> _Provider:
        return self.provider

    def record_success(
        self, _provider_name: str, _capability: DataCapability, _latency_ms: float
    ) -> None:
        return None

    def record_failure(self, _provider_name: str, _capability: DataCapability) -> None:
        return None


class _CatalogRepository:
    def get_by_code(self, _code: str) -> IndicatorCatalog:
        return IndicatorCatalog(
            code="CN_CPI",
            name_cn="CPI",
            name_en="CPI",
            description="",
            category="prices",
            default_period_type="M",
            default_unit="%",
            is_active=True,
            extra={},
        )


class _UnitRuleRepository:
    def resolve_active_rule(
        self,
        _indicator_code: str,
        *,
        source_type: str = "",
        original_unit: str | None = None,
    ) -> IndicatorUnitRule:
        return IndicatorUnitRule(
            id=1,
            indicator_code="CN_CPI",
            source_type=source_type or "tushare",
            dimension_key="rate",
            original_unit=original_unit or "%",
            storage_unit="%",
            display_unit="%",
            multiplier_to_storage=1.0,
            is_active=True,
            priority=1,
            description="",
        )


class _FactRepository:
    def __init__(self, events: list[str], transaction_active: Callable[[], bool]) -> None:
        self.events = events
        self._transaction_active = transaction_active
        self.facts: list[MacroFact] = []

    def bulk_upsert(self, facts: list[MacroFact]) -> int:
        assert self._transaction_active()
        self.events.append("facts")
        self.facts.extend(facts)
        return len(facts)

    def list_publication_candidates(self, _facts: list[MacroFact]) -> list[object]:
        assert self._transaction_active()
        return []


class _RawAuditRepository:
    def __init__(self, events: list[str], transaction_active: Callable[[], bool]) -> None:
        self.events = events
        self._transaction_active = transaction_active
        self.rows: list[RawAudit] = []

    def log(self, audit: RawAudit) -> RawAudit:
        assert self._transaction_active()
        self.events.append("raw_audit")
        stored = RawAudit(
            provider_name=audit.provider_name,
            capability=audit.capability,
            request_params=audit.request_params,
            status=audit.status,
            row_count=audit.row_count,
            latency_ms=audit.latency_ms,
            error_message=audit.error_message,
            fetched_at=audit.fetched_at,
            extra=audit.extra,
            request_params_hash=audit.request_params_hash,
            response_payload_hash=audit.response_payload_hash,
            schema_fingerprint=audit.schema_fingerprint,
            redacted=audit.redacted,
            parser_version=audit.parser_version,
            payload_size_bytes=audit.payload_size_bytes,
            retention_until=audit.retention_until,
            raw_audit_id="raw-1",
            run_id=audit.run_id,
            ingested_run_id=audit.ingested_run_id,
            content_hash="a" * 64,
        )
        self.rows.append(stored)
        return stored


class _UnitOfWork:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.active = False

    def atomic(self) -> AbstractContextManager[None]:
        owner = self

        class _Atomic(AbstractContextManager[None]):
            def __enter__(self) -> None:
                owner.active = True
                owner.events.append("begin")
                return None

            def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
                owner.events.append("rollback" if exc_type else "commit")
                owner.active = False
                return False

        return _Atomic()


class _Issuer:
    def __init__(self, identity: SyncExecutionIdentity) -> None:
        self.identity = identity

    def issue(self, *, dataset_key: str, provider_name: str) -> SyncExecutionIdentity:
        assert dataset_key == self.identity.dataset_key
        assert provider_name == self.identity.provider_name
        return self.identity


class _AuditWriter:
    def __init__(self, events: list[str], transaction_active: Callable[[], bool]) -> None:
        self.events = events
        self._transaction_active = transaction_active
        self.observations: list[DataFetchAuditObservation] = []
        self.fail = False

    def write(self, observation: DataFetchAuditObservation) -> None:
        assert self._transaction_active()
        self.events.append("audit_event")
        if self.fail:
            raise RuntimeError("audit writer failure")
        self.observations.append(observation)


class _PublicationWriter:
    def __init__(self, events: list[str], transaction_active: Callable[[], bool]) -> None:
        self.events = events
        self._transaction_active = transaction_active
        self.observations: list[DataPublicationAuditObservation] = []

    def write(self, observation: DataPublicationAuditObservation) -> None:
        assert self._transaction_active()
        self.events.append("publication_event")
        self.observations.append(observation)


class _ValidationWriter:
    def __init__(self, events: list[str], transaction_active: Callable[[], bool]) -> None:
        self.events = events
        self._transaction_active = transaction_active
        self.observations: list[DataValidationRejectedObservation] = []

    def write(self, observation: DataValidationRejectedObservation) -> None:
        assert self._transaction_active()
        self.events.append("validation_event")
        self.observations.append(observation)


class _FailoverWriter:
    def __init__(self, events: list[str], transaction_active: Callable[[], bool]) -> None:
        self.events = events
        self._transaction_active = transaction_active
        self.observations: list[DataFailoverAuditObservation] = []
        self.fail = False

    def write(self, observation: DataFailoverAuditObservation) -> None:
        assert self._transaction_active()
        self.events.append("failover_event")
        if self.fail:
            raise RuntimeError("failover writer failure")
        self.observations.append(observation)


class _ProviderHealthWriter:
    def __init__(self) -> None:
        self.events: list[str] = []
        self._transaction_active: Callable[[], bool] = lambda: False
        self.observations: list[DataProviderHealthAuditObservation] = []

    def bind(self, events: list[str], transaction_active: Callable[[], bool]) -> None:
        self.events = events
        self._transaction_active = transaction_active

    def write(self, observation: DataProviderHealthAuditObservation) -> None:
        assert self._transaction_active()
        self.events.append("provider_health_event")
        self.observations.append(observation)


class _Publisher:
    def __init__(self, events: list[str], error: ValueError | None = None) -> None:
        self.events = events
        self.error = error

    def execute(
        self,
        facts: list[MacroFact],
        *,
        provider_name: str,
        publication_key: str,
        run_id: str,
        published_at: datetime,
    ) -> CanonicalPublication:
        self.events.append("publication")
        if self.error is not None:
            raise self.error
        count = len(facts)
        return CanonicalPublication(
            publication_id="publication-1",
            dataset_key="macro.fact",
            publication_key=publication_key,
            policy_version="1.0:1.0",
            state=PublicationState.PUBLISHED,
            selected_source=provider_name,
            publication_hash="b" * 64,
            coverage=CoverageSnapshot(
                coverage_id="coverage-1",
                publication_id="publication-1",
                requested_count=count,
                eligible_count=count,
                selected_count=count,
                missing_count=0,
                conflict_count=0,
                generated_at=published_at,
            ),
            member_count=count,
            as_of=published_at,
            published_at=published_at,
            run_id=run_id,
        )


class _PublicationQualityRecorder:
    """Typed fake for persisted publication quality recording."""

    last_calls: list[tuple[str, str, str, str]] = []

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        type(self).last_calls = self.calls

    def execute(
        self,
        *,
        publication_id: str,
        run_id: str,
        ingested_run_id: str,
        provider_key: str,
    ) -> object:
        self.calls.append((publication_id, run_id, ingested_run_id, provider_key))
        return object()


class _Clock:
    def now(self) -> datetime:
        return NOW


def _fact() -> MacroFact:
    return MacroFact(
        indicator_code="CN_CPI",
        reporting_period=date(2026, 8, 1),
        value=2.1,
        unit="%",
        source="tushare",
        published_at=date(2026, 8, 3),
        fetched_at=NOW,
    )


def _build(
    facts: list[MacroFact],
    *,
    publisher: _Publisher | None = None,
    provider_health_writer: _ProviderHealthWriter | None = None,
    initial_provider_failures: int = 0,
    identity_provider_name: str = "provider-main",
) -> tuple[
    SyncMacroUseCase,
    _UnitOfWork,
    _AuditWriter,
    _PublicationWriter,
    _ValidationWriter,
    _FailoverWriter,
    list[str],
]:
    events: list[str] = []
    uow = _UnitOfWork(events)
    if provider_health_writer is not None:
        provider_health_writer.bind(events, lambda: uow.active)
    writer = _AuditWriter(events, lambda: uow.active)
    publication_writer = _PublicationWriter(events, lambda: uow.active)
    validation_writer = _ValidationWriter(events, lambda: uow.active)
    failover_writer = _FailoverWriter(events, lambda: uow.active)
    quality_recorder = _PublicationQualityRecorder()
    provider = _Provider(facts)
    provider_registry: _ProviderRegistry | ProviderRegistry
    if provider_health_writer is None and initial_provider_failures == 0:
        provider_registry = _ProviderRegistry(provider)
    else:
        provider_registry = ProviderRegistry()
        provider_registry.register(
            provider,
            priority=1,
            provider_id=1,
            source_type="tushare",
        )
        for _index in range(initial_provider_failures):
            provider_registry.record_failure("provider-main", DataCapability.MACRO)
    use_case = SyncMacroUseCase(
        provider_repo=_ProviderRepository(events),
        provider_registry=provider_registry,
        fact_repo=_FactRepository(events, lambda: uow.active),
        catalog_repo=_CatalogRepository(),
        unit_rule_repo=_UnitRuleRepository(),
        raw_audit_repo=_RawAuditRepository(events, lambda: uow.active),
        publication_publisher=publisher,
        sync_identity_issuer=_Issuer(_identity(identity_provider_name)),
        sync_unit_of_work=uow,
        data_fetch_audit_writer=writer,
        data_publication_audit_writer=publication_writer,
        publication_quality_recorder=quality_recorder if publisher is not None else None,
        data_validation_audit_writer=validation_writer,
        data_failover_audit_writer=failover_writer,
        data_provider_health_audit_writer=provider_health_writer,
        clock=_Clock(),
    )
    return (
        use_case,
        uow,
        writer,
        publication_writer,
        validation_writer,
        failover_writer,
        events,
    )


def _request() -> SyncMacroRequest:
    return SyncMacroRequest(
        provider_id=1,
        indicator_code="CN_CPI",
        start=date(2026, 8, 1),
        end=date(2026, 8, 27),
    )


def test_success_correlates_identity_raw_audit_and_event_inside_one_uow() -> None:
    (
        use_case,
        uow,
        writer,
        _publication_writer,
        _validation_writer,
        _failover_writer,
        events,
    ) = _build([_fact()])

    result = use_case.execute(_request())

    assert result.status == "success"
    assert uow.active is False
    assert events[0] == "begin"
    assert events[-1] == "commit"
    assert events.index("facts") < events.index("raw_audit") < events.index("audit_event")
    observation = writer.observations[0]
    assert observation.run_id == "11111111-1111-4111-8111-111111111111"
    assert observation.ingested_run_id == "22222222-2222-4222-8222-222222222222"
    assert observation.raw_audit_id == "raw-1"
    assert observation.raw_audit_content_hash == "a" * 64
    assert observation.outcome.value == "success"
    assert observation.row_count == 1


def test_recovered_provider_transition_uses_sync_identity_inside_same_uow() -> None:
    provider_health_writer = _ProviderHealthWriter()
    use_case, _uow, _writer, _publication_writer, _validation_writer, _failover_writer, events = (
        _build(
            [_fact()],
            provider_health_writer=provider_health_writer,
            initial_provider_failures=1,
        )
    )

    result = use_case.execute(_request())

    observation = provider_health_writer.observations[0]
    assert observation.transition == "recovered"
    assert observation.outcome is AuditOutcome.RECOVERED
    assert observation.run_id == result.run_id
    assert observation.ingested_run_id == result.ingested_run_id
    assert observation.dataset_key == "macro.fact"
    assert observation.provider_key == "provider-main"
    assert observation.capability == "macro"
    assert len(observation.provider_health_snapshot_hash) == 64
    assert events.index("facts") < events.index("provider_health_event")
    assert events.index("provider_health_event") < events.index("raw_audit")
    assert events[-1] == "commit"


def test_circuit_open_transition_uses_failed_sync_identity_inside_same_uow() -> None:
    provider_health_writer = _ProviderHealthWriter()
    mismatched = dataclasses.replace(_fact(), indicator_code="CN_PPI")
    use_case, _uow, _writer, _publication_writer, _validation_writer, _failover_writer, events = (
        _build(
            [mismatched],
            provider_health_writer=provider_health_writer,
            initial_provider_failures=4,
        )
    )

    with pytest.raises(ValueError, match="mismatched indicator"):
        use_case.execute(_request())

    observation = provider_health_writer.observations[0]
    assert observation.transition == "circuit_opened"
    assert observation.outcome is AuditOutcome.BLOCKED
    assert observation.run_id == _identity().run_id
    assert observation.ingested_run_id == _identity().ingested_run_id
    assert observation.reason_code == "provider_circuit_opened"
    assert "CN_PPI" not in repr(observation)
    assert events.index("provider_health_event") < events.index("raw_audit")
    assert events[-1] == "commit"


def test_noop_writes_identity_health_raw_audit_and_no_publication() -> None:
    use_case, uow, writer, publication_writer, validation_writer, failover_writer, events = _build(
        []
    )

    result = use_case.execute(_request())

    assert result.status == "noop"
    identity = writer.observations[0]
    assert result.run_id == identity.run_id
    assert result.ingested_run_id == identity.ingested_run_id
    assert result.publication_id is None
    assert result.publication_version is None
    assert result.publication_hash is None
    result_payload = result.to_dict()
    assert result_payload["run_id"] == identity.run_id
    assert result_payload["ingested_run_id"] == identity.ingested_run_id
    assert result_payload["publication_id"] is None
    assert result_payload["publication_version"] is None
    assert result_payload["publication_hash"] is None
    assert uow.active is False
    assert writer.observations[0].outcome.value == "noop"
    assert writer.observations[0].row_count == 0
    assert "facts" not in events
    assert events.count("audit_event") == 1
    assert publication_writer.observations == []
    assert validation_writer.observations == []
    assert failover_writer.observations == []
    assert events[-1] == "commit"


def test_audit_writer_failure_rolls_back_and_is_not_hidden() -> None:
    (
        use_case,
        uow,
        writer,
        _publication_writer,
        _validation_writer,
        _failover_writer,
        events,
    ) = _build([_fact()])
    writer.fail = True

    with pytest.raises(RuntimeError, match="audit writer failure"):
        use_case.execute(_request())

    assert uow.active is False
    assert events[-1] == "rollback"


def test_published_observation_uses_exact_publication_and_raw_audit_identity() -> None:
    events: list[str] = []
    publisher = _Publisher(events)
    (
        use_case,
        _uow,
        fetch_writer,
        publication_writer,
        _validation_writer,
        _failover_writer,
        committed_events,
    ) = _build([_fact()], publisher=publisher)
    publisher.events = committed_events

    result = use_case.execute(_request())

    assert result.status == "success"
    assert len(fetch_writer.observations) == 1
    observation = publication_writer.observations[0]
    assert result.run_id == observation.run_id
    assert result.ingested_run_id == observation.ingested_run_id
    assert result.publication_id == observation.publication_id
    assert result.publication_version == observation.publication_version
    assert result.publication_hash == observation.publication_hash
    result_payload = result.to_dict()
    assert result_payload["run_id"] == observation.run_id
    assert result_payload["ingested_run_id"] == observation.ingested_run_id
    assert result_payload["publication_id"] == observation.publication_id
    assert result_payload["publication_version"] == observation.publication_version
    assert result_payload["publication_hash"] == observation.publication_hash
    assert observation.outcome is AuditOutcome.PUBLISHED
    assert observation.publication_id == "publication-1"
    assert observation.publication_hash == "b" * 64
    assert observation.run_id == "11111111-1111-4111-8111-111111111111"
    assert observation.ingested_run_id == "22222222-2222-4222-8222-222222222222"
    assert observation.raw_audit_id == "raw-1"
    assert _PublicationQualityRecorder.last_calls == [
        (
            observation.publication_id,
            observation.run_id,
            observation.ingested_run_id,
            observation.provider_key,
        )
    ]
    assert committed_events.index("raw_audit") < committed_events.index("publication_event")
    assert committed_events[-1] == "commit"


def test_publication_policy_block_commits_exact_evidence_then_reraises_safely() -> None:
    events: list[str] = []
    publisher = _Publisher(events, ValueError("sensitive provider response"))
    (
        use_case,
        _uow,
        fetch_writer,
        publication_writer,
        _validation_writer,
        _failover_writer,
        committed_events,
    ) = _build([_fact()], publisher=publisher)
    publisher.events = committed_events

    with pytest.raises(ValueError, match="sensitive provider response"):
        use_case.execute(_request())

    assert fetch_writer.observations[0].outcome is AuditOutcome.SUCCESS
    observation = publication_writer.observations[0]
    assert observation.outcome is AuditOutcome.BLOCKED
    assert observation.blocked_reason == "publication_policy_rejected"
    assert observation.error_class == "ValueError"
    assert "sensitive provider response" not in repr(observation)
    assert _PublicationQualityRecorder.last_calls == []
    assert committed_events[-1] == "commit"


def test_validation_rejection_commits_fetch_and_exact_rejection_before_reraising() -> None:
    mismatched = dataclasses.replace(_fact(), indicator_code="CN_PPI")
    (
        use_case,
        uow,
        fetch_writer,
        publication_writer,
        validation_writer,
        _failover_writer,
        events,
    ) = _build([mismatched])

    with pytest.raises(ValueError, match="mismatched indicator"):
        use_case.execute(_request())

    assert uow.active is False
    assert events[-1] == "commit"
    assert publication_writer.observations == []
    fetch_observation = fetch_writer.observations[0]
    assert fetch_observation.outcome is AuditOutcome.SUCCESS
    assert fetch_observation.row_count == 1
    rejection = validation_writer.observations[0]
    assert rejection.dataset_key == "macro.fact"
    assert rejection.validator_key == "macro_fact_governance.v1"
    assert rejection.rejection_reason == "indicator_mismatch"
    assert rejection.error_class == "ValueError"
    assert rejection.rejected_count == 1
    assert rejection.run_id == fetch_observation.run_id
    assert rejection.ingested_run_id == fetch_observation.ingested_run_id
    assert rejection.raw_audit_id == fetch_observation.raw_audit_id
    assert "CN_CPI" not in repr(rejection)


def test_accepted_failover_is_correlated_and_committed_before_publication() -> None:
    events: list[str] = []
    publisher = _Publisher(events)
    (
        use_case,
        _uow,
        fetch_writer,
        _publication_writer,
        _validation_writer,
        failover_writer,
        committed_events,
    ) = _build([_fact()], publisher=publisher)
    publisher.events = committed_events
    decision = MacroFailoverDecision(
        from_provider="provider-primary",
        to_provider="provider-main",
        verification_provider="provider-verifier",
        tolerance=0.01,
        observed_deviation=0.005,
        reason_code="primary_unavailable_fallback_verified",
    )

    prepared = use_case.prepare(_request())
    verification = dataclasses.replace(
        prepared,
        config=dataclasses.replace(prepared.config, name="provider-verifier", id=2),
        provider_name="provider-verifier",
    )
    result = use_case.commit(
        prepared,
        failover_decision=decision,
        verification=verification,
    )

    assert result.status == "success"
    assert len(fetch_writer.observations) == 2
    assert [item.provider_key for item in fetch_writer.observations] == [
        "provider-main",
        "provider-verifier",
    ]
    assert fetch_writer.observations[0].run_id == fetch_writer.observations[1].run_id
    assert [item.outcome for item in failover_writer.observations] == [
        AuditOutcome.STARTED,
        AuditOutcome.SUCCESS,
    ]
    observation = failover_writer.observations[1]
    assert observation.outcome is AuditOutcome.SUCCESS
    assert observation.from_provider == "provider-primary"
    assert observation.to_provider == "provider-main"
    assert observation.observed_deviation == pytest.approx(0.005)
    assert observation.raw_audit_id == fetch_writer.observations[0].raw_audit_id
    assert committed_events.index("audit_event") < committed_events.index("failover_event")
    assert committed_events.index("failover_event") < committed_events.index("publication_event")
    assert committed_events[-1] == "commit"


def test_unverified_failover_is_blocked_with_fetch_evidence_and_no_fact_commit() -> None:
    (
        use_case,
        _uow,
        fetch_writer,
        publication_writer,
        validation_writer,
        failover_writer,
        events,
    ) = _build([_fact()])
    prepared = use_case.prepare(_request())

    use_case.block_failover(
        prepared,
        from_provider="provider-primary",
        tolerance=0.01,
        observed_deviation=None,
        reason_code="failover_consistency_evidence_missing",
        error_class="ConsistencyEvidenceUnavailable",
    )

    assert "facts" not in events
    assert publication_writer.observations == []
    assert validation_writer.observations == []
    assert fetch_writer.observations[0].outcome is AuditOutcome.SUCCESS
    assert [item.outcome for item in failover_writer.observations] == [
        AuditOutcome.STARTED,
        AuditOutcome.BLOCKED,
    ]
    blocked = failover_writer.observations[1]
    assert blocked.outcome is AuditOutcome.BLOCKED
    assert blocked.observed_deviation is None
    assert blocked.reason_code == "failover_consistency_evidence_missing"
    assert blocked.error_class == "ConsistencyEvidenceUnavailable"
    assert blocked.raw_audit_id == fetch_writer.observations[0].raw_audit_id
    assert events[-1] == "commit"


def test_candidate_exhaustion_commits_failed_fetch_and_required_failover_evidence() -> None:
    (
        use_case,
        _uow,
        fetch_writer,
        publication_writer,
        validation_writer,
        failover_writer,
        events,
    ) = _build([], identity_provider_name="macro-provider-candidates")

    use_case.exhaust_failover(
        indicator_code="CN_CPI",
        start=date(2026, 8, 1),
        end=date(2026, 8, 27),
        from_provider="provider-primary",
        attempted_provider_names=("provider-primary", "provider-a", "provider-b"),
        tolerance=0.01,
    )

    assert "facts" not in events
    assert publication_writer.observations == []
    assert validation_writer.observations == []
    assert len(fetch_writer.observations) == 1
    fetch = fetch_writer.observations[0]
    assert fetch.provider_key == "macro-provider-candidates"
    assert fetch.outcome is AuditOutcome.FAILED
    assert fetch.error_class == "ProviderCandidatesExhausted"
    assert [item.outcome for item in failover_writer.observations] == [
        AuditOutcome.STARTED,
        AuditOutcome.BLOCKED,
    ]
    exhausted = failover_writer.observations[1]
    assert exhausted.reason_code == "failover_candidates_exhausted"
    assert exhausted.error_class == "ProviderCandidatesExhausted"
    assert exhausted.raw_audit_id == fetch.raw_audit_id
    assert exhausted.raw_audit_version == fetch.raw_audit_version
    assert exhausted.raw_audit_content_hash == fetch.raw_audit_content_hash
    assert exhausted.run_id == fetch.run_id
    assert exhausted.ingested_run_id == fetch.ingested_run_id
    assert events == [
        "begin",
        "raw_audit",
        "audit_event",
        "failover_event",
        "failover_event",
        "commit",
    ]


def test_candidate_exhaustion_rolls_back_when_required_event_write_fails() -> None:
    use_case, _uow, _fetch, _publication, _validation, failover_writer, events = _build(
        [], identity_provider_name="macro-provider-candidates"
    )
    failover_writer.fail = True

    with pytest.raises(RuntimeError, match="failover writer failure"):
        use_case.exhaust_failover(
            indicator_code="CN_CPI",
            start=date(2026, 8, 1),
            end=date(2026, 8, 27),
            from_provider="provider-primary",
            attempted_provider_names=("provider-primary",),
            tolerance=0.01,
        )

    assert events[-1] == "rollback"
