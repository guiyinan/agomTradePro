"""Application orchestration for regional egress routing and diagnostics."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from apps.data_center.domain.egress_routing import (
    EgressRequestContext,
    EgressRouteDecision,
    EgressRouteRule,
    EgressRoutingError,
    EgressStrategy,
    resolve_egress_route,
    target_hostname,
)
from core.exceptions import DataFetchError
from core.integration.config_center_egress import (
    EgressEndpointSummary,
)
from core.integration.config_center_egress import create_egress_endpoint as _config_create_endpoint
from core.integration.config_center_egress import delete_egress_endpoint as _config_delete_endpoint
from core.integration.config_center_egress import (
    get_egress_endpoint_summary as _config_get_endpoint_summary,
)
from core.integration.config_center_egress import list_egress_endpoints as _config_list_endpoints
from core.integration.config_center_egress import update_egress_endpoint as _config_update_endpoint

logger = logging.getLogger(__name__)


class EgressRuleRepositoryProtocol(Protocol):
    """Application port implemented by Data Center rule persistence."""

    def list(self, *, include_disabled: bool = True) -> tuple[EgressRouteRule, ...]:
        """List route rules."""
        ...

    def get(self, rule_id: int) -> EgressRouteRule | None:
        """Read one route rule."""
        ...

    def create(self, rule: EgressRouteRule) -> EgressRouteRule:
        """Create one route rule."""
        ...

    def update(self, rule_id: int, rule: EgressRouteRule) -> EgressRouteRule | None:
        """Update one route rule."""
        ...


class EgressAuditWriterProtocol(Protocol):
    """Application port for redacted transport attempt audit evidence."""

    def record(
        self,
        *,
        request_id: UUID,
        provider_id: int | None,
        dataset_key: str,
        target_host: str,
        deployment_region: str,
        rule_id: int | None,
        egress_id: int | None,
        attempt: int,
        outcome: str,
        error_code: str = "",
        latency_ms: float | None = None,
    ) -> None:
        """Persist one redacted attempt."""
        ...


@dataclass(frozen=True, slots=True)
class EgressTransportResult:
    """Normalized result returned by one bounded HTTP transport attempt."""

    outcome: str
    error_code: str = ""
    message: str = ""
    status_code: int | None = None
    latency_ms: float | None = None
    observed_ip: str | None = None
    retryable: bool = False


class EgressTransportProtocol(Protocol):
    """Transport port used by diagnostics and provider adapters."""

    def request(
        self,
        context: EgressRequestContext,
        *,
        egress_id: int | None,
        request_id: UUID,
        attempt: int,
    ) -> EgressTransportResult:
        """Issue one allowlisted, bounded idempotent request."""
        ...

    def probe_endpoint(
        self,
        context: EgressRequestContext,
        *,
        egress_id: int | None,
        request_id: UUID,
        attempt: int,
    ) -> EgressTransportResult:
        """Test a configured endpoint without enabling production traffic."""
        ...

    def request_payload(
        self,
        context: EgressRequestContext,
        *,
        egress_id: int | None,
        request_id: UUID,
        attempt: int,
        method: str,
        params: Mapping[str, object] | None,
        json_body: Mapping[str, object] | None,
        headers: Mapping[str, str] | None,
        expect_json: bool,
    ) -> tuple[EgressTransportResult, object | None]:
        """Return one bounded provider response at the external JSON boundary."""
        ...


@dataclass(frozen=True, slots=True)
class EgressDiagnosticAttempt:
    """Public projection of a single egress attempt."""

    attempt: int
    egress_id: int | None
    outcome: str
    error_code: str
    message: str
    status_code: int | None
    latency_ms: float | None
    observed_ip: str | None

    def to_dict(self) -> dict[str, object]:
        """Return safe attempt evidence."""

        return {
            "attempt": self.attempt,
            "egress_id": self.egress_id,
            "outcome": self.outcome,
            "error_code": self.error_code,
            "message": self.message,
            "status_code": self.status_code,
            "latency_ms": self.latency_ms,
            "observed_ip": self.observed_ip,
        }


@dataclass(frozen=True, slots=True)
class EgressDiagnosticReport:
    """Public outcome for a bounded route diagnostic."""

    outcome: str
    error_code: str
    message: str
    request_id: str
    route: EgressRouteDecision
    attempts: tuple[EgressDiagnosticAttempt, ...]
    checked_at: str

    def to_dict(self) -> dict[str, object]:
        """Return diagnostic evidence without credentials or raw URLs."""

        return {
            "outcome": self.outcome,
            "error_code": self.error_code,
            "message": self.message,
            "request_id": self.request_id,
            "route": self.route.to_dict(),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "checked_at": self.checked_at,
        }


_rule_repository: EgressRuleRepositoryProtocol | None = None
_audit_writer: EgressAuditWriterProtocol | None = None
_transport: EgressTransportProtocol | None = None


def configure_egress_rule_repository(repository: EgressRuleRepositoryProtocol) -> None:
    """Install the Data Center rule repository at application composition time."""

    global _rule_repository
    _rule_repository = repository


def configure_egress_audit_writer(writer: EgressAuditWriterProtocol) -> None:
    """Install the Data Center audit writer at application composition time."""

    global _audit_writer
    _audit_writer = writer


def configure_egress_transport(transport: EgressTransportProtocol) -> None:
    """Install the HTTP transport used by diagnostics and market adapters."""

    global _transport
    _transport = transport


def get_egress_transport() -> EgressTransportProtocol | None:
    """Return the configured transport for infrastructure adapters."""

    return _transport


def _rules() -> EgressRuleRepositoryProtocol:
    """Return the configured rule repository or fail closed."""

    if _rule_repository is None:
        raise RuntimeError("data_center_egress_rule_repository_unconfigured")
    return _rule_repository


def list_endpoints() -> tuple[EgressEndpointSummary, ...]:
    """List Config Center endpoint metadata without resolving credentials."""

    return _config_list_endpoints(include_disabled=True)


def create_endpoint(payload: Mapping[str, object]) -> EgressEndpointSummary:
    """Create one encrypted Config Center endpoint and return its redacted view."""

    return _config_create_endpoint(payload)


def update_endpoint(
    endpoint_id: int, payload: Mapping[str, object]
) -> EgressEndpointSummary | None:
    """Update one endpoint through the Config Center public port."""

    return _config_update_endpoint(endpoint_id, payload)


def delete_endpoint(endpoint_id: int) -> bool:
    """Delete one Config Center endpoint."""

    return _config_delete_endpoint(endpoint_id)


def list_rules() -> tuple[EgressRouteRule, ...]:
    """List all Data Center routing rules."""

    return _rules().list(include_disabled=True)


def create_rule(payload: Mapping[str, object]) -> EgressRouteRule:
    """Validate and persist one route rule."""

    rule = _build_rule(payload, rule_id=None, existing=None)
    _validate_endpoint_reference(rule)
    candidate = _rules().list(include_disabled=True) + (rule,)
    _validate_rule_set(candidate)
    return _rules().create(rule)


def update_rule(rule_id: int, payload: Mapping[str, object]) -> EgressRouteRule | None:
    """Validate and update one rule, clearing stale fixed IDs for direct routes."""

    existing = _rules().get(rule_id)
    if existing is None:
        return None
    rule = _build_rule(payload, rule_id=rule_id, existing=existing)
    _validate_endpoint_reference(rule)
    candidate = tuple(item for item in _rules().list(include_disabled=True) if item.id != rule_id)
    _validate_rule_set(candidate + (rule,))
    return _rules().update(rule_id, rule)


def preview_route(context: EgressRequestContext) -> EgressRouteDecision:
    """Explain route selection without issuing a network request."""

    return resolve_egress_route(_rules().list(include_disabled=True), context)


def execute_provider_request(
    context: EgressRequestContext,
    *,
    method: str = "GET",
    params: Mapping[str, object] | None = None,
    json_body: Mapping[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
    max_attempts: int = 2,
) -> object | None:
    """Execute one provider read with a shared candidate budget and audit trail."""
    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or not 1 <= max_attempts <= 2
    ):
        raise EgressRoutingError("max_attempts must be one or two")
    if method not in {"GET", "POST"}:
        raise EgressRoutingError("unsupported provider read method")
    transport = _transport
    if transport is None:
        raise DataFetchError("出网传输尚未配置。", code="EGRESS_TRANSPORT_UNAVAILABLE")
    route = preview_route(context)
    request_id = uuid4()
    last = EgressTransportResult(
        outcome="blocked", error_code="EGRESS_NO_CANDIDATE", message="没有可用出口。"
    )
    for attempt_number, egress_id in enumerate(route.candidates[:max_attempts], start=1):
        result, payload = transport.request_payload(
            context,
            egress_id=egress_id,
            request_id=request_id,
            attempt=attempt_number,
            method=method,
            params=params,
            json_body=json_body,
            headers=headers,
            expect_json=True,
        )
        _record_attempt(
            context, route, request_id, _diagnostic_attempt(result, attempt_number, egress_id)
        )
        if result.outcome == "success":
            return payload
        last = result
        if not result.retryable:
            break
    raise DataFetchError(
        last.message or "出网请求失败。", code=last.error_code or "EGRESS_TRANSPORT_FAILED"
    )


def _diagnostic_attempt(
    result: EgressTransportResult, number: int, egress_id: int | None
) -> EgressDiagnosticAttempt:
    """Project a sanitized transport result into common audit evidence."""
    return EgressDiagnosticAttempt(
        attempt=number,
        egress_id=egress_id,
        outcome=result.outcome,
        error_code=result.error_code,
        message=result.message,
        status_code=result.status_code,
        latency_ms=result.latency_ms,
        observed_ip=result.observed_ip,
    )


def diagnose_route(context: EgressRequestContext) -> EgressDiagnosticReport:
    """Run bounded attempts only when a persisted rule explicitly allows the target."""

    route = preview_route(context)
    request_id = uuid4()
    checked_at = datetime.now(UTC).isoformat()
    if route.rule_id is None:
        return EgressDiagnosticReport(
            outcome="blocked",
            error_code="EGRESS_DIAGNOSTIC_RULE_REQUIRED",
            message="目标没有匹配的已登记出网规则。",
            request_id=str(request_id),
            route=route,
            attempts=(),
            checked_at=checked_at,
        )
    transport = _transport
    if transport is None:
        return EgressDiagnosticReport(
            outcome="blocked",
            error_code="EGRESS_TRANSPORT_UNAVAILABLE",
            message="出网传输尚未配置。",
            request_id=str(request_id),
            route=route,
            attempts=(),
            checked_at=checked_at,
        )
    return _execute_route(context, route, request_id=request_id, checked_at=checked_at)


def _execute_route(
    context: EgressRequestContext,
    route: EgressRouteDecision,
    *,
    request_id: UUID | None = None,
    checked_at: str | None = None,
) -> EgressDiagnosticReport:
    """Execute an already-authorized route and record bounded attempts."""

    resolved_request_id = request_id or uuid4()
    resolved_checked_at = checked_at or datetime.now(UTC).isoformat()
    transport = _transport
    if transport is None:
        return EgressDiagnosticReport(
            outcome="blocked",
            error_code="EGRESS_TRANSPORT_UNAVAILABLE",
            message="出网传输尚未配置。",
            request_id=str(resolved_request_id),
            route=route,
            attempts=(),
            checked_at=resolved_checked_at,
        )
    attempts: list[EgressDiagnosticAttempt] = []
    request_method = (
        transport.probe_endpoint if route.reason == "endpoint_test" else transport.request
    )
    for attempt_number, egress_id in enumerate(route.candidates, start=1):
        result = request_method(
            context,
            egress_id=egress_id,
            request_id=resolved_request_id,
            attempt=attempt_number,
        )
        attempt = EgressDiagnosticAttempt(
            attempt=attempt_number,
            egress_id=egress_id,
            outcome=result.outcome,
            error_code=result.error_code,
            message=result.message,
            status_code=result.status_code,
            latency_ms=result.latency_ms,
            observed_ip=result.observed_ip,
        )
        attempts.append(attempt)
        _record_attempt(context, route, resolved_request_id, attempt)
        if result.outcome == "success" or not result.retryable:
            return EgressDiagnosticReport(
                outcome=result.outcome,
                error_code=result.error_code,
                message=result.message,
                request_id=str(resolved_request_id),
                route=route,
                attempts=tuple(attempts),
                checked_at=resolved_checked_at,
            )
    final = attempts[-1]
    return EgressDiagnosticReport(
        outcome=final.outcome,
        error_code=final.error_code or "EGRESS_TRANSPORT_FAILED",
        message=final.message or "出网请求失败。",
        request_id=str(resolved_request_id),
        route=route,
        attempts=tuple(attempts),
        checked_at=resolved_checked_at,
    )


def test_endpoint(
    endpoint_id: int, *, context: EgressRequestContext | None = None
) -> EgressDiagnosticReport:
    """Probe a configured endpoint using one target from its persisted allowlist."""

    endpoint = _config_get_endpoint_summary(endpoint_id)
    rules = _rules().list(include_disabled=True)
    selected = next(
        (
            rule
            for rule in rules
            if rule.fixed_egress_id == endpoint_id
            and context is not None
            and resolve_egress_route((replace(rule, enabled=True),), context).rule_id
            == rule.rule_id
        ),
        None,
    )
    if endpoint is None:
        return _blocked_report(
            "EGRESS_ENDPOINT_UNAVAILABLE",
            "出口不存在。",
        )
    if context is None:
        return _blocked_report(
            "EGRESS_TEST_TARGET_REQUIRED", "请填写数据源、数据集、执行区域和具体目标地址。"
        )
    if selected is None:
        return _blocked_report(
            "EGRESS_TEST_NO_ALLOWLISTED_TARGET",
            "该出口没有关联的已登记目标。",
        )
    route = EgressRouteDecision(
        rule_id=selected.rule_id,
        strategy=EgressStrategy.FIXED,
        candidates=(endpoint_id,),
        reason="endpoint_test",
        matched_domain=target_hostname(context.target_url),
    )
    return _execute_route(context, route)


def _blocked_report(
    error_code: str,
    message: str,
    *,
    route: EgressRouteDecision | None = None,
) -> EgressDiagnosticReport:
    """Build a redacted blocked diagnostic report."""

    return EgressDiagnosticReport(
        outcome="blocked",
        error_code=error_code,
        message=message,
        request_id=str(uuid4()),
        route=route
        or EgressRouteDecision(
            rule_id=None,
            strategy=EgressStrategy.DIRECT,
            candidates=(None,),
            reason="blocked",
        ),
        attempts=(),
        checked_at=datetime.now(UTC).isoformat(),
    )


def _record_attempt(
    context: EgressRequestContext,
    route: EgressRouteDecision,
    request_id: UUID,
    attempt: EgressDiagnosticAttempt,
) -> None:
    """Write best-effort audit evidence without changing the data outcome."""

    if _audit_writer is None:
        return
    try:
        _audit_writer.record(
            request_id=request_id,
            provider_id=context.provider_id,
            dataset_key=context.dataset_key,
            target_host=target_hostname(context.target_url),
            deployment_region=context.deployment_region,
            rule_id=route.rule_id,
            egress_id=attempt.egress_id,
            attempt=attempt.attempt,
            outcome=attempt.outcome,
            error_code=attempt.error_code,
            latency_ms=attempt.latency_ms,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning("Failed to write egress audit evidence: %s", type(exc).__name__)


def _build_rule(
    payload: Mapping[str, object],
    *,
    rule_id: int | None,
    existing: EgressRouteRule | None,
) -> EgressRouteRule:
    """Build a typed rule from create or partial-update input."""

    def value(key: str, default: object) -> object:
        return payload[key] if key in payload else default

    provider_id = _int(
        value("provider_id", existing.provider_id if existing else None), "provider_id"
    )
    dataset_key = _text(
        value("dataset_key", existing.dataset_key if existing else ""), "dataset_key"
    )
    domain_pattern = _text(
        value("domain_pattern", existing.domain_pattern if existing else ""), "domain_pattern"
    )
    deployment_region = _text(
        value("deployment_region", existing.deployment_region if existing else ""),
        "deployment_region",
    )
    raw_strategy = value("strategy", existing.strategy.value if existing else None)
    if not isinstance(raw_strategy, str):
        raise EgressRoutingError("strategy is required", code="EGRESS_STRATEGY_REQUIRED")
    try:
        strategy = EgressStrategy(raw_strategy.strip().lower())
    except ValueError as exc:
        raise EgressRoutingError("invalid egress strategy") from exc
    if strategy is EgressStrategy.DIRECT:
        fixed_egress_id = None
    else:
        fixed_egress_id = _optional_int(
            value("fixed_egress_id", existing.fixed_egress_id if existing else None),
            "fixed_egress_id",
        )
    priority = _int(value("priority", existing.priority if existing else 100), "priority")
    enabled = _bool(value("enabled", existing.enabled if existing else False), "enabled")
    return EgressRouteRule(
        rule_id=rule_id,
        provider_id=provider_id,
        dataset_key=dataset_key,
        domain_pattern=domain_pattern,
        deployment_region=deployment_region,
        strategy=strategy,
        fixed_egress_id=fixed_egress_id,
        priority=priority,
        enabled=enabled,
    )


def _validate_endpoint_reference(rule: EgressRouteRule) -> None:
    """Require a configured, enabled endpoint for fixed strategies."""

    if rule.fixed_egress_id is None:
        return
    endpoint = _config_get_endpoint_summary(rule.fixed_egress_id)
    if endpoint is None:
        raise EgressRoutingError(
            "egress endpoint does not exist",
            code="EGRESS_ENDPOINT_NOT_FOUND",
        )
    if rule.enabled and not endpoint.enabled:
        raise EgressRoutingError(
            "egress endpoint is disabled",
            code="EGRESS_ENDPOINT_DISABLED",
        )


def _validate_rule_set(rules: tuple[EgressRouteRule, ...]) -> None:
    """Validate rule overlap through the domain policy."""

    from apps.data_center.domain.egress_routing import validate_rule_set

    validate_rule_set(rules)


def _int(value: object, key: str) -> int:
    """Narrow a positive integer payload field."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EgressRoutingError(
            f"{key} must be a positive integer", code="EGRESS_INVALID_CONFIGURATION"
        )
    return value


def _optional_int(value: object, key: str) -> int | None:
    """Narrow an optional positive integer payload field."""

    if value is None:
        return None
    return _int(value, key)


def _text(value: object, key: str) -> str:
    """Narrow a required text payload field."""

    if not isinstance(value, str) or not value.strip():
        raise EgressRoutingError(f"{key} is required", code="EGRESS_INVALID_CONFIGURATION")
    return value.strip()


def _bool(value: object, key: str) -> bool:
    """Narrow a boolean payload field."""

    if not isinstance(value, bool):
        raise EgressRoutingError(f"{key} must be boolean", code="EGRESS_INVALID_CONFIGURATION")
    return value


__all__ = [
    "EgressDiagnosticAttempt",
    "EgressDiagnosticReport",
    "EgressRuleRepositoryProtocol",
    "EgressTransportProtocol",
    "EgressTransportResult",
    "configure_egress_audit_writer",
    "configure_egress_rule_repository",
    "configure_egress_transport",
    "create_endpoint",
    "create_rule",
    "delete_endpoint",
    "diagnose_route",
    "execute_provider_request",
    "get_egress_transport",
    "list_endpoints",
    "list_rules",
    "preview_route",
    "test_endpoint",
    "update_endpoint",
    "update_rule",
]
