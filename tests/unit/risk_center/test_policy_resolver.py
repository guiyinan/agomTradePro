from datetime import UTC, datetime, timedelta

from apps.risk_center.domain.entities import (
    AccountRiskPolicy,
    GlobalRiskFloor,
    RiskException,
    RiskParameters,
    RiskProfile,
    RiskTemplate,
)
from apps.risk_center.domain.services import RiskPolicyResolver, fallback_template_for_profile


def test_account_policy_inherits_template_and_overrides_selected_fields():
    template = fallback_template_for_profile(RiskProfile.MODERATE)
    policy = AccountRiskPolicy(
        account_id=1,
        template_key=template.key,
        overrides=RiskParameters(max_single_position_pct=0.22),
    )

    resolved = RiskPolicyResolver().resolve(
        account_id=1,
        floor=None,
        template=template,
        account_policy=policy,
    )

    assert resolved.parameters.max_total_position_pct == 0.8
    assert resolved.parameters.max_single_position_pct == 0.22
    assert resolved.sources["max_total_position_pct"] == "template:moderate"
    assert resolved.sources["max_single_position_pct"] == "account_policy"


def test_global_floor_clamps_account_policy_to_stricter_limits():
    template = fallback_template_for_profile(RiskProfile.AGGRESSIVE)
    policy = AccountRiskPolicy(
        account_id=1,
        template_key=template.key,
        overrides=RiskParameters(max_total_position_pct=0.98, min_cash_pct=0.01),
    )
    floor = GlobalRiskFloor(
        parameters=RiskParameters(max_total_position_pct=0.75, min_cash_pct=0.12),
        is_active=True,
    )

    resolved = RiskPolicyResolver().resolve(
        account_id=1,
        floor=floor,
        template=template,
        account_policy=policy,
    )

    assert resolved.parameters.max_total_position_pct == 0.75
    assert resolved.parameters.min_cash_pct == 0.12
    assert {item["field"] for item in resolved.floor_applied} == {
        "max_total_position_pct",
        "min_cash_pct",
    }


def test_active_exception_allows_temporary_floor_breakthrough():
    now = datetime.now(UTC)
    template = fallback_template_for_profile(RiskProfile.AGGRESSIVE)
    floor = GlobalRiskFloor(
        parameters=RiskParameters(max_total_position_pct=0.75),
        is_active=True,
    )
    exception = RiskException(
        account_id=1,
        field_name="max_total_position_pct",
        allowed_value=0.9,
        reason="temporary hedge unwind",
        created_by="admin",
        expires_at=now + timedelta(hours=1),
    )

    resolved = RiskPolicyResolver().resolve(
        account_id=1,
        floor=floor,
        template=template,
        exceptions=[exception],
        resolved_at=now,
    )

    assert resolved.parameters.max_total_position_pct == 0.9
    assert resolved.exceptions_applied[0]["field"] == "max_total_position_pct"
    assert resolved.floor_applied == []


def test_expired_exception_no_longer_overrides_floor():
    now = datetime.now(UTC)
    template = RiskTemplate(
        key="custom",
        name="Custom",
        risk_profile=RiskProfile.CUSTOM,
        parameters=RiskParameters(max_total_position_pct=0.9),
    )
    floor = GlobalRiskFloor(
        parameters=RiskParameters(max_total_position_pct=0.7),
        is_active=True,
    )
    exception = RiskException(
        account_id=1,
        field_name="max_total_position_pct",
        allowed_value=0.9,
        reason="expired",
        created_by="admin",
        expires_at=now - timedelta(seconds=1),
    )

    resolved = RiskPolicyResolver().resolve(
        account_id=1,
        floor=floor,
        template=template,
        exceptions=[exception],
        resolved_at=now,
    )

    assert resolved.parameters.max_total_position_pct == 0.7
    assert resolved.exceptions_applied == []


def test_missing_account_policy_uses_moderate_template_fallback():
    template = fallback_template_for_profile(None)

    resolved = RiskPolicyResolver().resolve(account_id=1, floor=None, template=template)

    assert resolved.template_key == "moderate"
    assert resolved.risk_profile == RiskProfile.MODERATE
    assert resolved.parameters.max_total_position_pct == 0.8
