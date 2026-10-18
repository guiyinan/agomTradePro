"""Prove immutable snapshots reread exact retained provider facts and audits."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from typing import cast
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db import router as database_router

from apps.data_center.application.instrument_reference_snapshot import (
    SaveInstrumentReferenceMappingUseCase,
    SaveInstrumentReferenceSnapshotUseCase,
)
from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceFetchRound,
    InstrumentReferenceMappingContent,
    InstrumentReferenceSnapshotContent,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceProviderContract,
)
from apps.data_center.domain.protocols import RawAuditRepositoryProtocol
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.fact_and_operational_models import (
    InstrumentReferenceMappingModel,
    InstrumentReferenceSnapshotModel,
    RawAuditModel,
    RawPayloadModel,
)
from apps.data_center.infrastructure.instrument_reference_snapshot_repository import (
    DjangoInstrumentReferenceSnapshotRepository,
    InstrumentReferenceSnapshotPersistenceError,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from apps.data_center.infrastructure.tushare_instrument_reference_source import (
    DjangoInstrumentReferenceRawAuditOccurrenceWriter,
    TushareInstrumentReferenceSource,
    TushareStockBasicClientPort,
)
from tests.support.isolated_schema import isolated_schema
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])

FIELDS = ("ts_code", "name", "exchange", "market", "list_status", "list_date", "delist_date")


@pytest.fixture(autouse=True)
def _schema() -> Iterator[None]:
    with isolated_schema(
        (
            RawPayloadModel,
            RawAuditModel,
            InstrumentReferenceMappingModel,
            InstrumentReferenceSnapshotModel,
        )
    ):
        yield


class _StockBasicSession(_Session):
    """Return synthetic exact HTTP bodies for explicit stock-basic request scopes."""

    def __init__(self) -> None:
        super().__init__(_Response(b"{}"))

    def post(self, url: str, **kwargs: object) -> _Response:
        """Capture the request and return only fixture-owned stock-basic rows."""

        del url
        self.calls.append(kwargs)
        request = kwargs.get("json")
        assert isinstance(request, dict)
        params = request.get("params")
        assert isinstance(params, dict)
        status = params.get("list_status")
        rows: list[list[object]] = []
        if status == "L":
            rows = [["600000.SH", "Fixture bank", "SSE", "fixture-main", "L", "20200102", ""]]
        body = _body(rows)
        self.response = _Response(body)
        return cast(_Response, self.response)


class _OtherAliasPayloadReader:
    """Represent an injected exact reader routed to a different database alias."""

    @property
    def unit_of_work_key(self) -> str:
        """Expose the deliberately incompatible alias for constructor validation."""

        return "django:other"

    def get_by_id(self, payload_id: str) -> RawPayload | None:
        """Return no row because this fake only tests alias binding."""

        del payload_id
        return None


class _RouteRawPayloadElsewhere:
    """Route raw evidence to another alias so composition must fail closed."""

    def db_for_read(self, model: type[object], **hints: object) -> str | None:
        """Route only raw-payload reads away from the snapshot's fixed alias."""

        del hints
        return "other" if model is RawPayloadModel else None

    def db_for_write(self, model: type[object], **hints: object) -> str | None:
        """Route only raw-payload writes away from the snapshot's fixed alias."""

        del hints
        return "other" if model is RawPayloadModel else None


