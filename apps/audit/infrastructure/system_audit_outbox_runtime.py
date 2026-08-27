"""Production composition root and fail-closed entry for audit dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from apps.audit.application.data_conflict_audit import (
    AppendDataConflictAuditObservationUseCase,
    DataConflictAuditEventOutboxWriter,
)
from apps.audit.application.data_decision_read_audit import (
    AppendDataDecisionReadAuditObservationUseCase,
    DataDecisionReadAuditEventOutboxWriter,
)
from apps.audit.application.data_failover_audit import (
    AppendDataFailoverAuditObservationUseCase,
    DataFailoverAuditEventOutboxWriter,
)
from apps.audit.application.data_fetch_audit import (
    AppendDataFetchAuditObservationUseCase,
    DataFetchAuditEventOutboxWriter,
)
from apps.audit.application.data_freshness_audit import (
    AppendDataFreshnessAuditObservationUseCase,
    DataFreshnessAuditEventOutboxWriter,
)
from apps.audit.application.data_provider_health_audit import (
    AppendDataProviderHealthAuditObservationUseCase,
    DataProviderHealthAuditEventOutboxWriter,
)
from apps.audit.application.data_publication_audit import (
    AppendDataPublicationAuditObservationUseCase,
    DataPublicationAuditEventOutboxWriter,
)
from apps.audit.application.data_publication_rollback_audit import (
    AppendDataPublicationRollbackAuditObservationUseCase,
    DataPublicationRollbackAuditEventOutboxWriter,
)
from apps.audit.application.data_quality_audit import (
    AppendDataQualityAuditObservationUseCase,
    DataQualityAuditEventOutboxWriter,
)
from apps.audit.application.data_repair_audit import (
    AppendDataRepairAuditObservationUseCase,
    DataRepairAuditEventOutboxWriter,
)
from apps.audit.application.data_validation_audit import (
    AppendDataValidationRejectedObservationUseCase,
    DataValidationAuditEventOutboxWriter,
)
from apps.audit.application.system_audit_authority_provider import (
    ExactScopedSystemAuditAuthorityProvider,
)
from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
from apps.audit.application.system_audit_outbox_dispatcher import DispatchSystemAuditOutboxUseCase
from apps.audit.application.system_audit_query import SystemAuditReaderContext
from apps.audit.application.system_audit_runtime_composition import (
    ServerIssuedSystemAuditAuthorityBundle,
    SystemAuditRuntimeComposition,
    inspect_system_audit_runtime_composition,
    preflight_system_audit_runtime_authority,
)
from apps.audit.domain.system_audit_event import AuditScopeRef
from core.integration.system_audit_authority import (
    SystemAuditAuthorityReaders,
    build_system_audit_authority_readers,
)
from core.integration.system_audit_runtime_config import (
    SystemAuditRuntimeConfigBinding,
    SystemAuditRuntimeConfigurationUnavailable,
    load_system_audit_runtime_config,
)

from .system_audit_delivery_receipt import DjangoSystemAuditDeliveryReceiptPublisher
from .system_audit_event_outbox_coordinator import DjangoSystemAuditEventOutboxCoordinator
from .system_audit_outbox_repository import DjangoSystemAuditOutboxRepository
from .system_audit_outbox_unit_of_work import DjangoSystemAuditOutboxUnitOfWork


@dataclass(frozen=True, slots=True)
class _RuntimeAuthorityPreflight:
    """Bind dispatch-time authority reads to the inspected server bundle."""

    bundle: ServerIssuedSystemAuditAuthorityBundle

    def __call__(self, *, as_of: datetime) -> SystemAuditReaderContext:
        """Validate the exact current authority at the dispatch cutoff."""

        return preflight_system_audit_runtime_authority(self.bundle, as_of=as_of)


@dataclass(frozen=True, slots=True)
class _RuntimeAuthorityScopeProvider:
    """Resolve the current event scope from the inspected authority bundle."""

    bundle: ServerIssuedSystemAuditAuthorityBundle

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Return the exact current scope at the event persistence cutoff."""

        return preflight_system_audit_runtime_authority(self.bundle, as_of=as_of).scope


