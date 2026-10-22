"""Canonical request descriptor codec for source capture checkpoint rows."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import cast
from uuid import UUID

from apps.data_center.domain.instrument_reference_capture import (
    InstrumentReferenceCaptureContractError,
)
from apps.data_center.domain.instrument_reference_source import InstrumentReferenceProviderContract

from .models import SyncCheckpointModel

_REQUEST_PREFIX = "ircap.v1.request."
_REQUEST_NAME = re.compile(r"^ircap\.v1\.request\.([0-9]{6})\.([0-9]{6})$")
_DESCRIPTOR_CHUNK_SIZE = 500
_MAX_DESCRIPTOR_CHUNKS = 256
_MAX_DESCRIPTOR_LENGTH = _DESCRIPTOR_CHUNK_SIZE * _MAX_DESCRIPTOR_CHUNKS


def _request_descriptor_chunks(value: str) -> tuple[tuple[str, str], ...]:
    """Encode ASCII canonical request text into bounded, fixed-index checkpoint rows."""

    if type(value) is not str:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_INVALID"
        )
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_INVALID"
        ) from exc
    if not encoded or len(encoded) > _MAX_DESCRIPTOR_LENGTH:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_TOO_LARGE"
        )
    total = (len(encoded) + _DESCRIPTOR_CHUNK_SIZE - 1) // _DESCRIPTOR_CHUNK_SIZE
    return tuple(
        (
            f"{_REQUEST_PREFIX}{total:06d}.{index:06d}",
            encoded[(index - 1) * _DESCRIPTOR_CHUNK_SIZE : index * _DESCRIPTOR_CHUNK_SIZE].decode(
                "ascii"
            ),
        )
        for index in range(1, total + 1)
    )


def _join_request_descriptor(rows: list[SyncCheckpointModel]) -> str:
    """Require contiguous unique request chunks with exact count, bounds, and ASCII bytes."""

    if not rows or len(rows) > _MAX_DESCRIPTOR_CHUNKS:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
        )
    chunks: dict[int, str] = {}
    expected_total: int | None = None
    for row in rows:
        match = _REQUEST_NAME.fullmatch(row.cursor_name)
        if match is None or type(row.cursor_value) is not str:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
            )
        try:
            total = int(match.group(1))
            index = int(match.group(2))
            encoded = row.cursor_value.encode("ascii")
        except (UnicodeEncodeError, ValueError) as exc:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
            ) from exc
        if (
            total < 1
            or total > _MAX_DESCRIPTOR_CHUNKS
            or index < 1
            or index > total
            or len(encoded) < 1
            or len(encoded) > _DESCRIPTOR_CHUNK_SIZE
            or (expected_total is not None and expected_total != total)
            or index in chunks
            or len(row.cursor_value) != len(encoded)
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
            )
        expected_total = total
        chunks[index] = row.cursor_value
    if expected_total is None or set(chunks) != set(range(1, expected_total + 1)):
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
        )
    descriptor = "".join(chunks[index] for index in range(1, expected_total + 1))
    if len(descriptor.encode("ascii")) > _MAX_DESCRIPTOR_LENGTH:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
        )
    return descriptor


def _parse_canonical_request(value: str) -> dict[str, object]:
    """Parse one canonical descriptor object while rejecting duplicate keys and drift."""

    try:
        parsed: object = json.loads(value, object_pairs_hook=_unique_object)
        encoded = json.dumps(
            parsed,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError) as exc:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_INVALID"
        ) from exc
    if type(parsed) is not dict or encoded != value:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_NONCANONICAL"
        )
    payload = cast(dict[str, object], parsed)
    expected = {
        "schema",
        "capture_id",
        "provider_route_id",
        "provider_route_revision",
        "provider_configuration_id",
        "provider_contract",
        "mapping",
        "scopes",
        "repository_alias",
        "source_only",
        "actor_provenance",
    }
    if (
        payload.keys() != expected
        or payload.get("schema") != "instrument-reference-capture-request.v1"
    ):
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_INVALID"
        )
    return payload


def _provider_contract_from_payload(
    value: Mapping[str, object],
) -> InstrumentReferenceProviderContract:
    """Narrow canonical provider-contract JSON back through its existing Domain validator."""

    expected = {
        "contract_id",
        "contract_version",
        "provider_name",
        "dataset_key",
        "api_name",
        "fields",
        "exchange_scope",
        "list_status_scope",
        "content_hash",
    }
    if value.keys() != expected:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_CONTRACT_INVALID"
        )
    fields = _string_tuple(value, "fields")
    exchanges = _string_tuple(value, "exchange_scope")
    statuses = _string_tuple(value, "list_status_scope")
    contract = InstrumentReferenceProviderContract(
        contract_id=_string_payload(value, "contract_id"),
        contract_version=_string_payload(value, "contract_version"),
        provider_name=_string_payload(value, "provider_name"),
        dataset_key=_string_payload(value, "dataset_key"),
        api_name=_string_payload(value, "api_name"),
        fields=fields,
        exchange_scope=exchanges,
        list_status_scope=statuses,
    )
    if contract.content_hash != _string_payload(value, "content_hash"):
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_CONTRACT_INVALID"
        )
    return contract


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys in persisted request evidence."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate descriptor key")
        result[key] = value
    return result


def _mapping_value(payload: Mapping[str, object], key: str) -> dict[str, object]:
    """Return one exact nested JSON object without coercion."""

    value = payload.get(key)
    if type(value) is not dict or any(
        type(item) is not str for item in cast(dict[object, object], value)
    ):
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_INVALID"
        )
    return cast(dict[str, object], value)


def _string_payload(payload: Mapping[str, object], key: str) -> str:
    """Narrow one exact descriptor text field."""

    value = payload.get(key)
    if type(value) is not str:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_INVALID"
        )
    return value


def _string_tuple(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    """Narrow one canonical descriptor list to an immutable string tuple."""

    value = payload.get(key)
    if type(value) is not list or any(type(item) is not str for item in value):
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_INVALID"
        )
    return tuple(cast(list[str], value))


def _int_payload(payload: Mapping[str, object], key: str) -> int:
    """Return one exact integer descriptor field, excluding JSON booleans."""

    value = payload.get(key)
    if type(value) is not int:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_INVALID"
        )
    return value


def _uuid_payload(payload: Mapping[str, object], key: str) -> UUID:
    """Parse one canonical UUID string from request evidence."""

    value = _string_payload(payload, key)
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_INVALID"
        ) from exc
    if str(parsed) != value:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_INVALID"
        )
    return parsed
