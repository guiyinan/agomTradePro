"""Persist one owner signature per prebuilt order version and irrevocable cancellation."""

from django.db import models


class BrokerOrderExecutionScopeModel(models.Model):
    """Account-bound owner signature over immutable source identities and deadlines."""

    scope_id = models.UUIDField(primary_key=True)
    client_order_id = models.UUIDField(db_index=True)
    order_version = models.PositiveIntegerField()
    account_id = models.PositiveIntegerField()
    owner_user_id = models.PositiveBigIntegerField()
    recorded_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    benchmark_approval_id = models.UUIDField()
    benchmark_approval_version = models.PositiveIntegerField()
    benchmark_content_hash = models.CharField(max_length=64)
    manifest = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    issuer_mac = models.CharField(max_length=64)
    revoked_at = models.DateTimeField(null=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_order_scope"
        constraints = [
            models.UniqueConstraint(
                fields=("client_order_id", "order_version"), name="uq_broker_order_signed_version"
            )
        ]
