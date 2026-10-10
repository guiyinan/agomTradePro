"""Fail-closed tests for database capacity approvals and deployed build identity."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, override_settings

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityBinding,
    FinancialCapacityWorkflowError,
)
from apps.data_center.application.financial_capacity_governance import (
    parse_financial_capacity_governance_record,
)
from apps.data_center.infrastructure.financial_capacity_build_identity import (
    FileFinancialCapacityBuildIdentitySource,
)
from apps.data_center.infrastructure.financial_capacity_governance import (
    DjangoFinancialCapacityGovernanceSource,
)
from apps.data_center.infrastructure.financial_publication_capacity_runtime import (
    DjangoFinancialCapacityBindingSource,
)
from apps.data_center.infrastructure.models import (
    FinancialCapacityGovernanceRecordModel,
    FinancialCapacityGovernanceRevocationModel,
    FinancialCapacityOwnerApprovalEventModel,
)
from apps.data_center.interface.admin import (
    FinancialCapacityGovernanceRecordAdmin,
    FinancialCapacityGovernanceRecordAdminForm,
)


def _binding(environment: str = "isolated") -> FinancialCapacityBinding:
    """Return one exact synthetic AKShare policy-v3 identity for gate tests."""

    return FinancialCapacityBinding(
        environment=environment,
        candidate_sha="a" * 40,
        provider_id=17,
        provider_name="AKShare Public",
        provider_source="akshare",
        provider_identity_sha256="b" * 64,
        contract_id="akshare.notice-date",
        contract_version="v1",
        contract_sha256="c" * 64,
        parser_id="financial.parser.v1",
        parser_sha256="d" * 64,
        deployment_region="isolated-east",
        publication_policy_version="3",
        publication_policy_sha256="e" * 64,
        isolation_attestation_sha256="f" * 64 if environment == "isolated" else "",
    )


def _payload(binding: FinancialCapacityBinding, *, production: bool = False) -> dict[str, object]:
    """Build a pre-reviewed record-shaped payload without creating a governance row."""

    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "approval_id": "review:financial-capacity:unit-test",
        "approved_by": "owner:financial-data",
        "approved_at": (now - timedelta(days=1)).isoformat(),
        "approval_receipt_sha256": "6" * 64,
        "binding": binding.to_dict(),
        "manifest_sha256": "1" * 64,
        "maximum_slices": 1,
        "maximum_provider_requests": 2,
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "approved": True,
    }
    if production:
        payload["receipt_sha256"] = "2" * 64
    return payload


@pytest.mark.parametrize(
    "field",
    ("approved_by", "approved_at", "approval_receipt_sha256"),
)
def test_capacity_record_requires_every_approval_evidence_field(field: str) -> None:
    """Missing owner approval evidence is rejected instead of inferred from the recorder."""

    payload = _payload(_binding())
    payload.pop(field)

    with pytest.raises(FinancialCapacityWorkflowError, match="shape is invalid"):
        parse_financial_capacity_governance_record(stage="qualification", record=payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("approved_by", "", "approved_by"),
        ("approved_at", "2026-10-08T12:00:00+08:00", "UTC-aware"),
        ("approved_at", "2026-10-08T00:00:00", "include UTC"),
        ("approval_receipt_sha256", "6" * 63, "SHA-256"),
    ),
)
def test_capacity_record_rejects_invalid_approval_evidence(
    field: str,
    value: str,
    message: str,
) -> None:
    """Owner identity, UTC timestamp, and evidence digest are strongly typed."""

    payload = _payload(_binding())
    payload[field] = value

    with pytest.raises(FinancialCapacityWorkflowError, match=message):
        parse_financial_capacity_governance_record(stage="qualification", record=payload)


@pytest.mark.parametrize("production", (False, True))
def test_capacity_record_rejects_approval_after_expiry(production: bool) -> None:
    """Neither approval schema can describe an approval issued after its expiry."""

    stage = "production" if production else "qualification"
    environment = "production" if production else "isolated"
    payload = _payload(_binding(environment), production=production)
    expires_at = datetime.fromisoformat(str(payload["expires_at"]))
    payload["approved_at"] = (expires_at + timedelta(seconds=1)).isoformat()

    with pytest.raises(FinancialCapacityWorkflowError, match="must not be later than expiry"):
        parse_financial_capacity_governance_record(stage=stage, record=payload)


def _write_build_identity(path: Path, source_commit: str) -> None:
    """Write one build identity fixture using the deployed artifact schema."""

    path.write_text(
        '{"schema_version":1,"app_version":"0.7.9","source_commit":"' + source_commit + '"}',
        encoding="utf-8",
    )


def _create_approval_record_with_owner_event(
    *,
    stage: str,
    payload: dict[str, object],
) -> FinancialCapacityGovernanceRecordModel:
    """Create a test-only stand-in for an independent authenticated owner event."""

    approval_id = str(payload["approval_id"])
    record = FinancialCapacityGovernanceRecordModel._default_manager.create(
        approval_id=approval_id,
        stage=stage,
        record=payload,
        created_by="governance-recorder",
    )
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    approved_at = datetime.fromisoformat(str(payload["approved_at"]))
    FinancialCapacityOwnerApprovalEventModel._default_manager.create(
        governance_record=record,
        event_id=f"owner-event:{approval_id}",
        approved_by=str(payload["approved_by"]),
        approved_at=approved_at,
        approval_receipt_sha256=str(payload["approval_receipt_sha256"]),
        record_sha256=hashlib.sha256(canonical).hexdigest(),
    )
    return record


def test_build_identity_source_reads_exact_source_commit(tmp_path: Path) -> None:
    """The file port returns the immutable commit recorded by the built image."""

    identity_path = tmp_path / ".agom-build-identity.json"
    _write_build_identity(identity_path, "a" * 40)

    assert FileFinancialCapacityBuildIdentitySource(identity_path).source_commit() == "a" * 40


@pytest.mark.parametrize("contents", ["{}", "not-json", '{"source_commit":"bad"}'])
def test_build_identity_source_fails_closed_on_missing_or_invalid_identity(
    tmp_path: Path,
    contents: str,
) -> None:
    """Absent or malformed image identity cannot be replaced by a caller SHA."""

    identity_path = tmp_path / ".agom-build-identity.json"
    identity_path.write_text(contents, encoding="utf-8")

    with pytest.raises(FinancialCapacityWorkflowError):
        FileFinancialCapacityBuildIdentitySource(identity_path).source_commit()


def test_binding_source_rejects_candidate_that_differs_from_runtime_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revision drift blocks before provider or policy configuration is queried."""

    source = DjangoFinancialCapacityBindingSource(
        build_identity_source=SimpleNamespace(source_commit=lambda: "b" * 40)
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.financial_publication_capacity_runtime.get_provider_config_repository",
        lambda: pytest.fail("provider repository must not be read after build identity drift"),
    )

    with pytest.raises(FinancialCapacityWorkflowError, match="runtime build identity"):
        source.snapshot(environment="isolated", candidate_sha="a" * 40)


