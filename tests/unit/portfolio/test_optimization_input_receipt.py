"""Unit attacks for the independent governed R8 canonical input receipt."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import timedelta

import pytest

from apps.portfolio.domain.optimization_input_receipt import (
    GovernedOptimizationInputReceipt,
)
from apps.portfolio.infrastructure.optimization_input_receipt_codec import (
    decode_input_receipt,
    encode_input_receipt,
)
from tests.unit.portfolio.test_governed_optimization_inputs import NOW, _input_set


def test_complete_thirteen_input_graph_round_trips_through_strict_codec() -> None:
    input_set = _input_set()
    receipt = GovernedOptimizationInputReceipt.record(
        input_set=input_set,
        server_recorded_at=NOW,
    )

    restored = decode_input_receipt(encode_input_receipt(receipt))

    assert restored == receipt
    assert len(restored.input_set.payloads) == 13
    assert len(restored.input_set.owner_bindings) == 13
    assert len(restored.input_set.promotions) == 3
    assert {type(item) for item in restored.input_set.payloads} == {
        type(item) for item in input_set.payloads
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(owner="caller"),
        lambda payload: payload.update(content_hash="f" * 64),
        lambda payload: payload.pop("pit_manifest_set_hash"),
        lambda payload: payload.update(extra="not-allowed"),
    ],
)
def test_top_level_substitution_and_shape_drift_fail_closed(
    mutation: Callable[[dict[str, object]], object],
) -> None:
    receipt = GovernedOptimizationInputReceipt.record(
        input_set=_input_set(),
        server_recorded_at=NOW,
    )
    payload = deepcopy(encode_input_receipt(receipt))

    mutation(payload)

    with pytest.raises(ValueError):
        decode_input_receipt(payload)


def test_nested_owner_pit_private_mutation_fails_live_reconstruction() -> None:
    input_set = _input_set()
    binding = input_set.owner_bindings[0]
    object.__setattr__(binding, "pit_manifest_id", "attacker-pit")
    receipt = GovernedOptimizationInputReceipt.record(
        input_set=input_set,
        server_recorded_at=NOW,
    )

    with pytest.raises(ValueError, match="strict reconstruction"):
        decode_input_receipt(encode_input_receipt(receipt))


def test_receipt_rejects_future_recording_and_expired_recording() -> None:
    input_set = _input_set()

    with pytest.raises(ValueError, match="outside the input-set window"):
        GovernedOptimizationInputReceipt.record(
            input_set=input_set,
            server_recorded_at=input_set.created_at - timedelta(microseconds=1),
        )
    with pytest.raises(ValueError, match="outside the input-set window"):
        GovernedOptimizationInputReceipt.record(
            input_set=input_set,
            server_recorded_at=input_set.valid_until,
        )
