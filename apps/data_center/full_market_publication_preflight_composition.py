"""Composition root for the read-only full-market publication preflight.

Every port assembled here is strictly read-only: provider runtime settings are
loaded from Config Center, model-market routes are resolved without any
provider I/O, the current-market publication bundle is only composed (never
staged or activated), and the Account authority probe validates runtime
configuration without capturing a fence.
"""

from __future__ import annotations

from collections.abc import Mapping

from django.utils import timezone

from apps.audit.application.system_audit_authority_provider import (
    SystemAuditAuthorityBundleSelector,
)
from apps.audit.application.system_audit_authority_schema import (
    SYSTEM_AUDIT_SCOPE_SCHEMA_V3,
)
from apps.data_center.application.current_market_publication_activation import (
    CurrentMarketPublicationBundle,
)
from apps.data_center.application.full_market_publication_preflight import (
    AuthorityCaptureProbeEvidence,
    FullMarketPublicationPreflightPorts,
    RunFullMarketPublicationPreflightUseCase,
    TaskAttemptIdentityProbeEvidence,
)
from apps.data_center.application.interface_services import load_provider_settings_payload
from apps.data_center.application.model_market_data import ModelMarketDataService
from apps.data_center.application.query_services import list_active_stock_codes_for_backfill
from apps.data_center.composition import (
    get_price_bar_repository,
    get_provider_registry,
    get_publication_policy_repository,
    make_system_audited_sync_price_use_case,
)
from apps.data_center.publication_candidate_activation_composition import (
    build_production_current_market_publication_bundle,
)
from apps.task_monitor.application.repository_provider import get_task_record_repository
from core.exceptions import ConfigurationError
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


def build_full_market_publication_preflight_use_case(
    *,
    using: str = "default",
    provider_settings_override: Mapping[str, object] | None = None,
) -> RunFullMarketPublicationPreflightUseCase:
    """Compose the read-only full-market publication preflight use case.

    When ``provider_settings_override`` is given, the provider policy check
    evaluates that explicit snapshot instead of the live Config Center payload
    so rehearsals can bind the exact production policy bytes into evidence.
    """

    if provider_settings_override is None:
        load_settings = _load_provider_settings
    else:
        snapshot = dict(provider_settings_override)

        def load_settings() -> Mapping[str, object]:
            return dict(snapshot)

    return RunFullMarketPublicationPreflightUseCase(
        FullMarketPublicationPreflightPorts(
            load_provider_settings=load_settings,
            build_model_market_service=_build_model_market_service,
            build_publication_bundle=lambda: _build_publication_bundle(using=using),
            publication_policies=get_publication_policy_repository(),
            load_active_universe=_load_active_universe,
            probe_authority_capture=_probe_authority_capture,
            probe_task_attempt_identity=_probe_task_attempt_identity,
            clock=timezone.now,
        )
    )


def _load_provider_settings() -> Mapping[str, object]:
    """Load the typed Config Center provider runtime policy payload."""

    return dict(load_provider_settings_payload())


def _build_model_market_service(settings_payload: Mapping[str, object]) -> ModelMarketDataService:
    """Resolve model-market routes exactly as production, without provider I/O."""

    from apps.data_center.infrastructure.model_market_wiring import build_model_market_service

    registry = get_provider_registry()
    history_fetch_audit = make_system_audited_sync_price_use_case(
        provider_registry=registry,
        publish_current=False,
    )
    service = build_model_market_service(
        registry,
        get_price_bar_repository(),
        dict(settings_payload),
        history_fetch_audit=history_fetch_audit,
    )
    if not isinstance(service, ModelMarketDataService):
        raise ConfigurationError(
            "Model market wiring returned an unexpected service type",
            code="MODEL_MARKET_CONFIG_UNAVAILABLE",
        )
    return service


def _build_publication_bundle(*, using: str) -> CurrentMarketPublicationBundle:
    """Compose the production current-market bundle without staging anything."""

    return build_production_current_market_publication_bundle(
        using=using,
        created_by="ops.preflight_full_market_publication",
    )


def _load_active_universe() -> tuple[str, ...]:
    """Read the governed active A-share universe used by publication rebuilds."""

    return tuple(list_active_stock_codes_for_backfill())


def _probe_authority_capture() -> AuthorityCaptureProbeEvidence:
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
    return AuthorityCaptureProbeEvidence(
        environment=binding.environment,
        mode=binding.mode,
        scope_schema=selector.scope_schema,
        snapshot_id=binding.snapshot_id,
    )


def _probe_task_attempt_identity() -> TaskAttemptIdentityProbeEvidence:
    """Assemble the monitor reader and prove the identity path fails closed."""

    repository = get_task_record_repository()
    if repository is None:
        raise CurrentTaskAttemptIdentityUnavailable("Task Monitor record repository is unavailable")
    try:
        get_current_task_attempt_identity()
    except CurrentTaskAttemptIdentityUnavailable:
        return TaskAttemptIdentityProbeEvidence(
            repository=type(repository).__name__,
            resolution="expected_unavailable_outside_task",
        )
    return TaskAttemptIdentityProbeEvidence(
        repository=type(repository).__name__,
        resolution="bound_to_active_attempt",
    )


__all__ = [
    "build_full_market_publication_preflight_use_case",
]
