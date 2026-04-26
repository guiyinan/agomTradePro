"""Application-facing orchestration helpers for account interface views."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from django.utils import timezone

from apps.account.application.rbac import ROLE_CHOICES
from apps.account.application.use_cases import (
    CreatePositionFromBacktestInput,
    CreatePositionFromBacktestUseCase,
)
from apps.account.infrastructure.providers import (
    AccountClassificationRepository,
    AccountInterfaceRepository,
    AccountRepository,
    AssetMetadataRepository,
    PositionRepository,
)


@dataclass(frozen=True)
class FlashOutcome:
    """User-facing outcome for template views."""

    level: str
    message: str
    redirect_to: str | None = None


@dataclass(frozen=True)
class TokenCreationOutcome:
    """Token creation result for template views."""

    level: str
    message: str
    payload: dict[str, str] | None = None
    username: str | None = None
    token_name: str | None = None


_interface_repo = AccountInterfaceRepository
_classification_repo = AccountClassificationRepository


def get_system_settings():
    """Return the singleton system settings model."""

    return _interface_repo().get_system_settings()


def has_system_settings_singleton() -> bool:
    """Return whether the singleton settings row already exists."""

    return _interface_repo().has_system_settings_singleton()


def get_existing_system_settings():
    """Return the existing singleton settings row without creating one."""

    return _interface_repo().get_existing_system_settings()


def get_active_access_token(key: str):
    """Return one active access token when available."""

    return _interface_repo().get_active_access_token(key)


def touch_access_token(token) -> None:
    """Persist last-used metadata for one access token."""

    _interface_repo().touch_access_token(token)


def build_token_payload(*, username: str, token_name: str, token_value: str) -> dict[str, str] | None:
    """Build the session payload for newly created tokens when plaintext display is enabled."""

    settings_obj = get_system_settings()
    if not settings_obj.allow_token_plaintext_view:
        return None
    return {
        "username": username,
        "token_name": token_name,
        "token": token_value,
        "generated_at": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def provision_registered_user(
    *,
    user,
    display_name: str,
    system_settings,
    client_ip: str | None,
    approval_status: str,
    rbac_role: str,
) -> None:
    """Persist account scaffolding for a newly registered user."""

    _interface_repo().provision_registered_user(
        user=user,
        display_name=display_name,
        system_settings=system_settings,
        client_ip=client_ip,
        approval_status=approval_status,
        rbac_role=rbac_role,
    )


def build_profile_context(user_id: int) -> dict[str, Any]:
    """Build the HTML profile page context."""

    return _interface_repo().build_profile_context(user_id)


def build_settings_context(user_id: int) -> dict[str, Any]:
    """Build the HTML settings page context."""

    return _interface_repo().build_settings_context(user_id)


def update_account_settings(
    user_id: int,
    *,
    display_name: str,
    risk_tolerance: str,
    email: str,
    new_password: str,
) -> FlashOutcome:
    """Persist account settings edited from the template page."""

    password_updated = _interface_repo().update_account_settings(
        user_id,
        display_name=display_name,
        risk_tolerance=risk_tolerance,
        email=email,
        new_password=new_password,
    )
    if password_updated:
        return FlashOutcome(
            level="success",
            message="密码已修改，请重新登录",
            redirect_to="/account/login/",
        )
    return FlashOutcome(
        level="success",
        message="设置已保存",
        redirect_to="/account/settings/",
    )


def save_trading_cost_config(
    user_id: int,
    *,
    commission_rate: str,
    min_commission: str,
    stamp_duty_rate: str,
    transfer_fee_rate: str,
) -> FlashOutcome:
    """Persist trading cost settings for the user's active portfolio."""

    context = build_settings_context(user_id)
    portfolio = context["portfolio"]
    if portfolio is None:
        return FlashOutcome(
            level="error",
            message="暂无可配置的投资组合",
            redirect_to="/account/settings/",
        )

    _interface_repo().save_trading_cost_config(
        portfolio_id=portfolio.id,
        commission_rate=float(commission_rate or 0.00025),
        min_commission=float(min_commission or 5.0),
        stamp_duty_rate=float(stamp_duty_rate or 0.001),
        transfer_fee_rate=float(transfer_fee_rate or 0.00002),
    )
    return FlashOutcome(
        level="success",
        message="交易费率已保存",
        redirect_to="/account/settings/",
    )


def get_api_profile(user_id: int):
    """Return the account profile model for API serialization."""

    return _interface_repo().get_api_profile(user_id)


