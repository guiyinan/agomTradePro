"""Django ORM models for centralized risk control."""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, router
from django.db.models.base import ModelBase
from django.utils import timezone

PCT_VALIDATORS = [MinValueValidator(0.0), MaxValueValidator(1.0)]
_M1_RISK_AUDIT_WRITE_TOKEN = object()


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

    def to_parameter_dict(self) -> dict[str, Any]:
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


class RiskPolicyAuditQuerySet(models.QuerySet["RiskPolicyAuditModel"]):
    """Protect only M1 revision audit rows from ordinary ORM mutation APIs."""

    def update(self, **kwargs: Any) -> int:
        """Reject mutation of M1 audit events or conversion into an M1 event."""

        m1_target = RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION
        if "target_type" in kwargs:
            target_type = _validate_literal_audit_target_type(kwargs["target_type"])
            if target_type == m1_target:
                raise ValidationError("M1 risk policy audit events are append-only.")
        self._for_write = True
        write_queryset = self.using(self.db)
        if write_queryset.filter(target_type=m1_target).exists():
            raise ValidationError("M1 risk policy audit events are append-only.")
        return super().update(**kwargs)

    def delete(self) -> tuple[int, dict[str, int]]:
        """Reject deletion only when the selected rows include an M1 audit event."""

        self._for_write = True
        write_queryset = self.using(self.db)
        if write_queryset.filter(
            target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION
        ).exists():
            raise ValidationError("M1 risk policy audit events are append-only.")
        return super().delete()

    def bulk_create(
        self,
        objs: Iterable[RiskPolicyAuditModel],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[RiskPolicyAuditModel]:
        """Keep M1 event creation on the repository token path."""

        rows = list(objs)
        target_types = tuple(_validate_literal_audit_target_type(row.target_type) for row in rows)
        if any(
            target_type == RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION
            for target_type in target_types
        ):
            raise ValidationError("M1 risk policy audit events require the audited repository.")
        if update_conflicts:
            self._for_write = True
            write_queryset = self.using(self.db)
            primary_keys: list[int] = []
            for row in rows:
                if row.pk is None:
                    continue
                if type(row.pk) is not int or row.pk <= 0:
                    raise ValidationError(
                        "M1 audit conflict upserts require an exact positive integer primary key."
                    )
                primary_keys.append(row.pk)
            if (
                primary_keys
                and write_queryset.filter(
                    pk__in=tuple(primary_keys),
                    target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
                ).exists()
            ):
                raise ValidationError("M1 risk policy audit events are append-only.")
        return super().bulk_create(
            rows,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )

    def bulk_update(
        self,
        objs: Iterable[RiskPolicyAuditModel],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        """Reject bulk rewrites of existing or newly marked M1 events."""

        rows = list(objs)
        field_names = tuple(fields)
        if "target_type" in field_names:
            raise ValidationError("Risk policy audit target_type cannot be bulk-updated.")
        if any(
            row.target_type == RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION for row in rows
        ):
            raise ValidationError("M1 risk policy audit events are append-only.")
        row_ids = tuple(row.pk for row in rows if row.pk is not None)
        self._for_write = True
        write_queryset = self.using(self.db)
        if (
            row_ids
            and write_queryset.filter(
                pk__in=row_ids,
                target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
            ).exists()
        ):
            raise ValidationError("M1 risk policy audit events are append-only.")
        return super().bulk_update(rows, field_names, batch_size=batch_size)


class RiskPolicyAuditModel(models.Model):
    TARGET_FLOOR = "floor"
    TARGET_TEMPLATE = "template"
    TARGET_POLICY = "account_policy"
    TARGET_EXCEPTION = "exception"
    TARGET_M1_REBALANCE_REVISION = "m1_rebalance_revision"
    TARGET_CHOICES = [
        (TARGET_FLOOR, "Global Floor"),
        (TARGET_TEMPLATE, "Template"),
        (TARGET_POLICY, "Account Policy"),
        (TARGET_EXCEPTION, "Exception"),
        (TARGET_M1_REBALANCE_REVISION, "M1 Rebalance Risk Revision"),
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
    objects = RiskPolicyAuditQuerySet.as_manager()
    _m1_repository_write_token: object | None = None

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_policy_audit"
        verbose_name = "Risk Policy Audit"
        verbose_name_plural = "Risk Policy Audits"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["target_type", "target_id", "-created_at"])]

    def __str__(self) -> str:
        return f"RiskPolicyAudit({self.target_type}:{self.target_id}:{self.action})"

    def save(
        self,
        *args: Any,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Permit M1 event insertion through its repository and reject later edits."""

        m1_target = self.TARGET_M1_REBALANCE_REVISION
        saved_fields = None if update_fields is None else tuple(update_fields)
        writes_target_type = (
            self._state.adding or saved_fields is None or "target_type" in saved_fields
        )
        target_type: str | None = None
        if writes_target_type:
            target_type = _validate_literal_audit_target_type(self.target_type)
        if self.pk is not None:
            using = using or router.db_for_write(type(self), instance=self)
            audit_manager = type(self).objects.db_manager(using)
            prior = audit_manager.filter(pk=self.pk).values("target_type").first()
            if prior is not None and prior.get("target_type") == m1_target:
                raise ValidationError("M1 risk policy audit events are append-only.")
        if target_type == m1_target and (
            getattr(self, "_m1_repository_write_token", None) is not _M1_RISK_AUDIT_WRITE_TOKEN
        ):
            raise ValidationError("M1 risk policy audit events require the audited repository.")
        super().save(
            *args,
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=saved_fields,
        )

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Protect M1 publish/revoke evidence while preserving legacy audit behavior."""

        persisted_target_type: object | None = None
        if self.pk is not None:
            using = using or router.db_for_write(type(self), instance=self)
            audit_manager = type(self).objects.db_manager(using)
            persisted = audit_manager.filter(pk=self.pk).values("target_type").first()
            if persisted is not None:
                persisted_target_type = persisted.get("target_type")
        if (
            self.target_type == self.TARGET_M1_REBALANCE_REVISION
            or persisted_target_type == self.TARGET_M1_REBALANCE_REVISION
        ):
            raise ValidationError("M1 risk policy audit events are append-only.")
        return super().delete(using=using, keep_parents=keep_parents)


def _validate_literal_audit_target_type(value: object) -> str:
    """Reject ORM expressions or unknown values before they can set row identity."""

    valid_targets = {target_type for target_type, _label in RiskPolicyAuditModel.TARGET_CHOICES}
    if type(value) is not str or value not in valid_targets:
        raise ValidationError("Risk policy audit target_type must be a supported literal value.")
    return value


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


class ImmutableScenarioRecordMixin(models.Model):
    """Reject update/delete for append-only scenario revisions and evidence."""

    class Meta:
        abstract = True

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Insert after validation and reject mutation of a stored row."""

        if not self._state.adding:
            raise ValidationError("Scenario revisions and run evidence are immutable.")
        self.full_clean()
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion of append-only scenario records."""

        raise ValidationError("Scenario revisions and run evidence cannot be deleted.")


class StressScenarioDefinitionModel(models.Model):
    """Stable identity and compatibility aliases for a stress scenario."""

    scenario_key = models.CharField(max_length=120, unique=True, db_index=True)
    name = models.CharField(max_length=160)
    category = models.CharField(max_length=80, db_index=True)
    owner = models.CharField(max_length=80, default="risk_center")
    status = models.CharField(
        max_length=16,
        choices=[("active", "Active"), ("retired", "Retired")],
        default="active",
        db_index=True,
    )
    description = models.TextField(blank=True, default="")
    legacy_aliases = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_stress_scenario_definition"
        ordering = ["category", "scenario_key"]
        indexes = [models.Index(fields=["status", "category"], name="risk_scn_def_status_cat")]

    def __str__(self) -> str:
        return f"{self.name} ({self.scenario_key})"


class StressScenarioRevisionModel(ImmutableScenarioRecordMixin):
    """Append-only typed content revision for a stress scenario."""

    revision_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    definition = models.ForeignKey(
        "risk_center.StressScenarioDefinitionModel",
        on_delete=models.PROTECT,
        related_name="revisions",
    )
    version = models.PositiveIntegerField()
    based_on_version = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=[
            ("candidate", "Candidate"),
            ("draft", "Draft"),
            ("proposed", "Proposed"),
            ("approved", "Approved"),
            ("active", "Active"),
            ("superseded", "Superseded"),
            ("rejected", "Rejected"),
        ],
        db_index=True,
    )
    scenario_type = models.CharField(
        max_length=32,
        choices=[
            ("historical_window", "Historical window"),
            ("rolling_extreme", "Rolling extreme"),
            ("parametric_shock", "Parametric shock"),
            ("macro_path", "Macro path"),
        ],
        db_index=True,
    )
    parameters = models.JSONField(default=dict)
    assumptions = models.JSONField(default=list, blank=True)
    source_evidence = models.JSONField(default=list, blank=True)
    source_type = models.CharField(
        max_length=32,
        choices=[
            ("human", "Human"),
            ("ai_mcp", "AI MCP"),
            ("seed", "Seed"),
            ("detector", "Detector"),
            ("legacy_code_migration", "Legacy code migration"),
        ],
        db_index=True,
    )
    content_hash = models.CharField(max_length=64, db_index=True)
    created_by = models.CharField(max_length=150)
    change_reason = models.TextField()
    effective_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_stress_scenario_revision"
        ordering = ["definition_id", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["definition", "version"],
                name="risk_scn_revision_version_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="risk_scn_revision_ver_pos",
            ),
            models.CheckConstraint(
                condition=models.Q(based_on_version__isnull=True)
                | models.Q(based_on_version__lt=models.F("version")),
                name="risk_scn_revision_base_lt",
            ),
        ]
        indexes = [
            models.Index(
                fields=["definition", "status", "-version"],
                name="risk_scn_rev_def_status",
            )
        ]

    def __str__(self) -> str:
        return f"{self.definition.scenario_key}@v{self.version}"


