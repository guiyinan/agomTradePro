"""Create publisher catalog and backfill macro provenance publisher codes."""

from django.db import migrations, models


PUBLISHERS = {
    "NBS": {
        "canonical_name": "国家统计局",
        "canonical_name_en": "National Bureau of Statistics of China",
        "publisher_class": "government",
        "aliases": ["国家统计局", "统计局", "NBS"],
        "country_code": "CN",
        "website": "",
        "is_active": True,
        "description": "国家统计口径发布机构",
    },
    "CFLP": {
        "canonical_name": "中国物流与采购联合会",
        "canonical_name_en": "China Federation of Logistics & Purchasing",
        "publisher_class": "association",
        "aliases": ["中物联", "物流与采购联合会", "CFLP"],
        "country_code": "CN",
        "website": "",
        "is_active": True,
        "description": "PMI 等联合发布机构",
    },
    "GACC": {
        "canonical_name": "海关总署",
        "canonical_name_en": "General Administration of Customs of China",
        "publisher_class": "government",
        "aliases": ["中国海关", "海关总署", "GACC"],
        "country_code": "CN",
        "website": "",
        "is_active": True,
        "description": "进出口统计发布机构",
    },
    "PBOC": {
        "canonical_name": "中国人民银行",
        "canonical_name_en": "People's Bank of China",
        "publisher_class": "government",
        "aliases": ["人民银行", "中国人行", "央行", "中国人民银行", "PBOC"],
        "country_code": "CN",
        "website": "",
        "is_active": True,
        "description": "货币金融与社融官方发布机构",
    },
    "SAFE": {
        "canonical_name": "国家外汇管理局",
        "canonical_name_en": "State Administration of Foreign Exchange",
        "publisher_class": "regulator",
        "aliases": ["外汇局", "国家外汇管理局", "SAFE"],
        "country_code": "CN",
        "website": "",
        "is_active": True,
        "description": "外汇储备等外汇管理口径机构",
    },
    "NIFC": {
        "canonical_name": "全国银行间同业拆借中心",
        "canonical_name_en": "National Interbank Funding Center",
        "publisher_class": "market_infrastructure",
        "aliases": ["同业拆借中心", "全国银行间同业拆借中心", "NIFC"],
        "country_code": "CN",
        "website": "",
        "is_active": True,
        "description": "Shibor/LPR 等利率口径发布机构",
    },
    "CFETS": {
        "canonical_name": "中国外汇交易中心",
        "canonical_name_en": "China Foreign Exchange Trade System",
        "publisher_class": "market_infrastructure",
        "aliases": ["外汇交易中心", "中国外汇交易中心", "CFETS"],
        "country_code": "CN",
        "website": "",
        "is_active": True,
        "description": "银行间市场基础设施机构",
    },
    "SYSTEM_DERIVED": {
        "canonical_name": "系统派生",
        "canonical_name_en": "System Derived",
        "publisher_class": "system",
        "aliases": ["系统派生", "系统计算", "derived"],
        "country_code": "CN",
        "website": "",
        "is_active": True,
        "description": "系统自动计算得到的衍生序列",
    },
}


