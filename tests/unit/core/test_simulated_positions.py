from types import SimpleNamespace

from core.integration.simulated_positions import (
    get_simulated_position_price_updater,
    list_held_simulated_asset_codes,
)


def test_get_simulated_position_price_updater_uses_repository_provider(monkeypatch):
    repo = SimpleNamespace(name="repo")
    monkeypatch.setattr(
        "core.integration.simulated_positions.get_simulated_position_repository",
        lambda: repo,
    )

    assert get_simulated_position_price_updater() is repo


def test_list_held_simulated_asset_codes_reads_position_model(monkeypatch):
    class _FakeQuerySet:
        def values_list(self, *args, **kwargs):
            return self

        def distinct(self):
            return ["510300.SH", "159915.SZ"]

    class _FakeManager:
        def filter(self, **kwargs):
            assert kwargs == {"quantity__gt": 0}
            return _FakeQuerySet()

    monkeypatch.setattr(
        "core.integration.simulated_positions.PositionModel",
        SimpleNamespace(_default_manager=_FakeManager()),
    )

    assert list_held_simulated_asset_codes() == ["510300.SH", "159915.SZ"]
