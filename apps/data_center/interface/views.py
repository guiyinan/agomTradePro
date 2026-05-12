"""
Data Center — Interface Layer Page Views

Renders the /data-center/ HTML pages.  All data is loaded via the API
(HTMX / fetch) so these views only need to return template shells.
"""

from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.data_center.application.interface_services import (
    load_macro_governance_payload,
    run_macro_governance_action,
)


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


@staff_member_required
def publishers_page(request: HttpRequest) -> HttpResponse:
    """Publisher governance page at /data-center/publishers/."""
    return render(request, "data_center/publishers.html", {
        "page_title": "Data Center — Publishers",
        "active_nav": "data-center",
    })


@staff_member_required
def governance_page(request: HttpRequest) -> HttpResponse:
    """Macro data governance and audit console at /data-center/governance/."""

    action_result = None
    if request.method == "POST":
        action = str(request.POST.get("action") or "").strip()
        if action:
            action_result = run_macro_governance_action(action)

    context = {
        "page_title": "Data Center — Governance",
        "active_nav": "data-center",
        "snapshot": load_macro_governance_payload(),
        "action_result": action_result,
    }
    return render(request, "data_center/governance.html", context)