class ScenarioSetModel(models.Model):
    """Stable identity for a purpose-specific collection of scenarios."""

    set_key = models.CharField(max_length=120, unique=True, db_index=True)
    name = models.CharField(max_length=160)
    purpose = models.CharField(max_length=80, db_index=True)
    owner = models.CharField(max_length=80, default="risk_center")
    applicable_asset_scope = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=16,
        choices=[("active", "Active"), ("retired", "Retired")],
        default="active",
        db_index=True,
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_scenario_set"
        ordering = ["purpose", "set_key"]

    def __str__(self) -> str:
        return f"{self.name} ({self.set_key})"


class ScenarioSetRevisionModel(ImmutableScenarioRecordMixin):
    """Append-only revision of a scenario set."""

    revision_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scenario_set = models.ForeignKey(
        "risk_center.ScenarioSetModel",
        on_delete=models.PROTECT,
        related_name="revisions",
    )
    version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16,
        choices=StressScenarioRevisionModel._meta.get_field("status").choices,
        db_index=True,
    )
    driver_axes = models.JSONField(default=list, blank=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    created_by = models.CharField(max_length=150)
    change_reason = models.TextField()
    effective_from = models.DateTimeField(null=True, blank=True, db_index=True)
    effective_to = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_scenario_set_revision"
        ordering = ["scenario_set_id", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["scenario_set", "version"],
                name="risk_scn_set_revision_ver_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="risk_scn_set_revision_ver_pos",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_from__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_from")),
                name="risk_scn_set_effective_order",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.scenario_set.set_key}@v{self.version}"


