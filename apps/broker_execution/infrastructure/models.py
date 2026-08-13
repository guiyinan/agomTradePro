"""Django ORM models for governed live broker execution."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models


def default_trading_windows() -> list[str]:
    """Return the default China A-share continuous trading windows."""

    return ["09:30-11:30", "13:00-15:00"]


class BrokerAgentModel(models.Model):
    """Persisted health projection for one local QMT Agent."""

    STATUS_OFFLINE = "offline"
    STATUS_ONLINE = "online"
    STATUS_DEGRADED = "degraded"
    STATUS_CHOICES = [
        (STATUS_OFFLINE, "离线"),
        (STATUS_ONLINE, "在线"),
        (STATUS_DEGRADED, "异常"),
    ]

    agent_id = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="broker_agents",
    )
    display_name = models.CharField(max_length=100)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_OFFLINE,
        db_index=True,
    )
    qmt_connected = models.BooleanField(default=False)
    agent_version = models.CharField(max_length=32, blank=True, default="")
    last_heartbeat_at = models.DateTimeField(null=True, blank=True, db_index=True)
    health_snapshot = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_agent"
        ordering = ["display_name", "agent_id"]
        indexes = [models.Index(fields=["user", "is_active", "status"])]


class BrokerAccountBindingModel(models.Model):
    """Bind one owned system account to one local broker Agent."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="broker_account_bindings",
    )
    account_id = models.PositiveIntegerField(db_index=True)
    agent = models.ForeignKey(
        BrokerAgentModel,
        on_delete=models.PROTECT,
        related_name="account_bindings",
    )
    broker_account_ref = models.CharField(max_length=128)
    broker_account_mask = models.CharField(max_length=32, blank=True, default="")
    account_type = models.CharField(max_length=32, default="STOCK")
    auto_execution_enabled = models.BooleanField(default=False)
    max_single_order_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    daily_order_amount_limit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    max_position_count = models.PositiveIntegerField(default=20)
    max_snapshot_age_seconds = models.PositiveIntegerField(default=120)
    price_deviation_limit_pct = models.DecimalField(
        max_digits=7, decimal_places=4, default=Decimal("0.03")
    )
    allowed_trading_windows = models.JSONField(default=default_trading_windows, blank=True)
    enforce_trading_session = models.BooleanField(default=True)
    allowed_symbols = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_account_binding"
        constraints = [
            models.UniqueConstraint(fields=["account_id"], name="uq_broker_exec_account_binding"),
            models.UniqueConstraint(
                fields=["user", "account_id"], name="uq_broker_exec_user_account"
            ),
            models.UniqueConstraint(
                fields=["agent", "broker_account_ref"],
                name="uq_broker_exec_agent_account_ref",
            ),
        ]
        indexes = [models.Index(fields=["user", "is_active", "account_id"])]


class BrokerAccountAccessModel(models.Model):
    """Explicitly grant a non-owner user access to one live account."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="broker_account_access_grants",
    )
    account_id = models.PositiveIntegerField(db_index=True)
    can_approve = models.BooleanField(default=False)
    can_trade = models.BooleanField(default=False)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="broker_account_access_grants_created",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_account_access"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "account_id"], name="uq_broker_exec_access_user_account"
            )
        ]
        indexes = [models.Index(fields=["user", "account_id", "is_active"])]


class BrokerAgentCredentialModel(models.Model):
    """Hashed, scoped credential for one local Agent; raw secrets are never stored."""

    credential_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    agent = models.ForeignKey(
        BrokerAgentModel,
        on_delete=models.CASCADE,
        related_name="credentials",
    )
    secret_hash = models.CharField(max_length=64)
    scopes = models.JSONField(default=list)
    allowed_account_ids = models.JSONField(default=list)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="broker_agent_credentials_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_agent_credential"
        indexes = [models.Index(fields=["agent", "expires_at", "revoked_at"])]


class LiveOrderModel(models.Model):
    """Canonical VPS-side live-order lifecycle record."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="live_broker_orders",
    )
    account_id = models.PositiveIntegerField(db_index=True)
    agent = models.ForeignKey(
        BrokerAgentModel,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="live_orders",
    )
    client_order_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    asset_code = models.CharField(max_length=32, db_index=True)
    market = models.CharField(max_length=16, default="CN")
    side = models.CharField(max_length=8, choices=[("BUY", "买入"), ("SELL", "卖出")])
    order_type = models.CharField(max_length=16, default="LIMIT")
    quantity = models.DecimalField(max_digits=20, decimal_places=4)
    limit_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    estimated_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    status = models.CharField(max_length=32, default="WAITING_APPROVAL", db_index=True)
    source_recommendation_ids = models.JSONField(default=list, blank=True)
    source_signal_ids = models.JSONField(default=list, blank=True)
    risk_policy_version = models.CharField(max_length=128, blank=True, default="")
    risk_snapshot = models.JSONField(default=dict, blank=True)
    approval_mode = models.CharField(max_length=32, default="manual")
    approval_digest = models.CharField(max_length=64, blank=True, default="")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_live_broker_orders",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    broker_order_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    filled_quantity = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    average_fill_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    failure_code = models.CharField(max_length=64, blank=True, default="")
    failure_message = models.TextField(blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_live_order"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status", "-created_at"]),
            models.Index(fields=["account_id", "status", "-created_at"]),
        ]


