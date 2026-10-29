"""Decode the exact normalized JSON payload retained for native QMT statuses."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import cast

from apps.data_center.domain.qmt_daily_status import (
    BridgeDailyStatusBatch,
    BridgeDailyStatusSample,
    QmtDailyStatusValidationError,
)

_BATCH_FIELDS = frozenset(
    {
        "batch_id",
        "kind",
        "collected_at",
        "request_start",
        "request_end",
        "samples",
        "schema_version",
    }
)
_SAMPLE_FIELDS = frozenset({"asset_code", "bar_date", "suspend_flag"})


def decode_qmt_daily_status_payload(payload: object) -> BridgeDailyStatusBatch:
    """Decode one strictly shaped persisted JSON payload without using wall time."""

    fields = _json_object(payload, "batch")
    _require_exact_fields(fields, _BATCH_FIELDS, "batch")

    batch_id = _text(fields["batch_id"], "batch_id")
    kind = _text(fields["kind"], "kind")
    schema_version = _text(fields["schema_version"], "schema_version")
    collected_at = _datetime(fields["collected_at"], "collected_at")
    request_start = _date(fields["request_start"], "request_start")
    request_end = _date(fields["request_end"], "request_end")

    raw_samples = fields["samples"]
    if type(raw_samples) is not list:
        raise QmtDailyStatusValidationError("daily status samples must be a JSON list")
    samples: list[BridgeDailyStatusSample] = []
    for index, raw_sample in enumerate(raw_samples):
        sample_fields = _json_object(raw_sample, f"samples[{index}]")
        _require_exact_fields(sample_fields, _SAMPLE_FIELDS, f"samples[{index}]")
        asset_code = _text(sample_fields["asset_code"], f"samples[{index}].asset_code")
        bar_date = _date(sample_fields["bar_date"], f"samples[{index}].bar_date")
        raw_flag = sample_fields["suspend_flag"]
        if raw_flag is not None and type(raw_flag) is not int:
            raise QmtDailyStatusValidationError(
                f"daily status samples[{index}].suspend_flag must be an integer or null"
            )
        samples.append(
            BridgeDailyStatusSample(
                asset_code=asset_code,
                bar_date=bar_date,
                suspend_flag=raw_flag,
            )
        )

    batch = BridgeDailyStatusBatch(
        batch_id=batch_id,
        kind=kind,
        collected_at=collected_at,
        request_start=request_start,
        request_end=request_end,
        samples=tuple(samples),
        schema_version=schema_version,
    )
    batch.validate(collected_at)
    if batch.to_payload() != payload:
        raise QmtDailyStatusValidationError("daily status payload is not canonical")
    return batch


def _json_object(value: object, field_name: str) -> Mapping[str, object]:
    """Narrow one concrete JSON object and reject non-string or non-JSON keys."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise QmtDailyStatusValidationError(f"daily status {field_name} must be a JSON object")
    return cast(Mapping[str, object], value)


def _require_exact_fields(
    fields: Mapping[str, object], expected: frozenset[str], field_name: str
) -> None:
    """Reject both missing and unexpected keys at the retained JSON boundary."""

    if frozenset(fields) != expected:
        raise QmtDailyStatusValidationError(
            f"daily status {field_name} fields are missing or unsupported"
        )


def _text(value: object, field_name: str) -> str:
    """Require an exact JSON string without coercing other scalar types."""

    if type(value) is not str:
        raise QmtDailyStatusValidationError(f"daily status {field_name} must be text")
    return value


def _datetime(value: object, field_name: str) -> datetime:
    """Parse one aware ISO clock; canonical UTC spelling is checked after validation."""

    raw_text = _text(value, field_name)
    try:
        return datetime.fromisoformat(raw_text)
    except (OverflowError, TypeError, ValueError) as error:
        raise QmtDailyStatusValidationError(
            f"daily status {field_name} is not a valid ISO datetime"
        ) from error


def _date(value: object, field_name: str) -> date:
    """Parse one ISO calendar date without accepting datetime or numeric coercions."""

    raw_text = _text(value, field_name)
    try:
        return date.fromisoformat(raw_text)
    except (OverflowError, TypeError, ValueError) as error:
        raise QmtDailyStatusValidationError(
            f"daily status {field_name} is not an ISO date"
        ) from error


__all__ = ("decode_qmt_daily_status_payload",)
