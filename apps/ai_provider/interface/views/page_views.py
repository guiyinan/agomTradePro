"""
Page views for AI provider management.
"""

from typing import Any

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from ...application.dtos import ProviderListItemDTO
from ...application.use_cases import (
    GetOverallStatsUseCase,
    GetProviderStatsUseCase,
    GetUserFallbackQuotaUseCase,
    ListProvidersUseCase,
    ListUsageLogsUseCase,
    ListUserFallbackQuotasUseCase,
    UpdateProviderUseCase,
    UpdateUserFallbackQuotaUseCase,
)
from ..forms import AIProviderConfigForm, PersonalAIProviderConfigForm, UserFallbackQuotaForm

USAGE_STATUS_CHOICES = [
    ("success", "成功"),
    ("error", "错误"),
    ("timeout", "超时"),
    ("rate_limited", "限流"),
]
USAGE_STATUS_VALUES = frozenset(value for value, _label in USAGE_STATUS_CHOICES)
DEFAULT_LOG_LIMIT = 100
MAX_LOG_LIMIT = 500


def _is_admin(user: object) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    )


def _get_provider_item(
    provider_id: int,
    *,
    owner_user: object | None = None,
) -> ProviderListItemDTO:
    scope = "user" if owner_user is not None else "system"
    providers = ListProvidersUseCase().execute(
        include_inactive=True,
        scope=scope,
        owner_user=owner_user,
    )
    for provider in providers:
        if provider.id == int(provider_id):
            return provider
    raise Http404(f"Provider with id {provider_id} not found")


@login_required(login_url="/account/login/")
def ai_manage_view(request: HttpRequest) -> HttpResponse:
    """System provider management page for admins."""
    if not _is_admin(request.user):
        return redirect("ai_provider:my-providers")

    providers = ListProvidersUseCase().execute(include_inactive=True, scope="system")
    overall_dto = GetOverallStatsUseCase().execute()
    return render(
        request,
        "ai_provider/manage.html",
        {
            "providers": providers,
            "overall_stats": overall_dto.__dict__,
            "provider_types": [],
        },
    )


@login_required(login_url="/account/login/")
def ai_my_providers_view(request: HttpRequest) -> HttpResponse:
    """Personal provider management page for ordinary users."""
    quota_dto = GetUserFallbackQuotaUseCase().execute(user=request.user)
    providers = ListProvidersUseCase().execute(
        include_inactive=True,
        scope="user",
        owner_user=request.user,
    )
    return render(
        request,
        "ai_provider/my_providers.html",
        {
            "providers": providers,
            "quota": quota_dto,
        },
    )


@login_required(login_url="/account/login/")
def ai_user_quota_manage_view(request: HttpRequest) -> HttpResponse:
    """Admin page for per-user fallback quota management."""
    if not _is_admin(request.user):
        return HttpResponseForbidden("Admin privileges required.")

    if request.method == "POST":
        user_id = request.POST.get("user_id")
        target_user = get_object_or_404(get_user_model(), pk=user_id)
        form = UserFallbackQuotaForm(request.POST)
        if form.is_valid():
            UpdateUserFallbackQuotaUseCase().execute(
                user=target_user,
                daily_limit=(
                    float(form.cleaned_data["daily_limit"])
                    if form.cleaned_data["daily_limit"] is not None
                    else None
                ),
                monthly_limit=(
                    float(form.cleaned_data["monthly_limit"])
                    if form.cleaned_data["monthly_limit"] is not None
                    else None
                ),
                is_active=form.cleaned_data["is_active"],
                admin_note=form.cleaned_data["admin_note"],
            )
            messages.success(request, f"已更新 {target_user.username} 的系统兜底额度")
            return redirect("ai_provider:quota-manage")

    quotas = ListUserFallbackQuotasUseCase().execute()
    return render(
        request,
        "ai_provider/quota_manage.html",
        {
            "quotas": quotas,
            "quota_form": UserFallbackQuotaForm(),
        },
    )


