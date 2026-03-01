"""
模拟盘交易模块 Interface 层视图

遵循四层架构规范：
- Interface 层只做输入验证和输出格式化
- 禁止业务逻辑
- 包含 API 视图（DRF）
"""
from typing import Optional
from datetime import date, datetime
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_http_methods
from django.http import Http404
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from apps.simulated_trading.application.use_cases import (
    CreateSimulatedAccountUseCase,
    GetAccountPerformanceUseCase,
    ExecuteBuyOrderUseCase,
    ExecuteSellOrderUseCase,
    ListAccountsUseCase,
)
from apps.simulated_trading.application.performance_calculator import PerformanceCalculator
from apps.simulated_trading.application.auto_trading_engine import AutoTradingEngine
from apps.simulated_trading.application.daily_inspection_service import DailyInspectionService
from apps.simulated_trading.infrastructure.repositories import (
    DjangoSimulatedAccountRepository,
    DjangoPositionRepository,
    DjangoTradeRepository,
    DjangoFeeConfigRepository,
)
from apps.simulated_trading.infrastructure.market_data_provider import MarketDataProvider
from apps.simulated_trading.application.asset_pool_query_service import AssetPoolQueryService
from .serializers import (
    CreateAccountRequestSerializer,
    AccountResponseSerializer,
    AccountListResponseSerializer,
    PositionResponseSerializer,
    PositionListResponseSerializer,
    TradeListRequestSerializer,
    TradeResponseSerializer,
    TradeListResponseSerializer,
    PerformanceResponseSerializer,
    FeeConfigResponseSerializer,
    FeeConfigListResponseSerializer,
    ManualTradeRequestSerializer,
    ManualTradeResponseSerializer,
    EquityCurveRequestSerializer,
    EquityCurveResponseSerializer,
    AutoTradingRunRequestSerializer,
    AutoTradingRunResponseSerializer,
    DailyInspectionRunRequestSerializer,
    DailyInspectionReportListResponseSerializer,
)
from apps.simulated_trading.infrastructure.models import (
    SimulatedAccountModel,
    DailyInspectionReportModel,
    DailyInspectionNotificationConfigModel,
)


# ============================================================================
# 页面视图（前端）
# ============================================================================

@require_http_methods(["GET"])
def dashboard_page(request):
    """
    模拟盘仪表盘页面

    GET /simulated-trading/dashboard/
    """
    return render(request, 'simulated_trading/dashboard.html')


@require_http_methods(["GET"])
def account_detail_page(request, account_id):
    """
    账户详情页面

    GET /simulated-trading/accounts/{id}/
    """
    context = {
        'account_id': account_id
    }
    return render(request, 'simulated_trading/account_detail.html', context)


# ============================================================================
# 用户专属投资组合视图
# ============================================================================

@login_required
@require_http_methods(["GET", "POST"])
def my_accounts_page(request):
    """
    我的投资组合页面

    显示当前用户的所有投资组合（实仓+模拟仓）
    支持创建新的投资组合

    GET /simulated-trading/my-accounts/
    POST /simulated-trading/my-accounts/
    """
    from django.contrib import messages
    from decimal import Decimal

    if request.method == "POST":
        # 创建新的投资组合
        account_type = request.POST.get("account_type")
        account_name = request.POST.get("account_name")
        initial_capital = Decimal(request.POST.get("initial_capital", "100000"))

        # 验证
        if account_type not in ['real', 'simulated']:
            messages.error(request, "无效的账户类型")
            return redirect("/simulated-trading/my-accounts/")

        if not account_name:
            messages.error(request, "请输入账户名称")
            return redirect("/simulated-trading/my-accounts/")

        if initial_capital <= 0:
            messages.error(request, "初始资金必须大于0")
            return redirect("/simulated-trading/my-accounts/")

        # 创建投资组合
        account = SimulatedAccountModel._default_manager.create(
            user=request.user,
            account_name=account_name,
            account_type=account_type,
            initial_capital=initial_capital,
            current_cash=initial_capital,
            total_value=initial_capital,
        )

        type_label = "实仓" if account_type == "real" else "模拟仓"
        messages.success(request, f"{type_label}创建成功！")
        return redirect("/simulated-trading/my-accounts/")

    # GET 请求：显示用户的投资组合列表
    from django.db.models import Prefetch
    from apps.strategy.infrastructure.models import PortfolioStrategyAssignmentModel

    accounts = SimulatedAccountModel._default_manager.filter(
        user=request.user
    ).prefetch_related(
        Prefetch(
            'strategy_assignments',
            queryset=PortfolioStrategyAssignmentModel._default_manager.filter(
                is_active=True
            ).select_related('strategy').order_by('-assigned_at'),
            to_attr='prefetched_active_strategy_assignments'
        )
    ).order_by('-created_at')

    # 分类显示
    real_accounts = []
    simulated_accounts = []
    total_assets = 0

    for account in accounts:
        # 兼容现有模板：给 account 注入 active_strategy 属性
        active_assignments = getattr(account, 'prefetched_active_strategy_assignments', [])
        active_strategy = active_assignments[0].strategy if active_assignments else None
        account.active_strategy = active_strategy

        account_data = {
            'id': account.id,
            'name': account.account_name,
            'type': '实仓' if account.account_type == 'real' else '模拟仓',
            'type_code': account.account_type,
            'initial_capital': float(account.initial_capital),
            'current_cash': float(account.current_cash),
            'total_value': float(account.total_value),
            'total_return': account.total_return,
            'is_active': account.is_active,
        }

        if account.account_type == 'real':
            real_accounts.append(account_data)
        else:
            simulated_accounts.append(account_data)

        total_assets += float(account.total_value)

    context = {
        'real_accounts': real_accounts,
        'simulated_accounts': simulated_accounts,
        'total_assets': total_assets,
        'user': request.user,
        'accounts': accounts,  # 所有账户的合并列表
    }
    return render(request, 'simulated_trading/my_accounts.html', context)


