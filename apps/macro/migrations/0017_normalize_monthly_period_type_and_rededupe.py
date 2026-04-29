from collections import defaultdict

from django.db import migrations


def normalize_monthly_period_type_and_rededupe(apps, schema_editor):
    MacroIndicator = apps.get_model("macro", "MacroIndicator")

    MacroIndicator.objects.filter(period_type="PeriodType.MONTH").update(period_type="M")

    grouped_ids: dict[tuple[str, str, int, int, int], list[tuple[int, int]]] = defaultdict(list)
    for row in MacroIndicator.objects.filter(period_type="M").values_list(
        "id",
        "code",
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
        MacroIndicator.objects.filter(id__in=stale_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("macro", "0016_drop_legacy_month_start_duplicates"),
    ]

    operations = [
        migrations.RunPython(
            normalize_monthly_period_type_and_rededupe,
            migrations.RunPython.noop,
        ),
    ]
