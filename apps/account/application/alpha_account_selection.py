"""Resolve an owned investment account to its Alpha portfolio context."""

from typing import cast

from apps.account.application.interface_services import list_investment_account_options
from apps.account.application.portfolio_api_contracts import PortfolioApiRepository
from apps.account.application.repository_provider import get_portfolio_api_repository
from core.exceptions import AuthorizationError, ValidationError


def resolve_alpha_account_portfolio(*, user_id: int, account_id: int) -> int:
    """Return the owned account's active portfolio without creating a mapping."""

    if not any(
        option["value"] == account_id for option in list_investment_account_options(user_id)
    ):
        raise AuthorizationError("所选投资账户不可用，请选择本人名下的账户。")
    repository = cast(PortfolioApiRepository, get_portfolio_api_repository())
    portfolio = repository.get_portfolio_for_account(account_id)
    if portfolio is None or not portfolio.is_active:
        raise ValidationError("所选账户尚未关联有效投资组合，请先完成账户与组合关联。")
    if portfolio.user_id != user_id:
        raise AuthorizationError("所选账户关联的组合不属于当前用户。")
    return portfolio.id
