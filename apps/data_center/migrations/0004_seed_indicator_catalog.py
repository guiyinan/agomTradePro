# Generated seed migration for IndicatorCatalogModel
# Seeds all canonical macro indicator definitions used by the data center.

from django.db import migrations


INDICATORS = [
    # code, name_cn, name_en, default_unit, default_period_type, category
    ("CN_GDP",            "GDP 国内生产总值",                   "GDP",                       "亿元", "Q", "growth"),
    ("CN_PMI",            "PMI 制造业采购经理指数",             "Manufacturing PMI",         "指数", "M", "growth"),
    ("CN_NON_MAN_PMI",    "非制造业PMI",                        "Non-Manufacturing PMI",     "指数", "M", "growth"),
    ("CN_VALUE_ADDED",    "工业增加值",                         "Industrial Value Added",    "%",   "M", "growth"),
    ("CN_RETAIL_SALES",   "社会消费品零售总额",                  "Retail Sales",              "亿元", "M", "growth"),
    ("CN_FIXED_INVESTMENT","固定资产投资",                       "Fixed Asset Investment",    "亿元", "M", "growth"),
    ("CN_INDUSTRIAL_PROFIT","工业企业利润",                     "Industrial Profit",         "亿元", "M", "growth"),
    ("CN_CPI",            "CPI 居民消费价格指数",               "CPI",                       "指数", "M", "inflation"),
    ("CN_CPI_NATIONAL_YOY","全国CPI同比",                       "CPI YoY National",         "%",   "M", "inflation"),
    ("CN_CPI_NATIONAL_MOM","全国CPI环比",                       "CPI MoM National",         "%",   "M", "inflation"),
    ("CN_CPI_URBAN_YOY",  "城市CPI同比",                        "CPI YoY Urban",            "%",   "M", "inflation"),
    ("CN_CPI_URBAN_MOM",  "城市CPI环比",                        "CPI MoM Urban",            "%",   "M", "inflation"),
    ("CN_CPI_RURAL_YOY",  "农村CPI同比",                        "CPI YoY Rural",            "%",   "M", "inflation"),
    ("CN_CPI_RURAL_MOM",  "农村CPI环比",                        "CPI MoM Rural",            "%",   "M", "inflation"),
    ("CN_CPI_FOOD",       "CPI 食品价格",                       "CPI Food",                 "%",   "M", "inflation"),
    ("CN_CPI_CORE",       "CPI 核心CPI",                        "Core CPI",                 "%",   "M", "inflation"),
    ("CN_PPI",            "PPI 工业生产者出厂价格指数",         "PPI",                       "指数", "M", "inflation"),
    ("CN_PPI_YOY",        "PPI同比",                            "PPI YoY",                  "%",   "M", "inflation"),
    ("CN_PPIRM",          "PPIRM 生产资料价格指数",             "PPIRM",                     "%",   "M", "inflation"),
    ("CN_M0",             "M0 流通中现金",                      "M0 Currency in Circulation","亿元", "M", "money"),
    ("CN_M1",             "M1 狭义货币供应量",                  "M1 Narrow Money",          "亿元", "M", "money"),
    ("CN_M2",             "M2 广义货币供应量",                  "M2 Broad Money",           "万亿元", "M", "money"),
    ("CN_SHIBOR",         "SHIBOR 上海银行间同业拆放利率",       "SHIBOR",                   "%",   "D", "money"),
    ("CN_LPR",            "LPR 贷款市场报价利率",               "LPR",                      "%",   "M", "money"),
    ("CN_RRR",            "存款准备金率",                        "Reserve Requirement Ratio","%" ,  "M", "money"),
    ("CN_LOAN_RATE",      "贷款利率",                            "Lending Rate",             "%",   "M", "money"),
    ("CN_RESERVE_RATIO",  "存款准备金率（银行）",                "Reserve Ratio",            "%",   "M", "money"),
    ("CN_REVERSE_REPO",   "逆回购利率",                          "Reverse Repo Rate",        "%",   "D", "money"),
    ("CN_EXPORT",         "出口额",                              "Exports",                  "亿美元","M","trade"),
    ("CN_IMPORT",         "进口额",                              "Imports",                  "亿美元","M","trade"),
    ("CN_EXPORTS",        "出口同比增长",                        "Exports YoY",             "%",   "M", "trade"),
    ("CN_IMPORTS",        "进口同比增长",                        "Imports YoY",             "%",   "M", "trade"),
    ("CN_TRADE_BALANCE",  "贸易差额",                            "Trade Balance",            "亿美元","M","trade"),
    ("CN_FX_RESERVE",     "外汇储备",                            "FX Reserves",              "亿美元","M","trade"),
    ("CN_NEW_CREDIT",     "新增信贷",                            "New Credit",               "亿元", "M", "financial"),
    ("CN_RMB_DEPOSIT",    "人民币存款",                          "RMB Deposits",             "亿元", "M", "financial"),
    ("CN_RMB_LOAN",       "人民币贷款",                          "RMB Loans",                "亿元", "M", "financial"),
    ("CN_SOCIAL_FINANCING","社会融资规模",                       "Total Social Financing",   "亿元", "M", "financial"),
    ("CN_BOND_ISSUANCE",  "债券发行",                            "Bond Issuance",            "亿元", "M", "financial"),
    ("CN_STOCK_MARKET_CAP","股票市值",                           "Stock Market Cap",         "亿元", "M", "financial"),
    ("CN_NEW_HOUSE_PRICE","新房价格指数",                        "New House Price Index",    "%",   "M", "other"),
    ("CN_OIL_PRICE",      "成品油价格",                          "Oil Price",                "元/升","M","other"),
    ("CN_UNEMPLOYMENT",   "城镇调查失业率",                      "Urban Unemployment Rate",  "%",   "M", "other"),
]


def seed_indicators(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for row in INDICATORS:
        code, name_cn, name_en, unit, period_type, category = row
        IndicatorCatalog.objects.get_or_create(
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


def unseed_indicators(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    codes = [row[0] for row in INDICATORS]
    IndicatorCatalog.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0003_phase2_master_facts"),
    ]

    operations = [
        migrations.RunPython(seed_indicators, reverse_code=unseed_indicators),
    ]