class OrderLeaseModel(models.Model):
    """Exclusive short lease allowing one Agent to submit one READY order."""

    order = models.OneToOneField(
        LiveOrderModel,
        on_delete=models.CASCADE,
        related_name="lease",
    )
    agent = models.ForeignKey(
        BrokerAgentModel,
        on_delete=models.CASCADE,
        related_name="order_leases",
    )
    lease_token_hash = models.CharField(max_length=64)
    leased_at = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_order_lease"
        indexes = [models.Index(fields=["agent", "expires_at", "released_at"])]


class BrokerOrderEventModel(models.Model):
    """Append-only normalized broker event attached to an order."""

    agent = models.ForeignKey(
        BrokerAgentModel,
        on_delete=models.PROTECT,
        related_name="broker_order_events",
    )
    order = models.ForeignKey(
        LiveOrderModel,
        on_delete=models.CASCADE,
        related_name="broker_events",
    )
    event_id = models.CharField(max_length=96)
    event_type = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=32, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(db_index=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_order_event"
        ordering = ["occurred_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["agent", "event_id"],
                name="uq_broker_exec_agent_event",
            )
        ]
        indexes = [models.Index(fields=["order", "occurred_at"])]


class BrokerFillModel(models.Model):
    """Normalized immutable broker fill fact."""

    order = models.ForeignKey(
        LiveOrderModel,
        on_delete=models.CASCADE,
        related_name="fills",
    )
    agent = models.ForeignKey(BrokerAgentModel, on_delete=models.PROTECT)
    broker_account_ref = models.CharField(max_length=128)
    broker_trade_id = models.CharField(max_length=128)
    quantity = models.DecimalField(max_digits=20, decimal_places=4)
    price = models.DecimalField(max_digits=20, decimal_places=4)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    occurred_at = models.DateTimeField(db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_fill"
        constraints = [
            models.UniqueConstraint(
                fields=["broker_account_ref", "broker_trade_id"],
                name="uq_broker_exec_account_trade",
            )
        ]
        indexes = [models.Index(fields=["order", "occurred_at"])]


class BrokerAccountSnapshotModel(models.Model):
    """Persisted broker cash/asset snapshot used by reconciliation and readiness."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    agent = models.ForeignKey(BrokerAgentModel, on_delete=models.PROTECT)
    account_id = models.PositiveIntegerField(db_index=True)
    captured_at = models.DateTimeField(db_index=True)
    cash_available = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_asset = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_account_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=["agent", "account_id", "captured_at"],
                name="uq_broker_exec_account_snapshot",
            )
        ]


class BrokerPositionSnapshotModel(models.Model):
    """Persisted broker position snapshot used by pre-submit checks."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    agent = models.ForeignKey(BrokerAgentModel, on_delete=models.PROTECT)
    account_id = models.PositiveIntegerField(db_index=True)
    asset_code = models.CharField(max_length=32, db_index=True)
    quantity = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    available_quantity = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    captured_at = models.DateTimeField(db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_position_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=["agent", "account_id", "asset_code", "captured_at"],
                name="uq_broker_exec_position_snapshot",
            )
        ]


class BrokerCommandModel(models.Model):
    """Server-to-Agent command such as cancel, pause, resume, or full sync."""

    agent = models.ForeignKey(
        BrokerAgentModel,
        on_delete=models.CASCADE,
        related_name="commands",
    )
    command_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    command_type = models.CharField(max_length=32, db_index=True)
    account_id = models.PositiveIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, default="pending", db_index=True)
    leased_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_command"
        indexes = [models.Index(fields=["agent", "status", "created_at"])]


class BrokerAgentNonceModel(models.Model):
    """Short-lived replay guard for signed Agent requests."""

    credential = models.ForeignKey(BrokerAgentCredentialModel, on_delete=models.CASCADE)
    nonce_hash = models.CharField(max_length=64)
    request_id = models.CharField(max_length=128)
    seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_agent_nonce"
        constraints = [
            models.UniqueConstraint(
                fields=["credential", "nonce_hash"], name="uq_broker_exec_credential_nonce"
            )
        ]


