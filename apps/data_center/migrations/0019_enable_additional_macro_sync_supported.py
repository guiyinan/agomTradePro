from django.db import migrations

GOVERNANCE_SCOPE = "macro_console"

ADDITIONAL_SYNC_SUPPORTED_CODES = (
    "CN_BLAST_FURNACE",
    "CN_BOND_10Y",
    "CN_BOND_2Y",
    "CN_BOND_5Y",
    "CN_CCFI",
    "CN_CPI_NATIONAL_MOM",
    "CN_CPI_RURAL_MOM",
    "CN_CPI_RURAL_YOY",
    "CN_CPI_URBAN_MOM",
    "CN_CPI_URBAN_YOY",
    "CN_LPR",
    "CN_NEW_CREDIT",
    "CN_NEW_HOUSE_PRICE",
    "CN_NHCI",
    "CN_NON_MAN_PMI",
    "CN_OIL_PRICE",
    "CN_PMI",
    "CN_PMI_EMPLOYMENT",
    "CN_PMI_INVENTORY",
    "CN_PMI_NEW_ORDER",
    "CN_PMI_PRODUCTION",
    "CN_PMI_PURCHASE",
    "CN_PMI_RAW_MAT",
    "CN_POWER_GEN",
    "CN_RMB_DEPOSIT",
    "CN_RMB_LOAN",
    "CN_RRR",
    "CN_SCFI",
    "CN_SHIBOR",
    "CN_TERM_SPREAD_10Y2Y",
    "CN_TRADE_BALANCE",
    "US_BOND_10Y",
)


def apply_additional_sync_supported_metadata(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code in ADDITIONAL_SYNC_SUPPORTED_CODES:
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        extra = dict(indicator.extra or {})
        extra["governance_scope"] = GOVERNANCE_SCOPE
        extra["governance_sync_supported"] = True
        indicator.extra = extra
        indicator.save(update_fields=["extra"])


def revert_additional_sync_supported_metadata(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code in ADDITIONAL_SYNC_SUPPORTED_CODES:
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        extra = dict(indicator.extra or {})
        extra.pop("governance_scope", None)
        extra.pop("governance_sync_supported", None)
        indicator.extra = extra
        indicator.save(update_fields=["extra"])


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0018_seed_macro_compat_alias_catalog"),
    ]

    operations = [
        migrations.RunPython(
            apply_additional_sync_supported_metadata,
            revert_additional_sync_supported_metadata,
        ),
    ]
