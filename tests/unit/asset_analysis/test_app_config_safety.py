"""Safety coverage for Asset Analysis application startup registration."""

import logging

from django.apps import apps


def test_app_ready_does_not_log_registration_exception_details(
    monkeypatch,
    caplog,
) -> None:
    """Startup degradation records only a stable exception type."""

    def fail_registry_resolution():
        raise RuntimeError("registry failed: token=secret")

    monkeypatch.setattr(
        "core.integration.asset_analysis_market_registry.get_asset_analysis_market_registry",
        fail_registry_resolution,
    )
    config = apps.get_app_config("asset_analysis")

    with caplog.at_level(logging.ERROR):
        config.ready()

    assert "RuntimeError" in caplog.text
    assert "token=secret" not in caplog.text
