"""
Django Admin 视图用于 Regime 配置管理
"""

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect, get_object_or_404
from django.contrib import messages
from django.utils.translation import ngettext

from .models import RegimeThresholdConfig


@staff_member_required
def activate_regime_config(request, object_id):
    """
    激活指定的 Regime 阈值配置

    Args:
        request: HttpRequest
        object_id: 配置 ID

    Returns:
        HttpResponseRedirect
    """
    config = get_object_or_404(RegimeThresholdConfig, pk=object_id)

    # 取消其他配置的激活状态
    RegimeThresholdConfig._default_manager.exclude(pk=object_id).update(is_active=False)

    # 激活当前配置
    config.is_active = True
    config.save()

    messages.success(request, f'已成功激活配置：{config.name}')

    # 清除 Regime 缓存以应用新阈值
    try:
        from shared.infrastructure.cache_service import CacheService
        CacheService.invalidate_regime()
    except ImportError:
        pass

    return redirect('admin:regime_regimethresholdconfig_changelist')

