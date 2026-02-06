"""
Dashboard Interface Views

首页仪表盘视图 - 用户投资指挥中心。
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.conf import settings
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.dashboard.application.use_cases import GetDashboardDataUseCase
from apps.account.infrastructure.repositories import AccountRepository
from apps.account.infrastructure.repositories import PortfolioRepository
from apps.account.infrastructure.repositories import PositionRepository
from apps.regime.infrastructure.repositories import DjangoRegimeRepository
from apps.signal.infrastructure.repositories import DjangoSignalRepository


logger = logging.getLogger(__name__)


def _build_dashboard_data(user_id: int):
    """Build dashboard DTO for API and page views."""
    use_case = GetDashboardDataUseCase(
        account_repo=AccountRepository(),
        portfolio_repo=PortfolioRepository(),
        position_repo=PositionRepository(),
        regime_repo=DjangoRegimeRepository(),
        signal_repo=DjangoSignalRepository(),
    )
    return use_case.execute(user_id)


# ========================================
# Alpha 可视化数据获取函数
# ========================================

def _get_alpha_stock_scores(top_n: int = 10) -> list:
    """获取 Alpha 选股评分结果"""
    try:
        from apps.alpha.application.services import AlphaService

        service = AlphaService()
        result = service.get_stock_scores(
            universe_id="csi300",
            intended_trade_date=date.today(),
            top_n=top_n
        )

        if result.success and result.scores:
            return [
                {
                    "code": score.code,
                    "score": round(score.score, 4),
                    "rank": score.rank,
                    "source": score.source,
                    "confidence": round(score.confidence, 3),
                    "factors": score.factors,
                    "asof_date": score.asof_date.isoformat() if score.asof_date else None,
                }
                for score in result.scores[:top_n]
            ]
        return []
    except Exception as e:
        logger.warning(f"Failed to get alpha stock scores: {e}")
        return []


def _get_alpha_provider_status() -> dict:
    """获取 Alpha Provider 状态"""
    try:
        from apps.alpha.application.services import AlphaService
        from shared.infrastructure.metrics import get_alpha_metrics

        service = AlphaService()
        provider_status = service.get_provider_status()
        metrics = get_alpha_metrics()

        # 获取成功率指标
        provider_metrics = {}
        for provider_name in provider_status.keys():
            success_rate = metrics.registry.get_metric(
                "alpha_provider_success_rate",
                {"provider": provider_name}
            )
            latency = metrics.registry.get_metric(
                "alpha_provider_latency_ms",
                {"provider": provider_name}
            )

            provider_metrics[provider_name] = {
                "success_rate": round(success_rate.value, 3) if success_rate else 0.0,
                "latency_ms": int(latency.value) if latency else 0,
            }

        return {
            "providers": provider_status,
            "metrics": provider_metrics,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.warning(f"Failed to get alpha provider status: {e}")
        return {"providers": {}, "metrics": {}, "timestamp": None}


def _get_alpha_coverage_metrics() -> dict:
    """获取 Alpha 覆盖率指标"""
    try:
        from shared.infrastructure.metrics import get_alpha_metrics

        metrics = get_alpha_metrics()

        coverage = metrics.registry.get_metric("alpha_coverage_ratio")
        request_count = metrics.registry.get_metric("alpha_score_request_count")
        cache_hit_rate = metrics.registry.get_metric("alpha_cache_hit_rate")

        return {
            "coverage_ratio": round(coverage.value, 3) if coverage else 0.0,
            "total_requests": int(request_count.value) if request_count else 0,
            "cache_hit_rate": round(cache_hit_rate.value, 3) if cache_hit_rate else 0.0,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.warning(f"Failed to get alpha coverage metrics: {e}")
        return {
            "coverage_ratio": 0.0,
            "total_requests": 0,
            "cache_hit_rate": 0.0,
            "timestamp": None,
        }


def _get_alpha_ic_trends(days: int = 30) -> list:
    """获取 Alpha IC/ICIR 趋势数据"""
    try:
        from apps.alpha.infrastructure.models import QlibModelRegistryModel
        from datetime import timedelta

        # 获取激活的模型
        active_models = QlibModelRegistryModel._default_manager.filter(is_active=True)

        if not active_models.exists():
            # 没有激活模型时返回模拟数据
            return _generate_mock_ic_data(days)

        # 从模型历史记录中获取 IC 数据
        trends = []
        base_date = date.today()

        for i in range(days):
            check_date = base_date - timedelta(days=i)

            # 查找该日期附近的模型评估记录
            model_metrics = QlibModelRegistryModel._default_manager.filter(
                created_at__date=check_date
            ).first()

            if model_metrics:
                trends.append({
                    "date": check_date.isoformat(),
                    "ic": round(float(model_metrics.ic), 4) if model_metrics.ic else None,
                    "icir": round(float(model_metrics.icir), 4) if model_metrics.icir else None,
                    "rank_ic": round(float(model_metrics.rank_ic), 4) if model_metrics.rank_ic else None,
                })
            else:
                trends.append({
                    "date": check_date.isoformat(),
                    "ic": None,
                    "icir": None,
                    "rank_ic": None,
                })

        return list(reversed(trends))

    except Exception as e:
        logger.warning(f"Failed to get alpha IC trends: {e}")
        return _generate_mock_ic_data(days)


def _generate_mock_ic_data(days: int) -> list:
    """生成模拟 IC 数据（用于演示）"""
    import random

    trends = []
    base_date = date.today()
    base_ic = 0.05

    for i in range(days):
        check_date = base_date - timedelta(days=days - i)
        # 模拟 IC 波动
        ic = base_ic + random.uniform(-0.02, 0.02)
        icir = ic * random.uniform(0.5, 1.5)
        rank_ic = ic * random.uniform(0.8, 1.2)

        trends.append({
            "date": check_date.isoformat(),
            "ic": round(ic, 4),
            "icir": round(icir, 4),
            "rank_ic": round(rank_ic, 4),
        })

    return trends


@login_required(login_url="/account/login/")
def dashboard_entry(request):
    """
    Dashboard entrypoint.

    If Streamlit dashboard is enabled, redirect to Streamlit URL.
    Otherwise fall back to legacy Django dashboard page.
    """
    if settings.STREAMLIT_DASHBOARD_ENABLED:
        return redirect(settings.STREAMLIT_DASHBOARD_URL)
    return dashboard_view(request)


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
    # 获取首页数据
    data = _build_dashboard_data(request.user.id)

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
        # 资产配置建议（新增）
        "allocation_advice": data.allocation_advice,
        # 新增：图表数据
        "allocation_data": data.allocation_data if hasattr(data, 'allocation_data') else {},
        "performance_data": data.performance_data if hasattr(data, 'performance_data') else [],
        # 决策平面数据（新增）
        "beta_gate_visible_classes": _get_beta_gate_visible_classes(),
        "alpha_watch_count": _get_alpha_status_count("WATCH"),
        "alpha_candidate_count": _get_alpha_status_count("CANDIDATE"),
        "alpha_actionable_count": _get_alpha_status_count("ACTIONABLE"),
        "quota_total": _get_quota_total(),
        "quota_used": _get_quota_used(),
        "quota_remaining": _get_quota_remaining(),
        "quota_usage_percent": _get_quota_usage_percent(),
        # Alpha 可视化数据（新增）
        "alpha_stock_scores": _get_alpha_stock_scores(top_n=10),
        "alpha_provider_status": _get_alpha_provider_status(),
        "alpha_coverage_metrics": _get_alpha_coverage_metrics(),
        "alpha_ic_trends": _get_alpha_ic_trends(days=30),
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
        position = PositionModel._default_manager.get(
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
        related_signals = InvestmentSignalModel._default_manager.filter(
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
    # If not accessed via HTMX, redirect to main dashboard
    if 'HX-Request' not in request.headers:
        from django.shortcuts import redirect
        return redirect('dashboard:index')

    data = _build_dashboard_data(request.user.id)
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
    data = _build_dashboard_data(request.user.id)

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
    data = _build_dashboard_data(request.user.id)

    performance_data = data.performance_data if hasattr(data, 'performance_data') else []

    return JsonResponse({
        'success': True,
        'data': performance_data
    })


@api_view(["GET"])
@authentication_classes([SessionAuthentication, TokenAuthentication])
@permission_classes([IsAuthenticated])
def dashboard_summary_v1(request):
    """Summary endpoint for Streamlit dashboard."""
    data = _build_dashboard_data(request.user.id)
    return Response(
        {
            "user": {
                "id": request.user.id,
                "username": request.user.username,
                "display_name": data.display_name,
            },
            "regime": {
                "current": data.current_regime,
                "confidence": data.regime_confidence,
                "date": data.regime_date.isoformat() if data.regime_date else None,
            },
            "portfolio": {
                "total_assets": data.total_assets,
                "initial_capital": data.initial_capital,
                "total_return": data.total_return,
                "total_return_pct": data.total_return_pct,
                "cash_balance": data.cash_balance,
                "invested_value": data.invested_value,
                "invested_ratio": data.invested_ratio,
            },
        }
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication, TokenAuthentication])
@permission_classes([IsAuthenticated])
def regime_quadrant_v1(request):
    """Regime quadrant data for Streamlit visualization."""
    data = _build_dashboard_data(request.user.id)
    return Response(
        {
            "current_regime": data.current_regime,
            "distribution": data.regime_distribution or {},
            "confidence": data.regime_confidence,
            "as_of_date": data.regime_date.isoformat() if data.regime_date else None,
            "macro": {
                "pmi": data.pmi_value,
                "cpi": data.cpi_value,
                "growth_momentum_z": data.growth_momentum_z,
                "inflation_momentum_z": data.inflation_momentum_z,
            },
        }
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication, TokenAuthentication])
@permission_classes([IsAuthenticated])
def equity_curve_v1(request):
    """
    Equity curve data for Streamlit.

    Note: historical snapshots are not fully implemented in current backend.
    """
    requested_range = request.GET.get("range", "ALL").upper()
    data = _build_dashboard_data(request.user.id)
    series = data.performance_data if hasattr(data, "performance_data") else []

    if not series:
        # Fallback keeps chart usable until snapshot history is implemented.
        series = [
            {
                "date": date.today().isoformat(),
                "portfolio_value": data.total_assets,
                "return_pct": data.total_return_pct,
            }
        ]

    return Response(
        {
            "range": requested_range,
            "has_history": bool(data.performance_data),
            "series": series,
        }
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication, TokenAuthentication])
@permission_classes([IsAuthenticated])
def signal_status_v1(request):
    """Signal status and recent signal list for Streamlit."""
    try:
        limit = max(1, min(int(request.GET.get("limit", 50)), 200))
    except ValueError:
        limit = 50

    data = _build_dashboard_data(request.user.id)
    signals = data.active_signals if data.active_signals else []
    return Response(
        {
            "stats": data.signal_stats,
            "signals": signals[:limit],
            "limit": limit,
        }
    )


# ========================================
# 决策平面数据获取辅助函数
# ========================================

def _get_beta_gate_visible_classes() -> str:
    """获取 Beta Gate 允许的可见资产类别"""
    try:
        from apps.beta_gate.infrastructure.models import GateConfigModel
        config = GateConfigModel._default_manager.active().first()
        if config:
            regime_c = config.regime_constraints if isinstance(config.regime_constraints, dict) else {}
            allowed_classes = regime_c.get('allowed_asset_classes', [])
            if allowed_classes:
                return ", ".join(allowed_classes[:3])
        return "全部"
    except Exception as e:
        logger.warning(f"Failed to get beta gate visible classes: {e}")
        return "-"


def _get_alpha_status_count(status: str) -> int:
    """获取 Alpha 候选状态计数"""
    try:
        from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel
        return AlphaCandidateModel._default_manager.filter(status=status).count()
    except Exception as e:
        logger.warning(f"Failed to get alpha status count for {status}: {e}")
        return 0


def _get_quota_total() -> int:
    """获取决策配额总数"""
    try:
        from apps.decision_rhythm.infrastructure.models import DecisionQuotaModel
        quota = DecisionQuotaModel._default_manager.filter(is_active=True).order_by('-period_start').first()
        return getattr(quota, "max_decisions", 10) if quota else 10
    except Exception as e:
        logger.warning(f"Failed to get quota total: {e}")
        return 10


def _get_quota_used() -> int:
    """获取已使用的决策配额"""
    try:
        from apps.decision_rhythm.infrastructure.models import DecisionQuotaModel
        quota = DecisionQuotaModel._default_manager.filter(is_active=True).order_by('-period_start').first()
        return getattr(quota, "used_decisions", 0) if quota else 0
    except Exception as e:
        logger.warning(f"Failed to get quota used: {e}")
        return 0


def _get_quota_remaining() -> int:
    """获取剩余决策配额"""
    try:
        from apps.decision_rhythm.infrastructure.models import DecisionQuotaModel
        quota = DecisionQuotaModel._default_manager.filter(is_active=True).order_by('-period_start').first()
        if quota:
            max_decisions = getattr(quota, "max_decisions", 10)
            used_decisions = getattr(quota, "used_decisions", 0)
            return max(0, max_decisions - used_decisions)
        return 10
    except Exception as e:
        logger.warning(f"Failed to get quota remaining: {e}")
        return 10


def _get_quota_usage_percent() -> float:
    """获取决策配额使用百分比"""
    try:
        total = _get_quota_total()
        used = _get_quota_used()
        if total > 0:
            return round(used / total * 100, 1)
        return 0.0
    except Exception as e:
        logger.warning(f"Failed to get quota usage percent: {e}")
        return 0.0


# ========================================
# Alpha 可视化 HTMX 视图
# ========================================

@login_required(login_url="/account/login/")
def alpha_stocks_htmx(request):
    """
    HTMX Alpha 选股结果视图

    返回 Alpha 选股评分表格，支持动态刷新。
    """
    if 'HX-Request' not in request.headers:
        from django.shortcuts import redirect
        return redirect('dashboard:index')

    top_n = int(request.GET.get('top_n', 10))
    scores = _get_alpha_stock_scores(top_n=top_n)

    context = {
        'alpha_stocks': scores,
        'top_n': top_n,
    }

    return render(request, 'dashboard/partials/alpha_stocks_table.html', context)


@login_required(login_url="/account/login/")
def alpha_provider_status_htmx(request):
    """
    HTMX Alpha Provider 状态视图

    返回 Provider 状态面板 JSON 数据。
    """
    provider_status = _get_alpha_provider_status()

    return JsonResponse({
        'success': True,
        'data': provider_status
    })


@login_required(login_url="/account/login/")
def alpha_coverage_htmx(request):
    """
    HTMX Alpha 覆盖率指标视图

    返回覆盖率指标 JSON 数据。
    """
    coverage = _get_alpha_coverage_metrics()

    return JsonResponse({
        'success': True,
        'data': coverage
    })


@login_required(login_url="/account/login/")
def alpha_ic_trends_htmx(request):
    """
    HTMX Alpha IC/ICIR 趋势图数据视图

    返回 IC 趋势 JSON 数据。
    """
    days = int(request.GET.get('days', 30))
    trends = _get_alpha_ic_trends(days=days)

    return JsonResponse({
        'success': True,
        'data': trends
    })


