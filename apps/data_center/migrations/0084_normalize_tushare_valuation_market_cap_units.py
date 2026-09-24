from __future__ import annotations

from decimal import Decimal

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

_MULTIPLIER = Decimal("10000")
_MARKER = "market_cap_multiplier_to_storage"


def normalize_tushare_market_caps(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    valuation = apps.get_model("data_center", "ValuationFactModel")
    query = valuation.objects.using(schema_editor.connection.alias).filter(
        models.Q(source__iexact="tushare") | models.Q(extra__source_type="tushare")
    )
    pending = []
    for row in query.iterator(chunk_size=500):
        extra = dict(row.extra or {})
        if extra.get(_MARKER) == float(_MULTIPLIER):
            continue
        if row.market_cap is not None:
            row.market_cap *= _MULTIPLIER
        if row.float_market_cap is not None:
            row.float_market_cap *= _MULTIPLIER
        row.extra = {
            **extra,
            "market_cap_original_unit": "万元",
            "market_cap_canonical_unit": "元",
            _MARKER: float(_MULTIPLIER),
        }
        pending.append(row)
        if len(pending) == 500:
            valuation.objects.using(schema_editor.connection.alias).bulk_update(
                pending,
                ("market_cap", "float_market_cap", "extra"),
                batch_size=500,
            )
            pending.clear()
    if pending:
        valuation.objects.using(schema_editor.connection.alias).bulk_update(
            pending,
            ("market_cap", "float_market_cap", "extra"),
            batch_size=500,
        )


class Migration(migrations.Migration):
    dependencies = [("data_center", "0083_financial_source_time_audit_claim")]

    operations = [migrations.RunPython(normalize_tushare_market_caps, migrations.RunPython.noop)]
