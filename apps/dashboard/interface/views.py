"""
Dashboard Interface Views

首页仪表盘视图 - 用户投资指挥中心。

重构说明 (2026-03-11):
- 将跨模块数据获取逻辑从 views.py 移至 Query Services
- views.py 调用 Query Services 获取数据
- 隐藏 ORM 实现细节
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from django.shortcuts import redirect, render
from django.utils import timezone as django_timezone
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseNotAllowed
from django.conf import settings
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.cache_utils import cached_api, CACHE_TTL
from apps.account.interface.authentication import MultiTokenAuthentication
from apps.account.infrastructure.repositories import (
    AccountRepository,
    PortfolioRepository,
    PositionRepository,
)
from apps.dashboard.application.use_cases import GetDashboardDataUseCase
from apps.dashboard.application.queries import (
    get_alpha_visualization_query,
    get_dashboard_detail_query,
    get_decision_plane_query,
    get_regime_summary_query,
)
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
# Alpha 可视化数据获取函数（委托至 Query Services）
# ========================================

def _get_alpha_stock_scores(top_n: int = 10) -> list:
    """
    获取 Alpha 选股评分结果

    重构说明 (2026-03-11):
    - 委托至 AlphaVisualizationQuery
    - 隐藏跨模块导入细节
    """
    try:
        query = get_alpha_visualization_query()
        data = query.execute(top_n=top_n, ic_days=30)
        return data.stock_scores
    except Exception as e:
        logger.warning(f"Failed to get alpha stock scores: {e}")
        return []


def _get_alpha_provider_status() -> dict:
    """
    获取 Alpha Provider 状态

    重构说明 (2026-03-11):
    - 委托至 AlphaVisualizationQuery
    """
    try:
        query = get_alpha_visualization_query()
        data = query.execute(top_n=10, ic_days=30)
        return data.provider_status
    except Exception as e:
        logger.warning(f"Failed to get alpha provider status: {e}")
        return {"providers": {}, "metrics": {}, "timestamp": None}


def _get_alpha_coverage_metrics() -> dict:
    """
    获取 Alpha 覆盖率指标

    重构说明 (2026-03-11):
    - 委托至 AlphaVisualizationQuery
    """
    try:
        query = get_alpha_visualization_query()
        data = query.execute(top_n=10, ic_days=30)
        return data.coverage_metrics
    except Exception as e:
        logger.warning(f"Failed to get alpha coverage metrics: {e}")
        return {
            "coverage_ratio": 0.0,
            "total_requests": 0,
            "cache_hit_rate": 0.0,
            "timestamp": None,
        }


def _get_alpha_ic_trends(days: int = 30) -> list:
    """
    获取 Alpha IC/ICIR 趋势数据

    重构说明 (2026-03-11):
    - 委托至 AlphaVisualizationQuery
    """
    try:
        query = get_alpha_visualization_query()
        data = query.execute(top_n=10, ic_days=days)
        return data.ic_trends
    except Exception as e:
        logger.warning(f"Failed to get alpha IC trends: {e}")
        return []


def _build_alpha_factor_panel(stock_code: str, source: str | None = None, top_n: int = 10) -> dict:
    """Build factor panel data for a single alpha stock."""
    selected = None
    scores = _get_alpha_stock_scores(top_n=max(top_n, 10))
    for item in scores:
        if item.get("code") == stock_code:
            selected = item
            break

    provider = source or (selected.get("source") if selected else "unknown")
    factors = dict(selected.get("factors") or {}) if selected else {}
    factor_origin = "score_payload" if factors else ""
    empty_reason = ""

    if not factors and provider in {"simple", "qlib", "etf"}:
        try:
            from apps.alpha.application.services import AlphaService

            service = AlphaService()
            provider_instance = service._registry.get_provider(provider)
            if provider_instance:
                factors = provider_instance.get_factor_exposure(stock_code, date.today()) or {}
                if factors:
                    factor_origin = f"{provider}_provider"
        except Exception as exc:
            logger.warning("Failed to load factor exposure for %s: %s", stock_code, exc)

    if not factors:
        if provider == "qlib":
            empty_reason = "当前 Qlib 流程可展示评分与 IC/ICIR，但尚未输出可视化用的单股因子暴露。"
        elif provider == "cache":
            empty_reason = "当前缓存记录未包含因子明细，请等待新的带因子评分结果写入缓存。"
        elif provider == "etf":
            empty_reason = "ETF 兜底源只提供成份股替代结果，不提供单股因子暴露。"
        else:
            empty_reason = "当前股票暂无可展示的因子暴露数据。"

    sorted_factors = sorted(
        (
            {
                "name": key,
                "value": float(value),
                "abs_value": abs(float(value)),
                "bar_width": min(abs(float(value)) * 100, 100),
                "direction": "positive" if float(value) >= 0 else "negative",
            }
            for key, value in factors.items()
        ),
        key=lambda item: item["abs_value"],
        reverse=True,
    )

    return {
        "stock": selected,
        "stock_code": stock_code,
        "provider": provider,
        "factor_origin": factor_origin,
        "factors": sorted_factors,
        "factor_count": len(sorted_factors),
        "empty_reason": empty_reason,
    }


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

    actionable_candidates = _get_actionable_candidates()
    pending_requests = _get_pending_requests()
    alpha_stock_scores = _get_alpha_stock_scores(top_n=10)
    initial_alpha_stock = alpha_stock_scores[0]["code"] if alpha_stock_scores else ""
    try:
        from apps.equity.application.config import get_valuation_repair_config_summary
        valuation_repair_config_summary = get_valuation_repair_config_summary(use_cache=False)
    except Exception as e:
        logger.warning(f"Failed to get valuation repair config summary: {e}")
        valuation_repair_config_summary = None

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
        "regime_data_health": data.regime_data_health,
        "regime_warnings": data.regime_warnings,
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
        "actionable_candidates": actionable_candidates,
        "pending_requests": pending_requests,
        "pending_count": len(pending_requests),
        # Alpha 可视化数据（新增）
        "alpha_stock_scores": alpha_stock_scores,
        "alpha_provider_status": _get_alpha_provider_status(),
        "alpha_coverage_metrics": _get_alpha_coverage_metrics(),
        "alpha_ic_trends": _get_alpha_ic_trends(days=30),
        "alpha_factor_panel": _build_alpha_factor_panel(initial_alpha_stock, top_n=10),
        "valuation_repair_config_summary": valuation_repair_config_summary,
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
    context = get_dashboard_detail_query().get_position_detail(
        user_id=request.user.id,
        asset_code=asset_code,
    )

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
@authentication_classes([SessionAuthentication, MultiTokenAuthentication])
@permission_classes([IsAuthenticated])
@cached_api(key_prefix='dashboard_summary', ttl_seconds=CACHE_TTL['dashboard_summary'], include_user=True)
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
@authentication_classes([SessionAuthentication, MultiTokenAuthentication])
@permission_classes([IsAuthenticated])
@cached_api(key_prefix='regime_quadrant', ttl_seconds=CACHE_TTL['regime_current'], include_user=False)
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
@authentication_classes([SessionAuthentication, MultiTokenAuthentication])
@permission_classes([IsAuthenticated])
def equity_curve_v1(request):
    """
    Equity curve data for Streamlit.
    """
    requested_range = request.GET.get("range", "ALL").upper()
    data = _build_dashboard_data(request.user.id)
    series = data.performance_data if hasattr(data, "performance_data") else []

    if not series:
        # Defensive fallback for first-load or empty-history edge cases.
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
@authentication_classes([SessionAuthentication, MultiTokenAuthentication])
@permission_classes([IsAuthenticated])
@cached_api(key_prefix='signal_status', ttl_seconds=CACHE_TTL['signal_list'], vary_on=['limit'], include_user=True)
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
# 决策平面数据获取辅助函数（委托至 Query Services）
# ========================================

def _get_beta_gate_visible_classes() -> str:
    """
    获取 Beta Gate 允许的可见资产类别

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute()
        return data.beta_gate_visible_classes
    except Exception as e:
        logger.warning(f"Failed to get beta gate visible classes: {e}")
        return "-"


