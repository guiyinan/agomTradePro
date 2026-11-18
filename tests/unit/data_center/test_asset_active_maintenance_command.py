"""Input and authentication contracts for exact AssetMaster maintenance."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import nullcontext
from dataclasses import fields as dataclass_fields
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from django.core.management.base import CommandError

from apps.audit.domain.system_audit_event import AuditResourceRef, SystemAuditEvent
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.data_center.application.asset_active_maintenance import AssetActiveMaintenanceError
from apps.data_center.domain.asset_active_maintenance import (
    AssetActiveMaintenanceContractError,
    MaintenanceOwner,
)
from apps.data_center.infrastructure import asset_active_maintenance as repository_module
from apps.data_center.infrastructure.asset_active_maintenance_plan import decode_plan
from apps.data_center.management.commands import maintain_asset_active_scope as command
from core.integration import asset_active_maintenance_audit as audit_module
from core.integration import asset_active_maintenance_composition as composition
from core.integration.data_center_audit import SystemAuditReaderContext
from tests.unit.data_center.test_asset_active_maintenance import _plan, _use_case


def _raw() -> bytes:
    return json.dumps(_plan().to_file_payload(), separators=(",", ":")).encode("utf-8")


def _decode(raw: bytes) -> object:
    return decode_plan(raw, expected_sha256=hashlib.sha256(raw).hexdigest())


def test_plan_binds_actual_file_bytes_without_self_hash() -> None:
    raw = _raw()
    plan = decode_plan(raw, expected_sha256=hashlib.sha256(raw).hexdigest())
    assert plan == replace(_plan(), plan_file_sha256=hashlib.sha256(raw).hexdigest())
    assert b"plan_file_sha256" not in raw
    assert plan.to_payload()["plan_file_sha256"] == hashlib.sha256(raw).hexdigest()


def test_plan_tampering_is_blocked_by_external_file_hash() -> None:
    raw = _raw()
    with pytest.raises(AssetActiveMaintenanceContractError, match="plan_file_hash_mismatch"):
        decode_plan(raw + b" ", expected_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw.replace(b'"schema":', b'"schema":"duplicated","schema":', 1),
        lambda raw: raw[:-1] + b',"plan_file_sha256":"' + b"a" * 64 + b'"}',
        lambda raw: raw.replace(b'"asset_pk":1', b'"asset_pk":true', 1),
        lambda raw: raw.replace(b'"raw_audit_version":"1"', b'"raw_audit_version":null', 1),
        lambda raw: raw.replace(b'"expected_delist_date":null', b'"expected_delist_date":""', 1),
    ],
)
def test_ambiguous_plan_json_is_rejected(mutation: object) -> None:
    from collections.abc import Callable
    from typing import cast

    raw = cast(Callable[[bytes], bytes], mutation)(_raw())
    assert raw != _raw(), "test mutation must affect the real fixture"
    with pytest.raises(AssetActiveMaintenanceContractError):
        _decode(raw)


def test_plan_rejects_contract_hash_mismatch() -> None:
    payload = json.loads(_raw())
    payload["provider_contract"]["content_hash"] = "0" * 64
    with pytest.raises(
        AssetActiveMaintenanceContractError, match="provider_contract_hash_mismatch"
    ):
        _decode(json.dumps(payload).encode("utf-8"))


def test_private_pipe_password_is_read_exactly_and_closed() -> None:
    reader, writer = os.pipe()
    os.write(writer, "Owner秘密\n".encode())
    os.close(writer)
    assert command._read_password(reader) == "Owner秘密\n"
    with pytest.raises(OSError):
        os.fstat(reader)


@pytest.mark.parametrize("descriptor", [0, 1, 2, -1, True, None])
def test_password_rejects_stdio_and_bad_descriptors(descriptor: object) -> None:
    with pytest.raises(CommandError, match="private password FD"):
        command._read_password(descriptor)


def test_password_rejects_a_regular_file(tmp_path: Path) -> None:
    path = tmp_path / "not-a-password-input"
    path.write_text("must not authenticate", encoding="utf-8")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        with pytest.raises(CommandError, match="pipe or socket"):
            command._read_password(descriptor)
    finally:
        os.close(descriptor)


def test_failed_authentication_does_not_construct_or_execute_use_case(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reached: list[bool] = []
    monkeypatch.setattr(command, "authenticate", lambda **kwargs: None)
    monkeypatch.setattr(
        command, "create_asset_active_maintenance_use_case", lambda **kwargs: reached.append(True)
    )
    reader, writer = os.pipe()
    os.write(writer, b"incorrect-password")
    os.close(writer)
    with pytest.raises(CommandError, match="authentication failed"):
        command.Command().handle(
            owner="real-owner",
            password_fd=reader,
            plan_file=str(tmp_path / "never-read.json"),
            plan_sha256="a" * 64,
        )
    assert reached == []


def test_plan_file_is_bounded_and_regular(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    path.write_bytes(_raw())
    assert command._read_plan(path) == _raw()
    path.write_bytes(b"x" * (64 * 1024 + 1))
    with pytest.raises(CommandError, match="plan file invalid"):
        command._read_plan(path)


def _issued_context(content_hash: str, at: datetime) -> SystemAuditReaderContext:
    return SystemAuditReaderContext._from_authority(
        authority_source_id="test-authority",
        authority_source_version="v1",
        actor_id="django-user:1",
        user_id=1,
        tenant_id="test-tenant",
        owner_id="test-owner",
        authority_content_hash=content_hash,
        is_authenticated=True,
        is_staff=True,
        role="staff",
        authority_state="active",
        authority_recorded_at=at - timedelta(hours=1),
        authority_valid_until=at + timedelta(hours=1),
    )


def test_maintenance_rechecks_fresh_authority_hash_instead_of_cached_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
    starting = _issued_context("a" * 64, at)
    current = [starting]
    monkeypatch.setattr(
        composition, "preflight_data02_task_authority", lambda **kwargs: (current[0], None)
    )
    owner = MaintenanceOwner(1, "owner", "django-user:1", True, True, True)
    port = composition.DjangoAssetMaintenanceAuthorityPort()
    bound = port.current_context(owner, as_of=at)
    assert port.is_current(bound, as_of=at)
    current[0] = _issued_context("b" * 64, at)
    assert not port.is_current(bound, as_of=at)
    current[0] = starting
    assert port.is_current(bound, as_of=at)


@pytest.mark.parametrize("level", ["repeatable read", "serializable", "read uncommitted"])
def test_other_isolation_blocks_before_schema_read_or_asset_lock(
    monkeypatch: pytest.MonkeyPatch,
    level: str,
) -> None:
    statements: list[str] = []

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def execute(self, sql: str) -> None:
            statements.append(sql)

        def fetchone(self) -> tuple[str]:
            return (level,)

    connection = SimpleNamespace(
        vendor="postgresql",
        in_atomic_block=True,
        atomic_blocks=[object()],
        get_autocommit=lambda: False,
        cursor=Cursor,
    )
    monkeypatch.setattr(repository_module, "connections", {"default": connection})
    repository = repository_module.DjangoAssetMasterMaintenanceRepository()
    with pytest.raises(
        AssetActiveMaintenanceContractError, match="read_committed_isolation_required"
    ):
        repository.lock_exact_targets(_plan().targets)
    assert statements == ["SHOW transaction_isolation"]


def _event_fixture() -> tuple[object, object, SystemAuditEvent]:
    plan = _plan()
    service, _, _, audit = _use_case()
    service.execute(plan, expected_plan_file_sha256=plan.plan_file_sha256)
    observation = audit.observations[0]
    event = audit_module._event_from_observation(
        observation,
        event_id=audit_module._event_id(plan.digest),
        stream_id=audit_module._stream_id(plan.digest),
        scope=audit_module.AuditScopeRef(
            tenant_id=observation.authority.tenant_id,
            owner_id=observation.authority.owner_id,
        ),
    )
    return service, audit, event


def _rehash(event: SystemAuditEvent, **changes: object) -> SystemAuditEvent:
    kwargs = {
        field.name: getattr(event, field.name)
        for field in dataclass_fields(event)
        if field.name not in {"identity_hash", "content_hash"}
    }
    kwargs.update(changes)
    return SystemAuditEvent.create(**kwargs)


def test_real_audit_mapping_roundtrip_keeps_exact_plan_metadata() -> None:
    _, _, event = _event_fixture()
    receipt = audit_module._receipt_from_pair(event, UUID(int=1))
    assert receipt.plan_metadata.target_date == _plan().target_date
    assert receipt.plan_metadata.provider_contract_id == _plan().provider_contract.contract_id
    assert receipt.plan_metadata.actor_username == "real-owner"
    assert event.correlations.run_id is None


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("target_date", "2026-11-16"),
        ("provider_contract_id", "other-contract"),
        ("provider_contract_version", "other-version"),
        ("crosswalk_id", "other-crosswalk"),
        ("crosswalk_version", "other-version"),
    ],
)
def test_valid_hash_audit_with_wrong_plan_metadata_cannot_authorize_noop(
    field: str,
    wrong: str,
) -> None:
    service, audit, event = _event_fixture()
    detail = dict(event.detail)
    detail[field] = wrong
    substituted = _rehash(event, detail=detail)
    substituted.validate_hashes()
    audit.receipt = audit_module._receipt_from_pair(substituted, UUID(int=1))
    plan = _plan()
    with pytest.raises(AssetActiveMaintenanceError, match="maintenance_audit_replay_mismatch"):
        service.execute(plan, expected_plan_file_sha256=plan.plan_file_sha256)


@pytest.mark.parametrize("field", ["reason_codes", "correlations", "resource", "publication_id"])
def test_valid_hash_wrong_audit_envelope_is_rejected(field: str) -> None:
    _, _, event = _event_fixture()
    replacements = {
        "reason_codes": ("other_operation",),
        "correlations": replace(event.correlations, run_id="unreal-plan-run"),
        "resource": AuditResourceRef(
            resource_type="other.resource",
            resource_id=_plan().digest,
            resource_version=_plan().plan_file_sha256,
        ),
        "publication_id": "unrelated-publication",
    }
    substituted = _rehash(event, **{field: replacements[field]})
    substituted.validate_hashes()
    with pytest.raises(AssetActiveMaintenanceContractError):
        audit_module._receipt_from_pair(substituted, UUID(int=1))


@pytest.mark.parametrize("existing", [True, False])
def test_record_once_rejects_canonical_but_substituted_persisted_event(existing: bool) -> None:
    _, audit, event = _event_fixture()
    wrong_detail = dict(event.detail)
    wrong_detail["target_date"] = "2026-11-16"
    substituted = _rehash(event, detail=wrong_detail)

    class Coordinator(DjangoSystemAuditEventOutboxCoordinator):
        def __init__(self) -> None:
            self._using = "default"

        def caller_owned_atomic(self) -> object:
            return nullcontext()

        def lock_stream(self, stream_id: str) -> None:
            pass

        def get_winner_targeted(self, **kwargs: object) -> SystemAuditEvent | None:
            return substituted if existing else None

        def get_current_head_targeted(self, **kwargs: object) -> None:
            return None

        def append_and_enqueue(self, *args: object, **kwargs: object) -> object:
            return SimpleNamespace(event=substituted)

    adapter = audit_module.DjangoAssetMaintenanceSystemAuditAdapter(coordinator=Coordinator())
    expected = (
        "system_audit_idempotency_conflict" if existing else "system_audit_event_readback_mismatch"
    )
    with pytest.raises(AssetActiveMaintenanceContractError, match=expected):
        adapter.record_once(audit.observations[0])