@login_required
@require_http_methods(["GET"])
def my_account_detail_page(request, account_id):
    """
    我的账户详情页面

    显示指定投资组合的详细信息、持仓和交易记录
    GET /simulated-trading/my-accounts/{id}/
    """
    # 获取用户的投资组合
    account = get_object_or_404(
        SimulatedAccountModel,
        id=account_id,
        user=request.user
    )

    # 获取持仓和交易记录
    positions = account.positions.all()[:10]  # 最近10条持仓
    trades = account.trades.all()[:20]  # 最近20条交易

    context = {
        'account': account,
        'account_type': '实仓' if account.account_type == 'real' else '模拟仓',
        'account_type_code': account.account_type,
        'positions': positions,
        'trades': trades,
        'user': request.user,
    }
    return render(request, 'simulated_trading/my_account_detail.html', context)


@login_required
@require_http_methods(["GET"])
def my_positions_page(request, account_id):
    """
    我的持仓页面

    显示指定投资组合的所有持仓
    GET /simulated-trading/my-accounts/{id}/positions/
    """
    account = get_object_or_404(
        SimulatedAccountModel,
        id=account_id,
        user=request.user
    )

    positions = account.positions.all()

    context = {
        'account': account,
        'account_type': '实仓' if account.account_type == 'real' else '模拟仓',
        'account_type_code': account.account_type,
        'positions': positions,
        'user': request.user,
    }
    return render(request, 'simulated_trading/my_positions.html', context)


