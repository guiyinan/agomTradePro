"""Real ORM persistence checks for byte-bound provider response payloads."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import cast

import pytest

from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
from apps.data_center.infrastructure.models import RawPayloadModel
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])

RESPONSE_COMPLETED_AT = datetime(2026, 10, 16, 4, 0, 1, 123456, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _raw_payload_schema(django_db_blocker: object) -> Iterator[None]:
    """Create or reuse only the RawPayload table owned by these tests."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((RawPayloadModel,)):
            yield


def _capture(body: bytes) -> ProviderResponseCapture:
    """Build one local response capture from strict JSON bytes."""

    return ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=RESPONSE_COMPLETED_AT,
        status_code=200,
        content_type="application/json; charset=utf-8",
        transport=ProviderResponseTransport.DIRECT,
    )


def _retain(
    repository: RawLandingRepository,
    capture: ProviderResponseCapture,
    *,
    provider_name: str = "tushare",
    dataset_key: str = "equity.reference",
    request_params: Mapping[str, object] | None = None,
    sensitive_values: tuple[str, ...] = (),
) -> ProviderResponsePayloadReference:
    """Persist a capture through the public use case and real Django repository."""

    return RetainProviderResponsePayloadUseCase(repository).execute(
        capture,
        provider_name=provider_name,
        dataset_key=dataset_key,
        api_name="stock_basic",
        request_params=request_params or {},
        sensitive_values=sensitive_values,
    )


def test_raw_landing_roundtrip_preserves_exact_utf8_body_and_decimal_lexemes() -> None:
    """Database retrieval retains original JSON bytes and exact decimal text."""

    body = (
        b'{\n  "code": 0,\n  "data": {"price": '
        b'0.123456789012345678901234567890123456789, "tiny": 1e-9999}\n}\n'
    )
    repository = RawLandingRepository()
    reference = _retain(repository, _capture(body))

    row = repository.get_by_hash(reference.payload_hash)

    assert row is not None
    retained_text = row.payload["retained_response_json"]
    assert retained_text == body.decode("utf-8")
    assert row.payload["response_body_sha256"] == sha256(body).hexdigest()
    assert reference.body_sha256 == sha256(body).hexdigest()
    assert reference.retained_content_sha256 == sha256(body).hexdigest()
    assert reference.original_body_retained is True
    assert reference.retained_content_encoding == "exact_original_utf8_json"
    assert row.payload_size_bytes == len(body)
    assert row.fetched_at == RESPONSE_COMPLETED_AT
    assert "observed_at" not in row.payload

    rebuilt_payload = parse_provider_response_json(retained_text.encode("utf-8"))
    assert type(rebuilt_payload) is dict
    values = cast(dict[str, object], rebuilt_payload)
    assert type(values["data"]) is dict
    data = cast(dict[str, object], values["data"])
    assert type(data["price"]) is Decimal
    assert str(data["price"]) == "0.123456789012345678901234567890123456789"
    assert type(data["tiny"]) is Decimal
    assert str(data["tiny"]) == "1E-9999"

    serialized_reference = json.loads(json.dumps(reference.to_payload()))
    rebuilt_reference = ProviderResponsePayloadReference.from_payload(
        cast(Mapping[str, object], serialized_reference)
    )
    assert rebuilt_reference == reference
    assert rebuilt_reference.to_payload()["time_semantics"] == ("local_response_body_completion")
    assert rebuilt_reference.verifies(row)


def test_redacted_database_payload_does_not_claim_to_retain_the_original_body() -> None:
    """Credential redaction preserves the source-body digest but labels stored text."""

    secret = "provider-secret-value-7719"
    body = ('{"code":0,"message":"echoed ' + secret + '","token":"' + secret + '"}').encode("utf-8")
    repository = RawLandingRepository()
    reference = _retain(
        repository,
        _capture(body),
        request_params={"token": secret},
    )

    row = repository.get_by_hash(reference.payload_hash)

    assert row is not None
    retained_text = row.payload["retained_response_json"]
    assert isinstance(retained_text, str)
    assert secret not in retained_text
    assert reference.body_sha256 == sha256(body).hexdigest()
    assert row.payload["response_body_sha256"] == reference.body_sha256
    assert reference.original_body_retained is False
    assert reference.retained_content_encoding == "redacted_canonical_json"
    assert reference.retained_content_sha256 == sha256(retained_text.encode("utf-8")).hexdigest()
    assert reference.retained_content_sha256 != reference.body_sha256
    assert row.request_params["token"] == "[REDACTED]"
    assert reference.verifies(row)


def test_exact_capture_retry_is_idempotent_and_scope_changes_do_not_collide() -> None:
    """Identical captures reuse one row; provider and dataset are part of identity."""

    capture = _capture(b'{"code":0,"data":{"items":[]}}')
    repository = RawLandingRepository()

    first = _retain(repository, capture)
    replay = _retain(repository, capture)
    other_provider = _retain(repository, capture, provider_name="eastmoney")
    other_dataset = _retain(repository, capture, dataset_key="equity.calendar")

    assert replay == first
    assert first.payload_hash == replay.payload_hash
    assert first.payload_id == replay.payload_id
    assert first.body_sha256 == other_provider.body_sha256 == other_dataset.body_sha256
    assert len({first.payload_hash, other_provider.payload_hash, other_dataset.payload_hash}) == 3
    assert len({first.payload_id, other_provider.payload_id, other_dataset.payload_id}) == 3
    assert RawPayloadModel._default_manager.count() == 3

    for reference in (first, other_provider, other_dataset):
        row = repository.get_by_hash(reference.payload_hash)
        assert row is not None
        assert reference.verifies(row)


def test_row_or_reference_tampering_breaks_persisted_reference_verification() -> None:
    """The verifier detects changed row contents and changed reference digests."""

    repository = RawLandingRepository()
    reference = _retain(repository, _capture(b'{"code":0,"value":12.3400}'))
    row = repository.get_by_hash(reference.payload_hash)
    assert row is not None
    assert reference.verifies(row)

    changed_row = replace(
        row,
        payload={**row.payload, "response_body_sha256": "f" * 64},
    )
    changed_reference = replace(reference, record_digest="sha256:" + "0" * 64)

    assert reference.verifies(changed_row) is False
    assert changed_reference.verifies(row) is False
