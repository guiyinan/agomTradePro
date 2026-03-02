"""
Core Views for AgomSAAF

项目级视图函数
"""

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from datetime import date
from apps.regime.application.current_regime import resolve_current_regime


def index_view(request):
    """首页视图 - 重定向到 Dashboard"""
    from django.shortcuts import redirect
    return redirect('/dashboard/')


def health_view(request):
    """健康检查（公开端点，无需登录）"""
    from django.http import JsonResponse
    return JsonResponse({'status': 'healthy'})


def chat_example_view(request):
    """聊天组件示例页面"""
    return render(request, 'components/chat_example.html')


@login_required
def asset_screen_view(request):
    """
    资产筛选页面

    统一的多资产筛选和资产池管理界面
    """
    from apps.policy.infrastructure.repositories import DjangoPolicyRepository
    from apps.sentiment.infrastructure.repositories import SentimentIndexRepository

    # 获取当前上下文信息
    current_regime = resolve_current_regime()

    policy_repo = DjangoPolicyRepository()
    latest_policy = policy_repo.get_current_policy_level()

    sentiment_repo = SentimentIndexRepository()
    latest_sentiment = sentiment_repo.get_latest()

    regime_display = {
        'Recovery': '复苏',
        'Overheat': '过热',
        'Stagflation': '滞胀',
        'Deflation': '通缩',
    }

    policy_display = {
        'P0': 'P0（极度宽松）',
        'P1': 'P1（宽松）',
        'P2': 'P2（收紧）',
        'P3': 'P3（极度收紧）',
    }

    context = {
        'current_regime': current_regime.dominant_regime,
        'regime_display': regime_display.get(current_regime.dominant_regime, '未知'),
        'current_policy': latest_policy.value if latest_policy else 'P1',
        'policy_display': policy_display.get(latest_policy.value) if latest_policy else 'P1（宽松）',
        'sentiment_index': f"{latest_sentiment.composite_index:.2f}" if latest_sentiment else "0.00",
    }

    return render(request, 'asset_analysis/screen.html', context)


def docs_view(request, doc_slug=''):
    """文档查看视图"""
    from django.http import Http404
    from apps.account.infrastructure.models import DocumentationModel

    if doc_slug:
        # 显示具体文档
        try:
            doc = DocumentationModel._default_manager.get(slug=doc_slug, is_published=True)
        except DocumentationModel.DoesNotExist:
            raise Http404(f"文档 {doc_slug} 不存在")

        context = {
            'doc': doc,
            'slug': doc_slug,
            'all_docs': DocumentationModel._default_manager.filter(is_published=True).order_by('category', 'order'),
        }
        return render(request, 'docs/detail.html', context)
    else:
        # 显示文档列表
        docs = DocumentationModel._default_manager.filter(is_published=True).order_by('category', 'order')

        # 按分类分组
        categories = {
            'user_guide': {'name': '用户指南', 'docs': []},
            'concept': {'name': '概念说明', 'docs': []},
            'api': {'name': 'API 文档', 'docs': []},
            'development': {'name': '开发文档', 'docs': []},
            'other': {'name': '其他', 'docs': []},
        }

        for doc in docs:
            if doc.category in categories:
                categories[doc.category]['docs'].append(doc)

        context = {
            'categories': categories,
        }
        return render(request, 'docs/list.html', context)


def _group_by_asset_code(items, direction_attr="direction"):
    """
    按证券代码归并请求/候选，默认保留每组最新一条作为操作入口。
    """
    grouped = {}
    for item in items:
        code = (getattr(item, "asset_code", "") or "").upper()
        if not code:
            continue
        bucket = grouped.setdefault(code, {"items": [], "directions": set()})
        bucket["items"].append(item)
        direction = (getattr(item, direction_attr, "") or "").upper()
        if direction:
            bucket["directions"].add(direction)

    merged = []
    for code, bucket in grouped.items():
        # query 本身按时间倒序，取第一条作为最新记录
        representative = bucket["items"][0]
        representative.merged_count = len(bucket["items"])
        representative.merged_asset_code = code
        representative.merged_directions = sorted(bucket["directions"])
        if len(bucket["directions"]) == 1:
            representative.merged_direction = next(iter(bucket["directions"]))
        elif bucket["directions"]:
            representative.merged_direction = "MIXED"
        else:
            representative.merged_direction = getattr(representative, direction_attr, "")
        merged.append(representative)
    return merged


