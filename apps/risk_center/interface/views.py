"""Page views for risk center."""

from __future__ import annotations

from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.risk_center.application.use_cases import GetRiskCenterConsoleContextUseCase


@user_passes_test(lambda user: user.is_staff)
def risk_center_console_view(request: HttpRequest) -> HttpResponse:
    context = GetRiskCenterConsoleContextUseCase().execute(actor=request.user)
    context.update(
        {
            "page_title": "集中风控中心",
            "page_subtitle": "统一管理全局底线、风险模板、账户策略、管理员例外和审计记录。",
            "api_base_url": "/api/risk-center/",
        }
    )
    return render(request, "risk_center/console.html", context)
