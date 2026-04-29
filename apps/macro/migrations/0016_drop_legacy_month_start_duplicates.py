from collections import defaultdict

from django.db import migrations


def drop_legacy_month_start_duplicates(apps, schema_editor):
    MacroIndicator = apps.get_model("macro", "MacroIndicator")

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
        ("macro", "0015_indicatorconfigmodel"),
    ]

    operations = [
        migrations.RunPython(drop_legacy_month_start_duplicates, migrations.RunPython.noop),
    ]
