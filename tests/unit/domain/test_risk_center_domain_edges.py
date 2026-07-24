"""Exception and global-floor boundaries for the Risk Center Domain."""

from datetime import UTC, datetime, timedelta

from apps.risk_center.domain.entities import (
    AccountRiskPolicy,
    GlobalRiskFloor,
    ResolvedRiskPolicy,
    RiskException,
    RiskParameters,
    RiskProfile,
    RiskTemplate,
)
from apps.risk_center.domain.services import (
    RiskPolicyResolver,
    fallback_template_for_profile,
    with_template_key,
)


def _exception(
    field_name: str,
    allowed_value: object,
    *,
    now: datetime,
) -> RiskException:
    """Build an active account exception."""
    return RiskException(
        account_id=1,
        field_name=field_name,
        allowed_value=allowed_value,
        reason=f"temporary {field_name}",
        created_by="risk-admin",
        expires_at=now + timedelta(hours=1),
    )


def test_floor_applies_cash_stop_loss_and_hard_exclusions() -> None:
    """Non-limit floor fields remain mandatory without an exception."""
    template = RiskTemplate(
        key="custom",
        name="Custom",
        risk_profile=RiskProfile.CUSTOM,
        parameters=RiskParameters(
            min_cash_pct=0.01,
            force_stop_loss=False,
            hard_exclusions=("ST",),
        ),
    )
    floor = GlobalRiskFloor(
        parameters=RiskParameters(
            min_cash_pct=0.15,
            force_stop_loss=True,
            hard_exclusions=("delisted",),
        )
    )
    resolved = RiskPolicyResolver().resolve(
        account_id=1,
        floor=floor,
        template=template,
    )

    assert resolved.parameters.min_cash_pct == 0.15
    assert resolved.parameters.force_stop_loss is True
    assert resolved.parameters.hard_exclusions == ("ST", "delisted")
    assert {item["field"] for item in resolved.floor_applied} == {
        "min_cash_pct",
        "force_stop_loss",
        "hard_exclusions",
    }


def test_active_exceptions_bound_cash_stop_loss_and_exclusions() -> None:
    """Exceptions replace a specific floor without disabling other controls."""
    now = datetime(2026, 7, 24, tzinfo=UTC)
    template = RiskTemplate(
        key="custom",
        name="Custom",
        risk_profile=RiskProfile.CUSTOM,
        parameters=RiskParameters(
            min_cash_pct=0.01,
            force_stop_loss=False,
            hard_exclusions=("ST",),
        ),
    )
    floor = GlobalRiskFloor(
        parameters=RiskParameters(
            min_cash_pct=0.15,
            force_stop_loss=True,
            hard_exclusions=("delisted",),
        )
    )
    exceptions = [
        _exception("min_cash_pct", 0.05, now=now),
        _exception("force_stop_loss", False, now=now),
        _exception("hard_exclusions", ["watch"], now=now),
    ]
    resolved = RiskPolicyResolver().resolve(
        account_id=1,
        floor=floor,
        template=template,
        exceptions=exceptions,
        resolved_at=now,
    )

    assert resolved.parameters.min_cash_pct == 0.05
    assert resolved.parameters.force_stop_loss is False
    assert resolved.parameters.hard_exclusions == ("watch",)
    assert {item["field"] for item in resolved.exceptions_applied} == {
        "min_cash_pct",
        "force_stop_loss",
        "hard_exclusions",
    }


def test_invalid_numeric_exception_cannot_crash_or_expand_requested_limit() -> None:
    """Malformed exception values preserve the requested value for audit."""
    now = datetime(2026, 7, 24, tzinfo=UTC)
    template = RiskTemplate(
        key="custom",
        name="Custom",
        risk_profile=RiskProfile.CUSTOM,
        parameters=RiskParameters(
            max_total_position_pct=0.9,
            min_cash_pct=0.01,
        ),
    )
    floor = GlobalRiskFloor(
        parameters=RiskParameters(
            max_total_position_pct=0.7,
            min_cash_pct=0.15,
        )
    )
    resolved = RiskPolicyResolver().resolve(
        account_id=1,
        floor=floor,
        template=template,
        exceptions=[
            _exception("max_total_position_pct", "bad", now=now),
            _exception("min_cash_pct", "bad", now=now),
        ],
        resolved_at=now,
    )
    assert resolved.parameters.max_total_position_pct == 0.9
    assert resolved.parameters.min_cash_pct == 0.01


def test_inactive_policy_floor_and_exception_do_not_change_template() -> None:
    """Inactive configuration is ignored rather than partly applied."""
    now = datetime(2026, 7, 24, tzinfo=UTC)
    template = fallback_template_for_profile(RiskProfile.MODERATE)
    policy = AccountRiskPolicy(
        account_id=1,
        risk_profile=RiskProfile.AGGRESSIVE,
        overrides=RiskParameters(max_total_position_pct=0.99),
        is_active=False,
    )
    exception = RiskException(
        field_name="max_total_position_pct",
        allowed_value=0.99,
        reason="inactive",
        created_by="admin",
        expires_at=now + timedelta(hours=1),
        is_active=False,
    )
    resolved = RiskPolicyResolver().resolve(
        account_id=1,
        floor=GlobalRiskFloor(
            RiskParameters(max_total_position_pct=0.5),
            is_active=False,
        ),
        template=template,
        account_policy=policy,
        exceptions=[exception],
        resolved_at=now,
    )
    assert resolved.parameters.max_total_position_pct == 0.8
    assert resolved.risk_profile == RiskProfile.MODERATE
    assert resolved.floor_applied == []
    assert exception.is_valid_at(now) is False


def test_fallback_profiles_template_key_and_serialization() -> None:
    """Each declared profile has stable defaults and an auditable payload."""
    conservative = fallback_template_for_profile("conservative")
    aggressive = fallback_template_for_profile(RiskProfile.AGGRESSIVE)
    moderate = fallback_template_for_profile("unknown")
    assert conservative.parameters.max_total_position_pct == 0.65
    assert aggressive.parameters.max_total_position_pct == 0.9
    assert moderate.risk_profile == RiskProfile.MODERATE
    assert with_template_key(moderate, None) is moderate
    assert with_template_key(moderate, "renamed").key == "renamed"

    parameters = RiskParameters.from_mapping(
        {"hard_exclusions": [1, "ST"], "force_stop_loss": True}
    )
    assert parameters.hard_exclusions == ("1", "ST")
    assert RiskParameters.from_mapping(None) == RiskParameters()

    resolved = ResolvedRiskPolicy(
        account_id=1,
        parameters=parameters,
        template_key="moderate",
        risk_profile=RiskProfile.MODERATE,
        sources={"force_stop_loss": "template:moderate"},
        floor_applied=[],
        exceptions_applied=[],
        warnings=["review"],
    )
    assert resolved.to_dict()["risk_profile"] == "moderate"
    assert resolved.to_dict()["warnings"] == ["review"]
