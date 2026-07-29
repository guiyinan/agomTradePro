"""T3A account interface-service ownership, classification, and token contracts."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.account.application import interface_services


class _InterfaceRepository:
    def __init__(self) -> None:
        self.password_updated = False
        self.portfolio: object | None = SimpleNamespace(id=9)
        self.calls: list[tuple[str, object]] = []
        self.token_enabled = True

    def has_system_settings_singleton(self) -> bool:
        return True

    def get_existing_system_settings(self) -> object:
        return SimpleNamespace(id=1)

    def provision_registered_user(self, **kwargs: object) -> None:
        self.calls.append(("provision", kwargs))

    def update_account_settings(self, user_id: int, **kwargs: object) -> bool:
        self.calls.append(("settings", (user_id, kwargs)))
        return self.password_updated

    def build_settings_context(self, _user_id: int) -> dict[str, object]:
        return {
            "portfolio": self.portfolio,
            "profile": SimpleNamespace(mcp_enabled=self.token_enabled),
        }

    def save_trading_cost_config(self, **kwargs: object) -> None:
        self.calls.append(("cost", kwargs))

    def create_access_token(self, **kwargs: object) -> tuple[object, str]:
        self.calls.append(("create_token", kwargs))
        return (
            SimpleNamespace(
                name=kwargs["token_name"],
                access_level=kwargs["access_level"],
                user=SimpleNamespace(username="owner"),
            ),
            "plain-token",
        )

    def revoke_access_token_for_user(self, **_kwargs: object) -> str:
        return "self-token"

    def revoke_access_token_by_id(self, token_id: int) -> dict[str, str]:
        return {"username": "owner", "token_name": f"token-{token_id}"}

    def toggle_user_mcp(self, target_user_id: int) -> dict[str, object]:
        return {
            "username": f"user-{target_user_id}",
            "mcp_enabled": True,
            "default_mcp_enabled": False,
        }

    def build_profile_context(self, _user_id: int) -> dict[str, object]:
        return {
            "profile": SimpleNamespace(
                mcp_enabled=True,
                user=SimpleNamespace(username="target"),
            )
        }

    def create_capital_flow(self, **kwargs: object) -> None:
        self.calls.append(("capital", kwargs))

    def revoke_all_access_tokens_for_user(self, **_kwargs: object) -> dict[str, object]:
        return {"deleted_count": 2, "username": "owner"}

    def approve_user(self, **_kwargs: object) -> dict[str, str]:
        return {"level": "success", "message": "approved"}

    def set_user_role(self, **kwargs: object) -> dict[str, str]:
        self.calls.append(("role", kwargs))
        return {"level": "success", "message": "updated"}

    def search_observer_candidates(self, **kwargs: object) -> list[dict[str, object]]:
        self.calls.append(("search", kwargs))
        return [{"id": 2}]

    def save_api_trading_cost_config(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("api_cost", kwargs))
        return kwargs


class _ClassificationRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.rate_model: object | None = SimpleNamespace(
            rate=Decimal("7.2"),
            effective_date=date(2026, 7, 25),
            convert=lambda amount: amount * Decimal("7.2"),
        )

    def list_child_asset_categories(self, category_id: int) -> list[int]:
        return [category_id + 1]

    def create_asset_category(self, **kwargs: object) -> object:
        self.calls.append(("create_category", kwargs))
        return kwargs

    def update_asset_category(self, **kwargs: object) -> object:
        self.calls.append(("update_category", kwargs))
        return kwargs

    def delete_asset_category(self, **kwargs: object) -> None:
        self.calls.append(("delete_category", kwargs))

    def create_exchange_rate(self, **kwargs: object) -> object:
        return kwargs

    def update_exchange_rate(self, **kwargs: object) -> object:
        return kwargs

    def delete_exchange_rate(self, **kwargs: object) -> None:
        self.calls.append(("delete_rate", kwargs))

    def get_exchange_rate_for_conversion(self, **_kwargs: object) -> object | None:
        return self.rate_model

    def get_portfolio_for_user(self, **_kwargs: object) -> object:
        return SimpleNamespace(id=9, base_currency=SimpleNamespace(code="CNY"))

    def list_portfolio_allocation_rows(self, **_kwargs: object) -> list[dict[str, object]]:
        return [
            {
                "currency_code": "USD",
                "currency_name": "US Dollar",
                "category_path": "Equity/US",
                "amount": Decimal("10"),
            },
            {
                "currency_code": "CNY",
                "currency_name": "Yuan",
                "category_path": "Equity/CN",
                "amount": Decimal("20"),
            },
        ]

    def convert_amount(self, **kwargs: object) -> Decimal:
        if kwargs["from_code"] == "USD":
            raise ValueError("rate missing")
        return kwargs["amount"]  # type: ignore[return-value]


@pytest.fixture
def interface_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_InterfaceRepository, _ClassificationRepository]:
    account = _InterfaceRepository()
    classification = _ClassificationRepository()
    monkeypatch.setattr(interface_services, "_interface_repo", lambda: account)
    monkeypatch.setattr(interface_services, "_classification_repo", lambda: classification)
    monkeypatch.setattr(
        interface_services,
        "build_settings_context",
        lambda _user_id: {
            "portfolio": account.portfolio,
            "profile": SimpleNamespace(mcp_enabled=account.token_enabled),
        },
    )
    monkeypatch.setattr(
        interface_services,
        "get_system_settings",
        lambda: SimpleNamespace(allow_token_plaintext_view=True),
    )
    return account, classification


def test_account_settings_and_trading_cost_outcomes(
    interface_repositories: tuple[_InterfaceRepository, _ClassificationRepository],
) -> None:
    account, _ = interface_repositories
    saved = interface_services.update_account_settings(
        7,
        display_name="Owner",
        risk_tolerance="moderate",
        email="owner@example.test",
        new_password="",
    )
    assert saved.redirect_to == "/account/settings/"

    account.password_updated = True
    password = interface_services.update_account_settings(
        7,
        display_name="Owner",
        risk_tolerance="moderate",
        email="owner@example.test",
        new_password="new",
    )
    assert password.redirect_to == "/account/login/"

    account.portfolio = None
    missing = interface_services.save_trading_cost_config(
        7,
        commission_rate="",
        min_commission="",
        stamp_duty_rate="",
        transfer_fee_rate="",
    )
    assert missing.level == "error"

    account.portfolio = SimpleNamespace(id=9)
    success = interface_services.save_trading_cost_config(
        7,
        commission_rate="0.001",
        min_commission="8",
        stamp_duty_rate="0.002",
        transfer_fee_rate="0.0001",
    )
    assert success.level == "success"
    assert account.calls[-1][0] == "cost"


def test_singleton_registration_and_account_option_wrappers(
    interface_repositories: tuple[_InterfaceRepository, _ClassificationRepository],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account, _ = interface_repositories
    monkeypatch.setattr(
        interface_services,
        "AccountRepository",
        lambda: SimpleNamespace(
            list_investment_accounts=lambda _user_id: [
                {"id": None, "account_name": "skip"},
                {"id": 1, "account_name": "", "account_type": "cash"},
                {"id": 2, "account_name": "Growth", "account_type": ""},
            ]
        ),
    )

    assert interface_services.has_system_settings_singleton() is True
    assert interface_services.get_existing_system_settings().id == 1
    options = interface_services.list_investment_account_options(7)
    assert [option["value"] for option in options] == [1, 2]
    assert options[0]["label"] == "账户 1 · cash · #1"
    interface_services.provision_registered_user(
        user=object(),
        display_name="Owner",
        system_settings=object(),
        client_ip="127.0.0.1",
        approval_status="approved",
        rbac_role="owner",
    )
    assert account.calls[-1][0] == "provision"


def test_classification_crud_and_currency_conversion(
    interface_repositories: tuple[_InterfaceRepository, _ClassificationRepository],
) -> None:
    _, classification = interface_repositories

    assert interface_services.get_asset_category_children(category_id=3) == [4]
    assert interface_services.create_asset_category(validated_data={"code": "equity"}) == {
        "code": "equity"
    }
    assert (
        interface_services.update_asset_category(
            category_id=3,
            validated_data={"name": "Equity"},
        )["category_id"]
        == 3
    )
    interface_services.delete_asset_category(category_id=3)
    assert interface_services.create_exchange_rate(validated_data={"from_code": "USD"}) == {
        "from_code": "USD"
    }
    assert (
        interface_services.update_exchange_rate(
            exchange_rate_id=2,
            validated_data={"rate": Decimal("7.2")},
        )["exchange_rate_id"]
        == 2
    )
    interface_services.delete_exchange_rate(exchange_rate_id=2)

    same = interface_services.convert_currency_amount(
        amount=Decimal("10"),
        from_currency="CNY",
        to_currency="CNY",
        date_value=date(2026, 7, 25),
    )
    assert same["rate_used"] == Decimal("1")

    converted = interface_services.convert_currency_amount(
        amount=Decimal("10"),
        from_currency="USD",
        to_currency="CNY",
    )
    assert converted["converted_amount"] == Decimal("72")

    classification.rate_model = None
    with pytest.raises(ValueError, match="No exchange rate"):
        interface_services.convert_currency_amount(
            amount=Decimal("10"),
            from_currency="USD",
            to_currency="CNY",
        )

    currency = interface_services.get_portfolio_allocation_payload(
        portfolio_id=9,
        user_id=7,
        dimension="currency",
    )
    category = interface_services.get_portfolio_allocation_payload(
        portfolio_id=9,
        user_id=7,
        dimension="category",
    )
    assert currency is not None
    assert currency["total_value_base"] == Decimal("30")
    assert category is not None
    assert category["total_value"] == Decimal("30")


def test_token_permission_creation_revocation_and_capital_flow(
    interface_repositories: tuple[_InterfaceRepository, _ClassificationRepository],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account, _ = interface_repositories
    account.token_enabled = False
    with pytest.raises(PermissionError, match="关闭"):
        interface_services.create_self_token(
            7,
            token_name="self",
            access_level="read_only",
        )

    account.token_enabled = True
    created = interface_services.create_self_token(
        7,
        token_name="self",
        access_level="read_only",
    )
    assert created.payload is not None
    assert created.payload["token"] == "plain-token"

    monkeypatch.setattr(
        interface_services,
        "build_token_payload",
        lambda **_kwargs: None,
    )
    hidden = interface_services.create_self_token(
        7,
        token_name="hidden",
        access_level="invalid",
    )
    assert "禁止查看明文" in hidden.message

    revoked = interface_services.revoke_self_token(7, 1)
    assert "self-token" in revoked.message
    capital = interface_services.create_capital_flow(
        7,
        flow_type="deposit",
        amount=Decimal("1000"),
        flow_date=date(2026, 7, 25),
        notes="fund",
    )
    assert "入金" in capital.message
    withdrawal = interface_services.create_capital_flow(
        7,
        flow_type="withdrawal",
        amount=Decimal("100"),
        flow_date=date(2026, 7, 25),
        notes="use",
    )
    assert "出金" in withdrawal.message


def test_admin_and_miscellaneous_wrappers_preserve_actor_scope(
    interface_repositories: tuple[_InterfaceRepository, _ClassificationRepository],
) -> None:
    account, _ = interface_repositories
    revoked = interface_services.revoke_user_tokens(7)
    approved = interface_services.approve_user(actor_user_id=1, target_user_id=7)
    invalid_role = interface_services.set_user_role(target_user_id=7, raw_role="root")
    valid_role = interface_services.set_user_role(target_user_id=7, raw_role="risk")
    candidates = interface_services.search_observer_candidates(
        owner_user_id=7,
        query="analyst",
    )
    cost = interface_services.save_api_trading_cost_config(
        actor_user_id=7,
        portfolio_id=9,
        validated_data={
            "commission_rate": "0.001",
            "min_commission": "5",
            "stamp_duty_rate": "0.002",
            "transfer_fee_rate": "0.0001",
            "is_active": False,
        },
    )

    assert revoked["deleted_count"] == 2
    assert approved.message == "approved"
    assert invalid_role.level == "error"
    assert valid_role.level == "success"
    assert candidates == [{"id": 2}]
    assert cost["actor_user_id"] == 7
    assert cost["is_active"] is False
    assert any(name == "api_cost" for name, _value in account.calls)


def test_plaintext_disabled_detail_missing_and_backtest_application(
    interface_repositories: tuple[_InterfaceRepository, _ClassificationRepository],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        interface_services,
        "get_system_settings",
        lambda: SimpleNamespace(allow_token_plaintext_view=False),
    )
    assert (
        interface_services.build_token_payload(
            username="owner",
            token_name="hidden",
            token_value="secret",
            access_level="read_only",
        )
        is None
    )

    monkeypatch.setattr(
        interface_services,
        "build_self_mcp_api_payload",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(interface_services, "find_user_by_id", lambda _user_id: None)
    with pytest.raises(LookupError, match="用户不存在"):
        interface_services.build_admin_mcp_user_detail_payload(
            99,
            base_url="http://localhost",
        )

    monkeypatch.setattr(
        interface_services,
        "CreatePositionFromBacktestUseCase",
        lambda **_kwargs: SimpleNamespace(
            execute=lambda input_dto: SimpleNamespace(
                total_positions=2,
                total_value=1000.0,
                backtest_name=f"backtest-{input_dto.backtest_id}",
            )
        ),
    )
    monkeypatch.setattr(interface_services, "PositionRepository", lambda: object())
    monkeypatch.setattr(interface_services, "AccountRepository", lambda: object())
    monkeypatch.setattr(interface_services, "AssetMetadataRepository", lambda: object())

    result = interface_services.apply_backtest_results(
        7,
        backtest_id=3,
        scale_factor=0.5,
    )
    assert result["backtest_name"] == "backtest-3"


def test_admin_token_rotation_and_revoke_empty_or_missing(
    interface_repositories: tuple[_InterfaceRepository, _ClassificationRepository],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account, _ = interface_repositories
    monkeypatch.setattr(
        account,
        "build_profile_context",
        lambda _user_id: {
            "profile": SimpleNamespace(
                mcp_enabled=False,
                user=SimpleNamespace(username="target"),
            )
        },
        raising=False,
    )
    with pytest.raises(PermissionError, match="权限已关闭"):
        interface_services.rotate_user_token(
            actor_user_id=1,
            target_user_id=7,
            token_name="admin",
            access_level="read_write",
        )

    monkeypatch.setattr(
        account,
        "revoke_all_access_tokens_for_user",
        lambda **_kwargs: {"deleted_count": 0, "username": "owner"},
    )
    empty = interface_services.revoke_user_tokens(7)
    assert empty["level"] == "warning"

    class AccessTokenDoesNotExist(Exception):
        pass

    monkeypatch.setattr(
        account,
        "revoke_access_token_for_user",
        lambda **_kwargs: (_ for _ in ()).throw(AccessTokenDoesNotExist()),
    )
    with pytest.raises(LookupError, match="Token 不存在"):
        interface_services.revoke_self_token(7, 1)


def test_admin_token_rotation_revoke_and_mcp_toggle_success(
    interface_repositories: tuple[_InterfaceRepository, _ClassificationRepository],
) -> None:
    rotated = interface_services.rotate_user_token(
        actor_user_id=1,
        target_user_id=7,
        token_name="admin",
        access_level="read_write",
    )
    revoked = interface_services.revoke_access_token(3)
    toggled = interface_services.toggle_user_mcp(7)

    assert rotated.username == "owner"
    assert rotated.payload is not None
    assert revoked.message == "已撤销 owner 的 Token：token-3"
    assert "已开启用户 user-7" in toggled.message
    assert "系统默认：关闭" in toggled.message
