"""NAV purpose configuration never inherits initial-position marking or financial authority."""

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from apps.simulated_trading import corporate_action_nav_mark_composition as composition
from tests.unit.simulated_trading.test_corporate_action_nav_mark_reader import (
    _AS_OF,
    _policy,
    _query,
)
from tests.unit.simulated_trading.test_corporate_action_share_tax_policy_composition import (
    _configuration,
)


def _configuration_evidence(payload):
    base = _configuration({})
    return replace(
        base,
        definition_key=composition.CORPORATE_ACTION_NAV_RAW_MARK_POLICY_KEY,
        environment="test",
        value_json=json.dumps(payload),
        profile_created_at=_AS_OF - timedelta(days=3),
        profile_activated_at=_AS_OF - timedelta(days=2),
        effective_at=_AS_OF - timedelta(days=2),
        snapshot_generated_at=_AS_OF - timedelta(days=1),
        checked_at=_AS_OF + timedelta(seconds=1),
    )


def _payload():
    return {
        "schema": "simulated.corporate_action.nav_raw_mark_configuration.v1",
        "policy": _policy().to_payload(),
        "valid_from": (_AS_OF - timedelta(days=1)).isoformat(),
        "valid_until": (_AS_OF + timedelta(days=1)).isoformat(),
    }


def test_nav_configuration_preserves_original_policy_completion_and_profile(monkeypatch):
    evidence = _configuration_evidence(_payload())
    monkeypatch.setattr(
        composition, "read_corporate_action_configuration", lambda **kwargs: evidence
    )
    result = composition.ConfiguredCorporateActionNavRawMarkPolicyReader(
        environment="test"
    ).read_policy(query=_query(), as_of=_AS_OF)
    assert result is not None
    assert result.checked_at == evidence.checked_at
    assert result.snapshot_generated_at == evidence.snapshot_generated_at
    assert result.policy.purpose == "simulated_corporate_action_nav_raw_mark"


@pytest.mark.parametrize(
    "defect", ["purpose", "adjustment", "expiry", "asset", "field", "schema", "environment"]
)
def test_missing_wrong_purpose_or_expired_nav_configuration_is_unavailable(monkeypatch, defect):
    payload = _payload()
    if defect == "purpose":
        payload["policy"]["purpose"] = "apply_time_initial_position_mark"
    elif defect == "adjustment":
        payload["policy"]["adjustment"] = "forward"
    elif defect == "expiry":
        payload["valid_until"] = _AS_OF.isoformat()
    elif defect == "asset":
        payload["policy"]["supported_asset_types"] = ["unrelated"]
    elif defect == "field":
        payload["financial_permission"] = True
    elif defect == "schema":
        payload["schema"] = "initial-mark"
    evidence = _configuration_evidence(payload)
    if defect == "environment":
        evidence = replace(evidence, environment="another")
    monkeypatch.setattr(
        composition, "read_corporate_action_configuration", lambda **kwargs: evidence
    )
    assert (
        composition.ConfiguredCorporateActionNavRawMarkPolicyReader(environment="test").read_policy(
            query=_query(), as_of=_AS_OF
        )
        is None
    )
