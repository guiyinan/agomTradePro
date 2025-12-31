"""
Page Views for Investment Signal Management.
"""

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from apps.signal.infrastructure.models import InvestmentSignalModel
from apps.regime.infrastructure.models import RegimeLog
from apps.signal.application.use_cases import (
    ValidateSignalUseCase,
    GetRecommendedAssetsUseCase,
    ValidateSignalRequest,
)
from apps.signal.application.invalidation_checker import SignalInvalidationService
from apps.signal.domain.rules import ELIGIBILITY_MATRIX, Eligibility
from django.db.models import Count, Q
from datetime import date


def signal_manage_view(request):
    """投资信号管理页面"""
    # 获取筛选参数
    status_filter = request.GET.get('status', '')
    asset_class = request.GET.get('asset_class', '')
    direction = request.GET.get('direction', '')
    search = request.GET.get('search', '')

    # 基础查询
    queryset = InvestmentSignalModel.objects.all()

    # 应用筛选
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    if asset_class:
        queryset = queryset.filter(asset_class=asset_class)
    if direction:
        queryset = queryset.filter(direction=direction)
    if search:
        queryset = queryset.filter(
            Q(asset_code__icontains=search) | Q(logic_desc__icontains=search)
        )

    # 获取信号列表
    signals = queryset.order_by('-created_at')[:50]

    # 统计信息
    stats = {
        'total': InvestmentSignalModel.objects.count(),
        'pending': InvestmentSignalModel.objects.filter(status='pending').count(),
        'approved': InvestmentSignalModel.objects.filter(status='approved').count(),
        'rejected': InvestmentSignalModel.objects.filter(status='rejected').count(),
        'invalidated': InvestmentSignalModel.objects.filter(status='invalidated').count(),
    }

    # 获取所有资产类别和方向
    asset_classes = InvestmentSignalModel.objects.values('asset_class').distinct()
    directions = InvestmentSignalModel.objects.values('direction').distinct()

    # 获取当前 Regime 信息
    current_regime = get_current_regime()

    # 获取推荐资产
    recommended_assets = get_recommended_assets(current_regime['dominant_regime'] if current_regime else 'Deflation')

    # 从数据库动态获取可用指标列表
    from apps.macro.application.indicator_service import get_available_indicators_for_frontend
    available_indicators = get_available_indicators_for_frontend()

    context = {
        'signals': signals,
        'stats': stats,
        'asset_classes': [ac['asset_class'] for ac in asset_classes],
        'directions': [d['direction'] for d in directions],
        'filter_status': status_filter,
        'filter_asset_class': asset_class,
        'filter_direction': direction,
        'filter_search': search,
        'current_regime': current_regime,
        'recommended_assets': recommended_assets,
        'all_asset_classes': list(ELIGIBILITY_MATRIX.keys()),
        'all_regimes': ['Recovery', 'Overheat', 'Stagflation', 'Deflation'],
        'available_indicators': available_indicators,
    }

    return render(request, 'signal/manage.html', context)


def get_current_regime():
    """获取当前 Regime 信息"""
    latest = RegimeLog.objects.order_by('-observed_at').first()
    if not latest:
        return {
            'dominant_regime': 'Unknown',
            'confidence': 0.0,
            'observed_at': None,
            'distribution': {},
        }
    return {
        'dominant_regime': latest.dominant_regime,
        'confidence': latest.confidence,
        'observed_at': latest.observed_at,
        'distribution': latest.distribution,
    }


def get_recommended_assets(regime: str):
    """获取推荐资产列表"""
    from apps.signal.application.use_cases import GetRecommendedAssetsRequest

    use_case = GetRecommendedAssetsUseCase()
    request = GetRecommendedAssetsRequest(current_regime=regime)

    response = use_case.execute(request)

    return {
        'recommended': response.recommended,
        'neutral': response.neutral,
        'hostile': response.hostile,
    }


