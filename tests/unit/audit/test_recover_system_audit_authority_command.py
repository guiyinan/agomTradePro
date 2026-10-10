"""Read-only identity preflight contract for System Audit authority recovery."""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

import apps.audit.management.commands.recover_system_audit_authority as recovery_command


def _recovery_request() -> dict[str, object]:
    digest = "a" * 64
    return {
        "renewal": {
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
                "expected_active_profile_id": "profile:active",
                "expected_active_profile_version": 1,
                "expected_active_profile_hash": digest,
                "expected_active_snapshot_hash": digest,
            },
        },
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


_PREDECESSOR = SimpleNamespace(
    evidence_id="evidence:audit",
    subject=SimpleNamespace(receipt=SimpleNamespace(receipt_id="receipt:audit")),
)


class _ExactEvidenceReader:
    """Return the selected predecessor without opening a database connection."""

    def __init__(self, repository: object) -> None:
        del repository

    def execute(self, command: object) -> object:
        del command
        return _PREDECESSOR


class _IdentityReader:
    """Return one configured exact winner from a read-only repository port."""

    def __init__(self, winner: object | None, head: object | None = None) -> None:
        self._winner = winner
        self._head = head

    def get_winner(self, **selectors: object) -> object | None:
        del selectors
        return self._winner

    def get_head(self, **selectors: object) -> object | None:
        del selectors
        return self._head


def _install_readers(
    monkeypatch: pytest.MonkeyPatch,
    *,
    receipt: object | None = None,
    subject: object | None = None,
    evidence: object | None = None,
    authority: object | None = None,
    authority_head: object | None = None,
) -> None:
    monkeypatch.setattr(
        recovery_command, "GetExactAccountOwnerAssignmentEvidenceV5", _ExactEvidenceReader
    )
    monkeypatch.setattr(
        recovery_command,
        "DjangoAccountOwnerAssignmentEvidenceV5Repository",
        lambda **_kwargs: _IdentityReader(evidence),
    )
    monkeypatch.setattr(
        recovery_command,
        "DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository",
        lambda **_kwargs: _IdentityReader(receipt),
    )
    monkeypatch.setattr(
        recovery_command,
        "DjangoAccountOwnerAssignmentSubjectV5Repository",
        lambda **_kwargs: _IdentityReader(subject),
    )
    monkeypatch.setattr(
        recovery_command,
        "DjangoOwnerTenantAuthorityV3Repository",
        lambda **_kwargs: _IdentityReader(authority, authority_head),
    )


@pytest.mark.parametrize(
    ("occupied", "authority_head", "expected"),
    [
        ((False, False, False, False), None, None),
        ((True, True, True, True), object(), "recovery_envelope_consumed"),
        ((True, False, False, False), None, "recovery_identity_conflict"),
        ((False, True, False, False), None, "recovery_identity_conflict"),
        ((False, False, False, False), object(), "recovery_identity_conflict"),
    ],
)
def test_preflight_classifies_consumed_and_conflicting_identities(
    monkeypatch: pytest.MonkeyPatch,
    occupied: tuple[bool, bool, bool, bool],
    authority_head: object | None,
    expected: str | None,
) -> None:
    request = recovery_command.parse_system_audit_authority_recovery_request(
        json.dumps(_recovery_request(), separators=(",", ":")).encode()
    )
    receipt, subject, evidence, authority = (object() if value else None for value in occupied)
    _install_readers(
        monkeypatch,
        receipt=receipt,
        subject=subject,
        evidence=evidence,
        authority=authority,
        authority_head=authority_head,
    )

    result = recovery_command._preflight_recovery(request)

    assert result.predecessor is _PREDECESSOR
    assert result.block_reason_code == expected


