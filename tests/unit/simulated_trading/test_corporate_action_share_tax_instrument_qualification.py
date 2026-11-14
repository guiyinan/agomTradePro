"""Share-model scope must match original currency, listing and current selector pins."""

import json
from dataclasses import replace
from datetime import date, timedelta

import pytest

from apps.simulated_trading import corporate_action_share_tax_instrument_qualification as instrument
from apps.simulated_trading import corporate_action_share_tax_policy_composition as policy
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_share_tax_model import _query
from tests.unit.simulated_trading.test_corporate_action_share_tax_policy_composition import (
    _configuration,
    _payload,
    vars_scope,
)
from tests.unit.simulated_trading.test_corporate_action_tax_instrument_qualification import (
    _inputs as cash_inputs,
)
from tests.unit.simulated_trading.test_corporate_action_tax_instrument_qualification import (
    source,
)


def _inputs(monkeypatch, *, currency="CNY"):
    # Synthetic sealed reference objects exercise the real reader; no source or
    # financial authority is inferred from their fixture values.
    monkeypatch.setattr(source, "_SECURITY_ID", source._ASSET_CODE)
    _, classification, snapshot, cutoff = cash_inputs(monkeypatch, currency=currency)
    query = replace(
        _query(),
        security_id=source._ASSET_CODE,
        asset_code=source._ASSET_CODE,
        exchange=type(_query().exchange).SH,
        record_date=date(2025, 5, 1),
        effective_date=date(2025, 5, 2),
        stage_date=date(2025, 5, 5),
        source_observed_at=cutoff - timedelta(days=1),
    )
    payload = _payload()
    row = payload["models"][0]
    row["scope"] = {
        name: (value.value if hasattr(value, "value") else value)
        for name, value in vars_scope(query).items()
    }
    row["simulated_asset_type"] = classification.simulated_asset_type
    row["valid_from"] = (cutoff - timedelta(days=1)).isoformat()
    row["valid_until"] = (cutoff + timedelta(days=1)).isoformat()
    row["record_date_start"] = "2025-01-01"
    row["record_date_end"] = "2025-12-31"
    selection = classification.identity_evidence.selection
    config = replace(
        _configuration(payload),
        environment=source._ENVIRONMENT,
        value_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        profile_id=selection.profile_id,
        profile_key=selection.profile_key,
        profile_version=selection.profile_version,
        profile_content_sha256=selection.profile_content_hash,
        profile_created_at=selection.profile_activated_at - timedelta(seconds=1),
        profile_activated_at=selection.profile_activated_at,
        snapshot_id=selection.runtime_snapshot_id,
        snapshot_sha256=selection.runtime_snapshot_hash,
        snapshot_generated_at=selection.runtime_snapshot_generated_at,
        effective_at=selection.profile_activated_at,
        checked_at=cutoff,
    )
    monkeypatch.setattr(policy, "read_corporate_action_configuration", lambda **kwargs: config)
    configured = policy.read_current_share_capital_tax_policy(
        query=query, environment=source._ENVIRONMENT, as_of=cutoff
    )
    return query, configured, classification, snapshot, cutoff


def test_current_capital_model_uses_exact_native_reference_provenance(monkeypatch):
    query, configured, classification, snapshot, cutoff = _inputs(monkeypatch)
    proof = instrument.qualify_share_capital_tax_instrument(
        query=query,
        configured=configured,
        classification=classification,
        snapshot=snapshot,
        as_of=cutoff,
    )
    assert (
        proof.valid_until == classification.identity_evidence.source_evidence.identity_valid_until
    )
    assert proof.known_at <= cutoff
    assert proof.snapshot_id == str(snapshot.snapshot_id)
    assert proof.must_not_use_for_real_tax_decision is True


@pytest.mark.parametrize("currency", [None, "USD", "HKD"])
def test_unqualified_currency_never_inherits_model_cny(monkeypatch, currency):
    query, configured, classification, snapshot, cutoff = _inputs(monkeypatch, currency=currency)
    with pytest.raises(BusinessLogicError):
        instrument.qualify_share_capital_tax_instrument(
            query=query,
            configured=configured,
            classification=classification,
            snapshot=snapshot,
            as_of=cutoff,
        )


@pytest.mark.parametrize(
    "defect", ["profile", "snapshot", "listing", "asset_type", "expired", "future"]
)
def test_current_source_and_model_mismatches_block(monkeypatch, defect):
    query, configured, classification, snapshot, cutoff = _inputs(monkeypatch)
    if defect == "profile":
        configured = replace(
            configured,
            configuration=replace(configured.configuration, profile_id="changed-profile"),
        )
    elif defect == "snapshot":
        snapshot = source._synthetic_snapshot()
    elif defect == "listing":
        query = replace(query, record_date=date(2019, 12, 31))
        configured = replace(configured, record_date_start=date(2019, 1, 1))
    elif defect == "asset_type":
        configured = replace(configured, simulated_asset_type="different-explicit-model-type")
    elif defect == "expired":
        cutoff = classification.identity_evidence.source_evidence.identity_valid_until
    else:
        cutoff -= timedelta(seconds=1)
    with pytest.raises(BusinessLogicError):
        instrument.qualify_share_capital_tax_instrument(
            query=query,
            configured=configured,
            classification=classification,
            snapshot=snapshot,
            as_of=cutoff,
        )
