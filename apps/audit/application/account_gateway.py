"""Register Audit logging for Account consumers."""

from __future__ import annotations

from typing import Any

from apps.account.application.business_provider_gateway import (
    register_audit_operation_logger,
)

from . import interface_services


def _log_operation(**payload: Any) -> Any:
    return interface_services.log_operation_payload(**payload)


def register_audit_account_gateway() -> None:
    """Register the Audit operation logger for Account."""

    register_audit_operation_logger(_log_operation)


__all__ = ["register_audit_account_gateway"]
