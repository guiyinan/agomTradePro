"""Compose the SZSE renewal worker and the session-authorized Owner controls."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import DEFAULT_DB_ALIAS, connection, transaction
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from rest_framework.request import Request

from apps.data_center.application.calendar_publication_operations import (
    CaptureExchangeCalendarSnapshotIntent,
    ConfirmCalendarPublicationUseCase,
    PreviewCalendarPublicationIntent,
    PreviewCalendarPublicationUseCase,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    PublishExchangeCalendarSnapshotUseCase,
    ReadCurrentExchangeCalendarPublicationQuery,
)
from apps.data_center.calendar_publication_authority_composition import (
    locked_calendar_publisher_for_request,
)
from apps.data_center.calendar_publication_operations_composition import (
    _ActivationIdFactory,
    _formal_repository,
    _ServerClock,
    read_current_exchange_calendar_reference,
)
from apps.data_center.calendar_snapshot_capture_composition import compose_calendar_snapshot_capture
from apps.data_center.infrastructure._session_grant_authority_kernel import (
    _AuthorityPurpose,
    _PrincipalLease,
)
from apps.data_center.infrastructure.calendar_renewal_models import (
    CalendarRenewalGrant,
    CalendarRenewalReceipt,
)
from core.exceptions import AuthorizationError, InvalidInputError

TASK_NAME = "data_center.renew_szse_calendar"
QUEUE = "szse-calendar-renewal"


def _denied(code: str) -> AuthorizationError:
    return AuthorizationError("SZSE calendar renewal is blocked", code=code)


def _direct_witness(owner_id: int, model: str, codename: str) -> tuple[int, int]:
    """Return the locked through-row and permission identities for this direct grant."""
    permission = (
        Permission.objects.using(DEFAULT_DB_ALIAS)
        .select_for_update()
        .filter(
            content_type__app_label="data_center",
            content_type__model=model,
            codename=codename,
        )
        .first()
    )
    if permission is None:
        raise _denied("CALENDAR_RENEWAL_PERMISSION_REQUIRED")
    through = get_user_model().user_permissions.through
    witness = (
        through.objects.using(DEFAULT_DB_ALIAS)
        .select_for_update()
        .filter(
            user_id=owner_id,
            permission_id=permission.pk,
        )
        .values_list("pk", flat=True)
        .first()
    )
    if type(witness) is not int:
        raise _denied("CALENDAR_RENEWAL_PERMISSION_REQUIRED")
    return witness, permission.pk


def _publish_witness(owner_id: int) -> tuple[int, int]:
    return _direct_witness(
        owner_id, "exchangecalendarsnapshotfactmodel", "publish_exchange_calendar"
    )


def _delegate_witness(owner_id: int) -> int:
    return _direct_witness(owner_id, "calendarrenewalgrant", "delegate_szse_calendar_renewal")[0]


def issue_renewal(request: Request, dataset_key: str, expires_at: datetime) -> UUID:
    """Pin the live formal head and direct Owner grants, with a disabled Beat entry."""
    with locked_calendar_publisher_for_request(request, using=DEFAULT_DB_ALIAS) as principal:
        now = timezone.now()
        if timezone.is_naive(expires_at) or expires_at <= now:
            raise InvalidInputError(
                "Delegation requires a future expiry", code="CALENDAR_RENEWAL_EXPIRY_INVALID"
            )
        publish_id, _ = _publish_witness(principal.user_id)
        delegate_id = _delegate_witness(principal.user_id)
        current = read_current_exchange_calendar_reference(
            ReadCurrentExchangeCalendarPublicationQuery(dataset_key, "SZSE", now)
        )
        if (
            CalendarRenewalGrant.objects.using(DEFAULT_DB_ALIAS)
            .filter(dataset_key=dataset_key, revoked_at__isnull=True)
            .exists()
        ):
            raise _denied("CALENDAR_RENEWAL_ALREADY_DELEGATED")
        reference = current.record.seal.snapshot_reference
        grant = CalendarRenewalGrant.objects.using(DEFAULT_DB_ALIAS).create(
            owner_user_id=principal.user_id,
            publish_grant_id=publish_id,
            delegate_grant_id=delegate_id,
            dataset_key=dataset_key,
            coverage_start=reference.coverage_start,
            coverage_end=reference.coverage_end,
            issued_at=now,
            expires_at=expires_at,
            verified_at=current.as_of,
            activation_id=current.record.activation_id,
        )
        interval, _ = IntervalSchedule.objects.using(DEFAULT_DB_ALIAS).get_or_create(
            every=1, period=IntervalSchedule.MINUTES
        )
        PeriodicTask.objects.using(DEFAULT_DB_ALIAS).create(
            name=f"szse-calendar-renewal-{grant.pk}",
            task=TASK_NAME,
            args=json.dumps([str(grant.pk)]),
            queue=QUEUE,
            interval=interval,
            enabled=False,
        )
        return grant.pk


def revoke_renewal(request: Request, grant_id: UUID) -> None:
    """Withdraw this owner's grant and disable future enqueueing atomically."""
    with locked_calendar_publisher_for_request(request, using=DEFAULT_DB_ALIAS) as principal:
        grant = (
            CalendarRenewalGrant.objects.using(DEFAULT_DB_ALIAS)
            .select_for_update()
            .filter(pk=grant_id, owner_user_id=principal.user_id)
            .first()
        )
        if grant is None:
            raise _denied("CALENDAR_RENEWAL_GRANT_UNKNOWN")
        if grant.revoked_at is None:
            grant.revoked_at = timezone.now()
            grant.save(using=DEFAULT_DB_ALIAS, update_fields=["revoked_at"])
        schedule = (
            PeriodicTask.objects.using(DEFAULT_DB_ALIAS)
            .filter(name=f"szse-calendar-renewal-{grant.pk}")
            .first()
        )
        if schedule is not None and schedule.enabled:
            schedule.enabled = False
            schedule.save(using=DEFAULT_DB_ALIAS)


