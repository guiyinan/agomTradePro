"""Seed runtime macro scheduling and publication metadata into IndicatorCatalog.extra."""

from django.db import migrations

RUNTIME_EXTRA_UPDATES = {
    "CN_PMI": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 1,
        "publication_lag_days": 1,
        "publication_lag_description": "PMI 次月1日发布",
    },
    "CN_NON_MAN_PMI": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 1,
        "publication_lag_days": 1,
        "publication_lag_description": "非制造业PMI 次月1日发布",
    },
    "CN_CPI": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "CPI 月后10日左右发布",
    },
    "CN_CPI_NATIONAL_YOY": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "全国CPI同比 月后10日左右发布",
    },
    "CN_CPI_NATIONAL_MOM": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "全国CPI环比 月后10日左右发布",
    },
    "CN_CPI_URBAN_YOY": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "城市CPI同比 月后10日左右发布",
    },
    "CN_CPI_URBAN_MOM": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "城市CPI环比 月后10日左右发布",
    },
    "CN_CPI_RURAL_YOY": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "农村CPI同比 月后10日左右发布",
    },
    "CN_CPI_RURAL_MOM": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "农村CPI环比 月后10日左右发布",
    },
    "CN_PPI": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "PPI 月后10日左右发布",
    },
    "CN_PPI_YOY": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "PPI同比 月后10日左右发布",
    },
    "CN_M2": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 15,
        "publication_lag_days": 15,
        "publication_lag_description": "M2 月后10-15日发布",
    },
    "CN_M2_YOY": {
        "publication_lag_days": 15,
        "publication_lag_description": "M2同比 月后10-15日发布",
    },
    "CN_VALUE_ADDED": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 15,
        "publication_lag_days": 10,
        "publication_lag_description": "工业增加值 月后10日左右",
    },
    "CN_RETAIL_SALES": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 15,
        "publication_lag_days": 10,
        "publication_lag_description": "社零 月后10日左右",
    },
    "CN_RETAIL_SALES_YOY": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 15,
        "publication_lag_days": 10,
        "publication_lag_description": "社零同比 月后10日左右",
    },
    "CN_FIXED_INVESTMENT": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 15,
        "publication_lag_days": 15,
        "publication_lag_description": "固定资产投资 月后15日左右发布",
    },
    "CN_FAI_YOY": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 15,
        "publication_lag_days": 15,
        "publication_lag_description": "固定资产投资同比 月后15日左右发布",
    },
    "CN_GDP": {
        "schedule_frequency": "quarterly",
        "schedule_day_of_month": 20,
        "schedule_release_months": [1, 4, 7, 10],
        "publication_lag_days": 20,
        "publication_lag_description": "GDP 季后20日左右发布",
    },
    "CN_GDP_YOY": {
        "schedule_frequency": "quarterly",
        "schedule_day_of_month": 20,
        "schedule_release_months": [1, 4, 7, 10],
        "publication_lag_days": 20,
        "publication_lag_description": "GDP同比 季后20日左右发布",
    },
    "CN_SHIBOR": {
        "schedule_frequency": "daily",
        "publication_lag_days": 0,
        "publication_lag_description": "SHIBOR 每日发布",
    },
    "CN_EXPORTS": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "出口数据 月后10日左右发布",
    },
    "CN_EXPORT_YOY": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "出口同比 月后10日左右发布",
    },
    "CN_IMPORTS": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "进口数据 月后10日左右发布",
    },
    "CN_IMPORT_YOY": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "进口同比 月后10日左右发布",
    },
    "CN_TRADE_BALANCE": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "贸易差额 月后10日左右发布",
    },
    "CN_UNEMPLOYMENT": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 15,
        "publication_lag_days": 15,
        "publication_lag_description": "城镇调查失业率 月后15日左右发布",
    },
    "CN_FX_RESERVES": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 10,
        "publication_lag_days": 10,
        "publication_lag_description": "外汇储备 月后10日左右发布",
    },
    "CN_LPR": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 20,
        "publication_lag_days": 1,
        "publication_lag_description": "LPR 每月20日发布",
    },
    "CN_RRR": {
        "schedule_frequency": "daily",
        "publication_lag_days": 0,
        "publication_lag_description": "存款准备金率 不定期调整",
    },
    "CN_NEW_HOUSE_PRICE": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 15,
        "publication_lag_days": 15,
        "publication_lag_description": "新房价格指数 月后15日左右发布",
    },
    "CN_OIL_PRICE": {
        "schedule_frequency": "daily",
        "publication_lag_days": 0,
        "publication_lag_description": "成品油价格 不定期调整",
    },
    "CN_NEW_CREDIT": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 15,
        "publication_lag_days": 15,
        "publication_lag_description": "新增信贷 月后10-15日发布",
    },
    "CN_RMB_DEPOSIT": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 15,
        "publication_lag_days": 15,
        "publication_lag_description": "人民币存款 月后10-15日发布",
    },
    "CN_RMB_LOAN": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 15,
        "publication_lag_days": 15,
        "publication_lag_description": "人民币贷款 月后10-15日发布",
    },
    "CN_SOCIAL_FINANCING": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 15,
        "publication_lag_days": 15,
        "publication_lag_description": "社会融资规模 月后10-15日左右发布",
    },
    "CN_SOCIAL_FINANCING_YOY": {
        "schedule_frequency": "monthly",
        "schedule_day_of_month": 15,
        "publication_lag_days": 15,
        "publication_lag_description": "社会融资规模同比 月后10-15日左右发布",
    },
    "CN_BOND_10Y": {
        "orm_period_type_override": "10Y",
        "domain_period_type_override": "D",
    },
    "CN_BOND_5Y": {
        "orm_period_type_override": "5Y",
        "domain_period_type_override": "D",
    },
    "CN_BOND_2Y": {
        "orm_period_type_override": "2Y",
        "domain_period_type_override": "D",
    },
    "CN_BOND_1Y": {
        "orm_period_type_override": "1Y",
        "domain_period_type_override": "D",
    },
    "CN_TERM_SPREAD_10Y1Y": {
        "orm_period_type_override": "D",
        "domain_period_type_override": "D",
    },
    "CN_TERM_SPREAD_10Y2Y": {
        "orm_period_type_override": "D",
        "domain_period_type_override": "D",
    },
    "CN_CORP_YIELD_AAA": {
        "orm_period_type_override": "10Y",
        "domain_period_type_override": "D",
    },
    "CN_CORP_YIELD_AA": {
        "orm_period_type_override": "10Y",
        "domain_period_type_override": "D",
    },
    "CN_CREDIT_SPREAD": {
        "orm_period_type_override": "D",
        "domain_period_type_override": "D",
    },
    "CN_NHCI": {
        "orm_period_type_override": "W",
        "domain_period_type_override": "W",
    },
    "CN_FX_CENTER": {
        "orm_period_type_override": "D",
        "domain_period_type_override": "D",
    },
    "US_BOND_10Y": {
        "orm_period_type_override": "10Y",
        "domain_period_type_override": "D",
    },
    "USD_INDEX": {
        "orm_period_type_override": "D",
        "domain_period_type_override": "D",
    },
    "VIX_INDEX": {
        "orm_period_type_override": "D",
        "domain_period_type_override": "D",
    },
    "CN_POWER_GEN": {
        "orm_period_type_override": "M",
        "domain_period_type_override": "M",
    },
    "CN_BLAST_FURNACE": {
        "orm_period_type_override": "W",
        "domain_period_type_override": "W",
    },
    "CN_CCFI": {
        "orm_period_type_override": "W",
        "domain_period_type_override": "W",
    },
    "CN_SCFI": {
        "orm_period_type_override": "W",
        "domain_period_type_override": "W",
    },
    "CN_PMI_NEW_ORDER": {
        "orm_period_type_override": "M",
        "domain_period_type_override": "M",
    },
    "CN_PMI_INVENTORY": {
        "orm_period_type_override": "M",
        "domain_period_type_override": "M",
    },
    "CN_PMI_RAW_MAT": {
        "orm_period_type_override": "M",
        "domain_period_type_override": "M",
    },
    "CN_PMI_PURCHASE": {
        "orm_period_type_override": "M",
        "domain_period_type_override": "M",
    },
    "CN_PMI_PRODUCTION": {
        "orm_period_type_override": "M",
        "domain_period_type_override": "M",
    },
    "CN_PMI_EMPLOYMENT": {
        "orm_period_type_override": "M",
        "domain_period_type_override": "M",
    },
}


def apply_runtime_metadata(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code, extra_updates in RUNTIME_EXTRA_UPDATES.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        extra = dict(indicator.extra or {})
        extra.update(extra_updates)
        indicator.extra = extra
        indicator.save(update_fields=["extra"])


def revert_runtime_metadata(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code, extra_updates in RUNTIME_EXTRA_UPDATES.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        extra = dict(indicator.extra or {})
        for key in extra_updates:
            extra.pop(key, None)
        indicator.extra = extra
        indicator.save(update_fields=["extra"])


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0014_correct_trade_and_financing_semantics"),
    ]

    operations = [
        migrations.RunPython(apply_runtime_metadata, revert_runtime_metadata),
    ]
