"""Safe persistence contracts for opt-in non-financial provider responses."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from typing import cast

import pytest

from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
    ProviderResponsePayloadRepositoryPort,
    ProviderResponsePayloadRetentionError,
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    canonical_provider_response_json,
    parse_provider_response_json,
)
from apps.data_center.domain.raw_landing import RawPayload, raw_payload_record_digest

NOW = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)


class _Repository:
    """Small in-memory RawPayload repository with production identity semantics."""

    def __init__(self) -> None:
        self.rows: dict[str, RawPayload] = {}

    def save(self, payload: RawPayload) -> RawPayload:
        existing = self.rows.get(payload.payload_hash)
        if existing is not None and existing != payload:
            raise ValueError("raw_payload_immutable_conflict")
        self.rows[payload.payload_hash] = payload
        return payload

    def get_by_hash(self, payload_hash: str) -> RawPayload | None:
        return self.rows.get(payload_hash)


def _capture(
    body: bytes,
    payload: object,
    *,
    completed_at: datetime = NOW,
    transport: ProviderResponseTransport = ProviderResponseTransport.DIRECT,
) -> ProviderResponseCapture:
    """Build a capture from the exact HTTP body and its already-decoded JSON."""

    from hashlib import sha256

    return ProviderResponseCapture(
        body=body,
        payload=payload,
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=completed_at,
        status_code=200,
        content_type="application/json",
        transport=transport,
    )


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("body", bytearray(b'{"code":0}')),
        ("body_sha256", "not-a-digest"),
        ("body_sha256", sha256(b'{"code":1}').hexdigest()),
        ("body_size_bytes", True),
        (
            "response_completed_at",
            datetime(2026, 10, 16, 12, tzinfo=timezone(timedelta(hours=8))),
        ),
        ("status_code", True),
        ("content_type", "application/json\nheader-injection"),
        ("transport", "direct"),
    ],
)
def test_capture_rejects_untyped_or_unverifiable_public_fields(
    field_name: str, field_value: object
) -> None:
    """Public capture fields cannot be replaced by malformed adapter values."""

    capture = _capture(b'{"code":0}', {"code": 0})
    with pytest.raises(ValueError):
        replace(capture, **{field_name: field_value})


def test_capture_payload_freshness_and_acquisition_time_are_public_contracts() -> None:
    """The exposed payload check detects mutation and acquired_at is completion time."""

    payload = {"code": 0, "data": {"items": []}}
    body = b'{"code":0,"data":{"items":[]}}'
    capture = _capture(body, payload)

    assert capture.acquired_at == NOW
    assert capture.payload_matches_body() is True
    payload["code"] = 1
    assert capture.payload_matches_body() is False
    payload["code"] = object()
    assert capture.payload_matches_body() is False


def test_strict_json_parser_rejects_non_bytes_and_decimal_overflow() -> None:
    """Invalid body types and Decimal parser overflow are stable validation errors."""

    with pytest.raises(ValueError, match="body_must_be_bytes"):
        parse_provider_response_json(cast(bytes, "{}"))
    with pytest.raises(ValueError, match="strict_json"):
        parse_provider_response_json(b'{"value":1e' + b"9" * 60 + b"}")


def test_canonical_response_json_rejects_non_json_values_without_numeric_coercion() -> None:
    """Canonical JSON preserves exact Decimal values and rejects invalid Python types."""

    assert canonical_provider_response_json(None) == "null"
    assert canonical_provider_response_json(Decimal("0.1234567890123456789012345")) == (
        "0.1234567890123456789012345"
    )
    with pytest.raises(ValueError, match="decimal_not_finite"):
        canonical_provider_response_json(Decimal("Infinity"))
    with pytest.raises(ValueError, match="float_not_finite"):
        canonical_provider_response_json(float("inf"))
    with pytest.raises(ValueError, match="integer_too_large"):
        canonical_provider_response_json(10**256)
    with pytest.raises(ValueError, match="key_not_string"):
        canonical_provider_response_json({1: "not-json"})
    with pytest.raises(ValueError, match="value_not_json"):
        canonical_provider_response_json(object())


def test_retention_binds_exact_bytes_and_redacted_rawpayload_without_faking_body() -> None:
    """The body digest, retained JSON digest, and full record digest stay distinct."""

    body = b'{ "code": 0, "data": {"items": [["000001.SZ", 1.25]]}}'
    decoded = cast(
        dict[str, object],
        parse_provider_response_json(body),
    )
    repository = _Repository()
    use_case = RetainProviderResponsePayloadUseCase(repository)

    reference = use_case.execute(
        _capture(body, decoded),
        provider_name="tushare",
        dataset_key="equity.quote.snapshot",
        api_name="quote",
        request_params={"fields": "ts_code,price", "params": {"ts_code": "000001.SZ"}},
    )

    row = repository.get_by_hash(reference.payload_hash)
    assert row is not None
    assert reference.body_sha256 == _capture(body, decoded).body_sha256
    assert reference.retained_content_sha256 == reference.body_sha256
    assert reference.record_digest == raw_payload_record_digest(row)
    assert row.payload_size_bytes == len(body)
    assert row.fetched_at == NOW
    assert row.payload["response_body_sha256"] == reference.body_sha256
    retained_text = row.payload["retained_response_json"]
    assert retained_text == body.decode("utf-8")
    assert parse_provider_response_json(retained_text.encode("utf-8")) == decoded
    assert reference.original_body_retained is True
    assert reference.retained_content_encoding == "exact_original_utf8_json"
    assert reference.response_completed_at == NOW
    assert "observed_at" not in row.payload
    serialized_reference = json.loads(json.dumps(reference.to_payload()))
    assert row.run_id == ""
    assert "run_id" not in serialized_reference
    rebuilt = ProviderResponsePayloadReference.from_payload(serialized_reference)
    assert rebuilt == reference
    assert rebuilt.verifies(row)
    mutated_row = replace(row, payload={**row.payload, "response_body_sha256": "f" * 64})
    assert not rebuilt.verifies(mutated_row)


def test_run_id_is_bound_to_raw_row_and_optional_reference_payload() -> None:
    """A run identity binds the RawPayload record digest separately from body and payload hashes."""

    body = b'{"code":0,"data":{"price":12.5}}'
    repository = _Repository()
    reference = RetainProviderResponsePayloadUseCase(repository).execute(
        _capture(body, parse_provider_response_json(body)),
        provider_name="tushare",
        dataset_key="equity.quote.snapshot",
        api_name="quote",
        request_params={"ts_code": "000001.SZ"},
        run_id="00000000-0000-4000-8000-000000000001",
    )

    row = repository.get_by_hash(reference.payload_hash)
    assert row is not None
    assert row.run_id == reference.run_id == "00000000-0000-4000-8000-000000000001"
    assert reference.body_sha256 == sha256(body).hexdigest()
    assert len(reference.body_sha256) == 64
    assert not reference.body_sha256.startswith("sha256:")
    assert reference.record_digest == raw_payload_record_digest(row)
    assert reference.payload_hash.startswith("sha256:")
    assert reference.record_digest.startswith("sha256:")

    serialized = reference.to_payload()
    assert serialized["run_id"] == reference.run_id
    rebuilt = ProviderResponsePayloadReference.from_payload(serialized)
    assert rebuilt == reference
    assert rebuilt.verifies(row)

    from apps.data_center.infrastructure.instrument_reference_capture_persistence import (
        _reference_from_raw_payload,
    )

    rehydrated = _reference_from_raw_payload(row)
    assert rehydrated == reference
    assert rehydrated.verifies(row)

    other_run_row = replace(row, run_id="00000000-0000-4000-8000-000000000002")
    assert other_run_row.payload_hash == row.payload_hash
    assert raw_payload_record_digest(other_run_row) != reference.record_digest
    assert rebuilt.verifies(other_run_row) is False
    assert replace(row, provider_name="akshare").payload_hash == row.payload_hash
    assert rebuilt.verifies(replace(row, provider_name="akshare")) is False


def test_invalid_run_id_is_rejected_without_saving_a_payload() -> None:
    """Malformed capture identifiers fail before the RawPayload port is called."""

    repository = _Repository()
    body = b'{"code":0}'

    with pytest.raises(ProviderResponsePayloadRetentionError) as caught:
        RetainProviderResponsePayloadUseCase(repository).execute(
            _capture(body, parse_provider_response_json(body)),
            provider_name="tushare",
            dataset_key="equity.quote.snapshot",
            api_name="quote",
            request_params={"ts_code": "000001.SZ"},
            run_id="not-a-uuid",
        )

    assert caught.value.code == "PROVIDER_RESPONSE_RUN_ID_INVALID"
    assert repository.rows == {}


def test_retention_redacts_credentials_by_key_and_literal_in_response_and_request() -> None:
    """A secret echoed in an ordinary message field is scrubbed before storage."""

    secret = "credential-value-98765"
    repository = _Repository()
    use_case = RetainProviderResponsePayloadUseCase(repository)
    reference = use_case.execute(
        _capture(
            f'{{"code":0,"message":"upstream echoed {secret}","data":{{}}}}'.encode(),
            {"code": 0, "message": f"upstream echoed {secret}", "data": {}},
        ),
        provider_name="tushare",
        dataset_key="equity.reference",
        api_name="stock_basic",
        request_params={"token": secret, "params": {"ts_code": "000001.SZ"}},
        sensitive_values=(secret,),
    )

    row = repository.get_by_hash(reference.payload_hash)
    assert row is not None
    assert secret not in repr(row.payload)
    assert secret not in repr(row.request_params)
    retained_response = parse_provider_response_json(
        row.payload["retained_response_json"].encode("utf-8")
    )
    assert retained_response["message"] == "upstream echoed [REDACTED]"
    assert reference.original_body_retained is False
    assert reference.retained_content_encoding == "redacted_canonical_json"
    assert row.request_params["token"] == "[REDACTED]"
    assert reference.body_sha256 != reference.retained_content_sha256


def test_unredactable_short_secret_rejects_retention_without_saving_a_row() -> None:
    """Very short explicit secrets fail closed instead of corrupting raw values."""

    repository = _Repository()
    use_case = RetainProviderResponsePayloadUseCase(repository)

    with pytest.raises(ProviderResponsePayloadRetentionError) as caught:
        use_case.execute(
            _capture(b'{"message":"pw echoed"}', {"message": "pw echoed"}),
            provider_name="tushare",
            dataset_key="equity.reference",
            api_name="stock_basic",
            request_params={},
            sensitive_values=("pw",),
        )

    assert caught.value.code == "PROVIDER_RESPONSE_SECRET_CANNOT_BE_REDACTED"
    assert repository.rows == {}


def test_scoped_envelope_avoids_rawpayload_global_hash_collision() -> None:
    """Identical bytes from different datasets remain separately addressable."""

    repository = _Repository()
    use_case = RetainProviderResponsePayloadUseCase(repository)
    capture = _capture(b'{"code":0,"data":{}}', {"code": 0, "data": {}})

    first = use_case.execute(
        capture,
        provider_name="tushare",
        dataset_key="equity.reference.calendar",
        api_name="trade_cal",
        request_params={"exchange": "SSE"},
    )
    second = use_case.execute(
        capture,
        provider_name="tushare",
        dataset_key="equity.reference.security",
        api_name="stock_basic",
        request_params={"exchange": "SSE"},
    )

    assert first.body_sha256 == second.body_sha256
    assert first.payload_hash != second.payload_hash
    assert first.payload_id != second.payload_id
    assert len(repository.rows) == 2


def test_invalid_or_non_success_capture_cannot_be_retained() -> None:
    """A provider error status never yields a successful raw payload reference."""

    repository = _Repository()
    with pytest.raises(ValueError, match="status_code"):
        ProviderResponseCapture(
            body=b'{"code":500}',
            payload={"code": 500},
            body_sha256=sha256(b'{"code":500}').hexdigest(),
            body_size_bytes=len(b'{"code":500}'),
            response_completed_at=NOW,
            status_code=500,
            content_type="application/json",
            transport=ProviderResponseTransport.EGRESS,
        )
    assert repository.rows == {}


def test_capture_rejects_payload_not_derived_from_exact_body_with_typed_scalars() -> None:
    """Python equality cannot make true and one the same evidence value."""

    body = b'{"code":true}'
    with pytest.raises(ValueError, match="body is not bound"):
        _capture(body, {"code": 1})

    with pytest.raises(ValueError, match="body is not bound"):
        _capture(b'{"message":"body"}', {"message": "different"})


def test_capture_rejects_float_adapter_values_for_exact_decimal_body() -> None:
    """Float values cannot replace the strict parser's exact Decimal instances."""

    with pytest.raises(ValueError, match="body is not bound"):
        _capture(b'{"price":0.1}', {"price": 0.1})


