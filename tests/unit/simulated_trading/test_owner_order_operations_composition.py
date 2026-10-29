"""Owner recovery construction must not depend on today's configuration."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from apps.data_center.application.calendar_capture_configuration import (
    resolve_calendar_capture_configuration,
)
from apps.simulated_trading import execution_current_reference_composition as calendar_composition
from tests.unit.data_center.test_calendar_workbench_scope_composition import (
    DATASET,
    NOW,
    _candidates,
)


def test_configured_fill_calendar_retains_exact_cutoff_and_transaction_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = resolve_calendar_capture_configuration(_candidates(), known_at=NOW)
    calls: list[tuple[str, datetime, date | None]] = []

    def read_configuration(*, as_of: datetime) -> object:
        assert as_of == NOW
        return configuration

    def read_calendar(*, exchange: str, as_of: datetime, coverage_start: date | None) -> None:
        calls.append((exchange, as_of, coverage_start))

    def reference_reader(_query: object) -> None:
        pytest.fail("only the composed calendar reader may call the reference")

    def factory(*, dataset_key: str, runtime_environment: str, read_publication: object) -> object:
        assert dataset_key == DATASET.value
        assert runtime_environment == "development"
        assert read_publication is reference_reader
        return SimpleNamespace(get_effective_execution_calendar=read_calendar)

    def forbidden_configuration(*, as_of: datetime) -> None:
        pytest.fail("fill calendar must use the transaction-compatible selection callback")

    monkeypatch.setattr(
        calendar_composition, "read_calendar_capture_configuration_at", forbidden_configuration
    )
    monkeypatch.setattr(
        calendar_composition, "build_current_published_execution_calendar_reader", factory
    )
    reader = calendar_composition.build_configured_execution_calendar_reader(
        runtime_environment="development",
        read_publication=reference_reader,
        read_configuration=read_configuration,
    )
    assert calls == []
    assert (
        reader.get_effective_execution_calendar(
            exchange="SSE", as_of=NOW, coverage_start=NOW.date()
        )
        is None
    )
    assert calls == [("SSE", NOW, NOW.date())]


def test_owner_operation_factory_performs_no_source_or_configuration_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.simulated_trading import initial_position_mark_composition as mark_composition
    from apps.simulated_trading import owner_order_operations_composition as composition

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("construction must leave exact receipt replay available offline")

    monkeypatch.setattr(composition, "read_calendar_capture_configuration_reference_at", forbidden)

    for module, names in (
        (
            calendar_composition,
            (
                "read_calendar_capture_configuration_at",
                "get_active_runtime_profile",
                "get_active_runtime_value",
                "get_latest_runtime_snapshot",
            ),
        ),
        (
            mark_composition,
            (
                "get_active_runtime_profile",
                "get_active_runtime_value",
                "get_latest_runtime_snapshot",
                "get_published_price_bar_source",
            ),
        ),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    use_case = composition.build_owner_order_operations_use_case()
    assert callable(use_case.apply_retained_fill)
    assert callable(use_case.cancel_remaining)
