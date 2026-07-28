"""Macro API URL configuration.

Legacy data CRUD endpoints remain retired after the data-center cutover. The
TUI overview below is a read-only projection of the current application
facades and does not restore those retired contracts.
"""

from django.urls import URLPattern, URLResolver, path

from .tui_views import MacroTrendFilterTuiView, MacroTuiOverviewView

app_name = "macro_api"

urlpatterns: list[URLPattern | URLResolver] = [
    path("tui/overview/", MacroTuiOverviewView.as_view(), name="tui-overview"),
    path(
        "tui/trend-filter/",
        MacroTrendFilterTuiView.as_view(),
        name="tui-trend-filter",
    ),
]
