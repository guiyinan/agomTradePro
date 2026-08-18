"""Fail-closed local composition contract for the system-audit runtime.

The canonical event/outbox writer, outbox dispatcher ports, durable publisher,
and scoped authority are deliberately composed as one object before a future
runtime is allowed to claim an outbox row.  This module contains no Django,
Celery, request, or database lookup.  It is therefore a local contract only;
the current runtime gate remains ``publisher_not_wired`` until a production
composition root supplies real implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from apps.audit.application.system_audit_authority_provider import (
    SystemAuditAuthorityBundleSelector,
)
from apps.audit.application.system_audit_composition import (
    CanonicalSystemAuditPublisherPreflight,
    SystemAuditAuthorityProvider,
    SystemAuditCompositionUnavailable,
    inspect_canonical_system_audit_publisher,
)
from apps.audit.application.system_audit_event_outbox import (
    SystemAuditEventOutboxWriter,
)
from apps.audit.application.system_audit_outbox_dispatcher import (
    SystemAuditOutboxDispatchRepository,
    SystemAuditOutboxDispatchUnitOfWork,
    SystemAuditOutboxPublisher,
)


def _require_token(value: object, field: str) -> str:
    """Validate one bounded, whitespace-free composition identity token."""

    if (
        type(value) is not str
        or not value
        or len(value) > 192
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise SystemAuditCompositionUnavailable(
            f"system audit {field} is not configured",
            reason_code="composition_not_wired",
        )
    return value


class SystemAuditEventOutboxCoordinator(SystemAuditEventOutboxWriter, Protocol):
    """Same-alias canonical event plus outbox transaction boundary."""

    @property
    def database_alias(self) -> str:
        """Return the database alias used by both canonical writes."""


class SystemAuditDispatchRepositoryWithAlias(SystemAuditOutboxDispatchRepository, Protocol):
    """Outbox dispatch repository bound to one explicit database alias."""

    @property
    def database_alias(self) -> str:
        """Return the database alias used for claims and transitions."""


class SystemAuditDispatchUnitOfWorkWithAlias(SystemAuditOutboxDispatchUnitOfWork, Protocol):
    """Claim/finalization transaction boundary bound to one database alias."""

    @property
    def database_alias(self) -> str:
        """Return the database alias used by the unit of work."""


@dataclass(frozen=True, slots=True)
class ServerIssuedSystemAuditAuthorityBundle:
    """Bind an authority provider to one exact externally issued selector.

    ``issuer_id`` is an identity reference, not a locally generated authority
    decision.  A production composition root must obtain the selector from an
    authenticated/server-side issuer and must bind it to the provider before
    constructing this value.  This contract deliberately has no request or
    Django User/Profile access and cannot mint a selector itself.
    """

    provider: SystemAuditAuthorityProvider
    selector: SystemAuditAuthorityBundleSelector
    issuer_id: str

    def __post_init__(self) -> None:
        """Reject provider, selector, or issuer substitution at composition."""

        if not callable(getattr(self.provider, "get_current", None)):
            raise ValueError("authority provider must expose get_current")
        if type(self.selector) is not SystemAuditAuthorityBundleSelector:
            raise ValueError("authority bundle selector type was substituted")
        self.selector.__post_init__()
        try:
            _require_token(self.issuer_id, "authority issuer")
        except SystemAuditCompositionUnavailable as error:
            raise ValueError("authority issuer is not configured") from error
        provider_selector = getattr(self.provider, "authority_bundle_selector", None)
        if provider_selector != self.selector:
            raise ValueError("authority provider selector differs from issued bundle")


@dataclass(frozen=True, slots=True)
class SystemAuditRuntimeComposition:
    """All components that must pass preflight before an outbox claim."""

    database_alias: str
    event_outbox_coordinator: SystemAuditEventOutboxCoordinator
    dispatch_repository: SystemAuditDispatchRepositoryWithAlias
    dispatch_unit_of_work: SystemAuditDispatchUnitOfWorkWithAlias
    publisher: SystemAuditOutboxPublisher
    publisher_preflight: CanonicalSystemAuditPublisherPreflight
    authority_bundle: ServerIssuedSystemAuditAuthorityBundle


def _require_component_alias(
    component: object | None,
    *,
    expected_alias: str,
    field: str,
    required_methods: tuple[str, ...],
) -> str:
    """Validate one component's interface and same-alias binding."""

    if component is None:
        raise SystemAuditCompositionUnavailable(
            f"system audit {field} is not wired",
            reason_code="composition_not_wired",
        )
    for method_name in required_methods:
        if not callable(getattr(component, method_name, None)):
            raise SystemAuditCompositionUnavailable(
                f"system audit {field} contract is unavailable",
                reason_code="composition_not_wired",
            )
    try:
        alias = _require_token(
            cast(SystemAuditEventOutboxCoordinator, component).database_alias,
            f"{field} database alias",
        )
    except (AttributeError, TypeError):
        raise SystemAuditCompositionUnavailable(
            f"system audit {field} database alias is unavailable",
            reason_code="composition_not_wired",
        ) from None
    if alias != expected_alias:
        raise SystemAuditCompositionUnavailable(
            "system audit components are bound to different database aliases",
            reason_code="composition_alias_mismatch",
        )
    return alias


