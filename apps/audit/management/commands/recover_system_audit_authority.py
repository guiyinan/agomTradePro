"""Recover an expired System Audit approval chain without rewriting history."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.account.account_actor_authority_capture_composition import (
    build_account_actor_authority_capture,
)
from apps.account.account_owner_assignment_evidence_v5_composition import (
    build_account_owner_assignment_evidence_v5_facade,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
    ApproveAccountOwnerAssignmentEvidenceV5Command,
    GetExactAccountOwnerAssignmentEvidenceV5,
    GetExactAccountOwnerAssignmentEvidenceV5Command,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    IssueAccountOwnerAssignmentProvenanceReceiptV5,
    IssueAccountOwnerAssignmentProvenanceReceiptV5Command,
)
from apps.account.application.account_owner_assignment_subject_v5 import (
    RegisterAccountOwnerAssignmentSubjectV5,
    RegisterAccountOwnerAssignmentSubjectV5Command,
)
from apps.account.application.owner_tenant_authority_v3 import (
    IssueOwnerTenantAuthorityV3Command,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v5 import (
    AccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.domain.account_owner_assignment_subject_v5 import (
    AccountOwnerAssignmentSubjectV5,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v5_repository import (
    DjangoAccountOwnerAssignmentEvidenceV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_repository import (
    DjangoAccountOwnerAssignmentSubjectV5Repository,
)
from apps.account.owner_tenant_authority_v3_composition import (
    build_owner_tenant_authority_v3_facade,
)
from apps.audit.application.system_audit_authority_provider import (
    SystemAuditAuthorityBundleSelector,
)
from apps.audit.application.system_audit_authority_schema import (
    SYSTEM_AUDIT_SCOPE_SCHEMA_V3,
)
from apps.audit.infrastructure.system_audit_authority_recovery_request import (
    SystemAuditAuthorityRecoveryInput,
    parse_system_audit_authority_recovery_request,
)
from core.exceptions import AgomTradeProException


class Command(BaseCommand):
    """Append a fresh assignment approval and a new owner-authority root."""

    help = "Recover an expired System Audit authority bundle through append-only successors."
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the strict request path and explicit write opt-in."""

        parser.add_argument("--input", required=True, type=str)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args: object, **options: Any) -> None:
        """Validate the envelope or execute the recovery in one transaction."""

        del args
        input_path = options.get("input")
        execute = options.get("execute")
        if type(input_path) is not str or not input_path:
            raise CommandError("input must be an exact path string")
        if type(execute) is not bool:
            raise CommandError("execute must be an exact boolean")
        try:
            request = parse_system_audit_authority_recovery_request(Path(input_path).read_bytes())
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            raise CommandError("recovery request could not be validated") from error
        if request.renewal.database_alias != "default":
            raise CommandError("System Audit recovery requires the default database alias")
        if request.renewal.profile.environment != "production":
            raise CommandError("System Audit recovery is restricted to production")
        _require_profile_predecessor(request)
        if not execute:
            self._write(
                {
                    "outcome": "noop",
                    "mode": "dry_run",
                    "reason": "request_validated_only",
                    "authority_persisted": False,
                    "runtime_enabled": False,
                    "predecessor_evidence_id": (
                        request.renewal.renewal.owner_successor.assignment_evidence_id
                    ),
                    "successor_evidence_version": request.evidence_version,
                    "successor_authority_id": request.authority_id,
                }
            )
            return
        try:
            with transaction.atomic(using="default"):
                result = _execute_recovery(request)
        except (AgomTradeProException, DatabaseError, OSError, TypeError, ValueError) as error:
            del error
            self._write(
                {
                    "outcome": "blocked",
                    "mode": "execute",
                    "authority_persisted": False,
                    "runtime_enabled": False,
                    "blocked_reason": "recovery_transaction_rejected",
                }
            )
            return
        self._write({"outcome": "success", "mode": "execute", **result})

    def _write(self, payload: dict[str, object]) -> None:
        self.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _execute_recovery(request: SystemAuditAuthorityRecoveryInput) -> dict[str, object]:
    """Append the assignment and authority successors, then activate Audit."""

    base = request.renewal
    old_selector = base.renewal.owner_successor
    previous = GetExactAccountOwnerAssignmentEvidenceV5(
        DjangoAccountOwnerAssignmentEvidenceV5Repository(using=base.database_alias)
    ).execute(
        GetExactAccountOwnerAssignmentEvidenceV5Command(
            evidence_id=old_selector.assignment_evidence_id,
            evidence_version=old_selector.assignment_evidence_version,
            expected_content_hash=old_selector.expected_assignment_evidence_content_hash,
            as_of=timezone.now(),
        )
    )
    if previous is None:
        raise ValueError("predecessor Evidence V5 is unavailable")

    actor = build_account_actor_authority_capture(
        recorder_service_id=base.actor_recorder_service_id,
        validity_period=base.actor_validity_period,
        using=base.database_alias,
    ).execute(base.renewal.actor_capture)
    if type(actor) is not AccountOwnerAssignmentActorAuthoritySourceV3:
        raise TypeError("captured actor authority is invalid")

    now = timezone.now()
    previous_receipt = previous.subject.receipt
    receipt = replace(
        previous_receipt,
        receipt_version=request.receipt_version,
        issued_at=now,
        recorded_at=now,
        valid_until=min(
            now + request.assignment_validity_period,
            previous_receipt.policy.valid_until,
            previous_receipt.reobservation.valid_until,
        ),
        supersedes_content_hash=previous_receipt.content_hash,
        identity_hash="",
        content_hash="",
    )
    receipt = IssueAccountOwnerAssignmentProvenanceReceiptV5(
        DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository(using=base.database_alias)
    ).execute(
        IssueAccountOwnerAssignmentProvenanceReceiptV5Command(
            receipt=receipt,
            predecessor=previous_receipt,
        )
    )
    subject = _subject(
        receipt=receipt,
        subject_id=request.subject_id,
        subject_version=request.subject_version,
        requested_at=timezone.now(),
    )
    subject = RegisterAccountOwnerAssignmentSubjectV5(
        DjangoAccountOwnerAssignmentSubjectV5Repository(using=base.database_alias)
    ).execute(RegisterAccountOwnerAssignmentSubjectV5Command(subject))

    physical_rows = _load_physical_row_provider(base.database_alias)
    evidence = build_account_owner_assignment_evidence_v5_facade(
        principal=base.principal,
        policy_binding=base.policy_binding,
        actor_source_id=actor.source_id,
        actor_source_version=actor.source_version,
        actor_source_content_hash=actor.content_hash,
        validity_period=request.assignment_validity_period,
        physical_row_provider=physical_rows,
        using=base.database_alias,
    ).approve(
        ApproveAccountOwnerAssignmentEvidenceV5Command(
            evidence_id=previous.evidence_id,
            evidence_version=request.evidence_version,
            subject_id=subject.subject_id,
            subject_version=subject.subject_version,
            expected_subject_content_hash=subject.content_hash,
            expected_predecessor_content_hash=previous.content_hash,
        )
    )
    scope = build_owner_tenant_authority_v3_facade(
        principal=base.principal,
        policy_binding=base.policy_binding,
        actor_source_id=actor.source_id,
        actor_source_version=actor.source_version,
        actor_source_content_hash=actor.content_hash,
        validity_period=base.authority_validity_period,
        physical_row_provider=physical_rows,
        using=base.database_alias,
    ).issue(
        IssueOwnerTenantAuthorityV3Command(
            authority_id=request.authority_id,
            authority_version=request.authority_version,
            assignment_evidence_id=evidence.evidence_id,
            assignment_evidence_version=evidence.evidence_version,
            expected_assignment_evidence_content_hash=evidence.content_hash,
        )
    )
    observed_at = timezone.now()
    valid_until = min(actor.valid_until, scope.valid_until)
    if valid_until < observed_at + base.renewal.minimum_window:
        raise ValueError("recovered authority validity window is too short")
    selector = SystemAuditAuthorityBundleSelector(
        actor_source_id=actor.source_id,
        actor_source_version=actor.source_version,
        actor_content_hash=actor.content_hash,
        scope_source_id=scope.authority_id,
        scope_source_version=scope.authority_version,
        scope_content_hash=scope.content_hash,
        scope_schema=SYSTEM_AUDIT_SCOPE_SCHEMA_V3,
    )
    profile = _activate_runtime_successor(request, selector)
    return {
        "authority_persisted": True,
        "runtime_enabled": True,
        "evidence_id": evidence.evidence_id,
        "evidence_version": evidence.evidence_version,
        "evidence_content_hash": evidence.content_hash,
        "authority_valid_until": valid_until.isoformat(),
        "selector": _selector_payload(selector),
        "profile": profile,
    }


