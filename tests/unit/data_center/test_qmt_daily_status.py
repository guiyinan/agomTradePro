"""Pure validation and serialization tests for native QMT daily status."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest

from apps.data_center.domain.qmt_daily_status import (
    BridgeDailyStatusBatch,
    BridgeDailyStatusSample,
    QmtDailyStatusState,
    QmtDailyStatusValidationError,
)

_BATCH_ID = "4f1db65f-7517-46b8-8244-20951e384f73"
_COLLECTED_AT = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)
_NOW = _COLLECTED_AT + timedelta(seconds=1)
_START = date(2026, 10, 1)
_END = date(2026, 10, 19)


def _sample(
    asset_code: str = "600000.SH",
    bar_date: date = _END,
    suspend_flag: int | None = 0,
) -> BridgeDailyStatusSample:
    """Build one explicit source status row."""

    return BridgeDailyStatusSample(
        asset_code=asset_code,
        bar_date=bar_date,
        suspend_flag=suspend_flag,
    )


def _batch(
    samples: tuple[BridgeDailyStatusSample, ...] | None = None,
    **changes: object,
) -> BridgeDailyStatusBatch:
    """Build one request-scoped native status batch."""

    values: dict[str, object] = {
        "batch_id": _BATCH_ID,
        "kind": "daily_status",
        "collected_at": _COLLECTED_AT,
        "request_start": _START,
        "request_end": _END,
        "samples": (_sample(),) if samples is None else samples,
        "schema_version": "qmt-native-daily-status.v1",
    }
    values.update(changes)
    return BridgeDailyStatusBatch(
        batch_id=cast(str, values["batch_id"]),
        kind=cast(str, values["kind"]),
        collected_at=cast(datetime, values["collected_at"]),
        request_start=cast(date, values["request_start"]),
        request_end=cast(date, values["request_end"]),
        samples=cast(tuple[BridgeDailyStatusSample, ...], values["samples"]),
        schema_version=cast(str, values["schema_version"]),
    )


def test_valid_batch_has_exact_native_payload_and_stable_content_hash() -> None:
    batch = _batch(samples=(_sample("600000.SH", _END, 0), _sample("000001.SZ", _END, 1)))

    batch.validate(_NOW)
    payload = batch.to_payload()
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert set(payload) == {
        "batch_id",
        "kind",
        "collected_at",
        "request_start",
        "request_end",
        "samples",
        "schema_version",
    }
    assert payload["batch_id"] == str(UUID(_BATCH_ID))
    assert payload["kind"] == "daily_status"
    assert payload["collected_at"] == "2026-10-20T01:00:00+00:00"
    assert payload["request_start"] == "2026-10-01"
    assert payload["request_end"] == "2026-10-19"
    samples = payload["samples"]
    assert type(samples) is list and len(samples) == 2
    assert all(set(sample) == {"asset_code", "bar_date", "suspend_flag"} for sample in samples)
    assert batch.content_hash == hashlib.sha256(canonical).hexdigest()
    assert batch.content_hash == _batch(samples=batch.samples).content_hash


@pytest.mark.parametrize(
    ("flag", "expected"),
    (
        (0, QmtDailyStatusState.NORMAL),
        (1, QmtDailyStatusState.SUSPENDED),
        (-1, QmtDailyStatusState.RESUMED),
        (None, QmtDailyStatusState.UNKNOWN),
    ),
)
def test_native_suspend_flag_maps_without_defaulting_unknown(
    flag: int | None, expected: QmtDailyStatusState
) -> None:
    sample = _sample(suspend_flag=flag)

    sample.validate()

    assert sample.state is expected
    if flag is None:
        assert sample.state is QmtDailyStatusState.UNKNOWN


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("asset_code", ""),
        ("asset_code", " 600000.SH"),
        ("asset_code", "600000.SH "),
        ("asset_code", "X" * 21),
        ("asset_code", 600000),
        ("bar_date", datetime(2026, 10, 19, tzinfo=UTC)),
        ("bar_date", "2026-10-19"),
        ("suspend_flag", True),
        ("suspend_flag", False),
        ("suspend_flag", -2),
        ("suspend_flag", 2),
        ("suspend_flag", "0"),
    ),
)
def test_sample_rejects_wrong_types_unknown_codes_and_noncanonical_assets(
    field_name: str, value: object
) -> None:
    sample = replace(_sample(), **{field_name: value})

    with pytest.raises(QmtDailyStatusValidationError):
        sample.validate()


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("batch_id", "not-a-uuid"),
        ("batch_id", _BATCH_ID.upper()),
        ("batch_id", 1),
        ("kind", "bar"),
        ("kind", "daily-status"),
        ("kind", None),
        ("schema_version", "qmt-native-daily-status.v2"),
        ("schema_version", None),
        ("collected_at", datetime(2026, 10, 20, 1, 0)),
        ("collected_at", "2026-10-20T01:00:00Z"),
        ("request_start", datetime(2026, 10, 1, tzinfo=UTC)),
        ("request_end", datetime(2026, 10, 19, tzinfo=UTC)),
        ("request_start", date(2026, 10, 20)),
        ("request_end", _START),
        ("request_end", date(2026, 10, 20)),
        ("samples", []),
        ("samples", (_sample(), _sample())),
        ("samples", (object(),)),
    ),
)
def test_batch_rejects_invalid_identity_scope_and_shape(field_name: str, value: object) -> None:
    batch = _batch(**{field_name: value})

    with pytest.raises(QmtDailyStatusValidationError):
        batch.validate(_NOW)


def test_batch_rejects_wrong_schema_kind_span_and_china_local_future_date() -> None:
    with pytest.raises(QmtDailyStatusValidationError):
        _batch(kind="daily_status", schema_version="other.v1").validate(_NOW)
    with pytest.raises(QmtDailyStatusValidationError):
        _batch(request_start=date(2026, 8, 1), request_end=_END).validate(_NOW)
    with pytest.raises(QmtDailyStatusValidationError):
        _batch(request_end=date(2026, 10, 20)).validate(_NOW)


def test_request_span_and_sample_count_accept_exact_inclusive_limits() -> None:
    thirty_one_days = _batch(request_start=date(2026, 9, 18), request_end=_END)
    maximum_samples = tuple(_sample(f"QMT-{index:04d}") for index in range(500))
    five_hundred_samples = _batch(samples=maximum_samples)

    thirty_one_days.validate(_NOW)
    five_hundred_samples.validate(_NOW)


def test_request_span_and_sample_count_reject_one_over_each_limit() -> None:
    thirty_two_days = _batch(request_start=date(2026, 9, 17), request_end=_END)
    five_hundred_one_samples = tuple(_sample(f"QMT-{index:04d}") for index in range(501))
    oversized_batch = _batch(samples=five_hundred_one_samples)

    with pytest.raises(QmtDailyStatusValidationError):
        thirty_two_days.validate(_NOW)
    with pytest.raises(QmtDailyStatusValidationError):
        oversized_batch.validate(_NOW)


def test_batch_rejects_naive_or_future_validation_clock() -> None:
    batch = _batch()

    with pytest.raises(QmtDailyStatusValidationError):
        batch.validate(datetime(2026, 10, 20, 1, 1))
    with pytest.raises(QmtDailyStatusValidationError):
        batch.validate(_COLLECTED_AT - timedelta(microseconds=1))


def test_batch_rejects_duplicate_asset_and_date_and_dates_outside_declared_range() -> None:
    duplicate = _batch(samples=(_sample(), _sample()))
    out_of_range = _batch(samples=(_sample(bar_date=date(2026, 9, 30)),))

    with pytest.raises(QmtDailyStatusValidationError):
        duplicate.validate(_NOW)
    with pytest.raises(QmtDailyStatusValidationError):
        out_of_range.validate(_NOW)


def test_to_payload_revalidates_without_replacing_historical_collection_clock() -> None:
    historical = _batch(
        collected_at=datetime(2020, 1, 2, 1, 0, tzinfo=UTC),
        request_start=date(2019, 12, 1),
        request_end=date(2020, 1, 1),
        samples=(_sample(bar_date=date(2020, 1, 1)),),
    )

    payload = historical.to_payload()

    assert payload["collected_at"] == "2020-01-02T01:00:00+00:00"
    assert payload["request_start"] == "2019-12-01"
    assert payload["request_end"] == "2020-01-01"


def test_payload_includes_unknown_state_as_null_native_flag() -> None:
    batch = _batch(samples=(_sample(suspend_flag=None),))

    payload = batch.to_payload()

    samples = payload["samples"]
    assert type(samples) is list
    sample = samples[0]
    assert sample["suspend_flag"] is None
    assert BridgeDailyStatusSample("600000.SH", _END, None).state is QmtDailyStatusState.UNKNOWN


@pytest.mark.parametrize("operation", ("validate", "to_payload", "content_hash"))
def test_china_timezone_overflow_is_a_domain_validation_error(operation: str) -> None:
    """Extreme persisted clocks fail through the stable Domain error boundary."""

    collected_at = datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)
    batch = _batch(
        collected_at=collected_at,
        request_start=date(9999, 12, 1),
        request_end=date(9999, 12, 30),
        samples=(_sample(bar_date=date(9999, 12, 30)),),
    )

    with pytest.raises(QmtDailyStatusValidationError):
        if operation == "validate":
            batch.validate(collected_at)
        elif operation == "to_payload":
            batch.to_payload()
        else:
            _ = batch.content_hash
