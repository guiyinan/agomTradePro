"""Dashboard current-data reads honor Data Center publication evidence."""

from __future__ import annotations

from apps.dashboard.application.integration_gateways import DashboardApplicationGateway


def test_dashboard_macro_value_reads_published_rows(monkeypatch) -> None:
    """A dashboard macro value comes from the publication-only port."""

    monkeypatch.setattr(
        "apps.data_center.application.public.get_published_macro_fact_series",
        lambda _code, *, limit: {
            "rows": [{"value": 51.2}],
            "must_not_use_for_decision": False,
        },
    )

    assert DashboardApplicationGateway().get_latest_macro_indicator_value("PMI") == 51.2


def test_dashboard_macro_value_blocks_stale_publication(monkeypatch) -> None:
    """A stale publication must not be rendered as a current dashboard value."""

    monkeypatch.setattr(
        "apps.data_center.application.public.get_published_macro_fact_series",
        lambda _code, *, limit: {
            "rows": [{"value": 51.2}],
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_stale",
        },
    )

    assert DashboardApplicationGateway().get_latest_macro_indicator_value("PMI") is None
