"""Register Audit report generation for Backtest consumers."""

from __future__ import annotations

from typing import Any

from apps.backtest.application.audit_gateway import register_audit_report_generator

from . import interface_services


def _generate_report(**kwargs: Any) -> Any:
    return interface_services.generate_attribution_report_for_backtest(**kwargs)


def register_audit_backtest_gateway() -> None:
    """Register the Audit report generator for Backtest."""

    register_audit_report_generator(_generate_report)


__all__ = ["register_audit_backtest_gateway"]
