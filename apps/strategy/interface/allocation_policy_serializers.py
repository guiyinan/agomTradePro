"""Strict transport serializers for Strategy allocation-policy reads."""

from __future__ import annotations

from typing import cast

from rest_framework import serializers

from apps.strategy.application.allocation_policy import DEFAULT_ALLOCATION_POLICY_KEY
from apps.strategy.domain.allocation_matrix import (
    AllocationPolicyEntry,
    AllocationPolicyStatus,
    AllocationPolicyVersion,
    PolicyAllocationAdjustment,
)
from apps.strategy.interface.serializers import StrictStrategySerializer


class AllocationPolicyQuerySerializer(StrictStrategySerializer):
    """Validate a policy identity and reject every unknown query field."""

    policy_key = serializers.RegexField(
        regex=r"^[a-z][a-z0-9_]{2,63}$",
        required=False,
        default=DEFAULT_ALLOCATION_POLICY_KEY,
        max_length=64,
    )


def validated_policy_key(serializer: AllocationPolicyQuerySerializer) -> str:
    """Narrow a validated serializer value into the application key type."""

    return cast(str, serializer.validated_data["policy_key"])


def allocation_policy_summary(policy: AllocationPolicyVersion) -> dict[str, object]:
    """Serialize lifecycle metadata without expanding matrix content."""

    is_active = policy.status is AllocationPolicyStatus.ACTIVE
    return {
        "policy_key": policy.policy_key,
        "version": policy.version,
        "status": policy.status.value,
        "is_active": is_active,
        "content_hash": policy.content_hash,
        "source_type": policy.source_type.value,
        "change_reason": policy.change_reason,
        "based_on_version": policy.based_on_version,
        "created_by_id": policy.created_by_id,
        "created_at": policy.created_at.isoformat(),
        "effective_at": (None if policy.effective_at is None else policy.effective_at.isoformat()),
        "entry_count": len(policy.entries),
        "adjustment_count": len(policy.adjustments),
        "must_not_use_for_decision": not is_active,
    }


def allocation_policy_detail(policy: AllocationPolicyVersion) -> dict[str, object]:
    """Serialize one immutable policy version and its full governed content."""

    payload = allocation_policy_summary(policy)
    payload["entries"] = [_entry_payload(entry) for entry in policy.entries]
    payload["adjustments"] = [_adjustment_payload(adjustment) for adjustment in policy.adjustments]

    warnings: list[str] = []
    if policy.status is not AllocationPolicyStatus.ACTIVE:
        warnings.append("This version is not active and must not drive production decisions.")
    if any(entry.target.must_not_use_statistics_as_model_estimate for entry in policy.entries):
        warnings.append(
            "Unapproved statistics are assumptions and must not be presented as model estimates."
        )
    payload["warnings"] = warnings
    return payload


def _entry_payload(entry: AllocationPolicyEntry) -> dict[str, object]:
    """Serialize one matrix cell without changing its fractional weight units."""

    target = entry.target
    return {
        "regime": entry.regime.value,
        "risk_profile": entry.risk_profile.value,
        "allocation": {
            "equity": target.allocation.equity,
            "fixed_income": target.allocation.fixed_income,
            "commodity": target.allocation.commodity,
            "cash": target.allocation.cash,
        },
        "reasoning": target.reasoning,
        "expected_return": target.expected_return,
        "expected_volatility": target.expected_volatility,
        "sharpe_ratio": target.sharpe_ratio,
        "statistics_status": target.statistics_status.value,
        "research_evidence_id": target.research_evidence_id,
        "must_not_use_statistics_as_model_estimate": (
            target.must_not_use_statistics_as_model_estimate
        ),
    }


def _adjustment_payload(
    adjustment: PolicyAllocationAdjustment,
) -> dict[str, object]:
    """Serialize one policy-gear adjustment."""

    return {
        "policy_level": adjustment.policy_level.value,
        "equity_multiplier": adjustment.equity_multiplier,
        "expected_return_multiplier": adjustment.expected_return_multiplier,
        "expected_volatility_multiplier": adjustment.expected_volatility_multiplier,
        "sharpe_multiplier": adjustment.sharpe_multiplier,
    }
