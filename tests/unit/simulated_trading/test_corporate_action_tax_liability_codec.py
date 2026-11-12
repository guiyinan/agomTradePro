"""Stored financial components retain exact bytes, scope, lineage and money."""

import hashlib
import json
from dataclasses import replace
from decimal import Decimal

import pytest

from apps.simulated_trading.domain.corporate_action_tax_liability import (
    TaxLiabilityCashAction,
    TaxLiabilityCashRequest,
    plan_corporate_action_tax_liability,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_codec import (
    decode_liability_state,
    decode_liability_transition,
    encode_liability_state,
    encode_liability_transition,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_tax_liability import _taxable_assessment


def _transition():
    assessment = _taxable_assessment()
    original = plan_corporate_action_tax_liability(assessment, prior_state=None, cash_request=None)
    return plan_corporate_action_tax_liability(
        assessment,
        prior_state=original.state_after,
        cash_request=TaxLiabilityCashRequest(
            TaxLiabilityCashAction.COLLECT_AVAILABLE,
            Decimal("0.50"),
            Decimal("0.00"),
        ),
    )


def _changed(payload, mutate):
    values = json.loads(payload)
    mutate(values)
    encoded = json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return encoded, hashlib.sha256(encoded.encode()).hexdigest()


def test_state_and_partial_cash_transition_round_trip_exactly():
    transition = _transition()
    state = transition.state_after
    assert decode_liability_state(encode_liability_state(state), state.state_sha256) == state
    restored = decode_liability_transition(
        encode_liability_transition(transition),
        transition.transition_sha256,
        before_state=transition.before_state,
        state_after=state,
    )
    assert restored == transition and restored.cash_delta == Decimal("-0.50")


def test_unicode_scope_keeps_the_domain_ascii_json_seal():
    original = _transition().state_after
    state = replace(original, scope=replace(original.scope, corporate_action_id="分红更正"))
    encoded = encode_liability_state(state)
    assert "\\u5206" in encoded
    assert decode_liability_state(encoded, state.state_sha256) == state


@pytest.mark.parametrize(
    "fault", ["schema", "extra", "boolean_owner", "float_money", "nan_money", "scope_extra"]
)
def test_rehashed_invalid_state_fails_closed(fault):
    state = _transition().state_after

    def mutate(value):
        if fault == "schema":
            value["schema"] = "unknown"
        elif fault == "extra":
            value["ignored"] = "unexpected"
        elif fault == "boolean_owner":
            value["scope"]["owner_user_id"] = True
        elif fault == "float_money":
            value["assessed_amount"] = 0.5
        elif fault == "nan_money":
            value["net_collected_amount"] = "NaN"
        elif fault == "scope_extra":
            value["scope"]["inferred_date"] = "2026-11-13"

    payload, digest = _changed(encode_liability_state(state), mutate)
    with pytest.raises(BusinessLogicError):
        decode_liability_state(payload, digest)


def test_rehashed_transition_cannot_change_collection_arithmetic():
    transition = _transition()
    payload, digest = _changed(
        encode_liability_transition(transition), lambda value: value.update(cash_delta="0")
    )
    with pytest.raises(BusinessLogicError):
        decode_liability_transition(
            payload,
            digest,
            before_state=transition.before_state,
            state_after=transition.state_after,
        )


def test_transition_requires_its_exact_predecessor_state():
    transition = _transition()
    with pytest.raises(BusinessLogicError):
        decode_liability_transition(
            encode_liability_transition(transition),
            transition.transition_sha256,
            before_state=None,
            state_after=transition.state_after,
        )


def test_wrong_stored_component_hash_cannot_be_repaired_by_decoding():
    state = _transition().state_after
    with pytest.raises(BusinessLogicError):
        decode_liability_state(encode_liability_state(state), "0" * 64)
