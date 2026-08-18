"""Fail-closed tests for the dormant system-audit runtime composition."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from apps.audit.application.system_audit_authority_provider import (
    SystemAuditAuthorityBundleSelector,
)
from apps.audit.application.system_audit_composition import (
    CanonicalSystemAuditPublisherPreflight,
    SystemAuditCompositionUnavailable,
)
from apps.audit.application.system_audit_runtime_composition import (
    ServerIssuedSystemAuditAuthorityBundle,
    inspect_system_audit_runtime_composition,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _selector() -> SystemAuditAuthorityBundleSelector:
    return SystemAuditAuthorityBundleSelector(
        actor_source_id="account-actor-source",
        actor_source_version="v1",
        actor_content_hash="a" * 64,
        scope_source_id="research-scope-source",
        scope_source_version="v1",
        scope_content_hash="b" * 64,
    )


class _Coordinator:
    database_alias = "default"

    def atomic(self) -> object:
        return nullcontext()

    def append_and_enqueue(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("composition preflight must not write")


class _DispatchRepository:
    database_alias = "default"

    def __init__(self) -> None:
        self.claim_calls = 0

    def claim_due(self, **kwargs: object) -> tuple[object, ...]:
        del kwargs
        self.claim_calls += 1
        raise AssertionError("composition preflight must not claim")

    def mark_delivered(self, **kwargs: object) -> object:
        del kwargs
        raise AssertionError("composition preflight must not transition")

    def mark_failed(self, **kwargs: object) -> object:
        del kwargs
        raise AssertionError("composition preflight must not transition")


class _DispatchUnitOfWork:
    database_alias = "default"

    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        del args


class _DurablePublisher:
    def __init__(self) -> None:
        self.preflight_calls = 0

    def preflight(self) -> CanonicalSystemAuditPublisherPreflight:
        self.preflight_calls += 1
        return CanonicalSystemAuditPublisherPreflight(
            sink_id="audit-primary",
            sink_kind="durable",
        )

    def publish(self, event: object) -> object:
        del event
        raise AssertionError("composition preflight must not publish")


class _AuthorityProvider:
    def __init__(self, selector: SystemAuditAuthorityBundleSelector) -> None:
        self.authority_bundle_selector = selector
        self.calls = 0

    def get_current(self, *, as_of: datetime) -> None:
        del as_of
        self.calls += 1
        return None


def _authority_bundle(
    selector: SystemAuditAuthorityBundleSelector | None = None,
) -> ServerIssuedSystemAuditAuthorityBundle:
    checked = selector or _selector()
    return ServerIssuedSystemAuditAuthorityBundle(
        provider=_AuthorityProvider(checked),
        selector=checked,
        issuer_id="authority-issuer",
    )


def _kwargs() -> dict[str, object]:
    return {
        "database_alias": "default",
        "event_outbox_coordinator": _Coordinator(),
        "dispatch_repository": _DispatchRepository(),
        "dispatch_unit_of_work": _DispatchUnitOfWork(),
        "publisher": _DurablePublisher(),
        "authority_bundle": _authority_bundle(),
    }


def test_runtime_composition_requires_all_same_alias_components() -> None:
    values = _kwargs()

    composition = inspect_system_audit_runtime_composition(**values)

    assert composition.database_alias == "default"
    assert composition.publisher_preflight.sink_id == "audit-primary"
    assert composition.authority_bundle.issuer_id == "authority-issuer"
    assert composition.authority_bundle.provider.calls == 0


def test_missing_publisher_is_blocked_before_any_claim() -> None:
    values = _kwargs()
    repository = values["dispatch_repository"]
    values["publisher"] = None

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        inspect_system_audit_runtime_composition(**values)

    assert exc_info.value.reason_code == "publisher_not_wired"
    assert repository.claim_calls == 0  # type: ignore[union-attr]


def test_missing_authority_bundle_is_blocked_before_any_claim() -> None:
    values = _kwargs()
    repository = values["dispatch_repository"]
    publisher = values["publisher"]
    values["authority_bundle"] = None

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        inspect_system_audit_runtime_composition(**values)

    assert exc_info.value.reason_code == "authority_not_wired"
    assert repository.claim_calls == 0  # type: ignore[union-attr]
    assert publisher.preflight_calls == 0  # type: ignore[union-attr]


def test_invalid_authority_bundle_is_rejected_before_publisher_preflight() -> None:
    values = _kwargs()
    publisher = values["publisher"]
    forged = object.__new__(ServerIssuedSystemAuditAuthorityBundle)
    object.__setattr__(forged, "provider", object())
    object.__setattr__(forged, "selector", _selector())
    object.__setattr__(forged, "issuer_id", "authority-issuer")
    values["authority_bundle"] = forged

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        inspect_system_audit_runtime_composition(**values)

    assert exc_info.value.reason_code == "authority_unavailable"
    assert publisher.preflight_calls == 0  # type: ignore[union-attr]


def test_generic_publisher_contract_is_blocked_before_any_claim() -> None:
    values = _kwargs()
    repository = values["dispatch_repository"]
    values["publisher"] = object()

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        inspect_system_audit_runtime_composition(**values)

    assert exc_info.value.reason_code == "publisher_contract_unavailable"
    assert repository.claim_calls == 0  # type: ignore[union-attr]


def test_authority_provider_selector_substitution_is_blocked() -> None:
    values = _kwargs()
    selector = _selector()
    forged = object.__new__(ServerIssuedSystemAuditAuthorityBundle)
    object.__setattr__(
        forged,
        "provider",
        _AuthorityProvider(replace(selector, actor_content_hash="c" * 64)),
    )
    object.__setattr__(forged, "selector", selector)
    object.__setattr__(forged, "issuer_id", "authority-issuer")
    values["authority_bundle"] = forged

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        inspect_system_audit_runtime_composition(**values)

    assert exc_info.value.reason_code == "authority_unavailable"


@pytest.mark.parametrize(
    ("component", "expected_reason"),
    [
        ("event_outbox_coordinator", "composition_not_wired"),
        ("dispatch_repository", "composition_not_wired"),
        ("dispatch_unit_of_work", "composition_not_wired"),
    ],
)
def test_missing_storage_component_is_blocked_before_publisher_or_authority(
    component: str,
    expected_reason: str,
) -> None:
    values = _kwargs()
    values[component] = None

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        inspect_system_audit_runtime_composition(**values)

    assert exc_info.value.reason_code == expected_reason


@pytest.mark.parametrize(
    "component",
    ["event_outbox_coordinator", "dispatch_repository", "dispatch_unit_of_work"],
)
def test_database_alias_drift_is_blocked(component: str) -> None:
    values = _kwargs()
    drifted = values[component]
    drifted.database_alias = "other"  # type: ignore[attr-defined]

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        inspect_system_audit_runtime_composition(**values)

    assert exc_info.value.reason_code == "composition_alias_mismatch"


def test_authority_bundle_requires_a_nonempty_issuer_reference() -> None:
    with pytest.raises(ValueError, match="authority issuer"):
        ServerIssuedSystemAuditAuthorityBundle(
            provider=_AuthorityProvider(_selector()),
            selector=_selector(),
            issuer_id="",
        )
