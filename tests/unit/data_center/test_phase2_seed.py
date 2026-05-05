"""Database-backed checks for Phase 2 indicator catalog seed data."""

import pytest

from apps.data_center.infrastructure.models import IndicatorCatalogModel, PublisherCatalogModel


@pytest.mark.django_db
def test_indicator_catalog_seed_contains_core_phase2_codes():
    codes = set(
        IndicatorCatalogModel.objects.filter(
            code__in=["CN_GDP", "CN_PMI", "CN_CPI", "CN_M2", "CN_SHIBOR"]
        ).values_list("code", flat=True)
    )

    assert codes == {"CN_GDP", "CN_PMI", "CN_CPI", "CN_M2", "CN_SHIBOR"}


@pytest.mark.django_db
def test_indicator_catalog_cutover_codes_exist_after_expansion():
    codes = set(
        IndicatorCatalogModel.objects.filter(
            code__in=[
                "CN_GDP_YOY",
                "CN_M2_YOY",
                "CN_DR007",
                "CN_PBOC_NET_INJECTION",
                "CN_FX_RESERVES",
            ]
        ).values_list("code", flat=True)
    )

    assert codes == {
        "CN_GDP_YOY",
        "CN_M2_YOY",
        "CN_DR007",
        "CN_PBOC_NET_INJECTION",
        "CN_FX_RESERVES",
    }