@login_required
@require_http_methods(["GET"])
def my_trades_page(request, account_id):
    """
    我的交易记录页面

    显示指定投资组合的所有交易记录
    GET /simulated-trading/my-accounts/{id}/trades/
    """
    account = get_object_or_404(
        SimulatedAccountModel,
        id=account_id,
        user=request.user
    )

    trades = account.trades.all()[:100]  # 最近100条交易

    context = {
        'account': account,
        'account_type': '实仓' if account.account_type == 'real' else '模拟仓',
        'account_type_code': account.account_type,
        'trades': trades,
        'user': request.user,
    }
    return render(request, 'simulated_trading/my_trades.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def my_inspection_notify_page(request, account_id):
    """
    巡检邮件通知配置页面

    GET/POST /simulated-trading/my-accounts/{id}/inspection-notify/
    """
    from django.contrib import messages

    account = get_object_or_404(
        SimulatedAccountModel,
        id=account_id,
        user=request.user
    )

    config, _ = DailyInspectionNotificationConfigModel._default_manager.get_or_create(account=account)

    if request.method == "POST":
        is_enabled = request.POST.get("is_enabled") == "on"
        include_owner_email = request.POST.get("include_owner_email") == "on"
        notify_on = request.POST.get("notify_on", "warning_error")
        if notify_on not in {"warning_error", "all"}:
            notify_on = "warning_error"

        raw_emails = request.POST.get("recipient_emails", "")
        emails: list[str] = []
        invalid: list[str] = []
        for chunk in raw_emails.replace(";", ",").replace("\n", ",").split(","):
            email = chunk.strip()
            if not email:
                continue
            try:
                validate_email(email)
                emails.append(email)
            except DjangoValidationError:
                invalid.append(email)

        if invalid:
            messages.error(request, f"以下邮箱格式无效: {', '.join(invalid)}")
        else:
            config.is_enabled = is_enabled
            config.include_owner_email = include_owner_email
            config.notify_on = notify_on
            config.recipient_emails = sorted(set(emails))
            config.save()
            messages.success(request, "巡检邮件通知配置已保存")
            return redirect(f"/simulated-trading/my-accounts/{account_id}/inspection-notify/")

    context = {
        "account": account,
        "config": config,
        "recipient_emails_text": "\n".join(config.recipient_emails or []),
    }
    return render(request, "simulated_trading/inspection_notify.html", context)


# ============================================================================
# API 视图
# ============================================================================

class AccountListAPIView(APIView):
    """账户列表 API"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.account_repo = DjangoSimulatedAccountRepository()

    @extend_schema(
        summary="获取模拟账户列表",
        description="获取所有模拟账户（支持 active_only 过滤）",
        parameters=[
            OpenApiParameter(
                name='active_only',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description='是否只返回活跃账户（默认 true）'
            ),
        ],
        responses={200: AccountListResponseSerializer},
    )
    def get(self, request):
        """
        GET /api/simulated-trading/accounts/

        获取模拟账户列表

        Query Parameters:
        - active_only: true/false（默认 true）

        Response:
        {
            "success": true,
            "count": 2,
            "accounts": [...]
        }
        """
        active_only = request.query_params.get('active_only', 'true').lower() == 'true'

        use_case = ListAccountsUseCase(self.account_repo)
        accounts = use_case.execute(active_only=active_only)

        # 序列化账户
        account_list = []
        for account in accounts:
            account_list.append({
                'account_id': account.account_id,
                'account_name': account.account_name,
                'account_type': account.account_type.value,
                'initial_capital': str(account.initial_capital),
                'current_cash': str(account.current_cash),
                'current_market_value': str(account.current_market_value),
                'total_value': str(account.total_value),
                'total_return': account.total_return,
                'annual_return': account.annual_return,
                'max_drawdown': account.max_drawdown,
                'sharpe_ratio': account.sharpe_ratio,
                'win_rate': account.win_rate,
                'max_position_pct': account.max_position_pct,
                'stop_loss_pct': account.stop_loss_pct,
                'commission_rate': account.commission_rate,
                'slippage_rate': account.slippage_rate,
                'total_trades': account.total_trades,
                'winning_trades': account.winning_trades,
                'is_active': account.is_active,
                'auto_trading_enabled': account.auto_trading_enabled,
                'start_date': account.start_date.isoformat(),
                'last_trade_date': account.last_trade_date.isoformat() if account.last_trade_date else None,
                'created_at': (
                    getattr(account, 'created_at').isoformat()
                    if getattr(account, 'created_at', None)
                    else None
                ),
            })

        return Response({
            'success': True,
            'count': len(account_list),
            'accounts': account_list
        })

    @extend_schema(
        summary="创建模拟账户",
        description="创建新的模拟交易账户",
        request=CreateAccountRequestSerializer,
        responses={200: AccountResponseSerializer},
    )
    def post(self, request):
        """
        POST /api/simulated-trading/accounts/

        创建模拟账户

        Request Body:
        {
            "account_name": "测试账户1",
            "initial_capital": 100000.00,
            "max_position_pct": 20.0,
            "stop_loss_pct": 10.0,
            "commission_rate": 0.0003,
            "slippage_rate": 0.001
        }

        Response:
        {
            "success": true,
            "account": {...}
        }
        """
        # 1. 验证请求
        serializer = CreateAccountRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 2. 执行用例
        try:
            use_case = CreateSimulatedAccountUseCase(self.account_repo)
            account = use_case.execute(
                account_name=data['account_name'],
                initial_capital=float(data['initial_capital']),
                max_position_pct=data.get('max_position_pct', 20.0),
                stop_loss_pct=data.get('stop_loss_pct'),
                commission_rate=data.get('commission_rate', 0.0003),
                slippage_rate=data.get('slippage_rate', 0.001)
            )

            # 3. 序列化响应
            response_data = {
                'account_id': account.account_id,
                'account_name': account.account_name,
                'account_type': account.account_type.value,
                'initial_capital': str(account.initial_capital),
                'current_cash': str(account.current_cash),
                'current_market_value': str(account.current_market_value),
                'total_value': str(account.total_value),
                'total_return': None,
                'annual_return': None,
                'max_drawdown': None,
                'sharpe_ratio': None,
                'win_rate': None,
                'max_position_pct': account.max_position_pct,
                'stop_loss_pct': account.stop_loss_pct,
                'commission_rate': account.commission_rate,
                'slippage_rate': account.slippage_rate,
                'total_trades': account.total_trades,
                'winning_trades': account.winning_trades,
                'is_active': account.is_active,
                'auto_trading_enabled': account.auto_trading_enabled,
                'start_date': account.start_date.isoformat(),
                'last_trade_date': None,
                'created_at': None,
            }

            return Response({
                'success': True,
                'account': response_data
            }, status=status.HTTP_201_CREATED)

        except ValueError as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


class AccountDetailAPIView(APIView):
    """账户详情 API"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.account_repo = DjangoSimulatedAccountRepository()
        self.position_repo = DjangoPositionRepository()
        self.trade_repo = DjangoTradeRepository()

    @extend_schema(
        summary="获取账户详情",
        description="获取单个账户的完整信息",
        responses={200: AccountResponseSerializer},
    )
    def get(self, request, account_id):
        """
        GET /api/simulated-trading/accounts/{id}/

        获取账户详情

        Response:
        {
            "success": true,
            "account": {...}
        }
        """
        account = self.account_repo.get_by_id(account_id)
        if not account:
            return Response({
                'success': False,
                'error': f'账户不存在: {account_id}'
            }, status=status.HTTP_404_NOT_FOUND)

        response_data = {
            'account_id': account.account_id,
            'account_name': account.account_name,
            'account_type': account.account_type.value,
            'initial_capital': str(account.initial_capital),
            'current_cash': str(account.current_cash),
            'current_market_value': str(account.current_market_value),
            'total_value': str(account.total_value),
            'total_return': account.total_return,
            'annual_return': account.annual_return,
            'max_drawdown': account.max_drawdown,
            'sharpe_ratio': account.sharpe_ratio,
            'win_rate': account.win_rate,
            'max_position_pct': account.max_position_pct,
            'stop_loss_pct': account.stop_loss_pct,
            'commission_rate': account.commission_rate,
            'slippage_rate': account.slippage_rate,
            'total_trades': account.total_trades,
            'winning_trades': account.winning_trades,
            'is_active': account.is_active,
            'auto_trading_enabled': account.auto_trading_enabled,
            'start_date': account.start_date.isoformat(),
            'last_trade_date': account.last_trade_date.isoformat() if account.last_trade_date else None,
            'created_at': (
                getattr(account, 'created_at').isoformat()
                if getattr(account, 'created_at', None)
                else None
            ),
        }

        return Response({
            'success': True,
            'account': response_data
        })


class PositionListAPIView(APIView):
    """持仓列表 API"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.account_repo = DjangoSimulatedAccountRepository()
        self.position_repo = DjangoPositionRepository()

    @extend_schema(
        summary="获取账户持仓列表",
        description="获取指定账户的所有持仓",
        responses={200: PositionListResponseSerializer},
    )
    def get(self, request, account_id):
        """
        GET /api/simulated-trading/accounts/{id}/positions/

        获取账户持仓列表

        Response:
        {
            "success": true,
            "account_id": 1,
            "account_name": "测试账户1",
            "total_positions": 3,
            "total_market_value": "50000.00",
            "positions": [...]
        }
        """
        account = self.account_repo.get_by_id(account_id)
        if not account:
            return Response({
                'success': False,
                'error': f'账户不存在: {account_id}'
            }, status=status.HTTP_404_NOT_FOUND)

        positions = self.position_repo.get_by_account(account_id)

        # 序列化持仓
        position_list = []
        for pos in positions:
            position_list.append({
                'position_id': getattr(pos, 'position_id', None),
                'account_id': pos.account_id,
                'asset_code': pos.asset_code,
                'asset_name': pos.asset_name,
                'asset_type': pos.asset_type,
                'quantity': pos.quantity,
                'available_quantity': pos.available_quantity,
                'avg_cost': str(pos.avg_cost),
                'total_cost': str(pos.total_cost),
                'current_price': str(pos.current_price),
                'market_value': str(pos.market_value),
                'unrealized_pnl': str(pos.unrealized_pnl),
                'unrealized_pnl_pct': pos.unrealized_pnl_pct,
                'first_buy_date': pos.first_buy_date.isoformat(),
                'last_update_date': pos.last_update_date.isoformat(),
                'signal_id': pos.signal_id,
                'entry_reason': pos.entry_reason,
            })

        return Response({
            'success': True,
            'account_id': account_id,
            'account_name': account.account_name,
            'total_positions': len(position_list),
            'total_market_value': str(account.current_market_value),
            'positions': position_list
        })


class TradeListAPIView(APIView):
    """交易记录列表 API"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.account_repo = DjangoSimulatedAccountRepository()
        self.trade_repo = DjangoTradeRepository()

    @extend_schema(
        summary="获取账户交易记录",
        description="获取指定账户的交易记录（支持过滤）",
        parameters=[
            OpenApiParameter(name='start_date', type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY),
            OpenApiParameter(name='end_date', type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY),
            OpenApiParameter(name='asset_code', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY),
            OpenApiParameter(name='action', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY),
        ],
        responses={200: TradeListResponseSerializer},
    )
    def get(self, request, account_id):
        """
        GET /api/simulated-trading/accounts/{id}/trades/

        获取交易记录列表

        Query Parameters:
        - start_date: 开始日期（可选）
        - end_date: 结束日期（可选）
        - asset_code: 资产代码（可选）
        - action: 买入/卖出（可选）

        Response:
        {
            "success": true,
            "account_id": 1,
            "account_name": "测试账户1",
            "total_trades": 25,
            "total_buy_count": 15,
            "total_sell_count": 10,
            "total_realized_pnl": "5000.00",
            "trades": [...]
        }
        """
        account = self.account_repo.get_by_id(account_id)
        if not account:
            return Response({
                'success': False,
                'error': f'账户不存在: {account_id}'
            }, status=status.HTTP_404_NOT_FOUND)

        # 获取所有交易记录
        all_trades = self.trade_repo.get_by_account(account_id)

        # 应用过滤
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        asset_code = request.query_params.get('asset_code')
        action = request.query_params.get('action')

        filtered_trades = []
        for trade in all_trades:
            # 日期过滤
            if start_date:
                start = date.fromisoformat(start_date)
                if trade.execution_date < start:
                    continue
            if end_date:
                end = date.fromisoformat(end_date)
                if trade.execution_date > end:
                    continue

            # 资产过滤
            if asset_code and trade.asset_code != asset_code:
                continue

            # 方向过滤
            if action and trade.action.value != action:
                continue

            filtered_trades.append(trade)

        # 统计
        buy_count = sum(1 for t in filtered_trades if t.action.value == 'buy')
        sell_count = sum(1 for t in filtered_trades if t.action.value == 'sell')
        total_pnl = sum(t.realized_pnl or 0 for t in filtered_trades)

        # 序列化
        trade_list = []
        for trade in filtered_trades:
            trade_list.append({
                'trade_id': trade.trade_id,
                'account_id': trade.account_id,
                'asset_code': trade.asset_code,
                'asset_name': trade.asset_name,
                'asset_type': trade.asset_type,
                'action': trade.action.value,
                'quantity': trade.quantity,
                'price': str(trade.price),
                'amount': str(trade.amount),
                'commission': str(trade.commission),
                'slippage': str(trade.slippage),
                'total_cost': str(trade.total_cost),
                'realized_pnl': str(trade.realized_pnl) if trade.realized_pnl else None,
                'realized_pnl_pct': trade.realized_pnl_pct,
                'reason': trade.reason,
                'signal_id': trade.signal_id,
                'order_date': trade.order_date.isoformat(),
                'execution_date': trade.execution_date.isoformat(),
                'execution_time': trade.execution_time.isoformat(),
                'status': trade.status.value,
            })

        return Response({
            'success': True,
            'account_id': account_id,
            'account_name': account.account_name,
            'total_trades': len(trade_list),
            'total_buy_count': buy_count,
            'total_sell_count': sell_count,
            'total_realized_pnl': str(total_pnl),
            'trades': trade_list
        })


class PerformanceAPIView(APIView):
    """绩效分析 API"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.account_repo = DjangoSimulatedAccountRepository()
        self.position_repo = DjangoPositionRepository()
        self.trade_repo = DjangoTradeRepository()

    @extend_schema(
        summary="获取账户绩效",
        description="获取账户的完整绩效分析",
        responses={200: PerformanceResponseSerializer},
    )
    def get(self, request, account_id):
        """
        GET /api/simulated-trading/accounts/{id}/performance/

        获取账户绩效

        Response:
        {
            "success": true,
            "account": {...},
            "total_positions": 3,
            "total_trades": 25,
            "winning_trades": 15,
            "win_rate": 60.0,
            "performance": {
                "total_return": 10.5,
                "annual_return": 12.3,
                "max_drawdown": 5.2,
                "sharpe_ratio": 1.8,
                "win_rate": 60.0
            }
        }
        """
        use_case = GetAccountPerformanceUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )

        try:
            result = use_case.execute(account_id)

            # 序列化账户
            account_data = {
                'account_id': result['account'].account_id,
                'account_name': result['account'].account_name,
                'account_type': result['account'].account_type.value,
                'initial_capital': str(result['account'].initial_capital),
                'current_cash': str(result['account'].current_cash),
                'current_market_value': str(result['account'].current_market_value),
                'total_value': str(result['account'].total_value),
                'total_return': result['account'].total_return,
                'annual_return': result['account'].annual_return,
                'max_drawdown': result['account'].max_drawdown,
                'sharpe_ratio': result['account'].sharpe_ratio,
                'win_rate': result['account'].win_rate,
                'max_position_pct': result['account'].max_position_pct,
                'stop_loss_pct': result['account'].stop_loss_pct,
                'commission_rate': result['account'].commission_rate,
                'slippage_rate': result['account'].slippage_rate,
                'total_trades': result['account'].total_trades,
                'winning_trades': result['account'].winning_trades,
                'is_active': result['account'].is_active,
                'auto_trading_enabled': result['account'].auto_trading_enabled,
                'start_date': result['account'].start_date.isoformat(),
                'last_trade_date': result['account'].last_trade_date.isoformat() if result['account'].last_trade_date else None,
                'created_at': (
                    getattr(result['account'], 'created_at').isoformat()
                    if getattr(result['account'], 'created_at', None)
                    else None
                ),
            }

            return Response({
                'success': True,
                'account': account_data,
                'total_positions': result['total_positions'],
                'total_trades': result['total_trades'],
                'winning_trades': result['winning_trades'],
                'win_rate': result['win_rate'],
                'performance': result['performance']
            })

        except ValueError as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_404_NOT_FOUND)


class ManualTradeAPIView(APIView):
    """手动交易 API"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.account_repo = DjangoSimulatedAccountRepository()
        self.position_repo = DjangoPositionRepository()
        self.trade_repo = DjangoTradeRepository()

    @extend_schema(
        summary="手动交易",
        description="执行手动买入或卖出订单",
        request=ManualTradeRequestSerializer,
        responses={200: ManualTradeResponseSerializer},
    )
    def post(self, request, account_id):
        """
        POST /api/simulated-trading/accounts/{id}/trade/

        手动交易

        Request Body:
        {
            "asset_code": "000001.SZ",
            "asset_name": "平安银行",
            "asset_type": "equity",
            "action": "buy",
            "quantity": 1000,
            "price": 12.50,
            "reason": "测试买入"
        }

        Response:
        {
            "success": true,
            "message": "买入成功",
            "trade": {...}
        }
        """
        # 1. 验证请求
        serializer = ManualTradeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            # 2. 根据动作执行不同用例
            if data['action'] == 'buy':
                use_case = ExecuteBuyOrderUseCase(
                    self.account_repo,
                    self.position_repo,
                    self.trade_repo
                )
                trade = use_case.execute(
                    account_id=account_id,
                    asset_code=data['asset_code'],
                    asset_name=data['asset_name'],
                    asset_type=data['asset_type'],
                    quantity=data['quantity'],
                    price=float(data['price']),
                    reason=data.get('reason'),
                    signal_id=data.get('signal_id')
                )
                message = f"买入成功: {data['asset_name']} x{data['quantity']} @ {data['price']}"

            else:  # sell
                use_case = ExecuteSellOrderUseCase(
                    self.account_repo,
                    self.position_repo,
                    self.trade_repo
                )
                trade = use_case.execute(
                    account_id=account_id,
                    asset_code=data['asset_code'],
                    quantity=data['quantity'],
                    price=float(data['price']),
                    reason=data.get('reason')
                )
                message = f"卖出成功: {data['asset_name']} x{data['quantity']} @ {data['price']}"

            # 3. 序列化交易记录
            trade_data = {
                'trade_id': trade.trade_id,
                'account_id': trade.account_id,
                'asset_code': trade.asset_code,
                'asset_name': trade.asset_name,
                'asset_type': trade.asset_type,
                'action': trade.action.value,
                'quantity': trade.quantity,
                'price': str(trade.price),
                'amount': str(trade.amount),
                'commission': str(trade.commission),
                'slippage': str(trade.slippage),
                'total_cost': str(trade.total_cost),
                'realized_pnl': str(trade.realized_pnl) if trade.realized_pnl else None,
                'realized_pnl_pct': trade.realized_pnl_pct,
                'reason': trade.reason,
                'signal_id': trade.signal_id,
                'order_date': trade.order_date.isoformat(),
                'execution_date': trade.execution_date.isoformat(),
                'execution_time': trade.execution_time.isoformat(),
                'status': trade.status.value,
            }

            return Response({
                'success': True,
                'message': message,
                'trade': trade_data
            })

        except ValueError as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


class FeeConfigListAPIView(APIView):
    """费率配置列表 API"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fee_config_repo = DjangoFeeConfigRepository()

    @extend_schema(
        summary="获取费率配置列表",
        description="获取所有费率配置",
        responses={200: FeeConfigListResponseSerializer},
    )
    def get(self, request):
        """
        GET /api/simulated-trading/fee-configs/

        获取费率配置列表

        Response:
        {
            "success": true,
            "count": 6,
            "configs": [...]
        }
        """
        configs = self.fee_config_repo.get_all_configs()

        config_list = []
        for config in configs:
            config_list.append({
                'config_id': config.config_id,
                'config_name': config.config_name,
                'asset_type': config.asset_type,
                'commission_rate_buy': config.commission_rate_buy,
                'commission_rate_sell': config.commission_rate_sell,
                'min_commission': config.min_commission,
                'stamp_duty_rate': config.stamp_duty_rate,
                'transfer_fee_rate': config.transfer_fee_rate,
                'min_transfer_fee': config.min_transfer_fee,
                'slippage_rate': config.slippage_rate,
                'description': config.description,
            })

        return Response({
            'success': True,
            'count': len(config_list),
            'configs': config_list
        })


class EquityCurveAPIView(APIView):
    """净值曲线 API"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.account_repo = DjangoSimulatedAccountRepository()
        self.trade_repo = DjangoTradeRepository()
        self.performance_calculator = PerformanceCalculator()

    @extend_schema(
        summary="获取净值曲线",
        description="获取账户的净值曲线数据（用于图表）",
        parameters=[
            OpenApiParameter(name='start_date', type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY),
            OpenApiParameter(name='end_date', type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY),
        ],
        responses={200: EquityCurveResponseSerializer},
    )
    def get(self, request, account_id):
        """
        GET /api/simulated-trading/accounts/{id}/equity-curve/

        获取净值曲线

        Query Parameters:
        - start_date: 开始日期（可选）
        - end_date: 结束日期（可选）

        Response:
        {
            "success": true,
            "account_id": 1,
            "account_name": "测试账户1",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "data_points": [
                {
                    "date": "2024-01-01",
                    "net_value": 100000.00,
                    "trades_count": 2,
                    "daily_pnl": -500.00
                },
                ...
            ]
        }
        """
        account = self.account_repo.get_by_id(account_id)
        if not account:
            return Response({
                'success': False,
                'error': f'账户不存在: {account_id}'
            }, status=status.HTTP_404_NOT_FOUND)

        # 获取日期范围
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        if not start_date:
            start_date = account.start_date
        else:
            start_date = date.fromisoformat(start_date)

        if not end_date:
            end_date = date.today()
        else:
            end_date = date.fromisoformat(end_date)

        # 获取净值曲线
        data_points = self.performance_calculator.get_equity_curve(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date
        )

        return Response({
            'success': True,
            'account_id': account_id,
            'account_name': account.account_name,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'data_points': data_points
        })


class AutoTradingAPIView(APIView):
    """自动交易 API"""

    @extend_schema(
        summary="执行自动交易",
        description="手动触发自动交易引擎（用于测试或补跑）",
        request=AutoTradingRunRequestSerializer,
        responses={200: AutoTradingRunResponseSerializer},
    )
    def post(self, request):
        """
        POST /api/simulated-trading/auto-trading/run/

        执行自动交易

        Request Body:
        {
            "trade_date": "2024-01-15",
            "account_ids": [1, 2]  // 可选，空则全部活跃账户
        }

        Response:
        {
            "success": true,
            "trade_date": "2024-01-15",
            "total_accounts": 2,
            "results": {
                "1": {"buy_count": 3, "sell_count": 1},
                "2": {"buy_count": 2, "sell_count": 0}
            },
            "summary": {
                "total_buy_count": 5,
                "total_sell_count": 1
            }
        }
        """
        # 1. 验证请求
        serializer = AutoTradingRunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        trade_date = data.get('trade_date') or date.today()

        # 2. 初始化引擎
        account_repo = DjangoSimulatedAccountRepository()
        position_repo = DjangoPositionRepository()
        trade_repo = DjangoTradeRepository()

        buy_use_case = ExecuteBuyOrderUseCase(account_repo, position_repo, trade_repo)
        sell_use_case = ExecuteSellOrderUseCase(account_repo, position_repo, trade_repo)
        performance_use_case = GetAccountPerformanceUseCase(account_repo, position_repo, trade_repo)

        market_data = MarketDataProvider()
        asset_pool_service = AssetPoolQueryService()

        engine = AutoTradingEngine(
            account_repo=account_repo,
            position_repo=position_repo,
            trade_repo=trade_repo,
            buy_use_case=buy_use_case,
            sell_use_case=sell_use_case,
            performance_use_case=performance_use_case,
            asset_pool_service=asset_pool_service,
            market_data_provider=market_data,
        )

        # 3. 执行自动交易
        try:
            results = engine.run_daily_trading(trade_date)

            # 汇总统计
            total_buy_count = sum(r['buy_count'] for r in results.values())
            total_sell_count = sum(r['sell_count'] for r in results.values())

            return Response({
                'success': True,
                'trade_date': trade_date.isoformat(),
                'total_accounts': len(results),
                'results': results,
                'summary': {
                    'total_buy_count': total_buy_count,
                    'total_sell_count': total_sell_count
                }
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DailyInspectionRunAPIView(APIView):
    """手动触发日更巡检 API"""

    @extend_schema(
        summary="执行账户日更巡检",
        description="对指定账户执行一轮日更巡检并写入数据库",
        request=DailyInspectionRunRequestSerializer,
        responses={200: DailyInspectionReportListResponseSerializer},
    )
    def post(self, request, account_id):
        serializer = DailyInspectionRunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            result = DailyInspectionService.run(
                account_id=account_id,
                inspection_date=data.get("inspection_date") or date.today(),
                strategy_id=data.get("strategy_id"),
            )
            return Response({
                "success": True,
                "count": 1,
                "reports": [result],
            })
        except SimulatedAccountModel.DoesNotExist:
            return Response(
                {"success": False, "error": f"账户不存在: {account_id}"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DailyInspectionReportListAPIView(APIView):
    """账户日更巡检历史 API"""

    @extend_schema(
        summary="获取账户日更巡检历史",
        description="按账户查询日更巡检报告列表",
        parameters=[
            OpenApiParameter(name='limit', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY),
            OpenApiParameter(name='inspection_date', type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY),
        ],
        responses={200: DailyInspectionReportListResponseSerializer},
    )
    def get(self, request, account_id):
        if not SimulatedAccountModel._default_manager.filter(id=account_id).exists():
            return Response(
                {"success": False, "error": f"账户不存在: {account_id}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        limit = int(request.query_params.get("limit", 20))
        inspection_date_raw = request.query_params.get("inspection_date")

        queryset = DailyInspectionReportModel._default_manager.filter(account_id=account_id).order_by(
            "-inspection_date",
            "-updated_at",
        )
        if inspection_date_raw:
            queryset = queryset.filter(inspection_date=date.fromisoformat(inspection_date_raw))
        reports = queryset[:limit]

        payload = []
        for report in reports:
            payload.append(
                {
                    "report_id": report.id,
                    "account_id": report.account_id,
                    "inspection_date": report.inspection_date.isoformat(),
                    "status": report.status,
                    "macro_regime": report.macro_regime,
                    "policy_gear": report.policy_gear,
                    "strategy_id": report.strategy_id,
                    "position_rule_id": report.position_rule_id,
                    "summary": report.summary,
                    "checks": report.checks,
                }
            )

        return Response(
            {
                "success": True,
                "count": len(payload),
                "reports": payload,
            }
        )