def _body(rows: list[list[object]]) -> bytes:
    """Serialize one synthetic successful stock-basic provider response."""

    return json.dumps(
        {"code": 0, "msg": None, "data": {"fields": list(FIELDS), "items": rows}},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def test_repository_rejects_raw_payload_reader_on_a_different_database_alias() -> None:
    """Prevent identical facts from being assembled across independent databases."""

    with pytest.raises(ValueError, match="share one alias"):
        DjangoInstrumentReferenceSnapshotRepository(
            cast(RawAuditRepositoryProtocol, RawAuditRepository()),
            _OtherAliasPayloadReader(),
        )


def test_repository_rejects_database_router_that_splits_raw_payload_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse routed raw evidence instead of trusting caller-reported UoW text."""

    monkeypatch.setattr(database_router, "routers", [_RouteRawPayloadElsewhere()])
    with pytest.raises(ValueError, match="route to the default alias"):
        DjangoInstrumentReferenceSnapshotRepository(
            cast(RawAuditRepositoryProtocol, RawAuditRepository()),
            RawLandingRepository(),
        )


@pytest.fixture
def persisted_source_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[DjangoInstrumentReferenceSnapshotRepository, InstrumentReferenceSnapshotContent]:
    """Compose real RawPayload/RawAudit storage around synthetic HTTP only."""

    session = _StockBasicSession()
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    raw_payload_repository = RawLandingRepository()
    retainer = RetainProviderResponsePayloadUseCase(raw_payload_repository)
    dataset_key = "fixture.instrument-reference.stock-basic"
    client = tushare_client.create_tushare_pro_client(
        token="fixture-only-token",
        http_url="https://market.example.test/pro",
        request_mode=tushare_client.TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
        dataset_key=dataset_key,
        provider_response_handler=retainer.execute,
    )
    provider_contract = InstrumentReferenceProviderContract(
        contract_id="fixture.instrument-reference.stock-basic",
        contract_version="fixture-v1",
        provider_name="tushare",
        dataset_key=dataset_key,
        api_name="stock_basic",
        fields=FIELDS,
        exchange_scope=("SSE",),
        list_status_scope=("L", "D"),
    )
    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="fixture.stock-basic-crosswalk",
        crosswalk_version="fixture-v1",
        exchange_suffix_pairs=(("SSE", "SH"),),
    )
    raw_audit_repository = RawAuditRepository()
    source = TushareInstrumentReferenceSource(
        cast(TushareStockBasicClientPort, client),
        raw_payload_repository,
        DjangoInstrumentReferenceRawAuditOccurrenceWriter(raw_audit_repository),
        provider_contract=provider_contract,
        exchange_suffix_crosswalk=crosswalk,
    )
    run_id = uuid4()
    ingested_run_id = uuid4()
    candidates = (
        source.fetch_candidate(run_id=run_id, ingested_run_id=ingested_run_id),
        source.fetch_candidate(run_id=run_id, ingested_run_id=ingested_run_id),
    )
    mapping_content = InstrumentReferenceMappingContent(
        mapping_id="fixture.instrument-reference-map",
        mapping_version="fixture-v1",
        source_crosswalk=crosswalk,
        exchange_rule_market_pairs=(("SSE", "FIXTURE_SSE"),),
        exchange_source_market_board_pairs=(("SSE", "fixture-main", "FIXTURE_MAIN"),),
    )
    last_capture = max(
        occurrence.response_completed_at
        for candidate in candidates
        for occurrence in candidate.occurrences
    )
    clock_origin = last_capture + timedelta(seconds=1)
    clock_values = iter((clock_origin, clock_origin + timedelta(seconds=5)))
    repository = DjangoInstrumentReferenceSnapshotRepository(
        cast(RawAuditRepositoryProtocol, raw_audit_repository),
        raw_payload_repository,
        clock=lambda: next(clock_values),
    )
    mapping_record = SaveInstrumentReferenceMappingUseCase(repository).execute(mapping_content)
    content = InstrumentReferenceSnapshotContent(
        run_id=run_id,
        mapping_record=mapping_record,
        fetch_rounds=(
            InstrumentReferenceFetchRound(fetch_round_id=uuid4(), candidate=candidates[0]),
            InstrumentReferenceFetchRound(fetch_round_id=uuid4(), candidate=candidates[1]),
        ),
    )
    return repository, content


def test_repository_roundtrips_empty_scopes_raw_occurrences_and_first_seal(
    persisted_source_snapshot: tuple[
        DjangoInstrumentReferenceSnapshotRepository,
        InstrumentReferenceSnapshotContent,
    ],
) -> None:
    """Preserve same-run rounds, empty results, exact evidence and idempotent retry."""

    repository, content = persisted_source_snapshot
    use_case = SaveInstrumentReferenceSnapshotUseCase(repository)
    saved = use_case.execute(content)
    retried = use_case.execute(content)
    loaded = repository.get_snapshot(saved.snapshot_id)
    mapping_retry = repository.save_mapping(content.mapping_record.content)

    assert saved.snapshot_id == retried.snapshot_id
    assert saved.recorded_at == retried.recorded_at
    assert saved.record_digest == retried.record_digest
    assert loaded == saved
    assert loaded is not None
    assert loaded.content.occurrence_count == 4
    assert loaded.content.empty_occurrence_count == 2
    assert loaded.content.record_count == 2
    assert mapping_retry == content.mapping_record
    assert (
        len(
            {
                occurrence.raw_audit_reference.raw_audit_id
                for fetch_round in loaded.content.fetch_rounds
                for occurrence in fetch_round.candidate.occurrences
            }
        )
        == 4
    )
    assert (
        len(
            {
                occurrence.response_body_sha256
                for fetch_round in loaded.content.fetch_rounds
                for occurrence in fetch_round.candidate.occurrences
            }
        )
        == 2
    )
    assert InstrumentReferenceSnapshotModel.objects.count() == 1


@pytest.mark.parametrize("mutation", ["name", "date", "market", "extra_record"])
def test_repository_reparses_raw_body_before_sealing_candidate_facts(
    persisted_source_snapshot: tuple[
        DjangoInstrumentReferenceSnapshotRepository,
        InstrumentReferenceSnapshotContent,
    ],
    mutation: str,
) -> None:
    """Reject same-count source facts changed after the raw response was retained."""

    from dataclasses import replace

    from apps.data_center.domain.instrument_reference_snapshot import (
        InstrumentReferenceFetchRound,
        InstrumentReferenceSnapshotContent,
    )

    repository, content = persisted_source_snapshot
    first_round = content.fetch_rounds[0]
    candidate = first_round.candidate
    records = list(candidate.records)
    occurrences = list(candidate.occurrences)
    if mutation == "name":
        records[0] = replace(records[0], name="Caller-modified")
    elif mutation == "date":
        from datetime import date

        records[0] = replace(records[0], list_date_raw="20200103", list_date=date(2020, 1, 3))
    elif mutation == "market":
        records[0] = replace(records[0], source_market="forged-market")
    else:
        occurrences[0] = replace(occurrences[0], row_count=2)
        records.append(
            replace(
                records[0],
                ts_code="600001.SH",
                name="Injected row",
                occurrence_id=occurrences[0].occurrence_id,
            )
        )
    changed_candidate = replace(
        candidate,
        occurrences=tuple(occurrences),
        records=tuple(records),
    )
    changed_content = InstrumentReferenceSnapshotContent(
        run_id=content.run_id,
        mapping_record=content.mapping_record,
        fetch_rounds=(
            InstrumentReferenceFetchRound(
                fetch_round_id=first_round.fetch_round_id,
                candidate=changed_candidate,
            ),
        ),
    )

    with pytest.raises(InstrumentReferenceSnapshotPersistenceError):
        repository.save_snapshot(changed_content)
    assert InstrumentReferenceSnapshotModel.objects.count() == 0


def test_model_and_queryset_reject_snapshot_mutation_shortcuts(
    persisted_source_snapshot: tuple[
        DjangoInstrumentReferenceSnapshotRepository,
        InstrumentReferenceSnapshotContent,
    ],
) -> None:
    """Deny instance, stale-PK, queryset, and bulk mutation paths."""

    repository, content = persisted_source_snapshot
    snapshot = repository.save_snapshot(content)
    row = InstrumentReferenceSnapshotModel.objects.get(pk=snapshot.snapshot_id)
    with pytest.raises(ValidationError):
        row.save()
    stale = InstrumentReferenceSnapshotModel(
        snapshot_id=snapshot.snapshot_id,
        run_id=snapshot.content.run_id,
        mapping_record_id=snapshot.mapping_record.mapping_record_id,
        snapshot_payload=snapshot.content.to_payload(),
        content_hash=snapshot.content_hash,
        recorded_at=snapshot.recorded_at,
        record_digest=snapshot.record_digest,
        round_count=len(snapshot.content.fetch_rounds),
        occurrence_count=snapshot.content.occurrence_count,
        record_count=snapshot.content.record_count,
    )
    with pytest.raises(ValidationError):
        stale.save(force_insert=True)
    with pytest.raises(ValidationError):
        InstrumentReferenceSnapshotModel.objects.filter(pk=snapshot.snapshot_id).update(
            record_count=0
        )
    with pytest.raises(ValidationError):
        InstrumentReferenceSnapshotModel.objects.filter(pk=snapshot.snapshot_id).delete()
    with pytest.raises(ValidationError):
        InstrumentReferenceSnapshotModel.objects.bulk_create([stale])


def test_raw_sql_timestamp_tampering_is_detected_on_exact_read(
    persisted_source_snapshot: tuple[
        DjangoInstrumentReferenceSnapshotRepository,
        InstrumentReferenceSnapshotContent,
    ],
) -> None:
    """A low-level mutation bypassing ORM guards still fails the record seal."""

    repository, content = persisted_source_snapshot
    saved = repository.save_snapshot(content)
    with connection.cursor() as cursor:
        updated = cursor.execute(
            "UPDATE data_center_instrument_reference_snapshot SET recorded_at = %s WHERE snapshot_id = %s",
            [saved.recorded_at + timedelta(seconds=1), saved.snapshot_id.hex],
        )
        assert updated.rowcount == 1

    with pytest.raises(InstrumentReferenceSnapshotPersistenceError):
        repository.get_snapshot(saved.snapshot_id)


@pytest.mark.parametrize("target", ["raw_audit", "raw_payload"])
def test_exact_read_blocks_tampered_source_occurrence_or_body(
    persisted_source_snapshot: tuple[
        DjangoInstrumentReferenceSnapshotRepository,
        InstrumentReferenceSnapshotContent,
    ],
    target: str,
) -> None:
    """Require exact audit scope and exact retained response bytes on every read."""

    repository, content = persisted_source_snapshot
    saved = repository.save_snapshot(content)
    occurrence = content.fetch_rounds[0].candidate.occurrences[0]
    if target == "raw_audit":
        model = RawAuditModel.objects.get(pk=occurrence.raw_audit_reference.raw_audit_id)
        extra = model.extra
        extra["instrument_reference_occurrence"]["exchange"] = "SZSE"
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE data_center_raw_audit SET extra = %s WHERE id = %s",
                [json.dumps(extra), int(occurrence.raw_audit_reference.raw_audit_id)],
            )
    else:
        model = RawPayloadModel.objects.get(payload_id=occurrence.raw_payload_id)
        payload = model.payload
        retained = payload["retained_response_json"]
        payload["retained_response_json"] = retained.replace("Fixture bank", "Forged bank")
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE data_center_raw_payload SET payload = %s WHERE payload_id = %s",
                [json.dumps(payload), model.payload_id.hex],
            )

    with pytest.raises(InstrumentReferenceSnapshotPersistenceError):
        repository.get_snapshot(saved.snapshot_id)


def _load_current_reference_reader_composition() -> object:
    """Report the absent adapter as an assertion rather than an import error."""

    import importlib
    import importlib.util

    module_name = "apps.simulated_trading.execution_current_reference_composition"
    spec = importlib.util.find_spec(module_name)
    assert spec is not None, "current-reference reader composition is not implemented"
    module = importlib.import_module(module_name)
    assert callable(getattr(module, "build_current_reference_identity_reader", None))
    return module


def _install_native_reference_config(
    monkeypatch: pytest.MonkeyPatch,
    composition: object,
    *,
    selector: dict[str, object] | None,
    as_of: object,
) -> list[tuple[str, str, object]]:
    """Mock only Config Center public read ports; the source reader stays real."""

    from datetime import datetime, timedelta

    from apps.config_center.domain.runtime_config import (
        RuntimeConfigProfile,
        RuntimeConfigSnapshot,
        RuntimeProfileStatus,
        hash_public_runtime_projection,
        hash_runtime_profile_values,
    )

    assert isinstance(as_of, datetime)
    values: dict[str, object] = {}
    if selector is not None:
        values["config_center.market.simulated_current_reference_selection"] = selector
    activated_at = as_of - timedelta(seconds=5)
    profile = RuntimeConfigProfile(
        profile_id="native-fixture-profile",
        profile_key="native.fixture-market",
        environment="simulated-native-test",
        version=1,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash=hash_runtime_profile_values(values),
        created_at=activated_at - timedelta(seconds=1),
        activated_at=activated_at,
    )
    runtime_snapshot = RuntimeConfigSnapshot(
        snapshot_id="native-fixture-runtime-snapshot",
        profile_id=profile.profile_id,
        profile_key=profile.profile_key,
        profile_version=profile.version,
        snapshot_hash=hash_public_runtime_projection(values),
        resolved_values=values,
        generated_at=as_of - timedelta(seconds=1),
        effective_from=activated_at,
    )
    calls: list[tuple[str, str, object]] = []

    def get_value(
        *,
        environment: str,
        definition_key: str,
        as_of: datetime,
    ) -> object | None:
        calls.append((environment, definition_key, as_of))
        return selector

    monkeypatch.setattr(
        composition,
        "get_active_runtime_profile",
        lambda environment: profile,
    )
    monkeypatch.setattr(
        composition,
        "get_latest_runtime_snapshot",
        lambda profile_key: runtime_snapshot,
    )
    monkeypatch.setattr(composition, "get_active_runtime_value", get_value)
    return calls


def _native_reference_selector(snapshot: object) -> dict[str, object]:
    from apps.data_center.domain.instrument_reference_snapshot import (
        InstrumentReferenceSnapshotRecord,
    )

    record = cast(InstrumentReferenceSnapshotRecord, snapshot)
    mapping = record.mapping_record
    item: dict[str, object] = {
        "security_id": "risk-native-fixture-001",
        "asset_code": "600000.SH",
        "source_code": "600000.SH",
        "snapshot_id": str(record.snapshot_id),
        "snapshot_content_hash": record.content_hash,
        "snapshot_record_digest": record.record_digest,
        "mapping_record_id": str(mapping.mapping_record_id),
        "mapping_id": mapping.content.mapping_id,
        "mapping_version": mapping.content.mapping_version,
        "mapping_content_hash": mapping.content_hash,
        "mapping_record_digest": mapping.record_digest,
    }
    value: dict[str, object] = {
        "schema": "normal-simulated-current-reference-selection.v1",
        "purpose": "normal_simulated_current_reference",
        "max_local_reference_age_seconds": 600,
        "items": [item],
    }
    return value


def test_current_reference_adapter_reads_exact_saved_source_and_config_selection(
    persisted_source_snapshot: tuple[
        DjangoInstrumentReferenceSnapshotRepository,
        InstrumentReferenceSnapshotContent,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Map the real raw/audit-backed default-alias snapshot without writing on read."""

    from datetime import UTC

    from django.utils import timezone

    repository, content = persisted_source_snapshot
    saved = SaveInstrumentReferenceSnapshotUseCase(repository).execute(content)
    selector = _native_reference_selector(saved)
    as_of = max(timezone.now().astimezone(UTC), saved.recorded_at) + timedelta(seconds=1)
    composition = _load_current_reference_reader_composition()
    config_calls = _install_native_reference_config(
        monkeypatch,
        composition,
        selector=selector,
        as_of=as_of,
    )
    reader_factory = composition.build_current_reference_identity_reader
    reader = reader_factory(runtime_environment="simulated-native-test")
    before = (
        RawAuditModel.objects.count(),
        RawPayloadModel.objects.count(),
        InstrumentReferenceMappingModel.objects.count(),
        InstrumentReferenceSnapshotModel.objects.count(),
    )

    identity = reader.resolve_current_reference_identity(
        asset_code="600000.SH",
        as_of=as_of,
    )

    after = (
        RawAuditModel.objects.count(),
        RawPayloadModel.objects.count(),
        InstrumentReferenceMappingModel.objects.count(),
        InstrumentReferenceSnapshotModel.objects.count(),
    )
    assert identity is not None
    source = identity.source_evidence
    assert source.snapshot_id == saved.snapshot_id
    assert source.snapshot_content_hash == saved.content_hash
    assert source.snapshot_record_digest == saved.record_digest
    assert source.mapping_record_id == saved.mapping_record.mapping_record_id
    assert source.mapping_content_hash == saved.mapping_record.content_hash
    assert source.mapping_record_digest == saved.mapping_record.record_digest
    assert source.source_exchange == "SSE"
    assert source.source_market == "fixture-main"
    assert source.rule_market == "FIXTURE_SSE"
    assert source.board == "FIXTURE_MAIN"
    assert source.source_observed_at is None
    assert source.source_available_at is None
    assert source.must_not_use_for_decision is True
    assert source.must_not_execute is True
    matching_occurrences = [
        occurrence
        for fetch_round in content.fetch_rounds
        for occurrence in fetch_round.candidate.occurrences
        if any(
            record.ts_code == "600000.SH" and record.occurrence_id == occurrence.occurrence_id
            for record in fetch_round.candidate.records
        )
    ]
    expected_occurrence = max(
        matching_occurrences,
        key=lambda occurrence: (
            occurrence.response_completed_at,
            str(occurrence.occurrence_id),
        ),
    )
    assert identity.source_occurrence_id == expected_occurrence.occurrence_id
    assert identity.reference_response_completed_at == expected_occurrence.response_completed_at
    assert after == before
    assert config_calls == [
        (
            "simulated-native-test",
            "config_center.market.simulated_current_reference_selection",
            as_of,
        )
    ]


def test_current_reference_adapter_returns_none_for_missing_optional_selection(
    persisted_source_snapshot: tuple[
        DjangoInstrumentReferenceSnapshotRepository,
        InstrumentReferenceSnapshotContent,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An absent optional selector remains unavailable and does not invent identity."""

    from datetime import UTC

    from django.utils import timezone

    repository, content = persisted_source_snapshot
    saved = SaveInstrumentReferenceSnapshotUseCase(repository).execute(content)
    as_of = max(timezone.now().astimezone(UTC), saved.recorded_at) + timedelta(seconds=1)
    composition = _load_current_reference_reader_composition()
    config_calls = _install_native_reference_config(
        monkeypatch,
        composition,
        selector=None,
        as_of=as_of,
    )
    reader_factory = composition.build_current_reference_identity_reader
    reader = reader_factory(runtime_environment="simulated-native-test")

    identity = reader.resolve_current_reference_identity(
        asset_code="600000.SH",
        as_of=as_of,
    )

    assert identity is None
    assert saved.snapshot_id is not None
    assert config_calls == [
        (
            "simulated-native-test",
            "config_center.market.simulated_current_reference_selection",
            as_of,
        )
    ]


def test_current_reference_adapter_wraps_real_raw_evidence_tampering_as_a_block(
    persisted_source_snapshot: tuple[
        DjangoInstrumentReferenceSnapshotRepository,
        InstrumentReferenceSnapshotContent,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The composition path cannot bypass the repository's retained-body recheck."""

    from datetime import UTC

    from django.utils import timezone

    from apps.simulated_trading.application.execution_settlement_uow import (
        SimulatedTradeExecutionBlocked,
    )

    repository, content = persisted_source_snapshot
    saved = SaveInstrumentReferenceSnapshotUseCase(repository).execute(content)
    selector = _native_reference_selector(saved)
    as_of = max(timezone.now().astimezone(UTC), saved.recorded_at) + timedelta(seconds=1)
    composition = _load_current_reference_reader_composition()
    config_calls = _install_native_reference_config(
        monkeypatch,
        composition,
        selector=selector,
        as_of=as_of,
    )
    occurrence = next(
        occurrence
        for fetch_round in content.fetch_rounds
        for occurrence in fetch_round.candidate.occurrences
        if any(
            record.ts_code == "600000.SH" and record.occurrence_id == occurrence.occurrence_id
            for record in fetch_round.candidate.records
        )
    )
    payload_row = RawPayloadModel.objects.get(payload_id=occurrence.raw_payload_id)
    payload = payload_row.payload
    retained_response = payload["retained_response_json"]
    payload["retained_response_json"] = retained_response.replace(
        "Fixture bank",
        "Tampered bank",
    )
    with connection.cursor() as cursor:
        updated = cursor.execute(
            "UPDATE data_center_raw_payload SET payload = %s WHERE payload_id = %s",
            [json.dumps(payload), payload_row.payload_id.hex],
        )
        assert updated.rowcount == 1
    reader_factory = composition.build_current_reference_identity_reader
    reader = reader_factory(runtime_environment="simulated-native-test")

    with pytest.raises(SimulatedTradeExecutionBlocked) as exc_info:
        reader.resolve_current_reference_identity(asset_code="600000.SH", as_of=as_of)

    assert exc_info.value.__cause__ is not None
    assert config_calls == [
        (
            "simulated-native-test",
            "config_center.market.simulated_current_reference_selection",
            as_of,
        )
    ]


@pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "apps.audit",
        "apps.config_center",
        "apps.data_center",
    ],
)
def test_current_reference_adapter_reads_real_persisted_config_and_source(
    persisted_source_snapshot: tuple[
        DjangoInstrumentReferenceSnapshotRepository,
        InstrumentReferenceSnapshotContent,
    ],
) -> None:
    """Bind persisted Config Center metadata to the exact retained source read."""

    import os
    from datetime import UTC, timedelta

    from django.utils import timezone

    from apps.config_center.application.runtime_public import (
        activate_runtime_profile_patch,
        get_active_runtime_profile,
        get_active_runtime_value,
        get_latest_runtime_snapshot,
    )
    from apps.config_center.infrastructure.models import (
        RuntimeConfigDefinitionModel,
        RuntimeConfigProfileModel,
        RuntimeConfigRevisionModel,
        RuntimeConfigSnapshotModel,
        RuntimeConfigValueModel,
    )
    from apps.simulated_trading.execution_current_reference_composition import (
        build_current_reference_identity_reader,
    )
    from tests.support.runtime_config import configure_critical_runtime

    repository, content = persisted_source_snapshot
    saved = SaveInstrumentReferenceSnapshotUseCase(repository).execute(content)
    selector = _native_reference_selector(saved)
    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    runtime_environment = "production" if settings_module.endswith(".production") else "development"

    configure_critical_runtime()
    created_profile, created_snapshot = activate_runtime_profile_patch(
        environment=runtime_environment,
        patch={
            "config_center.market.simulated_current_reference_selection": selector,
        },
        actor="current-reference-integration-test",
        reason="bind an exact persisted selector to retained native test evidence",
    )
    activated_at = created_profile.activated_at
    assert activated_at is not None
    as_of = max(
        timezone.now().astimezone(UTC),
        saved.recorded_at,
        activated_at,
        created_snapshot.generated_at,
    ) + timedelta(seconds=1)
    before = (
        RawAuditModel.objects.count(),
        RawPayloadModel.objects.count(),
        InstrumentReferenceMappingModel.objects.count(),
        InstrumentReferenceSnapshotModel.objects.count(),
        RuntimeConfigDefinitionModel.objects.count(),
        RuntimeConfigProfileModel.objects.count(),
        RuntimeConfigValueModel.objects.count(),
        RuntimeConfigRevisionModel.objects.count(),
        RuntimeConfigSnapshotModel.objects.count(),
    )
    active_profile = get_active_runtime_profile(runtime_environment)
    latest_snapshot = get_latest_runtime_snapshot(created_profile.profile_key)
    selected_value = get_active_runtime_value(
        environment=runtime_environment,
        definition_key="config_center.market.simulated_current_reference_selection",
        as_of=as_of,
    )
    reader = build_current_reference_identity_reader(runtime_environment=runtime_environment)
    identity = reader.resolve_current_reference_identity(
        asset_code="600000.SH",
        as_of=as_of,
    )
    after = (
        RawAuditModel.objects.count(),
        RawPayloadModel.objects.count(),
        InstrumentReferenceMappingModel.objects.count(),
        InstrumentReferenceSnapshotModel.objects.count(),
        RuntimeConfigDefinitionModel.objects.count(),
        RuntimeConfigProfileModel.objects.count(),
        RuntimeConfigValueModel.objects.count(),
        RuntimeConfigRevisionModel.objects.count(),
        RuntimeConfigSnapshotModel.objects.count(),
    )

    assert identity is not None
    assert active_profile is not None
    assert latest_snapshot is not None
    assert active_profile.profile_id == created_profile.profile_id
    assert active_profile.content_hash == created_profile.content_hash
    assert active_profile.version == created_profile.version
    assert latest_snapshot.snapshot_id == created_snapshot.snapshot_id
    assert latest_snapshot.snapshot_hash == created_snapshot.snapshot_hash
    assert latest_snapshot.profile_id == active_profile.profile_id
    assert latest_snapshot.profile_version == active_profile.version
    assert selected_value == selector
    assert identity.selection.profile_id == active_profile.profile_id
    assert identity.selection.profile_key == active_profile.profile_key
    assert identity.selection.environment == runtime_environment
    assert identity.selection.profile_version == active_profile.version
    assert identity.selection.profile_content_hash == active_profile.content_hash
    assert identity.selection.runtime_snapshot_id == latest_snapshot.snapshot_id
    assert identity.selection.runtime_snapshot_hash == latest_snapshot.snapshot_hash
    assert identity.selection.profile_activated_at == activated_at
    assert identity.selection.runtime_snapshot_generated_at == latest_snapshot.generated_at
    assert identity.selection.selected_at == as_of
    assert identity.source_evidence.snapshot_id == saved.snapshot_id
    assert identity.source_evidence.snapshot_content_hash == saved.content_hash
    assert identity.source_evidence.source_observed_at is None
    assert identity.source_evidence.source_available_at is None
    assert identity.source_evidence.must_not_use_for_decision is True
    assert identity.source_evidence.must_not_execute is True
    assert after == before
