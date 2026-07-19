"""Regression tests for the deployable macro consistency guard."""

import json
from datetime import date
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel


@pytest.mark.django_db
def test_strict_consistency_audit_blocks_ungoverned_cross_source_difference():
    IndicatorCatalogModel.objects.create(code="CN_AUDIT_TEST", name_cn="审计测试")
    for source, value in (("akshare", "100.000000"), ("tushare", "120.000000")):
        MacroFactModel.objects.create(
            indicator_code="CN_AUDIT_TEST",
            reporting_period=date(2026, 7, 1),
            value=value,
            unit="%",
            source=source,
            extra={"source_type": source, "provider_name": source},
        )

    with pytest.raises(CommandError, match="ungoverned blocking issues"):
        call_command("audit_macro_fact_consistency", strict=True, stdout=StringIO())


@pytest.mark.django_db
def test_strict_consistency_audit_allows_explicitly_governed_source():
    IndicatorCatalogModel.objects.create(
        code="CN_AUDIT_GOVERNED",
        name_cn="已治理审计测试",
        extra={"decision_source_type": "tushare"},
    )
    for source, value in (("akshare", "100.000000"), ("tushare", "120.000000")):
        MacroFactModel.objects.create(
            indicator_code="CN_AUDIT_GOVERNED",
            reporting_period=date(2026, 7, 1),
            value=value,
            unit="%",
            source=source,
            extra={"source_type": source, "provider_name": source},
        )
    stdout = StringIO()

    call_command("audit_macro_fact_consistency", strict=True, stdout=stdout)

    payload = json.loads(stdout.getvalue())
    assert payload["summary"]["cross_source_conflict_count"] == 1
    assert payload["summary"]["ungoverned_cross_source_conflict_count"] == 0
