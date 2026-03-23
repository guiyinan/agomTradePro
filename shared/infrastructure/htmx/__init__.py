"""
AgomTradePro - HTMX Utilities

Provides HTMX-related views, mixins, and decorators for building dynamic interfaces.

Usage:
    from shared.infrastructure.htmx import (
        HtmxTemplateView,
        HtmxListView,
        HtmxFormView,
        is_htmx,
        staff_required,
        htmx_only,
    )
"""

from shared.infrastructure.htmx.decorators import (
    admin_htmx_view,
    ajax_required,
    cache_per_user,
    conditionally,
    error_message,
    htmx_only,
    htmx_redirect,
    htmx_trigger,
    htmx_view,
    login_htmx_view,
    staff_required,
    success_message,
    superuser_required,
)
from shared.infrastructure.htmx.views import (
    HtmxDeleteView,
    HtmxDetailView,
    HtmxFormView,
    HtmxListView,
    HtmxPartialView,
    HtmxResponseMixin,
    HtmxTemplateView,
    StaffRequiredMixin,
    SuperuserRequiredMixin,
    is_htmx,
)

__all__ = [
    # Views and Mixins
    'is_htmx',
    'HtmxTemplateView',
    'HtmxListView',
    'HtmxFormView',
    'HtmxDetailView',
    'HtmxDeleteView',
    'HtmxPartialView',
    'HtmxResponseMixin',
    'StaffRequiredMixin',
    'SuperuserRequiredMixin',
    # Decorators
    'staff_required',
    'superuser_required',
    'ajax_required',
    'htmx_only',
    'conditionally',
    'htmx_view',
    'htmx_trigger',
    'htmx_redirect',
    'success_message',
    'error_message',
    'cache_per_user',
    'admin_htmx_view',
    'login_htmx_view',
]
