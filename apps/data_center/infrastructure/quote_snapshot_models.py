"""Django ORM model for canonical quote snapshots."""

from typing import Any

from django.db import models


class QuoteSnapshotModel(models.Model):
    """Intraday real-time quote snapshot.

    Publication-referenced rows are immutable; later ingestion adds a revision.
    Natural key: (asset_code, snapshot_at, source, revision_number).
    """

    asset_code = models.CharField(max_length=20, db_index=True)
    snapshot_at = models.DateTimeField(db_index=True)
    fetched_at = models.DateTimeField(null=True, blank=True, db_index=True)
    current_price = models.DecimalField(max_digits=18, decimal_places=4)
    open = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    high = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    low = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    prev_close = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    volume = models.DecimalField(max_digits=24, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField(max_digits=24, decimal_places=2, null=True, blank=True)
    bid = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    ask = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    change_pct = models.DecimalField(max_digits=38, decimal_places=12, null=True, blank=True)
    source = models.CharField(max_length=50)
    extra = models.JSONField(default=dict, blank=True)
    contract_version = models.CharField(max_length=40, default="1.0")
    schema_version = models.CharField(max_length=40, default="1.0")
    source_record_id = models.CharField(max_length=200, blank=True)
    raw_payload_hash = models.CharField(max_length=128, blank=True, db_index=True)
    quality_status = models.CharField(max_length=40, default="accepted", db_index=True)
    revision_number = models.PositiveSmallIntegerField(default=1)
    ingested_run_id = models.UUIDField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "data_center_quote_snapshot"
        unique_together = [("asset_code", "snapshot_at", "source", "revision_number")]
        indexes = [
            models.Index(fields=["asset_code", "snapshot_at"]),
        ]
        ordering = ["-snapshot_at"]
        verbose_name = "Quote Snapshot"
        verbose_name_plural = "Quote Snapshots"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(current_price__gt=0) & ~models.Q(asset_code="") & ~models.Q(source="")
                ),
                name="dc_quote_executable_price",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.asset_code} @ {self.snapshot_at} = {self.current_price}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate canonical price invariants before persisting a quote."""

        self.validate_constraints()
        super().save(*args, **kwargs)
