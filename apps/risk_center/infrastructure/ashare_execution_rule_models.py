"""Risk-owned persistence for immutable, operator-supplied A-share rule versions."""

from __future__ import annotations

from django.db import models


class AShareExecutionRuleModel(models.Model):
    """One complete canonical A-share execution rule configuration version."""

    security_id = models.CharField(max_length=192)
    rule_id = models.CharField(max_length=192)
    rule_version = models.CharField(max_length=192)
    market = models.CharField(max_length=192)
    board = models.CharField(max_length=192)
    recorded_at = models.DateTimeField(db_index=True)
    source_available_at = models.DateTimeField()
    effective_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    content_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    retirement_effective_at = models.DateTimeField(null=True, blank=True)
    retirement_recorded_at = models.DateTimeField(null=True, blank=True)
    retirement_request_id = models.UUIDField(null=True, blank=True, unique=True)
    retirement_actor_type = models.CharField(max_length=64, null=True, blank=True)
    retirement_actor_id = models.CharField(max_length=256, null=True, blank=True)
    retirement_request_hash = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        db_table = "risk_center_ashare_execution_rule"
        indexes = [
            models.Index(
                fields=("security_id", "effective_from", "valid_until"),
                name="risk_ash_rule_effective_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("security_id", "rule_id", "rule_version"),
                name="risk_ash_rule_identity_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_from__lt=models.F("valid_until")),
                name="risk_ash_rule_effective_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(source_available_at__lt=models.F("valid_until")),
                name="risk_ash_rule_source_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        retirement_effective_at__isnull=True,
                        retirement_recorded_at__isnull=True,
                        retirement_request_id__isnull=True,
                        retirement_actor_type__isnull=True,
                        retirement_actor_id__isnull=True,
                        retirement_request_hash__isnull=True,
                    )
                    | models.Q(
                        retirement_effective_at__isnull=False,
                        retirement_recorded_at__isnull=False,
                        retirement_request_id__isnull=False,
                        retirement_actor_type__isnull=False,
                        retirement_actor_id__isnull=False,
                        retirement_request_hash__isnull=False,
                    )
                ),
                name="risk_ash_rule_retire_all_or_none_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(retirement_recorded_at__isnull=True)
                | models.Q(retirement_recorded_at__lte=models.F("retirement_effective_at")),
                name="risk_ash_rule_retire_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(retirement_effective_at__isnull=True)
                | models.Q(
                    effective_from__lte=models.F("retirement_effective_at"),
                    retirement_effective_at__lt=models.F("valid_until"),
                ),
                name="risk_ash_rule_retire_window_ck",
            ),
        ]