@require_http_methods(["POST"])
def create_signal_view(request):
    """创建新投资信号"""
    import json

    asset_code = request.POST.get('asset_code', '').strip()
    asset_class = request.POST.get('asset_class', '').strip()
    direction = request.POST.get('direction', 'LONG').strip()
    logic_desc = request.POST.get('logic_desc', '').strip()
    invalidation_rules_json = request.POST.get('invalidation_rules', '{}')
    target_regime = request.POST.get('target_regime', 'Recovery').strip()

    # 基本验证
    if not all([asset_code, asset_class, logic_desc]):
        return JsonResponse({
            'success': False,
            'error': '请填写所有必填字段'
        })

    # 解析证伪规则
    try:
        invalidation_rules = json.loads(invalidation_rules_json)
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': '证伪规则格式错误'
        })

    # 生成人类可读的描述
    invalidation_logic = generate_invalidation_logic_text(invalidation_rules)

    # 提取阈值（取第一个条件的阈值）
    invalidation_threshold = None
    if invalidation_rules.get('conditions'):
        invalidation_threshold = invalidation_rules['conditions'][0].get('threshold')

    # 获取当前 Regime
    current_regime_data = get_current_regime()
    current_regime = current_regime_data['dominant_regime']
    confidence = current_regime_data['confidence']

    # 执行准入检查
    validate_use_case = ValidateSignalUseCase()
    validate_request = ValidateSignalRequest(
        asset_code=asset_code,
        asset_class=asset_class,
        direction=direction,
        logic_desc=logic_desc,
        invalidation_logic=invalidation_logic,
        invalidation_threshold=invalidation_threshold,
        target_regime=target_regime,
        current_regime=current_regime,
        policy_level=0,
        regime_confidence=confidence,
    )

    response = validate_use_case.execute(validate_request)

    # 创建信号
    signal = InvestmentSignalModel.objects.create(
        asset_code=asset_code,
        asset_class=asset_class,
        direction=direction,
        logic_desc=logic_desc,
        invalidation_logic=invalidation_logic,
        invalidation_threshold=invalidation_threshold,
        invalidation_rules=invalidation_rules if invalidation_rules else None,
        target_regime=target_regime,
        status='approved' if response.is_approved else 'rejected',
        rejection_reason=response.rejection_record.reason if response.rejection_record else '',
    )

    return JsonResponse({
        'success': True,
        'signal_id': signal.id,
        'is_approved': response.is_approved,
        'warnings': response.warnings,
        'rejection_reason': signal.rejection_reason if not response.is_approved else None,
    })


def generate_invalidation_logic_text(rules: dict) -> str:
    """从结构化规则生成人类可读的文本"""
    if not rules or not rules.get('conditions'):
        return "未设置证伪条件"

    conditions = []
    for cond in rules.get('conditions', []):
        indicator = cond.get('indicator', '')
        op = cond.get('condition', '')
        threshold = cond.get('threshold', '')

        op_map = {'lt': '<', 'lte': '≤', 'gt': '>', 'gte': '≥', 'eq': '='}
        cond_str = f"{indicator} {op_map.get(op, op)} {threshold}"

        if cond.get('duration'):
            cond_str += f" 连续{cond['duration']}期"
        if cond.get('compare_with'):
            compare_map = {'prev_value': '前值', 'prev_year': '同期'}
            cond_str += f" (较{compare_map.get(cond['compare_with'], cond['compare_with'])})"

        conditions.append(cond_str)

    logic = rules.get('logic', 'AND')
    logic_text = ' 且 ' if logic == 'AND' else ' 或 '
    return f"当{' 且 '.join(conditions)}时证伪"


@require_http_methods(["POST"])
def approve_signal_view(request):
    """手动批准信号"""
    signal_id = request.POST.get('signal_id')
    signal = InvestmentSignalModel.objects.get(id=signal_id)

    signal.status = 'approved'
    signal.rejection_reason = ''
    signal.save()

    return JsonResponse({
        'success': True,
        'message': f'信号 {signal.asset_code} 已批准'
    })


