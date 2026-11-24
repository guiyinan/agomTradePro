"""Restore an account's actual Risk configuration and seal its five source components."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from django.db import connections, models
from django.db.models import Q

from apps.risk_center.application.broker_order_execution_policy import (
    BrokerOrderExecutionPolicySourceRef,
    BrokerOrderExecutionPolicySourceSnapshot,
    BrokerOrderExecutionPolicyUnavailable,
)
from apps.risk_center.application.use_cases import ResolveEffectiveRiskPolicyForAccountUseCase
from apps.risk_center.domain.broker_order_execution_policy import BrokerOrderExecutionRiskControls
from apps.risk_center.infrastructure.models import (
    AccountRiskPolicyModel,
    GlobalRiskFloorModel,
    RiskExceptionModel,
    RiskTemplateModel,
)


def lock_risk_configuration(*, using: str) -> None:
    """Fence changes and phantom insertions in all five configuration sources."""
    db = connections[using]
    if using != "default" or db.vendor != "postgresql" or not db.in_atomic_block:
        raise BrokerOrderExecutionPolicyUnavailable(
            "broker_risk_configuration_transaction_required"
        )
    with db.cursor() as cur:
        cur.execute(
            "LOCK TABLE risk_center_account_policy, risk_center_exception, risk_center_global_floor, risk_center_template IN SHARE MODE NOWAIT"
        )


def _row_fields(row: models.Model) -> dict[str, object]:
    return {field.attname: getattr(row, field.attname) for field in row._meta.concrete_fields}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class LiveBrokerPolicySources:
    """Bind the source to one account, policy identity and human-certified expiry."""

    account_id: int
    policy_id: str
    policy_version: str
    valid_until: datetime
    using: str

    @property
    def source_id(self) -> str:
        """Name the account's specific activated policy without trusting supplied source IDs."""
        return "risk-account-" + _digest([self.account_id, self.policy_id])

    def get_exact_active(
        self, *, source_snapshot_id: str, source_snapshot_version: str, as_of: datetime
    ) -> BrokerOrderExecutionPolicySourceSnapshot | None:
        """Read the actual source and prevent fallback to unpersisted default controls."""
        if (
            (source_snapshot_id, source_snapshot_version) != (self.source_id, self.policy_version)
            or as_of.utcoffset() is None
            or self.valid_until.utcoffset() is None
            or as_of >= self.valid_until
        ):
            return None
        lock_risk_configuration(using=self.using)
        floors = list(
            GlobalRiskFloorModel._default_manager.using(self.using)
            .filter(is_active=True)
            .order_by("pk")[:2]
        )
        account = (
            AccountRiskPolicyModel._default_manager.using(self.using)
            .filter(account_id=self.account_id, is_active=True, template__is_active=True)
            .select_related("template")
            .first()
        )
        if (
            len(floors) != 1
            or account is None
            or account.template is None
            or account.risk_profile not in dict(RiskTemplateModel.RISK_PROFILE_CHOICES)
        ):
            return None
        template: RiskTemplateModel = account.template
        exceptions = list(
            RiskExceptionModel._default_manager.using(self.using)
            .filter(
                Q(account_id=self.account_id) | Q(account_id__isnull=True),
                is_active=True,
                expires_at__gt=as_of,
            )
            .order_by("pk")
        )
        if any(e.expires_at < self.valid_until for e in exceptions) or len(
            {e.field_name for e in exceptions}
        ) != len(exceptions):
            return None
        recorded = max(
            floors[0].updated_at,
            account.updated_at,
            template.updated_at,
            *(e.updated_at for e in exceptions),
        )
        if recorded > as_of:
            return None

        def ref(kind: str, rows: list[models.Model]) -> BrokerOrderExecutionPolicySourceRef:
            # Empty exception sets are observed under the same table fence as nonempty sets.
            content = _digest([kind, self.account_id, [_row_fields(r) for r in rows]])
            return BrokerOrderExecutionPolicySourceRef(
                kind,
                self.source_id + "-" + kind,
                content,
                content,
                recorded,
                self.valid_until.astimezone(UTC),
            )

        refs = (
            ref("account_override", [account]),
            ref("account_exceptions", [e for e in exceptions if e.account_id is not None]),
            ref("floor", [floors[0]]),
            ref("global_exceptions", [e for e in exceptions if e.account_id is None]),
            ref("template", [template]),
        )
        raw = ResolveEffectiveRiskPolicyForAccountUseCase().execute(account_id=self.account_id)[
            "parameters"
        ]

        def number(name: str) -> Decimal:
            value = raw.get(name)
            if type(value) not in (float, int, Decimal):
                raise BrokerOrderExecutionPolicyUnavailable(
                    "broker_risk_incomplete_numeric_control"
                )
            return Decimal(str(value))

        codes = raw.get("hard_exclusions")
        if not isinstance(codes, (list, tuple)) or any(
            type(s) is not str or s != s.strip().upper() for s in codes
        ):
            raise BrokerOrderExecutionPolicyUnavailable("broker_risk_exclusions_invalid")
        force_stop_loss = raw.get("force_stop_loss")
        if type(force_stop_loss) is not bool or len(codes) != len(set(codes)):
            raise BrokerOrderExecutionPolicyUnavailable("broker_risk_incomplete_controls")
        controls = BrokerOrderExecutionRiskControls(
            max_total_position_pct=number("max_total_position_pct"),
            max_single_position_pct=number("max_single_position_pct"),
            max_daily_loss_pct=number("max_daily_loss_pct"),
            max_drawdown_pct=number("max_drawdown_pct"),
            max_stop_loss_pct=number("max_stop_loss_pct"),
            take_profit_pct=number("take_profit_pct"),
            min_cash_pct=number("min_cash_pct"),
            force_stop_loss=force_stop_loss,
            hard_exclusions=tuple(sorted(codes)),
        )
        return BrokerOrderExecutionPolicySourceSnapshot(
            self.source_id,
            self.policy_version,
            self.account_id,
            controls,
            refs,
            recorded,
            self.valid_until,
        )
