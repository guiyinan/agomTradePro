from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import apps.audit.management.commands.renew_system_audit_authority as renewal_command
from apps.audit.application.system_audit_authority_renewal import (
    RenewSystemAuditAuthority,
    SystemAuditAuthorityRenewalUnavailable,
)
from apps.audit.infrastructure.system_audit_authority_recovery_request import (
    parse_system_audit_authority_recovery_request,
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


def _recovery_request() -> dict[str, object]:
    return {
        "renewal": _request(),
        "assignment_recovery": {
            "assignment_validity_seconds": 7200,
            "receipt_version": "v5.2",
            "subject_id": "subject:audit:recovery",
            "subject_version": "v5.2",
            "evidence_version": "v5.2",
            "authority_id": "authority:audit:recovery",
            "authority_version": "v3.1",
        },
    }


def test_recovery_request_parser_binds_successor_identities_to_renewal_input() -> None:
    parsed = parse_system_audit_authority_recovery_request(
        json.dumps(_recovery_request(), separators=(",", ":")).encode()
    )

    assert parsed.renewal.renewal.owner_successor.assignment_evidence_id == "evidence:audit"
    assert parsed.assignment_validity_period.total_seconds() == 7200
    assert parsed.receipt_version == "v5.2"
    assert parsed.evidence_version == "v5.2"
    assert parsed.authority_id == "authority:audit:recovery"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value["assignment_recovery"].update({"unexpected": "field"}),
        lambda value: value["assignment_recovery"].update({"assignment_validity_seconds": True}),
        lambda value: value["assignment_recovery"].update(
            {"authority_id": " authority:audit:recovery"}
        ),
    ],
)
def test_recovery_request_parser_rejects_noncanonical_input(mutator) -> None:
    value = _recovery_request()
    mutator(value)

    with pytest.raises(ValueError):
        parse_system_audit_authority_recovery_request(
            json.dumps(value, separators=(",", ":")).encode()
        )


def test_recovery_request_parser_rejects_duplicate_json_keys() -> None:
    payload = json.dumps(_recovery_request(), separators=(",", ":"))
    duplicate = payload[:-1] + ',"renewal":{}}'

    with pytest.raises(ValueError):
        parse_system_audit_authority_recovery_request(duplicate.encode())


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


def _bound_request() -> dict[str, object]:
    value = _request()
    profile = value["profile"]
    assert type(profile) is dict
    digest = "a" * 64
    profile.update(
        {
            "expected_active_profile_id": "profile:active",
            "expected_active_profile_version": 1,
            "expected_active_profile_hash": digest,
            "expected_active_snapshot_hash": digest,
        }
    )
    return value


class _AuthorityIdentityReader:
    """Expose the existing Authority V3 exact-winner and head read contract."""

    def __init__(self, winner: object | None, head: object | None) -> None:
        self._winner = winner
        self._head = head

    def get_winner(self, **selectors: object) -> object | None:
        del selectors
        return self._winner

    def get_head(self, **selectors: object) -> object | None:
        del selectors
        return self._head


def _install_authority_reader(
    monkeypatch: pytest.MonkeyPatch,
    *,
    winner: object | None = None,
    head: object | None = None,
) -> None:
    monkeypatch.setattr(
        renewal_command,
        "DjangoOwnerTenantAuthorityV3Repository",
        lambda **_kwargs: _AuthorityIdentityReader(winner, head),
    )


@pytest.mark.parametrize(
    ("winner", "head", "expected"),
    [
        (object(), None, "authority_renewal_envelope_consumed"),
        (
            None,
            SimpleNamespace(
                authority=SimpleNamespace(authority_version="v3.1", content_hash="a" * 64)
            ),
            None,
        ),
        (
            None,
            SimpleNamespace(
                authority=SimpleNamespace(authority_version="v3.0", content_hash="a" * 64)
            ),
            "authority_renewal_predecessor_changed",
        ),
        (None, None, "authority_renewal_predecessor_changed"),
    ],
)
def test_renewal_preflight_checks_exact_successor_and_expected_predecessor(
    monkeypatch: pytest.MonkeyPatch,
    winner: object | None,
    head: object | None,
    expected: str | None,
) -> None:
    request = parse_system_audit_authority_renewal_request(
        json.dumps(_request(), separators=(",", ":")).encode()
    )
    _install_authority_reader(monkeypatch, winner=winner, head=head)

    result = renewal_command._preflight_renewal(request)

    assert result.block_reason_code == expected


@pytest.mark.parametrize("execute", [False, True])
def test_consumed_renewal_envelope_blocks_before_actor_capture_or_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    execute: bool,
) -> None:
    request_path = tmp_path / "renewal.json"
    request_path.write_text(json.dumps(_bound_request()), encoding="utf-8")
    _install_authority_reader(monkeypatch, winner=object())
    monkeypatch.setattr(renewal_command.transaction, "atomic", lambda **_kwargs: nullcontext())
    actor_captures: list[str] = []

    def fail_if_captured(**_kwargs: object) -> None:
        actor_captures.append("capture")
        raise AssertionError("consumed renewal envelope must block before actor capture")

    monkeypatch.setattr(
        renewal_command,
        "build_account_actor_authority_capture",
        fail_if_captured,
    )
    outputs: list[dict[str, object]] = []
    command = renewal_command.Command()
    monkeypatch.setattr(command, "_write", outputs.append)

    command.handle(input=str(request_path), execute=execute)

    assert outputs[0]["outcome"] == "blocked"
    assert outputs[0]["mode"] == ("execute" if execute else "dry_run")
    assert outputs[0]["block_reason_code"] == "authority_renewal_envelope_consumed"
    assert actor_captures == []
