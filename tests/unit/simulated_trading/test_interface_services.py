from types import SimpleNamespace

from apps.simulated_trading.application.interface_services import build_my_account_detail_context


class _FakeAccountRepository:
    def get_account_model_for_user(self, account_id: int, user_id: int):
        assert account_id == 7
        assert user_id == 3
        return SimpleNamespace(
            id=7,
            user_id=3,
            account_type="paper",
        )


class _FakePositionRepository:
    def list_position_models_for_account(self, account_id: int, limit: int = 10):
        assert account_id == 7
        assert limit == 10
        return ["position-1"]


class _FakeTradeRepository:
    def list_trade_models_for_account(self, account_id: int, limit: int = 20):
        assert account_id == 7
        assert limit == 20
        return ["trade-1"]


def test_build_my_account_detail_context_uses_share_context_bridge(monkeypatch):
    monkeypatch.setattr(
        "apps.simulated_trading.application.interface_services.get_simulated_account_repository",
        lambda: _FakeAccountRepository(),
    )
    monkeypatch.setattr(
        "apps.simulated_trading.application.interface_services.get_simulated_position_repository",
        lambda: _FakePositionRepository(),
    )
    monkeypatch.setattr(
        "apps.simulated_trading.application.interface_services.get_simulated_trade_repository",
        lambda: _FakeTradeRepository(),
    )
    monkeypatch.setattr(
        "apps.simulated_trading.application.interface_services.get_account_owner_share_links",
        lambda owner_id, account_id: [{"owner_id": owner_id, "account_id": account_id}],
    )

    user = SimpleNamespace(id=3)
    context = build_my_account_detail_context(user, 7)

    assert context is not None
    assert context["share_links"] == [{"owner_id": 3, "account_id": 7}]
    assert context["positions"] == ["position-1"]
    assert context["trades"] == ["trade-1"]