def _validated_alias(value: object) -> str:
    """Return one bounded database alias before configuration I/O."""

    if (
        type(value) is not str
        or not value
        or len(value) > 64
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise SystemAuditCompositionUnavailable(
            "system audit database alias is invalid",
            reason_code="composition_not_wired",
        )
    return value


def _bounded_reason(value: object) -> str:
    """Keep externally returned composition reasons canonical and bounded."""

    if (
        type(value) is str
        and bool(value)
        and len(value) <= 64
        and all(character in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in value)
    ):
        return value
    return "runtime_composition_failed"


def _load_binding(environment: str) -> SystemAuditRuntimeConfigBinding:
    """Load and revalidate exactly one immutable runtime snapshot binding."""

    try:
        binding = load_system_audit_runtime_config(environment=environment)
    except SystemAuditRuntimeConfigurationUnavailable as error:
        raise SystemAuditCompositionUnavailable(
            "system audit runtime configuration is unavailable",
            reason_code=error.reason_code,
        ) from None
    except Exception:
        raise SystemAuditCompositionUnavailable(
            "system audit runtime configuration is unavailable",
            reason_code="runtime_configuration_unavailable",
        ) from None
    if type(binding) is not SystemAuditRuntimeConfigBinding:
        raise SystemAuditCompositionUnavailable(
            "system audit runtime configuration is unavailable",
            reason_code="runtime_configuration_invalid",
        )
    try:
        binding.__post_init__()
    except (TypeError, ValueError):
        raise SystemAuditCompositionUnavailable(
            "system audit runtime configuration is unavailable",
            reason_code="runtime_configuration_invalid",
        ) from None
    if binding.environment != environment:
        raise SystemAuditCompositionUnavailable(
            "system audit runtime configuration is unavailable",
            reason_code="runtime_configuration_invalid",
        )
    return binding


def _build_system_audit_runtime_composition(
    *, environment: str = "production", using: str = "default"
) -> SystemAuditRuntimeComposition:
    """Build and inspect the sole durable, scoped, same-alias runtime."""

    alias = _validated_alias(using)
    binding = _load_binding(environment)
    if binding.mode == "off":
        raise SystemAuditCompositionUnavailable(
            "system audit runtime is disabled",
            reason_code="audit_runtime_disabled",
        )
    if not binding.outbox_enabled:
        raise SystemAuditCompositionUnavailable(
            "system audit outbox is disabled",
            reason_code="audit_outbox_disabled",
        )

    try:
        coordinator = DjangoSystemAuditEventOutboxCoordinator(using=alias)
        repository = DjangoSystemAuditOutboxRepository(using=alias)
        unit_of_work = DjangoSystemAuditOutboxUnitOfWork(repository)
        publisher = DjangoSystemAuditDeliveryReceiptPublisher(using=alias)
        readers = build_system_audit_authority_readers(using=alias)
        if type(readers) is not SystemAuditAuthorityReaders:
            raise TypeError("authority reader bundle type was substituted")
        readers.__post_init__()
        if readers.database_alias != alias:
            raise ValueError("authority reader alias differs from runtime alias")
        authority_provider = ExactScopedSystemAuditAuthorityProvider(
            actor_reader=readers.actor,
            scope_reader=readers.scope,
            selector=binding.authority_selector,
        )
        authority_bundle = ServerIssuedSystemAuditAuthorityBundle(
            provider=authority_provider,
            selector=binding.authority_selector,
            issuer_id=binding.issuer_id,
        )
        return inspect_system_audit_runtime_composition(
            database_alias=alias,
            event_outbox_coordinator=coordinator,
            dispatch_repository=repository,
            dispatch_unit_of_work=unit_of_work,
            publisher=publisher,
            authority_bundle=authority_bundle,
        )
    except SystemAuditCompositionUnavailable as error:
        raise SystemAuditCompositionUnavailable(
            "system audit runtime composition is unavailable",
            reason_code=_bounded_reason(error.reason_code),
        ) from None
    except Exception:
        raise SystemAuditCompositionUnavailable(
            "system audit runtime composition is unavailable",
            reason_code="runtime_composition_failed",
        ) from None


def build_system_audit_outbox_dispatcher(
    *, environment: str = "production", using: str = "default"
) -> DispatchSystemAuditOutboxUseCase:
    """Build the sole durable, scoped, same-alias audit dispatcher."""

    composition = _build_system_audit_runtime_composition(
        environment=environment,
        using=using,
    )
    return DispatchSystemAuditOutboxUseCase(
        composition.dispatch_repository,
        composition.publisher,
        composition.dispatch_unit_of_work,
        authority_preflight=_RuntimeAuthorityPreflight(composition.authority_bundle),
    )


def build_data_reliability_audit_writers(
    *, environment: str = "production", using: str = "default"
) -> tuple[
    AppendDataFetchAuditObservationUseCase,
    AppendDataPublicationAuditObservationUseCase,
    AppendDataValidationRejectedObservationUseCase,
    AppendDataFailoverAuditObservationUseCase,
    AppendDataDecisionReadAuditObservationUseCase,
    AppendDataProviderHealthAuditObservationUseCase,
    AppendDataFreshnessAuditObservationUseCase,
    AppendDataQualityAuditObservationUseCase,
]:
    """Build canonical Data Reliability writers from one authority bundle."""

    composition = _build_system_audit_runtime_composition(
        environment=environment,
        using=using,
    )
    coordinator = composition.event_outbox_coordinator
    if not all(
        callable(getattr(coordinator, method_name, None))
        for method_name in ("get_winner", "get_current_head")
    ):
        raise SystemAuditCompositionUnavailable(
            "system audit replay reads are unavailable",
            reason_code="composition_not_wired",
        )
    scope_provider = _RuntimeAuthorityScopeProvider(composition.authority_bundle)
    return (
        AppendDataFetchAuditObservationUseCase(
            cast(DataFetchAuditEventOutboxWriter, coordinator),
            scope_provider,
        ),
        AppendDataPublicationAuditObservationUseCase(
            cast(DataPublicationAuditEventOutboxWriter, coordinator),
            scope_provider,
        ),
        AppendDataValidationRejectedObservationUseCase(
            cast(DataValidationAuditEventOutboxWriter, coordinator),
            scope_provider,
        ),
        AppendDataFailoverAuditObservationUseCase(
            cast(DataFailoverAuditEventOutboxWriter, coordinator),
            scope_provider,
        ),
        AppendDataDecisionReadAuditObservationUseCase(
            cast(DataDecisionReadAuditEventOutboxWriter, coordinator),
            scope_provider,
        ),
        AppendDataProviderHealthAuditObservationUseCase(
            cast(DataProviderHealthAuditEventOutboxWriter, coordinator),
            scope_provider,
        ),
        AppendDataFreshnessAuditObservationUseCase(
            cast(DataFreshnessAuditEventOutboxWriter, coordinator),
            scope_provider,
        ),
        AppendDataQualityAuditObservationUseCase(
            cast(DataQualityAuditEventOutboxWriter, coordinator),
            scope_provider,
        ),
    )


def build_data_fetch_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataFetchAuditObservationUseCase:
    """Build the canonical scoped writer used by Data Center fetch commits."""

    return build_data_reliability_audit_writers(
        environment=environment,
        using=using,
    )[0]


def build_data_publication_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataPublicationAuditObservationUseCase:
    """Build the canonical scoped writer used by publication commits."""

    return build_data_reliability_audit_writers(
        environment=environment,
        using=using,
    )[1]


def build_data_validation_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataValidationRejectedObservationUseCase:
    """Build the canonical scoped writer used by validation rejections."""

    return build_data_reliability_audit_writers(
        environment=environment,
        using=using,
    )[2]


def build_data_failover_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataFailoverAuditObservationUseCase:
    """Build the canonical scoped writer used by failover decisions."""

    return build_data_reliability_audit_writers(
        environment=environment,
        using=using,
    )[3]


def build_data_decision_read_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataDecisionReadAuditObservationUseCase:
    """Build the canonical scoped writer used by decision-read gates."""

    return build_data_reliability_audit_writers(
        environment=environment,
        using=using,
    )[4]


def build_data_provider_health_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataProviderHealthAuditObservationUseCase:
    """Build the canonical scoped writer used by provider circuit transitions."""

    return build_data_reliability_audit_writers(
        environment=environment,
        using=using,
    )[5]


def build_data_freshness_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataFreshnessAuditObservationUseCase:
    """Build the canonical scoped writer used by publication freshness gates."""

    return build_data_reliability_audit_writers(
        environment=environment,
        using=using,
    )[6]


def build_data_quality_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataQualityAuditObservationUseCase:
    """Build the canonical scoped writer used by publication-quality projections."""

    return build_data_reliability_audit_writers(
        environment=environment,
        using=using,
    )[7]


def build_data_repair_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataRepairAuditObservationUseCase:
    """Build the canonical scoped writer used by reliability repair runs."""

    composition = _build_system_audit_runtime_composition(
        environment=environment,
        using=using,
    )
    coordinator = composition.event_outbox_coordinator
    if not all(
        callable(getattr(coordinator, method_name, None))
        for method_name in ("get_winner", "get_current_head")
    ):
        raise SystemAuditCompositionUnavailable(
            "system audit replay reads are unavailable",
            reason_code="composition_not_wired",
        )
    return AppendDataRepairAuditObservationUseCase(
        cast(DataRepairAuditEventOutboxWriter, coordinator),
        _RuntimeAuthorityScopeProvider(composition.authority_bundle),
    )


def build_data_conflict_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataConflictAuditObservationUseCase:
    """Build the canonical scoped writer used by reconciliation transitions."""

    composition = _build_system_audit_runtime_composition(
        environment=environment,
        using=using,
    )
    coordinator = composition.event_outbox_coordinator
    if not all(
        callable(getattr(coordinator, method_name, None))
        for method_name in ("get_winner", "get_current_head")
    ):
        raise SystemAuditCompositionUnavailable(
            "system audit replay reads are unavailable",
            reason_code="composition_not_wired",
        )
    return AppendDataConflictAuditObservationUseCase(
        cast(DataConflictAuditEventOutboxWriter, coordinator),
        _RuntimeAuthorityScopeProvider(composition.authority_bundle),
    )


def build_data_publication_rollback_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataPublicationRollbackAuditObservationUseCase:
    """Build the canonical scoped writer used by publication rollbacks."""

    composition = _build_system_audit_runtime_composition(
        environment=environment,
        using=using,
    )
    coordinator = composition.event_outbox_coordinator
    if not all(
        callable(getattr(coordinator, method_name, None))
        for method_name in ("get_winner", "get_current_head")
    ):
        raise SystemAuditCompositionUnavailable(
            "system audit replay reads are unavailable",
            reason_code="composition_not_wired",
        )
    return AppendDataPublicationRollbackAuditObservationUseCase(
        cast(DataPublicationRollbackAuditEventOutboxWriter, coordinator),
        _RuntimeAuthorityScopeProvider(composition.authority_bundle),
    )


class SystemAuditOutboxPublisherUnavailable(RuntimeError):
    """Compatibility error for an unavailable canonical audit runtime."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        checked_reason = _bounded_reason(reason_code)
        super().__init__(message)
        self.reason_code = checked_reason


def get_system_audit_outbox_dispatcher() -> DispatchSystemAuditOutboxUseCase:
    """Resolve the canonical production composition root."""

    try:
        return build_system_audit_outbox_dispatcher()
    except SystemAuditCompositionUnavailable as error:
        reason_code = _bounded_reason(error.reason_code)
    except Exception:
        reason_code = "runtime_composition_failed"
    raise SystemAuditOutboxPublisherUnavailable(
        "system audit outbox runtime is unavailable",
        reason_code=reason_code,
    ) from None


__all__ = [
    "SystemAuditOutboxPublisherUnavailable",
    "build_data_conflict_audit_writer",
    "build_data_decision_read_audit_writer",
    "build_data_freshness_audit_writer",
    "build_data_failover_audit_writer",
    "build_data_fetch_audit_writer",
    "build_data_publication_audit_writer",
    "build_data_publication_rollback_audit_writer",
    "build_data_provider_health_audit_writer",
    "build_data_quality_audit_writer",
    "build_data_repair_audit_writer",
    "build_data_reliability_audit_writers",
    "build_data_validation_audit_writer",
    "build_system_audit_outbox_dispatcher",
    "get_system_audit_outbox_dispatcher",
]