def _get_alpha_status_count(status: str) -> int:
    """
    获取 Alpha 候选状态计数

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute()
        if status == "WATCH":
            return data.alpha_watch_count
        elif status == "CANDIDATE":
            return data.alpha_candidate_count
        elif status == "ACTIONABLE":
            return data.alpha_actionable_count
        return 0
    except Exception as e:
        logger.warning(f"Failed to get alpha status count for {status}: {e}")
        return 0


def _get_quota_total() -> int:
    """
    获取决策配额总数

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute()
        return data.quota_total
    except Exception as e:
        logger.warning(f"Failed to get quota total: {e}")
        return 10


def _get_quota_used() -> int:
    """
    获取已使用的决策配额

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute()
        return data.quota_used
    except Exception as e:
        logger.warning(f"Failed to get quota used: {e}")
        return 0


def _get_quota_remaining() -> int:
    """
    获取剩余决策配额

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute()
        return data.quota_remaining
    except Exception as e:
        logger.warning(f"Failed to get quota remaining: {e}")
        return 10


def _get_quota_usage_percent() -> float:
    """
    获取决策配额使用百分比

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute()
        return data.quota_usage_percent
    except Exception as e:
        logger.warning(f"Failed to get quota usage percent: {e}")
        return 0.0


def _get_actionable_candidates():
    """
    首页主流程展示：可操作候选列表（含估值修复信息）

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute(max_candidates=5, max_pending=10)
        return data.actionable_candidates
    except Exception as e:
        logger.warning(f"Failed to get actionable candidates: {e}")
        return []