@pytest.mark.django_db
def test_indicator_catalog_seed_preserves_units_categories_and_period_types():
    gdp = IndicatorCatalogModel.objects.get(code="CN_GDP")
    gdp_yoy = IndicatorCatalogModel.objects.get(code="CN_GDP_YOY")
    m2 = IndicatorCatalogModel.objects.get(code="CN_M2")
    m2_yoy = IndicatorCatalogModel.objects.get(code="CN_M2_YOY")
    cpi = IndicatorCatalogModel.objects.get(code="CN_CPI")
    cpi_yoy = IndicatorCatalogModel.objects.get(code="CN_CPI_NATIONAL_YOY")
    ppi = IndicatorCatalogModel.objects.get(code="CN_PPI")
    ppi_yoy = IndicatorCatalogModel.objects.get(code="CN_PPI_YOY")
    retail = IndicatorCatalogModel.objects.get(code="CN_RETAIL_SALES")
    retail_yoy = IndicatorCatalogModel.objects.get(code="CN_RETAIL_SALES_YOY")
    fixed_investment = IndicatorCatalogModel.objects.get(code="CN_FIXED_INVESTMENT")
    fai_yoy = IndicatorCatalogModel.objects.get(code="CN_FAI_YOY")
    value_added = IndicatorCatalogModel.objects.get(code="CN_VALUE_ADDED")
    exports = IndicatorCatalogModel.objects.get(code="CN_EXPORTS")
    export_yoy = IndicatorCatalogModel.objects.get(code="CN_EXPORT_YOY")
    imports = IndicatorCatalogModel.objects.get(code="CN_IMPORTS")
    import_yoy = IndicatorCatalogModel.objects.get(code="CN_IMPORT_YOY")
    fx_reserves = IndicatorCatalogModel.objects.get(code="CN_FX_RESERVES")
    social_financing = IndicatorCatalogModel.objects.get(code="CN_SOCIAL_FINANCING")
    social_financing_yoy = IndicatorCatalogModel.objects.get(code="CN_SOCIAL_FINANCING_YOY")
    pmi = IndicatorCatalogModel.objects.get(code="CN_PMI")
    shibor = IndicatorCatalogModel.objects.get(code="CN_SHIBOR")

    assert gdp.default_unit == "亿元"
    assert gdp.default_period_type == "Q"
    assert gdp.category == "growth"
    assert gdp.name_cn == "GDP 国内生产总值累计值"
    assert "不是单季值" in gdp.description
    assert gdp.extra["series_semantics"] == "cumulative_level"
    assert gdp.extra["paired_indicator_code"] == "CN_GDP_YOY"
    assert gdp.extra["display_priority"] == 20

    assert gdp_yoy.default_unit == "%"
    assert gdp_yoy.default_period_type == "Q"
    assert gdp_yoy.category == "growth"
    assert "同比增速口径" in gdp_yoy.description
    assert gdp_yoy.extra["series_semantics"] == "yoy_rate"
    assert gdp_yoy.extra["paired_indicator_code"] == "CN_GDP"
    assert gdp_yoy.extra["display_priority"] == 120

    assert m2.name_cn == "M2 广义货币供应量余额"
    assert m2.extra["series_semantics"] == "balance_level"
    assert m2.extra["paired_indicator_code"] == "CN_M2_YOY"
    assert m2_yoy.extra["series_semantics"] == "yoy_rate"

    assert cpi.extra["series_semantics"] == "index_level"
    assert cpi.extra["paired_indicator_code"] == "CN_CPI_NATIONAL_YOY"
    assert cpi_yoy.extra["series_semantics"] == "yoy_rate"

    assert ppi.extra["series_semantics"] == "index_level"
    assert ppi.extra["paired_indicator_code"] == "CN_PPI_YOY"
    assert ppi_yoy.extra["series_semantics"] == "yoy_rate"

    assert retail.name_cn == "社会消费品零售总额当月值"
    assert retail.default_unit == "亿元"
    assert retail.extra["series_semantics"] == "monthly_level"
    assert retail.extra["paired_indicator_code"] == "CN_RETAIL_SALES_YOY"
    assert retail_yoy.extra["series_semantics"] == "yoy_rate"

    assert fixed_investment.default_unit == "亿元"
    assert fixed_investment.extra["series_semantics"] == "cumulative_level"
    assert fixed_investment.extra["paired_indicator_code"] == "CN_FAI_YOY"
    assert fai_yoy.extra["series_semantics"] == "yoy_rate"

    assert value_added.name_cn == "工业增加值同比增速"
    assert value_added.default_unit == "%"
    assert value_added.extra["series_semantics"] == "yoy_rate"

    assert exports.name_cn == "当月出口额"
    assert exports.default_unit == "亿美元"
    assert exports.extra["series_semantics"] == "monthly_level"
    assert exports.extra["paired_indicator_code"] == "CN_EXPORT_YOY"
    assert export_yoy.extra["series_semantics"] == "yoy_rate"

    assert imports.name_cn == "当月进口额"
    assert imports.default_unit == "亿美元"
    assert imports.extra["series_semantics"] == "monthly_level"
    assert imports.extra["paired_indicator_code"] == "CN_IMPORT_YOY"
    assert import_yoy.extra["series_semantics"] == "yoy_rate"

    assert fx_reserves.name_cn == "国家外汇储备余额"
    assert fx_reserves.default_unit == "亿美元"
    assert fx_reserves.extra["series_semantics"] == "balance_level"

    assert social_financing.name_cn == "社会融资规模增量"
    assert social_financing.default_unit == "亿元"
    assert social_financing.extra["series_semantics"] == "flow_level"
    assert social_financing.extra["paired_indicator_code"] == "CN_SOCIAL_FINANCING_YOY"
    assert social_financing_yoy.extra["series_semantics"] == "yoy_rate"

    assert pmi.default_unit == "指数"
    assert pmi.default_period_type == "M"
    assert pmi.category == "growth"

    assert cpi.default_unit == "指数"
    assert cpi.default_period_type == "M"
    assert cpi.category == "inflation"

    assert ppi.default_unit == "指数"
    assert ppi.default_period_type == "M"
    assert ppi.category == "inflation"

    assert m2.default_unit == "万亿元"
    assert m2.default_period_type == "M"
    assert m2.category == "money"

    assert shibor.default_unit == "%"
    assert shibor.default_period_type == "D"
    assert shibor.category == "money"


@pytest.mark.django_db
def test_indicator_catalog_seed_contains_runtime_schedule_and_period_override_metadata():
    gdp = IndicatorCatalogModel.objects.get(code="CN_GDP")
    exports = IndicatorCatalogModel.objects.get(code="CN_EXPORTS")
    bond_10y = IndicatorCatalogModel.objects.get(code="CN_BOND_10Y")
    power_gen = IndicatorCatalogModel.objects.get(code="CN_POWER_GEN")

    assert gdp.extra["schedule_frequency"] == "quarterly"
    assert gdp.extra["schedule_day_of_month"] == 20
    assert gdp.extra["schedule_release_months"] == [1, 4, 7, 10]
    assert gdp.extra["publication_lag_days"] == 20

    assert exports.extra["schedule_frequency"] == "monthly"
    assert exports.extra["schedule_day_of_month"] == 10
    assert exports.extra["publication_lag_days"] == 10

    assert bond_10y.extra["orm_period_type_override"] == "10Y"
    assert bond_10y.extra["domain_period_type_override"] == "D"

    assert power_gen.extra["orm_period_type_override"] == "M"
    assert power_gen.extra["domain_period_type_override"] == "M"


