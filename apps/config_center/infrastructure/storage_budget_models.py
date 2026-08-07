"""Storage budget policy persistence owned by Config Center."""

from django.db import models

from apps.config_center.domain.runtime_config import StorageBudgetPolicy


class StorageBudgetPolicyModel(models.Model):
    """Runtime storage policy; no code-level capacity fallback is implied."""

    policy_key = models.CharField(max_length=100, db_index=True)
    version = models.PositiveIntegerField()
    configured_capacity_bytes = models.PositiveBigIntegerField()
    raw_budget_ratio = models.FloatField()
    quarantine_budget_ratio = models.FloatField()
    database_budget_ratio = models.FloatField()
    logs_budget_ratio = models.FloatField()
    emergency_reserve_ratio = models.FloatField()
    warning_ratio = models.FloatField()
    critical_ratio = models.FloatField()
    active = models.BooleanField(default=False, db_index=True)
    created_by = models.CharField(max_length=150, default="system")
    activated_at = models.DateTimeField(null=True, blank=True)
    change_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "config_center_storage_budget_policy"
        ordering = ["-active", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["policy_key", "version"],
                name="config_center_storage_policy_version_unique",
            ),
            models.UniqueConstraint(
                fields=["active"],
                condition=models.Q(active=True),
                name="config_center_one_active_storage_policy",
            ),
            models.CheckConstraint(
                condition=models.Q(configured_capacity_bytes__gt=0),
                name="config_center_storage_capacity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(warning_ratio__lt=models.F("critical_ratio")),
                name="config_center_storage_warning_lt_critical",
            ),
        ]

    def to_domain(self) -> StorageBudgetPolicy:
        """Convert this policy row to a domain budget value object."""

        return StorageBudgetPolicy(
            policy_key=self.policy_key,
            version=self.version,
            configured_capacity_bytes=int(self.configured_capacity_bytes),
            raw_budget_ratio=self.raw_budget_ratio,
            quarantine_budget_ratio=self.quarantine_budget_ratio,
            database_budget_ratio=self.database_budget_ratio,
            logs_budget_ratio=self.logs_budget_ratio,
            emergency_reserve_ratio=self.emergency_reserve_ratio,
            warning_ratio=self.warning_ratio,
            critical_ratio=self.critical_ratio,
            active=self.active,
        )


__all__ = ["StorageBudgetPolicyModel"]
