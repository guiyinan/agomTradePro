"""Audit report integration bridge."""

from typing import Any


def generate_audit_report_for_backtest(
    backtest_id: int,
    backtest_repository: Any,
):
    """Trigger the audit module's attribution report workflow."""
    from apps.audit.application.interface_services import (
        generate_attribution_report_for_backtest as _generate_attribution_report,
    )

    return _generate_attribution_report(
        backtest_id,
        backtest_repository=backtest_repository,
    )
