"""Govern the market-turnover decision series to the full A-share aggregation."""

from django.db import migrations


def govern_turnover_source(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    indicator = IndicatorCatalog.objects.filter(code="CN_A_TOTAL_TURNOVER").first()
    if indicator is None:
        return
    extra = dict(indicator.extra or {})
    extra["decision_source_type"] = "tushare"
    extra["source_semantics"] = "sum_all_a_share_daily_amount"
    indicator.extra = extra
    indicator.save(update_fields=["extra", "updated_at"])


def remove_turnover_source(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    indicator = IndicatorCatalog.objects.filter(code="CN_A_TOTAL_TURNOVER").first()
    if indicator is None:
        return
    extra = dict(indicator.extra or {})
    extra.pop("decision_source_type", None)
    extra.pop("source_semantics", None)
    indicator.extra = extra
    indicator.save(update_fields=["extra", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("data_center", "0033_close_macro_fact_governance_gaps")]

    operations = [migrations.RunPython(govern_turnover_source, remove_turnover_source)]
