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