def _get_pending_requests():
    """
    首页主流程展示：已批准但未执行/失败待重试请求

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute(max_candidates=5, max_pending=10)
        return data.pending_requests
    except Exception as e:
        logger.warning(f"Failed to get pending requests: {e}")
        return []


def _get_pending_count() -> int:
    try:
        return len(_get_pending_requests())
    except Exception:
        return 0


@login_required(login_url="/account/login/")
def workflow_refresh_candidates(request):
    """
    主流程候选刷新：从活跃触发器补齐候选，并尝试提升高置信候选为 ACTIONABLE。
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        result = get_dashboard_detail_query().generate_alpha_candidates()

        return JsonResponse({
            "success": True,
            "result": result,
        })

    except Exception as e:
        logger.error(f"Failed to refresh workflow candidates: {e}", exc_info=True)
        return JsonResponse({"success": False, "error": str(e)}, status=500)


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


@login_required(login_url="/account/login/")
def alpha_factor_panel_htmx(request):
    """HTMX factor panel for a selected alpha stock."""
    if 'HX-Request' not in request.headers:
        return redirect('dashboard:index')

    stock_code = (request.GET.get('code') or '').strip()
    source = (request.GET.get('source') or '').strip() or None
    top_n = int(request.GET.get('top_n', 10))

    if not stock_code:
        return render(
            request,
            'dashboard/partials/alpha_factor_panel.html',
            {
                'stock': None,
                'stock_code': '',
                'provider': source or 'unknown',
                'factor_origin': '',
                'factors': [],
                'factor_count': 0,
                'empty_reason': '请选择左侧一只股票查看因子暴露。',
            },
        )

    context = _build_alpha_factor_panel(stock_code=stock_code, source=source, top_n=top_n)
    return render(request, 'dashboard/partials/alpha_factor_panel.html', context)
