"""Seed semantics-driven chart policies for active macro indicators."""

from django.db import migrations

SEMANTICS_TO_POLICY = {
    "cumulative_level": "yearly_reset_bar",
    "monthly_level": "period_bar",
    "flow_level": "period_bar",
    "yoy_rate": "continuous_line",
    "mom_rate": "continuous_line",
    "rate": "continuous_line",
    "index_level": "continuous_line",
    "balance_level": "continuous_line",
    "level": "continuous_line",
}

FALLBACK_POLICY = "continuous_line"
PREVIOUS_SPECIAL_CASES = {
    "CN_GDP": "yearly_segmented",
    "CN_FIXED_INVESTMENT": "yearly_segmented",
}


def _resolve_policy(extra: dict) -> str:
    series_semantics = str(extra.get("series_semantics") or "").strip()
    return SEMANTICS_TO_POLICY.get(series_semantics, FALLBACK_POLICY)


def apply_chart_policies(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")

    for indicator in IndicatorCatalog.objects.filter(is_active=True):
        merged_extra = dict(indicator.extra or {})
        merged_extra["chart_policy"] = _resolve_policy(merged_extra)
        indicator.extra = merged_extra
        indicator.save(update_fields=["extra"])


def revert_chart_policies(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")

    for indicator in IndicatorCatalog.objects.filter(is_active=True):
        reverted_extra = dict(indicator.extra or {})
        if indicator.code in PREVIOUS_SPECIAL_CASES:
            reverted_extra["chart_policy"] = PREVIOUS_SPECIAL_CASES[indicator.code]
        else:
            reverted_extra.pop("chart_policy", None)
        indicator.extra = reverted_extra
        indicator.save(update_fields=["extra"])


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0024_seed_macro_chart_policies"),
    ]

    operations = [
        migrations.RunPython(apply_chart_policies, revert_chart_policies),
    ]
