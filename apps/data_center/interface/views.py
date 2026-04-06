"""
Data Center — Interface Layer Page Views

Renders the /data-center/ HTML pages.  All data is loaded via the API
(HTMX / fetch) so these views only need to return template shells.
"""

from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.http import HttpRequest, HttpResponse


@staff_member_required
def providers_page(request: HttpRequest) -> HttpResponse:
    """Main provider configuration page at /data-center/providers/."""
    return render(request, "data_center/providers.html", {
        "page_title": "Data Center — Providers",
        "active_nav": "data-center",
    })


@staff_member_required
def monitor_page(request: HttpRequest) -> HttpResponse:
    """Provider health monitor at /data-center/monitor/."""
    return render(request, "data_center/monitor.html", {
        "page_title": "Data Center — Monitor",
        "active_nav": "data-center",
    })