INDICATOR_PUBLISHER_LINKS = {
    "CN_PMI": ["NBS", "CFLP"],
    "CN_NON_MAN_PMI": ["NBS", "CFLP"],
    "CN_CPI": ["NBS"],
    "CN_CPI_YOY": ["NBS"],
    "CN_CPI_NATIONAL_YOY": ["NBS"],
    "CN_CPI_NATIONAL_MOM": ["NBS"],
    "CN_CPI_URBAN_YOY": ["NBS"],
    "CN_CPI_URBAN_MOM": ["NBS"],
    "CN_CPI_RURAL_YOY": ["NBS"],
    "CN_CPI_RURAL_MOM": ["NBS"],
    "CN_PPI": ["NBS"],
    "CN_PPI_YOY": ["NBS"],
    "CN_VALUE_ADDED": ["NBS"],
    "CN_RETAIL_SALES": ["NBS"],
    "CN_RETAIL_SALES_YOY": ["NBS"],
    "CN_FIXED_INVESTMENT": ["NBS"],
    "CN_GDP": ["NBS"],
    "CN_GDP_YOY": ["NBS"],
    "CN_UNEMPLOYMENT": ["NBS"],
    "CN_EXPORTS": ["GACC"],
    "CN_EXPORT_YOY": ["GACC"],
    "CN_IMPORTS": ["GACC"],
    "CN_IMPORT_YOY": ["GACC"],
    "CN_TRADE_BALANCE": ["GACC"],
    "CN_M2": ["PBOC"],
    "CN_M2_YOY": ["PBOC"],
    "CN_NEW_CREDIT": ["PBOC"],
    "CN_RMB_DEPOSIT": ["PBOC"],
    "CN_RMB_LOAN": ["PBOC"],
    "CN_SOCIAL_FINANCING": ["PBOC"],
    "CN_FX_RESERVES": ["SAFE"],
    "CN_SHIBOR": ["NIFC"],
    "CN_LPR": ["NIFC"],
    "CN_DR007": ["CFETS", "NIFC"],
    "CN_PBOC_NET_INJECTION": ["PBOC"],
    "CN_TERM_SPREAD_10Y1Y": ["SYSTEM_DERIVED"],
    "CN_TERM_SPREAD_10Y2Y": ["SYSTEM_DERIVED"],
    "CN_FAI_YOY": ["SYSTEM_DERIVED"],
    "CN_SOCIAL_FINANCING_YOY": ["SYSTEM_DERIVED"],
}


def _display_name(codes):
    return "/".join(PUBLISHERS[code]["canonical_name"] for code in codes if code in PUBLISHERS)


def seed_publishers_and_backfill(apps, schema_editor):
    PublisherCatalog = apps.get_model("data_center", "PublisherCatalogModel")
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")

    for code, payload in PUBLISHERS.items():
        PublisherCatalog.objects.update_or_create(
            code=code,
            defaults=payload,
        )

    for indicator_code, publisher_codes in INDICATOR_PUBLISHER_LINKS.items():
        indicator = IndicatorCatalog.objects.filter(code=indicator_code).first()
        if indicator is None:
            continue
        extra = dict(indicator.extra or {})
        extra["publisher_code"] = publisher_codes[0]
        extra["publisher_codes"] = list(publisher_codes)
        extra["publisher"] = _display_name(publisher_codes) or str(extra.get("publisher") or "")
        indicator.extra = extra
        indicator.save(update_fields=["extra"])


def revert_publishers_and_backfill(apps, schema_editor):
    PublisherCatalog = apps.get_model("data_center", "PublisherCatalogModel")
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")

    for indicator_code in INDICATOR_PUBLISHER_LINKS:
        indicator = IndicatorCatalog.objects.filter(code=indicator_code).first()
        if indicator is None:
            continue
        extra = dict(indicator.extra or {})
        extra.pop("publisher_code", None)
        extra.pop("publisher_codes", None)
        indicator.extra = extra
        indicator.save(update_fields=["extra"])

    PublisherCatalog.objects.filter(code__in=list(PUBLISHERS)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0022_seed_macro_provenance_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="PublisherCatalogModel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(db_index=True, help_text="Stable publisher code such as PBOC, NBS, GACC", max_length=40, unique=True)),
                ("canonical_name", models.CharField(help_text="Canonical Chinese display name", max_length=120)),
                ("canonical_name_en", models.CharField(blank=True, max_length=160)),
                ("publisher_class", models.CharField(choices=[("government", "Government"), ("association", "Association"), ("market_infrastructure", "Market Infrastructure"), ("regulator", "Regulator"), ("system", "System"), ("other", "Other")], max_length=30)),
                ("aliases", models.JSONField(blank=True, default=list, help_text="Known alias names")),
                ("country_code", models.CharField(blank=True, default="CN", max_length=10)),
                ("website", models.URLField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("description", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "data_center_publisher_catalog",
                "ordering": ["code"],
                "verbose_name": "Publisher Catalog",
                "verbose_name_plural": "Publisher Catalog",
            },
        ),
        migrations.AddIndex(
            model_name="publishercatalogmodel",
            index=models.Index(fields=["is_active"], name="data_center_is_acti_029649_idx"),
        ),
        migrations.RunPython(seed_publishers_and_backfill, revert_publishers_and_backfill),
    ]
