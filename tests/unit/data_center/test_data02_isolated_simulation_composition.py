"""Tests for the isolated DATA-02 application-root composition."""

from __future__ import annotations

import pytest

from apps.data_center import data02_isolated_simulation_composition as composition


def test_factory_injects_database_url_into_snapshot_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The composition root wires the configured database URL to the use case."""

    captured: dict[str, object] = {}

    class FakeAdapter:
        def __init__(self, *, database_url: str) -> None:
            captured["database_url"] = database_url
            captured["adapter"] = self

    class FakeUseCase:
        def __init__(self, *, snapshot_port: object) -> None:
            captured["snapshot_port"] = snapshot_port

    monkeypatch.setattr(composition, "PostgresData02HistoricalSnapshotAdapter", FakeAdapter)
    monkeypatch.setattr(composition, "RunData02IsolatedSimulationUseCase", FakeUseCase)

    result = composition.make_data02_isolated_simulation_use_case(database_url="postgres://sim")

    assert isinstance(result, FakeUseCase)
    assert captured["database_url"] == "postgres://sim"
    assert captured["snapshot_port"] is captured["adapter"]
