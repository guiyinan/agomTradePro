"""Structural contracts for Dashboard interface view helpers."""

from apps.dashboard.interface import (
    dashboard_alpha_context,
    dashboard_navigation_context,
    dashboard_regime_context,
    views,
)


def test_dashboard_views_keep_compatibility_helper_exports() -> None:
    """Keep legacy monkeypatch paths while moving helper implementations."""
    assert (
        views._build_regime_status_context is dashboard_regime_context._build_regime_status_context
    )
    assert (
        views._get_alpha_stock_scores_payload
        is dashboard_alpha_context._get_alpha_stock_scores_payload
    )
    assert callable(dashboard_navigation_context._empty_decision_plane_data)
    empty_decision_plane = dashboard_navigation_context._empty_decision_plane_data()
    assert empty_decision_plane.quota_available is False
    assert empty_decision_plane.quota_total == 0
    assert empty_decision_plane.quota_remaining == 0

    assert callable(views._build_dashboard_page_context)
    assert callable(views._build_dashboard_data)
    assert callable(views._ensure_dashboard_positions)