@pytest.mark.django_db
def test_governance_source_defaults_to_no_approval() -> None:
    """A deployed database with no independently recorded ceiling remains blocked."""

    assert FinancialCapacityGovernanceRecordModel._default_manager.count() == 0
    source = DjangoFinancialCapacityGovernanceSource()

    assert source.get_qualification(binding=_binding(), manifest_sha256="1" * 64) is None
    assert (
        source.get(
            receipt_sha256="2" * 64,
            candidate_sha="a" * 40,
            manifest_sha256="1" * 64,
        )
        is None
    )


@pytest.mark.django_db
def test_governance_source_returns_only_exact_database_record() -> None:
    """Stored reviewed scope must match every binding field before it can be used."""

    binding = _binding()
    payload = _payload(binding)
    _create_approval_record_with_owner_event(
        stage="qualification",
        payload=payload,
    )
    source = DjangoFinancialCapacityGovernanceSource()

    assert source.get_qualification(binding=binding, manifest_sha256="1" * 64) is not None
    assert (
        source.get_qualification(
            binding=_binding(environment="production"), manifest_sha256="1" * 64
        )
        is None
    )
    assert source.get_qualification(binding=binding, manifest_sha256="3" * 64) is None


@pytest.mark.django_db
def test_governance_source_fails_closed_when_exact_approval_is_ambiguous() -> None:
    """Two independently entered active approvals for one exact scope are ambiguous."""

    binding = _binding()
    for approval_id in (
        "review:financial-capacity:ambiguous-a",
        "review:financial-capacity:ambiguous-b",
    ):
        payload = _payload(binding)
        payload["approval_id"] = approval_id
        _create_approval_record_with_owner_event(
            stage="qualification",
            payload=payload,
        )

    assert (
        DjangoFinancialCapacityGovernanceSource().get_qualification(
            binding=binding, manifest_sha256="1" * 64
        )
        is None
    )


