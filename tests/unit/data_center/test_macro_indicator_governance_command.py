"""Tests for the macro indicator governance initialization command."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.data_center.infrastructure.models import IndicatorCatalogModel


@pytest.mark.django_db
def test_init_macro_indicator_governance_repairs_metadata_for_target_codes():
    power_gen = IndicatorCatalogModel.objects.get(code="CN_POWER_GEN")
    power_gen.description = ""
    power_gen.extra = {}
    power_gen.save(update_fields=["description", "extra"])

    export_alias = IndicatorCatalogModel.objects.get(code="CN_EXPORT")
    export_alias.description = ""
    export_alias.extra = {}
    export_alias.save(update_fields=["description", "extra"])

    industrial_profit = IndicatorCatalogModel.objects.get(code="CN_INDUSTRIAL_PROFIT")
    industrial_profit.description = ""
    industrial_profit.extra = {}
    industrial_profit.save(update_fields=["description", "extra"])

    stdout = StringIO()
    call_command(
        "init_macro_indicator_governance",
        indicator_codes="CN_POWER_GEN,CN_EXPORT,CN_INDUSTRIAL_PROFIT",
        stdout=stdout,
    )

    power_gen.refresh_from_db()
    export_alias.refresh_from_db()
    industrial_profit.refresh_from_db()

    assert power_gen.extra["series_semantics"] == "monthly_level"
    assert power_gen.extra["chart_policy"] == "period_bar"
    assert "月度值作为发电量代理序列" in power_gen.description

    assert export_alias.extra["series_semantics"] == "monthly_level"
    assert export_alias.extra["paired_indicator_code"] == "CN_EXPORT_YOY"
    assert export_alias.extra["alias_of_indicator_code"] == "CN_EXPORTS"
    assert export_alias.extra["governance_scope"] == "macro_compat_alias"
    assert export_alias.extra["chart_policy"] == "period_bar"

    assert industrial_profit.extra["series_semantics"] == "cumulative_level"
    assert industrial_profit.extra["chart_policy"] == "yearly_reset_bar"
    assert industrial_profit.extra["chart_reset_frequency"] == "year"
    assert industrial_profit.extra["chart_segment_basis"] == "period_delta"
    assert industrial_profit.extra["regime_input_policy"] == "derive_required"
    assert industrial_profit.extra["pulse_input_policy"] == "derive_required"


@pytest.mark.django_db
def test_init_macro_indicator_governance_dry_run_leaves_rows_unchanged():
    pmi = IndicatorCatalogModel.objects.get(code="CN_PMI")
    pmi.description = ""
    pmi.extra = {}
    pmi.save(update_fields=["description", "extra"])

    call_command(
        "init_macro_indicator_governance",
        indicator_codes="CN_PMI",
        dry_run=True,
    )

    pmi.refresh_from_db()

    assert pmi.description == ""
    assert pmi.extra == {}


@pytest.mark.django_db
def test_init_macro_indicator_governance_strict_fails_for_unmapped_active_indicator():
    IndicatorCatalogModel.objects.create(
        code="TMP_MACRO_STRICT",
        name_cn="测试指标",
        name_en="Temporary Macro Strict",
        description="",
        default_unit="%",
        default_period_type="M",
        category="test",
        is_active=True,
        extra={},
    )

    with pytest.raises(CommandError):
        call_command("init_macro_indicator_governance", strict=True)