@require_http_methods(["POST"])
def reject_signal_view(request):
    """手动拒绝信号"""
    signal_id = request.POST.get('signal_id')
    reason = request.POST.get('reason', '手动拒绝').strip()

    signal = InvestmentSignalModel.objects.get(id=signal_id)
    signal.status = 'rejected'
    signal.rejection_reason = reason
    signal.save()

    return JsonResponse({
        'success': True,
        'message': f'信号 {signal.asset_code} 已拒绝'
    })


@require_http_methods(["POST"])
def invalidate_signal_view(request):
    """手动证伪信号"""
    signal_id = request.POST.get('signal_id')
    reason = request.POST.get('reason', '手动证伪').strip()

    signal = InvestmentSignalModel.objects.get(id=signal_id)
    signal.status = 'invalidated'
    signal.rejection_reason = reason
    signal.invalidated_at = timezone.now()
    signal.save()

    return JsonResponse({
        'success': True,
        'message': f'信号 {signal.asset_code} 已证伪'
    })


@require_http_methods(["DELETE"])
def delete_signal_view(request, signal_id):
    """删除信号"""
    signal = InvestmentSignalModel.objects.get(id=signal_id)
    asset_code = signal.asset_code
    signal.delete()

    return JsonResponse({
        'success': True,
        'message': f'信号 {asset_code} 已删除'
    })


@require_http_methods(["POST"])
def check_invalidation_view(request, signal_id):
    """手动触发证伪检查"""
    service = SignalInvalidationService()
    result = service.check_signal_by_id(signal_id)

    if result:
        return JsonResponse({
            'success': True,
            'is_invalidated': result.is_invalidated,
            'reason': result.reason,
            'details': result.details,
        })
    else:
        return JsonResponse({
            'success': False,
            'error': '信号不存在'
        })


@require_http_methods(["POST"])
def run_batch_check_view(request):
    """批量检查所有信号"""
    from apps.signal.application.invalidation_checker import check_and_invalidate_signals

    result = check_and_invalidate_signals()

    return JsonResponse({
        'success': True,
        **result
    })


def signal_eligibility_info_view(request):
    """获取资产准入信息（AJAX）"""
    asset_class = request.GET.get('asset_class', '')
    regime = request.GET.get('regime', '')

    if not asset_class or not regime:
        return JsonResponse({'error': '缺少参数'}, status=400)

    try:
        eligibility = ELIGIBILITY_MATRIX.get(asset_class, {}).get(regime, Eligibility.NEUTRAL)

        return JsonResponse({
            'asset_class': asset_class,
            'regime': regime,
            'eligibility': eligibility.value,
            'eligible': eligibility in [Eligibility.PREFERRED, Eligibility.NEUTRAL],
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def ai_parse_logic_view(request):
    """AI 解析证伪逻辑"""
    import json
    from apps.signal.application.ai_invalidation_helper import ai_parse_invalidation_logic

    try:
        data = json.loads(request.body)
        user_input = data.get('text', '').strip()

        if not user_input:
            return JsonResponse({
                'success': False,
                'error': '请输入证伪逻辑描述'
            })

        result = ai_parse_invalidation_logic(user_input)

        if 'error' in result:
            return JsonResponse({
                'success': False,
                'error': result['error'],
                'suggestions': result.get('suggestions', [])
            })

        return JsonResponse({
            'success': True,
            'conditions': result['conditions'],
            'logic': result['logic'],
            'explanation': result['explanation'],
            'confidence': result.get('confidence', 0.8)
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


def get_indicators_view(request):
    """获取可用指标列表"""
    from apps.macro.application.indicator_service import get_available_indicators_for_frontend

    try:
        indicators = get_available_indicators_for_frontend()

        # 按类别分组
        grouped = {}
        for ind in indicators:
            category = ind.get('category', '其他')
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(ind)

        return JsonResponse({
            'success': True,
            'indicators': indicators,
            'grouped': grouped,
            'total': len(indicators)
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })
