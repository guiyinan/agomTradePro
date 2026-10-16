"""Retain redacted, byte-bound JSON responses from non-financial providers."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, cast
from uuid import NAMESPACE_URL, uuid5

from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    canonical_provider_response_json,
    parse_provider_response_json,
)
from apps.data_center.domain.raw_landing import RawPayload, raw_payload_record_digest
from core.exceptions import DataFetchError

_SCHEMA = "provider-response-payload.v1"
_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_NAMES = frozenset(
    {
        "apikey",
        "apisecret",
        "authorization",
        "clientsecret",
        "cookie",
        "credential",
        "credentials",
        "password",
        "secret",
        "setcookie",
        "token",
        "xapikey",
    }
)


class ProviderResponsePayloadRetentionError(DataFetchError):
    """Raised when a captured response cannot be retained without ambiguity."""

    default_message = "Provider 响应原始载荷无法安全留存。"
    default_code = "PROVIDER_RESPONSE_PAYLOAD_RETENTION_FAILED"


class _ProviderResponseShortSecretMatch(ValueError):
    """Internal marker for a too-short secret found inside ordinary text."""


class _ProviderResponseKeyRedactionCollision(ValueError):
    """Internal marker when replacing a key would silently merge JSON fields."""


@dataclass(frozen=True, slots=True)
class ProviderResponsePayloadReference:
    """Bind one exact response body to its redacted immutable RawPayload row."""

    payload_id: str
    payload_hash: str
    record_digest: str
    body_sha256: str
    retained_content_sha256: str
    original_body_retained: bool
    retained_content_encoding: str
    body_size_bytes: int
    response_completed_at: datetime
    provider_name: str
    dataset_key: str
    transport: ProviderResponseTransport

    def __post_init__(self) -> None:
        """Reject references whose identity or digest fields are malformed."""

        try:
            parsed_id = uuid5(NAMESPACE_URL, self.payload_hash)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("ProviderResponsePayloadReference.payload_hash is invalid") from exc
        if str(parsed_id) != self.payload_id:
            raise ValueError("ProviderResponsePayloadReference.payload_id is invalid")
        for name in ("payload_hash", "record_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                raise ValueError(f"ProviderResponsePayloadReference.{name} is invalid")
        for name in ("body_sha256", "retained_content_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(f"ProviderResponsePayloadReference.{name} is invalid")
        if type(self.original_body_retained) is not bool:
            raise ValueError("ProviderResponsePayloadReference.original_body_retained is invalid")
        expected_encoding = (
            "exact_original_utf8_json" if self.original_body_retained else "redacted_canonical_json"
        )
        if self.retained_content_encoding != expected_encoding:
            raise ValueError(
                "ProviderResponsePayloadReference.retained_content_encoding is invalid"
            )
        if (
            isinstance(self.body_size_bytes, bool)
            or not isinstance(self.body_size_bytes, int)
            or self.body_size_bytes < 0
        ):
            raise ValueError("ProviderResponsePayloadReference.body_size_bytes is invalid")
        _require_aware_utc(self.response_completed_at)
        _require_text(self.provider_name, "provider_name", 100)
        _require_text(self.dataset_key, "dataset_key", 160)
        if not isinstance(self.transport, ProviderResponseTransport):
            raise ValueError("ProviderResponsePayloadReference.transport is invalid")

    def to_payload(self) -> dict[str, object]:
        """Return an immutable safe reference without the response contents."""

        return {
            "payload_id": self.payload_id,
            "payload_hash": self.payload_hash,
            "record_digest": self.record_digest,
            "body_sha256": self.body_sha256,
            "retained_content_sha256": self.retained_content_sha256,
            "original_body_retained": self.original_body_retained,
            "retained_content_encoding": self.retained_content_encoding,
            "body_size_bytes": self.body_size_bytes,
            "response_completed_at": self.response_completed_at.isoformat(),
            "provider_name": self.provider_name,
            "dataset_key": self.dataset_key,
            "transport": self.transport.value,
            "time_semantics": "local_response_body_completion",
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, object]) -> ProviderResponsePayloadReference:
        """Rebuild a reference from its exact serialized public representation."""

        expected = {
            "payload_id",
            "payload_hash",
            "record_digest",
            "body_sha256",
            "retained_content_sha256",
            "original_body_retained",
            "retained_content_encoding",
            "body_size_bytes",
            "response_completed_at",
            "provider_name",
            "dataset_key",
            "transport",
            "time_semantics",
        }
        if set(value) != expected or value.get("time_semantics") != (
            "local_response_body_completion"
        ):
            raise ValueError("Provider response reference payload has invalid fields")
        try:
            return cls(
                payload_id=_payload_text(value, "payload_id"),
                payload_hash=_payload_text(value, "payload_hash"),
                record_digest=_payload_text(value, "record_digest"),
                body_sha256=_payload_text(value, "body_sha256"),
                retained_content_sha256=_payload_text(value, "retained_content_sha256"),
                original_body_retained=_payload_bool(value, "original_body_retained"),
                retained_content_encoding=_payload_text(value, "retained_content_encoding"),
                body_size_bytes=_payload_int(value, "body_size_bytes"),
                response_completed_at=datetime.fromisoformat(
                    _payload_text(value, "response_completed_at")
                ),
                provider_name=_payload_text(value, "provider_name"),
                dataset_key=_payload_text(value, "dataset_key"),
                transport=ProviderResponseTransport(_payload_text(value, "transport")),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Provider response reference payload is invalid") from exc

    def verifies(self, row: RawPayload) -> bool:
        """Revalidate a reference against its immutable redacted RawPayload row.

        The original bytes are represented by their exact digest because this
        JSON landing stores only redacted parsed content. This checks that the
        original-body digest remains bound to the record and independently
        recomputes retained-content, schema, payload, and record digests.
        """

        if not isinstance(row, RawPayload):
            return False
        payload = row.payload
        request_params = row.request_params
        if not isinstance(payload, dict) or not isinstance(request_params, dict):
            return False
        retained_response_json = payload.get("retained_response_json")
        if not isinstance(retained_response_json, str):
            return False
        try:
            retained_content_sha256 = hashlib.sha256(
                retained_response_json.encode("utf-8")
            ).hexdigest()
            if self.original_body_retained:
                retained_body_matches = retained_content_sha256 == self.body_sha256
            else:
                parsed_retained = parse_provider_response_json(
                    retained_response_json.encode("utf-8")
                )
                retained_body_matches = (
                    canonical_provider_response_json(parsed_retained) == retained_response_json
                )
            return (
                row.payload_id == self.payload_id
                and row.payload_hash == self.payload_hash
                and row.provider_name == self.provider_name
                and row.dataset_key == self.dataset_key
                and row.fetched_at == self.response_completed_at
                and row.payload_size_bytes == self.body_size_bytes
                and payload.get("schema") == _SCHEMA
                and payload.get("provider_name") == self.provider_name
                and payload.get("dataset_key") == self.dataset_key
                and payload.get("transport") == self.transport.value
                and payload.get("response_completed_at") == self.response_completed_at.isoformat()
                and payload.get("response_body_sha256") == self.body_sha256
                and payload.get("response_body_size_bytes") == self.body_size_bytes
                and payload.get("retained_content_sha256") == self.retained_content_sha256
                and payload.get("original_body_retained") is self.original_body_retained
                and payload.get("retained_content_encoding") == self.retained_content_encoding
                and payload.get("request_params_sha256") == _canonical_sha256(request_params)
                and retained_content_sha256 == self.retained_content_sha256
                and retained_body_matches
                and f"sha256:{_canonical_sha256(payload)}" == self.payload_hash
                and f"sha256:{_canonical_sha256(_schema_shape(payload))}" == row.schema_fingerprint
                and raw_payload_record_digest(row) == self.record_digest
            )
        except (TypeError, ValueError):
            return False


class ProviderResponsePayloadRepositoryPort(Protocol):
    """Persistence port for immutable redacted RawPayload records."""

    def save(self, payload: RawPayload) -> RawPayload:
        """Persist one payload or return an exactly identical replay."""
        ...


class RetainProviderResponsePayloadUseCase:
    """Persist captured JSON after credential redaction and content binding."""

    def __init__(self, repository: ProviderResponsePayloadRepositoryPort) -> None:
        """Create the use case with an explicitly composed raw-payload store."""

        self._repository = repository

    def execute(
        self,
        capture: ProviderResponseCapture,
        *,
        provider_name: str,
        dataset_key: str,
        api_name: str,
        request_params: Mapping[str, object],
        sensitive_values: tuple[str, ...] = (),
    ) -> ProviderResponsePayloadReference:
        """Persist one successful response and return its verifiable reference.

        ``body_sha256`` covers the original transport bytes. The original UTF-8
        JSON text is retained only when no configured credential redaction is
        needed; otherwise a redacted canonical JSON text is kept and explicitly
        marked as not being the original body. Its digest, RawPayload payload
        hash, and complete record digest are independent.
        ``response_completed_at`` is the local body-acquisition time, not an
        upstream source timestamp.
        """

        if not isinstance(capture, ProviderResponseCapture):
            raise ProviderResponsePayloadRetentionError(
                "响应捕获对象无效。", code="PROVIDER_RESPONSE_CAPTURE_INVALID"
            )
        if not capture.payload_matches_body():
            raise ProviderResponsePayloadRetentionError(
                "响应 JSON 已与原始响应字节不一致。",
                code="PROVIDER_RESPONSE_CAPTURE_BODY_MISMATCH",
            )
        _require_text(provider_name, "provider_name", 100)
        _require_text(dataset_key, "dataset_key", 160)
        _require_text(api_name, "api_name", 128)
        if not isinstance(request_params, Mapping):
            raise ProviderResponsePayloadRetentionError(
                "请求范围无效。", code="PROVIDER_RESPONSE_REQUEST_SCOPE_INVALID"
            )

        try:
            secret_literals = _secret_literals(request_params, sensitive_values)
            source_response = capture.payload_from_body()
            if not isinstance(source_response, dict):
                raise ValueError("provider response must be a JSON object")
            safe_response = _redact_json(source_response, secret_literals)
            safe_request = _redact_json(request_params, secret_literals)
            if not isinstance(safe_response, dict) or not isinstance(safe_request, dict):
                raise ValueError("provider response and request must be JSON objects")
            original_body_retained = not _requires_redaction(source_response, secret_literals)
            if original_body_retained:
                retained_response_json = capture.body.decode("utf-8")
                retained_content_encoding = "exact_original_utf8_json"
            else:
                retained_response_json = canonical_provider_response_json(safe_response)
                retained_content_encoding = "redacted_canonical_json"
            content_digest = hashlib.sha256(retained_response_json.encode("utf-8")).hexdigest()
            request_digest = _canonical_sha256(safe_request)
            content_type = _safe_content_type(capture.content_type, secret_literals)
            payload = _raw_payload_envelope(
                capture,
                provider_name=provider_name,
                dataset_key=dataset_key,
                api_name=api_name,
                retained_response_json=retained_response_json,
                original_body_retained=original_body_retained,
                retained_content_encoding=retained_content_encoding,
                content_type=content_type,
                request_params_sha256=request_digest,
                retained_content_sha256=content_digest,
            )
            payload_hash = f"sha256:{_canonical_sha256(payload)}"
            schema_fingerprint = f"sha256:{_canonical_sha256(_schema_shape(payload))}"
            raw_payload = RawPayload(
                payload_id=str(uuid5(NAMESPACE_URL, payload_hash)),
                dataset_key=dataset_key,
                provider_name=provider_name,
                payload_hash=payload_hash,
                schema_fingerprint=schema_fingerprint,
                payload=cast(dict[str, Any], payload),
                fetched_at=capture.response_completed_at,
                request_params=cast(dict[str, Any], safe_request),
                content_type=content_type,
                parser_version=_SCHEMA,
                redacted=True,
                payload_size_bytes=capture.body_size_bytes,
            )
        except ProviderResponsePayloadRetentionError:
            raise
        except _ProviderResponseShortSecretMatch as exc:
            raise ProviderResponsePayloadRetentionError(
                "响应内容包含无法安全替换的短凭据。",
                code="PROVIDER_RESPONSE_SECRET_CANNOT_BE_REDACTED",
            ) from exc
        except _ProviderResponseKeyRedactionCollision as exc:
            raise ProviderResponsePayloadRetentionError(
                "响应键脱敏会合并不同字段。",
                code="PROVIDER_RESPONSE_REDACTION_KEY_COLLISION",
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ProviderResponsePayloadRetentionError(
                "响应内容无法在脱敏后安全留存。",
                code="PROVIDER_RESPONSE_PAYLOAD_INVALID",
            ) from exc

        try:
            stored = self._repository.save(raw_payload)
        except Exception as exc:
            raise ProviderResponsePayloadRetentionError(
                "RawPayload 写入失败。", code="PROVIDER_RESPONSE_PAYLOAD_SAVE_FAILED"
            ) from exc
        if stored != raw_payload:
            raise ProviderResponsePayloadRetentionError(
                "RawPayload 返回值与捕获内容不一致。",
                code="PROVIDER_RESPONSE_PAYLOAD_IMMUTABLE_CONFLICT",
            )
        return ProviderResponsePayloadReference(
            payload_id=stored.payload_id,
            payload_hash=stored.payload_hash,
            record_digest=raw_payload_record_digest(stored),
            body_sha256=capture.body_sha256,
            retained_content_sha256=content_digest,
            original_body_retained=original_body_retained,
            retained_content_encoding=retained_content_encoding,
            body_size_bytes=capture.body_size_bytes,
            response_completed_at=capture.response_completed_at,
            provider_name=provider_name,
            dataset_key=dataset_key,
            transport=capture.transport,
        )


def _raw_payload_envelope(
    capture: ProviderResponseCapture,
    *,
    provider_name: str,
    dataset_key: str,
    api_name: str,
    retained_response_json: str,
    original_body_retained: bool,
    retained_content_encoding: str,
    content_type: str,
    request_params_sha256: str,
    retained_content_sha256: str,
) -> dict[str, object]:
    """Build the exact allowlisted redacted payload envelope."""

    return {
        "schema": _SCHEMA,
        "provider_name": provider_name,
        "dataset_key": dataset_key,
        "api_name": api_name,
        "transport": capture.transport.value,
        "status_code": capture.status_code,
        "content_type": content_type or None,
        "response_completed_at": capture.response_completed_at.isoformat(),
        "response_body_sha256": capture.body_sha256,
        "response_body_size_bytes": capture.body_size_bytes,
        "request_params_sha256": request_params_sha256,
        "retained_content_sha256": retained_content_sha256,
        "original_body_retained": original_body_retained,
        "retained_content_encoding": retained_content_encoding,
        "retained_response_json": retained_response_json,
    }


def _secret_literals(
    request_params: Mapping[str, object], sensitive_values: tuple[str, ...]
) -> tuple[str, ...]:
    """Collect explicit secrets and values found under credential-like keys."""

    values = {value for value in sensitive_values if isinstance(value, str) and value}

    def visit(value: object) -> None:
        """Collect credential values nested under credential-like request keys."""

        if isinstance(value, Mapping):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("provider response JSON keys must be strings")
                if _is_sensitive_key(key) and isinstance(item, str) and item:
                    values.add(item)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(request_params)
    return tuple(sorted(values, key=lambda item: (-len(item), item)))


def _redact_json(value: object, secrets: tuple[str, ...]) -> object:
    """Copy JSON data while hiding secret keys and explicit secret literals."""

    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("provider response JSON keys must be strings")
            redacted_key = _redact_text(key, secrets)
            if redacted_key in redacted:
                raise _ProviderResponseKeyRedactionCollision(
                    "provider response key redaction caused a collision"
                )
            redacted[redacted_key] = (
                _REDACTED if _is_sensitive_key(key) else _redact_json(item, secrets)
            )
        return redacted
    if isinstance(value, list):
        return [_redact_json(item, secrets) for item in value]
    if isinstance(value, str):
        return _redact_text(value, secrets)
    if value is None or type(value) in {bool, int}:
        return value
    if isinstance(value, Decimal) and value.is_finite():
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("provider response contains a non-JSON value")


def _requires_redaction(value: object, secrets: tuple[str, ...]) -> bool:
    """Return whether retaining the original response text would expose a secret."""

    if isinstance(value, Mapping):
        return any(
            _is_sensitive_key(key)
            or _redact_text(key, secrets) != key
            or _requires_redaction(item, secrets)
            for key, item in value.items()
            if isinstance(key, str)
        )
    if isinstance(value, list):
        return any(_requires_redaction(item, secrets) for item in value)
    if isinstance(value, str):
        return any(secret in value for secret in secrets)
    return False


def _redact_text(value: str, secrets: tuple[str, ...]) -> str:
    """Replace known secrets embedded in ordinary text fields."""

    redacted = value
    for secret in secrets:
        if secret in redacted:
            if len(secret) < 3:
                raise _ProviderResponseShortSecretMatch
            redacted = redacted.replace(secret, _REDACTED)
    return redacted


def _safe_content_type(value: str | None, secrets: tuple[str, ...]) -> str:
    """Keep only a bounded media type, omitting unsafe parameters or secrets."""

    if value is None:
        return ""
    media_type = value.split(";", 1)[0].strip().lower()
    if not media_type or len(media_type) > 80:
        return ""
    return _redact_text(media_type, secrets)


def _is_sensitive_key(value: str) -> bool:
    """Return whether a JSON key names a credential or session secret."""

    normalized = "".join(character for character in value.casefold() if character.isalnum())
    return normalized in _SENSITIVE_KEY_NAMES or any(
        marker in normalized
        for marker in (
            "apikey",
            "authorization",
            "cookie",
            "credential",
            "password",
            "secret",
            "token",
        )
    )


def _canonical_sha256(value: object) -> str:
    """Hash one canonical JSON value with strict finite-number handling."""

    encoded = canonical_provider_response_json(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _schema_shape(value: object) -> object:
    """Describe JSON key/type shape without retaining provider values."""

    if isinstance(value, Mapping):
        return {
            "object": {
                key: _schema_shape(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
                if isinstance(key, str)
            }
        }
    if isinstance(value, list):
        if not value:
            return {"array": "empty"}
        return {"array": sorted({_canonical_json_text(_schema_shape(item)) for item in value})}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _canonical_json_text(value: object) -> str:
    """Serialize a schema fragment for deterministic heterogeneous-array shape."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _require_text(value: object, field_name: str, maximum: int) -> None:
    """Validate bounded identifiers without silently normalizing them."""

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise ProviderResponsePayloadRetentionError(
            f"{field_name} 无效。", code="PROVIDER_RESPONSE_REQUEST_SCOPE_INVALID"
        )


def _require_aware_utc(value: datetime) -> None:
    """Require a UTC-aware acquisition time."""

    offset = value.utcoffset() if value.tzinfo is not None else None
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("response_completed_at must be UTC-aware")


def _payload_text(value: Mapping[str, object], key: str) -> str:
    """Read one required string from a serialized reference."""

    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"Provider response reference {key} is invalid")
    return item


def _payload_int(value: Mapping[str, object], key: str) -> int:
    """Read one required exact integer from a serialized reference."""

    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"Provider response reference {key} is invalid")
    return item


def _payload_bool(value: Mapping[str, object], key: str) -> bool:
    """Read one required exact boolean from a serialized reference."""

    item = value.get(key)
    if type(item) is not bool:
        raise ValueError(f"Provider response reference {key} is invalid")
    return item


__all__ = [
    "ProviderResponsePayloadReference",
    "ProviderResponsePayloadRepositoryPort",
    "ProviderResponsePayloadRetentionError",
    "RetainProviderResponsePayloadUseCase",
]
