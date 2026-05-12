"""Enrich core macro indicators with canonical semantics metadata."""

from django.db import migrations

INDICATOR_UPDATES = {
    "CN_M2": {
        "name_cn": "M2 广义货币供应量余额",
        "description": "月度余额口径，反映货币总量存量，不是同比增速。判断货币扩张方向时应配合 CN_M2_YOY。",
        "extra": {
            "series_semantics": "balance_level",
            "paired_indicator_code": "CN_M2_YOY",
            "display_priority": 25,
        },
    },
    "CN_M2_YOY": {
        "name_cn": "M2同比增速",
        "description": "月度同比增速口径，用于观察货币扩张或收缩方向；与 CN_M2 余额口径配对使用。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "CN_M2",
            "display_priority": 125,
        },
    },
    "CN_CPI": {
        "name_cn": "CPI 居民消费价格指数",
        "description": "月度指数水平值口径，不是同比涨幅。判断通胀方向时应优先结合 CN_CPI_NATIONAL_YOY。",
        "extra": {
            "series_semantics": "index_level",
            "paired_indicator_code": "CN_CPI_NATIONAL_YOY",
            "display_priority": 15,
        },
    },
    "CN_CPI_YOY": {
        "name_cn": "CPI同比",
        "description": "月度同比增速口径，通常与 CPI 指数水平值配对观察。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "CN_CPI",
            "display_priority": 114,
        },
    },
    "CN_CPI_NATIONAL_YOY": {
        "name_cn": "全国CPI同比",
        "description": "月度同比增速口径，用于观察居民消费价格涨幅方向；与 CN_CPI 指数水平值配对使用。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "CN_CPI",
            "display_priority": 115,
        },
    },
    "CN_PPI": {
        "name_cn": "PPI 工业生产者出厂价格指数",
        "description": "月度指数水平值口径，不是同比涨幅。判断工业品价格方向时应优先结合 CN_PPI_YOY。",
        "extra": {
            "series_semantics": "index_level",
            "paired_indicator_code": "CN_PPI_YOY",
            "display_priority": 15,
        },
    },
    "CN_PPI_YOY": {
        "name_cn": "PPI同比",
        "description": "月度同比增速口径，用于观察工业品价格涨幅方向；与 CN_PPI 指数水平值配对使用。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "CN_PPI",
            "display_priority": 115,
        },
    },
    "CN_RETAIL_SALES": {
        "name_cn": "社会消费品零售总额当月值",
        "description": "月度当月值口径，单位亿元，不是同比增速。判断消费改善方向时应配合 CN_RETAIL_SALES_YOY。",
        "extra": {
            "series_semantics": "monthly_level",
            "paired_indicator_code": "CN_RETAIL_SALES_YOY",
            "display_priority": 30,
        },
    },
    "CN_RETAIL_SALES_YOY": {
        "name_cn": "社会消费品零售总额同比增速",
        "description": "月度同比增速口径，用于观察消费改善方向；与 CN_RETAIL_SALES 当月值口径配对使用。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "CN_RETAIL_SALES",
            "display_priority": 130,
        },
    },
    "CN_FIXED_INVESTMENT": {
        "name_cn": "固定资产投资累计值",
        "description": "月度累计值口径，单位亿元，不是同比增速。判断投资方向时应配合 CN_FAI_YOY。",
        "extra": {
            "series_semantics": "cumulative_level",
            "paired_indicator_code": "CN_FAI_YOY",
            "display_priority": 20,
        },
    },
    "CN_FAI_YOY": {
        "name_cn": "固定资产投资累计同比增速",
        "description": "月度累计同比增速口径，用于观察投资改善方向；与 CN_FIXED_INVESTMENT 累计值口径配对使用。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "CN_FIXED_INVESTMENT",
            "display_priority": 120,
        },
    },
    "CN_VALUE_ADDED": {
        "name_cn": "工业增加值同比增速",
        "description": "月度同比增速口径，当前 canonical 口径不是绝对值水平，而是工业增加值增长率。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "",
            "display_priority": 108,
        },
    },
    "CN_EXPORTS": {
        "name_cn": "出口同比增长",
        "description": "月度同比增速口径，反映出口变化方向，不是出口总额水平值。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "",
            "display_priority": 118,
        },
    },
    "CN_EXPORT_YOY": {
        "name_cn": "出口同比",
        "description": "月度同比增速口径，反映出口变化方向，不是出口总额水平值。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "",
            "display_priority": 118,
        },
    },
    "CN_IMPORTS": {
        "name_cn": "进口同比增长",
        "description": "月度同比增速口径，反映进口变化方向，不是进口总额水平值。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "",
            "display_priority": 118,
        },
    },
    "CN_IMPORT_YOY": {
        "name_cn": "进口同比",
        "description": "月度同比增速口径，反映进口变化方向，不是进口总额水平值。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "",
            "display_priority": 118,
        },
    },
    "CN_FX_RESERVES": {
        "name_cn": "国家外汇储备余额",
        "description": "月度期末余额口径，当前 canonical display unit 为亿美元，不是同比增速。",
        "extra": {
            "series_semantics": "balance_level",
            "paired_indicator_code": "",
            "display_priority": 35,
        },
    },
    "CN_SOCIAL_FINANCING": {
        "name_cn": "社会融资规模",
        "description": "月度规模值口径，单位亿元，不是同比增速。若接入同比口径，应与 CN_SOCIAL_FINANCING_YOY 配对观察。",
        "extra": {
            "series_semantics": "flow_level",
            "paired_indicator_code": "CN_SOCIAL_FINANCING_YOY",
            "display_priority": 28,
        },
    },
    "CN_SOCIAL_FINANCING_YOY": {
        "name_cn": "社会融资规模同比",
        "description": "月度同比增速口径，用于观察社融扩张方向；与 CN_SOCIAL_FINANCING 规模值口径配对使用。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "CN_SOCIAL_FINANCING",
            "display_priority": 128,
        },
    },
}


