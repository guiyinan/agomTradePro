"""Macro fact controller/read-model CRUD and filtering contracts."""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_center.infrastructure.models import (
    IndicatorCatalogModel,
    IndicatorUnitRuleModel,
)
from apps.macro.infrastructure.data_center_fact_repository import (
    DataCenterMacroReadRepository,
    DataCenterMacroRepository,
)


def _seed_rule(code: str) -> None:
    IndicatorCatalogModel.objects.update_or_create(
        code=code,
        defaults={
            "name_cn": code,
            "name_en": code,
            "description": "contract",
            "category": "测试",
            "default_period_type": "M",
            "default_unit": "指数",
            "is_active": True,
            "extra": {},
        },
    )
    IndicatorUnitRuleModel.objects.update_or_create(
        indicator_code=code,
        source_type="manual",
        original_unit="指数",
        defaults={
            "dimension_key": "index",
            "storage_unit": "指数",
            "display_unit": "指数",
            "multiplier_to_storage": 1.0,
            "is_active": True,
            "priority": 10,
            "description": "contract",
        },
    )


@pytest.mark.django_db
def test_macro_fact_controller_crud_statistics_filters_and_bulk_delete() -> None:
    """Controller CRUD preserves units, publication lag, revisions, and filter scope."""
    _seed_rule("CONTRACT_PMI")
    repo = DataCenterMacroRepository()
    first = repo.create_record(
        code="CONTRACT_PMI",
        value=50.1,
        reporting_period=date(2026, 6, 1),
        period_type="M",
        published_at=date(2026, 6, 3),
    )
    second = repo.create_record(
        code="CONTRACT_PMI",
        value=50.8,
        reporting_period=date(2026, 7, 1),
        period_type="M",
        published_at=date(2026, 7, 2),
        revision_number=2,
    )
    assert repo.get_record_by_id(first["id"])["publication_lag_days"] == 2
    assert repo.get_record_by_id(999999) is None
    assert repo.get_indicator_count("CONTRACT_PMI") == 2
    assert repo.count_records_before_date(date(2026, 7, 1)) == 1

    updated = repo.update_record(
        first["id"],
        value=49.9,
        source="manual",
        reporting_period=date(2026, 6, 2),
        published_at=date(2026, 6, 5),
        period_type="M",
        revision_number=3,
    )
    assert updated is not None
    assert updated["value"] == 49.9
    assert updated["revision_number"] == 3
    assert repo.update_record(999999, value=1) is None

    stats = repo.get_statistics()
    assert stats["total_records"] == 2
    assert stats["total_indicators"] == 1
    assert repo.get_recent_syncs(limit=5)[0]["status"] == "success"

    assert repo.delete_records_by_ids([first["id"]]) == 1
    assert repo.delete_record_by_id(first["id"]) is False
    assert (
        repo.delete_by_conditions(
            indicator_code="CONTRACT_PMI",
            source="manual",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
        )
        == 1
    )
    assert repo.get_indicator_count() == 0
    assert repo.delete_record_by_id(second["id"]) is False


@pytest.mark.django_db
def test_macro_read_repository_rollups_history_sort_pagination_and_latest_values() -> None:
    """Read model provides deterministic rollups, ordering, pagination, and statistics."""
    _seed_rule("CONTRACT_A")
    _seed_rule("CONTRACT_B")
    repo = DataCenterMacroRepository()
    for code, month, value in (
        ("CONTRACT_A", 5, 1.0),
        ("CONTRACT_A", 6, 2.0),
        ("CONTRACT_A", 7, 3.0),
        ("CONTRACT_B", 7, 8.0),
    ):
        repo.create_record(
            code=code,
            value=value,
            reporting_period=date(2026, month, 1),
            period_type="M",
        )

    read = DataCenterMacroReadRepository()
    assert read.list_distinct_codes() == ["CONTRACT_A", "CONTRACT_B"]
    assert read.get_storage_summary()["total_records"] == 4
    assert read.list_indicator_rollups()[0]["count"] == 3
    assert read.list_source_rollups()[0] == {"source": "manual", "count": 4}
    assert read.count_table_rows(code_filter="CONTRACT", period_type_filter="M") == 4

    rows = read.get_table_rows(
        code_filter="CONTRACT_A",
        source_filter="manual",
        period_type_filter="M",
        sort_field="-value",
        offset=1,
        limit=1,
    )
    assert rows[0]["value"] == 2.0
    ascending = read.get_indicator_rows(code="CONTRACT_A", limit=2)
    descending = read.get_indicator_rows(code="CONTRACT_A", limit=2, ascending=False)
    assert [row["value"] for row in ascending] == [1.0, 2.0]
    assert [row["value"] for row in descending] == [3.0, 2.0]
    assert read.get_latest_indicator("CONTRACT_A")["value"] == 3.0
    assert read.get_latest_indicator("MISSING") is None
    assert read.get_indicator_stats("CONTRACT_A", date(2026, 1, 1)) == {
        "avg_value": 2.0,
        "max_value": 3.0,
        "min_value": 1.0,
    }
    history = read.get_indicator_history(
        "CONTRACT_A",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        limit=2,
    )
    assert [row["value"] for row in history] == [3.0, 2.0]
    assert read.get_latest_values_by_codes(["CONTRACT_A", "MISSING"]) == [
        {"code": "CONTRACT_A", "value": 3.0}
    ]
