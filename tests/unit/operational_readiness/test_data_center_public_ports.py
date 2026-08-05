"""Operational readiness current reads use Data Center Public Ports."""

from types import SimpleNamespace

from apps.operational_readiness.application import monitor_service, status_services


def test_decision_data_readiness_uses_public_port(monkeypatch) -> None:
    calls: list[tuple[list[str], float]] = []

    def fake_readiness(*, asset_codes: list[str], quote_max_age_hours: float) -> dict[str, object]:
        calls.append((asset_codes, quote_max_age_hours))
        return {
            "status": "ready",
            "readiness_status": "ready",
            "must_not_use_for_decision": False,
            "blocked_reasons": [],
            "market_thermometer": {"status": "ready"},
        }

    monkeypatch.setattr(status_services, "get_decision_data_readiness_payload", fake_readiness)

    result = status_services.build_current_decision_data(
        asset_codes=["000001.SZ"],
        quote_max_age_hours=2.5,
    )

    assert result is not None
    assert result["status"] == "ready"
    assert calls == [(["000001.SZ"], 2.5)]


def test_coverage_readiness_uses_public_port(monkeypatch) -> None:
    requested_modules: list[str] = []

    def fake_import(module_name: str) -> SimpleNamespace:
        requested_modules.append(module_name)
        return SimpleNamespace(
            get_active_stock_fact_coverage_payload=lambda: {"status": "ok", "asset_count": 1}
        )

    monkeypatch.setattr(monitor_service, "import_module", fake_import)

    assert monitor_service.get_active_stock_fact_coverage_payload() == {
        "status": "ok",
        "asset_count": 1,
    }
    assert requested_modules == ["apps.data_center.application.public"]
