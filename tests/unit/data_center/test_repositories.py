from datetime import date

import pytest

from apps.data_center.infrastructure.models import MacroFactModel, PublisherCatalogModel
from apps.data_center.infrastructure.repositories import MacroFactRepository, PublisherCatalogRepository


@pytest.mark.django_db
def test_macro_fact_repository_returns_latest_first_series():
    MacroFactModel.objects.create(
        indicator_code="CN_IMPORT_YOY",
        reporting_period=date(2025, 6, 1),
        value="1.200000",
        unit="%",
        source="akshare",
        revision_number=1,
        quality="valid",
        extra={},
    )
    MacroFactModel.objects.create(
        indicator_code="CN_IMPORT_YOY",
        reporting_period=date(2026, 3, 1),
        value="27.800000",
        unit="%",
        source="akshare",
        revision_number=1,
        quality="valid",
        extra={},
    )

    rows = MacroFactRepository().get_series("CN_IMPORT_YOY", limit=10)

    assert [row.reporting_period for row in rows] == [
        date(2026, 3, 1),
        date(2025, 6, 1),
    ]


@pytest.mark.django_db
def test_publisher_catalog_repository_persists_aliases():
    PublisherCatalogModel.objects.create(
        code="TEST_REPO_PUBLISHER",
        canonical_name="测试仓储机构",
        publisher_class="government",
        aliases=["测试别名一", "测试别名二"],
    )

    publisher = PublisherCatalogRepository().get_by_code("TEST_REPO_PUBLISHER")

    assert publisher is not None
    assert publisher.canonical_name == "测试仓储机构"
    assert publisher.aliases == ["测试别名一", "测试别名二"]
