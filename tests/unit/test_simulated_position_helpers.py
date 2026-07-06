from apps.decision_rhythm.application.workspace_services import (
    SimulatedPositionSnapshotProvider,
    get_simulated_position_snapshots,
)


def test_get_simulated_position_snapshots_normalizes_numeric_account_ids(monkeypatch):
    monkeypatch.setattr(
        "apps.decision_rhythm.application.workspace_services._get_position_snapshots",
        lambda account_id: [{"account_id": account_id, "asset_code": "510300.SH"}],
    )

    result = get_simulated_position_snapshots(" 42 ")

    assert result == [{"account_id": 42, "asset_code": "510300.SH"}]


def test_get_simulated_position_snapshots_rejects_non_numeric_account_ids(monkeypatch):
    called = False

    def _unexpected_call(account_id):
        nonlocal called
        called = True
        return [{"account_id": account_id}]

    monkeypatch.setattr(
        "apps.decision_rhythm.application.workspace_services._get_position_snapshots",
        _unexpected_call,
    )

    assert get_simulated_position_snapshots("acct-1") == []
    assert called is False


def test_simulated_position_snapshot_provider_uses_local_helper(monkeypatch):
    monkeypatch.setattr(
        "apps.decision_rhythm.application.workspace_services.get_simulated_position_snapshots",
        lambda account_id: [{"account_id": int(account_id), "asset_code": "159915.SZ"}],
    )

    provider = SimulatedPositionSnapshotProvider()

    assert provider.get_position_snapshots("7") == [
        {"account_id": 7, "asset_code": "159915.SZ"}
    ]
