"""
Django Admin 视图用于 Regime 配置管理
"""

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect

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
    with transaction.atomic():
        config = get_object_or_404(
            RegimeThresholdConfig._default_manager.select_for_update(),
            pk=object_id,
        )
        list(
            RegimeThresholdConfig._default_manager.select_for_update().filter(
                pk=config.pk
            ).values_list("pk", flat=True)
        )
        list(
            RegimeThresholdConfig._default_manager.select_for_update().filter(
                is_active=True
            ).values_list("pk", flat=True)
        )
        RegimeThresholdConfig._default_manager.exclude(pk=object_id).filter(is_active=True).update(
            is_active=False
        )
        config.is_active = True
        config.save(update_fields=["is_active", "updated_at"])

    messages.success(request, f'已成功激活配置：{config.name}')

    def _invalidate_regime_cache() -> None:
        try:
            from shared.infrastructure.cache_service import CacheService

            CacheService.invalidate_regime()
        except ImportError:
            pass

    transaction.on_commit(_invalidate_regime_cache)

    return redirect('admin:regime_regimethresholdconfig_changelist')

