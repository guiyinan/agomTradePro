"""Account profile and account-classification repository owners."""

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from django.contrib.auth.models import User
from django.db import transaction

from apps.account.application.simulated_trading_gateway import (
    list_investment_account_payloads,
)
from apps.account.domain.entities import (
    AccountProfile,
    RiskTolerance,
)
from apps.account.infrastructure.models import (
    AccountProfileModel,
    AssetCategoryModel,
    CurrencyModel,
    ExchangeRateModel,
    PortfolioModel,
    PositionModel,
)

logger = logging.getLogger(__name__)


class AccountRepository:
    """用户账户仓储"""

    def list_investment_accounts(self, user_id: int) -> list[dict[str, Any]]:
        """返回用户投资组合账户摘要，供 Interface 层只读展示。"""
        return list_investment_account_payloads(user_id)

    def get_by_user_id(self, user_id: int) -> AccountProfile | None:
        """根据用户ID获取账户配置"""
        try:
            model = AccountProfileModel._default_manager.get(user_id=user_id)
            return AccountProfile(
                user_id=model.user_id,
                display_name=model.display_name,
                initial_capital=model.initial_capital,
                risk_tolerance=RiskTolerance(model.risk_tolerance),
                created_at=model.created_at,
            )
        except AccountProfileModel.DoesNotExist:
            return None

    def create_default_profile(self, user_id: int) -> AccountProfile:
        """为用户创建默认账户配置（接受user_id）"""
        try:
            user = User._default_manager.get(id=user_id)
        except User.DoesNotExist:
            raise ValueError(f"用户 {user_id} 不存在") from None

        return self.create_default_account(user)

    def get_or_create_default_portfolio(self, user_id: int) -> int:
        """获取或创建默认投资组合，返回portfolio_id"""
        portfolio, created = PortfolioModel._default_manager.get_or_create(
            user_id=user_id, name="默认组合", defaults={"is_active": True}
        )
        return portfolio.id

    def create_default_account(self, user: User) -> AccountProfile:
        """为新用户创建默认账户配置"""
        profile = AccountProfileModel._default_manager.create(
            user=user,
            display_name=user.username,
            initial_capital=Decimal("1000000.00"),
            risk_tolerance="moderate",
        )
        PortfolioModel._default_manager.create(
            user=user,
            name="默认组合",
            is_active=True,
        )
        return AccountProfile(
            user_id=profile.user_id,
            display_name=profile.display_name,
            initial_capital=profile.initial_capital,
            risk_tolerance=RiskTolerance(profile.risk_tolerance),
            created_at=profile.created_at,
        )

    def get_volatility_settings(self, user_id: int) -> dict[str, Any] | None:
        """获取用户波动率控制配置。"""
        try:
            model = AccountProfileModel._default_manager.get(user_id=user_id)
        except AccountProfileModel.DoesNotExist:
            return None

        return {
            "user_id": model.user_id,
            "target_volatility": model.target_volatility,
            "volatility_tolerance": model.volatility_tolerance,
            "max_volatility_reduction": model.max_volatility_reduction,
        }

    def update_volatility_settings(
        self,
        user_id: int,
        *,
        target_volatility: float | None = None,
        volatility_tolerance: float | None = None,
        max_volatility_reduction: float | None = None,
    ) -> dict[str, Any] | None:
        """更新用户波动率控制配置。"""
        try:
            model = AccountProfileModel._default_manager.get(user_id=user_id)
        except AccountProfileModel.DoesNotExist:
            return None

        if target_volatility is not None:
            model.target_volatility = target_volatility
        if volatility_tolerance is not None:
            model.volatility_tolerance = volatility_tolerance
        if max_volatility_reduction is not None:
            model.max_volatility_reduction = max_volatility_reduction
        model.save(
            update_fields=[
                "target_volatility",
                "volatility_tolerance",
                "max_volatility_reduction",
                "updated_at",
            ]
        )
        return self.get_volatility_settings(user_id)


