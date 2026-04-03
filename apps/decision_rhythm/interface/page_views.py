"""Decision rhythm HTML page views."""

import logging

from django.shortcuts import render

from ..application.page_workflows import (
    DecisionQuotaConfigPageRequest,
    DecisionQuotaPageRequest,
)
from .dependencies import (
    build_get_decision_quota_config_page_use_case,
    build_get_decision_quota_page_use_case,
)

logger = logging.getLogger(__name__)


def decision_rhythm_quota_view(request):
    """
    决策配额管理页面

    显示当前配额状态、冷却期和决策请求历史。
    支持按账户查看配额。
    """
    try:
        context = (
            build_get_decision_quota_page_use_case()
            .execute(
                DecisionQuotaPageRequest(
                    requested_account_id=request.GET.get("account_id", ""),
                    user_id=request.user.id if request.user.is_authenticated else None,
                    is_authenticated=request.user.is_authenticated,
                )
            )
            .to_context()
        )

        return render(request, "decision_rhythm/quota.html", context)

    except Exception as e:
        logger.error(f"Failed to load decision rhythm quota page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "决策配额管理",
        }
        return render(request, "decision_rhythm/quota.html", context, status=500)


def decision_rhythm_config_view(request):
    """
    决策配额配置页面

    管理员可以配置不同周期的配额参数。
    支持按账户查看和配置配额。
    """
    try:
        context = (
            build_get_decision_quota_config_page_use_case()
            .execute(
                DecisionQuotaConfigPageRequest(
                    requested_account_id=request.GET.get("account_id", ""),
                    user_id=request.user.id if request.user.is_authenticated else None,
                    is_authenticated=request.user.is_authenticated,
                )
            )
            .to_context()
        )

        return render(request, "decision_rhythm/quota_config.html", context)

    except Exception as e:
        logger.error(f"Failed to load decision rhythm config page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "决策配额配置",
        }
        return render(request, "decision_rhythm/quota_config.html", context, status=500)