ORIGINAL_NAMES = {
    "CN_M2": "M2 广义货币供应量",
    "CN_M2_YOY": "M2同比增速",
    "CN_CPI": "CPI 居民消费价格指数",
    "CN_CPI_YOY": "CPI同比",
    "CN_CPI_NATIONAL_YOY": "全国CPI同比",
    "CN_PPI": "PPI 工业生产者出厂价格指数",
    "CN_PPI_YOY": "PPI同比",
    "CN_RETAIL_SALES": "社会消费品零售总额",
    "CN_RETAIL_SALES_YOY": "社会消费品零售总额同比",
    "CN_FIXED_INVESTMENT": "固定资产投资",
    "CN_FAI_YOY": "固定资产投资同比",
    "CN_VALUE_ADDED": "工业增加值",
    "CN_EXPORTS": "出口同比增长",
    "CN_EXPORT_YOY": "出口同比",
    "CN_IMPORTS": "进口同比增长",
    "CN_IMPORT_YOY": "进口同比",
    "CN_FX_RESERVES": "外汇储备",
    "CN_SOCIAL_FINANCING": "社会融资规模",
    "CN_SOCIAL_FINANCING_YOY": "社会融资规模同比",
}


def apply_semantics(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code, payload in INDICATOR_UPDATES.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        merged_extra = dict(indicator.extra or {})
        merged_extra.update(payload["extra"])
        indicator.name_cn = payload["name_cn"]
        indicator.description = payload["description"]
        indicator.extra = merged_extra
        indicator.save(update_fields=["name_cn", "description", "extra"])


def revert_semantics(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code, payload in INDICATOR_UPDATES.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        reverted_extra = dict(indicator.extra or {})
        for key in payload["extra"]:
            reverted_extra.pop(key, None)
        indicator.name_cn = ORIGINAL_NAMES.get(code, indicator.name_cn)
        indicator.description = ""
        indicator.extra = reverted_extra
        indicator.save(update_fields=["name_cn", "description", "extra"])


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0010_enrich_gdp_indicator_semantics"),
    ]

    operations = [
        migrations.RunPython(apply_semantics, revert_semantics),
    ]
