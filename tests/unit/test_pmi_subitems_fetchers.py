import json
from datetime import date
from pathlib import Path

import pytest

from apps.data_center.infrastructure.macro_sources.base import (
    BaseMacroAdapter,
    DataValidationError,
)
from apps.data_center.infrastructure.macro_sources.fetchers.pmi_subitems_fetchers import (
    MANUAL_DATA_FILE,
    MANUAL_SOURCE_NAME,
    PMISubitemsFetcher,
)


def _validate(point) -> None:
    BaseMacroAdapter()._validate_data_point(point)


def _sort(points):
    return sorted(points, key=lambda point: point.observed_at)


@pytest.fixture(autouse=True)
def governed_pmi_subitem_units(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.data_center.infrastructure.macro_sources.fetchers.common.get_runtime_macro_index_metadata_map",
        lambda: {
            code: {"default_unit": "指数", "governance_scope": "macro_console"}
            for code in (
                "CN_PMI_NEW_ORDER",
                "CN_PMI_INVENTORY",
                "CN_PMI_RAW_MAT",
                "CN_PMI_PURCHASE",
                "CN_PMI_PRODUCTION",
                "CN_PMI_EMPLOYMENT",
            )
        },
    )


@pytest.fixture
def fetcher() -> PMISubitemsFetcher:
    return PMISubitemsFetcher(object(), "akshare", _validate, _sort)


@pytest.mark.parametrize(
    ("method_name", "indicator_code", "latest_value"),
    [
        ("fetch_pmi_new_order", "CN_PMI_NEW_ORDER", 49.2),
        ("fetch_pmi_inventory", "CN_PMI_INVENTORY", 47.8),
        ("fetch_pmi_raw_material", "CN_PMI_RAW_MAT", 48.6),
        ("fetch_pmi_purchase", "CN_PMI_PURCHASE", 49.0),
        ("fetch_pmi_production", "CN_PMI_PRODUCTION", 51.1),
        ("fetch_pmi_employment", "CN_PMI_EMPLOYMENT", 48.1),
    ],
)
def test_default_manual_file_is_reachable_and_emits_governed_source(
    fetcher,
    method_name,
    indicator_code,
    latest_value,
) -> None:
    assert MANUAL_DATA_FILE.is_file()

    points = getattr(fetcher, method_name)(
        date(2024, 1, 1),
        date(2025, 12, 31),
    )

    assert len(points) == 4
    assert points[-1].code == indicator_code
    assert points[-1].observed_at == date(2025, 1, 31)
    assert points[-1].value == latest_value
    assert points[-1].source == MANUAL_SOURCE_NAME
    assert points[-1].unit == "指数"


def _write_payload(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"data": {}},
        {"data": ["not-an-object"]},
    ],
)
def test_manual_payload_rejects_invalid_structure(
    fetcher,
    tmp_path,
    payload,
) -> None:
    data_file = tmp_path / "pmi.json"
    _write_payload(data_file, payload)
    fetcher._data_file_path = data_file

    with pytest.raises(DataValidationError):
        fetcher.fetch_pmi_new_order(date(2025, 1, 1), date(2025, 12, 31))


def test_manual_payload_rejects_invalid_json(fetcher, tmp_path) -> None:
    data_file = tmp_path / "pmi.json"
    data_file.write_text("{invalid", encoding="utf-8")
    fetcher._data_file_path = data_file

    with pytest.raises(DataValidationError, match="无法读取"):
        fetcher.fetch_pmi_new_order(date(2025, 1, 1), date(2025, 12, 31))


def test_missing_manual_file_remains_an_explicit_optional_empty_source(
    fetcher,
    tmp_path,
) -> None:
    fetcher._data_file_path = tmp_path / "missing.json"

    assert (
        fetcher.fetch_pmi_new_order(
            date(2025, 1, 1),
            date(2025, 12, 31),
        )
        == []
    )


def test_manual_records_skip_invalid_periods_and_index_values(
    fetcher,
    tmp_path,
) -> None:
    data_file = tmp_path / "pmi.json"
    _write_payload(
        data_file,
        {
            "data": [
                {"reporting_period": "2025-01-30", "new_order": 50.0},
                {"reporting_period": "2025-02-28", "new_order": True},
                {"reporting_period": "2025-03-31", "new_order": "nan"},
                {"reporting_period": "2025-04-30", "new_order": 101.0},
                {"reporting_period": "2025-05-31", "new_order": -0.1},
                {"reporting_period": "2025-06-30", "new_order": "50.6"},
            ]
        },
    )
    fetcher._data_file_path = data_file

    points = fetcher.fetch_pmi_new_order(
        date(2025, 1, 1),
        date(2025, 12, 31),
    )

    assert [(point.observed_at, point.value) for point in points] == [(date(2025, 6, 30), 50.6)]


def test_manual_fetch_rejects_reversed_date_range(fetcher) -> None:
    with pytest.raises(ValueError, match="起始日期不得晚于结束日期"):
        fetcher.fetch_pmi_new_order(
            date(2025, 12, 31),
            date(2025, 1, 1),
        )
