"""Expand data_center macro indicator catalog coverage for macro cutover."""

from django.db import migrations


INDICATORS = [
    ("CN_GDP_YOY", "GDP同比增速", "GDP YoY", "%", "Q", "growth"),
    ("CN_M2_YOY", "M2同比增速", "M2 YoY", "%", "M", "money"),
    ("CN_DR007", "存款类机构7天期回购加权平均利率", "DR007", "%", "D", "money"),
    ("CN_PBOC_NET_INJECTION", "央行公开市场净投放", "PBOC Net Injection", "亿元", "D", "money"),
    ("CN_FX_RESERVES", "外汇储备", "FX Reserves", "亿美元", "M", "trade"),
    ("CN_EXPORT_YOY", "出口同比", "Export YoY", "%", "M", "trade"),
    ("CN_IMPORT_YOY", "进口同比", "Import YoY", "%", "M", "trade"),
    ("CN_SOCIAL_FINANCING_YOY", "社会融资规模同比", "Social Financing YoY", "%", "M", "financial"),
    ("CN_FAI_YOY", "固定资产投资同比", "Fixed Asset Investment YoY", "%", "M", "growth"),
    ("CN_REALESTATE_INVESTMENT_YOY", "房地产开发投资同比", "Real Estate Investment YoY", "%", "M", "growth"),
    ("CN_RETAIL_SALES_YOY", "社会消费品零售总额同比", "Retail Sales YoY", "%", "M", "growth"),
    ("CN_CPI_YOY", "CPI同比", "CPI YoY", "%", "M", "inflation"),
    ("CN_CPI_MOY", "CPI环比", "CPI MoM", "%", "M", "inflation"),
    ("CN_PMI_NEW_ORDER", "PMI新订单指数", "PMI New Orders", "指数", "M", "growth"),
    ("CN_PMI_INVENTORY", "PMI产成品库存指数", "PMI Inventory", "指数", "M", "growth"),
    ("CN_PMI_RAW_MAT", "PMI原材料库存指数", "PMI Raw Materials Inventory", "指数", "M", "growth"),
    ("CN_PMI_PURCHASE", "PMI采购量指数", "PMI Purchase Volume", "指数", "M", "growth"),
    ("CN_PMI_PRODUCTION", "PMI生产指数", "PMI Production", "指数", "M", "growth"),
    ("CN_PMI_EMPLOYMENT", "PMI从业人员指数", "PMI Employment", "指数", "M", "growth"),
    ("CN_BOND_10Y", "10年期国债收益率", "China 10Y Treasury Yield", "%", "D", "financial"),
    ("CN_BOND_5Y", "5年期国债收益率", "China 5Y Treasury Yield", "%", "D", "financial"),
    ("CN_BOND_2Y", "2年期国债收益率", "China 2Y Treasury Yield", "%", "D", "financial"),
    ("CN_BOND_1Y", "1年期国债收益率", "China 1Y Treasury Yield", "%", "D", "financial"),
    ("CN_TERM_SPREAD_10Y1Y", "期限利差(10Y-1Y)", "Term Spread 10Y-1Y", "%", "D", "financial"),
    ("CN_TERM_SPREAD_10Y2Y", "期限利差(10Y-2Y)", "Term Spread 10Y-2Y", "%", "D", "financial"),
    ("CN_CORP_YIELD_AAA", "AAA级企业债收益率", "AAA Corporate Bond Yield", "%", "D", "financial"),
    ("CN_CORP_YIELD_AA", "AA级企业债收益率", "AA Corporate Bond Yield", "%", "D", "financial"),
    ("CN_CREDIT_SPREAD", "信用利差(AA-AAA)", "Credit Spread AA-AAA", "%", "D", "financial"),
    ("CN_NHCI", "南华商品指数", "Nanhua Commodity Index", "指数", "D", "other"),
    ("CN_FX_CENTER", "人民币中间价", "CNY Central Parity", "", "D", "trade"),
    ("US_BOND_10Y", "美国10年期国债收益率", "US 10Y Treasury Yield", "%", "D", "financial"),
    ("USD_INDEX", "美元指数", "US Dollar Index", "指数", "D", "trade"),
    ("VIX_INDEX", "VIX波动率指数", "VIX Index", "指数", "D", "financial"),
    ("CN_POWER_GEN", "发电量", "Power Generation", "%", "W", "growth"),
    ("CN_BLAST_FURNACE", "高炉开工率", "Blast Furnace Utilization", "%", "W", "growth"),
    ("CN_CCFI", "中国出口集装箱运价指数", "CCFI", "指数", "W", "trade"),
    ("CN_SCFI", "上海出口集装箱运价指数", "SCFI", "指数", "W", "trade"),
]


def seed_indicator_coverage(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")

    legacy_fx = IndicatorCatalog.objects.filter(code="CN_FX_RESERVE").first()
    plural_fx = IndicatorCatalog.objects.filter(code="CN_FX_RESERVES").first()
    if legacy_fx and plural_fx is None:
        legacy_fx.code = "CN_FX_RESERVES"
        legacy_fx.name_cn = "外汇储备"
        legacy_fx.name_en = "FX Reserves"
        legacy_fx.default_unit = "亿美元"
        legacy_fx.default_period_type = "M"
        legacy_fx.category = "trade"
        legacy_fx.is_active = True
        legacy_fx.save()
    elif legacy_fx and plural_fx:
        legacy_fx.is_active = False
        legacy_fx.save(update_fields=["is_active"])

    for code, name_cn, name_en, unit, period_type, category in INDICATORS:
        IndicatorCatalog.objects.update_or_create(
            code=code,
            defaults={
                "name_cn": name_cn,
                "name_en": name_en,
                "default_unit": unit,
                "default_period_type": period_type,
                "category": category,
                "is_active": True,
            },
        )


def unseed_indicator_coverage(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    codes = [row[0] for row in INDICATORS]
    IndicatorCatalog.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0006_drop_legacy_month_start_duplicates"),
    ]

    operations = [
        migrations.RunPython(
            seed_indicator_coverage,
            reverse_code=unseed_indicator_coverage,
        ),
    ]