def update_api_profile(
    user_id: int,
    *,
    profile_data: Mapping[str, Any],
    email: str | None = None,
):
    """Persist API profile updates and return the refreshed profile model."""

    return _interface_repo().update_api_profile(
        user_id,
        profile_data=profile_data,
        email=email,
    )


def get_asset_category_queryset():
    """Return active asset categories for API listing/retrieval."""

    return _classification_repo().list_active_asset_categories()


def get_asset_category_roots():
    """Return active root-level asset categories."""

    return _classification_repo().list_root_asset_categories()


def get_asset_category_tree_roots():
    """Return active tree root categories."""

    return _classification_repo().list_tree_root_asset_categories()


def get_asset_category_children(*, category_id: int):
    """Return active child categories for one category."""

    return _classification_repo().list_child_asset_categories(category_id)


def create_asset_category(*, validated_data: Mapping[str, Any]):
    """Create one asset category from serializer-validated data."""

    return _classification_repo().create_asset_category(**dict(validated_data))


def update_asset_category(*, category_id: int, validated_data: Mapping[str, Any]):
    """Update one asset category from serializer-validated data."""

    return _classification_repo().update_asset_category(
        category_id=category_id,
        **dict(validated_data),
    )


def delete_asset_category(*, category_id: int) -> None:
    """Delete one asset category."""

    _classification_repo().delete_asset_category(category_id=category_id)


def get_currency_queryset():
    """Return active currencies for API listing/retrieval."""

    return _classification_repo().list_active_currencies()


def get_base_currency():
    """Return the configured base currency model."""

    return _classification_repo().get_base_currency()


def get_exchange_rate_queryset():
    """Return exchange rates for API listing/retrieval."""

    return _classification_repo().list_exchange_rates()


def create_exchange_rate(*, validated_data: Mapping[str, Any]):
    """Create one exchange rate from serializer-validated data."""

    return _classification_repo().create_exchange_rate(**dict(validated_data))


def update_exchange_rate(*, exchange_rate_id: int, validated_data: Mapping[str, Any]):
    """Update one exchange rate from serializer-validated data."""

    return _classification_repo().update_exchange_rate(
        exchange_rate_id=exchange_rate_id,
        **dict(validated_data),
    )


def delete_exchange_rate(*, exchange_rate_id: int) -> None:
    """Delete one exchange rate."""

    _classification_repo().delete_exchange_rate(exchange_rate_id=exchange_rate_id)


def get_latest_exchange_rate(*, from_code: str, to_code: str):
    """Return the latest exchange rate model for one pair."""

    return _classification_repo().get_latest_exchange_rate(from_code=from_code, to_code=to_code)


def convert_currency_amount(
    *,
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    date_value=None,
) -> dict[str, Any]:
    """Convert one amount and return the rate metadata used."""

    repository = _classification_repo()
    if from_currency == to_currency:
        return {
            "converted_amount": amount,
            "rate_used": Decimal("1"),
            "rate_date": date_value,
        }

    rate_model = repository.get_exchange_rate_for_conversion(
        from_code=from_currency,
        to_code=to_currency,
        date_value=date_value,
    )
    if rate_model is None:
        raise ValueError(f"No exchange rate found for {from_currency} -> {to_currency}")

    return {
        "converted_amount": rate_model.convert(amount),
        "rate_used": rate_model.rate,
        "rate_date": rate_model.effective_date,
    }


def get_portfolio_allocation_payload(
    *,
    portfolio_id: int,
    user_id: int,
    dimension: str,
) -> dict[str, Any] | None:
    """Return category/currency allocation payload for one owned portfolio."""

    repository = _classification_repo()
    portfolio = repository.get_portfolio_for_user(portfolio_id=portfolio_id, user_id=user_id)
    if portfolio is None:
        return None

    rows = repository.list_portfolio_allocation_rows(portfolio_id=portfolio.id)
    if dimension == "currency":
        base_currency = portfolio.base_currency or repository.get_base_currency()
        base_currency_code = getattr(base_currency, "code", "CNY")
        currency_totals: dict[str, dict[str, Any]] = {}
        total_value_base = Decimal("0")

        for row in rows:
            currency_code = row["currency_code"]
            amount = row["amount"]
            bucket = currency_totals.setdefault(
                currency_code,
                {
                    "currency_code": currency_code,
                    "currency_name": row["currency_name"],
                    "amount": Decimal("0"),
                    "amount_base": Decimal("0"),
                },
            )
            bucket["amount"] += amount
            try:
                amount_base = repository.convert_amount(
                    amount=amount,
                    from_code=currency_code,
                    to_code=base_currency_code,
                )
            except ValueError:
                amount_base = amount
            bucket["amount_base"] += amount_base
            total_value_base += amount_base

        data = [
            {
                **item,
                "percentage": (
                    float(item["amount_base"] / total_value_base * 100) if total_value_base > 0 else 0
                ),
            }
            for item in currency_totals.values()
        ]
        return {
            "dimension": "currency",
            "base_currency": base_currency_code,
            "total_value_base": total_value_base,
            "data": data,
        }

    category_totals: dict[str, Decimal] = {}
    total_value = Decimal("0")
    for row in rows:
        category_path = row["category_path"]
        amount = row["amount"]
        category_totals[category_path] = category_totals.get(category_path, Decimal("0")) + amount
        total_value += amount

    data = [
        {
            "category_path": category_path,
            "amount": amount,
            "percentage": float(amount / total_value * 100) if total_value > 0 else 0,
        }
        for category_path, amount in category_totals.items()
    ]
    return {
        "dimension": "category",
        "total_value": total_value,
        "data": data,
    }


