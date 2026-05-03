"""Move remaining legacy macro code aliases into catalog-managed compatibility rows."""

from __future__ import annotations

from django.db import migrations


ALIAS_ROWS = {
    "CN_CPI_YOY": {
        "canonical_code": "CN_CPI_NATIONAL_YOY",
        "name_cn": "CPI同比",
        "name_en": "CPI YoY",
        "description": "兼容别名代码，canonical 指标为 CN_CPI_NATIONAL_YOY；不再单独维护独立时序。",
    },
    "CN_CPI_MOY": {
        "canonical_code": "CN_CPI_NATIONAL_MOM",
        "name_cn": "CPI环比",
        "name_en": "CPI MoM",
        "description": "兼容别名代码，canonical 指标为 CN_CPI_NATIONAL_MOM；不再单独维护独立时序。",
    },
    "CN_PMI_MANUFACTURING": {
        "canonical_code": "CN_PMI",
        "name_cn": "制造业PMI",
        "name_en": "Manufacturing PMI Legacy Alias",
        "description": "兼容别名代码，canonical 指标为 CN_PMI；不再单独维护独立时序。",
    },
    "CN_PMI_NON_MANUFACTURING": {
        "canonical_code": "CN_NON_MAN_PMI",
        "name_cn": "非制造业PMI",
        "name_en": "Non-Manufacturing PMI Legacy Alias",
        "description": "兼容别名代码，canonical 指标为 CN_NON_MAN_PMI；不再单独维护独立时序。",
    },
}

ALIAS_SCOPE = "macro_compat_alias"


def _build_alias_extra(target_extra: dict | None) -> dict:
    extra = dict(target_extra or {})
    extra["alias_of_indicator_code"] = ""
    extra["governance_status"] = "alias_only"
    extra["governance_scope"] = ALIAS_SCOPE
    extra["governance_sync_supported"] = False
    return extra


def apply_catalog_aliases(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for alias_code, payload in ALIAS_ROWS.items():
        target = IndicatorCatalog.objects.filter(code=payload["canonical_code"]).first()
        if target is None:
            continue

        alias_extra = _build_alias_extra(target.extra)
        alias_extra["alias_of_indicator_code"] = payload["canonical_code"]

        IndicatorCatalog.objects.update_or_create(
            code=alias_code,
            defaults={
                "name_cn": payload["name_cn"],
                "name_en": payload["name_en"],
                "description": payload["description"],
                "default_unit": target.default_unit,
                "default_period_type": target.default_period_type,
                "category": target.category,
                "is_active": True,
                "extra": alias_extra,
            },
        )


def revert_catalog_aliases(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for alias_code in ALIAS_ROWS:
        if alias_code == "CN_CPI_YOY":
            indicator = IndicatorCatalog.objects.filter(code=alias_code).first()
            if indicator is None:
                continue
            extra = dict(indicator.extra or {})
            extra["alias_of_indicator_code"] = "CN_CPI_NATIONAL_YOY"
            extra["governance_status"] = "alias_only"
            extra["governance_scope"] = "macro_console"
            extra["governance_sync_supported"] = False
            indicator.extra = extra
            indicator.description = (
                "兼容别名代码，canonical 指标为 CN_CPI_NATIONAL_YOY；不再单独维护独立时序。"
            )
            indicator.save(update_fields=["description", "extra"])
            continue
        if alias_code == "CN_CPI_MOY":
            indicator = IndicatorCatalog.objects.filter(code=alias_code).first()
            if indicator is None:
                continue
            extra = dict(indicator.extra or {})
            extra.pop("alias_of_indicator_code", None)
            extra.pop("governance_status", None)
            extra.pop("governance_scope", None)
            extra.pop("governance_sync_supported", None)
            indicator.extra = extra
            indicator.description = ""
            indicator.save(update_fields=["description", "extra"])
            continue
        IndicatorCatalog.objects.filter(code=alias_code).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0017_canonicalize_fact_sources"),
    ]

    operations = [
        migrations.RunPython(apply_catalog_aliases, revert_catalog_aliases),
    ]
