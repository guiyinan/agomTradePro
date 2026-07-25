from datetime import date
from decimal import Decimal
from importlib import import_module

import pytest
from django.apps import apps

from apps.data_center.infrastructure.models import MacroFactModel


@pytest.mark.django_db
def test_manual_pmi_provenance_migration_repairs_and_conflict_marks_legacy_facts():
    migration = import_module(
        "apps.data_center.migrations.0043_govern_manual_pmi_subitem_provenance"
    )
    repairable = MacroFactModel.objects.create(
        indicator_code="CN_PMI_NEW_ORDER",
        reporting_period=date(2026, 1, 31),
        value=Decimal("49.2"),
        unit="指数",
        source="akshare",
        quality="valid",
    )
    conflicting = MacroFactModel.objects.create(
        indicator_code="CN_PMI_NEW_ORDER",
        reporting_period=date(2026, 2, 28),
        value=Decimal("49.4"),
        unit="指数",
        source="akshare",
        quality="estimated",
    )
    MacroFactModel.objects.create(
        indicator_code="CN_PMI_NEW_ORDER",
        reporting_period=date(2026, 2, 28),
        value=Decimal("49.5"),
        unit="指数",
        source="manual_pmi_subitems",
        quality="valid",
    )

    migration.govern_manual_pmi_provenance(apps, None)

    repairable.refresh_from_db()
    conflicting.refresh_from_db()
    assert repairable.source == "manual_pmi_subitems"
    assert repairable.extra["source_type"] == "manual"
    assert repairable.extra["access_channel"] == "manual_file"
    assert conflicting.source == "akshare"
    assert conflicting.quality == "error"
    assert conflicting.extra["provenance_repair_conflict"] is True

    migration.restore_manual_pmi_provenance(apps, None)

    repairable.refresh_from_db()
    conflicting.refresh_from_db()
    assert repairable.source == "akshare"
    assert repairable.quality == "valid"
    assert conflicting.source == "akshare"
    assert conflicting.quality == "estimated"
    assert repairable.extra == {}
    assert conflicting.extra == {}
