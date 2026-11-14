"""Pure tests for the purpose-bound corporate-action raw-price policy."""

from __future__ import annotations

from dataclasses import replace

import pytest

from apps.simulated_trading.domain.corporate_action_nav_mark_policy import (
    SimulatedCorporateActionNavRawMarkPolicy,
    SimulatedCorporateActionNavRawMarkPolicyError,
)


def _policy(**changes: object) -> SimulatedCorporateActionNavRawMarkPolicy:
    """Build an explicit raw NAV mark policy for contract tests."""

    values: dict[str, object] = {
        "schema_version": "simulated-corporate-action-nav-raw-mark-policy.v1",
        "purpose": "simulated_corporate_action_nav_raw_mark",
        "policy_id": "nav-raw-mark-policy",
        "version": "v1",
        "source": "tushare",
        "publication_key": "nav-reference-v1",
        "frequency": "1d",
        "adjustment": "none",
        "observation_basis": "daily_interval_end",
        "currency": "CNY",
        "supported_asset_types": ("equity",),
        "freshness_window_seconds": 86400,
    }
    values.update(changes)
    return SimulatedCorporateActionNavRawMarkPolicy(**values)  # type: ignore[arg-type]


def test_policy_is_explicit_and_has_a_purpose_separated_canonical_hash() -> None:
    policy = _policy()

    payload = policy.to_payload()

    assert payload["purpose"] == "simulated_corporate_action_nav_raw_mark"
    assert payload["adjustment"] == "none"
    assert payload["observation_basis"] == "daily_interval_end"
    assert policy.content_sha256 != _policy(version="v2").content_sha256
    assert len(policy.content_sha256) == 64
    assert policy.identity == "simulated_corporate_action_nav_raw_mark:nav-raw-mark-policy:v1"
    assert SimulatedCorporateActionNavRawMarkPolicy.from_payload(payload) == policy


@pytest.mark.parametrize(
    "changes",
    (
        {"schema_version": "simulated-initial-position-mark-policy.daily-interval.v1"},
        {"purpose": "apply_time_initial_position_mark"},
        {"frequency": "1m"},
        {"adjustment": "forward"},
        {"observation_basis": "source_observed_at"},
        {"currency": "USD"},
        {"supported_asset_types": ()},
        {"supported_asset_types": ("equity", "equity")},
        {"freshness_window_seconds": True},
        {"freshness_window_seconds": 0},
        {"freshness_window_seconds": 2**80},
    ),
)
def test_policy_rejects_implicit_or_out_of_scope_values(changes: dict[str, object]) -> None:
    with pytest.raises(SimulatedCorporateActionNavRawMarkPolicyError):
        replace(_policy(), **changes)


def test_policy_payload_decoder_rejects_unknown_fields() -> None:
    payload = _policy().to_payload()
    payload["initial_position_mark_permission"] = True

    with pytest.raises(SimulatedCorporateActionNavRawMarkPolicyError):
        SimulatedCorporateActionNavRawMarkPolicy.from_payload(payload)


@pytest.mark.parametrize(
    "payload",
    (
        None,
        {**_policy().to_payload(), "supported_asset_types": ("equity",)},
        {**_policy().to_payload(), "freshness_window_seconds": True},
        {**_policy().to_payload(), "purpose": 1},
    ),
)
def test_policy_payload_decoder_rejects_non_object_and_wrong_field_types(
    payload: object,
) -> None:
    with pytest.raises(SimulatedCorporateActionNavRawMarkPolicyError):
        SimulatedCorporateActionNavRawMarkPolicy.from_payload(payload)


def test_policy_rejects_invalid_source_tokens() -> None:
    with pytest.raises(SimulatedCorporateActionNavRawMarkPolicyError):
        replace(_policy(), policy_id="bad policy id")
