"""
DRF API Views for Account Module.

提供账户、投资组合、持仓、交易和资金流水的 RESTful API。
"""

from decimal import Decimal
from typing import Any

from django.db import models
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.infrastructure.models import (
    AccountProfileModel,
    AssetMetadataModel,
    CapitalFlowModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
    TradingCostConfigModel,
    TransactionModel,
)
from apps.account.infrastructure.repositories import (
    PortfolioRepository,
    PositionRepository,
)

from .permissions import GeneralPermission, ObserverAccessPermission, TradingPermission
from .serializers import (
    AccountProfileSerializer,
    AccountProfileUpdateSerializer,
    AssetMetadataSerializer,
    CapitalFlowCreateSerializer,
    CapitalFlowSerializer,
    ObserverGrantCreateSerializer,
    ObserverGrantSerializer,
    ObserverGrantUpdateSerializer,
    PortfolioCreateSerializer,
    PortfolioSerializer,
    PortfolioStatisticsSerializer,
    PositionCreateSerializer,
    PositionSerializer,
    PositionUpdateSerializer,
    TradingCostCalculationSerializer,
    TradingCostConfigCreateSerializer,
    TradingCostConfigSerializer,
    TransactionCreateSerializer,
    TransactionSerializer,
)


class UnifiedLedgerMixin:
    """Helpers for wiring account real-holding APIs to the unified ledger."""

    def _get_or_create_real_account(self, portfolio) -> int:
        from django.db import transaction as db_transaction

        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
            SimulatedAccountModel,
        )

        try:
            mapping = LedgerMigrationMapModel._default_manager.get(
                source_app="account",
                source_table="portfolio",
                source_id=portfolio.id,
            )
            return mapping.target_id
        except LedgerMigrationMapModel.DoesNotExist:
            pass

        with db_transaction.atomic():
            real_account = SimulatedAccountModel._default_manager.create(
                user=portfolio.user,
                account_name=portfolio.name,
                account_type="real",
                initial_capital=0,
                current_cash=0,
                current_market_value=0,
                total_value=0,
                is_active=portfolio.is_active,
                auto_trading_enabled=False,
            )
            LedgerMigrationMapModel._default_manager.create(
                source_app="account",
                source_table="portfolio",
                source_id=portfolio.id,
                target_table="simulated_account",
                target_id=real_account.id,
            )
        return real_account.id

    def _get_portfolio_for_account(self, account_id: int) -> PortfolioModel | None:
        from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel

        mapping = LedgerMigrationMapModel._default_manager.filter(
            source_app="account",
            source_table="portfolio",
            target_table="simulated_account",
            target_id=account_id,
        ).first()
        if not mapping:
            return None
        return PortfolioModel._default_manager.filter(id=mapping.source_id).first()

    def _get_legacy_projection_for_unified_position(self, unified_position_id: int) -> PositionModel | None:
        from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel

        mapping = LedgerMigrationMapModel._default_manager.filter(
            source_app="account",
            source_table="position",
            target_table="simulated_position",
            target_id=unified_position_id,
        ).first()
        if not mapping:
            return None
        return (
            PositionModel._default_manager.filter(pk=mapping.source_id)
            .select_related("portfolio", "category", "currency")
            .first()
        )

    def _sync_unified_position_from_legacy(self, legacy_position: PositionModel):
        """Bootstrap a legacy real holding into the unified ledger exactly once."""
        from apps.simulated_trading.application.unified_position_service import (
            UnifiedPositionService,
        )
        from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel
        from apps.simulated_trading.management.commands.migrate_account_ledger import (
            _map_asset_type,
        )

        existing = LedgerMigrationMapModel._default_manager.filter(
            source_app="account",
            source_table="position",
            source_id=legacy_position.id,
        ).first()
        if existing:
            from apps.simulated_trading.infrastructure.models import PositionModel as UnifiedPositionModel

            unified_existing = UnifiedPositionModel._default_manager.filter(pk=existing.target_id).first()
            if unified_existing is not None:
                return unified_existing
            existing.delete()

        unified_model = UnifiedPositionService.default().create_position(
            account_id=self._get_or_create_real_account(legacy_position.portfolio),
            asset_code=legacy_position.asset_code,
            shares=float(legacy_position.shares),
            price=float(legacy_position.avg_cost),
            current_price=float(legacy_position.current_price or legacy_position.avg_cost),
            asset_name=legacy_position.asset_code,
            asset_type=_map_asset_type(legacy_position.asset_class),
            source=legacy_position.source,
            source_id=legacy_position.source_id,
            entry_reason=f"bootstrap from account.position:{legacy_position.id}",
        )
        LedgerMigrationMapModel._default_manager.create(
            source_app="account",
            source_table="position",
            source_id=legacy_position.id,
            target_table="simulated_position",
            target_id=unified_model.id,
        )
        return unified_model

    def _ensure_portfolio_ledger_synced(self, portfolio) -> int:
        """
        Ensure a portfolio has a real account mapping and all active legacy positions
        are bootstrapped into the unified ledger.
        """
        account_id = self._get_or_create_real_account(portfolio)
        legacy_positions = (
            portfolio.positions.filter(is_closed=False)
            .select_related("category", "currency", "portfolio")
            .order_by("id")
        )
        for legacy_position in legacy_positions:
            self._sync_unified_position_from_legacy(legacy_position)
        return account_id

    def _sync_legacy_projection_from_unified(
        self,
        *,
        unified_position,
        portfolio,
        asset_class: str,
        region: str,
        cross_border: str,
        category=None,
        currency=None,
        source: str = "manual",
        source_id: int | None = None,
        close_projection: bool = False,
    ) -> PositionModel:
        """
        Keep apps/account.PositionModel as a read projection for account-specific fields.
        The unified ledger remains the source of truth.
        """
        from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel

        legacy_projection = self._get_legacy_projection_for_unified_position(unified_position.id)
        if legacy_projection is None:
            legacy_projection = PositionModel._default_manager.filter(
                portfolio=portfolio,
                asset_code=unified_position.asset_code,
                is_closed=False,
            ).first()

        if legacy_projection is None:
            legacy_projection = PositionModel._default_manager.create(
                portfolio=portfolio,
                asset_code=unified_position.asset_code,
                category=category,
                currency=currency,
                asset_class=asset_class,
                region=region,
                cross_border=cross_border,
                shares=float(unified_position.quantity),
                avg_cost=unified_position.avg_cost,
                current_price=unified_position.current_price,
                market_value=unified_position.market_value,
                unrealized_pnl=unified_position.unrealized_pnl,
                unrealized_pnl_pct=unified_position.unrealized_pnl_pct,
                source=source,
                source_id=source_id,
                is_closed=False,
            )
        else:
            legacy_projection.category = category
            legacy_projection.currency = currency
            legacy_projection.asset_class = asset_class
            legacy_projection.region = region
            legacy_projection.cross_border = cross_border
            legacy_projection.shares = float(unified_position.quantity)
            legacy_projection.avg_cost = unified_position.avg_cost
            legacy_projection.current_price = unified_position.current_price
            legacy_projection.market_value = unified_position.market_value
            legacy_projection.unrealized_pnl = unified_position.unrealized_pnl
            legacy_projection.unrealized_pnl_pct = unified_position.unrealized_pnl_pct
            legacy_projection.source = source
            legacy_projection.source_id = source_id
            if not close_projection:
                legacy_projection.is_closed = False
                legacy_projection.closed_at = None
            legacy_projection.save()

        LedgerMigrationMapModel._default_manager.update_or_create(
            source_app="account",
            source_table="position",
            source_id=legacy_projection.id,
            defaults={
                "target_table": "simulated_position",
                "target_id": unified_position.id,
            },
        )
        return legacy_projection

    def _build_position_payload(self, unified_position, portfolio: PortfolioModel | None = None) -> dict[str, Any]:
        legacy_projection = self._get_legacy_projection_for_unified_position(unified_position.id)
        if portfolio is None:
            portfolio = legacy_projection.portfolio if legacy_projection else self._get_portfolio_for_account(
                unified_position.account_id
            )

        asset_metadata = AssetMetadataModel._default_manager.filter(
            asset_code=unified_position.asset_code
        ).first()

        category = legacy_projection.category if legacy_projection else None
        currency = legacy_projection.currency if legacy_projection else getattr(portfolio, "base_currency", None)
        asset_class = (
            legacy_projection.asset_class
            if legacy_projection
            else getattr(asset_metadata, "asset_class", unified_position.asset_type)
        )
        region = (
            legacy_projection.region
            if legacy_projection
            else getattr(asset_metadata, "region", "CN")
        )
        cross_border = (
            legacy_projection.cross_border
            if legacy_projection
            else getattr(asset_metadata, "cross_border", "domestic")
        )

        return {
            "id": unified_position.id,
            "portfolio": portfolio.id if portfolio else None,
            "portfolio_name": portfolio.name if portfolio else "",
            "asset_code": unified_position.asset_code,
            "asset_name": getattr(asset_metadata, "name", None) or unified_position.asset_name or unified_position.asset_code,
            "category": category.id if category else None,
            "category_code": category.code if category else None,
            "category_name": category.name if category else None,
            "category_path": category.get_full_path() if category else None,
            "currency": currency.id if currency else None,
            "currency_code": currency.code if currency else None,
            "currency_name": currency.name if currency else None,
            "currency_symbol": currency.symbol if currency else None,
            "asset_class": asset_class,
            "region": region,
            "cross_border": cross_border,
            "shares": float(unified_position.quantity),
            "avg_cost": unified_position.avg_cost,
            "current_price": unified_position.current_price,
            "market_value": unified_position.market_value,
            "unrealized_pnl": unified_position.unrealized_pnl,
            "unrealized_pnl_pct": unified_position.unrealized_pnl_pct,
            "source": legacy_projection.source if legacy_projection else "manual",
            "source_id": unified_position.signal_id,
            "is_closed": False,
            "opened_at": legacy_projection.opened_at if legacy_projection else None,
            "closed_at": legacy_projection.closed_at if legacy_projection else None,
            "created_at": getattr(unified_position, "created_at", None),
            "updated_at": getattr(unified_position, "updated_at", None),
        }


