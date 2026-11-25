"""Revocable SZSE renewal decisions and their formal publication receipts."""

from uuid import uuid4

from django.db import models


class CalendarRenewalGrant(models.Model):
    """One owner's bounded delegation over an existing SZSE publication chain."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner_user_id = models.PositiveBigIntegerField()
    publish_grant_id = models.PositiveBigIntegerField()
    delegate_grant_id = models.PositiveBigIntegerField()
    dataset_key = models.CharField(max_length=160)
    coverage_start = models.DateField()
    coverage_end = models.DateField()
    issued_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)
    activation_id = models.CharField(max_length=300)
    verified_at = models.DateTimeField()

    class Meta:
        permissions = (("delegate_szse_calendar_renewal", "Delegate renewal of the SZSE calendar"),)
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_key"],
                condition=models.Q(revoked_at__isnull=True),
                name="dc_szse_one_renewal_grant",
            ),
        ]


class CalendarRenewalReceipt(models.Model):
    """Link an automated confirmation to its owner's decision and exact audit pair."""

    grant = models.ForeignKey(CalendarRenewalGrant, on_delete=models.PROTECT)
    delivery_id = models.UUIDField()
    previous_activation_id = models.CharField(max_length=300)
    activation_id = models.CharField(max_length=300, unique=True)
    event_id = models.CharField(max_length=300)
    event_content_hash = models.CharField(max_length=64)
    outbox_id = models.UUIDField()
    checked_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["grant", "delivery_id"], name="dc_szse_renewal_delivery"
            ),
        ]
