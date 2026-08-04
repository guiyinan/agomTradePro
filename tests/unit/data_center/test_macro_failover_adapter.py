"""Consistency and disclosure tests for macro-source failover."""

from __future__ import annotations

import logging
from datetime import date

import pytest

from apps.data_center.infrastructure.macro_sources.base import (
    DataSourceUnavailableError,
    MacroDataPoint,
)
from apps.data_center.infrastructure.macro_sources.failover_adapter import (
    FailoverAdapter,
    MultiSourceAdapter,
    _resolve_failover_enabled,
    _resolve_failover_tolerance,
)


class _Adapter:
    def __init__(
        self,
        source_name: str,
        *,
        data: list[MacroDataPoint] | None = None,
        error: Exception | None = None,
        supported: bool = True,
    ) -> None:
        self.source_name = source_name
        self.data = data or []
        self.error = error
        self.supported = supported

    def supports(self, indicator_code: str) -> bool:
        return self.supported

    def fetch(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroDataPoint]:
        if self.error is not None:
            raise self.error
        return list(self.data)


def _point(
    value: float,
    *,
    observed_at: date = date(2026, 7, 1),
    published_at: date | None = date(2026, 7, 2),
    source: str = "test",
) -> MacroDataPoint:
    return MacroDataPoint(
        code="CN_PMI",
        value=value,
        observed_at=observed_at,
        published_at=published_at,
        source=source,
        unit="指数",
    )


@pytest.mark.parametrize("tolerance", [-0.01, 1.01, float("nan"), float("inf"), True])
def test_failover_rejects_invalid_tolerance(tolerance) -> None:
    with pytest.raises(ValueError, match="tolerance must be finite"):
        FailoverAdapter([_Adapter("primary")], tolerance=tolerance)


def test_runtime_failover_tolerance_is_preferred(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.integration.config_center_runtime.get_active_runtime_value",
        lambda *, environment, definition_key: (
            0.025
            if environment == "production"
            and definition_key == "data_center.provider.failover_tolerance"
            else None
        ),
    )

    assert _resolve_failover_tolerance(0.01, environment="production") == pytest.approx(0.025)


def test_runtime_failover_tolerance_keeps_owner_compatibility_on_missing_profile(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "core.integration.config_center_runtime.get_active_runtime_value",
        lambda **_: None,
    )

    assert _resolve_failover_tolerance(0.01, environment="development") == pytest.approx(0.01)


def test_runtime_failover_switch_is_preferred(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.integration.config_center_runtime.get_active_runtime_value",
        lambda *, environment, definition_key: (
            True
            if environment == "production"
            and definition_key == "data_center.provider.enable_failover"
            else None
        ),
    )

    assert _resolve_failover_enabled(False, environment="production") is True


def test_runtime_failover_switch_keeps_owner_compatibility_on_invalid_value(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "core.integration.config_center_runtime.get_active_runtime_value",
        lambda **_: "true",
    )

    assert _resolve_failover_enabled(True, environment="development") is True
    assert _resolve_failover_enabled(False, environment="development") is False


def test_primary_data_is_retained_when_backup_disagrees(caplog) -> None:
    primary_data = [_point(50.0, source="primary")]
    backup_data = [_point(55.0, source="backup")]
    adapter = FailoverAdapter(
        [
            _Adapter("primary", data=primary_data),
            _Adapter("backup", data=backup_data),
        ],
        tolerance=0.01,
    )

    with caplog.at_level(logging.WARNING):
        result = adapter.fetch("CN_PMI", date(2026, 7, 1), date(2026, 7, 1))

    assert result == primary_data
    assert "无法通过一致性校验" in caplog.text


def test_single_available_fallback_is_explicitly_unvalidated(caplog) -> None:
    fallback_data = [_point(50.0, source="backup")]
    adapter = FailoverAdapter(
        [
            _Adapter("primary", error=DataSourceUnavailableError("token=secret")),
            _Adapter("backup", data=fallback_data),
        ]
    )

    with caplog.at_level(logging.WARNING):
        result = adapter.fetch("CN_PMI", date(2026, 7, 1), date(2026, 7, 1))

    assert result == fallback_data
    assert "没有其他可用数据源执行交叉校验" in caplog.text
    assert "token=secret" not in caplog.text


def test_disagreeing_fallback_sources_fail_closed() -> None:
    adapter = FailoverAdapter(
        [
            _Adapter("primary", error=DataSourceUnavailableError("offline")),
            _Adapter("backup-a", data=[_point(50.0, source="backup-a")]),
            _Adapter("backup-b", data=[_point(55.0, source="backup-b")]),
        ],
        tolerance=0.01,
    )

    with pytest.raises(
        DataSourceUnavailableError,
        match="fallback source failed consistency validation",
    ):
        adapter.fetch("CN_PMI", date(2026, 7, 1), date(2026, 7, 1))


def test_non_overlapping_series_are_not_reported_as_consistent() -> None:
    adapter = FailoverAdapter([_Adapter("primary")])

    assert adapter._validate_consistency([], [_point(50.0)]) is False
    assert (
        adapter._validate_consistency(
            [_point(50.0, observed_at=date(2026, 7, 1))],
            [_point(50.0, observed_at=date(2026, 7, 2))],
        )
        is False
    )


def test_multi_source_handles_missing_publication_dates_and_prefers_newer() -> None:
    older = _point(49.0, published_at=None, source="older")
    newer = _point(50.0, published_at=date(2026, 7, 3), source="newer")
    adapter = MultiSourceAdapter(
        [
            _Adapter("older", data=[older]),
            _Adapter("newer", data=[newer]),
        ]
    )

    result = adapter.fetch("CN_PMI", date(2026, 7, 1), date(2026, 7, 1))

    assert result == [newer]