@pytest.mark.parametrize(
    "body",
    [
        b'{"code":0,"code":1}',
        b'{"value":NaN}',
        b'{"value":' + b"9" * 300 + b"}",
        b'{"code":0',
    ],
)
def test_capture_rejects_ambiguous_or_oversized_json_bytes(body: bytes) -> None:
    """Ambiguous, invalid, and hostile-number bytes cannot produce a reference."""

    with pytest.raises(ValueError, match="body is not bound to payload"):
        _capture(body, {})


def test_retention_rejects_capture_payload_mutation_after_construction() -> None:
    """A nested mutation after capture construction cannot reuse its body hash."""

    response = {"code": 0, "data": {"fields": ["ts_code"], "items": []}}
    capture = _capture(b'{"code":0,"data":{"fields":["ts_code"],"items":[]}}', response)
    cast(dict[str, object], capture.payload)["code"] = 1
    repository = _Repository()

    with pytest.raises(ProviderResponsePayloadRetentionError) as caught:
        RetainProviderResponsePayloadUseCase(repository).execute(
            capture,
            provider_name="tushare",
            dataset_key="equity.reference",
            api_name="stock_basic",
            request_params={},
        )

    assert caught.value.code == "PROVIDER_RESPONSE_CAPTURE_BODY_MISMATCH"
    assert repository.rows == {}