class ReconciliationRunModel(models.Model):
    """One persisted reconciliation batch and its unresolved differences."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="broker_reconciliation_runs",
    )
    account_id = models.PositiveIntegerField(db_index=True)
    run_key = models.CharField(max_length=96, unique=True, null=True, blank=True)
    status = models.CharField(max_length=32, default="pending", db_index=True)
    order_difference_count = models.PositiveIntegerField(default=0)
    fill_difference_count = models.PositiveIntegerField(default=0)
    cash_difference_count = models.PositiveIntegerField(default=0)
    position_difference_count = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_reconciliation_run"
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["user", "status", "-started_at"])]


class ReconciliationDifferenceModel(models.Model):
    """One immutable four-dimensional reconciliation difference."""

    DIMENSION_CHOICES = [
        ("order", "委托"),
        ("fill", "成交"),
        ("cash", "资金"),
        ("position", "持仓"),
    ]
    run = models.ForeignKey(
        ReconciliationRunModel,
        on_delete=models.CASCADE,
        related_name="differences",
    )
    dimension = models.CharField(max_length=16, choices=DIMENSION_CHOICES, db_index=True)
    difference_key = models.CharField(max_length=160)
    severity = models.CharField(max_length=8, default="P1", db_index=True)
    expected = models.JSONField(default=dict, blank=True)
    actual = models.JSONField(default=dict, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=16, default="open", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_reconciliation_difference"
        constraints = [
            models.UniqueConstraint(
                fields=["run", "dimension", "difference_key"],
                name="uq_broker_exec_recon_difference",
            )
        ]
        indexes = [models.Index(fields=["run", "dimension", "status"])]


class BrokerExecutionAlertModel(models.Model):
    """Deduplicated operational alert with automatic-stop evidence."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    account_id = models.PositiveIntegerField(db_index=True)
    fingerprint = models.CharField(max_length=64, unique=True)
    code = models.CharField(max_length=64, db_index=True)
    severity = models.CharField(max_length=8, db_index=True)
    status = models.CharField(max_length=16, default="open", db_index=True)
    title = models.CharField(max_length=200)
    message = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    occurrence_count = models.PositiveIntegerField(default=1)
    auto_stop_applied = models.BooleanField(default=False)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_alert"
        ordering = ["-last_seen_at"]
        indexes = [models.Index(fields=["user", "account_id", "status", "severity"])]


class BrokerExecutionDailyReportModel(models.Model):
    """Daily execution, reconciliation, and safety summary per account."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    account_id = models.PositiveIntegerField(db_index=True)
    report_date = models.DateField(db_index=True)
    status = models.CharField(max_length=16, default="ok", db_index=True)
    metrics = models.JSONField(default=dict, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_daily_report"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "account_id", "report_date"],
                name="uq_broker_exec_daily_report",
            )
        ]
        ordering = ["-report_date", "-generated_at"]


class TradingControlModel(models.Model):
    """Account-scoped kill switch; account ID zero represents the user global switch."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="broker_trading_controls",
    )
    account_id = models.PositiveIntegerField(default=0)
    kill_switch_active = models.BooleanField(default=False, db_index=True)
    reason = models.TextField(blank=True, default="")
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="broker_trading_controls_changed",
    )
    changed_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_trading_control"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "account_id"], name="uq_broker_exec_control_user_account"
            )
        ]


class BrokerExecutionAuditModel(models.Model):
    """Append-only audit event for broker-execution actions."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="broker_execution_audits_owned",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="broker_execution_audits_acted",
    )
    actor_type = models.CharField(max_length=16, default="user")
    action = models.CharField(max_length=64, db_index=True)
    account_id = models.PositiveIntegerField(default=0, db_index=True)
    resource_type = models.CharField(max_length=64)
    resource_id = models.CharField(max_length=128)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True, default="")
    request_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_audit"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "account_id", "-created_at"])]


class BrokerExecutionIdempotencyModel(models.Model):
    """Persist one governed write result for safe request replay."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    action = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)
    response_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_idempotency"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "action", "idempotency_key"],
                name="uq_broker_exec_idempotency",
            )
        ]


from apps.broker_execution.infrastructure.broker_account_identity_snapshot_models import (  # noqa: E402,F401
    BrokerAccountIdentitySnapshotModel,
)
from apps.broker_execution.infrastructure.order_approval_artifact_models import (  # noqa: E402,F401
    BrokerOrderApprovalArtifactModel,
)
from apps.broker_execution.infrastructure.portfolio_broker_account_binding_models import (  # noqa: E402,F401
    BrokerPortfolioAccountBindingModel,
)
from apps.broker_execution.infrastructure.pre_risk_execution_scope_models import (  # noqa: E402,F401
    BrokerPreRiskExecutionScopeModel,
)
from apps.broker_execution.infrastructure.r8_monitoring_reconciliation_models import (  # noqa: E402,F401
    R8BrokerMonitoringPeriodReceiptModel,
)