def renew_calendar_grant(grant_id: UUID, *, delivery_id: UUID) -> str:
    """Renew once under native row locks, the formal scope fence and a live Owner lease."""
    if (
        connection.vendor != "postgresql"
        or connection.in_atomic_block
        or not connection.get_autocommit()
    ):
        raise _denied("CALENDAR_RENEWAL_TRANSACTION_REQUIRED")
    clock = _ServerClock()
    with transaction.atomic(durable=True):
        owner_id = (
            CalendarRenewalGrant.objects.using(DEFAULT_DB_ALIAS)
            .filter(pk=grant_id)
            .values_list("owner_user_id", flat=True)
            .first()
        )
        if owner_id is None:
            raise _denied("CALENDAR_RENEWAL_GRANT_UNKNOWN")
        owner = (
            get_user_model()
            .objects.using(DEFAULT_DB_ALIAS)
            .select_for_update()
            .filter(pk=owner_id, is_active=True)
            .first()
        )
        if owner is None:
            raise _denied("CALENDAR_RENEWAL_GRANT_UNKNOWN")
        publish_id, permission_id = _publish_witness(owner.pk)
        delegate_id = _delegate_witness(owner.pk)
        grant = (
            CalendarRenewalGrant.objects.using(DEFAULT_DB_ALIAS)
            .select_for_update()
            .get(pk=grant_id)
        )
        now = clock.now()
        if (
            grant.owner_user_id != owner.pk
            or grant.revoked_at is not None
            or not grant.issued_at <= grant.verified_at <= now < grant.expires_at
            or (grant.publish_grant_id, grant.delegate_grant_id) != (publish_id, delegate_id)
        ):
            raise _denied("CALENDAR_RENEWAL_GRANT_INACTIVE")
        if (
            CalendarRenewalReceipt.objects.using(DEFAULT_DB_ALIAS)
            .filter(grant=grant, delivery_id=delivery_id)
            .exists()
        ):
            return "already_renewed"
        current = read_current_exchange_calendar_reference(
            ReadCurrentExchangeCalendarPublicationQuery(
                grant.dataset_key, "SZSE", grant.verified_at
            )
        )
        reference = current.record.seal.snapshot_reference
        if (
            current.record.activation_id != grant.activation_id
            or reference.coverage_start != grant.coverage_start
            or reference.coverage_end != grant.coverage_end
        ):
            raise _denied("CALENDAR_RENEWAL_SCOPE_CHANGED")
        due_check_at = clock.now()
        if not now <= due_check_at < grant.expires_at:
            raise _denied("CALENDAR_RENEWAL_GRANT_INACTIVE")
        if current.record.is_effective_at(due_check_at):
            return "still_valid"
        enabled = (
            PeriodicTask.objects.using(DEFAULT_DB_ALIAS)
            .select_for_update()
            .filter(
                name=f"szse-calendar-renewal-{grant.pk}",
                enabled=True,
                task=TASK_NAME,
                queue=QUEUE,
            )
            .first()
        )
        if enabled is None:
            raise _denied("CALENDAR_RENEWAL_SCHEDULE_DISABLED")
        capture = compose_calendar_snapshot_capture(known_at=clock.now())
        if capture.dataset_key != grant.dataset_key:
            raise _denied("CALENDAR_RENEWAL_SCOPE_CHANGED")
        principal = _PrincipalLease(
            user_id=owner.pk,
            permission_id=permission_id,
            permission_codename="publish_exchange_calendar",
            database_alias=DEFAULT_DB_ALIAS,
            verified_at=now,
            expires_at=grant.expires_at,
            authority_content_hash=hashlib.sha256(
                json.dumps(
                    [
                        str(grant.pk),
                        grant.owner_user_id,
                        publish_id,
                        delegate_id,
                        grant.dataset_key,
                        "SZSE",
                        grant.coverage_start.isoformat(),
                        grant.coverage_end.isoformat(),
                        grant.expires_at.isoformat(),
                    ],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            purpose=_AuthorityPurpose.PUBLISH,
            clock=clock,
            connection=transaction.get_connection(),
        )
        try:
            principal.assert_live()
            captured = capture.execute(
                CaptureExchangeCalendarSnapshotIntent(
                    "SZSE", grant.coverage_start, grant.coverage_end
                )
            )
            repository = _formal_repository(clock)
            preview = PreviewCalendarPublicationUseCase(
                preparation=repository, clock=clock, activation_ids=_ActivationIdFactory()
            ).execute(
                PreviewCalendarPublicationIntent(captured.snapshot_reference), principal=principal
            )
            if preview.expected_pointer != current.pointer:
                raise _denied("CALENDAR_RENEWAL_SCOPE_CHANGED")
            commit = ConfirmCalendarPublicationUseCase(
                preparation=repository,
                publisher=PublishExchangeCalendarSnapshotUseCase(repository),
                clock=clock,
            ).execute(preview.confirmation_intent(), principal=principal)
            CalendarRenewalReceipt.objects.using(DEFAULT_DB_ALIAS).create(
                grant=grant,
                delivery_id=delivery_id,
                previous_activation_id=grant.activation_id,
                activation_id=commit.record.activation_id,
                event_id=commit.audit_pair.event_id,
                event_content_hash=commit.audit_pair.event_content_hash,
                outbox_id=commit.audit_pair.outbox_id,
                checked_at=commit.post_audit_checked_at,
            )
            grant.activation_id = commit.record.activation_id
            grant.verified_at = commit.post_audit_checked_at
            grant.save(using=DEFAULT_DB_ALIAS, update_fields=["activation_id", "verified_at"])
            principal.assert_live()
        finally:
            principal.deactivate()
    return "renewed"
