"""Equity page views.

Owns the login-required HTML page entries. The compatibility facade in
`views.py` remains the stable import surface for URL configuration; do not
import it here.
"""

import re

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.equity.application.market_sessions import (
    get_equity_detail_market_session_profile,
)

# ============================================================================

_STOCK_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


def _normalized_stock_code(stock_code: str) -> str:
    """Return a bounded stock code suitable for page bootstrap reads."""

    normalized = stock_code.strip().upper()
    if _STOCK_CODE_PATTERN.fullmatch(normalized) is None:
        raise Http404("Stock not found")
    return normalized


# 页面视图（前端）
# ============================================================================


@login_required(login_url="/account/login/")
@require_http_methods(["GET"])
def screen_page(request: HttpRequest) -> HttpResponse:
    """
    个股筛选页面

    GET /equity/screen/
    """
    return render(request, "equity/screen.html")


@login_required(login_url="/account/login/")
@require_http_methods(["GET"])
def detail_page(request: HttpRequest, stock_code: str) -> HttpResponse:
    """
    个股详情页面

    GET /equity/detail/<stock_code>/
    """
    normalized_code = _normalized_stock_code(stock_code)
    context = {
        "stock_code": normalized_code,
        "market_session_profile": get_equity_detail_market_session_profile(normalized_code),
    }
    return render(request, "equity/detail.html", context)


@login_required(login_url="/account/login/")
@require_http_methods(["GET"])
def pool_page(request: HttpRequest) -> HttpResponse:
    """
    股票池管理页面

    GET /equity/pool/
    """
    return render(request, "equity/pool.html")


@login_required(login_url="/account/login/")
@require_http_methods(["GET"])
def valuation_repair_page(request: HttpRequest) -> HttpResponse:
    """
    估值修复跟踪页面

    GET /equity/valuation-repair/
    """
    from apps.equity.application.config import get_valuation_repair_config_summary

    return render(
        request,
        "equity/valuation_repair.html",
        {
            "valuation_repair_config_summary": get_valuation_repair_config_summary(use_cache=False),
            "can_manage_valuation_repair_config": bool(
                getattr(request.user, "is_authenticated", False)
                and (
                    getattr(request.user, "is_staff", False)
                    or getattr(request.user, "is_superuser", False)
                )
            ),
        },
    )


@login_required(login_url="/account/login/")
@require_http_methods(["GET"])
def valuation_repair_config_page(request: HttpRequest) -> HttpResponse:
    """
    估值修复配置管理页面

    GET /equity/valuation-repair/config/
    """
    return render(request, "equity/config.html")


__all__ = [
    "detail_page",
    "pool_page",
    "screen_page",
    "valuation_repair_config_page",
    "valuation_repair_page",
]