@pytest.mark.django_db
def test_indicator_catalog_seed_contains_governance_console_metadata():
    gdp = IndicatorCatalogModel.objects.get(code="CN_GDP")
    cpi_yoy = IndicatorCatalogModel.objects.get(code="CN_CPI_YOY")
    social_financing_yoy = IndicatorCatalogModel.objects.get(code="CN_SOCIAL_FINANCING_YOY")
    pmi = IndicatorCatalogModel.objects.get(code="CN_PMI")
    shibor = IndicatorCatalogModel.objects.get(code="CN_SHIBOR")
    bond_10y = IndicatorCatalogModel.objects.get(code="CN_BOND_10Y")
    dr007 = IndicatorCatalogModel.objects.get(code="CN_DR007")

    assert gdp.extra["governance_scope"] == "macro_console"
    assert gdp.extra["governance_sync_supported"] is True
    assert gdp.extra["governance_sync_source_type"] == "akshare"

    assert cpi_yoy.extra["governance_scope"] == "macro_compat_alias"
    assert cpi_yoy.extra["alias_of_indicator_code"] == "CN_CPI_NATIONAL_YOY"
    assert cpi_yoy.extra["governance_sync_supported"] is False

    assert social_financing_yoy.extra["governance_scope"] == "macro_console"
    assert social_financing_yoy.extra["governance_sync_supported"] is True
    assert social_financing_yoy.extra["governance_sync_source_type"] == "akshare"

    assert pmi.extra["governance_scope"] == "macro_console"
    assert pmi.extra["governance_sync_supported"] is True
    assert pmi.extra["governance_sync_source_type"] == "akshare"

    assert shibor.extra["governance_scope"] == "macro_console"
    assert shibor.extra["governance_sync_supported"] is True
    assert shibor.extra["governance_sync_source_type"] == "akshare"

    assert bond_10y.extra["governance_scope"] == "macro_console"
    assert bond_10y.extra["governance_sync_supported"] is True
    assert bond_10y.extra["governance_sync_source_type"] == "akshare"

    assert dr007.extra["governance_scope"] == "macro_console"
    assert dr007.extra["governance_sync_supported"] is True
    assert dr007.extra["governance_sync_source_type"] == "akshare"


@pytest.mark.django_db
def test_indicator_catalog_seed_contains_macro_provenance_metadata():
    export_yoy = IndicatorCatalogModel.objects.get(code="CN_EXPORT_YOY")
    social_financing_yoy = IndicatorCatalogModel.objects.get(code="CN_SOCIAL_FINANCING_YOY")
    shibor = IndicatorCatalogModel.objects.get(code="CN_SHIBOR")

    assert export_yoy.extra["provenance_class"] == "official"
    assert export_yoy.extra["publisher"] == "海关总署"
    assert export_yoy.extra["publisher_code"] == "GACC"
    assert export_yoy.extra["publisher_codes"] == ["GACC"]
    assert export_yoy.extra["access_channel"] == "akshare"

    assert social_financing_yoy.extra["provenance_class"] == "derived"
    assert social_financing_yoy.extra["publisher"] == "系统派生"
    assert social_financing_yoy.extra["publisher_code"] == "SYSTEM_DERIVED"
    assert social_financing_yoy.extra["publisher_codes"] == ["SYSTEM_DERIVED"]
    assert social_financing_yoy.extra["decision_grade_enabled"] is False
    assert social_financing_yoy.extra["upstream_indicator_codes"] == ["CN_SOCIAL_FINANCING"]
    assert "prior_flow_value > 0 guardrail" in social_financing_yoy.extra["derivation_method"]

    assert shibor.extra["provenance_class"] == "authoritative_third_party"
    assert shibor.extra["publisher"] == "全国银行间同业拆借中心"
    assert shibor.extra["publisher_code"] == "NIFC"
    assert shibor.extra["publisher_codes"] == ["NIFC"]


@pytest.mark.django_db
def test_publisher_catalog_seed_contains_canonical_institutions_and_aliases():
    pboc = PublisherCatalogModel.objects.get(code="PBOC")
    nbs = PublisherCatalogModel.objects.get(code="NBS")
    system_derived = PublisherCatalogModel.objects.get(code="SYSTEM_DERIVED")

    assert pboc.canonical_name == "中国人民银行"
    assert "中国人行" in pboc.aliases
    assert "人民银行" in pboc.aliases
    assert pboc.publisher_class == "government"

    assert nbs.canonical_name == "国家统计局"
    assert nbs.publisher_class == "government"

    assert system_derived.canonical_name == "系统派生"
    assert system_derived.publisher_class == "system"