@login_required
def decision_workspace_view(request):
    """
    统一决策工作台

    集成 Beta Gate、Alpha Trigger、Decision Rhythm 三个模块的概览和快速操作。
    """
    import logging
    from apps.policy.application.use_cases import GetCurrentPolicyUseCase
    from apps.policy.infrastructure.repositories import get_policy_repository

    logger = logging.getLogger(__name__)

    context = {
        'page_title': '决策工作台',
        'page_description': '统一管理投资决策流程',
    }

    # ========== 获取当前 Regime（与 Regime 页面保持同口径） ==========
    try:
        current_regime = resolve_current_regime(as_of_date=date.today())
        context['current_regime'] = current_regime.dominant_regime
        context['regime_confidence'] = current_regime.confidence
    except Exception as e:
        logger.warning(f"Failed to get current regime: {e}")
        context['current_regime'] = 'Unknown'
        context['regime_confidence'] = 0.0

    # ========== 获取当前 Policy ==========
    try:
        policy_use_case = GetCurrentPolicyUseCase(get_policy_repository())
        policy_response = policy_use_case.execute()
        if policy_response.success and policy_response.policy_level:
            context['current_policy'] = policy_response.policy_level.value
    except Exception as e:
        logger.warning(f"Failed to get current policy: {e}")
        context['current_policy'] = 'P0'

    # ========== Beta Gate 数据 ==========
    try:
        from apps.beta_gate.infrastructure.models import GateConfigModel
        active_config = GateConfigModel._default_manager.active().first()
        if active_config:
            regime_constraints = active_config.regime_constraints if isinstance(active_config.regime_constraints, dict) else {}
            context['beta_gate_allowed_classes'] = regime_constraints.get('allowed_asset_classes', [])
            context['beta_gate_config_id'] = active_config.config_id
        else:
            context['beta_gate_allowed_classes'] = []
    except Exception as e:
        logger.warning(f"Failed to get beta gate config: {e}")
        context['beta_gate_allowed_classes'] = []

    # ========== Alpha Trigger 数据 ==========
    try:
        from apps.alpha_trigger.infrastructure.models import AlphaTriggerModel, AlphaCandidateModel

        # 统计各状态数量
        context['alpha_trigger_count'] = AlphaTriggerModel._default_manager.filter(status='ACTIVE').count()
        context['alpha_watch_count'] = AlphaCandidateModel._default_manager.filter(status='WATCH').count()
        context['alpha_candidate_count'] = AlphaCandidateModel._default_manager.filter(status='CANDIDATE').count()
        context['alpha_actionable_count'] = AlphaCandidateModel._default_manager.filter(status='ACTIONABLE').count()

        # 可操作候选（按优先级排序）
        raw_actionable_candidates = list(AlphaCandidateModel._default_manager.filter(
            status='ACTIONABLE'
        ).order_by('-confidence', '-created_at')[:50])
        actionable_candidates = _group_by_asset_code(raw_actionable_candidates, direction_attr="direction")[:5]
        context['actionable_candidates'] = actionable_candidates
        context['alpha_actionable_count'] = len(actionable_candidates)
    except Exception as e:
        logger.warning(f"Failed to get alpha trigger data: {e}")
        context['alpha_trigger_count'] = 0
        context['alpha_watch_count'] = 0
        context['alpha_candidate_count'] = 0
        context['alpha_actionable_count'] = 0
        context['actionable_candidates'] = []

    # ========== Decision Rhythm 数据 ==========
    try:
        from apps.decision_rhythm.infrastructure.models import DecisionQuotaModel
        from apps.decision_rhythm.domain.entities import QuotaPeriod
        current_quota = (
            DecisionQuotaModel._default_manager
            .filter(period=QuotaPeriod.WEEKLY.value)
            .order_by('-period_start')
            .first()
        )
        if current_quota:
            context['quota_total'] = current_quota.max_decisions
            context['quota_used'] = current_quota.used_decisions
            context['quota_remaining'] = max(0, current_quota.max_decisions - current_quota.used_decisions)
            context['quota_usage_percent'] = round(current_quota.used_decisions / current_quota.max_decisions * 100, 1) if current_quota.max_decisions > 0 else 0
        else:
            context['quota_total'] = 10
            context['quota_used'] = 0
            context['quota_remaining'] = 10
            context['quota_usage_percent'] = 0
    except Exception as e:
        logger.warning(f"Failed to get decision rhythm data: {e}")
        context['quota_total'] = 10
        context['quota_used'] = 0
        context['quota_remaining'] = 10
        context['quota_usage_percent'] = 0

    # ========== 决策待办列表（优先级排序） ==========
    try:
        from apps.decision_rhythm.infrastructure.models import DecisionRequestModel, DecisionResponseModel

        # 待处理定义：已批准但未执行的请求
        # P1-8: 查询条件改为 PENDING + FAILED，以支持重试分支
        raw_pending_requests = list(
            DecisionRequestModel._default_manager
            .filter(
                response__approved=True,
                execution_status__in=['PENDING', 'FAILED']
            )
            .order_by('-requested_at')[:100]
        )
        pending_requests = _group_by_asset_code(raw_pending_requests, direction_attr="direction")[:10]
        context['pending_requests'] = pending_requests
        context['pending_count'] = len(pending_requests)
    except Exception as e:
        logger.warning(f"Failed to get pending requests: {e}")
        context['pending_requests'] = []
        context['pending_count'] = 0

    # ========== 告警信息 ==========
    alerts = []

    # 配额告警
    if context.get('quota_usage_percent', 0) >= 100:
        alerts.append({
            'type': 'danger',
            'icon': '🚨',
            'title': '配额已耗尽',
            'message': '本周决策配额已用完，请联系管理员重置。',
        })
    elif context.get('quota_usage_percent', 0) >= 80:
        alerts.append({
            'type': 'warning',
            'icon': '⚠️',
            'title': '配额即将耗尽',
            'message': f'本周剩余配额仅 {context.get("quota_remaining", 0)} 次。',
        })

    # 候选即将过期告警
    try:
        from django.utils import timezone
        from datetime import timedelta
        expiring_soon = 0
        now = timezone.now()
        threshold = now + timedelta(days=2)
        candidates = AlphaCandidateModel._default_manager.filter(
            status__in=['WATCH', 'CANDIDATE', 'ACTIONABLE']
        ).only('created_at', 'time_horizon')
        for c in candidates:
            if not c.created_at or not c.time_horizon:
                continue
            expires_at = c.created_at + timedelta(days=int(c.time_horizon))
            if now < expires_at <= threshold:
                expiring_soon += 1
        if expiring_soon > 0:
            alerts.append({
                'type': 'info',
                'icon': '⏰',
                'title': f'{expiring_soon} 个候选即将过期',
                'message': '请在过期前处理相关投资机会。',
            })
    except Exception as e:
        logger.warning(f"Failed to check expiring candidates: {e}")

    context['alerts'] = alerts

    # 轻量刷新接口（前端每 30 秒调用）
    if request.GET.get('refresh') == '1':
        return JsonResponse({
            'success': True,
            'quota_usage_percent': context.get('quota_usage_percent', 0),
            'quota_remaining': context.get('quota_remaining', 0),
            'pending_count': context.get('pending_count', 0),
            'alpha_actionable_count': context.get('alpha_actionable_count', 0),
        })

    return render(request, 'decision/workspace.html', context)


