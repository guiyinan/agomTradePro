"""Behavioral coverage for database-driven financial configuration commands."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import CommandError, call_command


@pytest.mark.django_db
def test_audit_configuration_commands_are_idempotent_and_refreshable() -> None:
    """Audit defaults can be created, skipped, and refreshed without duplication."""
    from apps.audit.infrastructure.models import (
        ConfidenceConfigModel,
        IndicatorThresholdConfigModel,
    )

    output = StringIO()
    call_command("init_confidence_config", stdout=output)
    call_command("init_confidence_config", stdout=output)
    call_command("init_confidence_config", refresh=True, stdout=output)
    assert ConfidenceConfigModel._default_manager.filter(is_active=True).count() == 1
    assert "Updated existing confidence configuration" in output.getvalue()

    threshold_output = StringIO()
    call_command("init_indicator_thresholds", stdout=threshold_output)
    initial_count = IndicatorThresholdConfigModel._default_manager.count()
    call_command("init_indicator_thresholds", stdout=threshold_output)
    call_command("init_indicator_thresholds", refresh=True, stdout=threshold_output)
    assert initial_count > 20
    assert IndicatorThresholdConfigModel._default_manager.count() == initial_count
    assert "refreshed successfully" in threshold_output.getvalue()


@pytest.mark.django_db
def test_regime_threshold_commands_create_update_activate_and_reset() -> None:
    """Regime thresholds retain one active configuration across command workflows."""
    from apps.regime.infrastructure.models import (
        RegimeIndicatorThreshold,
        RegimeThresholdConfig,
    )

    output = StringIO()
    call_command("init_regime_thresholds", stdout=output)
    call_command("init_regime_thresholds", stdout=output)
    call_command(
        "set_regime_threshold",
        pmi=51.0,
        cpi_high=2.5,
        cpi_low=0.8,
        ppi_high=3.0,
        activate=True,
        stdout=output,
    )
    active = RegimeThresholdConfig._default_manager.get(is_active=True)
    pmi = RegimeIndicatorThreshold._default_manager.get(
        config=active,
        indicator_code="PMI",
    )
    assert (pmi.level_low, pmi.level_high) == (51.0, 51.0)
    assert "阈值已更新" in output.getvalue()

    call_command("init_regime_thresholds", reset=True, stdout=output)
    assert RegimeThresholdConfig._default_manager.filter(is_active=True).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "options",
    [
        {"pmi": float("nan")},
        {"cpi_low": 3.0, "cpi_high": 2.0},
        {"ppi_high": float("inf")},
    ],
)
def test_regime_threshold_command_rejects_nonfinite_or_inverted_values(options) -> None:
    with pytest.raises(CommandError):
        call_command("set_regime_threshold", **options, stdout=StringIO())


@pytest.mark.django_db
def test_regime_threshold_command_validates_partial_update_against_stored_bound() -> None:
    call_command("init_regime_thresholds", stdout=StringIO())

    with pytest.raises(CommandError, match="cpi-low must not exceed cpi-high"):
        call_command("set_regime_threshold", cpi_low=3.0, stdout=StringIO())


@pytest.mark.django_db
def test_position_rule_command_supports_dry_run_create_skip_and_force_update(
    django_user_model: type,
) -> None:
    """Position-rule initialization honors its dry-run and overwrite contracts."""
    from apps.strategy.infrastructure.models import (
        PositionManagementRuleModel,
        StrategyModel,
    )

    user = django_user_model.objects.create_user(
        username="position-rule-owner",
        password="test-password",
    )
    strategy = StrategyModel._default_manager.create(
        name="command-contract",
        strategy_type="rule_based",
        created_by=user.account_profile,
    )
    output = StringIO()
    call_command("init_position_rules", dry_run=True, stdout=output)
    assert not PositionManagementRuleModel._default_manager.exists()

    call_command("init_position_rules", stdout=output)
    rule = PositionManagementRuleModel._default_manager.get(strategy=strategy)
    assert rule.metadata["template"] == "atr_risk"

    call_command("init_position_rules", stdout=output)
    call_command(
        "init_position_rules",
        strategy_id=strategy.pk,
        template="breakout_trend",
        force=True,
        stdout=output,
    )
    rule.refresh_from_db()
    assert rule.metadata["template"] == "breakout_trend"
    assert "skipped=1" in output.getvalue()
