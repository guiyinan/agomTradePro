from types import SimpleNamespace

from core.integration.audit_reports import generate_audit_report_for_backtest


class _FakeAuditUseCase:
    def __init__(self, *, audit_repository, backtest_repository):
        self.audit_repository = audit_repository
        self.backtest_repository = backtest_repository

    def execute(self, request):
        return SimpleNamespace(success=True, report_id=99, error=None, request=request)


def test_generate_audit_report_for_backtest_uses_audit_use_case(monkeypatch):
    fake_backtest_repo = object()
    monkeypatch.setattr(
        "apps.audit.application.use_cases.GenerateAttributionReportUseCase",
        _FakeAuditUseCase,
    )
    monkeypatch.setattr(
        "apps.audit.infrastructure.repositories.DjangoAuditRepository",
        lambda: "audit-repo",
    )

    response = generate_audit_report_for_backtest(42, fake_backtest_repo)

    assert response.success is True
    assert response.report_id == 99
    assert response.request.backtest_id == 42