def create_self_token(user_id: int, *, token_name: str) -> TokenCreationOutcome:
    """Create a token for the current user."""

    settings_context = _interface_repo().build_settings_context(user_id)
    profile = settings_context["profile"]
    if not profile.mcp_enabled:
        raise PermissionError("管理员已关闭您的 MCP/SDK 权限，暂时不能创建 Token")

    token, raw_key = _interface_repo().create_access_token(
        target_user_id=user_id,
        created_by_user_id=user_id,
        token_name=token_name,
    )
    payload = build_token_payload(
        username=token.user.username,
        token_name=token.name,
        token_value=raw_key,
    )
    if payload:
        message = f"已创建 Token：{token.name}"
    else:
        message = f"已创建 Token：{token.name}。当前系统禁止查看明文，请自行妥善管理。"
    return TokenCreationOutcome(
        level="success",
        message=message,
        payload=payload,
        username=token.user.username,
        token_name=token.name,
    )


def revoke_self_token(user_id: int, token_id: int) -> FlashOutcome:
    """Revoke one token owned by the current user."""

    try:
        token_name = _interface_repo().revoke_access_token_for_user(
            target_user_id=user_id,
            token_id=token_id,
        )
    except Exception as exc:
        if "DoesNotExist" in exc.__class__.__name__:
            raise LookupError("Token 不存在或已失效") from exc
        raise
    return FlashOutcome(level="success", message=f"已撤销 Token：{token_name}")


def create_capital_flow(
    user_id: int,
    *,
    flow_type: str,
    amount: Decimal,
    flow_date,
    notes: str,
) -> FlashOutcome:
    """Create a capital flow entry for the current user."""

    _interface_repo().create_capital_flow(
        user_id=user_id,
        flow_type=flow_type,
        amount=amount,
        flow_date=flow_date,
        notes=notes,
    )
    action_text = "入金" if flow_type == "deposit" else "出金"
    return FlashOutcome(level="success", message=f"{action_text}记录已添加：¥{amount:.2f}")


def apply_backtest_results(
    user_id: int,
    *,
    backtest_id: int,
    scale_factor: float,
) -> dict[str, Any]:
    """Apply backtest positions into the user's account."""

    use_case = CreatePositionFromBacktestUseCase(
        position_repo=PositionRepository(),
        account_repo=AccountRepository(),
        asset_meta_repo=AssetMetadataRepository(),
    )
    input_dto = CreatePositionFromBacktestInput(
        user_id=user_id,
        backtest_id=backtest_id,
        scale_factor=scale_factor,
    )
    result = use_case.execute(input_dto)
    return {
        "total_positions": result.total_positions,
        "total_value": result.total_value,
        "backtest_name": result.backtest_name,
    }


def build_user_management_context(status_filter: str, search_query: str) -> dict[str, Any]:
    """Build the admin user management page context."""

    context = _interface_repo().build_user_management_context(
        status_filter=status_filter,
        search_query=search_query,
    )
    context["role_choices"] = ROLE_CHOICES
    return context


def build_token_management_context(search_query: str, only_without_token: bool) -> dict[str, Any]:
    """Build the admin token management page context."""

    return _interface_repo().build_token_management_context(
        search_query=search_query,
        only_without_token=only_without_token,
    )


