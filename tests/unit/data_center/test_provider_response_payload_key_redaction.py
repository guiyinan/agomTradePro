"""Credential literal redaction for JSON object keys."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
    ProviderResponsePayloadRetentionError,
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
from apps.data_center.domain.raw_landing import RawPayload


class _MemoryRawPayloadRepository:
    """Fake persistence port retaining one exact RawPayload for the test."""

    def __init__(self) -> None:
        self.saved: RawPayload | None = None

    def save(self, payload: RawPayload) -> RawPayload:
        """Return the row supplied by the real retain use case."""

        self.saved = payload
        return payload


def test_known_credential_literal_in_object_key_is_redacted() -> None:
    """Known credentials in a key must not make the full original body retainable."""

    secret = "q7Zx81vP"
    body = ('{"code":0,"message":{"echo-' + secret + '":123},"data":{}}').encode("utf-8")
    capture = ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=datetime(2026, 10, 16, 4, 0, tzinfo=UTC),
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.DIRECT,
    )
    repository = _MemoryRawPayloadRepository()

    reference: ProviderResponsePayloadReference = RetainProviderResponsePayloadUseCase(
        repository
    ).execute(
        capture,
        provider_name="tushare",
        dataset_key="equity.reference",
        api_name="stock_basic",
        request_params={"echo-" + secret: 456},
        sensitive_values=(secret,),
    )

    assert repository.saved is not None
    retained = repository.saved.payload["retained_response_json"]
    assert isinstance(retained, str)
    assert reference.original_body_retained is False
    assert secret not in retained
    assert secret not in repr(repository.saved.request_params)
    assert reference.verifies(repository.saved)

    tampered_payload = dict(repository.saved.payload)
    tampered_payload["retained_response_json"] = retained.replace("[REDACTED]", secret)
    tampered_row = replace(repository.saved, payload=tampered_payload)
    assert reference.verifies(tampered_row) is False


def test_secret_key_redaction_collision_fails_with_stable_retention_error() -> None:
    """Distinct response fields are never silently merged during redaction."""

    secret = "q7Zx81vP"
    body = (
        '{"code":0,"message":{"echo-' + secret + '":123,"echo-[REDACTED]":456},"data":{}}'
    ).encode("utf-8")
    capture = ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=datetime(2026, 10, 16, 4, 0, tzinfo=UTC),
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.DIRECT,
    )
    repository = _MemoryRawPayloadRepository()

    with pytest.raises(ProviderResponsePayloadRetentionError) as caught:
        RetainProviderResponsePayloadUseCase(repository).execute(
            capture,
            provider_name="tushare",
            dataset_key="equity.reference",
            api_name="stock_basic",
            request_params={},
            sensitive_values=(secret,),
        )

    assert caught.value.code == "PROVIDER_RESPONSE_REDACTION_KEY_COLLISION"
    assert repository.saved is None


def test_short_secret_in_object_key_rejects_retention() -> None:
    """Short credential literals in keys fail closed instead of persisting."""

    secret = "pw"
    body = b'{"code":0,"message":{"echo-pw":123},"data":{}}'
    capture = ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=datetime(2026, 10, 16, 4, 0, tzinfo=UTC),
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.DIRECT,
    )
    repository = _MemoryRawPayloadRepository()

    with pytest.raises(ProviderResponsePayloadRetentionError) as caught:
        RetainProviderResponsePayloadUseCase(repository).execute(
            capture,
            provider_name="tushare",
            dataset_key="equity.reference",
            api_name="stock_basic",
            request_params={},
            sensitive_values=(secret,),
        )

    assert caught.value.code == "PROVIDER_RESPONSE_SECRET_CANNOT_BE_REDACTED"
    assert repository.saved is None
