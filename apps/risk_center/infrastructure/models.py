"""Django ORM models for centralized risk control."""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

PCT_VALIDATORS = [MinValueValidator(0.0), MaxValueValidator(1.0)]


class RiskParameterMixin(models.Model):
    max_total_position_pct = models.FloatField(null=True, blank=True, validators=PCT_VALIDATORS)
    max_single_position_pct = models.FloatField(null=True, blank=True, validators=PCT_VALIDATORS)
    max_daily_loss_pct = models.FloatField(null=True, blank=True, validators=PCT_VALIDATORS)
    max_drawdown_pct = models.FloatField(null=True, blank=True, validators=PCT_VALIDATORS)
    max_stop_loss_pct = models.FloatField(null=True, blank=True, validators=PCT_VALIDATORS)
    take_profit_pct = models.FloatField(null=True, blank=True, validators=PCT_VALIDATORS)
    min_cash_pct = models.FloatField(null=True, blank=True, validators=PCT_VALIDATORS)
    force_stop_loss = models.BooleanField(null=True, blank=True)
    hard_exclusions = models.JSONField(default=list, blank=True)

    class Meta:
        abstract = True

    def to_parameter_dict(self) -> dict:
        return {
            "max_total_position_pct": self.max_total_position_pct,
            "max_single_position_pct": self.max_single_position_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_stop_loss_pct": self.max_stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "min_cash_pct": self.min_cash_pct,
            "force_stop_loss": self.force_stop_loss,
            "hard_exclusions": self.hard_exclusions or [],
        }


class GlobalRiskFloorModel(RiskParameterMixin):
    name = models.CharField(max_length=100, default="Global Risk Floor")
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_global_floor"
        verbose_name = "Global Risk Floor"
        verbose_name_plural = "Global Risk Floors"
        indexes = [models.Index(fields=["is_active"])]
        ordering = ["-is_active", "-updated_at"]

    def __str__(self) -> str:
        return f"{self.name} ({'active' if self.is_active else 'inactive'})"


class RiskTemplateModel(RiskParameterMixin):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"
    CUSTOM = "custom"
    RISK_PROFILE_CHOICES = [
        (CONSERVATIVE, "Conservative"),
        (MODERATE, "Moderate"),
        (AGGRESSIVE, "Aggressive"),
        (CUSTOM, "Custom"),
    ]

    key = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=120)
    risk_profile = models.CharField(
        max_length=20,
        choices=RISK_PROFILE_CHOICES,
        default=MODERATE,
        db_index=True,
    )
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_template"
        verbose_name = "Risk Template"
        verbose_name_plural = "Risk Templates"
        ordering = ["risk_profile", "key"]
        indexes = [models.Index(fields=["risk_profile", "is_active"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"


class AccountRiskPolicyModel(RiskParameterMixin):
    account_id = models.PositiveIntegerField(unique=True, db_index=True)
    template = models.ForeignKey(
        "risk_center.RiskTemplateModel",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="account_policies",
    )
    risk_profile = models.CharField(
        max_length=20,
        choices=RiskTemplateModel.RISK_PROFILE_CHOICES,
        null=True,
        blank=True,
        db_index=True,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_account_policy"
        verbose_name = "Account Risk Policy"
        verbose_name_plural = "Account Risk Policies"
        ordering = ["account_id"]
        indexes = [models.Index(fields=["account_id", "is_active"])]

    def __str__(self) -> str:
        return f"AccountRiskPolicy(account_id={self.account_id})"


class RiskExceptionModel(models.Model):
    account_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    field_name = models.CharField(max_length=64, db_index=True)
    allowed_value = models.JSONField()
    reason = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="risk_exceptions_created",
    )
    expires_at = models.DateTimeField(db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_exception"
        verbose_name = "Risk Exception"
        verbose_name_plural = "Risk Exceptions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["account_id", "field_name", "is_active"]),
            models.Index(fields=["expires_at", "is_active"]),
        ]

    @property
    def is_current(self) -> bool:
        return self.is_active and self.expires_at > timezone.now()

    def __str__(self) -> str:
        return f"RiskException({self.field_name}, account={self.account_id or '*'})"


class RiskPolicyAuditModel(models.Model):
    TARGET_FLOOR = "floor"
    TARGET_TEMPLATE = "template"
    TARGET_POLICY = "account_policy"
    TARGET_EXCEPTION = "exception"
    TARGET_CHOICES = [
        (TARGET_FLOOR, "Global Floor"),
        (TARGET_TEMPLATE, "Template"),
        (TARGET_POLICY, "Account Policy"),
        (TARGET_EXCEPTION, "Exception"),
    ]

    target_type = models.CharField(max_length=32, choices=TARGET_CHOICES, db_index=True)
    target_id = models.CharField(max_length=64, db_index=True)
    action = models.CharField(max_length=32, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="risk_policy_audits",
    )
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_policy_audit"
        verbose_name = "Risk Policy Audit"
        verbose_name_plural = "Risk Policy Audits"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["target_type", "target_id", "-created_at"])]

    def __str__(self) -> str:
        return f"RiskPolicyAudit({self.target_type}:{self.target_id}:{self.action})"


class RiskDailyReportModel(models.Model):
    account_id = models.PositiveIntegerField(db_index=True)
    report_date = models.DateField(db_index=True)
    status = models.CharField(max_length=32, db_index=True)
    risk_daily_report = models.JSONField(default=dict, blank=True)
    position_daily_report = models.JSONField(default=dict, blank=True)
    post_investment_check = models.JSONField(default=dict, blank=True)
    input_snapshot = models.JSONField(default=dict, blank=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="risk_daily_reports_generated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_daily_report"
        verbose_name = "Risk Daily Report"
        verbose_name_plural = "Risk Daily Reports"
        constraints = [
            models.UniqueConstraint(
                fields=["account_id", "report_date"],
                name="uniq_risk_daily_report_account_date",
            )
        ]
        indexes = [
            models.Index(fields=["account_id", "-report_date"]),
            models.Index(fields=["status", "-report_date"]),
        ]
        ordering = ["-report_date", "-updated_at"]

    def __str__(self) -> str:
        return f"RiskDailyReport(account_id={self.account_id}, date={self.report_date})"
