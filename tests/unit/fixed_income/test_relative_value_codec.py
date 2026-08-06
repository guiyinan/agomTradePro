"""Strict typed canonical codec coverage for R5 persistence graphs."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import cast

import pytest

from apps.fixed_income.application.relative_value_persistence import (
    R5PersistedRelativeValueBundle,
    R5RelativeValuePersistenceDraft,
)
from apps.fixed_income.infrastructure.relative_value_codec import (
    R5RelativeValueCodecError,
    decode_r5_input_receipt,
    decode_r5_result_record,
    encode_r5_input_receipt,
    encode_r5_result_record,
)
from tests.unit.fixed_income.test_relative_value_use_case import (
    _EVALUATED_AT,
    _command,
    _fixture_graph,
    _runner_graph,
)


def _bundle(monkeypatch: pytest.MonkeyPatch) -> R5PersistedRelativeValueBundle:
    graph = _fixture_graph(monkeypatch)
    run = _runner_graph(graph).runner.execute_authoritative(_command(graph))
    draft = R5RelativeValuePersistenceDraft.from_authoritative_run(run)
    return R5PersistedRelativeValueBundle.from_draft(
        draft,
        recorded_at=_EVALUATED_AT + timedelta(minutes=1),
    )


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)
    return cast(dict[str, object], value)


def _root_fields(payload: dict[str, object]) -> dict[str, object]:
    value = _object(payload["value"])
    return _object(value["$fields"])


def _tagged_objects(value: object, tag: str) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    if isinstance(value, dict):
        tagged = _object(value)
        if tag in tagged:
            matches.append(tagged)
        for child in tagged.values():
            matches.extend(_tagged_objects(child, tag))
    elif isinstance(value, list):
        for child in value:
            matches.extend(_tagged_objects(child, tag))
    return matches


def test_receipt_and_complete_result_round_trip_canonically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(monkeypatch)
    receipt_payload = encode_r5_input_receipt(bundle.receipt)
    result_payload = encode_r5_result_record(bundle.result)

    receipt = decode_r5_input_receipt(receipt_payload)
    result = decode_r5_result_record(result_payload)

    assert receipt == bundle.receipt
    assert result == bundle.result
    assert encode_r5_input_receipt(receipt) == receipt_payload
    assert encode_r5_result_record(result) == result_payload
    assert result.assessment.output_hash == result.assessment.calculated_output_hash


@pytest.mark.parametrize("mutation", ("missing", "extra", "schema"))
def test_receipt_envelope_and_fields_must_be_exact(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    payload = deepcopy(encode_r5_input_receipt(_bundle(monkeypatch).receipt))
    if mutation == "missing":
        _root_fields(payload).pop("owner")
    elif mutation == "extra":
        _root_fields(payload)["caller_trust"] = True
    else:
        payload["schema"] = "caller-schema.v1"

    with pytest.raises(R5RelativeValueCodecError):
        decode_r5_input_receipt(payload)


def test_noncanonical_datetime_and_wrong_owner_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = deepcopy(encode_r5_input_receipt(_bundle(monkeypatch).receipt))
    fields = _root_fields(payload)
    evaluated_at = _object(fields["evaluated_at"])
    evaluated_at["$datetime"] = str(evaluated_at["$datetime"]).replace(
        "Z",
        "+00:00",
    )
    with pytest.raises(R5RelativeValueCodecError, match="noncanonical"):
        decode_r5_input_receipt(payload)

    payload = deepcopy(encode_r5_input_receipt(_bundle(monkeypatch).receipt))
    _root_fields(payload)["owner"] = "portfolio"
    with pytest.raises(R5RelativeValueCodecError, match="validation failed"):
        decode_r5_input_receipt(payload)


def test_nested_composite_hash_tamper_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = deepcopy(encode_r5_result_record(_bundle(monkeypatch).result))
    assessment = _object(_root_fields(payload)["assessment"])
    assessment_fields = _object(assessment["$fields"])
    assessment_fields["output_hash"] = "0" * 64

    with pytest.raises(R5RelativeValueCodecError, match="validation failed"):
        decode_r5_result_record(payload)


def test_unknown_type_and_scalar_widening_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = deepcopy(encode_r5_input_receipt(_bundle(monkeypatch).receipt))
    _object(payload["value"])["$type"] = "CallerControlledType"
    with pytest.raises(R5RelativeValueCodecError, match="unknown"):
        decode_r5_input_receipt(payload)

    payload = deepcopy(encode_r5_input_receipt(_bundle(monkeypatch).receipt))
    _root_fields(payload)["research_only"] = 1
    with pytest.raises(R5RelativeValueCodecError, match="type mismatch"):
        decode_r5_input_receipt(payload)


@pytest.mark.parametrize("root_type", ("receipt", "result"))
@pytest.mark.parametrize(
    "mutation",
    ("noncanonical", "nonfinite", "wrong_scalar", "wrong_tag"),
)
def test_decimal_tags_are_typed_finite_and_canonical(
    monkeypatch: pytest.MonkeyPatch,
    root_type: str,
    mutation: str,
) -> None:
    bundle = _bundle(monkeypatch)
    if root_type == "receipt":
        payload = deepcopy(encode_r5_input_receipt(bundle.receipt))
        decoder = decode_r5_input_receipt
    else:
        payload = deepcopy(encode_r5_result_record(bundle.result))
        decoder = decode_r5_result_record
    decimal_tags = _tagged_objects(payload, "$decimal")
    assert decimal_tags
    target = decimal_tags[0]
    original = target["$decimal"]
    assert isinstance(original, str)
    if mutation == "noncanonical":
        target["$decimal"] = f"{original}0" if "." in original else f"{original}.0"
    elif mutation == "nonfinite":
        target["$decimal"] = "NaN"
    elif mutation == "wrong_scalar":
        target["$decimal"] = 1
    else:
        target["$caller_decimal"] = target.pop("$decimal")

    with pytest.raises(R5RelativeValueCodecError):
        decoder(payload)
