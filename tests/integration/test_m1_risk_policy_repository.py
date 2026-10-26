"""Database contract candidates for immutable revisions and audit-backed revocation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.risk_center.application.m1_rebalance_risk_policy import (
    GetM1RiskPolicyQualificationUseCase,
    M1RiskPolicyAlreadyRevokedError,
    M1RiskPolicyIdempotencyConflictError,
    M1RiskPolicyIdempotencyContext,
    M1RiskPolicyNotFoundError,
    M1RiskPolicyOperation,
)
from apps.risk_center.domain.m1_rebalance_risk_policy import (
    M1RiskCondition,
    M1RiskPolicyPublishCommand,
    M1RiskPolicyRevision,
    M1RiskSourceSnapshot,
    RiskApplicability,
    RiskQualificationState,
)
from apps.risk_center.infrastructure.m1_rebalance_risk_policy_models import (
    M1RebalanceRiskPolicyRevisionModel,
)
from apps.risk_center.infrastructure.m1_rebalance_risk_policy_repository import (
    DjangoM1RiskPolicyRevisionRepository,
)
from apps.risk_center.infrastructure.models import RiskPolicyAuditModel


def _idempotency(
    *,
    account_id: int,
    actor_id: int,
    operation: M1RiskPolicyOperation,
    key: str,
    request_body: str,
) -> M1RiskPolicyIdempotencyContext:
    """Build a deterministic request context used only by repository contracts."""

    scope = hashlib.sha256(f"{account_id}:{actor_id}:{operation}:{key}".encode()).hexdigest()
    body = hashlib.sha256(request_body.encode("utf-8")).hexdigest()
    return M1RiskPolicyIdempotencyContext(
        account_id=account_id,
        actor_user_id=actor_id,
        operation=operation,
        identity_sha256=scope,
        request_sha256=body,
    )


def _create_revision(
    repository: DjangoM1RiskPolicyRevisionRepository,
    command: M1RiskPolicyPublishCommand,
    *,
    key: str,
) -> M1RiskPolicyRevision:
    """Create through the real repository with one stable request identity."""

    return repository.create_revision(
        command,
        idempotency=_idempotency(
            account_id=command.account_id,
            actor_id=command.actor_user_id,
            operation="publish",
            key=key,
            request_body=repr(command),
        ),
    )


def _revoke_revision(
    repository: DjangoM1RiskPolicyRevisionRepository,
    *,
    account_id: int,
    risk_policy_version: str,
    actor_id: int,
    reason: str,
    key: str,
) -> M1RiskPolicyRevision:
    """Append or replay one revoke result using its request-bound identity."""

    return repository.revoke_revision(
        account_id=account_id,
        risk_policy_version=risk_policy_version,
        actor_user_id=actor_id,
        reason=reason,
        idempotency=_idempotency(
            account_id=account_id,
            actor_id=actor_id,
            operation="revoke",
            key=key,
            request_body=f"{risk_policy_version}:{reason}",
        ),
    )


def _command(
    *,
    actor_id: int,
    account_id: int,
    effective_from: datetime,
) -> M1RiskPolicyPublishCommand:
    """Return explicit decimal conditions bound to a confirmed manual account source."""

    source = M1RiskSourceSnapshot(
        account_id=account_id,
        account_owner_user_id=actor_id,
        account_type="simulated",
        account_is_active=True,
        account_max_single_position_pct=Decimal("20"),
        account_max_total_position_pct=Decimal("95"),
        account_stop_loss_pct=Decimal("8"),
        strategy_selection_state="confirmed_unconfigured",
        strategy_id=None,
        strategy_version=None,
        strategy_max_single_position_pct=None,
        strategy_max_total_position_pct=None,
        strategy_stop_loss_pct=None,
        position_rule_id=None,
        position_rule_source_json=None,
    )
    start = effective_from
    return M1RiskPolicyPublishCommand(
        account_id=account_id,
        actor_user_id=actor_id,
        effective_from=start,
        effective_until=start + timedelta(days=30),
        reason="Owner accepted the explicit M1 preview risk window.",
        max_single_position=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("19")),
        max_total_position=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("90")),
        max_stop_loss=M1RiskCondition(RiskApplicability.APPLICABLE, Decimal("7")),
        source_snapshot=source,
    )


@pytest.mark.django_db
def test_model_instance_cannot_publish_without_audited_repository_path() -> None:
    """The only ordinary ORM creation path is the audited repository transaction."""

    with pytest.raises(ValidationError, match="audited repository"):
        M1RebalanceRiskPolicyRevisionModel.objects.create()


@pytest.mark.django_db
def test_repository_persists_real_actor_version_source_and_publish_audit() -> None:
    """The created row is a new policy source and its actor is a real auth FK."""

    user = get_user_model().objects.create_user(
        username=f"m1-risk-publish-{uuid4().hex}",
        password="unused",
    )
    account_id = 987654
    start = timezone.now() + timedelta(minutes=5)
    repository = DjangoM1RiskPolicyRevisionRepository()
    revision = _create_revision(
        repository,
        _command(actor_id=user.pk, account_id=account_id, effective_from=start),
        key="persist-publish",
    )
    row = M1RebalanceRiskPolicyRevisionModel.objects.get(
        risk_policy_version=revision.risk_policy_version
    )
    audit = RiskPolicyAuditModel.objects.get(
        target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
        target_id=revision.risk_policy_version,
        action="publish",
    )

    assert row.actor_id == user.pk
    assert row.account_id == account_id
    assert row.known_at is not None
    assert row.effective_from == start
    assert revision.source_snapshot.account_stop_loss_pct == Decimal("8")
    assert row.source_snapshot["account_stop_loss_pct"] == "8"
    assert audit.actor_id == user.pk
    assert audit.reason == "Owner accepted the explicit M1 preview risk window."


@pytest.mark.django_db
def test_revision_instance_rejects_update_and_delete() -> None:
    """A published revision can only be superseded or revoked through an audit row."""

    user = get_user_model().objects.create_user(
        username=f"m1-risk-immutable-{uuid4().hex}",
        password="unused",
    )
    repository = DjangoM1RiskPolicyRevisionRepository()
    revision = _create_revision(
        repository,
        _command(
            actor_id=user.pk,
            account_id=987655,
            effective_from=timezone.now() + timedelta(minutes=5),
        ),
        key="immutable-publish",
    )
    row = M1RebalanceRiskPolicyRevisionModel.objects.get(
        risk_policy_version=revision.risk_policy_version
    )
    row.reason = "attempted edit"

    with pytest.raises(ValidationError, match="immutable"):
        row.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="immutable"):
        M1RebalanceRiskPolicyRevisionModel.objects.filter(
            risk_policy_version=revision.risk_policy_version
        ).update(reason="bulk edit")
    with pytest.raises(ValidationError, match="cannot be deleted"):
        M1RebalanceRiskPolicyRevisionModel.objects.filter(
            risk_policy_version=revision.risk_policy_version
        ).delete()
    with pytest.raises(ValidationError, match="audited repository"):
        M1RebalanceRiskPolicyRevisionModel.objects.bulk_create([row])

    row.refresh_from_db()
    assert row.reason == "Owner accepted the explicit M1 preview risk window."


@pytest.mark.django_db
def test_repository_revokes_by_appending_audit_and_reader_never_rewrites_revision() -> None:
    """The original revision remains byte-stable while a real audit event revokes it."""

    owner = get_user_model().objects.create_user(
        username=f"m1-risk-revoker-{uuid4().hex}",
        password="unused",
    )
    repository = DjangoM1RiskPolicyRevisionRepository()
    revision = _create_revision(
        repository,
        _command(
            actor_id=owner.pk,
            account_id=987656,
            effective_from=timezone.now() + timedelta(minutes=5),
        ),
        key="audit-publish",
    )
    original_row = M1RebalanceRiskPolicyRevisionModel.objects.get(
        risk_policy_version=revision.risk_policy_version
    )
    before = {
        "reason": original_row.reason,
        "source_snapshot": original_row.source_snapshot,
        "effective_from": original_row.effective_from,
        "effective_until": original_row.effective_until,
    }

    revoke_request_hash = _idempotency(
        account_id=987656,
        actor_id=owner.pk,
        operation="revoke",
        key="audit-revoke",
        request_body=f"{revision.risk_policy_version}:Owner withdrew the M1 risk decision.",
    )
    revoked = repository.revoke_revision(
        account_id=987656,
        risk_policy_version=revision.risk_policy_version,
        actor_user_id=owner.pk,
        reason="Owner withdrew the M1 risk decision.",
        idempotency=revoke_request_hash,
    )
    retry = repository.revoke_revision(
        account_id=987656,
        risk_policy_version=revision.risk_policy_version,
        actor_user_id=owner.pk,
        reason="Owner withdrew the M1 risk decision.",
        idempotency=revoke_request_hash,
    )
    after_row = M1RebalanceRiskPolicyRevisionModel.objects.get(
        risk_policy_version=revision.risk_policy_version
    )
    audit = RiskPolicyAuditModel.objects.get(
        target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
        target_id=revision.risk_policy_version,
        action="revoke",
    )
    read_back = repository.list_revisions(account_id=987656)[0]

    assert audit.after["effective_at"] == revoked.revoked_at.isoformat()
    assert revoked.revoked_by_user_id == owner.pk
    assert revoked.revocation_reason == audit.reason
    assert after_row.reason == before["reason"]
    assert after_row.source_snapshot == before["source_snapshot"]
    assert after_row.effective_from == before["effective_from"]
    assert after_row.effective_until == before["effective_until"]
    assert read_back.revoked_at == revoked.revoked_at
    assert read_back.revoked_by_user_id == owner.pk
    assert audit.actor_id == owner.pk
    assert retry == revoked

    with pytest.raises(ValidationError, match="append-only"):
        audit.delete()
    with pytest.raises(ValidationError, match="append-only"):
        RiskPolicyAuditModel.objects.filter(pk=audit.pk).delete()
    with pytest.raises(ValidationError, match="append-only"):
        RiskPolicyAuditModel.objects.filter(pk=audit.pk).update(action="publish")
    audit.reason = "Tampered revoke evidence."
    with pytest.raises(ValidationError, match="append-only"):
        audit.save(update_fields=("reason",))
    audit.action = "publish"
    with pytest.raises(ValidationError, match="append-only"):
        RiskPolicyAuditModel.objects.bulk_update([audit], ["action"])
    audit.target_type = RiskPolicyAuditModel.TARGET_FLOOR
    with pytest.raises(ValidationError, match="append-only"):
        audit.delete()

    legacy_audit = RiskPolicyAuditModel.objects.create(
        target_type=RiskPolicyAuditModel.TARGET_POLICY,
        target_id="legacy-policy-row",
        action="publish",
        reason="Legacy event remains editable.",
    )
    target_expressions: tuple[object, ...] = (
        models.Value(RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION),
        models.F("target_type"),
        models.Case(
            models.When(
                pk=legacy_audit.pk,
                then=models.Value(RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION),
            ),
            default=models.Value(RiskPolicyAuditModel.TARGET_POLICY),
            output_field=models.CharField(max_length=32),
        ),
    )
    for expression in target_expressions:
        with pytest.raises(ValidationError, match="literal"):
            RiskPolicyAuditModel.objects.filter(pk=legacy_audit.pk).update(
                target_type=cast(str, expression)
            )

    legacy_audit.target_type = cast(
        str,
        models.Value(RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION),
    )
    with pytest.raises(ValidationError, match="literal"):
        legacy_audit.save(update_fields=("target_type",))
    legacy_audit.target_type = cast(
        str,
        models.Case(
            models.When(
                pk=legacy_audit.pk,
                then=models.Value(RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION),
            ),
            default=models.Value(RiskPolicyAuditModel.TARGET_POLICY),
            output_field=models.CharField(max_length=32),
        ),
    )
    with pytest.raises(ValidationError, match="target_type"):
        RiskPolicyAuditModel.objects.bulk_update([legacy_audit], ["target_type"])
    with pytest.raises(ValidationError, match="literal"):
        RiskPolicyAuditModel.objects.bulk_create(
            [
                RiskPolicyAuditModel(
                    target_type=cast(str, models.F("target_type")),
                    target_id="expression-created-row",
                    action="publish",
                )
            ]
        )

    explicit_pk_replacement = RiskPolicyAuditModel(
        pk=audit.pk,
        target_type=RiskPolicyAuditModel.TARGET_POLICY,
        target_id="replacement-row",
        action="publish",
        reason="Replacement attempt.",
    )
    with pytest.raises(ValidationError, match="append-only"):
        explicit_pk_replacement.save()
    with pytest.raises(ValidationError, match="append-only"):
        RiskPolicyAuditModel.objects.bulk_create(
            [explicit_pk_replacement],
            update_conflicts=True,
            update_fields=["target_type", "action", "reason"],
            unique_fields=[RiskPolicyAuditModel._meta.pk.name],
        )

    audit.refresh_from_db()
    legacy_audit.refresh_from_db()
    assert audit.action == "revoke"
    assert audit.target_type == RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION
    assert audit.reason == "Owner withdrew the M1 risk decision."
    assert audit.after["effective_at"] == revoked.revoked_at.isoformat()
    assert legacy_audit.target_type == RiskPolicyAuditModel.TARGET_POLICY
    assert legacy_audit.reason == "Legacy event remains editable."
    assert repository.list_revisions(account_id=987656)[0].revocation_state == "revoked"
    final_qualification = GetM1RiskPolicyQualificationUseCase(repository).execute(
        account_id=987656,
        as_of=revision.effective_from + timedelta(seconds=1),
        current_source=revision.source_snapshot,
    )
    assert final_qualification.state is RiskQualificationState.REVOKED

    changed_payload = _idempotency(
        account_id=987656,
        actor_id=owner.pk,
        operation="revoke",
        key="audit-revoke",
        request_body=f"{revision.risk_policy_version}:Different reason.",
    )
    with pytest.raises(M1RiskPolicyIdempotencyConflictError):
        repository.revoke_revision(
            account_id=987656,
            risk_policy_version=revision.risk_policy_version,
            actor_user_id=owner.pk,
            reason="Different reason.",
            idempotency=changed_payload,
        )

    with pytest.raises(M1RiskPolicyAlreadyRevokedError):
        _revoke_revision(
            repository,
            account_id=987656,
            risk_policy_version=revision.risk_policy_version,
            actor_id=owner.pk,
            reason="Duplicate revocation.",
            key="new-revoke-submission",
        )
    with pytest.raises(M1RiskPolicyNotFoundError):
        _revoke_revision(
            repository,
            account_id=987656,
            risk_policy_version=str(uuid4()),
            actor_id=owner.pk,
            reason="Unknown version.",
            key="missing-revoke-submission",
        )


@pytest.mark.django_db
def test_revoked_window_can_be_replaced_by_new_owner_revision() -> None:
    """A verified revoke event ends one window so a tighter new version can start."""

    owner = get_user_model().objects.create_user(
        username=f"m1-risk-replace-{uuid4().hex}",
        password="unused",
    )
    account_id = 987657
    repository = DjangoM1RiskPolicyRevisionRepository()
    old = _create_revision(
        repository,
        _command(
            actor_id=owner.pk,
            account_id=account_id,
            effective_from=timezone.now() + timedelta(minutes=5),
        ),
        key="replace-first-publish",
    )
    revoked = _revoke_revision(
        repository,
        account_id=account_id,
        risk_policy_version=old.risk_policy_version,
        actor_id=owner.pk,
        reason="Owner replaces the earlier M1 decision.",
        key="replace-first-revoke",
    )
    replacement_start = old.effective_from + timedelta(minutes=1)
    replacement = _create_revision(
        repository,
        _command(
            actor_id=owner.pk,
            account_id=account_id,
            effective_from=replacement_start,
        ),
        key="replace-second-publish",
    )
    source = replacement.source_snapshot
    qualified = GetM1RiskPolicyQualificationUseCase(repository).execute(
        account_id=account_id,
        as_of=replacement_start,
        current_source=source,
    )

    assert replacement.effective_from > revoked.revoked_at
    assert qualified.ready_for_buy is True
    assert qualified.revision is not None
    assert qualified.revision.risk_policy_version == replacement.risk_policy_version