@pytest.mark.django_db
def test_governance_source_returns_only_receipt_bound_production_record() -> None:
    """The production record must match receipt, candidate, and frozen manifest."""

    binding = _binding(environment="production")
    payload = _payload(binding, production=True)
    _create_approval_record_with_owner_event(
        stage="production",
        payload=payload,
    )
    source = DjangoFinancialCapacityGovernanceSource()

    assert (
        source.get(
            receipt_sha256="2" * 64,
            candidate_sha="a" * 40,
            manifest_sha256="1" * 64,
        )
        is not None
    )
    assert (
        source.get(
            receipt_sha256="3" * 64,
            candidate_sha="a" * 40,
            manifest_sha256="1" * 64,
        )
        is None
    )


@pytest.mark.django_db
def test_owner_event_must_match_exact_payload_hash_and_owner_identity() -> None:
    """An event for another owner or changed payload cannot authorize a ceiling."""

    binding = _binding()
    payload = _payload(binding)
    record = _create_approval_record_with_owner_event(
        stage="qualification",
        payload=payload,
    )
    source = DjangoFinancialCapacityGovernanceSource()
    assert source.get_qualification(binding=binding, manifest_sha256="1" * 64) is not None

    event = FinancialCapacityOwnerApprovalEventModel._default_manager.get(governance_record=record)
    event.approved_by = "another-owner"
    event.save(update_fields=["approved_by"])
    assert source.get_qualification(binding=binding, manifest_sha256="1" * 64) is None
    assert (
        source.get(
            receipt_sha256="2" * 64,
            candidate_sha="4" * 40,
            manifest_sha256="1" * 64,
        )
        is None
    )


def test_governance_admin_forbids_add_and_limits_view_or_revoke_to_superusers() -> None:
    """Only the build-bound command can append; superusers may inspect or revoke."""

    model_admin = FinancialCapacityGovernanceRecordAdmin(
        FinancialCapacityGovernanceRecordModel,
        AdminSite(),
    )
    request = RequestFactory().get("/admin/")
    request.user = SimpleNamespace(is_authenticated=True, is_superuser=False, is_staff=True)
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_module_permission(request)
    assert not model_admin.has_view_permission(request)
    assert not model_admin.has_change_permission(request)
    request.user = SimpleNamespace(is_authenticated=True, is_superuser=True, is_staff=True)
    assert not model_admin.has_add_permission(request)
    assert model_admin.has_module_permission(request)
    assert model_admin.has_view_permission(request)
    assert not model_admin.has_change_permission(request)
    assert not model_admin.has_delete_permission(request)
    with pytest.raises(PermissionDenied, match="immutable"):
        model_admin.save_model(
            request,
            FinancialCapacityGovernanceRecordModel(),
            cast(FinancialCapacityGovernanceRecordAdminForm, None),
            False,
        )


