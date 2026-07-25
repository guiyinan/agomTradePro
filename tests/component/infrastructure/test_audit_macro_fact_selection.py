"""Canonical macro selection coverage for Audit infrastructure readers."""

from datetime import date

import pytest

from apps.audit.infrastructure.repositories import DjangoAuditRepository
from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel


@pytest.mark.django_db
def test_audit_macro_reader_prefers_governed_canonical_fact() -> None:
    IndicatorCatalogModel.objects.update_or_create(
        code="CN_TEST_AUDIT",
        defaults={
            "name_cn": "审计测试指标",
            "default_unit": "%",
            "default_period_type": "M",
            "is_active": True,
            "extra": {"decision_source_type": "akshare"},
        },
    )
    MacroFactModel.objects.create(
        indicator_code="CN_TEST_AUDIT",
        reporting_period=date(2026, 6, 30),
        value=999.0,
        unit="%",
        source="AKShare Public",
        revision_number=9,
        extra={"source_type": "akshare"},
    )
    MacroFactModel.objects.create(
        indicator_code="CN_TEST_AUDIT",
        reporting_period=date(2026, 6, 30),
        value=1.2,
        unit="%",
        source="akshare",
        revision_number=0,
        extra={"source_type": "akshare", "provider_name": "AKShare Public"},
    )

    values = DjangoAuditRepository().get_macro_indicator_values(
        "CN_TEST_AUDIT",
        date(2026, 6, 1),
        date(2026, 6, 30),
    )

    assert values == [(date(2026, 6, 30), 1.2)]