@login_required
def ops_center_view(request):
    """Unified non-admin operations center for common configuration tasks."""
    context = {
        "sections": [
            {
                "title": "Policy 管理",
                "items": [
                    {"name": "政策事件列表", "url": "/policy/events/"},
                    {"name": "新增政策事件", "url": "/policy/events/new/"},
                    {"name": "RSS 源管理", "url": "/policy/rss/manage/"},
                    {"name": "新增 RSS 源", "url": "/policy/rss/manage/new/"},
                    {"name": "关键词规则", "url": "/policy/rss/keywords/"},
                    {"name": "新增关键词规则", "url": "/policy/rss/keywords/new/"},
                ],
            },
            {
                "title": "Macro 管理",
                "items": [
                    {"name": "数据源配置", "url": "/macro/datasources/"},
                    {"name": "新增数据源", "url": "/macro/datasources/new/"},
                    {"name": "数据管理器", "url": "/macro/controller/"},
                ],
            },
            {
                "title": "Beta Gate",
                "items": [
                    {"name": "配置总览", "url": "/beta-gate/config/"},
                    {"name": "新建配置", "url": "/beta-gate/config/new/"},
                    {"name": "资产测试", "url": "/beta-gate/test/"},
                    {"name": "版本管理", "url": "/beta-gate/version/"},
                ],
            },
            {
                "title": "系统配置",
                "items": [
                    {"name": "账户系统设置", "url": "/account/admin/settings/"},
                    {"name": "文档管理", "url": "/admin/docs/manage/"},
                    {"name": "服务端日志", "url": "/admin/server-logs/"},
                    {"name": "AI 接口管理", "url": "/ai/manage/"},
                    {"name": "AI 调用日志", "url": "/ai/logs/"},
                    {"name": "Prompt 模板管理", "url": "/prompt/manage/"},
                ],
            },
        ]
    }
    return render(request, "ops/center.html", context)
