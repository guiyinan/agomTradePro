"""Application contract tests for owner-bound raw NAV marks."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.simulated_trading.application.corporate_action_nav_mark import (
    SimulatedCorporateActionNavRawMarkContractError,
    SimulatedCorporateActionNavRawMarkPolicyBinding,
    SimulatedCorporateActionNavRawMarkQuery,
)
from apps.simulated_trading.domain.corporate_action_nav_mark_policy import (
    SimulatedCorporateActionNavRawMarkPolicy,
)

_CHECKED = datetime(2026, 10, 28, 6, 59, tzinfo=UTC)


def _policy() -> SimulatedCorporateActionNavRawMarkPolicy:
    """Return one explicit raw mark policy with no inherited authority."""

    return SimulatedCorporateActionNavRawMarkPolicy(
        schema_version="simulated-corporate-action-nav-raw-mark-policy.v1",
        purpose="simulated_corporate_action_nav_raw_mark",
        policy_id="nav-raw-mark-policy",
        version="v1",
        source="tushare",
        publication_key="nav-reference-v1",
        frequency="1d",
        adjustment="none",
        observation_basis="daily_interval_end",
        currency="CNY",
        supported_asset_types=("equity",),
        freshness_window_seconds=86400,
    )


def _binding(**changes: object) -> SimulatedCorporateActionNavRawMarkPolicyBinding:
    """Build a current binding with complete runtime provenance and a finite window."""

    values: dict[str, object] = {
        "policy": _policy(),
        "runtime_environment": "development",
        "profile_id": "profile-7",
        "profile_key": "nav-raw-mark",
        "profile_version": 7,
        "profile_content_sha256": "a" * 64,
        "profile_activated_at": _CHECKED - timedelta(hours=5),
        "snapshot_id": "snapshot-7",
        "snapshot_content_sha256": "b" * 64,
        "snapshot_generated_at": _CHECKED - timedelta(hours=4),
        "snapshot_effective_from": _CHECKED - timedelta(hours=5),
        "known_at": _CHECKED - timedelta(hours=3),
        "valid_from": _CHECKED - timedelta(hours=5),
        "valid_until": _CHECKED + timedelta(days=2),
        "checked_at": _CHECKED,
    }
    values.update(changes)
    return SimulatedCorporateActionNavRawMarkPolicyBinding(**values)  # type: ignore[arg-type]


def test_query_binds_physical_and_canonical_owner_identity_separately() -> None:
    query = SimulatedCorporateActionNavRawMarkQuery(
        physical_account_id=17,
        canonical_account_id="simulated:17",
        owner_user_id=23,
        security_id="security-000001",
        asset_code="000001.SZ",
        asset_type="equity",
    )

    query.validate()
    assert query.physical_account_id == 17
    assert query.canonical_account_id == "simulated:17"
    assert query.owner_user_id == 23


@pytest.mark.parametrize(
    "changes",
    (
        {"physical_account_id": True},
        {"physical_account_id": 0},
        {"canonical_account_id": "simulated:17 "},
        {"owner_user_id": False},
        {"security_id": "security with spaces"},
        {"asset_code": ""},
    ),
)
def test_query_rejects_malformed_owner_or_instrument_identity(changes: dict[str, object]) -> None:
    query = SimulatedCorporateActionNavRawMarkQuery(
        physical_account_id=17,
        canonical_account_id="simulated:17",
        owner_user_id=23,
        security_id="security-000001",
        asset_code="000001.SZ",
        asset_type="equity",
    )

    with pytest.raises(SimulatedCorporateActionNavRawMarkContractError):
        replace(query, **changes).validate()


def test_policy_binding_requires_known_provenance_and_a_current_finite_window() -> None:
    binding = _binding()
    binding.validate_for(as_of=_CHECKED + timedelta(seconds=1))

    assert len(binding.content_sha256) == 64


@pytest.mark.parametrize(
    ("changes", "as_of"),
    (
        ({"checked_at": _CHECKED + timedelta(seconds=2)}, _CHECKED + timedelta(seconds=1)),
        ({"valid_from": _CHECKED + timedelta(seconds=1)}, _CHECKED + timedelta(seconds=1)),
        ({"known_at": _CHECKED + timedelta(seconds=1)}, _CHECKED + timedelta(seconds=1)),
        (
            {"snapshot_generated_at": _CHECKED + timedelta(seconds=1)},
            _CHECKED + timedelta(seconds=1),
        ),
        ({"valid_until": _CHECKED}, _CHECKED),
    ),
)
def test_policy_binding_rejects_future_known_clocks_and_expired_window(
    changes: dict[str, object], as_of: datetime
) -> None:
    binding = _binding(**changes)

    with pytest.raises(SimulatedCorporateActionNavRawMarkContractError):
        binding.validate_for(as_of=as_of)