def inspect_system_audit_runtime_composition(
    *,
    database_alias: str,
    event_outbox_coordinator: object | None,
    dispatch_repository: object | None,
    dispatch_unit_of_work: object | None,
    publisher: object | None,
    authority_bundle: ServerIssuedSystemAuditAuthorityBundle | None,
) -> SystemAuditRuntimeComposition:
    """Validate a future runtime composition before any outbox claim.

    The function only inspects injected objects.  It does not call a provider
    ``get_current`` method, claim rows, publish events, or open a transaction.
    Missing publisher and authority remain stable ``publisher_not_wired`` and
    ``authority_not_wired`` failures respectively; every other missing or
    mismatched component fails with a bounded composition reason.
    """

    expected_alias = _require_token(database_alias, "database alias")
    _require_component_alias(
        event_outbox_coordinator,
        expected_alias=expected_alias,
        field="event/outbox coordinator",
        required_methods=("atomic", "append_and_enqueue"),
    )
    _require_component_alias(
        dispatch_repository,
        expected_alias=expected_alias,
        field="outbox dispatch repository",
        required_methods=("claim_due", "mark_delivered", "mark_failed"),
    )
    _require_component_alias(
        dispatch_unit_of_work,
        expected_alias=expected_alias,
        field="outbox dispatch unit of work",
        required_methods=("__enter__", "__exit__"),
    )

    # Validate the authority bundle before invoking publisher preflight.  A
    # publisher preflight may perform an external capability check; it must
    # not be called when the authenticated/scoped authority side is absent or
    # forged.  This keeps the fail-closed boundary deterministic and avoids a
    # side effect before all local composition prerequisites are present.
    if authority_bundle is None:
        raise SystemAuditCompositionUnavailable(
            "system audit authority bundle is not wired",
            reason_code="authority_not_wired",
        )
    try:
        authority_bundle.__post_init__()
    except (AttributeError, TypeError, ValueError):
        raise SystemAuditCompositionUnavailable(
            "system audit authority bundle is unavailable",
            reason_code="authority_unavailable",
        ) from None

    if publisher is None:
        raise SystemAuditCompositionUnavailable(
            "system audit publisher is not wired",
            reason_code="publisher_not_wired",
        )
    try:
        validated_publisher, publisher_preflight = inspect_canonical_system_audit_publisher(
            publisher
        )
    except SystemAuditCompositionUnavailable:
        raise
    except Exception:
        raise SystemAuditCompositionUnavailable(
            "system audit publisher composition is unavailable",
            reason_code="publisher_not_wired",
        ) from None

    return SystemAuditRuntimeComposition(
        database_alias=expected_alias,
        event_outbox_coordinator=cast(SystemAuditEventOutboxCoordinator, event_outbox_coordinator),
        dispatch_repository=cast(SystemAuditDispatchRepositoryWithAlias, dispatch_repository),
        dispatch_unit_of_work=cast(SystemAuditDispatchUnitOfWorkWithAlias, dispatch_unit_of_work),
        publisher=validated_publisher,
        publisher_preflight=publisher_preflight,
        authority_bundle=authority_bundle,
    )


__all__ = [
    "ServerIssuedSystemAuditAuthorityBundle",
    "SystemAuditDispatchRepositoryWithAlias",
    "SystemAuditDispatchUnitOfWorkWithAlias",
    "SystemAuditEventOutboxCoordinator",
    "SystemAuditRuntimeComposition",
    "inspect_system_audit_runtime_composition",
]
