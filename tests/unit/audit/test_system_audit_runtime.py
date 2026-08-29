"""Production composition-root tests for the system-audit dispatcher."""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from apps.audit.application import repository_provider
from apps.audit.application.data_conflict_audit import (
    AppendDataConflictAuditObservationUseCase,
)
from apps.audit.application.data_freshness_audit import (
    AppendDataFreshnessAuditObservationUseCase,
)
from apps.audit.application.data_publication_rollback_audit import (
    AppendDataPublicationRollbackAuditObservationUseCase,
)
from apps.audit.application.data_quality_audit import (
    AppendDataQualityAuditObservationUseCase,
)
from apps.audit.application.data_repair_audit import (
    AppendDataRepairAuditObservationUseCase,
)
from apps.audit.application.system_audit_authority_provider import (
    SystemAuditActorAuthorityFacts,
    SystemAuditAuthorityBundleSelector,
    SystemAuditScopeAuthorityFacts,
)
from apps.audit.application.system_audit_composition import (
    CanonicalSystemAuditPublisherPreflight,
    CanonicalSystemAuditPublishReceipt,
    SystemAuditCompositionUnavailable,
)
from apps.audit.application.system_audit_outbox_dispatcher import (
    DispatchSystemAuditOutboxCommand,
    SystemAuditOutboxClaimDTO,
    SystemAuditOutboxDispatchUnavailable,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent
from apps.audit.infrastructure import system_audit_outbox_runtime as runtime
from core.integration.system_audit_authority import SystemAuditAuthorityReaders
from core.integration.system_audit_runtime_config import (
    SystemAuditRuntimeConfigBinding,
    SystemAuditRuntimeConfigurationUnavailable,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _selector() -> SystemAuditAuthorityBundleSelector:
    return SystemAuditAuthorityBundleSelector(
        actor_source_id="account-actor-source",
        actor_source_version="v1",
        actor_content_hash="a" * 64,
        scope_source_id="account-scope-source",
        scope_source_version="v1",
        scope_content_hash="b" * 64,
    )


def _binding(
    *, mode: str = "required", outbox_enabled: bool = True
) -> SystemAuditRuntimeConfigBinding:
    return SystemAuditRuntimeConfigBinding(
        mode=mode,
        outbox_enabled=outbox_enabled,
        authority_selector=_selector(),
        issuer_id="audit-config:" + "c" * 64,
        snapshot_id="audit-snapshot-7",
        snapshot_hash="d" * 64,
        profile_id="audit-profile-3",
        profile_key="production-audit",
        profile_version=3,
        environment="production",
    )


class _ActorReader:
    def __init__(self, alias: str, order: list[str]) -> None:
        self.database_alias = alias
        self._order = order

    def get_current(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> SystemAuditActorAuthorityFacts:
        self._order.append("authority_actor")
        return SystemAuditActorAuthorityFacts(
            source_id=source_id,
            source_version=source_version,
            content_hash=expected_content_hash,
            actor_id="django-user:7",
            user_id=7,
            is_authenticated=True,
            is_staff=True,
            role="audit_reader",
            authority_state="active",
            recorded_at=as_of - timedelta(minutes=1),
            valid_until=as_of + timedelta(minutes=1),
        )


class _ScopeReader:
    def __init__(self, alias: str, order: list[str]) -> None:
        self.database_alias = alias
        self._order = order

    def get_current(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> SystemAuditScopeAuthorityFacts:
        self._order.append("authority_scope")
        return SystemAuditScopeAuthorityFacts(
            source_id=source_id,
            source_version=source_version,
            content_hash=expected_content_hash,
            actor_id="django-user:7",
            user_id=7,
            tenant_id="tenant:primary",
            owner_id="owner:audit",
            authority_state="active",
            recorded_at=as_of - timedelta(minutes=1),
            valid_until=as_of + timedelta(minutes=1),
        )


class _Coordinator:
    def __init__(self, alias: str) -> None:
        self.database_alias = alias

    def atomic(self) -> AbstractContextManager[None]:
        return nullcontext()

    def append_and_enqueue(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("dispatcher composition must not write an event")

    def get_winner(self, **kwargs: object) -> None:
        del kwargs
        return None

    def get_current_head(self, **kwargs: object) -> None:
        del kwargs
        return None


class _Repository:
    def __init__(self, alias: str, order: list[str]) -> None:
        self.database_alias = alias
        self._order = order

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self._order.append("uow_enter")
        try:
            yield
        finally:
            self._order.append("uow_exit")

    def claim_due(
        self, *, worker_id: str, as_of: datetime, limit: int
    ) -> tuple[SystemAuditOutboxClaimDTO, ...]:
        del worker_id, as_of, limit
        self._order.append("claim")
        return ()

    def mark_delivered(self, **kwargs: object) -> object:
        del kwargs
        raise AssertionError("there are no claims to finalize")

    def mark_failed(self, **kwargs: object) -> object:
        del kwargs
        raise AssertionError("there are no claims to finalize")


class _Publisher:
    def __init__(self, alias: str, order: list[str]) -> None:
        self.database_alias = alias
        self._order = order

    def preflight(self) -> CanonicalSystemAuditPublisherPreflight:
        self._order.append("publisher_preflight")
        return CanonicalSystemAuditPublisherPreflight(
            sink_id="audit-system-delivery-receipt-v1",
            sink_kind="durable",
        )

    def publish(self, event: SystemAuditEvent) -> CanonicalSystemAuditPublishReceipt:
        del event
        raise AssertionError("there are no claimed events to publish")


def _readers(alias: str, order: list[str]) -> SystemAuditAuthorityReaders:
    return SystemAuditAuthorityReaders(
        actor=cast(object, _ActorReader(alias, order)),
        scope=cast(object, _ScopeReader(alias, order)),
        database_alias=alias,
    )


def _install_successful_components(
    monkeypatch: pytest.MonkeyPatch,
    *,
    binding: SystemAuditRuntimeConfigBinding,
    alias: str,
    order: list[str],
) -> tuple[_Repository, _Publisher, SystemAuditAuthorityReaders]:
    repository = _Repository(alias, order)
    publisher = _Publisher(alias, order)
    readers = _readers(alias, order)

    def load_binding(*, environment: str) -> SystemAuditRuntimeConfigBinding:
        assert environment == binding.environment
        return binding

    def build_readers(*, using: str) -> SystemAuditAuthorityReaders:
        assert using == alias
        return readers

    monkeypatch.setattr(runtime, "load_system_audit_runtime_config", load_binding)
    monkeypatch.setattr(
        runtime,
        "DjangoSystemAuditEventOutboxCoordinator",
        lambda *, using: _Coordinator(using),
    )
    monkeypatch.setattr(
        runtime,
        "DjangoSystemAuditOutboxRepository",
        lambda *, using: repository if using == alias else AssertionError(using),
    )
    monkeypatch.setattr(
        runtime,
        "DjangoSystemAuditDeliveryReceiptPublisher",
        lambda *, using: publisher if using == alias else AssertionError(using),
    )
    monkeypatch.setattr(runtime, "build_system_audit_authority_readers", build_readers)
    return repository, publisher, readers


@pytest.mark.parametrize(
    ("binding", "reason_code"),
    [
        (_binding(mode="off"), "audit_runtime_disabled"),
        (_binding(outbox_enabled=False), "audit_outbox_disabled"),
    ],
)
def test_disabled_binding_constructs_no_runtime_component(
    monkeypatch: pytest.MonkeyPatch,
    binding: SystemAuditRuntimeConfigBinding,
    reason_code: str,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(runtime, "load_system_audit_runtime_config", lambda **kwargs: binding)
    monkeypatch.setattr(
        runtime,
        "DjangoSystemAuditEventOutboxCoordinator",
        lambda **kwargs: calls.append("coordinator"),
    )

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        runtime.build_system_audit_outbox_dispatcher()

    assert exc_info.value.reason_code == reason_code
    assert calls == []


def test_config_failure_preserves_stable_reason_before_component_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def unavailable(*, environment: str) -> SystemAuditRuntimeConfigBinding:
        del environment
        raise SystemAuditRuntimeConfigurationUnavailable("snapshot_unavailable")

    monkeypatch.setattr(runtime, "load_system_audit_runtime_config", unavailable)
    monkeypatch.setattr(
        runtime,
        "DjangoSystemAuditEventOutboxCoordinator",
        lambda **kwargs: calls.append("coordinator"),
    )

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        runtime.build_system_audit_outbox_dispatcher()

    assert exc_info.value.reason_code == "snapshot_unavailable"
    assert calls == []


@pytest.mark.parametrize(
    "binding",
    [object(), replace(_binding(), environment="staging")],
)
def test_substituted_or_cross_environment_binding_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    binding: object,
) -> None:
    monkeypatch.setattr(runtime, "load_system_audit_runtime_config", lambda **kwargs: binding)

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        runtime.build_system_audit_outbox_dispatcher(environment="production")

    assert exc_info.value.reason_code == "runtime_configuration_invalid"


@pytest.mark.parametrize("alias", ["", " bad", "a b", "a" * 65, 7])
def test_invalid_alias_is_rejected_before_config_read(
    monkeypatch: pytest.MonkeyPatch, alias: object
) -> None:
    config_calls: list[str] = []
    monkeypatch.setattr(
        runtime,
        "load_system_audit_runtime_config",
        lambda **kwargs: config_calls.append("config"),
    )

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        runtime.build_system_audit_outbox_dispatcher(using=cast(str, alias))

    assert exc_info.value.reason_code == "composition_not_wired"
    assert config_calls == []


def test_runtime_binds_exact_alias_repository_selector_and_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _binding()
    order: list[str] = []
    repository, publisher, readers = _install_successful_components(
        monkeypatch,
        binding=binding,
        alias="audit",
        order=order,
    )

    dispatcher = runtime.build_system_audit_outbox_dispatcher(
        environment="production",
        using="audit",
    )

    unit_of_work = dispatcher._unit_of_work
    authority_preflight = dispatcher._authority_preflight
    bundle = authority_preflight.bundle
    provider = bundle.provider
    assert dispatcher._repository is repository
    assert dispatcher._publisher is publisher
    assert unit_of_work._repository is repository
    assert unit_of_work.database_alias == "audit"
    assert bundle.selector is binding.authority_selector
    assert bundle.issuer_id == binding.issuer_id
    assert provider.authority_bundle_selector is binding.authority_selector
    assert provider._actor_reader is readers.actor
    assert provider._scope_reader is readers.scope
    assert order == ["publisher_preflight"]


def test_execute_orders_authority_and_sink_preflight_before_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    _install_successful_components(
        monkeypatch,
        binding=_binding(mode="shadow"),
        alias="audit",
        order=order,
    )
    dispatcher = runtime.build_system_audit_outbox_dispatcher(using="audit")
    order.clear()

    result = dispatcher.execute(
        DispatchSystemAuditOutboxCommand(
            worker_id="audit-worker",
            as_of=NOW,
            limit=5,
        )
    )

    assert result.outcome == "noop"
    assert (result.claimed, result.delivered, result.failed) == (0, 0, 0)
    assert order == [
        "authority_actor",
        "authority_scope",
        "publisher_preflight",
        "uow_enter",
        "claim",
        "uow_exit",
    ]


def test_repair_writer_uses_the_inspected_alias_and_authority_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    _install_successful_components(
        monkeypatch,
        binding=_binding(),
        alias="audit",
        order=order,
    )

    writer = runtime.build_data_repair_audit_writer(using="audit")
    scope = writer._scope_provider.get_scope(as_of=NOW)

    assert isinstance(writer, AppendDataRepairAuditObservationUseCase)
    assert writer.database_alias == "audit"
    assert scope.tenant_id == "tenant:primary"
    assert scope.owner_id == "owner:audit"
    assert order == ["publisher_preflight", "authority_actor", "authority_scope"]


def test_freshness_writer_uses_the_inspected_alias_and_authority_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    _install_successful_components(
        monkeypatch,
        binding=_binding(),
        alias="audit",
        order=order,
    )

    writer = runtime.build_data_freshness_audit_writer(using="audit")
    scope = writer._scope_provider.get_scope(as_of=NOW)

    assert isinstance(writer, AppendDataFreshnessAuditObservationUseCase)
    assert writer.database_alias == "audit"
    assert scope.tenant_id == "tenant:primary"
    assert scope.owner_id == "owner:audit"
    assert order == ["publisher_preflight", "authority_actor", "authority_scope"]


def test_quality_writer_uses_the_inspected_alias_and_authority_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    _install_successful_components(
        monkeypatch,
        binding=_binding(),
        alias="audit",
        order=order,
    )

    writer = runtime.build_data_quality_audit_writer(using="audit")
    scope = writer._scope_provider.get_scope(as_of=NOW)

    assert isinstance(writer, AppendDataQualityAuditObservationUseCase)
    assert writer.database_alias == "audit"
    assert scope.tenant_id == "tenant:primary"
    assert scope.owner_id == "owner:audit"
    assert order == ["publisher_preflight", "authority_actor", "authority_scope"]


def test_conflict_writer_uses_the_inspected_alias_and_authority_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    _install_successful_components(
        monkeypatch,
        binding=_binding(),
        alias="audit",
        order=order,
    )

    writer = runtime.build_data_conflict_audit_writer(using="audit")
    scope = writer._scope_provider.get_scope(as_of=NOW)

    assert isinstance(writer, AppendDataConflictAuditObservationUseCase)
    assert writer.database_alias == "audit"
    assert scope.tenant_id == "tenant:primary"
    assert scope.owner_id == "owner:audit"
    assert order == ["publisher_preflight", "authority_actor", "authority_scope"]


def test_publication_rollback_writer_uses_inspected_alias_and_authority_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    _install_successful_components(
        monkeypatch,
        binding=_binding(),
        alias="audit",
        order=order,
    )

    writer = runtime.build_data_publication_rollback_audit_writer(using="audit")
    scope = writer._scope_provider.get_scope(as_of=NOW)

    assert isinstance(writer, AppendDataPublicationRollbackAuditObservationUseCase)
    assert writer.database_alias == "audit"
    assert scope.tenant_id == "tenant:primary"
    assert scope.owner_id == "owner:audit"
    assert order == ["publisher_preflight", "authority_actor", "authority_scope"]


def test_constructor_failure_is_redacted_by_infrastructure_composition_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime, "load_system_audit_runtime_config", lambda **kwargs: _binding())
    monkeypatch.setattr(
        runtime,
        "DjangoSystemAuditEventOutboxCoordinator",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("postgres://audit:secret@example.test/audit")
        ),
    )

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        runtime.build_system_audit_outbox_dispatcher()

    assert exc_info.value.reason_code == "runtime_composition_failed"
    assert "postgres://" not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


def test_inspection_failure_preserves_only_its_stable_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_successful_components(
        monkeypatch,
        binding=_binding(),
        alias="default",
        order=[],
    )

    def mismatched_alias(**kwargs: object) -> object:
        del kwargs
        raise SystemAuditCompositionUnavailable(
            "postgres://audit:secret@example.test/audit",
            reason_code="composition_alias_mismatch",
        )

    monkeypatch.setattr(runtime, "inspect_system_audit_runtime_composition", mismatched_alias)

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        runtime.build_system_audit_outbox_dispatcher()

    assert exc_info.value.reason_code == "composition_alias_mismatch"
    assert "postgres://" not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


def test_infrastructure_boundary_preserves_only_safe_reason_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unsafe_reason(**kwargs: object) -> object:
        del kwargs
        raise SystemAuditCompositionUnavailable(
            "postgres://audit:secret@example.test/audit",
            reason_code="postgres://audit:secret",
        )

    monkeypatch.setattr(runtime, "build_system_audit_outbox_dispatcher", unsafe_reason)

    with pytest.raises(runtime.SystemAuditOutboxPublisherUnavailable) as exc_info:
        runtime.get_system_audit_outbox_dispatcher()

    assert exc_info.value.reason_code == "runtime_composition_failed"
    assert "postgres://" not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


def test_repository_provider_maps_runtime_unavailability_without_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> object:
        raise runtime.SystemAuditOutboxPublisherUnavailable(
            "postgres://audit:secret@example.test/audit",
            reason_code="snapshot_unavailable",
        )

    monkeypatch.setattr(runtime, "get_system_audit_outbox_dispatcher", unavailable)

    with pytest.raises(SystemAuditOutboxDispatchUnavailable) as exc_info:
        repository_provider.get_system_audit_outbox_dispatcher()

    assert exc_info.value.reason_code == "snapshot_unavailable"
    assert "postgres://" not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


def test_repository_provider_rejects_substituted_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime,
        "get_system_audit_outbox_dispatcher",
        lambda: object(),
    )

    with pytest.raises(SystemAuditOutboxDispatchUnavailable) as exc_info:
        repository_provider.get_system_audit_outbox_dispatcher()

    assert exc_info.value.reason_code == "invalid_dispatch_composition"


def test_runtime_sources_have_no_generic_event_or_memory_fallback() -> None:
    source = inspect.getsource(runtime)

    assert "apps.events" not in source
    assert "InMemory" not in source