class AccountClassificationRepository:
    """Classification and FX persistence helpers for interface/application layers."""

    def list_active_asset_categories(self) -> Any:
        """Return active asset categories with related parent/children loaded."""

        return (
            AssetCategoryModel._default_manager.filter(is_active=True)
            .select_related("parent")
            .prefetch_related("children")
            .order_by("path", "sort_order")
        )

    def list_root_asset_categories(self) -> Any:
        """Return active root-level asset categories."""

        return self.list_active_asset_categories().filter(level=1)

    def list_tree_root_asset_categories(self) -> Any:
        """Return active root categories without parents."""

        return self.list_active_asset_categories().filter(level=1, parent__isnull=True)

    def list_child_asset_categories(self, category_id: int) -> Any:
        """Return active child categories for one parent."""

        return (
            AssetCategoryModel._default_manager.filter(parent_id=category_id, is_active=True)
            .select_related("parent")
            .order_by("sort_order")
        )

    def create_asset_category(self, **validated_data: Any) -> Any:
        """Create one asset category."""

        parent = validated_data.get("parent")
        name = str(validated_data["name"]).strip()
        validated_data["name"] = name
        validated_data["level"] = parent.level + 1 if parent is not None else 1
        validated_data["path"] = f"{parent.path}/{name}" if parent is not None else name
        return AssetCategoryModel._default_manager.create(**validated_data)

    def update_asset_category(
        self,
        *,
        category_id: int,
        **validated_data: Any,
    ) -> Any:
        """Update one asset category and return the refreshed model."""

        with transaction.atomic():
            model = AssetCategoryModel._default_manager.select_for_update().get(id=category_id)
            parent = validated_data.get("parent", model.parent)
            if self._category_parent_would_cycle(category=model, parent=parent):
                raise ValueError("资产分类不能移动到自身或其后代节点下")
            for field, value in validated_data.items():
                setattr(model, field, value)
            model.name = str(model.name).strip()
            model.level = parent.level + 1 if parent is not None else 1
            model.path = f"{parent.path}/{model.name}" if parent is not None else model.name
            model.save()
            self._refresh_category_descendants(model)
        return model

    @staticmethod
    def _category_parent_would_cycle(*, category: Any, parent: Any | None) -> bool:
        """Return whether assigning parent would create a category cycle."""

        seen: set[int] = set()
        current = parent
        while current is not None:
            current_id = int(current.id)
            if current_id == int(category.id) or current_id in seen:
                return True
            seen.add(current_id)
            current = current.parent
        return False

    def _refresh_category_descendants(self, parent: Any) -> None:
        """Refresh materialized level/path values after a parent rename or move."""

        for child in AssetCategoryModel._default_manager.select_for_update().filter(
            parent_id=parent.id
        ):
            child.level = parent.level + 1
            child.path = f"{parent.path}/{child.name}"
            child.save(update_fields=["level", "path", "updated_at"])
            self._refresh_category_descendants(child)

    def delete_asset_category(self, *, category_id: int) -> None:
        """Delete one asset category."""

        AssetCategoryModel._default_manager.filter(id=category_id).delete()

    def list_active_currencies(self) -> Any:
        """Return active currencies."""

        return CurrencyModel._default_manager.filter(is_active=True).order_by("-is_base", "code")

    def get_base_currency(self) -> Any:
        """Return the configured base currency."""

        return (
            self.list_active_currencies().filter(is_base=True).first()
            or self.list_active_currencies().filter(code="CNY").first()
        )

    def active_currency_codes_exist(self, codes: set[str]) -> bool:
        """Return whether every requested currency code is active and registered."""

        return bool(
            self.list_active_currencies().filter(code__in=codes).values("code").distinct().count()
            == len(codes)
        )

    def list_exchange_rates(self) -> Any:
        """Return exchange rates with currency relations loaded."""

        return (
            ExchangeRateModel._default_manager.select_related("from_currency", "to_currency")
            .all()
            .order_by("-effective_date")
        )

    def create_exchange_rate(self, **validated_data: Any) -> Any:
        """Create one exchange rate."""

        return ExchangeRateModel._default_manager.create(**validated_data)

    def update_exchange_rate(
        self,
        *,
        exchange_rate_id: int,
        **validated_data: Any,
    ) -> Any:
        """Update one exchange rate and return the refreshed model."""

        model = ExchangeRateModel._default_manager.get(id=exchange_rate_id)
        for field, value in validated_data.items():
            setattr(model, field, value)
        model.save()
        return model

    def delete_exchange_rate(self, *, exchange_rate_id: int) -> None:
        """Delete one exchange rate."""

        ExchangeRateModel._default_manager.filter(id=exchange_rate_id).delete()

    def get_latest_exchange_rate(self, *, from_code: str, to_code: str) -> Any:
        """Return the latest exchange rate for one currency pair."""

        return (
            self.list_exchange_rates()
            .filter(
                from_currency__code=from_code,
                to_currency__code=to_code,
            )
            .first()
        )

    def get_exchange_rate_for_conversion(
        self,
        *,
        from_code: str,
        to_code: str,
        date_value: date | None = None,
    ) -> Any:
        """Return the effective exchange rate used for conversion."""

        queryset = self.list_exchange_rates().filter(
            from_currency__code=from_code,
            to_currency__code=to_code,
        )
        if date_value:
            queryset = queryset.filter(effective_date__lte=date_value)
        return queryset.first()

    def convert_amount(
        self,
        *,
        amount: Decimal,
        from_code: str,
        to_code: str,
        date_value: date | None = None,
    ) -> Decimal:
        """Convert one amount between currencies."""

        if from_code == to_code:
            return amount

        rate_model = self.get_exchange_rate_for_conversion(
            from_code=from_code,
            to_code=to_code,
            date_value=date_value,
        )
        if rate_model is None:
            raise ValueError(f"No exchange rate found for {from_code} -> {to_code}")
        return Decimal(str(rate_model.convert(amount)))

    def get_portfolio_for_user(self, *, portfolio_id: int, user_id: int) -> Any:
        """Return one portfolio owned by the given user."""

        return (
            PortfolioModel._default_manager.select_related("base_currency")
            .filter(id=portfolio_id, user_id=user_id)
            .first()
        )

    def list_portfolio_allocation_rows(self, *, portfolio_id: int) -> list[dict[str, Any]]:
        """Return position rows required for category/currency allocation summaries."""

        positions = (
            PositionModel._default_manager.filter(portfolio_id=portfolio_id, is_closed=False)
            .select_related("category", "currency")
            .order_by("id")
        )
        return [
            {
                "category_path": (
                    position.category.get_full_path() if position.category else "未分类"
                ),
                "currency_code": position.currency.code if position.currency else "CNY",
                "currency_name": position.currency.name if position.currency else "CNY",
                "amount": position.market_value,
            }
            for position in positions
        ]
