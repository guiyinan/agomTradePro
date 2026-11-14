"""Read-boundary orchestration uses advancing real clocks, never a rewritten original clock."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from apps.simulated_trading import corporate_action_share_tax_model_composition as composition
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_share_tax_model import _NOW, _query
from tests.unit.simulated_trading.test_corporate_action_share_tax_proof import _proof, _request
from tests.unit.simulated_trading.test_corporate_action_share_tax_statutory_qualification import (
    _inputs,
)


def _reader(monkeypatch):
    configured, retained = _inputs(monkeypatch)
    # Advance the actual configuration completion clock beyond the entry cutoff.
    configured = replace(
        configured,
        configuration=replace(configured.configuration, checked_at=_NOW + timedelta(seconds=1)),
    )
    monkeypatch.setattr(
        composition, "read_share_capital_tax_policy_for_stage", lambda **kwargs: configured
    )
    reader = composition.DjangoCurrentShareCapitalTaxQualificationReader.__new__(
        composition.DjangoCurrentShareCapitalTaxQualificationReader
    )
    reader._environment = "test"
    reader._using = "default"
    reader._sources = SimpleNamespace(read_retained_bundle=lambda **kwargs: retained)
    reader._action_source = SimpleNamespace(verify_source=lambda request: True)
    monkeypatch.setattr(
        composition,
        "make_security_disclosure_event_reader",
        lambda **kwargs: SimpleNamespace(execute=lambda scope: ()),
    )
    monkeypatch.setattr(
        composition,
        "_find_current_event_with_complete_lineage",
        lambda *args, **kwargs: SimpleNamespace(content_hash=_query().source_revision_sha256),
    )
    monkeypatch.setattr(
        composition, "read_instrument_reference_snapshot", lambda **kwargs: object()
    )

    def classification(**kwargs):
        return SimpleNamespace(
            read_at=kwargs["as_of"],
            identity_evidence=SimpleNamespace(
                source_evidence=SimpleNamespace(snapshot_id="synthetic")
            ),
        )

    monkeypatch.setattr(
        composition,
        "build_current_reference_classification_reader",
        lambda **kwargs: SimpleNamespace(
            resolve_simulated_instrument_classification=classification
        ),
    )

    def instrument(**kwargs):
        # The independent instrument qualifier enforces this exact ordering.
        kwargs["configured"].verify_for(kwargs["query"], as_of=kwargs["as_of"])
        assert kwargs["classification"].read_at == kwargs["as_of"]
        return SimpleNamespace(
            semantic_sha256="5" * 64,
            snapshot_id="synthetic-snapshot",
            snapshot_content_sha256="6" * 64,
            snapshot_record_digest="7" * 64,
            occurrence_id="synthetic-occurrence",
            reference_response_completed_at=_NOW - timedelta(days=1),
            known_at=_NOW - timedelta(hours=1),
            valid_until=_NOW + timedelta(seconds=20),
        )

    monkeypatch.setattr(composition, "qualify_share_capital_tax_instrument", instrument)
    monkeypatch.setattr(composition.timezone, "now", lambda: _NOW + timedelta(seconds=2))
    return reader


def test_current_model_composes_advancing_configuration_and_capture_clocks(monkeypatch):
    reader = _reader(monkeypatch)
    proof = reader._read_state(
        _request(), canonical_account_id=_query().canonical_account_id, as_of=_NOW
    )
    assert proof.model.source_1997_198.captured_at == _NOW - timedelta(seconds=30)
    assert proof.checked_at == _NOW + timedelta(seconds=2)
    assert proof.valid_until == _NOW + timedelta(seconds=20)
    proof.verify_for(_request(), as_of=proof.checked_at)


@pytest.mark.parametrize("defect", ["profile", "expired", "backward"])
def test_current_model_final_reread_rejects_changed_or_expired_evidence(monkeypatch, defect):
    first = _proof()
    reader = composition.DjangoCurrentShareCapitalTaxQualificationReader.__new__(
        composition.DjangoCurrentShareCapitalTaxQualificationReader
    )
    second = (
        replace(first, model=replace(first.model, runtime_profile_id="changed"))
        if defect == "profile"
        else first
    )
    states = iter((first, second))
    monkeypatch.setattr(reader, "_read_state", lambda *args, **kwargs: next(states))
    clock = (
        _NOW - timedelta(seconds=1)
        if defect == "backward"
        else first.valid_until if defect == "expired" else _NOW
    )
    monkeypatch.setattr(composition.timezone, "now", lambda: clock)
    with pytest.raises(BusinessLogicError):
        reader.read_current(
            _request(), canonical_account_id=_query().canonical_account_id, as_of=_NOW
        )
