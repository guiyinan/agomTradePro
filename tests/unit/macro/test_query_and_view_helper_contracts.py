"""Macro query facade and page helper contracts."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from apps.macro.application import query_services
from apps.macro.interface.views import helpers


def test_macro_query_services_delegate_and_normalize_sync_result(monkeypatch) -> None:
    """Query helpers preserve filters while presenting a command-safe sync payload."""
    repository = SimpleNamespace(
        get_latest_observation_date=lambda code: date(2026, 7, 1),
        get_series=lambda **kwargs: [kwargs],
    )
    monkeypatch.setattr(query_services, "get_macro_repository", lambda: repository)
    assert query_services.get_latest_macro_indicator_date("CN_PMI") == date(2026, 7, 1)
    rows = query_services.get_legacy_macro_series(
        code="CN_PMI",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 1),
        source="akshare",
    )
    assert rows[0]["source"] == "akshare"

    use_case = SimpleNamespace(
        execute=lambda request: SimpleNamespace(
            success=False,
            synced_count=2,
            skipped_count=1,
            errors=("offline",),
        )
    )
    monkeypatch.setattr(
        query_services,
        "build_sync_macro_data_use_case",
        lambda: use_case,
    )
    payload = query_services.sync_macro_indicators(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 1),
        indicators=["CN_PMI"],
    )
    assert payload == {
        "success": False,
        "synced_count": 2,
        "skipped_count": 1,
        "errors": ["offline"],
    }


def test_macro_view_helpers_use_primary_and_fallback_sources(monkeypatch) -> None:
    """Page helpers expose repositories, indicator catalogs, and deterministic fallback."""
    repository = object()
    monkeypatch.setattr(helpers, "get_macro_repository", lambda: repository)
    monkeypatch.setattr(
        helpers,
        "get_supported_macro_indicators",
        lambda source: [source, "CN_PMI"],
    )
    assert helpers.get_repository() is repository
    assert helpers.get_supported_indicators() == ["akshare", "CN_PMI"]

    calls: list[str | None] = []

    def _builder(source: str | None):
        calls.append(source)
        if source == "akshare":
            raise RuntimeError("unavailable")
        return "fallback"

    monkeypatch.setattr(helpers, "build_sync_macro_data_use_case", _builder)
    assert helpers.get_sync_use_case() == "fallback"
    assert calls == ["akshare", None]
