"""Complete original model material is bound to its actual simulated financial scope."""

from dataclasses import replace
from datetime import timedelta

import pytest

from apps.simulated_trading.application.corporate_action_share_tax_proof import (
    ShareCapitalTaxQualificationProof,
)
from apps.simulated_trading.infrastructure.corporate_action_constructor_codec import (
    encode_corporate_action_constructor,
    restore_corporate_action_constructor,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_posting import _share_delivery_request
from tests.unit.simulated_trading.test_corporate_action_share_tax_model import _NOW, _model, _query


def _request():
    query = _query()
    names = (
        "owner_user_id",
        "security_id",
        "asset_code",
        "source_namespace",
        "source_record_id",
        "source_event_id",
        "source_revision_id",
        "source_payload_sha256",
        "action_kind",
        "stage",
        "entry_kind",
        "record_date",
        "effective_date",
        "stage_date",
        "source_observed_at",
    )
    return replace(
        _share_delivery_request(),
        account_id=query.physical_account_id,
        **{name: getattr(query, name) for name in names},
        qualified_at=_NOW - timedelta(minutes=2),
        posted_at=_NOW - timedelta(minutes=1),
        sellable_date=query.stage_date,
    )


def _proof():
    return ShareCapitalTaxQualificationProof(
        _query(),
        _model(),
        "test",
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "4" * 64,
        "5" * 64,
        "synthetic-instrument-snapshot",
        "6" * 64,
        "7" * 64,
        "synthetic-occurrence",
        _NOW - timedelta(days=1),
        _NOW,
        _NOW + timedelta(minutes=1),
    )


def test_original_complete_model_constructor_roundtrip_keeps_actual_clocks_and_terms():
    proof = _proof()
    proof.verify_for(_request(), as_of=_NOW)
    restored = restore_corporate_action_constructor(
        encode_corporate_action_constructor(proof), ShareCapitalTaxQualificationProof
    )
    assert restored == proof
    assert restored.model.source_terms == proof.model.source_terms
    assert restored.simulation_only is True
    assert restored.must_not_use_for_real_tax_decision is True


def test_native_instrument_digests_keep_their_original_prefixed_representation():
    proof = replace(
        _proof(),
        instrument_snapshot_content_sha256="sha256:" + "6" * 64,
        instrument_snapshot_record_digest="sha256:" + "7" * 64,
    )
    assert proof.instrument_snapshot_content_sha256 == "sha256:" + "6" * 64
    assert proof.instrument_snapshot_record_digest == "sha256:" + "7" * 64
    proof.verify_for(_request(), as_of=_NOW)


@pytest.mark.parametrize(
    "pin",
    [
        "sha512:" + "a" * 64,
        "sha256:" + "A" * 64,
        "sha256:sha256:" + "a" * 64,
        "sha256:" + "a" * 63,
        " " + "a" * 64,
    ],
)
def test_native_pin_compatibility_does_not_normalize_malformed_digest(pin):
    with pytest.raises(BusinessLogicError):
        replace(_proof(), instrument_snapshot_record_digest=pin)


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_id", 18),
        ("owner_user_id", 30),
        ("source_record_id", "other"),
        ("source_payload_sha256", "f" * 64),
        ("source_event_id", "other-event"),
    ],
)
def test_retained_model_cannot_authorize_other_owner_or_source(field, value):
    with pytest.raises(BusinessLogicError):
        _proof().verify_for(replace(_request(), **{field: value}), as_of=_NOW)


def test_original_proof_does_not_gain_a_new_current_deadline_on_readback():
    proof = _proof()
    with pytest.raises(BusinessLogicError):
        proof.verify_for(_request(), as_of=proof.valid_until)
    with pytest.raises(BusinessLogicError):
        replace(proof, instrument_response_completed_at=_NOW + timedelta(seconds=1))


def test_stable_selection_ignores_only_read_clocks_and_detects_same_value_profile_change():
    proof = _proof()
    reread = replace(
        proof, checked_at=_NOW + timedelta(seconds=1), model=replace(proof.model, checked_at=_NOW)
    )
    assert reread.selection_sha256 == proof.selection_sha256
    assert (
        replace(
            proof, model=replace(proof.model, runtime_profile_id="changed-profile")
        ).selection_sha256
        != proof.selection_sha256
    )
