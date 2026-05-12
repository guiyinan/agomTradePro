"""Seed macro provenance metadata into IndicatorCatalog.extra."""

from django.db import migrations

PROVENANCE_UPDATES = {
    "CN_PMI": {
        "provenance_class": "official",
        "publisher": "国家统计局/中国物流与采购联合会",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS", "CFLP"],
        "access_channel": "akshare",
    },
    "CN_NON_MAN_PMI": {
        "provenance_class": "official",
        "publisher": "国家统计局/中国物流与采购联合会",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS", "CFLP"],
        "access_channel": "akshare",
    },
    "CN_CPI": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_CPI_YOY": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_CPI_NATIONAL_YOY": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_CPI_NATIONAL_MOM": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_CPI_URBAN_YOY": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_CPI_URBAN_MOM": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_CPI_RURAL_YOY": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_CPI_RURAL_MOM": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_PPI": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_PPI_YOY": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_VALUE_ADDED": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_RETAIL_SALES": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_RETAIL_SALES_YOY": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_FIXED_INVESTMENT": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_GDP": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_GDP_YOY": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_UNEMPLOYMENT": {
        "provenance_class": "official",
        "publisher": "国家统计局",
        "publisher_code": "NBS",
        "publisher_codes": ["NBS"],
        "access_channel": "akshare",
    },
    "CN_EXPORTS": {
        "provenance_class": "official",
        "publisher": "海关总署",
        "publisher_code": "GACC",
        "publisher_codes": ["GACC"],
        "access_channel": "akshare",
    },
    "CN_EXPORT_YOY": {
        "provenance_class": "official",
        "publisher": "海关总署",
        "publisher_code": "GACC",
        "publisher_codes": ["GACC"],
        "access_channel": "akshare",
    },
    "CN_IMPORTS": {
        "provenance_class": "official",
        "publisher": "海关总署",
        "publisher_code": "GACC",
        "publisher_codes": ["GACC"],
        "access_channel": "akshare",
    },
    "CN_IMPORT_YOY": {
        "provenance_class": "official",
        "publisher": "海关总署",
        "publisher_code": "GACC",
        "publisher_codes": ["GACC"],
        "access_channel": "akshare",
    },
    "CN_TRADE_BALANCE": {
        "provenance_class": "official",
        "publisher": "海关总署",
        "publisher_code": "GACC",
        "publisher_codes": ["GACC"],
        "access_channel": "akshare",
    },
    "CN_M2": {
        "provenance_class": "official",
        "publisher": "中国人民银行",
        "publisher_code": "PBOC",
        "publisher_codes": ["PBOC"],
        "access_channel": "akshare",
    },
    "CN_M2_YOY": {
        "provenance_class": "official",
        "publisher": "中国人民银行",
        "publisher_code": "PBOC",
        "publisher_codes": ["PBOC"],
        "access_channel": "akshare",
    },
    "CN_NEW_CREDIT": {
        "provenance_class": "official",
        "publisher": "中国人民银行",
        "publisher_code": "PBOC",
        "publisher_codes": ["PBOC"],
        "access_channel": "akshare",
    },
    "CN_RMB_DEPOSIT": {
        "provenance_class": "official",
        "publisher": "中国人民银行",
        "publisher_code": "PBOC",
        "publisher_codes": ["PBOC"],
        "access_channel": "akshare",
    },
    "CN_RMB_LOAN": {
        "provenance_class": "official",
        "publisher": "中国人民银行",
        "publisher_code": "PBOC",
        "publisher_codes": ["PBOC"],
        "access_channel": "akshare",
    },
    "CN_SOCIAL_FINANCING": {
        "provenance_class": "official",
        "publisher": "中国人民银行",
        "publisher_code": "PBOC",
        "publisher_codes": ["PBOC"],
        "access_channel": "akshare",
    },
    "CN_FX_RESERVES": {
        "provenance_class": "official",
        "publisher": "国家外汇管理局",
        "publisher_code": "SAFE",
        "publisher_codes": ["SAFE"],
        "access_channel": "akshare",
    },
    "CN_SHIBOR": {
        "provenance_class": "authoritative_third_party",
        "publisher": "全国银行间同业拆借中心",
        "publisher_code": "NIFC",
        "publisher_codes": ["NIFC"],
        "access_channel": "akshare",
    },
    "CN_LPR": {
        "provenance_class": "authoritative_third_party",
        "publisher": "全国银行间同业拆借中心",
        "publisher_code": "NIFC",
        "publisher_codes": ["NIFC"],
        "access_channel": "akshare",
    },
    "CN_DR007": {
        "provenance_class": "authoritative_third_party",
        "publisher": "中国外汇交易中心/全国银行间同业拆借中心",
        "publisher_code": "CFETS",
        "publisher_codes": ["CFETS", "NIFC"],
        "access_channel": "akshare",
    },
    "CN_PBOC_NET_INJECTION": {
        "provenance_class": "official",
        "publisher": "中国人民银行",
        "publisher_code": "PBOC",
        "publisher_codes": ["PBOC"],
        "access_channel": "akshare",
    },
    "CN_TERM_SPREAD_10Y1Y": {
        "provenance_class": "derived",
        "publisher": "系统派生",
        "publisher_code": "SYSTEM_DERIVED",
        "publisher_codes": ["SYSTEM_DERIVED"],
        "access_channel": "data_center",
        "derivation_method": "CN_BOND_10Y - CN_BOND_1Y, then * 100 to bps",
        "upstream_indicator_codes": ["CN_BOND_10Y", "CN_BOND_1Y"],
        "decision_grade_enabled": False,
    },
    "CN_TERM_SPREAD_10Y2Y": {
        "provenance_class": "derived",
        "publisher": "系统派生",
        "publisher_code": "SYSTEM_DERIVED",
        "publisher_codes": ["SYSTEM_DERIVED"],
        "access_channel": "data_center",
        "derivation_method": "CN_BOND_10Y - CN_BOND_2Y, then * 100 to bps",
        "upstream_indicator_codes": ["CN_BOND_10Y", "CN_BOND_2Y"],
        "decision_grade_enabled": False,
    },
    "CN_FAI_YOY": {
        "provenance_class": "derived",
        "publisher": "系统派生",
        "publisher_code": "SYSTEM_DERIVED",
        "publisher_codes": ["SYSTEM_DERIVED"],
        "access_channel": "data_center",
        "derivation_method": "same-month cumulative fixed investment year-over-year growth",
        "upstream_indicator_codes": ["CN_FIXED_INVESTMENT"],
        "decision_grade_enabled": False,
    },
    "CN_SOCIAL_FINANCING_YOY": {
        "provenance_class": "derived",
        "publisher": "系统派生",
        "publisher_code": "SYSTEM_DERIVED",
        "publisher_codes": ["SYSTEM_DERIVED"],
        "access_channel": "data_center",
        "derivation_method": "same-month social financing flow year-over-year growth with prior_flow_value > 0 guardrail",
        "upstream_indicator_codes": ["CN_SOCIAL_FINANCING"],
        "decision_grade_enabled": False,
    },
}


def apply_provenance_metadata(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code, updates in PROVENANCE_UPDATES.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        extra = dict(indicator.extra or {})
        extra.update(updates)
        indicator.extra = extra
        indicator.save(update_fields=["extra"])


def revert_provenance_metadata(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code, updates in PROVENANCE_UPDATES.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        extra = dict(indicator.extra or {})
        for key in updates:
            extra.pop(key, None)
        indicator.extra = extra
        indicator.save(update_fields=["extra"])


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0021_seed_macro_sync_source_type"),
    ]

    operations = [
        migrations.RunPython(apply_provenance_metadata, revert_provenance_metadata),
    ]
