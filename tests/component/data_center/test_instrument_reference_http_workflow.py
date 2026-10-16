"""Exercise source-only instrument provenance with only outbound HTTP replaced."""

import json
from collections.abc import Iterator
from typing import cast
from uuid import uuid4

import pytest

from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceProviderContract,
)
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.fact_and_operational_models import (
    RawAuditModel,
    RawPayloadModel,
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
STATUSES = ("L", "D", "P", "G", "UN")


@pytest.fixture(autouse=True)
def _schema() -> Iterator[None]:
    with isolated_schema((RawPayloadModel, RawAuditModel)):
        yield


def _body(items: list[list[object]]) -> bytes:
    return json.dumps(
        {"code": 0, "msg": None, "data": {"fields": list(FIELDS), "items": items}},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


class _InstrumentSession(_Session):
    def __init__(self) -> None:
        super().__init__(_Response(b"{}"))
        self.responses: list[_Response] = []

    def post(self, _url: str, **kwargs: object) -> _Response:
        self.calls.append(kwargs)
        body = kwargs["json"]
        assert isinstance(body, dict)
        assert body["api_name"] == "stock_basic"
        assert body["fields"] == ",".join(FIELDS)
        params = body["params"]
        assert isinstance(params, dict)
        assert params["exchange"] == "SSE"
        status = params["list_status"]
        assert status in STATUSES
        rows: list[list[object]] = []
        if status == "L":
            rows = [["600000.SH", "Synthetic listed", "SSE", "source-label", "L", "20200102", ""]]
        elif status == "D":
            rows = [["600001.SH", "Synthetic delisted", "SSE", None, "D", "20190102", "20261015"]]
        response = _Response(_body(rows))
        self.responses.append(response)
        return response


def test_http_to_retained_body_and_exact_raw_audit_occurrences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same body can recur while each actual client call owns another audit ID."""

    session = _InstrumentSession()
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    payload_repository = RawLandingRepository()
    retainer = RetainProviderResponsePayloadUseCase(payload_repository)
    dataset_key = "fixture.instrument.reference.raw"
    client = tushare_client.create_tushare_pro_client(
        token="fixture-instrument-key",
        http_url="https://market.example.test/pro",
        request_mode=tushare_client.TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
        dataset_key=dataset_key,
        provider_response_handler=retainer.execute,
    )
    audit_repository = RawAuditRepository()
    source = TushareInstrumentReferenceSource(
        cast(TushareStockBasicClientPort, client),
        payload_repository,
        DjangoInstrumentReferenceRawAuditOccurrenceWriter(audit_repository),
        provider_contract=InstrumentReferenceProviderContract(
            contract_id="fixture.instrument.reference",
            contract_version="fixture-v1",
            provider_name="tushare",
            dataset_key=dataset_key,
            api_name="stock_basic",
            fields=FIELDS,
            exchange_scope=("SSE",),
            list_status_scope=STATUSES,
        ),
        exchange_suffix_crosswalk=InstrumentReferenceExchangeSuffixCrosswalk(
            crosswalk_id="fixture.explicit.suffix",
            crosswalk_version="fixture-v1",
            exchange_suffix_pairs=(("SSE", "SH"),),
        ),
    )
    run_id, ingested_run_id = uuid4(), uuid4()
    candidates = [
        source.fetch_candidate(run_id=run_id, ingested_run_id=ingested_run_id) for _ in range(2)
    ]

    assert len(session.calls) == 10
    assert all(response.closed for response in session.responses)
    assert RawAuditModel.objects.count() == 10
    ids: set[str] = set()
    body_hashes: set[str] = set()
    for candidate in candidates:
        assert len(candidate.occurrences) == 5
        assert len(candidate.records) == 2
        assert sum(item.row_count for item in candidate.occurrences) == 2
        assert candidate.source_observed_at is None
        assert candidate.source_available_at is None
        assert candidate.must_not_use_for_decision is True
        assert candidate.must_not_execute is True
        assert candidate.blocked_reason == "INSTRUMENT_REFERENCE_SOURCE_ONLY_NOT_DECISION_READY"
        assert all(record.source_observed_at is None for record in candidate.records)
        assert all(record.source_available_at is None for record in candidate.records)
        for occurrence in candidate.occurrences:
            reference = occurrence.raw_audit_reference
            ids.add(reference.raw_audit_id)
            body_hashes.add(occurrence.response_body_sha256)
            audit = audit_repository.get_by_id(reference.raw_audit_id)
            assert audit is not None
            assert audit.exact_reference() == reference
            assert audit.status == "ok"
            assert audit.run_id == str(run_id)
            assert audit.ingested_run_id == str(ingested_run_id)
            assert audit.response_payload_hash == occurrence.response_body_sha256
            model = RawAuditModel.objects.get(pk=reference.raw_audit_id)
            model.full_clean()
            raw = payload_repository.get_by_hash(occurrence.raw_payload_hash)
            assert raw is not None
            assert raw.payload_id == occurrence.raw_payload_id
            assert raw.fetched_at == occurrence.response_completed_at == audit.fetched_at
            assert raw.request_params["params"]["list_status"] == occurrence.list_status
    assert len(ids) == 10
    assert len(body_hashes) == 3
