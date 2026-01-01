"""
Dashboard Interface Views

首页仪表盘视图 - 用户投资指挥中心。
"""

from django.shortcuts import render
from django.contrib.auth.decorators import login_required

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
    }

    return render(request, 'dashboard/index.html', context)