# ==================== Portfolio ViewSet ====================

class PortfolioViewSet(UnifiedLedgerMixin, viewsets.ModelViewSet):
    """
    投资组合 API ViewSet

    提供以下接口:
    - GET /api/account/portfolios/ - 获取投资组合列表
    - POST /api/account/portfolios/ - 创建投资组合
    - GET /api/account/portfolios/{id}/ - 获取组合详情
    - PUT /api/account/portfolios/{id}/ - 更新组合
    - DELETE /api/account/portfolios/{id}/ - 删除组合
    - GET /api/account/portfolios/{id}/positions/ - 获取组合持仓
    - GET /api/account/portfolios/{id}/statistics/ - 获取统计信息

    权限说明:
    - 账户拥有者：完全访问权限
    - 观察员：只读权限（通过有效的 PortfolioObserverGrant）

    注意：观察员授权已撤销/过期时返回 403 而非 404
    """

    permission_classes = [IsAuthenticated, ObserverAccessPermission]

    def get_queryset(self):
        """返回用户可访问的投资组合（包括被授权观察的）"""
        from .permissions import get_accessible_portfolios
        return get_accessible_portfolios(self.request.user)

    def get_object(self):
        """
        获取单个对象，区分 404 和 403

        关键：观察员授权已撤销/过期时返回 403 而非 404
        """
        from django.core.exceptions import PermissionDenied
        from django.utils import timezone
        from rest_framework.exceptions import NotFound

        from apps.account.infrastructure.models import PortfolioModel, PortfolioObserverGrantModel

        # 先尝试获取对象（不限制 queryset）
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        pk = self.kwargs[lookup_url_kwarg]

        try:
            portfolio = PortfolioModel._default_manager.select_related('user').get(pk=pk)
        except (PortfolioModel.DoesNotExist, ValueError):
            raise NotFound(f"投资组合 {pk} 不存在")

        # 检查权限
        user = self.request.user

        # 1. 拥有者：完全访问权限
        if portfolio.user == user:
            # 检查对象级权限（ObserverAccessPermission.has_object_permission）
            self.check_object_permissions(self.request, portfolio)
            return portfolio

        # 2. 非拥有者：检查观察员授权
        now = timezone.now()
        try:
            grant = PortfolioObserverGrantModel._default_manager.get(
                owner_user_id=portfolio.user,
                observer_user_id=user,
                status='active',
            )

            # 检查授权是否有效（未过期）
            if grant.is_valid():
                # 有效授权：检查对象级权限
                self.check_object_permissions(self.request, portfolio)
                return portfolio
            else:
                # 授权已过期：返回 403
                raise PermissionDenied("观察员授权已过期")
        except PortfolioObserverGrantModel.DoesNotExist:
            # 检查是否存在已撤销的授权
            revoked_grant = PortfolioObserverGrantModel._default_manager.filter(
                owner_user_id=portfolio.user,
                observer_user_id=user,
            ).exclude(status='active').first()

            if revoked_grant:
                # 存在已撤销的授权：返回 403
                raise PermissionDenied(f"观察员授权已{revoked_grant.get_status_display()}")

        # 无任何授权：返回 403
        raise PermissionDenied("无权访问此投资组合")

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return PortfolioCreateSerializer
        return PortfolioSerializer

    def perform_create(self, serializer):
        """创建时自动关联当前用户（只有拥有者可以创建）"""
        serializer.save(user=self.request.user)

    def update(self, request, *args, **kwargs):
        """
        更新投资组合

        关键：观察员尝试更新时返回 403
        """
        portfolio = self.get_object()

        # 检查是否是拥有者
        if portfolio.user != request.user:
            return Response({
                'success': False,
                'error': '观察员无权更新投资组合，只有账户拥有者可以执行此操作'
            }, status=status.HTTP_403_FORBIDDEN)

        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """
        删除投资组合

        关键：观察员尝试删除时返回 403
        """
        portfolio = self.get_object()

        # 检查是否是拥有者
        if portfolio.user != request.user:
            return Response({
                'success': False,
                'error': '观察员无权删除投资组合，只有账户拥有者可以执行此操作'
            }, status=status.HTTP_403_FORBIDDEN)

        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['get'])
    def positions(self, request, pk=None):
        """
        获取投资组合的持仓列表

        GET /api/account/portfolios/{id}/positions/
        """
        portfolio = self.get_object()

        # 记录观察员访问审计日志
        self._log_observer_access_if_needed(request, portfolio, 'positions')

        from apps.simulated_trading.infrastructure.models import PositionModel as UnifiedPositionModel

        account_id = self._ensure_portfolio_ledger_synced(portfolio)
        positions = UnifiedPositionModel._default_manager.filter(account_id=account_id).select_related("account")
        payload = [self._build_position_payload(pos, portfolio) for pos in positions]
        serializer = PositionSerializer(payload, many=True)
        return Response({
            'success': True,
            'count': len(payload),
            'data': serializer.data
        })

    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """
        获取投资组合统计信息

        GET /api/account/portfolios/{id}/statistics/
        """
        portfolio = self.get_object()

        # 记录观察员访问审计日志
        self._log_observer_access_if_needed(request, portfolio, 'statistics')

        # 持仓统计
        positions = portfolio.positions.filter(is_closed=False)
        position_count = positions.count()

        total_value = positions.aggregate(total=Sum('market_value'))['total'] or Decimal('0')
        total_cost = positions.aggregate(
            total=Sum(
                models.F('shares') * models.F('avg_cost'),
                output_field=models.DecimalField(max_digits=20, decimal_places=2),
            )
        )['total'] or Decimal('0')
        total_pnl = total_value - total_cost
        total_pnl_pct = float((total_pnl / total_cost * 100) if total_cost > 0 else 0)

        # 资产类别分布
        asset_class_breakdown = {}
        for pos in positions:
            key = pos.get_asset_class_display()
            asset_class_breakdown[key] = asset_class_breakdown.get(key, 0) + float(pos.market_value)

        # 地区分布
        region_breakdown = {}
        for pos in positions:
            key = pos.get_region_display()
            region_breakdown[key] = region_breakdown.get(key, 0) + float(pos.market_value)

        # 资金流水
        capital_flows = CapitalFlowModel._default_manager.filter(portfolio=portfolio)
        total_inflow = capital_flows.filter(flow_type='deposit').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')
        total_outflow = capital_flows.filter(flow_type='withdraw').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        data = {
            'total_value': total_value,
            'total_cost': total_cost,
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'position_count': position_count,
            'asset_class_breakdown': asset_class_breakdown,
            'region_breakdown': region_breakdown,
            'total_capital_inflow': total_inflow,
            'total_capital_outflow': total_outflow,
            'net_capital_flow': total_inflow - total_outflow,
        }

        serializer = PortfolioStatisticsSerializer(data)
        return Response(serializer.data)

    def _log_observer_access_if_needed(self, request, portfolio, action: str):
        """
        记录观察员访问审计日志

        Args:
            request: 请求对象
            portfolio: 被访问的投资组合
            action: 操作动作（如 'positions', 'statistics'）
        """
        # 如果访问者不是拥有者，记录为观察员访问
        if portfolio.user != request.user:
            self._log_audit_action(
                request=request,
                action='READ',
                resource_type='portfolio_via_observer_grant',
                resource_id=str(portfolio.id),
                response_status=200,
                extra_context={
                    'portfolio_owner': portfolio.user.username,
                    'portfolio_name': portfolio.name,
                    'access_action': action,
                }
            )

    def _log_audit_action(self, request, action: str, resource_type: str,
                         resource_id: str, response_status: int, extra_context: dict = None):
        """
        记录审计日志

        Args:
            request: 请求对象
            action: 操作动作 (CREATE/DELETE/UPDATE/READ)
            resource_type: 资源类型
            resource_id: 资源ID
            response_status: 响应状态码
            extra_context: 额外上下文信息
        """
        try:
            import uuid

            from apps.audit.domain.entities import (
                OperationAction,
                OperationLog,
                OperationSource,
                OperationType,
            )
            from apps.audit.infrastructure.repositories import DjangoAuditRepository

            audit_repo = DjangoAuditRepository()

            # 构造审计日志实体
            log_entity = OperationLog.create(
                request_id=str(uuid.uuid4()),
                user_id=request.user.id,
                username=request.user.username,
                source=OperationSource.API,
                operation_type=OperationType.API_ACCESS,
                module='account',
                action=OperationAction[action],
                resource_type=resource_type,
                resource_id=resource_id,
                request_method=request.method,
                request_path=request.path,
                response_status=response_status,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            )

            audit_repo.save_operation_log(log_entity)

        except Exception as e:
            # 审计失败不影响主流程
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"记录审计日志失败: {e}", exc_info=True)

    @staticmethod
    def _get_client_ip(request):
        """获取客户端IP地址"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


# ==================== Position ViewSet ====================

class PositionViewSet(UnifiedLedgerMixin, viewsets.ModelViewSet):
    """
    持仓 API ViewSet

    提供以下接口:
    - GET /api/account/positions/ - 获取持仓列表
    - POST /api/account/positions/ - 创建持仓
    - GET /api/account/positions/{id}/ - 获取持仓详情
    - PUT /api/account/positions/{id}/ - 更新持仓
    - DELETE /api/account/positions/{id}/ - 删除持仓
    - POST /api/account/positions/{id}/close/ - 平仓

    权限说明:
    - 账户拥有者：完全访问权限
    - 观察员：只读权限（通过有效的 PortfolioObserverGrant）

    注意：观察员授权已撤销/过期时返回 403 而非 404
    """

    permission_classes = [IsAuthenticated, ObserverAccessPermission]
    queryset = PositionModel._default_manager.none()

    def get_queryset(self):
        """持仓列表读取已改为 unified ledger，自定义 list 不再依赖 queryset。"""
        return self.queryset

    def _validate_portfolio_access(self, portfolio: PortfolioModel) -> PortfolioModel:
        from django.core.exceptions import PermissionDenied
        from rest_framework.exceptions import NotFound

        if portfolio is None:
            raise NotFound("投资组合不存在")

        if portfolio.user == self.request.user:
            return portfolio

        grant = PortfolioObserverGrantModel._default_manager.filter(
            owner_user_id=portfolio.user,
            observer_user_id=self.request.user,
            status="active",
        ).first()
        if grant:
            if grant.is_valid():
                return portfolio
            raise PermissionDenied("观察员授权已过期")

        revoked_grant = PortfolioObserverGrantModel._default_manager.filter(
            owner_user_id=portfolio.user,
            observer_user_id=self.request.user,
        ).exclude(status="active").first()
        if revoked_grant:
            raise PermissionDenied(f"观察员授权已{revoked_grant.get_status_display()}")
        raise PermissionDenied("无权访问此持仓")

    def _resolve_position_context(self, pk: int):
        from rest_framework.exceptions import NotFound

        from apps.simulated_trading.infrastructure.models import PositionModel as UnifiedPositionModel

        try:
            unified_position = UnifiedPositionModel._default_manager.select_related("account").get(pk=pk)
            portfolio = self._validate_portfolio_access(
                self._get_portfolio_for_account(unified_position.account_id)
            )
            return unified_position, portfolio
        except (UnifiedPositionModel.DoesNotExist, ValueError):
            pass

        legacy_projection = (
            PositionModel._default_manager.filter(pk=pk)
            .select_related("portfolio", "portfolio__user", "category", "currency")
            .first()
        )
        if legacy_projection is None:
            raise NotFound(f"持仓 {pk} 不存在")

        portfolio = self._validate_portfolio_access(legacy_projection.portfolio)
        unified_position = self._sync_unified_position_from_legacy(legacy_projection)
        return unified_position, portfolio

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return PositionCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return PositionUpdateSerializer
        return PositionSerializer

    def _get_filtered_accessible_portfolios(self):
        from .permissions import get_accessible_portfolios

        portfolios = get_accessible_portfolios(self.request.user).select_related("user", "base_currency")
        portfolio_id = self.request.query_params.get("portfolio_id")
        if portfolio_id:
            portfolios = portfolios.filter(id=portfolio_id)
        return portfolios

    def _get_or_create_real_account(self, portfolio) -> int:
        """
        Return the SimulatedAccountModel ID for the given portfolio.

        Each portfolio maps 1-to-1 to a dedicated real account.  If no mapping
        exists yet (pre-migration), a new account is created and the mapping
        recorded so subsequent calls are idempotent.
        """
        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
            SimulatedAccountModel,
        )
        from django.db import transaction as db_transaction

        try:
            mapping = LedgerMigrationMapModel._default_manager.get(
                source_app="account",
                source_table="portfolio",
                source_id=portfolio.id,
            )
            return mapping.target_id
        except LedgerMigrationMapModel.DoesNotExist:
            pass

        with db_transaction.atomic():
            real_account = SimulatedAccountModel._default_manager.create(
                user=portfolio.user,
                account_name=portfolio.name,
                account_type="real",
                initial_capital=0,
                current_cash=0,
                current_market_value=0,
                total_value=0,
                is_active=portfolio.is_active,
                auto_trading_enabled=False,
            )
            LedgerMigrationMapModel._default_manager.create(
                source_app="account",
                source_table="portfolio",
                source_id=portfolio.id,
                target_table="simulated_account",
                target_id=real_account.id,
            )
        return real_account.id

    def create(self, request, *args, **kwargs):
        from apps.simulated_trading.application.unified_position_service import (
            UnifiedPositionService,
        )
        from apps.simulated_trading.management.commands.migrate_account_ledger import (
            _map_asset_type,
        )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        portfolio_id = request.data.get("portfolio")
        if not portfolio_id:
            return Response({"success": False, "error": "缺少 portfolio 参数"}, status=status.HTTP_400_BAD_REQUEST)

        portfolio = PortfolioModel._default_manager.select_related("user", "base_currency").filter(id=portfolio_id).first()
        if portfolio is None:
            return Response({"success": False, "error": f"投资组合 {portfolio_id} 不存在"}, status=status.HTTP_404_NOT_FOUND)
        if portfolio.user != request.user:
            return Response(
                {"success": False, "error": "观察员无权创建持仓，只有账户拥有者可以执行此操作"},
                status=status.HTTP_403_FORBIDDEN,
            )

        account_id = self._ensure_portfolio_ledger_synced(portfolio)
        unified_model = UnifiedPositionService.default().create_position(
            account_id=account_id,
            asset_code=serializer.validated_data["asset_code"],
            shares=float(serializer.validated_data["shares"]),
            price=float(serializer.validated_data["avg_cost"]),
            current_price=float(serializer.validated_data.get("current_price") or serializer.validated_data["avg_cost"]),
            asset_type=_map_asset_type(serializer.validated_data.get("asset_class", "equity")),
            source=serializer.validated_data.get("source", "manual"),
            source_id=serializer.validated_data.get("source_id"),
        )
        self._sync_legacy_projection_from_unified(
            unified_position=unified_model,
            portfolio=portfolio,
            asset_class=serializer.validated_data.get("asset_class", "equity"),
            region=serializer.validated_data.get("region", "CN"),
            cross_border=serializer.validated_data.get("cross_border", "domestic"),
            category=serializer.validated_data.get("category"),
            currency=serializer.validated_data.get("currency"),
            source=serializer.validated_data.get("source", "manual"),
            source_id=serializer.validated_data.get("source_id"),
        )
        payload = self._build_position_payload(unified_model, portfolio)
        return Response(PositionSerializer(payload).data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        """
        Create position: write to unified ledger (primary), then mirror to apps/account.

        The unified ledger (simulated_trading) is the source of truth.
        apps/account.PositionModel is kept as a compatibility mirror so that
        existing list/retrieve queries continue to work during the migration period.
        """
        from shared.domain.position_calculations import recalculate_derived_fields
        from apps.simulated_trading.application.unified_position_service import (
            UnifiedPositionService,
        )
        from apps.simulated_trading.infrastructure.models import LedgerMigrationMapModel
        from apps.simulated_trading.management.commands.migrate_account_ledger import (
            _map_asset_type,
        )

        portfolio_id = self.request.data.get('portfolio')
        portfolio = get_object_or_404(
            PortfolioModel,
            id=portfolio_id,
            user=self.request.user
        )

        shares = serializer.validated_data['shares']
        avg_cost = serializer.validated_data['avg_cost']
        current_price = serializer.validated_data.get('current_price', avg_cost)
        mv, pnl, pnl_pct = recalculate_derived_fields(
            float(shares), float(avg_cost), float(current_price)
        )

        # ── Primary write: unified ledger ──────────────────────────────────
        account_id = self._get_or_create_real_account(portfolio)
        asset_code = serializer.validated_data['asset_code']
        asset_class = serializer.validated_data.get('asset_class', 'equity')
        service = UnifiedPositionService.default()
        unified_model = service.create_position(
            account_id=account_id,
            asset_code=asset_code,
            shares=float(shares),
            price=float(avg_cost),
            current_price=float(current_price),
            asset_type=_map_asset_type(asset_class),
            source=serializer.validated_data.get('source', 'manual'),
            source_id=serializer.validated_data.get('source_id'),
        )

        # ── Mirror write: apps/account (backward compat for reads) ─────────
        account_pos = serializer.save(
            portfolio=portfolio,
            market_value=mv,
            unrealized_pnl=pnl,
            unrealized_pnl_pct=pnl_pct,
        )

        # Record position-level mapping so update/close can find the unified record
        LedgerMigrationMapModel._default_manager.get_or_create(
            source_app="account",
            source_table="position",
            source_id=account_pos.id,
            defaults={
                "target_table": "simulated_position",
                "target_id": unified_model.id,
            },
        )

    def retrieve(self, request, *args, **kwargs):
        unified_position, portfolio = self._resolve_position_context(kwargs["pk"])
        if portfolio.user != request.user:
            self._log_observer_access_if_needed(request, portfolio, unified_position.asset_code, "detail")
        payload = self._build_position_payload(unified_position, portfolio)
        return Response(PositionSerializer(payload).data)

    def update(self, request, *args, **kwargs):
        from apps.simulated_trading.application.unified_position_service import (
            UnifiedPositionService,
        )
        from apps.simulated_trading.infrastructure.models import PositionModel as UnifiedPositionModel

        partial = kwargs.pop("partial", False)
        unified_position, portfolio = self._resolve_position_context(kwargs["pk"])
        legacy_projection = self._get_legacy_projection_for_unified_position(unified_position.id)

        if portfolio.user != request.user:
            return Response(
                {"success": False, "error": "观察员无权更新持仓，只有账户拥有者可以执行此操作"},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        UnifiedPositionService.default().update_position(
            account_id=unified_position.account_id,
            asset_code=unified_position.asset_code,
            shares=float(validated["shares"]) if "shares" in validated else None,
            avg_cost=float(validated["avg_cost"]) if "avg_cost" in validated else None,
            current_price=float(validated["current_price"]) if "current_price" in validated else None,
        )
        unified_model = UnifiedPositionModel._default_manager.get(pk=unified_position.id)
        self._sync_legacy_projection_from_unified(
            unified_position=unified_model,
            portfolio=portfolio,
            asset_class=legacy_projection.asset_class if legacy_projection else "equity",
            region=legacy_projection.region if legacy_projection else "CN",
            cross_border=legacy_projection.cross_border if legacy_projection else "domestic",
            category=legacy_projection.category if legacy_projection else None,
            currency=legacy_projection.currency if legacy_projection else None,
            source=legacy_projection.source if legacy_projection else "manual",
            source_id=legacy_projection.source_id if legacy_projection else unified_model.signal_id,
        )
        payload = self._build_position_payload(unified_model, portfolio)
        return Response(PositionSerializer(payload).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def perform_update(self, serializer):
        """
        Update position: write to unified ledger (primary), then sync apps/account mirror.

        Derived fields are always recalculated to maintain consistency.
        """
        from shared.domain.position_calculations import recalculate_derived_fields
        from apps.simulated_trading.application.unified_position_service import (
            UnifiedPositionService,
        )
        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
        )

        # ── Mirror write: apps/account (for backward compat reads) ─────────
        instance = serializer.save()
        shares = instance.shares
        avg_cost = float(instance.avg_cost)
        current_price = float(instance.current_price or instance.avg_cost)
        mv, pnl, pnl_pct = recalculate_derived_fields(shares, avg_cost, current_price)
        instance.market_value = mv
        instance.unrealized_pnl = pnl
        instance.unrealized_pnl_pct = pnl_pct
        instance.save(update_fields=['market_value', 'unrealized_pnl', 'unrealized_pnl_pct'])

        # ── Primary write: unified ledger ──────────────────────────────────
        try:
            mapping = LedgerMigrationMapModel._default_manager.get(
                source_app="account",
                source_table="position",
                source_id=instance.id,
            )
            # Resolve account_id for the unified position
            account_mapping = LedgerMigrationMapModel._default_manager.get(
                source_app="account",
                source_table="portfolio",
                source_id=instance.portfolio_id,
            )
            UnifiedPositionService.default().update_position(
                account_id=account_mapping.target_id,
                asset_code=instance.asset_code,
                shares=float(shares),
                avg_cost=avg_cost,
                current_price=current_price,
            )
        except LedgerMigrationMapModel.DoesNotExist:
            # Position has not been migrated yet; apps/account mirror is the only store.
            pass

    def destroy(self, request, *args, **kwargs):
        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
            PositionModel as UnifiedPositionModel,
        )

        unified_position, portfolio = self._resolve_position_context(kwargs["pk"])
        if portfolio.user != request.user:
            return Response(
                {"success": False, "error": "观察员无权删除持仓，只有账户拥有者可以执行此操作"},
                status=status.HTTP_403_FORBIDDEN,
            )

        legacy_projection = self._get_legacy_projection_for_unified_position(unified_position.id)
        UnifiedPositionModel._default_manager.filter(pk=unified_position.id).delete()
        LedgerMigrationMapModel._default_manager.filter(
            source_app="account",
            source_table="position",
            target_table="simulated_position",
            target_id=unified_position.id,
        ).delete()
        if legacy_projection is not None:
            legacy_projection.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def list(self, request, *args, **kwargs):
        from apps.simulated_trading.infrastructure.models import PositionModel as UnifiedPositionModel

        portfolios = list(self._get_filtered_accessible_portfolios())
        account_to_portfolio: dict[int, PortfolioModel] = {}
        for portfolio in portfolios:
            account_to_portfolio[self._ensure_portfolio_ledger_synced(portfolio)] = portfolio

        queryset = UnifiedPositionModel._default_manager.filter(
            account_id__in=list(account_to_portfolio.keys())
        ).select_related("account").order_by("-market_value", "asset_code")

        asset_code = request.query_params.get("asset_code")
        if asset_code:
            queryset = queryset.filter(asset_code=asset_code)

        page = self.paginate_queryset(queryset)
        positions = page if page is not None else queryset
        payload = [
            self._build_position_payload(pos, account_to_portfolio.get(pos.account_id))
            for pos in positions
        ]

        for portfolio in portfolios:
            if portfolio.user != request.user:
                self._log_audit_action(
                    request=request,
                    action="READ",
                    resource_type="position_via_observer_grant",
                    resource_id=f"portfolio_{portfolio.id}",
                    response_status=200,
                    extra_context={"portfolio_id": str(portfolio.id)},
                )

        serializer = PositionSerializer(payload, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        from apps.simulated_trading.application.unified_position_service import (
            UnifiedPositionService,
        )
        from apps.simulated_trading.infrastructure.models import (
            LedgerMigrationMapModel,
            PositionModel as UnifiedPositionModel,
        )

        unified_position, portfolio = self._resolve_position_context(pk)
        legacy_projection = self._get_legacy_projection_for_unified_position(unified_position.id)

        if portfolio.user != request.user:
            return Response(
                {"success": False, "error": "观察员无权执行平仓操作，只有账户拥有者可以平仓"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if legacy_projection is not None and legacy_projection.is_closed:
            return Response({"success": False, "error": "该持仓已平仓"}, status=status.HTTP_400_BAD_REQUEST)

        close_shares_raw = request.data.get("shares", None)
        close_shares = float(close_shares_raw) if close_shares_raw is not None else None

        result = UnifiedPositionService.default().close_position(
            account_id=unified_position.account_id,
            asset_code=unified_position.asset_code,
            close_shares=close_shares,
            reason="账户平仓",
        )

        if legacy_projection is not None:
            closed_position = PositionRepository().close_position(legacy_projection.id, close_shares)
            if closed_position is None:
                return Response({"success": False, "error": "平仓失败"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            legacy_projection.refresh_from_db()

        if result is None:
            LedgerMigrationMapModel._default_manager.filter(
                source_app="account",
                source_table="position",
                target_table="simulated_position",
                target_id=unified_position.id,
            ).delete()
            payload = {
                "id": unified_position.id,
                "portfolio": portfolio.id,
                "portfolio_name": portfolio.name,
                "asset_code": unified_position.asset_code,
                "asset_name": unified_position.asset_name,
                "category": legacy_projection.category_id if legacy_projection else None,
                "category_code": legacy_projection.category.code if legacy_projection and legacy_projection.category else None,
                "category_name": legacy_projection.category.name if legacy_projection and legacy_projection.category else None,
                "category_path": legacy_projection.category.get_full_path() if legacy_projection and legacy_projection.category else None,
                "currency": legacy_projection.currency_id if legacy_projection else None,
                "currency_code": legacy_projection.currency.code if legacy_projection and legacy_projection.currency else None,
                "currency_name": legacy_projection.currency.name if legacy_projection and legacy_projection.currency else None,
                "currency_symbol": legacy_projection.currency.symbol if legacy_projection and legacy_projection.currency else None,
                "asset_class": legacy_projection.asset_class if legacy_projection else "equity",
                "region": legacy_projection.region if legacy_projection else "CN",
                "cross_border": legacy_projection.cross_border if legacy_projection else "domestic",
                "shares": 0.0,
                "avg_cost": legacy_projection.avg_cost if legacy_projection else unified_position.avg_cost,
                "current_price": legacy_projection.current_price if legacy_projection else unified_position.current_price,
                "market_value": Decimal("0.00"),
                "unrealized_pnl": Decimal("0.00"),
                "unrealized_pnl_pct": 0.0,
                "source": legacy_projection.source if legacy_projection else "manual",
                "source_id": legacy_projection.source_id if legacy_projection else unified_position.signal_id,
                "is_closed": True,
                "opened_at": legacy_projection.opened_at if legacy_projection else None,
                "closed_at": legacy_projection.closed_at if legacy_projection else timezone.now(),
                "created_at": getattr(legacy_projection, "created_at", None),
                "updated_at": getattr(legacy_projection, "updated_at", None),
            }
        else:
            unified_model = UnifiedPositionModel._default_manager.get(
                account_id=unified_position.account_id,
                asset_code=unified_position.asset_code,
            )
            if legacy_projection is not None:
                self._sync_legacy_projection_from_unified(
                    unified_position=unified_model,
                    portfolio=portfolio,
                    asset_class=legacy_projection.asset_class,
                    region=legacy_projection.region,
                    cross_border=legacy_projection.cross_border,
                    category=legacy_projection.category,
                    currency=legacy_projection.currency,
                    source=legacy_projection.source,
                    source_id=legacy_projection.source_id,
                )
            payload = self._build_position_payload(unified_model, portfolio)

        return Response({
            "success": True,
            "message": "持仓已平仓",
            "data": PositionSerializer(payload).data,
        })

    def _log_observer_access_if_needed(self, request, portfolio, asset_code: str, action: str):
        """记录观察员访问审计日志。"""
        if portfolio.user != request.user:
            self._log_audit_action(
                request=request,
                action='READ',
                resource_type='position_via_observer_grant',
                resource_id=f"{portfolio.id}:{asset_code}",
                response_status=200,
                extra_context={
                    'portfolio_owner': portfolio.user.username,
                    'portfolio_name': portfolio.name,
                    'position_asset': asset_code,
                    'access_action': action,
                }
            )

    def _log_audit_action(self, request, action: str, resource_type: str,
                         resource_id: str, response_status: int, extra_context: dict = None):
        """
        记录审计日志

        Args:
            request: 请求对象
            action: 操作动作 (CREATE/DELETE/UPDATE/READ)
            resource_type: 资源类型
            resource_id: 资源ID
            response_status: 响应状态码
            extra_context: 额外上下文信息
        """
        try:
            import uuid

            from apps.audit.domain.entities import (
                OperationAction,
                OperationLog,
                OperationSource,
                OperationType,
            )
            from apps.audit.infrastructure.repositories import DjangoAuditRepository

            audit_repo = DjangoAuditRepository()

            # 构造审计日志实体
            log_entity = OperationLog.create(
                request_id=str(uuid.uuid4()),
                user_id=request.user.id,
                username=request.user.username,
                source=OperationSource.API,
                operation_type=OperationType.API_ACCESS,
                module='account',
                action=OperationAction[action],
                resource_type=resource_type,
                resource_id=resource_id,
                request_method=request.method,
                request_path=request.path,
                response_status=response_status,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            )

            audit_repo.save_operation_log(log_entity)

        except Exception as e:
            # 审计失败不影响主流程
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"记录审计日志失败: {e}", exc_info=True)

    @staticmethod
    def _get_client_ip(request):
        """获取客户端IP地址"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


