"""Owner-bound account selection for the manual auto-trading API."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from apps.simulated_trading.application import interface_services


def _account_row(
    account_id: int,
    *,
    user_id: int = 17,
    account_type: str = "simulated",
    is_active: bool = True,
    auto_trading_enabled: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=account_id,
        user_id=user_id,
        account_type=account_type,
        is_active=is_active,
        auto_trading_enabled=auto_trading_enabled,
    )


@pytest.mark.parametrize("is_superuser", [False, True])
def test_default_scope_is_only_the_users_active_enabled_simulated_accounts(
    monkeypatch: pytest.MonkeyPatch,
    is_superuser: bool,
) -> None:
    repository = SimpleNamespace(
        get_active_account_models_for_user=Mock(
            return_value=[
                _account_row(1),
                _account_row(2, account_type="real"),
                _account_row(3, auto_trading_enabled=False),
            ]
        )
    )
    repository_factory = Mock(return_value=repository)
    monkeypatch.setattr(
        interface_services,
        "get_simulated_account_repository",
        repository_factory,
    )
    user = SimpleNamespace(id=17, is_authenticated=True, is_superuser=is_superuser)

    result = interface_services.resolve_auto_trading_account_scope(user, None)

    assert result.allowed is True
    assert result.account_ids == (1,)
    repository.get_active_account_models_for_user.assert_called_once_with(17)


def test_default_scope_rejects_more_than_the_technical_account_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    too_many_accounts = [
        _account_row(account_id)
        for account_id in range(1, interface_services.MAX_AUTO_TRADING_ACCOUNT_SCOPE_SIZE + 2)
    ]
    repository = SimpleNamespace(
        get_active_account_models_for_user=Mock(return_value=too_many_accounts)
    )
    monkeypatch.setattr(
        interface_services,
        "get_simulated_account_repository",
        Mock(return_value=repository),
    )

    result = interface_services.resolve_auto_trading_account_scope(
        SimpleNamespace(id=17, is_authenticated=True, is_superuser=False),
        None,
    )

    assert result.allowed is False
    assert result.status_code == 400
    assert result.account_ids is None


def test_explicit_empty_scope_is_preserved_without_repository_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_factory = Mock(side_effect=AssertionError("empty scope must not read accounts"))
    access_check = Mock(side_effect=AssertionError("empty scope has no account to authorize"))
    monkeypatch.setattr(
        interface_services,
        "get_simulated_account_repository",
        repository_factory,
    )
    monkeypatch.setattr(interface_services, "get_account_access", access_check)

    result = interface_services.resolve_auto_trading_account_scope(
        SimpleNamespace(id=17, is_authenticated=True, is_superuser=False),
        [],
    )

    assert result.allowed is True
    assert result.account_ids == ()
    repository_factory.assert_not_called()
    access_check.assert_not_called()


@pytest.mark.parametrize(
    ("user", "requested_ids", "expected_status"),
    [
        (SimpleNamespace(id=17, is_authenticated=False), None, 401),
        (SimpleNamespace(id=17, is_authenticated=1), None, 401),
        (SimpleNamespace(id=None, is_authenticated=True), None, 401),
        (SimpleNamespace(id=17, is_authenticated=True), cast(list[int], [True]), 400),
        (SimpleNamespace(id=17, is_authenticated=True), cast(list[int], [0]), 400),
        (SimpleNamespace(id=17, is_authenticated=True), cast(list[int], [1, 1]), 400),
        (
            SimpleNamespace(id=17, is_authenticated=True),
            cast(
                list[int],
                list(range(1, interface_services.MAX_AUTO_TRADING_ACCOUNT_SCOPE_SIZE + 2)),
            ),
            400,
        ),
    ],
)
def test_invalid_identity_or_scope_fails_before_repository_access(
    monkeypatch: pytest.MonkeyPatch,
    user: SimpleNamespace,
    requested_ids: list[int] | None,
    expected_status: int,
) -> None:
    repository_factory = Mock(side_effect=AssertionError("invalid scope must not query"))
    monkeypatch.setattr(
        interface_services,
        "get_simulated_account_repository",
        repository_factory,
    )

    result = interface_services.resolve_auto_trading_account_scope(user, requested_ids)

    assert result.allowed is False
    assert result.status_code == expected_status
    assert result.account_ids is None
    repository_factory.assert_not_called()


def test_explicit_accounts_use_existing_access_policy_and_preserve_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=17, is_authenticated=True, is_superuser=False)
    rows = {9: _account_row(9), 4: _account_row(4)}
    access_check = Mock(
        side_effect=lambda checked_user, account_id, action: SimpleNamespace(
            allowed=checked_user is user,
            account=rows[account_id],
            error=None,
            status_code=None,
        )
    )
    monkeypatch.setattr(interface_services, "get_account_access", access_check)
    monkeypatch.setattr(
        interface_services,
        "get_simulated_account_repository",
        Mock(side_effect=AssertionError("explicit scope must use ownership checks")),
    )

    result = interface_services.resolve_auto_trading_account_scope(user, [9, 4])

    assert result.allowed is True
    assert result.account_ids == (9, 4)
    assert [call.args[1] for call in access_check.call_args_list] == [9, 4]


def test_first_denied_explicit_account_stops_before_checking_later_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=17, is_authenticated=True, is_superuser=False)
    access_check = Mock(
        return_value=SimpleNamespace(
            allowed=False,
            account=None,
            error="无权执行自动交易该账户",
            status_code=403,
        )
    )
    monkeypatch.setattr(interface_services, "get_account_access", access_check)

    result = interface_services.resolve_auto_trading_account_scope(user, [9, 4])

    assert result.allowed is False
    assert result.status_code == 403
    assert result.account_ids is None
    access_check.assert_called_once()


@pytest.mark.parametrize(
    "accounts",
    [
        [_account_row(9, user_id=18)],
        [
            SimpleNamespace(
                id=0,
                user_id=17,
                account_type="simulated",
                is_active=True,
                auto_trading_enabled=True,
            )
        ],
        [_account_row(9), _account_row(9)],
    ],
)
def test_default_scope_rejects_corrupt_or_cross_user_repository_rows(
    monkeypatch: pytest.MonkeyPatch,
    accounts: list[SimpleNamespace],
) -> None:
    repository = SimpleNamespace(get_active_account_models_for_user=Mock(return_value=accounts))
    monkeypatch.setattr(
        interface_services,
        "get_simulated_account_repository",
        Mock(return_value=repository),
    )

    result = interface_services.resolve_auto_trading_account_scope(
        SimpleNamespace(id=17, is_authenticated=True, is_superuser=False),
        None,
    )

    assert result.allowed is False
    assert result.status_code == 500
    assert result.account_ids is None


@pytest.mark.parametrize(
    ("account", "message"),
    [
        (_account_row(9, account_type="real"), "自动交易仅支持模拟账户"),
        (_account_row(9, is_active=False), "所选账户未启用"),
        (_account_row(9, auto_trading_enabled=False), "所选账户未启用自动交易"),
    ],
)
def test_explicit_accounts_must_be_enabled_simulated_accounts(
    monkeypatch: pytest.MonkeyPatch,
    account: SimpleNamespace,
    message: str,
) -> None:
    user = SimpleNamespace(id=17, is_authenticated=True, is_superuser=False)
    monkeypatch.setattr(
        interface_services,
        "get_account_access",
        Mock(
            return_value=SimpleNamespace(
                allowed=True,
                account=account,
                error=None,
                status_code=None,
            )
        ),
    )

    result = interface_services.resolve_auto_trading_account_scope(user, [9])

    assert result.allowed is False
    assert result.status_code == 400
    assert result.error == message
    assert result.account_ids is None
