from core.integration.audit_reports import generate_audit_report_for_backtest


def test_generate_audit_report_for_backtest_uses_audit_service(monkeypatch):
    fake_backtest_repo = object()
    seen = {}

    def _generate(backtest_id, *, backtest_repository):
        seen["backtest_id"] = backtest_id
        seen["backtest_repository"] = backtest_repository
        return {"success": True, "report_id": 99}

    monkeypatch.setattr("apps.audit.application.interface_services.generate_attribution_report_for_backtest", _generate)

    response = generate_audit_report_for_backtest(42, fake_backtest_repo)

    assert response == {"success": True, "report_id": 99}
    assert seen == {"backtest_id": 42, "backtest_repository": fake_backtest_repo}