@pytest.mark.django_db
def test_append_command_records_only_external_superuser_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The command appends the supplied approved payload and does not generate one."""

    user_model = get_user_model()
    username_field = user_model.USERNAME_FIELD
    superuser = user_model._default_manager.create_user(
        **{username_field: "capacity-reviewer"},
        password="test-password",
        is_superuser=True,
    )
    payload = _payload(_binding())
    approval_path = tmp_path / "reviewed-ceiling.json"
    approval_path.write_text(json.dumps(payload), encoding="utf-8")
    identity_path = tmp_path / ".agom-build-identity.json"
    _write_build_identity(identity_path, "a" * 40)
    monkeypatch.setattr(
        "apps.data_center.management.commands.record_financial_capacity_governance.getpass",
        lambda _prompt: "test-password",
    )

    with override_settings(AGOM_BUILD_IDENTITY_PATH=identity_path):
        call_command(
            "record_financial_capacity_governance",
            record_file=approval_path,
            stage="qualification",
            actor=superuser.get_username(),
        )

    record = FinancialCapacityGovernanceRecordModel._default_manager.get(
        approval_id=payload["approval_id"]
    )
    assert record.record == payload
    assert record.stage == "qualification"
    assert record.created_by == superuser.get_username()
    assert record.record["approved_by"] != record.created_by
    assert not FinancialCapacityOwnerApprovalEventModel._default_manager.filter(
        governance_record=record
    ).exists()
    assert (
        DjangoFinancialCapacityGovernanceSource().get_qualification(
            binding=_binding(),
            manifest_sha256="1" * 64,
        )
        is None
    )
    assert FinancialCapacityGovernanceRecordModel._default_manager.count() == 1
    with override_settings(AGOM_BUILD_IDENTITY_PATH=identity_path):
        with pytest.raises(CommandError, match="approval ID already exists"):
            call_command(
                "record_financial_capacity_governance",
                record_file=approval_path,
                stage="qualification",
                actor=superuser.get_username(),
            )
    assert FinancialCapacityGovernanceRecordModel._default_manager.count() == 1


@pytest.mark.django_db
def test_append_command_rejects_non_superuser_and_candidate_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unprivileged users and approvals for another image cannot enter the database."""

    user_model = get_user_model()
    username_field = user_model.USERNAME_FIELD
    regular_user = user_model._default_manager.create_user(
        **{username_field: "capacity-operator"},
        password="test-password",
    )
    payload = _payload(_binding())
    approval_path = tmp_path / "reviewed-ceiling.json"
    approval_path.write_text(json.dumps(payload), encoding="utf-8")
    identity_path = tmp_path / ".agom-build-identity.json"
    _write_build_identity(identity_path, "b" * 40)
    monkeypatch.setattr(
        "apps.data_center.management.commands.record_financial_capacity_governance.getpass",
        lambda _prompt: "test-password",
    )

    with override_settings(AGOM_BUILD_IDENTITY_PATH=identity_path):
        with pytest.raises(CommandError, match="requires a Django superuser"):
            call_command(
                "record_financial_capacity_governance",
                record_file=approval_path,
                stage="qualification",
                actor=regular_user.get_username(),
            )

        regular_user.is_superuser = True
        regular_user.save(update_fields=["is_superuser"])
        with pytest.raises(CommandError, match="does not match the running build identity"):
            call_command(
                "record_financial_capacity_governance",
                record_file=approval_path,
                stage="qualification",
                actor=regular_user.get_username(),
            )

    assert FinancialCapacityGovernanceRecordModel._default_manager.count() == 0


