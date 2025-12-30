"""
Page Views for Investment Signal Management.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from apps.signal.infrastructure.models import InvestmentSignalModel
from apps.regime.infrastructure.models import RegimeLog
from apps.signal.application.use_cases import (
    ValidateSignalUseCase,
    GetRecommendedAssetsUseCase,
    ValidateSignalRequest,
)
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
    asset_code = request.POST.get('asset_code', '').strip()
    asset_class = request.POST.get('asset_class', '').strip()
    direction = request.POST.get('direction', 'LONG').strip()
    logic_desc = request.POST.get('logic_desc', '').strip()
    invalidation_logic = request.POST.get('invalidation_logic', '').strip()
    invalidation_threshold = request.POST.get('invalidation_threshold')
    target_regime = request.POST.get('target_regime', 'Recovery').strip()

    # 基本验证
    if not all([asset_code, asset_class, logic_desc, invalidation_logic]):
        return JsonResponse({
            'success': False,
            'error': '请填写所有必填字段'
        })

    try:
        if invalidation_threshold:
            invalidation_threshold = float(invalidation_threshold)
    except ValueError:
        return JsonResponse({
            'success': False,
            'error': '证伪阈值必须是数字'
        })

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
        policy_level=0,  # TODO: 从 policy 表获取
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


@require_http_methods(["POST"])
def validate_signal_view(request):
    """验证信号准入"""
    signal_id = request.POST.get('signal_id')

    signal = get_object_or_404(InvestmentSignalModel, id=signal_id)

    # 获取当前 Regime
    current_regime_data = get_current_regime()
    current_regime = current_regime_data['dominant_regime']
    confidence = current_regime_data['confidence']

    # 执行准入检查
    validate_use_case = ValidateSignalUseCase()
    validate_request = ValidateSignalRequest(
        asset_code=signal.asset_code,
        asset_class=signal.asset_class,
        direction=signal.direction,
        logic_desc=signal.logic_desc,
        invalidation_logic=signal.invalidation_logic,
        invalidation_threshold=signal.invalidation_threshold,
        target_regime=signal.target_regime,
        current_regime=current_regime,
        policy_level=0,  # TODO: 从 policy 表获取
        regime_confidence=confidence,
    )

    response = validate_use_case.execute(validate_request)

    # 更新信号状态
    if response.is_approved:
        signal.status = 'approved'
        signal.rejection_reason = ''
    else:
        signal.status = 'rejected'
        signal.rejection_reason = response.rejection_record.reason if response.rejection_record else '准入检查未通过'

    signal.save()

    return JsonResponse({
        'success': True,
        'is_approved': response.is_approved,
        'warnings': response.warnings,
        'rejection_reason': signal.rejection_reason,
    })


@require_http_methods(["POST"])
def approve_signal_view(request):
    """手动批准信号"""
    signal_id = request.POST.get('signal_id')
    signal = get_object_or_404(InvestmentSignalModel, id=signal_id)

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

    signal = get_object_or_404(InvestmentSignalModel, id=signal_id)
    signal.status = 'rejected'
    signal.rejection_reason = reason
    signal.save()

    return JsonResponse({
        'success': True,
        'message': f'信号 {signal.asset_code} 已拒绝'
    })


@require_http_methods(["POST"])
def invalidate_signal_view(request):
    """证伪信号"""
    signal_id = request.POST.get('signal_id')
    reason = request.POST.get('reason', '信号已证伪').strip()

    signal = get_object_or_404(InvestmentSignalModel, id=signal_id)
    signal.status = 'invalidated'
    signal.rejection_reason = reason
    signal.save()

    return JsonResponse({
        'success': True,
        'message': f'信号 {signal.asset_code} 已证伪'
    })


@require_http_methods(["DELETE"])
def delete_signal_view(request, signal_id):
    """删除信号"""
    signal = get_object_or_404(InvestmentSignalModel, id=signal_id)
    asset_code = signal.asset_code
    signal.delete()

    return JsonResponse({
        'success': True,
        'message': f'信号 {asset_code} 已删除'
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