@pytest.mark.parametrize(
    ("execute", "occupied", "expected_code"),
    [
        (False, (True, True, True, True), "recovery_envelope_consumed"),
        (True, (True, True, True, True), "recovery_envelope_consumed"),
        (False, (True, False, False, False), "recovery_identity_conflict"),
        (True, (True, False, False, False), "recovery_identity_conflict"),
        (False, (False, True, False, False), "recovery_identity_conflict"),
        (True, (False, True, False, False), "recovery_identity_conflict"),
    ],
)
def test_occupied_identity_blocks_before_actor_capture_and_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    execute: bool,
    occupied: tuple[bool, bool, bool, bool],
    expected_code: str,
) -> None:
    request_path = tmp_path / "recovery.json"
    request_path.write_text(json.dumps(_recovery_request()), encoding="utf-8")
    receipt, subject, evidence, authority = (object() if value else None for value in occupied)
    _install_readers(
        monkeypatch,
        receipt=receipt,
        subject=subject,
        evidence=evidence,
        authority=authority,
    )
    monkeypatch.setattr(recovery_command.transaction, "atomic", lambda **_kwargs: nullcontext())

    actor_captures: list[str] = []
    writes: list[str] = []

    def capture_actor(**_kwargs: object) -> None:
        actor_captures.append("capture")
        raise AssertionError("preflight blocker must prevent actor capture")

    def write_attempt(name: str):
        def fail_if_called(*_args: object, **_kwargs: object) -> None:
            writes.append(name)
            raise AssertionError(f"preflight blocker must prevent {name}")

        return fail_if_called

    monkeypatch.setattr(recovery_command, "build_account_actor_authority_capture", capture_actor)
    monkeypatch.setattr(
        recovery_command,
        "IssueAccountOwnerAssignmentProvenanceReceiptV5",
        write_attempt("receipt"),
    )
    monkeypatch.setattr(
        recovery_command,
        "RegisterAccountOwnerAssignmentSubjectV5",
        write_attempt("subject"),
    )
    monkeypatch.setattr(
        recovery_command,
        "build_account_owner_assignment_evidence_v5_facade",
        write_attempt("evidence"),
    )
    monkeypatch.setattr(
        recovery_command,
        "build_owner_tenant_authority_v3_facade",
        write_attempt("authority"),
    )
    monkeypatch.setattr(recovery_command, "_activate_runtime_successor", write_attempt("profile"))
    outputs: list[dict[str, object]] = []
    command = recovery_command.Command()
    monkeypatch.setattr(command, "_write", outputs.append)

    command.handle(input=str(request_path), execute=execute)

    assert outputs == [
        {
            "outcome": "blocked",
            "mode": "execute" if execute else "dry_run",
            "authority_persisted": False,
            "runtime_enabled": False,
            "block_reason_code": expected_code,
        }
    ]
    assert actor_captures == []
    assert writes == []


def test_available_dry_run_confirms_preflight_without_capture_or_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "recovery.json"
    request_path.write_text(json.dumps(_recovery_request()), encoding="utf-8")
    _install_readers(monkeypatch)
    actor_captures: list[str] = []
    monkeypatch.setattr(
        recovery_command,
        "build_account_actor_authority_capture",
        lambda **_kwargs: actor_captures.append("capture"),
    )
    outputs: list[dict[str, object]] = []
    command = recovery_command.Command()
    monkeypatch.setattr(command, "_write", outputs.append)

    command.handle(input=str(request_path), execute=False)

    assert outputs[0]["outcome"] == "noop"
    assert outputs[0]["reason"] == "request_and_identity_slots_validated"
    assert actor_captures == []


def test_available_execute_passes_preflight_predecessor_to_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "recovery.json"
    request_path.write_text(json.dumps(_recovery_request()), encoding="utf-8")
    _install_readers(monkeypatch)
    monkeypatch.setattr(recovery_command.transaction, "atomic", lambda **_kwargs: nullcontext())
    calls: list[tuple[object, object]] = []

    def execute_recovery(request: object, predecessor: object) -> dict[str, object]:
        calls.append((request, predecessor))
        return {"authority_persisted": True, "runtime_enabled": True}

    monkeypatch.setattr(recovery_command, "_execute_recovery", execute_recovery)
    outputs: list[dict[str, object]] = []
    command = recovery_command.Command()
    monkeypatch.setattr(command, "_write", outputs.append)

    command.handle(input=str(request_path), execute=True)

    assert outputs == [
        {
            "outcome": "success",
            "mode": "execute",
            "authority_persisted": True,
            "runtime_enabled": True,
        }
    ]
    assert len(calls) == 1
    assert calls[0][1] is _PREDECESSOR
