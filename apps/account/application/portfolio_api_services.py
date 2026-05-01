"""Application services for the account portfolio/position API boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.account.application.repository_provider import (
    get_account_interface_repository,
    get_account_position_repository,
    get_portfolio_api_repository,
)
from apps.simulated_trading.application.unified_position_service import (
    UnifiedPositionService,
)


class PortfolioNotFoundError(LookupError):
    """Raised when the target portfolio does not exist."""


class PositionNotFoundError(LookupError):
    """Raised when the target position does not exist."""


class PortfolioAccessDeniedError(PermissionError):
    """Raised when the current user cannot access the target portfolio."""


class PositionMutationDeniedError(PermissionError):
    """Raised when the current user cannot mutate the target position."""


@dataclass(frozen=True)
class PortfolioAccessContext:
    """Resolved portfolio access context for API handlers."""

    portfolio: Any
    is_owner: bool


def _portfolio_api_repo():
    """Return the portfolio API repository."""

    return get_portfolio_api_repository()


def _interface_repo():
    """Return the account interface repository."""

    return get_account_interface_repository()


def _position_repo():
    """Return the legacy account position repository."""

    return get_account_position_repository()


def _map_account_asset_type(asset_class: str) -> str:
    """Map account asset classes to unified ledger asset types."""

    mapping = {
        "equity": "equity",
        "fund": "fund",
        "fixed_income": "bond",
        "commodity": "equity",
        "currency": "fund",
        "cash": "fund",
        "derivative": "equity",
        "other": "equity",
    }
    return mapping.get(asset_class, "equity")


def get_accessible_portfolios_queryset(user_id: int):
    """Return the portfolios accessible to the current user."""

    return _interface_repo().get_accessible_portfolios_queryset(user_id)


def resolve_portfolio_for_user(*, user_id: int, portfolio_id: int | str) -> PortfolioAccessContext:
    """Resolve one portfolio and validate read access."""

    portfolio = _portfolio_api_repo().get_portfolio_with_owner(int(portfolio_id))
    if portfolio is None:
        raise PortfolioNotFoundError(f"投资组合 {portfolio_id} 不存在")
    return _validate_portfolio_access(user_id=user_id, portfolio=portfolio)


def get_portfolio_positions_payload(
    *,
    user_id: int,
    portfolio_id: int | str,
) -> tuple[PortfolioAccessContext, list[dict[str, Any]]]:
    """Return the portfolio positions payload for one accessible portfolio."""

    context = resolve_portfolio_for_user(user_id=user_id, portfolio_id=portfolio_id)
    account_id = _ensure_portfolio_ledger_synced(context.portfolio)
    positions = _portfolio_api_repo().list_unified_positions(account_ids=[account_id])
    payload = [
        _portfolio_api_repo().build_position_payload(position, context.portfolio)
        for position in positions
    ]
    return context, payload


def get_portfolio_statistics_payload(
    *,
    user_id: int,
    portfolio_id: int | str,
) -> tuple[PortfolioAccessContext, dict[str, Any]]:
    """Return summary statistics for one accessible portfolio."""

    context = resolve_portfolio_for_user(user_id=user_id, portfolio_id=portfolio_id)
    return context, _portfolio_api_repo().build_portfolio_statistics(context.portfolio)


def create_position_payload(
    *,
    user_id: int,
    portfolio_id: int | str | None,
    validated_data: dict[str, Any],
) -> dict[str, Any]:
    """Create one position via the unified ledger and return its response payload."""

    if portfolio_id in (None, ""):
        raise ValueError("缺少 portfolio 参数")

    context = resolve_portfolio_for_user(user_id=user_id, portfolio_id=portfolio_id)
    if not context.is_owner:
        raise PositionMutationDeniedError("观察员无权创建持仓，只有账户拥有者可以执行此操作")

    account_id = _ensure_portfolio_ledger_synced(context.portfolio)
    unified_model = UnifiedPositionService.default().create_position(
        account_id=account_id,
        asset_code=validated_data["asset_code"],
        shares=float(validated_data["shares"]),
        price=float(validated_data["avg_cost"]),
        current_price=float(validated_data.get("current_price") or validated_data["avg_cost"]),
        asset_type=_map_account_asset_type(validated_data.get("asset_class", "equity")),
        source=validated_data.get("source", "manual"),
        source_id=validated_data.get("source_id"),
    )
    _portfolio_api_repo().upsert_legacy_projection_from_unified(
        unified_position=unified_model,
        portfolio=context.portfolio,
        asset_class=validated_data.get("asset_class", "equity"),
        region=validated_data.get("region", "CN"),
        cross_border=validated_data.get("cross_border", "domestic"),
        category=validated_data.get("category"),
        currency=validated_data.get("currency"),
        source=validated_data.get("source", "manual"),
        source_id=validated_data.get("source_id"),
    )
    return _portfolio_api_repo().build_position_payload(unified_model, context.portfolio)


def get_position_payload(
    *,
    user_id: int,
    position_id: int | str,
) -> tuple[PortfolioAccessContext, dict[str, Any]]:
    """Return one accessible position payload."""

    unified_position, context = _resolve_position_context(
        user_id=user_id,
        position_id=int(position_id),
    )
    payload = _portfolio_api_repo().build_position_payload(
        unified_position,
        context.portfolio,
    )
    return context, payload


def update_position_payload(
    *,
    user_id: int,
    position_id: int | str,
    validated_data: dict[str, Any],
) -> dict[str, Any]:
    """Update one position via the unified ledger and return the response payload."""

    unified_position, context = _resolve_position_context(
        user_id=user_id,
        position_id=int(position_id),
    )
    if not context.is_owner:
        raise PositionMutationDeniedError("观察员无权更新持仓，只有账户拥有者可以执行此操作")

    legacy_projection = _portfolio_api_repo().get_legacy_projection_for_unified_position(
        unified_position.id
    )
    UnifiedPositionService.default().update_position(
        account_id=unified_position.account_id,
        asset_code=unified_position.asset_code,
        shares=float(validated_data["shares"]) if "shares" in validated_data else None,
        avg_cost=float(validated_data["avg_cost"]) if "avg_cost" in validated_data else None,
        current_price=float(validated_data["current_price"]) if "current_price" in validated_data else None,
    )
    unified_model = _portfolio_api_repo().get_unified_position(unified_position.id)
    if unified_model is None:
        raise PositionNotFoundError(f"持仓 {position_id} 不存在")

    _portfolio_api_repo().upsert_legacy_projection_from_unified(
        unified_position=unified_model,
        portfolio=context.portfolio,
        asset_class=legacy_projection.asset_class if legacy_projection else "equity",
        region=legacy_projection.region if legacy_projection else "CN",
        cross_border=legacy_projection.cross_border if legacy_projection else "domestic",
        category=legacy_projection.category if legacy_projection else None,
        currency=legacy_projection.currency if legacy_projection else None,
        source=legacy_projection.source if legacy_projection else "manual",
        source_id=legacy_projection.source_id if legacy_projection else unified_model.signal_id,
    )
    return _portfolio_api_repo().build_position_payload(unified_model, context.portfolio)


def delete_position(*, user_id: int, position_id: int | str) -> None:
    """Delete one position from the unified ledger and legacy projection."""

    unified_position, context = _resolve_position_context(
        user_id=user_id,
        position_id=int(position_id),
    )
    if not context.is_owner:
        raise PositionMutationDeniedError("观察员无权删除持仓，只有账户拥有者可以执行此操作")

    legacy_projection = _portfolio_api_repo().get_legacy_projection_for_unified_position(
        unified_position.id
    )
    _portfolio_api_repo().delete_unified_position(unified_position.id)
    _portfolio_api_repo().delete_position_mapping_for_target(unified_position.id)
    if legacy_projection is not None:
        _portfolio_api_repo().delete_legacy_projection(legacy_projection)


def list_positions_payload(
    *,
    user_id: int,
    portfolio_id: int | str | None = None,
    asset_code: str | None = None,
) -> tuple[list[dict[str, Any]], list[Any]]:
    """Return unified position payloads for all accessible portfolios."""

    portfolios = get_accessible_portfolios_queryset(user_id).select_related("user", "base_currency")
    if portfolio_id not in (None, ""):
        portfolios = portfolios.filter(id=int(portfolio_id))
    portfolios = list(portfolios)

    account_to_portfolio: dict[int, Any] = {}
    observer_portfolios: list[Any] = []
    for portfolio in portfolios:
        account_to_portfolio[_ensure_portfolio_ledger_synced(portfolio)] = portfolio
        if portfolio.user_id != user_id:
            observer_portfolios.append(portfolio)

    if not account_to_portfolio:
        return [], observer_portfolios

    unified_positions = _portfolio_api_repo().list_unified_positions(
        account_ids=list(account_to_portfolio.keys()),
        asset_code=asset_code,
    )
    payload = [
        _portfolio_api_repo().build_position_payload(
            unified_position,
            account_to_portfolio.get(unified_position.account_id),
        )
        for unified_position in unified_positions
    ]
    return payload, observer_portfolios


def close_position_payload(
    *,
    user_id: int,
    position_id: int | str,
    close_shares: float | None,
) -> dict[str, Any]:
    """Close one position and return the resulting response payload."""

    unified_position, context = _resolve_position_context(
        user_id=user_id,
        position_id=int(position_id),
    )
    if not context.is_owner:
        raise PositionMutationDeniedError("观察员无权执行平仓操作，只有账户拥有者可以平仓")

    legacy_projection = _portfolio_api_repo().get_legacy_projection_for_unified_position(
        unified_position.id
    )
    if legacy_projection is not None and legacy_projection.is_closed:
        raise ValueError("该持仓已平仓")

    result = UnifiedPositionService.default().close_position(
        account_id=unified_position.account_id,
        asset_code=unified_position.asset_code,
        close_shares=close_shares,
        reason="账户平仓",
    )

    if legacy_projection is not None:
        closed_position = _position_repo().close_position(
            legacy_projection.id,
            close_shares,
        )
        if closed_position is None:
            raise RuntimeError("平仓失败")
        legacy_projection = _portfolio_api_repo().get_legacy_position_by_id(legacy_projection.id)

    if result is None:
        _portfolio_api_repo().delete_position_mapping_for_target(unified_position.id)
        return _portfolio_api_repo().build_closed_position_payload(
            unified_position=unified_position,
            portfolio=context.portfolio,
            legacy_projection=legacy_projection,
        )

    unified_model = _portfolio_api_repo().get_unified_position_for_account_asset(
        account_id=unified_position.account_id,
        asset_code=unified_position.asset_code,
    )
    if unified_model is None:
        raise PositionNotFoundError(f"持仓 {position_id} 不存在")

    if legacy_projection is not None:
        _portfolio_api_repo().upsert_legacy_projection_from_unified(
            unified_position=unified_model,
            portfolio=context.portfolio,
            asset_class=legacy_projection.asset_class,
            region=legacy_projection.region,
            cross_border=legacy_projection.cross_border,
            category=legacy_projection.category,
            currency=legacy_projection.currency,
            source=legacy_projection.source,
            source_id=legacy_projection.source_id,
        )
    return _portfolio_api_repo().build_position_payload(unified_model, context.portfolio)


def _validate_portfolio_access(*, user_id: int, portfolio) -> PortfolioAccessContext:
    """Validate whether the current user can access one portfolio."""

    if portfolio.user_id == user_id:
        return PortfolioAccessContext(portfolio=portfolio, is_owner=True)

    grant = _portfolio_api_repo().get_active_observer_grant(
        owner_user_id=portfolio.user_id,
        observer_user_id=user_id,
    )
    if grant is not None:
        if grant.is_valid():
            return PortfolioAccessContext(portfolio=portfolio, is_owner=False)
        raise PortfolioAccessDeniedError("观察员授权已过期")

    revoked_grant = _portfolio_api_repo().get_inactive_observer_grant(
        owner_user_id=portfolio.user_id,
        observer_user_id=user_id,
    )
    if revoked_grant is not None:
        raise PortfolioAccessDeniedError(f"观察员授权已{revoked_grant.get_status_display()}")
    raise PortfolioAccessDeniedError("无权访问此投资组合")


def _ensure_portfolio_ledger_synced(portfolio) -> int:
    """Ensure the portfolio and its open legacy positions exist in the unified ledger."""

    account_id = _portfolio_api_repo().ensure_real_account(portfolio)
    for legacy_position in _portfolio_api_repo().list_open_legacy_positions(portfolio):
        _sync_unified_position_from_legacy(legacy_position)
    return account_id


def _sync_unified_position_from_legacy(legacy_position):
    """Bootstrap one legacy position into the unified ledger when needed."""

    existing_mapping = _portfolio_api_repo().get_position_mapping_for_source(legacy_position.id)
    if existing_mapping is not None:
        unified_existing = _portfolio_api_repo().get_unified_position(existing_mapping.target_id)
        if unified_existing is not None:
            return unified_existing
        _portfolio_api_repo().delete_position_mapping_for_source(legacy_position.id)

    unified_model = UnifiedPositionService.default().create_position(
        account_id=_portfolio_api_repo().ensure_real_account(legacy_position.portfolio),
        asset_code=legacy_position.asset_code,
        shares=float(legacy_position.shares),
        price=float(legacy_position.avg_cost),
        current_price=float(legacy_position.current_price or legacy_position.avg_cost),
        asset_name=legacy_position.asset_code,
        asset_type=_map_account_asset_type(legacy_position.asset_class),
        source=legacy_position.source,
        source_id=legacy_position.source_id,
        entry_reason=f"bootstrap from account.position:{legacy_position.id}",
    )
    _portfolio_api_repo().create_position_mapping(
        source_id=legacy_position.id,
        target_id=unified_model.id,
    )
    return unified_model


def _resolve_position_context(
    *,
    user_id: int,
    position_id: int,
) -> tuple[Any, PortfolioAccessContext]:
    """Resolve one position from the unified ledger or legacy projection."""

    unified_position = _portfolio_api_repo().get_unified_position(position_id)
    if unified_position is not None:
        portfolio = _portfolio_api_repo().get_portfolio_for_account(unified_position.account_id)
        if portfolio is None:
            raise PositionNotFoundError(f"持仓 {position_id} 不存在")
        return unified_position, _validate_portfolio_access(user_id=user_id, portfolio=portfolio)

    legacy_projection = _portfolio_api_repo().get_legacy_position_by_id(position_id)
    if legacy_projection is None:
        raise PositionNotFoundError(f"持仓 {position_id} 不存在")

    context = _validate_portfolio_access(
        user_id=user_id,
        portfolio=legacy_projection.portfolio,
    )
    return _sync_unified_position_from_legacy(legacy_projection), context