def _subject(
    *,
    receipt: AccountOwnerAssignmentProvenanceReceiptV5,
    subject_id: str,
    subject_version: str,
    requested_at: datetime,
) -> AccountOwnerAssignmentSubjectV5:
    """Build one fresh Subject V5 from the renewed receipt graph."""

    binding = receipt.binding
    reobservation = receipt.reobservation
    current = reobservation.current_physical
    return AccountOwnerAssignmentSubjectV5(
        subject_id=subject_id,
        subject_version=subject_version,
        receipt=receipt,
        binding=binding,
        reobservation=reobservation,
        receipt_identity_hash=receipt.identity_hash,
        receipt_content_hash=receipt.content_hash,
        policy_identity_hash=receipt.policy.identity_hash,
        policy_content_hash=receipt.policy.content_hash,
        binding_identity_hash=binding.identity_hash,
        binding_content_hash=binding.content_hash,
        allocation_identity_hash=binding.allocation.identity_hash,
        allocation_content_hash=binding.allocation.content_hash,
        account_claim_hash=binding.account_claim_hash,
        underlying_claim_hash=binding.underlying_claim_hash,
        reobservation_identity_hash=reobservation.identity_hash,
        reobservation_content_hash=reobservation.content_hash,
        current_physical_observation_content_hash=current.content_hash,
        current_physical_source_content_hash=current.source_content_hash,
        current_physical_raw_observation_content_hash=current.raw_observation_content_hash,
        requested_at=requested_at,
        valid_until=receipt.valid_until,
    )