# ==================== Transaction ViewSet ====================

class TransactionViewSet(viewsets.ModelViewSet):
    """
    交易记录 API ViewSet

    提供以下接口:
    - GET /api/account/transactions/ - 获取交易列表
    - POST /api/account/transactions/ - 创建交易记录
    - GET /api/account/transactions/{id}/ - 获取交易详情
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self):
        """只返回当前用户投资组合的交易"""
        user_portfolios = PortfolioModel._default_manager.filter(user=self.request.user)
        return TransactionModel._default_manager.filter(portfolio__in=user_portfolios).select_related(
            'portfolio', 'position'
        )

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return TransactionCreateSerializer
        return TransactionSerializer

    def perform_create(self, serializer):
        """创建时验证持仓归属"""
        position = serializer.validated_data.get('position')
        if position and position.portfolio.user != self.request.user:
            raise PermissionError("无权为此持仓创建交易记录")

        # 计算成交金额
        shares = serializer.validated_data['shares']
        price = serializer.validated_data['price']
        notional = shares * float(price)

        serializer.save(notional=notional)


# ==================== Capital Flow ViewSet ====================

class CapitalFlowViewSet(viewsets.ModelViewSet):
    """
    资金流水 API ViewSet

    提供以下接口:
    - GET /api/account/capital-flows/ - 获取资金流水列表
    - POST /api/account/capital-flows/ - 创建资金流水
    - GET /api/account/capital-flows/{id}/ - 获取流水详情
    - DELETE /api/account/capital-flows/{id}/ - 删除流水
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self):
        """只返回当前用户投资组合的资金流水"""
        user_portfolios = PortfolioModel._default_manager.filter(user=self.request.user)
        return CapitalFlowModel._default_manager.filter(portfolio__in=user_portfolios).select_related('portfolio')

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return CapitalFlowCreateSerializer
        return CapitalFlowSerializer

    def perform_create(self, serializer):
        """创建时验证投资组合归属"""
        portfolio_id = self.request.data.get('portfolio')
        portfolio = get_object_or_404(
            PortfolioModel,
            id=portfolio_id,
            user=self.request.user
        )
        serializer.save(portfolio=portfolio, user=self.request.user)


