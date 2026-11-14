"""Capital-transfer simulation settings require an explicit exact owned scope."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from apps.simulated_trading import corporate_action_share_tax_policy_composition as policy
from apps.simulated_trading.corporate_action_configuration_composition import (
    CorporateActionConfigurationEvidence,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_share_tax_model import _NOW, _query


def _payload():
    query = _query()
    return {
        "schema": "simulated.corporate_action.share_capital_tax_models.v1",
        "models": [
            {
                "enabled": True,
                "simulation_only": True,
                "must_not_use_for_real_tax_decision": True,
                "model_kind": "stock_issue_premium_transfer_no_withholding_simulation",
                "model_rule_id": "synthetic-reviewed-share-model",
                "simulated_asset_type": "stock",
                "scope": {
                    name: (value.value if hasattr(value, "value") else value)
                    for name, value in vars_scope(query).items()
                },
                "valid_from": (_NOW - timedelta(days=1)).isoformat(),
                "valid_until": (_NOW + timedelta(hours=1)).isoformat(),
                "record_date_start": "2026-01-01",
                "record_date_end": "2026-12-31",
                "statutory_bundle_id": "synthetic-capital-source-bundle",
                "statutory_bundle_version": "1",
                "statutory_source_bundle_sha256": "4" * 64,
                "document_1997_id": "synthetic-sat-1997-198",
                "document_1998_id": "synthetic-sat-1998-289",
            }
        ],
    }


def vars_scope(query):
    names = (
        "account_kind",
        "physical_account_id",
        "canonical_account_id",
        "owner_user_id",
        "security_id",
        "asset_code",
        "exchange",
        "persona",
        "instrument_kind",
        "currency",
        "capital_source",
    )
    return {name: getattr(query, name) for name in names}


def _configuration(payload):
    return CorporateActionConfigurationEvidence(
        definition_key=policy.SHARE_CAPITAL_TAX_MODELS_KEY,
        environment="test",
        value_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        profile_id="synthetic-profile",
        profile_key="test-profile",
        profile_version=1,
        profile_content_sha256="1" * 64,
        profile_created_at=_NOW - timedelta(days=3),
        profile_activated_at=_NOW - timedelta(days=2),
        snapshot_id="synthetic-snapshot",
        snapshot_sha256="2" * 64,
        snapshot_generated_at=_NOW - timedelta(days=2),
        effective_at=_NOW - timedelta(days=2),
        checked_at=_NOW,
    )


def _install(monkeypatch, payload):
    monkeypatch.setattr(
        policy, "read_corporate_action_configuration", lambda **kwargs: _configuration(payload)
    )


def test_explicit_capital_model_matches_owned_source_scope_and_preserves_actual_configuration(
    monkeypatch,
):
    payload = _payload()
    _install(monkeypatch, payload)
    result = policy.read_current_share_capital_tax_policy(
        query=_query(), environment="test", as_of=_NOW
    )
    assert result.configuration.profile_id == "synthetic-profile"
    assert result.statutory_bundle_id == "synthetic-capital-source-bundle"
    assert result.valid_until == _NOW + timedelta(hours=1)
    assert result.model_rule_id == "synthetic-reviewed-share-model"
    assert result.simulation_only is True
    assert result.must_not_use_for_real_tax_decision is True


@pytest.mark.parametrize(
    "changes",
    [{"owner_user_id": 30}, {"physical_account_id": 18}, {"canonical_account_id": "another"}],
)
def test_model_configuration_is_never_a_cross_account_default(monkeypatch, changes):
    _install(monkeypatch, _payload())
    with pytest.raises(BusinessLogicError):
        policy.read_current_share_capital_tax_policy(
            query=replace(_query(), **changes), environment="test", as_of=_NOW
        )


@pytest.mark.parametrize(
    "defect",
    [
        "missing_persona",
        "false_simulation",
        "boolean_one",
        "other_capital",
        "duplicate",
        "expired",
        "record_window",
        "unknown_field",
    ],
)
def test_missing_ambiguous_or_unreviewed_model_declarations_block(monkeypatch, defect):
    payload = _payload()
    row = payload["models"][0]
    if defect == "missing_persona":
        del row["scope"]["persona"]
    elif defect == "false_simulation":
        row["simulation_only"] = False
    elif defect == "boolean_one":
        row["must_not_use_for_real_tax_decision"] = 1
    elif defect == "other_capital":
        row["scope"]["capital_source"] = "other_capital_reserve"
    elif defect == "duplicate":
        payload["models"].append(deepcopy(row))
    elif defect == "expired":
        row["valid_until"] = _NOW.isoformat()
    elif defect == "record_window":
        row["record_date_start"] = "2026-11-01"
    else:
        row["unknown_permission"] = True
    _install(monkeypatch, payload)
    with pytest.raises(BusinessLogicError):
        policy.read_current_share_capital_tax_policy(query=_query(), environment="test", as_of=_NOW)