def rotate_user_token(*, actor_user_id: int, target_user_id: int, token_name: str) -> TokenCreationOutcome:
    """Create a token for another user as an administrator."""

    profile = _interface_repo().build_profile_context(target_user_id)["profile"]
    if not profile.mcp_enabled:
        raise PermissionError(f"用户 {profile.user.username} 的 MCP/SDK 权限已关闭，请先开启")

    token, raw_key = _interface_repo().create_access_token(
        target_user_id=target_user_id,
        created_by_user_id=actor_user_id,
        token_name=token_name,
    )
    payload = build_token_payload(
        username=token.user.username,
        token_name=token.name,
        token_value=raw_key,
    )
    if payload:
        message = f"已为用户 {token.user.username} 创建 Token：{token.name}"
    else:
        message = f"已为用户 {token.user.username} 创建 Token：{token.name}。当前系统禁止查看明文。"
    return TokenCreationOutcome(
        level="success",
        message=message,
        payload=payload,
        username=token.user.username,
        token_name=token.name,
    )


def revoke_user_tokens(target_user_id: int) -> dict[str, Any]:
    """Revoke all active tokens for a user."""

    result = _interface_repo().revoke_all_access_tokens_for_user(target_user_id=target_user_id)
    if result["deleted_count"] > 0:
        return {
            "level": "success",
            "message": f"已撤销用户 {result['username']} 的全部 Token",
            **result,
        }
    return {
        "level": "warning",
        "message": f"用户 {result['username']} 当前没有可撤销的 Token",
        **result,
    }


def revoke_access_token(token_id: int) -> FlashOutcome:
    """Revoke one token by id."""

    try:
        result = _interface_repo().revoke_access_token_by_id(token_id)
    except Exception as exc:
        if "DoesNotExist" in exc.__class__.__name__:
            raise LookupError("Token 不存在或已失效") from exc
        raise
    return FlashOutcome(
        level="success",
        message=f"已撤销 {result['username']} 的 Token：{result['token_name']}",
    )


def toggle_user_mcp(target_user_id: int) -> FlashOutcome:
    """Toggle a user's MCP permission."""

    result = _interface_repo().toggle_user_mcp(target_user_id)
    state = "开启" if result["mcp_enabled"] else "关闭"
    default_state = "开启" if result["default_mcp_enabled"] else "关闭"
    return FlashOutcome(
        level="success",
        message=f"已{state}用户 {result['username']} 的 MCP/SDK 权限（系统默认：{default_state}）",
    )


def approve_user(*, actor_user_id: int, target_user_id: int) -> FlashOutcome:
    """Approve a user and return the UI message."""

    result = _interface_repo().approve_user(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
    )
    return FlashOutcome(level=result["level"], message=result["message"])


def reject_user(*, actor_user_id: int, target_user_id: int, rejection_reason: str) -> FlashOutcome:
    """Reject a user and return the UI message."""

    result = _interface_repo().reject_user(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        rejection_reason=rejection_reason,
    )
    return FlashOutcome(level=result["level"], message=result["message"])


def set_user_role(*, target_user_id: int, raw_role: str) -> FlashOutcome:
    """Update a user's role after interface validation."""

    valid_values = {value for value, _ in ROLE_CHOICES}
    if raw_role not in valid_values:
        return FlashOutcome(level="error", message="无效的角色")
    result = _interface_repo().set_user_role(target_user_id=target_user_id, rbac_role=raw_role)
    return FlashOutcome(level=result["level"], message=result["message"])


def reset_user_status(*, actor_user_id: int, target_user_id: int) -> FlashOutcome:
    """Reset a user's approval status."""

    result = _interface_repo().reset_user_status(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
    )
    return FlashOutcome(level=result["level"], message=result["message"])


def build_system_settings_context() -> dict[str, Any]:
    """Build the admin system settings context."""

    return _interface_repo().build_system_settings_context()


def update_system_settings(data: Mapping[str, Any]) -> FlashOutcome:
    """Persist system settings from a form mapping."""

    _interface_repo().update_system_settings_from_mapping(data)
    return FlashOutcome(
        level="success",
        message="系统配置已更新",
        redirect_to="/account/admin/settings/",
    )


def build_collaboration_context(user_id: int) -> dict[str, Any]:
    """Build the collaboration page context."""

    return {
        "grant_count": _interface_repo().count_owned_active_observer_grants(user_id),
        "max_grants": 10,
    }


def build_observer_portal_context(user_id: int) -> dict[str, Any]:
    """Build the observer portal page context."""

    return {
        "observable_count": _interface_repo().count_observable_active_grants(user_id),
    }


def find_user_by_username(username: str):
    """Return one user by username when available."""

    return _interface_repo().find_user_by_username(username)


def find_user_by_id(user_id: int):
    """Return one user by id when available."""

    return _interface_repo().find_user_by_id(user_id)