# ==================== Account Profile API ====================

class AccountProfileView(APIView):
    """
    账户配置 API

    - GET /api/account/profile/ - 获取账户配置
    - PUT /api/account/profile/ - 更新账户配置
    """

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get(self, request):
        """获取当前用户的账户配置"""
        profile = request.user.account_profile
        serializer = AccountProfileSerializer(profile)
        return Response(serializer.data)

    def put(self, request):
        """更新当前用户的账户配置"""
        profile = request.user.account_profile
        serializer = AccountProfileUpdateSerializer(profile, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            # 更新邮箱
            email = request.data.get('email')
            if email:
                request.user.email = email
                request.user.save()

            return Response(serializer.data)
        return Response({'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


# ==================== Asset Metadata API ====================

class AssetMetadataViewSet(viewsets.ReadOnlyModelViewSet):
    """
    资产元数据 API ViewSet (只读)

    - GET /api/account/assets/ - 获取资产列表
    - GET /api/account/assets/{id}/ - 获取资产详情
    - GET /api/account/assets/by-class/{asset_class}/ - 按类别查询
    """

    queryset = AssetMetadataModel._default_manager.all()
    serializer_class = AssetMetadataSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'], url_path='by-class/(?P<asset_class>[^/]+)')
    def by_class(self, request, asset_class=None):
        """
        按资产类别查询

        GET /api/account/assets/by-class/{asset_class}/
        """
        assets = self.get_queryset().filter(asset_class=asset_class)
        serializer = AssetMetadataSerializer(assets, many=True)
        return Response({
            'success': True,
            'count': assets.count(),
            'data': serializer.data
        })


# ==================== Health Check ====================

class AccountHealthView(APIView):
    """Account 服务健康检查"""

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get(self, request):
        """检查 Account 服务健康状态"""
        portfolio_count = PortfolioModel._default_manager.filter(user=request.user).count()
        position_count = PositionModel._default_manager.filter(
            portfolio__user=request.user,
            is_closed=False
        ).count()

        return Response({
            'status': 'healthy',
            'service': 'account',
            'portfolio_count': portfolio_count,
            'position_count': position_count
        })


# ==================== Observer Grant ViewSet ====================

class ObserverGrantViewSet(viewsets.ModelViewSet):
    """
    观察员授权 API ViewSet

    提供以下接口:
    - GET /api/account/observer-grants/ - 获取当前用户的授权列表
    - POST /api/account/observer-grants/ - 创建观察员授权
    - GET /api/account/observer-grants/{id}/ - 获取授权详情
    - PUT /api/account/observer-grants/{id}/ - 更新授权（过期时间）
    - DELETE /api/account/observer-grants/{id}/ - 撤销授权
    """

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get_queryset(self):
        """支持 owner 和 observer 双视角查询"""
        # 支持观察员视角查询
        as_observer = self.request.query_params.get('as_observer') == '1'

        if as_observer:
            # 返回当前用户作为观察员的授权
            queryset = PortfolioObserverGrantModel._default_manager.filter(
                observer_user_id=self.request.user
            ).select_related('observer_user_id', 'owner_user_id', 'revoked_by')
        else:
            # 返回当前用户作为 owner 的授权
            queryset = PortfolioObserverGrantModel._default_manager.filter(
                owner_user_id=self.request.user
            ).select_related('observer_user_id', 'owner_user_id', 'revoked_by')

        # 支持按状态过滤
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by('-created_at')

    def get_object(self):
        """
        对写操作使用全量查询后做显式鉴权，确保“对象存在但无权限”返回 403。
        """
        if self.action in ['destroy', 'update', 'partial_update']:
            lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
            lookup_value = self.kwargs.get(lookup_url_kwarg)
            grant = get_object_or_404(
                PortfolioObserverGrantModel._default_manager.select_related(
                    'owner_user_id', 'observer_user_id', 'revoked_by'
                ),
                **{self.lookup_field: lookup_value},
            )
            if grant.owner_user_id != self.request.user:
                self.permission_denied(self.request, message='无权访问此授权')
            return grant
        return super().get_object()

    @action(detail=True, methods=['get'])
    def positions(self, request, pk=None):
        """
        获取授权对应账户的持仓列表（观察员专用）

        GET /api/account/observer-grants/{id}/positions/
        """
        grant = self.get_object()

        # 验证当前用户是该授权的观察员
        if grant.observer_user_id != request.user:
            return Response({
                'success': False,
                'error': '您无权查看此授权的持仓信息'
            }, status=status.HTTP_403_FORBIDDEN)

        # 验证授权状态
        if grant.status != 'active':
            return Response({
                'success': False,
                'error': f'授权状态为 {grant.get_status_display()}，无法查看'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 检查授权是否过期
        if grant.is_expired():
            return Response({
                'success': False,
                'error': '授权已过期，无法查看'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 获取 owner 的活跃投资组合
        portfolio = PortfolioModel._default_manager.filter(
            user=grant.owner_user_id,
            is_active=True
        ).first()

        if not portfolio:
            return Response({
                'success': True,
                'data': {
                    'positions': [],
                    'statistics': {
                        'position_count': 0,
                        'total_value': 0,
                        'total_cost': 0,
                        'total_pnl': 0,
                        'total_pnl_pct': 0
                    }
                }
            })

        # 获取持仓
        positions = portfolio.positions.filter(is_closed=False).select_related()

        # 计算统计
        position_count = positions.count()
        total_value = positions.aggregate(total=Sum('market_value'))['total'] or Decimal('0')
        total_cost = positions.aggregate(
            total=Sum(
                models.F('shares') * models.F('avg_cost'),
                output_field=models.DecimalField(max_digits=20, decimal_places=2),
            )
        )['total'] or Decimal('0')
        total_pnl = total_value - total_cost
        total_pnl_pct = float((total_pnl / total_cost * 100) if total_cost > 0 else 0)

        # 序列化持仓数据
        positions_data = []
        for pos in positions:
            positions_data.append({
                'id': pos.id,
                'asset_code': pos.asset_code,
                'asset_name': pos.asset_name,
                'asset_class': pos.asset_class,
                'shares': float(pos.shares),
                'avg_cost': float(pos.avg_cost),
                'current_price': float(pos.current_price),
                'market_value': float(pos.market_value),
                'unrealized_pnl': float(pos.unrealized_pnl),
                'unrealized_pnl_pct': float(pos.unrealized_pnl_pct),
            })

        # 记录观察员访问审计日志
        self._log_audit_action(
            request=request,
            action='READ',
            resource_type='observer_grant_positions',
            resource_id=str(grant.id),
            response_status=200,
            extra_context={
                'grant_owner': grant.owner_user_id.username,
                'portfolio_id': portfolio.id,
            }
        )

        return Response({
            'success': True,
            'data': {
                'positions': positions_data,
                'statistics': {
                    'position_count': position_count,
                    'total_value': float(total_value),
                    'total_cost': float(total_cost),
                    'total_pnl': float(total_pnl),
                    'total_pnl_pct': total_pnl_pct,
                }
            }
        })

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return ObserverGrantCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ObserverGrantUpdateSerializer
        return ObserverGrantSerializer

    def perform_create(self, serializer):
        """创建时自动关联当前用户为 owner"""
        serializer.save(owner_user_id=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """
        撤销授权（软删除）

        DELETE /api/account/observer-grants/{id}/
        """
        grant = self.get_object()

        # 验证权限：只有 owner 可以撤销
        if grant.owner_user_id != request.user:
            return Response({
                'success': False,
                'error': '无权撤销此授权'
            }, status=status.HTTP_403_FORBIDDEN)

        # 已撤销或过期的授权不能再次撤销
        if grant.status != 'active':
            return Response({
                'success': False,
                'error': f'授权状态为 {grant.get_status_display()}，无法撤销'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 撤销授权
        grant.revoke(request.user)

        # 审计打点
        self._log_audit_action(
            request=request,
            action='DELETE',
            resource_type='observer_grant',
            resource_id=str(grant.id),
            response_status=200
        )

        serializer = ObserverGrantSerializer(grant)
        return Response({
            'success': True,
            'message': '授权已撤销',
            'data': serializer.data
        })

    def create(self, request, *args, **kwargs):
        """
        创建观察员授权

        POST /api/account/observer-grants/
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        # 审计打点
        grant = serializer.instance
        self._log_audit_action(
            request=request,
            action='CREATE',
            resource_type='observer_grant',
            resource_id=str(grant.id),
            response_status=201
        )

        # 使用完整序列化器返回创建的数据
        response_serializer = ObserverGrantSerializer(grant)
        headers = self.get_success_headers(response_serializer.data)
        return Response({
            'success': True,
            'message': '观察员授权创建成功',
            'data': response_serializer.data
        }, status=status.HTTP_201_CREATED, headers=headers)

    def _log_audit_action(self, request, action: str, resource_type: str,
                         resource_id: str, response_status: int):
        """
        记录审计日志

        Args:
            request: 请求对象
            action: 操作动作 (CREATE/DELETE/UPDATE/READ)
            resource_type: 资源类型
            resource_id: 资源ID
            response_status: 响应状态码
        """
        try:
            import uuid

            from apps.audit.domain.entities import (
                OperationAction,
                OperationLog,
                OperationSource,
                OperationType,
            )
            from apps.audit.infrastructure.repositories import DjangoAuditRepository

            audit_repo = DjangoAuditRepository()

            # 构造审计日志实体
            log_entity = OperationLog.create(
                request_id=str(uuid.uuid4()),
                user_id=request.user.id,
                username=request.user.username,
                source=OperationSource.API,
                operation_type=OperationType.DATA_MODIFY if action in ('CREATE', 'DELETE', 'UPDATE') else OperationType.API_ACCESS,
                module='account',
                action=OperationAction[action],
                resource_type=resource_type,
                resource_id=resource_id,
                request_method=request.method,
                request_path=request.path,
                response_status=response_status,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            )

            audit_repo.save_operation_log(log_entity)

        except Exception as e:
            # 审计失败不影响主流程
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"记录审计日志失败: {e}", exc_info=True)

    @staticmethod
    def _get_client_ip(request):
        """获取客户端IP地址"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip




# ==================== User Search API ====================

class UserSearchView(APIView):
    """
    用户搜索 API

    用于协作页面添加观察员时的用户搜索

    - GET /api/account/users/search/?q=xxx - 搜索用户
    """

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get(self, request):
        """
        搜索用户

        支持按用户名或显示名称搜索
        排除当前用户和已授权的用户
        """
        from django.contrib.auth.models import User

        from apps.account.infrastructure.models import PortfolioObserverGrantModel

        query = request.GET.get("q", "").strip()

        if not query or len(query) < 2:
            return Response({
                "success": True,
                "results": []
            })

        # 搜索用户（按用户名或显示名称）
        users = User._default_manager.filter(
            is_active=True
        ).filter(
            models.Q(username__icontains=query) |
            models.Q(account_profile__display_name__icontains=query)
        ).exclude(id=request.user.id).select_related("account_profile")[:10]

        # 获取已授权的用户ID列表
        granted_user_ids = PortfolioObserverGrantModel._default_manager.filter(
            owner_user_id=request.user,
            status="active"
        ).values_list("observer_user_id", flat=True)

        # 格式化结果
        results = []
        for user in users:
            # 检查是否已授权
            is_already_granted = user.id in granted_user_ids

            results.append({
                "id": user.id,
                "username": user.username,
                "display_name": user.account_profile.display_name if hasattr(user, "account_profile") else user.username,
                "email": user.email or "",
                "is_already_granted": is_already_granted,
            })

        return Response({
            "success": True,
            "results": results
        })


# ==================== Trading Cost Config ViewSet ====================

class TradingCostConfigViewSet(viewsets.ModelViewSet):
    """
    交易费率配置 API ViewSet

    提供以下接口:
    - GET /api/account/trading-cost-configs/ - 获取费率配置列表
    - POST /api/account/trading-cost-configs/ - 创建费率配置
    - GET /api/account/trading-cost-configs/{id}/ - 获取费率配置详情
    - PUT /api/account/trading-cost-configs/{id}/ - 更新费率配置
    - DELETE /api/account/trading-cost-configs/{id}/ - 删除费率配置
    - POST /api/account/trading-cost-configs/{id}/calculate/ - 计算交易费用
    """

    permission_classes = [IsAuthenticated, TradingPermission]

    def get_queryset(self):
        """只返回当前用户投资组合的费率配置"""
        user_portfolios = PortfolioModel._default_manager.filter(user=self.request.user)
        return TradingCostConfigModel._default_manager.filter(
            portfolio__in=user_portfolios
        ).select_related('portfolio')

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return TradingCostConfigCreateSerializer
        return TradingCostConfigSerializer

    def perform_create(self, serializer):
        """创建时验证投资组合归属"""
        portfolio = serializer.validated_data['portfolio']
        if portfolio.user != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("无权为此投资组合配置费率")
        serializer.save()

    def perform_update(self, serializer):
        """更新时禁止越权修改配置归属"""
        portfolio = serializer.validated_data.get("portfolio", serializer.instance.portfolio)
        if portfolio.user != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("无权修改此投资组合的费率")
        serializer.save()

    @action(detail=True, methods=['post'])
    def calculate(self, request, pk=None):
        """
        计算交易费用

        POST /api/account/trading-cost-configs/{id}/calculate/

        Body:
            {
                "action": "buy" | "sell",
                "amount": 10000.0,
                "is_shanghai": true
            }
        """
        config_model = self.get_object()
        config = config_model.to_domain()

        payload = TradingCostCalculationSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        action_type = payload.validated_data["action"]
        amount = payload.validated_data["amount"]
        is_shanghai = payload.validated_data["is_shanghai"]

        if action_type == 'sell':
            cost = config.calculate_sell_cost(amount, is_shanghai)
        else:
            cost = config.calculate_buy_cost(amount, is_shanghai)

        cost['action'] = action_type
        cost['amount'] = amount
        cost['is_shanghai'] = is_shanghai
        cost['cost_ratio'] = round(cost['total'] / amount * 100, 4) if amount > 0 else 0

        return Response({'success': True, 'data': cost})
