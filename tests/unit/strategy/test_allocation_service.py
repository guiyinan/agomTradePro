from datetime import UTC, datetime
from types import SimpleNamespace

from apps.strategy.application.allocation_service import AllocationService
from apps.strategy.domain.allocation_matrix import (
    AllocationPolicyEntry,
    AllocationPolicySourceType,
    AllocationPolicyStatus,
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


def _position(asset_code: str, asset_class: str, market_value: float):
    return SimpleNamespace(
        asset_code=asset_code,
        asset_class=SimpleNamespace(value=asset_class),
        market_value=market_value,
    )


class AllocationPolicyRepository:
    def __init__(self) -> None:
        entries = tuple(
            AllocationPolicyEntry(
                regime=regime,
                risk_profile=risk_profile,
                target=AllocationTarget(
                    allocation=AssetAllocation(0.4, 0.3, 0.1, 0.2),
                    reasoning="test policy",
                    statistics_status=AllocationStatisticsStatus.HUMAN_ASSUMPTION,
                ),
            )
            for regime in RegimeType
            for risk_profile in RiskProfile
        )
        adjustments = tuple(PolicyAllocationAdjustment(level, 1.0) for level in PolicyLevel)
        self.policy = AllocationPolicyVersion(
            policy_key="strategic_asset_allocation",
            version=7,
            status=AllocationPolicyStatus.ACTIVE,
            entries=entries,
            adjustments=adjustments,
            content_hash=calculate_allocation_policy_content_hash(entries, adjustments),
            source_type=AllocationPolicySourceType.HUMAN,
            change_reason="unit test",
            created_at=datetime.now(UTC),
            effective_at=datetime.now(UTC),
        )

    def get_active(self, policy_key: str) -> AllocationPolicyVersion | None:
        return self.policy if policy_key == self.policy.policy_key else None


def test_allocation_service_accepts_position_protocol_without_account_entity():
    advice = AllocationService.calculate_allocation_advice(
        current_regime="Recovery",
        risk_profile="moderate",
        policy_level="P1",
        total_assets=1000.0,
        current_positions=[_position("510300.SH", "equity", 600.0)],
        asset_name_resolver=None,
        allocation_policy_repository=AllocationPolicyRepository(),
    )

    assert advice.current_allocation["equity"] == 0.6
    assert advice.current_allocation["cash"] == 0.4
    assert advice.allocation_policy_version == 7