class ScenarioSetMemberModel(ImmutableScenarioRecordMixin):
    """Probability-bearing reference from a set revision to a scenario revision."""

    scenario_set_revision = models.ForeignKey(
        "risk_center.ScenarioSetRevisionModel",
        on_delete=models.PROTECT,
        related_name="members",
    )
    scenario_revision = models.ForeignKey(
        "risk_center.StressScenarioRevisionModel",
        on_delete=models.PROTECT,
        related_name="set_memberships",
    )
    probability = models.DecimalField(
        max_digits=18,
        decimal_places=12,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    probability_source = models.CharField(
        max_length=24,
        choices=[("subjective", "Subjective"), ("model_inferred", "Model inferred")],
    )
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_scenario_set_member"
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["scenario_set_revision", "scenario_revision"],
                name="risk_scn_set_member_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(probability__gte=0, probability__lte=1),
                name="risk_scn_member_prob_range",
            ),
        ]


class ScenarioActivationModel(models.Model):
    """Historical active-set pointer; only lifecycle fields may change."""

    activation_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    environment = models.CharField(max_length=40, db_index=True)
    purpose = models.CharField(max_length=80, db_index=True)
    scenario_set_revision = models.ForeignKey(
        "risk_center.ScenarioSetRevisionModel",
        on_delete=models.PROTECT,
        related_name="activations",
    )
    previous_activation = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="replacement_activations",
    )
    activated_by = models.CharField(max_length=150)
    reason = models.TextField()
    correlation_id = models.CharField(max_length=120, blank=True, default="")
    activated_at = models.DateTimeField(default=timezone.now, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_scenario_activation"
        ordering = ["-activated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["environment", "purpose"],
                condition=models.Q(is_active=True),
                name="risk_scn_one_active_scope",
            ),
        ]
        indexes = [
            models.Index(
                fields=["environment", "purpose", "-activated_at"],
                name="risk_scn_activation_scope",
            )
        ]


