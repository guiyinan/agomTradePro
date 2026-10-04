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
from core.exceptions import ConfigurationError
from core.integration.publication_preflight_runtime import (
    probe_current_task_attempt_runtime,
    probe_production_audit_runtime,
)


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

    probe = probe_production_audit_runtime()
    return AuthorityCaptureProbeEvidence(
        environment=probe.environment,
        mode=probe.mode,
        scope_schema=probe.scope_schema,
        snapshot_id=probe.snapshot_id,
    )


def _probe_task_attempt_identity() -> TaskAttemptIdentityProbeEvidence:
    """Assemble the monitor reader and prove the identity path fails closed."""

    probe = probe_current_task_attempt_runtime()
    return TaskAttemptIdentityProbeEvidence(
        repository=probe.repository,
        resolution=probe.resolution,
    )


__all__ = [
    "build_full_market_publication_preflight_use_case",
]
