"""Private checkpoint receipts for capture progress and fenced completion."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from apps.data_center.domain.instrument_reference_capture import (
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureRequest,
    InstrumentReferenceCaptureScope,
)

_CHECKPOINT_PREFIX = "ircap.v1."
_SCOPE_PREFIX = "ircap.v1.scope."
_COMPLETION_CURSOR_NAME = "ircap.v1.complete"
_COMPLETION_SCHEMA = "instrument-reference-capture-completion.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECORD_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_VALUE_BYTES = 500


@dataclass(frozen=True, slots=True)
class CaptureCompletionMarker:
    """Seal one source snapshot to the exact request and latest claim epoch."""

    request_sha256: str
    epoch: int
    claim_sha256: str
    snapshot_id: UUID
    snapshot_content_hash: str
    snapshot_record_digest: str

    def __post_init__(self) -> None:
        """Reject malformed request, claim, snapshot, or digest identity."""

        if (
            type(self.request_sha256) is not str
            or _SHA256.fullmatch(self.request_sha256) is None
            or type(self.epoch) is not int
            or self.epoch < 1
            or type(self.claim_sha256) is not str
            or _SHA256.fullmatch(self.claim_sha256) is None
            or type(self.snapshot_id) is not UUID
            or type(self.snapshot_content_hash) is not str
            or _RECORD_DIGEST.fullmatch(self.snapshot_content_hash) is None
            or type(self.snapshot_record_digest) is not str
            or _RECORD_DIGEST.fullmatch(self.snapshot_record_digest) is None
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_INVALID"
            )

    def encode(self) -> str:
        """Return canonical bounded JSON for the existing checkpoint column."""

        value = json.dumps(
            {
                "schema": _COMPLETION_SCHEMA,
                "request_sha256": self.request_sha256,
                "epoch": self.epoch,
                "claim_sha256": self.claim_sha256,
                "snapshot_id": str(self.snapshot_id),
                "snapshot_content_hash": self.snapshot_content_hash,
                "snapshot_record_digest": self.snapshot_record_digest,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(value.encode("ascii")) > _MAX_VALUE_BYTES:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_TOO_LONG"
            )
        return value

    @classmethod
    def decode(cls, value: object) -> CaptureCompletionMarker:
        """Decode one exact canonical marker without accepting extra fields."""

        if type(value) is not str:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_INVALID"
            )
        try:
            if len(value.encode("ascii")) > _MAX_VALUE_BYTES:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_INVALID"
                )
            parsed_value: object = json.loads(value, object_pairs_hook=_unique_object)
        except (
            UnicodeEncodeError,
            json.JSONDecodeError,
            RecursionError,
            TypeError,
            ValueError,
        ) as exc:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_INVALID"
            ) from exc
        if type(parsed_value) is not dict:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_INVALID"
            )
        parsed = cast(dict[str, object], parsed_value)
        if (
            set(parsed)
            != {
                "schema",
                "request_sha256",
                "epoch",
                "claim_sha256",
                "snapshot_id",
                "snapshot_content_hash",
                "snapshot_record_digest",
            }
            or parsed.get("schema") != _COMPLETION_SCHEMA
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_INVALID"
            )
        snapshot_value = parsed.get("snapshot_id")
        if type(snapshot_value) is not str:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_INVALID"
            )
        try:
            snapshot_id = UUID(snapshot_value)
        except ValueError as exc:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_INVALID"
            ) from exc
        if str(snapshot_id) != snapshot_value:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_INVALID"
            )
        marker = cls(
            request_sha256=_text(parsed, "request_sha256"),
            epoch=_integer(parsed, "epoch"),
            claim_sha256=_text(parsed, "claim_sha256"),
            snapshot_id=snapshot_id,
            snapshot_content_hash=_text(parsed, "snapshot_content_hash"),
            snapshot_record_digest=_text(parsed, "snapshot_record_digest"),
        )
        if marker.encode() != value:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_NONCANONICAL"
            )
        return marker


def scope_checkpoint_name(
    scope: InstrumentReferenceCaptureScope,
    phase: str,
) -> str:
    """Return an exact reserved checkpoint name for one scope and stage."""

    if (
        type(scope) is not InstrumentReferenceCaptureScope
        or type(phase) is not str
        or phase not in {"response", "audit"}
    ):
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_CHECKPOINT_INVALID"
        )
    scope_value = json.dumps(
        {"exchange": scope.exchange, "list_status": scope.list_status},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    scope_hash = hashlib.sha256(scope_value.encode("ascii")).hexdigest()
    return f"{_SCOPE_PREFIX}{scope_hash}.{phase}"


def validate_progress_checkpoints(
    request: InstrumentReferenceCaptureRequest,
    rows: Sequence[tuple[object, object]],
) -> dict[tuple[InstrumentReferenceCaptureScope, str], str]:
    """Validate response and audit pointers against only requested scopes."""

    scope_by_name = {
        scope_checkpoint_name(scope, phase): (scope, phase)
        for scope in request.scopes
        for phase in ("response", "audit")
    }
    result: dict[tuple[InstrumentReferenceCaptureScope, str], str] = {}
    for raw_name, raw_value in rows:
        if type(raw_name) is not str or type(raw_value) is not str:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
            )
        identity = scope_by_name.get(raw_name)
        if identity is None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
            )
        scope, phase = identity
        if phase == "response":
            try:
                parsed_id = UUID(raw_value)
            except ValueError as exc:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
                ) from exc
            if str(parsed_id) != raw_value:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
                )
        elif not raw_value.isascii() or not raw_value.isdecimal() or raw_value.startswith("0"):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
            )
        key = (scope, phase)
        if key in result:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_DUPLICATE"
            )
        result[key] = raw_value
    if any(
        (scope, "audit") in result and (scope, "response") not in result for scope in request.scopes
    ):
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
        )
    return result


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys in the completion receipt."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("capture_completion_marker_duplicate_key")
        result[key] = value
    return result


def _text(value: dict[str, object], key: str) -> str:
    """Read one exact JSON text field."""

    result = value.get(key)
    if type(result) is not str:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_INVALID"
        )
    return result


def _integer(value: dict[str, object], key: str) -> int:
    """Read one exact integer field, excluding boolean values."""

    result = value.get(key)
    if type(result) is not int:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_INVALID"
        )
    return result


__all__ = [
    "CaptureCompletionMarker",
    "_COMPLETION_CURSOR_NAME",
    "scope_checkpoint_name",
    "validate_progress_checkpoints",
]
