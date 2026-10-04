"""Cross-app runtime probes used by publication preflight composition."""

from __future__ import annotations

from dataclasses import dataclass

from apps.audit.application.system_audit_authority_provider import (
    SystemAuditAuthorityBundleSelector,
)
from apps.audit.application.system_audit_authority_schema import (
    SYSTEM_AUDIT_SCOPE_SCHEMA_V3,
)
from apps.task_monitor.application.repository_provider import get_task_record_repository
from core.integration.data_center_audit import SystemAuditCompositionUnavailable
from core.integration.system_audit_runtime_config import (
    SystemAuditRuntimeConfigBinding,
    SystemAuditRuntimeConfigurationUnavailable,
    load_system_audit_runtime_config,
)
from core.integration.task_monitor_runtime import (
    CurrentTaskAttemptIdentityUnavailable,
    get_current_task_attempt_identity,
)

_PRODUCTION_ENVIRONMENT = "production"


@dataclass(frozen=True, slots=True)
class AuditRuntimeProbe:
    """Validated production audit binding projected without Audit types."""

    environment: str
    mode: str
    scope_schema: str
    snapshot_id: str


@dataclass(frozen=True, slots=True)
class TaskAttemptRuntimeProbe:
    """Task Monitor runtime wiring result safe for another app to consume."""

    repository: str
    resolution: str


def probe_production_audit_runtime() -> AuditRuntimeProbe:
    """Validate the production authority binding without capturing a fence."""

    try:
        binding = load_system_audit_runtime_config(environment=_PRODUCTION_ENVIRONMENT)
    except SystemAuditRuntimeConfigurationUnavailable as exc:
        raise SystemAuditCompositionUnavailable(
            "production Account authority capture is unavailable",
            reason_code=exc.reason_code,
        ) from exc
    if type(binding) is not SystemAuditRuntimeConfigBinding:
        raise SystemAuditCompositionUnavailable(
            "production Account authority capture is unavailable",
            reason_code="runtime_binding_invalid",
        )
    if binding.environment != _PRODUCTION_ENVIRONMENT or binding.mode == "off":
        raise SystemAuditCompositionUnavailable(
            "production Account authority capture is unavailable",
            reason_code="runtime_binding_unavailable",
        )
    selector = binding.authority_selector
    if type(selector) is not SystemAuditAuthorityBundleSelector:
        raise SystemAuditCompositionUnavailable(
            "production Account authority capture is unavailable",
            reason_code="authority_selector_missing",
        )
    if selector.scope_schema != SYSTEM_AUDIT_SCOPE_SCHEMA_V3:
        raise SystemAuditCompositionUnavailable(
            "production Account authority capture is unavailable",
            reason_code="authority_scope_schema_unsupported",
        )
    return AuditRuntimeProbe(
        environment=binding.environment,
        mode=binding.mode,
        scope_schema=selector.scope_schema,
        snapshot_id=binding.snapshot_id,
    )


def probe_current_task_attempt_runtime() -> TaskAttemptRuntimeProbe:
    """Assemble Task Monitor wiring and prove CLI identity fails closed."""

    repository = get_task_record_repository()
    if repository is None:
        raise CurrentTaskAttemptIdentityUnavailable("Task Monitor record repository is unavailable")
    try:
        get_current_task_attempt_identity()
    except CurrentTaskAttemptIdentityUnavailable:
        return TaskAttemptRuntimeProbe(
            repository=type(repository).__name__,
            resolution="expected_unavailable_outside_task",
        )
    return TaskAttemptRuntimeProbe(
        repository=type(repository).__name__,
        resolution="bound_to_active_attempt",
    )


__all__ = [
    "AuditRuntimeProbe",
    "TaskAttemptRuntimeProbe",
    "probe_current_task_attempt_runtime",
    "probe_production_audit_runtime",
]
