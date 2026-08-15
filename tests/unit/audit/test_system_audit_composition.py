"""Unit contracts for the dormant system-audit composition boundary."""

from __future__ import annotations

from collections import UserDict
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from apps.audit.application.system_audit_composition import (
    CanonicalSystemAuditPublishReceipt,
    SystemAuditAuthoritySnapshot,
    SystemAuditCompositionUnavailable,
    SystemAuditPublisherContractViolation,
    get_system_audit_reader_context,
    system_audit_authority_content_hash,
)
from tests.unit.audit.test_system_audit_event import make_event

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def _authority(**changes: object) -> SystemAuditAuthoritySnapshot:
    values: dict[str, object] = {
        "actor_id": "django-user:7",
        "user_id": 7,
        "tenant_id": "tenant:primary",
        "owner_id": "owner:research",
        "is_authenticated": True,
        "is_staff": True,
        "role": "audit_reader",
    }
    values.update(changes)
    values["authority_content_hash"] = system_audit_authority_content_hash(
        actor_id=values["actor_id"],
        user_id=values["user_id"],
        tenant_id=values["tenant_id"],
        owner_id=values["owner_id"],
        is_authenticated=values["is_authenticated"],
        is_staff=values["is_staff"],
        role=values["role"],
    )
    return SystemAuditAuthoritySnapshot(**values)


class Provider:
    def __init__(self, snapshot: SystemAuditAuthoritySnapshot | None) -> None:
        self.snapshot = snapshot

    def get_current(self, *, as_of: datetime) -> SystemAuditAuthoritySnapshot | None:
        assert as_of == NOW
        return self.snapshot


def test_missing_authority_provider_is_blocked_before_query_context() -> None:
    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        get_system_audit_reader_context(None, as_of=NOW)
    assert exc_info.value.reason_code == "authority_not_wired"


@pytest.mark.parametrize(
    "changes",
    [
        {"is_authenticated": False},
        {"is_staff": False},
        {"actor_id": "django-user:8"},
    ],
)
def test_unscoped_or_ineligible_authority_is_blocked(changes: dict[str, object]) -> None:
    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        get_system_audit_reader_context(Provider(_authority(**changes)), as_of=NOW)
    assert exc_info.value.reason_code == "authority_unavailable"


@pytest.mark.parametrize("field", ["tenant_id", "owner_id"])
def test_authority_snapshot_rejects_missing_scope(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        _authority(**{field: ""})


def test_authority_provider_is_the_only_source_for_reader_context() -> None:
    context = get_system_audit_reader_context(Provider(_authority()), as_of=NOW)
    assert context.can_read is True
    assert (context.actor_id, context.user_id, context.is_staff) == (
        "django-user:7",
        7,
        True,
    )


def test_authority_snapshot_hash_binds_all_scope_facts() -> None:
    snapshot = _authority()
    substituted = snapshot.__class__(
        actor_id=snapshot.actor_id,
        user_id=snapshot.user_id,
        tenant_id="tenant:other",
        owner_id=snapshot.owner_id,
        authority_content_hash=snapshot.authority_content_hash,
        is_authenticated=snapshot.is_authenticated,
        is_staff=snapshot.is_staff,
        role=snapshot.role,
    )

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        get_system_audit_reader_context(Provider(substituted), as_of=NOW)

    assert exc_info.value.reason_code == "authority_unavailable"


def test_authority_snapshot_hash_rejects_provider_issued_placeholder() -> None:
    snapshot = replace(_authority(), authority_content_hash="a" * 64)

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        get_system_audit_reader_context(Provider(snapshot), as_of=NOW)

    assert exc_info.value.reason_code == "authority_unavailable"


def test_invalid_cutoff_is_blocked_before_provider_read() -> None:
    class ExplodingProvider(Provider):
        def get_current(self, *, as_of: datetime) -> SystemAuditAuthoritySnapshot | None:
            raise AssertionError("provider must not run")

    with pytest.raises(SystemAuditCompositionUnavailable, match="cutoff"):
        get_system_audit_reader_context(
            ExplodingProvider(_authority()),
            as_of=datetime(2026, 8, 15, 12, 0),
        )


def test_authority_provider_failure_is_redacted_and_fail_closed() -> None:
    class FailingProvider(Provider):
        def get_current(self, *, as_of: datetime) -> SystemAuditAuthoritySnapshot | None:
            del as_of
            raise RuntimeError("database password must not escape")

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        get_system_audit_reader_context(FailingProvider(_authority()), as_of=NOW)

    assert exc_info.value.reason_code == "authority_unavailable"
    assert "password" not in str(exc_info.value)


def test_invalid_authority_provider_result_is_fail_closed() -> None:
    class InvalidProvider:
        def get_current(self, *, as_of: datetime) -> object:
            del as_of
            return object()

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        get_system_audit_reader_context(InvalidProvider(), as_of=NOW)

    assert exc_info.value.reason_code == "authority_unavailable"


@pytest.mark.parametrize("cutoff", [None, "2026-08-15T12:00:00Z", object()])
def test_non_datetime_cutoff_is_blocked_before_provider_read(cutoff: object) -> None:
    class ExplodingProvider(Provider):
        def get_current(self, *, as_of: datetime) -> SystemAuditAuthoritySnapshot | None:
            del as_of
            raise AssertionError("provider must not run")

    with pytest.raises(SystemAuditCompositionUnavailable) as exc_info:
        get_system_audit_reader_context(ExplodingProvider(_authority()), as_of=cutoff)  # type: ignore[arg-type]

    assert exc_info.value.reason_code == "authority_cutoff_invalid"


def test_publish_receipt_preserves_all_event_identity_and_payload() -> None:
    event = make_event()
    receipt = CanonicalSystemAuditPublishReceipt.from_event(event)
    receipt.validate_for(event)

    with pytest.raises(SystemAuditPublisherContractViolation):
        replace(receipt, content_hash="b" * 64).validate_for(event)

    payload = dict(receipt.canonical_payload)
    payload["sequence_no"] = 2
    with pytest.raises(SystemAuditPublisherContractViolation):
        replace(receipt, canonical_payload=payload).validate_for(event)

    with pytest.raises(SystemAuditPublisherContractViolation, match="non-canonical"):
        replace(receipt, canonical_payload={"invalid": object()}).validate_for(event)


@pytest.mark.parametrize(
    "replacement",
    [
        lambda payload: {**payload, "reason_codes": tuple(payload["reason_codes"])},
        lambda payload: {
            **payload,
            "detail": UserDict(payload["detail"]),
        },
        lambda payload: {**payload, "sequence_no": str(payload["sequence_no"])},
    ],
)
def test_publish_receipt_rejects_non_exact_nested_payload_types(
    replacement: Callable[[dict[str, object]], dict[str, object]],
) -> None:
    event = make_event()
    receipt = CanonicalSystemAuditPublishReceipt.from_event(event)
    payload = dict(receipt.canonical_payload)
    changed = replacement(payload)

    with pytest.raises(SystemAuditPublisherContractViolation, match="canonical"):
        replace(receipt, canonical_payload=changed).validate_for(event)


def test_publish_receipt_rejects_bool_for_sequence_number() -> None:
    event = make_event()
    with pytest.raises(ValueError, match="sequence_no"):
        replace(CanonicalSystemAuditPublishReceipt.from_event(event), sequence_no=True)