def _activate_runtime_successor(
    request: SystemAuditAuthorityRecoveryInput,
    selector: SystemAuditAuthorityBundleSelector,
) -> dict[str, object]:
    profile = request.renewal.profile
    activate = _load_runtime_profile_activator()
    return activate(
        environment=profile.environment,
        patch={
            "audit.system_event.mode": "required",
            "audit.system_event.outbox_enabled": True,
            "audit.system_event.authority_selector": _selector_payload(selector),
        },
        actor=profile.actor,
        reason=profile.reason,
        release_ref=profile.release_ref,
        expected_active_profile_id=profile.expected_active_profile_id,
        expected_active_profile_version=profile.expected_active_profile_version,
        expected_active_profile_hash=profile.expected_active_profile_hash,
        expected_active_snapshot_hash=profile.expected_active_snapshot_hash,
    )


def _selector_payload(selector: SystemAuditAuthorityBundleSelector) -> dict[str, str]:
    """Project one validated selector without secrets."""

    return {
        "actor_source_id": selector.actor_source_id,
        "actor_source_version": selector.actor_source_version,
        "actor_content_hash": selector.actor_content_hash,
        "scope_source_id": selector.scope_source_id,
        "scope_source_version": selector.scope_source_version,
        "scope_content_hash": selector.scope_content_hash,
        "scope_schema": selector.scope_schema,
    }


def _require_profile_predecessor(request: SystemAuditAuthorityRecoveryInput) -> None:
    """Require complete Config Center CAS bindings before any write."""

    profile = request.renewal.profile
    if any(
        value is None
        for value in (
            profile.expected_active_profile_id,
            profile.expected_active_profile_version,
            profile.expected_active_profile_hash,
            profile.expected_active_snapshot_hash,
        )
    ):
        raise CommandError("recovery execution requires complete profile predecessor bindings")


def _load_physical_row_provider(using: str) -> Any:
    """Load the simulated-account provider at the composition boundary."""

    module = import_module("apps.simulated_trading.account_physical_row_v2_composition")
    builder = getattr(module, "build_account_physical_row_v2_provider", None)
    if not callable(builder):
        raise TypeError("physical row provider factory is unavailable")
    return builder(using=using)


def _load_runtime_profile_activator() -> Callable[..., dict[str, object]]:
    """Load the public Config Center writer without an app implementation edge."""

    module = import_module("apps.config_center.application.runtime_public")
    activator = getattr(module, "activate_runtime_profile_patch_payload", None)
    if not callable(activator):
        raise TypeError("runtime profile activator is unavailable")
    return cast(Callable[..., dict[str, object]], activator)


__all__ = ["Command"]
