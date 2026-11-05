"""Canonical serializer boundaries for optional plan-order execution bindings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from apps.portfolio.application.transition_plan_lifecycle import (
    TransitionPlanOrderExecutionBinding,
)
from apps.simulated_trading.infrastructure.transition_plan_execution_snapshot import (
    decode_plan_execution_binding,
    encode_plan_execution_binding,
)


def _binding() -> TransitionPlanOrderExecutionBinding:
    """Build a typed binding whose original source offsets are explicit."""

    offset = timedelta(hours=8)
    return TransitionPlanOrderExecutionBinding(
        plan_id="plan-1",
        family_id="family-1",
        root_plan_id="plan-1",
        plan_version=1,
        revision_hash=sha256(b"revision").hexdigest(),
        order_ordinal=0,
        plan_order_binding_id=sha256(b"binding-id").hexdigest(),
        order_content_hash=sha256(b"order").hexdigest(),
        account_id=41,
        owner_user_id=23,
        action_attempt_key="attempt-1",
        asset_code="600036.SH",
        security_id="SSE:600036",
        asset_type="equity",
        classification_content_hash=sha256(b"classification").hexdigest(),
        side="sell",
        approved_quantity=100,
        approved_limit_price=None,
        quantity_unit="share",
        money_unit="CNY",
        plan_expires_at=datetime(2026, 11, 5, 18, 0, tzinfo=timezone(offset)),
    )


def test_roundtrip_preserves_exact_binding_and_plus_eight_clocks() -> None:
    binding = _binding()
    recorded_at = datetime(2026, 11, 5, 15, 5, tzinfo=binding.plan_expires_at.tzinfo)

    wrapper = encode_plan_execution_binding(binding=binding, revision_recorded_at=recorded_at)
    decoded_binding, decoded_recorded_at = decode_plan_execution_binding(wrapper)

    assert decoded_binding.to_payload() == binding.to_payload()
    assert decoded_binding.content_hash == binding.content_hash
    assert decoded_recorded_at.isoformat() == recorded_at.isoformat()
    assert decoded_recorded_at.utcoffset() == timedelta(hours=8)


def test_content_hash_and_unknown_fields_are_strictly_bound() -> None:
    binding = _binding()
    recorded_at = datetime(2026, 11, 5, 15, 5, tzinfo=binding.plan_expires_at.tzinfo)
    wrapper = encode_plan_execution_binding(binding=binding, revision_recorded_at=recorded_at)

    wrong_hash = dict(wrapper)
    wrong_hash["binding_content_hash"] = "0" * 64
    with pytest.raises(ValueError, match="binding digest"):
        decode_plan_execution_binding(wrong_hash)

    wrong_payload = dict(wrapper)
    inner = dict(wrapper["binding"])
    inner["action_attempt_key"] = "other-attempt"
    wrong_payload["binding"] = inner
    with pytest.raises(ValueError, match="canonical binding digest"):
        decode_plan_execution_binding(wrong_payload)

    extra = dict(wrapper)
    extra["is_active"] = True
    with pytest.raises(ValueError, match="unknown fields"):
        decode_plan_execution_binding(extra)


def test_plan_recorded_clock_must_precede_its_exact_expiry() -> None:
    binding = _binding()
    with pytest.raises(ValueError, match="TRANSITION_PLAN_EXECUTION_BINDING_INVALID"):
        encode_plan_execution_binding(
            binding=binding,
            revision_recorded_at=binding.plan_expires_at,
        )
