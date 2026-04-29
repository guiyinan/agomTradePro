from collections import defaultdict

from django.db import migrations


def drop_legacy_month_start_duplicates(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    MacroFact = apps.get_model("data_center", "MacroFactModel")

    monthly_codes = set(
        IndicatorCatalog.objects.filter(default_period_type="M").values_list("code", flat=True)
    )

    grouped_ids: dict[tuple[str, str, int, int, int], list[tuple[int, int]]] = defaultdict(list)
    for row in MacroFact.objects.filter(indicator_code__in=monthly_codes).values_list(
        "id",
        "indicator_code",
        "source",
        "revision_number",
        "reporting_period",
    ):
        row_id, code, source, revision_number, reporting_period = row
        key = (code, source, revision_number, reporting_period.year, reporting_period.month)
        grouped_ids[key].append((row_id, reporting_period.day))

    stale_ids: list[int] = []
    for rows in grouped_ids.values():
        if len(rows) <= 1:
            continue
        keep_id, _ = max(rows, key=lambda item: item[1])
        stale_ids.extend(row_id for row_id, _ in rows if row_id != keep_id)

    if stale_ids:
        MacroFact.objects.filter(id__in=stale_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0005_fix_indicator_catalog_units"),
    ]

    operations = [
        migrations.RunPython(drop_legacy_month_start_duplicates, migrations.RunPython.noop),
    ]