@pytest.mark.django_db
def test_append_command_rejects_recorder_who_is_the_approving_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The command recorder cannot claim to be the independently approving owner."""

    user_model = get_user_model()
    username_field = user_model.USERNAME_FIELD
    superuser = user_model._default_manager.create_user(
        **{username_field: "capacity-reviewer"},
        password="test-password",
        is_superuser=True,
    )
    payload = _payload(_binding())
    payload["approved_by"] = "CAPACITY-REVIEWER"
    approval_path = tmp_path / "self-approved-ceiling.json"
    approval_path.write_text(json.dumps(payload), encoding="utf-8")
    identity_path = tmp_path / ".agom-build-identity.json"
    _write_build_identity(identity_path, "a" * 40)
    monkeypatch.setattr(
        "apps.data_center.management.commands.record_financial_capacity_governance.getpass",
        lambda _prompt: "test-password",
    )

    with override_settings(AGOM_BUILD_IDENTITY_PATH=identity_path):
        with pytest.raises(CommandError, match="recorder must differ from the approving owner"):
            call_command(
                "record_financial_capacity_governance",
                record_file=approval_path,
                stage="qualification",
                actor=superuser.get_username(),
            )

    assert FinancialCapacityGovernanceRecordModel._default_manager.count() == 0


@pytest.mark.django_db
def test_owner_command_requires_distinct_authenticated_owner_and_binds_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a separate interactive owner account can append the exact approval event."""

    user_model = get_user_model()
    username_field = user_model.USERNAME_FIELD
    recorder = user_model._default_manager.create_user(
        **{username_field: "capacity-recorder"},
        password="recorder-password",
        is_superuser=True,
    )
    owner = user_model._default_manager.create_user(
        **{username_field: "owner:financial-data"},
        password="owner-password",
        is_superuser=True,
    )
    payload = _payload(_binding())
    approval_path = tmp_path / "owner-reviewed-ceiling.json"
    approval_path.write_text(json.dumps(payload), encoding="utf-8")
    identity_path = tmp_path / ".agom-build-identity.json"
    _write_build_identity(identity_path, "a" * 40)
    monkeypatch.setattr(
        "apps.data_center.management.commands.record_financial_capacity_governance.getpass",
        lambda _prompt: "recorder-password",
    )

    with override_settings(AGOM_BUILD_IDENTITY_PATH=identity_path):
        call_command(
            "record_financial_capacity_governance",
            record_file=approval_path,
            stage="qualification",
            actor=recorder.get_username(),
        )
    row = FinancialCapacityGovernanceRecordModel._default_manager.get(
        approval_id=payload["approval_id"]
    )
    source = DjangoFinancialCapacityGovernanceSource()
    assert source.get_qualification(binding=_binding(), manifest_sha256="1" * 64) is None

    monkeypatch.setattr(
        "apps.data_center.management.commands.approve_financial_capacity_governance.getpass",
        lambda _prompt: "wrong-password",
    )
    with override_settings(AGOM_BUILD_IDENTITY_PATH=identity_path):
        with pytest.raises(CommandError, match="exact Django owner account"):
            call_command(
                "approve_financial_capacity_governance",
                approval_id=payload["approval_id"],
                owner=owner.get_username(),
            )
    assert not FinancialCapacityOwnerApprovalEventModel._default_manager.filter(
        governance_record=row
    ).exists()

    monkeypatch.setattr(
        "apps.data_center.management.commands.approve_financial_capacity_governance.getpass",
        lambda _prompt: "owner-password",
    )
    with override_settings(AGOM_BUILD_IDENTITY_PATH=identity_path):
        call_command(
            "approve_financial_capacity_governance",
            approval_id=payload["approval_id"],
            owner=owner.get_username(),
        )

    event = FinancialCapacityOwnerApprovalEventModel._default_manager.get(governance_record=row)
    assert event.approved_by == owner.get_username()
    assert event.approval_receipt_sha256 == payload["approval_receipt_sha256"]
    assert source.get_qualification(binding=_binding(), manifest_sha256="1" * 64) is not None

    with override_settings(AGOM_BUILD_IDENTITY_PATH=identity_path):
        with pytest.raises(CommandError, match="already has an owner event"):
            call_command(
                "approve_financial_capacity_governance",
                approval_id=payload["approval_id"],
                owner=owner.get_username(),
            )


@pytest.mark.django_db
def test_capacity_admin_appends_irreversible_revocation_event() -> None:
    """The admin appends revocation evidence while approval history remains immutable."""

    model_admin = FinancialCapacityGovernanceRecordAdmin(
        FinancialCapacityGovernanceRecordModel,
        AdminSite(),
    )
    request = RequestFactory().post("/admin/")
    request.user = SimpleNamespace(
        is_authenticated=True,
        is_superuser=True,
        is_staff=True,
        get_username=lambda: "capacity-reviewer",
    )
    payload = _payload(_binding())
    payload["approval_id"] = "review:financial-capacity:revocation-test"
    approval = _create_approval_record_with_owner_event(
        stage="qualification",
        payload=payload,
    )
    source = DjangoFinancialCapacityGovernanceSource()
    assert source.get_qualification(binding=_binding(), manifest_sha256="1" * 64) is not None
    model_admin.revoke_selected_records(
        request,
        FinancialCapacityGovernanceRecordModel._default_manager.filter(pk=approval.pk),
    )
    assert FinancialCapacityGovernanceRecordModel._default_manager.filter(pk=approval.pk).exists()
    revocation = FinancialCapacityGovernanceRevocationModel._default_manager.get(
        governance_record=approval
    )
    assert revocation.revoked_by == "capacity-reviewer"
    assert source.get_qualification(binding=_binding(), manifest_sha256="1" * 64) is None
    with pytest.raises(ValidationError, match="append-only"):
        revocation.delete()
    with pytest.raises(PermissionDenied, match="immutable"):
        model_admin.save_model(
            request,
            approval,
            cast(FinancialCapacityGovernanceRecordAdminForm, None),
            True,
        )
