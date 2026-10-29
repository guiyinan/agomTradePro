from __future__ import annotations

from collections import UserDict
from datetime import UTC, date, datetime
from typing import cast

import pytest

from apps.data_center.domain.qmt_daily_status import (
    BridgeDailyStatusBatch,
    BridgeDailyStatusSample,
    QmtDailyStatusState,
    QmtDailyStatusValidationError,
)
from apps.data_center.infrastructure.qmt_daily_status_codec import (
    decode_qmt_daily_status_payload,
)

_COLLECTED_AT = "2099-10-29T08:00:00+00:00"
_VALID_PAYLOAD: dict[str, object] = {
    "batch_id": "123e4567-e89b-12d3-a456-426614174000",
    "kind": "daily_status",
    "collected_at": _COLLECTED_AT,
    "request_start": "2099-10-26",
    "request_end": "2099-10-28",
    "samples": [
        {"asset_code": "510300.SH", "bar_date": "2099-10-26", "suspend_flag": 0},
        {"asset_code": "600000.SH", "bar_date": "2099-10-27", "suspend_flag": 1},
        {"asset_code": "000001.SZ", "bar_date": "2099-10-28", "suspend_flag": -1},
        {"asset_code": "000002.SZ", "bar_date": "2099-10-28", "suspend_flag": None},
    ],
    "schema_version": "qmt-native-daily-status.v1",
}


def _payload_copy() -> dict[str, object]:
    """Return a mutable nested copy of the canonical fixture."""

    return {
        **_VALID_PAYLOAD,
        "samples": [
            dict(sample) for sample in cast(list[dict[str, object]], _VALID_PAYLOAD["samples"])
        ],
    }


def test_daily_status_decoder_round_trips_every_native_state_and_fixed_hash() -> None:
    batch = decode_qmt_daily_status_payload(_VALID_PAYLOAD)

    assert type(batch) is BridgeDailyStatusBatch
    assert batch.to_payload() == _VALID_PAYLOAD
    assert [sample.state for sample in batch.samples] == [
        QmtDailyStatusState.NORMAL,
        QmtDailyStatusState.SUSPENDED,
        QmtDailyStatusState.RESUMED,
        QmtDailyStatusState.UNKNOWN,
    ]
    assert batch.content_hash == "4fcd8369ea73661883ba856831321ee5cfe19c80b16ae4e54f2bf37c33d4ca5a"


def test_daily_status_decoder_does_not_rewrite_recorded_clock_or_use_wall_clock() -> None:
    payload = _payload_copy()
    payload["collected_at"] = "2099-10-29T08:00:00+00:00"

    batch = decode_qmt_daily_status_payload(payload)

    assert batch.collected_at == datetime(2099, 10, 29, 8, tzinfo=UTC)
    assert batch.to_payload()["collected_at"] == payload["collected_at"]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_batch_field",
        "extra_batch_field",
        "wrong_kind",
        "unsupported_schema",
        "bad_uuid",
        "noncanonical_uuid",
        "naive_collected_at",
        "noncanonical_collected_at",
        "bad_request_start",
        "noncanonical_request_date",
        "samples_tuple",
        "sample_not_dict",
        "missing_sample_field",
        "extra_sample_field",
        "bool_status",
        "unsupported_status",
        "sample_wrong_type",
        "sample_date_out_of_range",
        "inverted_range",
        "range_too_long",
        "duplicate_asset_date",
    ],
)
def test_daily_status_decoder_rejects_noncanonical_or_invalid_payloads(mutation: str) -> None:
    payload = _payload_copy()
    samples = cast(list[dict[str, object]], payload["samples"])
    if mutation == "missing_batch_field":
        payload.pop("request_end")
    elif mutation == "extra_batch_field":
        payload["unexpected"] = "value"
    elif mutation == "wrong_kind":
        payload["kind"] = "bar"
    elif mutation == "unsupported_schema":
        payload["schema_version"] = "qmt-native-daily-status.v2"
    elif mutation == "bad_uuid":
        payload["batch_id"] = "not-a-uuid"
    elif mutation == "noncanonical_uuid":
        payload["batch_id"] = "123E4567-E89B-12D3-A456-426614174000"
    elif mutation == "naive_collected_at":
        payload["collected_at"] = "2099-10-29T08:00:00"
    elif mutation == "noncanonical_collected_at":
        payload["collected_at"] = "2099-10-29T16:00:00+08:00"
    elif mutation == "bad_request_start":
        payload["request_start"] = "20991026"
    elif mutation == "noncanonical_request_date":
        payload["request_start"] = "2099-10-26T00:00:00"
    elif mutation == "samples_tuple":
        payload["samples"] = tuple(samples)
    elif mutation == "sample_not_dict":
        samples[0] = cast(dict[str, object], "not-a-sample")
    elif mutation == "missing_sample_field":
        samples[0].pop("suspend_flag")
    elif mutation == "extra_sample_field":
        samples[0]["observed_at"] = _COLLECTED_AT
    elif mutation == "bool_status":
        samples[0]["suspend_flag"] = True
    elif mutation == "unsupported_status":
        samples[0]["suspend_flag"] = 2
    elif mutation == "sample_wrong_type":
        samples[0]["asset_code"] = 510300
    elif mutation == "sample_date_out_of_range":
        samples[0]["bar_date"] = "2099-10-25"
    elif mutation == "inverted_range":
        payload["request_start"] = "2099-10-28"
        payload["request_end"] = "2099-10-26"
    elif mutation == "range_too_long":
        payload["request_start"] = "2099-09-01"
    else:
        samples[1]["asset_code"] = samples[0]["asset_code"]
        samples[1]["bar_date"] = samples[0]["bar_date"]

    with pytest.raises(QmtDailyStatusValidationError):
        decode_qmt_daily_status_payload(payload)


def test_daily_status_decoder_requires_concrete_json_types() -> None:
    with pytest.raises(QmtDailyStatusValidationError):
        decode_qmt_daily_status_payload(cast(object, UserDict(_VALID_PAYLOAD)))
    with pytest.raises(QmtDailyStatusValidationError):
        decode_qmt_daily_status_payload(list(_VALID_PAYLOAD.items()))


def test_daily_status_domain_fixture_matches_decoder_wire_shape() -> None:
    batch = BridgeDailyStatusBatch(
        batch_id="123e4567-e89b-12d3-a456-426614174000",
        kind="daily_status",
        collected_at=datetime(2099, 10, 29, 8, tzinfo=UTC),
        request_start=date(2099, 10, 26),
        request_end=date(2099, 10, 28),
        samples=(
            BridgeDailyStatusSample("510300.SH", date(2099, 10, 26), 0),
            BridgeDailyStatusSample("600000.SH", date(2099, 10, 27), 1),
        ),
        schema_version="qmt-native-daily-status.v1",
    )

    assert batch.to_payload()["kind"] == "daily_status"
