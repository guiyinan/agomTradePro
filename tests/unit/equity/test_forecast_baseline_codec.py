"""Canonical JSON codec coverage for the R1 forecast-baseline ledger."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

import pytest

from apps.equity.infrastructure.forecast_baseline_codec import (
    ForecastBaselineCodecError,
    decode_approval_evidence,
    decode_forecast_baseline_spec,
    encode_approval_evidence,
    encode_forecast_baseline_spec,
    seal_approval_evidence,
)
from tests.unit.equity.test_forecast_baseline import _spec
from tests.unit.equity.test_forecast_baseline_application import _approval


def test_codec_round_trip_rejects_approval_payload_tamper() -> None:
    approval = seal_approval_evidence(_approval())
    payload = encode_approval_evidence(approval)
    assert decode_approval_evidence(payload) == approval

    tampered = deepcopy(payload)
    tampered["payload"]["subject_code"] = "SUBSTITUTED"
    with pytest.raises(ForecastBaselineCodecError, match="content hash mismatch"):
        decode_approval_evidence(tampered)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value["payload"].pop("owner"), "fields do not match"),
        (lambda value: value["payload"].update({"unexpected": True}), "fields do not match"),
        (
            lambda value: value["payload"]["metric_rules"][0].update(
                {"maximum_forecast_error": "0.200"}
            ),
            "canonical decimal",
        ),
        (
            lambda value: value["payload"].update(
                {"approved_at": value["payload"]["approved_at"].replace("Z", "+00:00")}
            ),
            "canonical UTC",
        ),
        (lambda value: value["payload"].update({"family": "unknown"}), "unknown enum"),
        (
            lambda value: value["payload"].update({"metric_evaluation_order": {"0": "x"}}),
            "JSON array",
        ),
        (
            lambda value: value["payload"].update({"content_hash": "0" * 64}),
            "typed contract",
        ),
    ),
)
def test_spec_codec_rejects_noncanonical_or_tampered_json(
    mutation: Callable[[dict[str, object]], object],
    message: str,
) -> None:
    spec = _spec()
    payload = encode_forecast_baseline_spec(spec)
    assert decode_forecast_baseline_spec(payload) == spec

    tampered = deepcopy(payload)
    mutation(tampered)
    with pytest.raises(ForecastBaselineCodecError, match=message):
        decode_forecast_baseline_spec(tampered)