@login_required(login_url="/account/login/")
def ai_usage_logs_view(request: HttpRequest) -> HttpResponse:
    """Usage logs page; admins see all, users see only their own."""
    provider_id = request.GET.get("provider")
    status_filter = request.GET.get("status")
    limit = _parse_log_limit(request.GET.get("limit"))
    provider_id_int = _parse_optional_positive_int(provider_id)
    normalized_status = status_filter if status_filter in USAGE_STATUS_VALUES else None

    logs_dto = ListUsageLogsUseCase().execute(
        provider_id=provider_id_int,
        status=normalized_status,
        limit=limit,
        user=None if _is_admin(request.user) else request.user,
    )
    providers = ListProvidersUseCase().execute(
        include_inactive=True,
        scope="system" if _is_admin(request.user) else "user",
        owner_user=None if _is_admin(request.user) else request.user,
    )
    return render(
        request,
        "ai_provider/usage_logs.html",
        {
            "logs": logs_dto,
            "providers": providers,
            "filter_provider": provider_id_int,
            "filter_status": normalized_status,
            "filter_limit": limit,
            "status_choices": USAGE_STATUS_CHOICES,
            "is_admin_view": _is_admin(request.user),
        },
    )


@login_required(login_url="/account/login/")
def ai_provider_detail_view(request: HttpRequest, provider_id: int) -> HttpResponse:
    """Detail page for one provider within visible scope."""
    provider = _get_provider_item(
        provider_id,
        owner_user=None if _is_admin(request.user) else request.user,
    )

    try:
        stats_dto = GetProviderStatsUseCase().execute(
            pk=provider_id,
            actor_user=None if _is_admin(request.user) else request.user,
        )
    except ValueError as exc:
        raise Http404(str(exc)) from exc

    recent_logs_dto = ListUsageLogsUseCase().execute(
        provider_id=provider_id,
        limit=50,
        user=None if _is_admin(request.user) else request.user,
    )
    return render(
        request,
        "ai_provider/detail.html",
        {
            "provider": provider,
            "today_usage": {
                "total_requests": stats_dto.today_requests,
                "success_requests": stats_dto.today_requests,
                "total_tokens": 0,
                "total_cost": stats_dto.today_cost,
            },
            "month_usage": {
                "total_requests": stats_dto.month_requests,
                "success_requests": stats_dto.month_requests,
                "total_tokens": 0,
                "total_cost": stats_dto.month_cost,
            },
            "recent_logs": recent_logs_dto[:20],
            "usage_by_date": stats_dto.usage_by_date,
            "model_stats": stats_dto.model_stats,
        },
    )


@login_required(login_url="/account/login/")
def ai_provider_edit_view(request: HttpRequest, provider_id: int) -> HttpResponse:
    """Provider edit page honoring scope ownership."""
    provider = _get_provider_item(
        provider_id,
        owner_user=None if _is_admin(request.user) else request.user,
    )

    form_class = (
        AIProviderConfigForm if provider.scope == "system" else PersonalAIProviderConfigForm
    )

    if request.method == "POST":
        form = form_class(request.POST, provider=provider)
        if form.is_valid():
            update_data: dict[str, Any] = {
                "name": form.cleaned_data.get("name"),
                "provider_type": form.cleaned_data.get("provider_type"),
                "is_active": form.cleaned_data.get("is_active", False),
                "priority": form.cleaned_data.get("priority"),
                "base_url": form.cleaned_data.get("base_url"),
                "default_model": form.cleaned_data.get("default_model"),
                "api_mode": form.cleaned_data.get("api_mode"),
                "fallback_enabled": form.cleaned_data.get("fallback_enabled", True),
                "description": form.cleaned_data.get("description", ""),
                "extra_config": form.cleaned_data.get("extra_config_text", {}),
            }
            if provider.scope == "system":
                update_data["daily_budget_limit"] = form.cleaned_data.get("daily_budget_limit")
                update_data["monthly_budget_limit"] = form.cleaned_data.get("monthly_budget_limit")
            if form.cleaned_data.get("api_key"):
                update_data["api_key"] = form.cleaned_data["api_key"]

            try:
                UpdateProviderUseCase().execute(
                    pk=provider_id,
                    actor_user=None if _is_admin(request.user) else request.user,
                    **update_data,
                )
                messages.success(request, "AI 提供商配置已更新")
                return redirect("ai_provider:detail", provider_id=provider_id)
            except ValueError as exc:
                messages.error(request, str(exc))
    else:
        form = form_class(provider=provider)

    return render(
        request,
        "ai_provider/form.html",
        {
            "form": form,
            "provider": provider,
            "page_title": f"编辑 AI 提供商：{provider.name}",
        },
    )


def _parse_optional_positive_int(value: str | None) -> int | None:
    """Parse one optional positive identifier without turning bad filters into 500s."""
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _parse_log_limit(value: str | None) -> int:
    """Normalize the user-facing log page size to a bounded positive value."""
    parsed = _parse_optional_positive_int(value)
    if parsed is None:
        return DEFAULT_LOG_LIMIT
    return min(parsed, MAX_LOG_LIMIT)