def test_retained_json_keeps_extreme_decimal_lexemes_without_float_underflow() -> None:
    """Exact body and parsed JSON preserve very small and long decimal values."""

    body = b'{"small":1e-9999,"long":0.123456789012345678901234567890123456789}'
    parsed = parse_provider_response_json(body)
    assert str(parsed["small"]) == "1E-9999"
    assert str(parsed["long"]) == "0.123456789012345678901234567890123456789"
    capture = ProviderResponseCapture(
        body=body,
        payload=parsed,
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=NOW,
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.DIRECT,
    )
    repository = _Repository()
    reference = RetainProviderResponsePayloadUseCase(repository).execute(
        capture,
        provider_name="tushare",
        dataset_key="equity.reference",
        api_name="stock_basic",
        request_params={},
    )
    row = repository.get_by_hash(reference.payload_hash)
    assert row is not None
    assert reference.original_body_retained is True
    assert row.payload["retained_response_json"] == body.decode("utf-8")
    assert reference.verifies(row)


def test_response_payload_port_is_structurally_typed() -> None:
    """The use case depends only on the RawPayload repository port."""

    repository = _Repository()
    port = cast(ProviderResponsePayloadRepositoryPort, repository)
    result = RetainProviderResponsePayloadUseCase(port).execute(
        _capture(b'{"code":0}', {"code": 0}),
        provider_name="tushare",
        dataset_key="equity.reference",
        api_name="stock_basic",
        request_params={},
    )
    assert result.payload_id
