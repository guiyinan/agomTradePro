"""
Dashboard Interface Views

首页仪表盘视图 - 用户投资指挥中心。
"""

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from apps.dashboard.application.use_cases import GetDashboardDataUseCase
from apps.account.infrastructure.repositories import AccountRepository
from apps.account.infrastructure.repositories import PortfolioRepository
from apps.account.infrastructure.repositories import PositionRepository
from apps.regime.infrastructure.repositories import DjangoRegimeRepository
from apps.signal.infrastructure.repositories import DjangoSignalRepository


@login_required(login_url="/account/login/")
def dashboard_view(request):
    """
    首页仪表盘视图

    展示：
    1. 宏观环境快照（当前Regime）
    2. 我的资产总览
    3. 当前持仓列表
    4. 我的投资信号
    5. AI操作建议
    """
    # 创建用例（依赖注入）
    use_case = GetDashboardDataUseCase(
        account_repo=AccountRepository(),
        portfolio_repo=PortfolioRepository(),
        position_repo=PositionRepository(),
        regime_repo=DjangoRegimeRepository(),
        signal_repo=DjangoSignalRepository(),
    )

    # 获取首页数据
    data = use_case.execute(request.user.id)

    # 补充用户名
    data.username = request.user.username

    context = {
        "user": request.user,
        "display_name": data.display_name,
        # 宏观环境
        "current_regime": data.current_regime,
        "regime_date": data.regime_date,
        "regime_confidence": data.regime_confidence,
        "regime_confidence_pct": data.regime_confidence * 100,
        "growth_momentum_z": data.growth_momentum_z,
        "inflation_momentum_z": data.inflation_momentum_z,
        "regime_distribution": data.regime_distribution,
        "pmi_value": data.pmi_value,
        "cpi_value": data.cpi_value,
        # 政策档位
        "policy_level": data.current_policy_level,
        # 资产总览
        "total_assets": data.total_assets,
        "initial_capital": data.initial_capital,
        "total_return": data.total_return,
        "total_return_pct": data.total_return_pct,
        "cash_balance": data.cash_balance,
        "invested_value": data.invested_value,
        "invested_ratio": data.invested_ratio,
        # 持仓
        "positions": data.positions,
        "position_count": data.position_count,
        "regime_match_score": data.regime_match_score,
        "regime_recommendations": data.regime_recommendations,
        # 信号
        "active_signals": data.active_signals,
        "signal_stats": data.signal_stats,
        # 资产配置
        "asset_allocation": data.asset_allocation,
        # AI建议
        "ai_insights": data.ai_insights,
        # 新增：图表数据
        "allocation_data": data.allocation_data if hasattr(data, 'allocation_data') else {},
        "performance_data": data.performance_data if hasattr(data, 'performance_data') else [],
    }

    return render(request, 'dashboard/index.html', context)


# ========================================
# HTMX 专用视图
# ========================================

@login_required(login_url="/account/login/")
def position_detail_htmx(request, asset_code: str):
    """
    HTMX 持仓详情视图

    用于在模态框中显示持仓详情，包括：
    - 持仓基本信息
    - 历史价格走势
    - 相关投资信号
    """
    from apps.account.infrastructure.models import PositionModel

    try:
        position = PositionModel.objects.get(
            user=request.user,
            asset_code=asset_code
        )
    except PositionModel.DoesNotExist:
        context = {
            'error': f'未找到持仓 {asset_code}'
        }
    else:
        # 获取相关信号
        from apps.signal.infrastructure.models import InvestmentSignalModel
        related_signals = InvestmentSignalModel.objects.filter(
            asset_code=asset_code,
            status='active'
        ).order_by('-created_at')[:5]

        context = {
            'position': position,
            'related_signals': related_signals,
            'asset_code': asset_code,
        }

    return render(request, 'dashboard/partials/position_detail.html', context)


@login_required(login_url="/account/login/")
def positions_list_htmx(request):
    """
    HTMX 持仓列表视图

    支持排序和筛选的持仓列表，用于动态更新。
    """
    use_case = GetDashboardDataUseCase(
        account_repo=AccountRepository(),
        portfolio_repo=PortfolioRepository(),
        position_repo=PositionRepository(),
        regime_repo=DjangoRegimeRepository(),
        signal_repo=DjangoSignalRepository(),
    )

    data = use_case.execute(request.user.id)
    positions = list(data.positions)

    # 获取排序参数
    sort_by = request.GET.get('sort', 'market_value')

    # 排序
    if sort_by == 'code':
        positions.sort(key=lambda p: p.asset_code)
    elif sort_by == 'pnl_pct':
        positions.sort(key=lambda p: p.unrealized_pnl_pct or 0, reverse=True)
    elif sort_by == 'market_value':
        positions.sort(key=lambda p: p.market_value or 0, reverse=True)

    context = {
        'positions': positions,
    }

    return render(request, 'dashboard/partials/positions_table.html', context)


@login_required(login_url="/account/login/")
def allocation_chart_htmx(request):
    """
    HTMX 资产配置图表数据

    返回 JSON 格式的资产配置数据，用于前端图表更新。
    """
    use_case = GetDashboardDataUseCase(
        account_repo=AccountRepository(),
        portfolio_repo=PortfolioRepository(),
        position_repo=PositionRepository(),
        regime_repo=DjangoRegimeRepository(),
        signal_repo=DjangoSignalRepository(),
    )

    data = use_case.execute(request.user.id)

    allocation_data = data.allocation_data if hasattr(data, 'allocation_data') else {}

    return JsonResponse({
        'success': True,
        'data': allocation_data
    })


@login_required(login_url="/account/login/")
def performance_chart_htmx(request):
    """
    HTMX 收益趋势图表数据

    返回 JSON 格式的收益历史数据。
    """
    use_case = GetDashboardDataUseCase(
        account_repo=AccountRepository(),
        portfolio_repo=PortfolioRepository(),
        position_repo=PositionRepository(),
        regime_repo=DjangoRegimeRepository(),
        signal_repo=DjangoSignalRepository(),
    )

    data = use_case.execute(request.user.id)

    performance_data = data.performance_data if hasattr(data, 'performance_data') else []

    return JsonResponse({
        'success': True,
        'data': performance_data
    })
