from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from apps.audit.application.system_audit_authority_renewal import (
    RenewSystemAuditAuthority,
    SystemAuditAuthorityRenewalUnavailable,
)
from apps.audit.infrastructure.system_audit_authority_renewal_request import (
    parse_system_audit_authority_renewal_request,
)


def _request() -> dict[str, object]:
    digest = "a" * 64
    return {
        "database_alias": "default",
        "actor_recorder_service_id": "service:audit-renewer",
        "actor_validity_seconds": 7200,
        "authority_validity_seconds": 7200,
        "minimum_window_seconds": 2100,
        "principal": {
            "principal_id": "principal:fresh",
            "user_id": 1,
            "authentication_context_hash": digest,
            "authenticated_at": "2026-09-23T07:00:00Z",
            "valid_until": "2026-09-23T12:00:00Z",
        },
        "policy": {
            "policy_id": "policy:audit",
            "policy_version": "v1",
            "expected_content_hash": digest,
            "tenant_id": "tenant:agom",
            "owner_id": "owner:admin",
            "account_namespace": "simulated",
            "account_id": "account:1",
        },
        "actor_capture": {
            "source_id": "actor:fresh",
            "source_version": "v1",
            "principal_id": "principal:fresh",
            "user_id": 1,
            "authentication_context_id": "auth:fresh",
            "authentication_context_version": "v1",
            "expected_authentication_context_content_hash": digest,
            "user_source_id": "user:fresh",
            "user_source_version": "v1",
            "expected_user_source_content_hash": digest,
            "rbac_source_id": "rbac:fresh",
            "rbac_source_version": "v1",
            "expected_rbac_source_content_hash": digest,
        },
        "owner_successor": {
            "authority_id": "authority:audit",
            "authority_version": "v3.2",
            "predecessor_version": "v3.1",
            "expected_predecessor_content_hash": digest,
            "assignment_evidence_id": "evidence:audit",
            "assignment_evidence_version": "v5.1",
            "expected_assignment_evidence_content_hash": digest,
        },
        "profile": {
            "environment": "production",
            "actor": "service:audit-renewer",
            "reason": "renew audit authority",
            "release_ref": "test",
            "expected_active_profile_id": None,
            "expected_active_profile_version": None,
            "expected_active_profile_hash": None,
            "expected_active_snapshot_hash": None,
        },
    }


def test_renewal_request_parser_returns_typed_hash_bound_input() -> None:
    parsed = parse_system_audit_authority_renewal_request(
        json.dumps(_request(), separators=(",", ":")).encode()
    )

    assert parsed.database_alias == "default"
    assert parsed.renewal.actor_capture.source_id == "actor:fresh"
    assert parsed.renewal.owner_successor.authority_version == "v3.2"
    assert parsed.renewal.minimum_window.total_seconds() == 2100
    assert parsed.principal.valid_until == datetime(2026, 9, 23, 12, tzinfo=UTC)
    assert parsed.profile.expected_active_profile_version is None


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.pop("profile"),
        lambda value: value["profile"].update({"unexpected": "field"}),
        lambda value: value["actor_capture"].update({"user_id": True}),
        lambda value: value["principal"].update({"valid_until": "2026-09-23T12:00:00"}),
    ],
)
def test_renewal_request_parser_rejects_noncanonical_or_unaware_input(mutator) -> None:
    value = _request()
    mutator(value)

    with pytest.raises(ValueError):
        parse_system_audit_authority_renewal_request(
            json.dumps(value, separators=(",", ":")).encode()
        )


def test_renewal_request_parser_rejects_duplicate_json_keys() -> None:
    payload = json.dumps(_request(), separators=(",", ":"))
    duplicate = payload[:-1] + ',"database_alias":"default"}'

    with pytest.raises(ValueError):
        parse_system_audit_authority_renewal_request(duplicate.encode())


class _RejectingCapture:
    """Return an untrusted value to prove the application boundary is closed."""

    def execute(self, command):
        del command
        return object()


class _UnexpectedOwnerFactory:
    """Fail the test if an invalid actor reaches the owner writer."""

    def build(self, actor):
        del actor
        raise AssertionError("owner writer must not run after actor type rejection")


def test_renewal_service_rejects_substituted_actor_before_owner_write() -> None:
    parsed = parse_system_audit_authority_renewal_request(
        json.dumps(_request(), separators=(",", ":")).encode()
    )
    renewal = RenewSystemAuditAuthority(
        actor_capture=_RejectingCapture(),
        owner_factory=_UnexpectedOwnerFactory(),
        clock=lambda: datetime(2026, 9, 23, 7, tzinfo=UTC),
    )

    with pytest.raises(SystemAuditAuthorityRenewalUnavailable) as error:
        renewal.execute(parsed.renewal)
    assert error.value.reason_code == "actor_capture_type_invalid"