class ScenarioRunEvidenceModel(ImmutableScenarioRecordMixin):
    """Append-only evidence binding scenario, portfolio, data, code, and result."""

    run_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scenario_revision = models.ForeignKey(
        "risk_center.StressScenarioRevisionModel",
        on_delete=models.PROTECT,
        related_name="run_evidence",
    )
    scenario_set_revision = models.ForeignKey(
        "risk_center.ScenarioSetRevisionModel",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="run_evidence",
    )
    portfolio_snapshot_id = models.CharField(max_length=120, db_index=True)
    portfolio_snapshot_hash = models.CharField(max_length=64)
    as_of_time = models.DateTimeField(db_index=True)
    data_evidence_ids = models.JSONField(default=list)
    result_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    allocation_policy_version = models.CharField(max_length=120)
    code_version = models.CharField(max_length=120)
    must_not_use_for_decision = models.BooleanField(default=False, db_index=True)
    blocked_reason = models.CharField(max_length=160, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        app_label = "risk_center"
        db_table = "risk_center_scenario_run_evidence"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["scenario_revision", "-created_at"],
                name="risk_scn_run_revision",
            ),
            models.Index(
                fields=["portfolio_snapshot_id", "-created_at"],
                name="risk_scn_run_portfolio",
            ),
        ]

    def clean(self) -> None:
        """Enforce decision-usable and blocked evidence shapes."""

        super().clean()
        if self.must_not_use_for_decision:
            if not self.blocked_reason.strip():
                raise ValidationError({"blocked_reason": "Blocked evidence requires a reason."})
            return
        if not self.data_evidence_ids:
            raise ValidationError({"data_evidence_ids": "Decision-usable runs require evidence."})
        if len(self.result_hash) != 64:
            raise ValidationError({"result_hash": "Decision-usable runs require SHA-256."})
