"""Audit report integration bridge."""

from apps.backtest.infrastructure.repositories import DjangoBacktestRepository


def generate_audit_report_for_backtest(
    backtest_id: int,
    backtest_repository: DjangoBacktestRepository,
):
    """Trigger the audit module's attribution report workflow."""
    from apps.audit.application.use_cases import (
        GenerateAttributionReportRequest,
        GenerateAttributionReportUseCase,
    )
    from apps.audit.infrastructure.repositories import DjangoAuditRepository

    audit_use_case = GenerateAttributionReportUseCase(
        audit_repository=DjangoAuditRepository(),
        backtest_repository=backtest_repository,
    )
    return audit_use_case.execute(
        GenerateAttributionReportRequest(backtest_id=backtest_id)
    )
