"""API contracts for governed Strategy allocation-policy reads."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from apps.strategy.domain.allocation_matrix import (
    AllocationPolicyEntry,
    AllocationPolicySourceType,
    AllocationPolicyStatus,
    AllocationPolicyUnavailableError,
    AllocationPolicyVersion,
    AllocationStatisticsStatus,
    AllocationTarget,
    AssetAllocation,
    PolicyAllocationAdjustment,
    PolicyLevel,
    RegimeType,
    RiskProfile,
    calculate_allocation_policy_content_hash,
)


def test_allocation_policy_reads_require_authentication(api_client) -> None:
    """Policy content is never exposed to anonymous callers."""

    for endpoint in (
        "/api/strategy/allocation-policies/active/",
        "/api/strategy/allocation-policies/versions/",
        "/api/strategy/allocation-policies/versions/1/",
    ):
        assert api_client.get(endpoint).status_code in {401, 403}


def test_active_policy_read_is_strict_and_calls_application(authenticated_client) -> None:
    """The active endpoint rejects unknown fields before Application execution."""

    policy = _policy(version=2, status=AllocationPolicyStatus.ACTIVE)
    target = "apps.strategy.interface.allocation_policy_views.get_active_allocation_policy"
    with patch(target, return_value=policy) as query:
        response = authenticated_client.get(
            "/api/strategy/allocation-policies/active/",
            {"policy_key": "strategic_asset_allocation"},
        )
        invalid_response = authenticated_client.get(
            "/api/strategy/allocation-policies/active/",
            {"policy_key": "strategic_asset_allocation", "unexpected": "value"},
        )

    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["content_hash"] == policy.content_hash
    assert response.json()["must_not_use_for_decision"] is False
    assert response.json()["entries"][0]["allocation"]["equity"] == 0.5
    assert invalid_response.status_code == 400
    assert "Unknown parameters: unexpected" in str(invalid_response.json())
    query.assert_called_once_with("strategic_asset_allocation")


def test_version_list_and_detail_preserve_lifecycle_safety(authenticated_client) -> None:
    """Historical versions remain visibly non-active and never imply activation."""

    active = _policy(version=2, status=AllocationPolicyStatus.ACTIVE)
    historical = _policy(version=1, status=AllocationPolicyStatus.SUPERSEDED)
    list_target = "apps.strategy.interface.allocation_policy_views.list_allocation_policy_versions"
    detail_target = "apps.strategy.interface.allocation_policy_views.get_allocation_policy_version"
    with (
        patch(list_target, return_value=[active, historical]) as list_query,
        patch(detail_target, return_value=historical) as detail_query,
    ):
        list_response = authenticated_client.get("/api/strategy/allocation-policies/versions/")
        detail_response = authenticated_client.get("/api/strategy/allocation-policies/versions/1/")

    assert list_response.status_code == 200
    assert list_response.json()["count"] == 2
    assert [row["version"] for row in list_response.json()["results"]] == [2, 1]
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "superseded"
    assert detail_response.json()["must_not_use_for_decision"] is True
    assert "not active" in detail_response.json()["warnings"][0]
    list_query.assert_called_once_with("strategic_asset_allocation")
    detail_query.assert_called_once_with(1, "strategic_asset_allocation")


def test_missing_policy_is_a_stable_fail_closed_response(authenticated_client) -> None:
    """A missing version returns a stable not-found envelope with a decision block."""

    target = "apps.strategy.interface.allocation_policy_views.get_allocation_policy_version"
    with patch(
        target,
        side_effect=AllocationPolicyUnavailableError(
            "allocation_policy_version_missing:strategic_asset_allocation:v99"
        ),
    ):
        response = authenticated_client.get("/api/strategy/allocation-policies/versions/99/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "allocation_policy_not_found"
    assert response.json()["must_not_use_for_decision"] is True


def test_allocation_policy_routes_are_read_only(authenticated_client) -> None:
    """Unsafe mutation verbs remain unavailable until governance persistence exists."""

    response = authenticated_client.post(
        "/api/strategy/allocation-policies/active/",
        {"version": 2},
        format="json",
    )

    assert response.status_code == 405


def _policy(
    *,
    version: int,
    status: AllocationPolicyStatus,
) -> AllocationPolicyVersion:
    """Build one hash-valid policy for transport serialization."""

    entries = (
        AllocationPolicyEntry(
            regime=RegimeType.RECOVERY,
            risk_profile=RiskProfile.MODERATE,
            target=AllocationTarget(
                allocation=AssetAllocation(
                    equity=0.5,
                    fixed_income=0.3,
                    commodity=0.1,
                    cash=0.1,
                ),
                reasoning="API fixture",
                statistics_status=AllocationStatisticsStatus.LEGACY_UNVERIFIED,
            ),
        ),
    )
    adjustments = (
        PolicyAllocationAdjustment(
            policy_level=PolicyLevel.P0,
            equity_multiplier=1.0,
        ),
    )
    return AllocationPolicyVersion(
        policy_key="strategic_asset_allocation",
        version=version,
        status=status,
        entries=entries,
        adjustments=adjustments,
        content_hash=calculate_allocation_policy_content_hash(entries, adjustments),
        source_type=AllocationPolicySourceType.HUMAN,
        change_reason="API fixture",
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
        effective_at=(
            datetime(2026, 8, 5, tzinfo=UTC) if status is AllocationPolicyStatus.ACTIVE else None
        ),
        created_by_id=7,
    )