def get_active_observer_grant(*, owner_user_id: int, observer_user_id: int):
    """Return one active observer grant for the owner/observer pair."""

    return _interface_repo().get_active_observer_grant(
        owner_user_id=owner_user_id,
        observer_user_id=observer_user_id,
    )


def count_owned_active_observer_grants(user_id: int) -> int:
    """Count active observer grants granted by the user."""

    return _interface_repo().count_owned_active_observer_grants(user_id)


def create_observer_grant_record(
    *,
    owner_user_id: int,
    observer_user_id: int,
    created_by_user_id: int,
    expires_at,
):
    """Create one observer grant record."""

    return _interface_repo().create_observer_grant(
        owner_user_id=owner_user_id,
        observer_user_id=observer_user_id,
        created_by_user_id=created_by_user_id,
        expires_at=expires_at,
    )


def has_active_observer_access(*, owner_user_id: int, observer_user_id: int) -> bool:
    """Return whether an observer currently has a valid portfolio-read grant."""

    return _interface_repo().has_active_observer_access(
        owner_user_id=owner_user_id,
        observer_user_id=observer_user_id,
    )


def get_accessible_portfolios_queryset(user_id: int):
    """Return the portfolio queryset accessible to the given user."""

    return _interface_repo().get_accessible_portfolios_queryset(user_id)


def get_asset_metadata_queryset():
    """Return the asset metadata queryset for API listing/retrieval."""

    return _interface_repo().get_asset_metadata_queryset()


def get_user_transaction_queryset(user_id: int):
    """Return transactions scoped to portfolios owned by the user."""

    return _interface_repo().get_user_transaction_queryset(user_id)


def get_user_capital_flow_queryset(user_id: int):
    """Return capital flows scoped to portfolios owned by the user."""

    return _interface_repo().get_user_capital_flow_queryset(user_id)


def get_user_portfolio(*, user_id: int, portfolio_id: int):
    """Return one owned portfolio when available."""

    return _interface_repo().get_user_portfolio(
        user_id=user_id,
        portfolio_id=portfolio_id,
    )


def get_account_health_payload(user_id: int) -> dict[str, Any]:
    """Return the account API health summary for one user."""

    return _interface_repo().get_account_health_payload(user_id)


def search_observer_candidates(*, owner_user_id: int, query: str) -> list[dict[str, Any]]:
    """Search active users for collaboration grants."""

    return _interface_repo().search_observer_candidates(
        owner_user_id=owner_user_id,
        query=query,
    )


def get_trading_cost_config_queryset(user_id: int):
    """Return trading cost configs for portfolios owned by the user."""

    return _interface_repo().get_trading_cost_config_queryset(user_id)


def save_api_trading_cost_config(
    *,
    actor_user_id: int,
    portfolio_id: int,
    validated_data: Mapping[str, Any],
):
    """Create or update one trading cost config from validated API data."""

    return _interface_repo().save_api_trading_cost_config(
        actor_user_id=actor_user_id,
        portfolio_id=portfolio_id,
        commission_rate=float(validated_data["commission_rate"]),
        min_commission=float(validated_data["min_commission"]),
        stamp_duty_rate=float(validated_data["stamp_duty_rate"]),
        transfer_fee_rate=float(validated_data["transfer_fee_rate"]),
        is_active=bool(validated_data.get("is_active", True)),
    )


def list_observer_grants_queryset(
    *,
    user_id: int,
    as_observer: bool,
    status_filter: str | None = None,
):
    """Return observer grants scoped to the current owner or observer view."""

    return _interface_repo().list_observer_grants_queryset(
        user_id=user_id,
        as_observer=as_observer,
        status_filter=status_filter,
    )


def get_observer_grant_by_id(grant_id):
    """Return one observer grant with related users when available."""

    return _interface_repo().get_observer_grant_by_id(grant_id)


def build_observer_positions_payload(owner_user_id: int) -> dict[str, Any]:
    """Return the active portfolio positions payload for observer access."""

    return _interface_repo().build_observer_positions_payload(owner_user_id)


def update_observer_grant(*, grant_id, expires_at):
    """Persist a grant expiry update and return the refreshed model."""

    return _interface_repo().update_observer_grant(
        grant_id=grant_id,
        expires_at=expires_at,
    )


def revoke_observer_grant(*, grant_id, revoked_by_user_id: int):
    """Revoke one observer grant and return the refreshed model."""

    return _interface_repo().revoke_observer_grant(
        grant_id=grant_id,
        revoked_by_user_id=revoked_by_user_id,
    )


def build_backup_download_payload(token: str) -> dict[str, Any]:
    """Validate a backup token and return the generated archive payload."""

    return _interface_repo().build_backup_download_payload(token)
