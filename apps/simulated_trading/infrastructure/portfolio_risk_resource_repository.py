"""Locked exact simulated-account snapshot reader for Portfolio Risk."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Literal

from django.db import DEFAULT_DB_ALIAS, transaction
from django.db.models import Q
from django.utils import timezone

from apps.risk_center.application.portfolio_risk_snapshot import (
    AccountSnapshot,
    ExecutedUsage,
    HeldPosition,
    OpenOrder,
)
from apps.simulated_trading.application.performance_use_cases import (
    ObserverGrantRepositoryProtocol,
)
from apps.simulated_trading.application.portfolio_risk_resource_ports import (
    AccountSnapshotReadResult,
    NativeAccountRiskLimits,
    PortfolioRiskAccountScope,
    PortfolioRiskIdentityIssue,
    PortfolioRiskResourceSnapshotReaderProtocol,
)
from apps.simulated_trading.application.rebalance_resource_snapshot import (
    RebalanceResourceSnapshot,
    RebalanceResourceSnapshotReader,
)
from apps.simulated_trading.infrastructure.rebalance_resource_snapshot_repository import (
    DjangoRebalanceResourceSnapshotRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
    SimulatedTradeModel,
)

MoneyUnitBasis = Literal["native_simulated_ledger_config", "unknown"]


class DjangoPortfolioRiskResourceRepository(PortfolioRiskResourceSnapshotReaderProtocol):
    """Read locked exact ledger resources with owner or valid observer read scope."""

    def __init__(
        self,
        *,
        observer_grant_repository: ObserverGrantRepositoryProtocol,
        using: str = DEFAULT_DB_ALIAS,
        rebalance_snapshot_reader: RebalanceResourceSnapshotReader | None = None,
    ) -> None:
        """Bind account, observer, and exact resource reads to one database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be a nonempty database alias")
        self._observer_grants = observer_grant_repository
        self._using = using
        self._rebalance_snapshots = (
            rebalance_snapshot_reader
            if rebalance_snapshot_reader is not None
            else DjangoRebalanceResourceSnapshotRepository(using=using)
        )

    def read_account_scope(
        self,
        *,
        user_id: int,
        account_id: int,
    ) -> PortfolioRiskAccountScope | None:
        """Resolve owner/delegated read scope without loading account balances."""

        if (
            type(user_id) is not int
            or user_id <= 0
            or type(account_id) is not int
            or account_id <= 0
        ):
            return None
        with transaction.atomic(using=self._using):
            account = (
                SimulatedAccountModel._default_manager.using(self._using)
                .select_for_update()
                .only("pk", "user_id", "account_type", "is_active")
                .filter(pk=account_id, account_type="simulated", is_active=True)
                .first()
            )
            if account is None or type(account.user_id) is not int or account.user_id <= 0:
                return None
            owner_user_id = account.user_id
            if user_id != owner_user_id and not self._has_valid_observer_grant(
                owner_user_id=owner_user_id,
                observer_user_id=user_id,
            ):
                return None
            return PortfolioRiskAccountScope(
                owner_user_id=owner_user_id,
                can_read=True,
                can_write=user_id == owner_user_id,
            )

    def read_account_snapshot(
        self,
        *,
        user_id: int,
        account_id: int,
        execution_session: date,
        money_unit: str | None,
    ) -> AccountSnapshotReadResult:
        """Return an exact owner snapshot or a non-disclosing scope/read failure."""

        if (
            type(user_id) is not int
            or user_id <= 0
            or type(account_id) is not int
            or account_id <= 0
            or type(execution_session) is not date
        ):
            return self._unavailable_scope()
        money_unit_invalid = money_unit is not None and (
            type(money_unit) is not str
            or not money_unit.strip()
            or money_unit.strip() != money_unit
        )
        money_unit_basis: MoneyUnitBasis = (
            "native_simulated_ledger_config"
            if money_unit is not None and not money_unit_invalid
            else "unknown"
        )
        try:
            with transaction.atomic(using=self._using):
                account = (
                    SimulatedAccountModel._default_manager.using(self._using)
                    .select_for_update()
                    .only("pk", "user_id", "account_type", "is_active")
                    .filter(
                        pk=account_id,
                        account_type="simulated",
                        is_active=True,
                    )
                    .first()
                )
                if account is None or type(account.user_id) is not int or account.user_id <= 0:
                    return self._unavailable_scope(money_unit_basis=money_unit_basis)
                owner_user_id = account.user_id
                if user_id != owner_user_id and not self._has_valid_observer_grant(
                    owner_user_id=owner_user_id,
                    observer_user_id=user_id,
                ):
                    return self._unavailable_scope(money_unit_basis=money_unit_basis)

                scope = PortfolioRiskAccountScope(
                    owner_user_id=owner_user_id,
                    can_read=True,
                    can_write=user_id == owner_user_id,
                )
                if money_unit_invalid:
                    return self._scoped_unavailable(
                        scope=scope,
                        reason_code="simulated_money_unit_invalid",
                        money_unit_basis=money_unit_basis,
                    )
                resources = self._rebalance_snapshots.read_account_snapshot(
                    account_id=account_id,
                    user_id=owner_user_id,
                )
                if resources is None:
                    return self._scoped_unavailable(
                        scope=scope,
                        reason_code="simulated_resource_snapshot_unavailable",
                        money_unit_basis=money_unit_basis,
                    )
                if not resources.exact_balances_complete:
                    return self._scoped_unavailable(
                        scope=scope,
                        reason_code="simulated_exact_positions_incomplete",
                        money_unit_basis=money_unit_basis,
                    )

                native_account_limits = self._read_native_account_limits(resources)
                exact_snapshot, identity_issues = self._build_exact_snapshot(
                    account_id=account_id,
                    owner_user_id=owner_user_id,
                    execution_session=execution_session,
                    money_unit=money_unit,
                    native_account_limits=native_account_limits,
                    resources=resources,
                )
                return AccountSnapshotReadResult(
                    snapshot=exact_snapshot,
                    scope=scope,
                    native_account_limits=native_account_limits,
                    reason_codes=(),
                    identity_issues=identity_issues,
                    money_unit_basis=money_unit_basis,
                )
        except (ArithmeticError, AttributeError, TypeError, ValueError):
            return self._scoped_unavailable_after_read_failure(
                user_id=user_id,
                account_id=account_id,
                money_unit_basis=money_unit_basis,
            )

    def _has_valid_observer_grant(
        self,
        *,
        owner_user_id: int,
        observer_user_id: int,
    ) -> bool:
        """Use the existing simulated-trading owner/observer authorization port."""

        return self._observer_grants.has_valid_grant(owner_user_id, observer_user_id)

    def _build_exact_snapshot(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        execution_session: date,
        money_unit: str | None,
        native_account_limits: NativeAccountRiskLimits,
        resources: RebalanceResourceSnapshot,
    ) -> tuple[AccountSnapshot, tuple[PortfolioRiskIdentityIssue, ...]]:
        """Build immutable exact Decimal values while the account lock is held."""

        reservation_ids_by_code: dict[str, set[str]] = defaultdict(set)
        for reservation in resources.active_reservations:
            reservation_ids_by_code[reservation.asset_code].add(reservation.security_id)

        asset_codes = tuple(
            sorted(
                {row.asset_code for row in resources.exact_position_balances}
                | set(reservation_ids_by_code)
            )
        )
        trade_security_ids_by_code = self._read_trade_security_ids(
            account_id=account_id,
            asset_codes=asset_codes,
        )
        all_codes = set(asset_codes) | set(trade_security_ids_by_code)
        identity_issues: list[PortfolioRiskIdentityIssue] = []
        security_by_code: dict[str, str | None] = {}
        for asset_code in sorted(all_codes):
            security_ids = set(reservation_ids_by_code.get(asset_code, set()))
            security_ids.update(trade_security_ids_by_code.get(asset_code, set()))
            if len(security_ids) > 1:
                security_by_code[asset_code] = None
                identity_issues.append(
                    PortfolioRiskIdentityIssue(asset_code=asset_code, kind="conflict")
                )
            elif security_ids:
                security_by_code[asset_code] = next(iter(security_ids))
            else:
                security_by_code[asset_code] = None
                identity_issues.append(
                    PortfolioRiskIdentityIssue(asset_code=asset_code, kind="missing")
                )

        holdings = tuple(
            HeldPosition(
                asset_code=row.asset_code,
                quantity=row.quantity,
                available_quantity=row.available_quantity,
                security_id=security_by_code.get(row.asset_code),
            )
            for row in resources.exact_position_balances
        )
        active_orders = tuple(
            OpenOrder(
                order_id=str(row.reservation_id),
                asset_code=row.asset_code,
                security_id=row.security_id,
                side=row.side,
                remaining_quantity=row.remaining_quantity,
                remaining_amount=row.remaining_amount,
                remaining_cash=row.remaining_cash,
            )
            for row in resources.active_reservations
        )
        active_orders_complete = all(
            order.remaining_quantity is not None
            and order.remaining_amount is not None
            and order.remaining_cash is not None
            for order in active_orders
        )
        executed_usage, executed_usage_complete = self._read_executed_usage(
            account_id=account_id,
            execution_session=execution_session,
        )
        read_at = timezone.now()
        cash = resources.exact_cash
        snapshot_payload = {
            "account_id": account_id,
            "owner_user_id": owner_user_id,
            "read_at": read_at.isoformat(),
            "cash": self._decimal_text(cash),
            "money_unit": money_unit,
            "money_unit_basis": (
                "native_simulated_ledger_config" if money_unit is not None else "unknown"
            ),
            "native_account_limits": {
                "max_single_weight": self._decimal_text(native_account_limits.max_single_weight),
                "max_total_weight": self._decimal_text(native_account_limits.max_total_weight),
                "reason_codes": native_account_limits.reason_codes,
                "basis": native_account_limits.basis,
            },
            "holdings": [
                {
                    "asset_code": row.asset_code,
                    "quantity": self._decimal_text(row.quantity),
                    "available_quantity": self._decimal_text(row.available_quantity),
                    "security_id": row.security_id,
                }
                for row in holdings
            ],
            "active_orders": [
                {
                    "order_id": row.order_id,
                    "asset_code": row.asset_code,
                    "security_id": row.security_id,
                    "side": row.side,
                    "remaining_quantity": self._decimal_text(row.remaining_quantity),
                    "remaining_amount": self._decimal_text(row.remaining_amount),
                    "remaining_cash": self._decimal_text(row.remaining_cash),
                }
                for row in active_orders
            ],
            "executed_usage": [
                {
                    "asset_code": row.asset_code,
                    "security_id": row.security_id,
                    "execution_session": (
                        row.execution_session.isoformat()
                        if row.execution_session is not None
                        else None
                    ),
                    "quantity": self._decimal_text(row.quantity),
                    "amount": self._decimal_text(row.amount),
                    "complete": row.complete,
                }
                for row in executed_usage
            ],
            "active_orders_complete": active_orders_complete,
            "execution_session": execution_session.isoformat(),
            "executed_usage_complete": executed_usage_complete,
            "identity_issues": [
                {"asset_code": issue.asset_code, "kind": issue.kind} for issue in identity_issues
            ],
        }
        canonical = json.dumps(
            snapshot_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        snapshot = AccountSnapshot(
            account_id=account_id,
            owner_user_id=owner_user_id,
            snapshot_id=f"simulated-account:{account_id}:{digest}",
            read_at=read_at,
            cash=cash,
            money_unit=money_unit,
            holdings=holdings,
            active_orders=active_orders,
            executed_usage=executed_usage,
            active_orders_complete=active_orders_complete,
            execution_session=execution_session,
            executed_usage_complete=executed_usage_complete,
        )
        return snapshot, tuple(identity_issues)

    @classmethod
    def _read_native_account_limits(
        cls,
        resources: RebalanceResourceSnapshot,
    ) -> NativeAccountRiskLimits:
        """Decode the locked account percentage fields without guessing defaults."""

        single_weight, single_reason = cls._weight_from_percent(
            resources.account.max_position_pct,
            reason_code="native_single_weight_unknown",
        )
        total_weight, total_reason = cls._weight_from_percent(
            resources.account.max_total_position_pct,
            reason_code="native_total_weight_unknown",
        )
        reasons = tuple(reason for reason in (single_reason, total_reason) if reason is not None)
        return NativeAccountRiskLimits(
            max_single_weight=single_weight,
            max_total_weight=total_weight,
            reason_codes=reasons,
            basis="simulated_account_percent_fields",
        )

    @staticmethod
    def _weight_from_percent(
        value: object,
        *,
        reason_code: str,
    ) -> tuple[Decimal | None, str | None]:
        """Convert one stored account FloatField percentage to a precise fraction."""

        if type(value) is not float:
            return None, reason_code
        try:
            percent = Decimal(str(value))
        except (ArithmeticError, TypeError, ValueError):
            return None, reason_code
        if not percent.is_finite() or percent < 0 or percent > Decimal("100"):
            return None, reason_code
        return percent / Decimal("100"), None

    def _read_trade_security_ids(
        self,
        *,
        account_id: int,
        asset_codes: tuple[str, ...],
    ) -> dict[str, set[str]]:
        """Read exact historical settlement identities for currently held/held-order assets."""

        if not asset_codes:
            return {}
        rows = (
            SimulatedTradeModel._default_manager.using(self._using)
            .filter(
                account_id=account_id,
                status="executed",
                asset_code__in=asset_codes,
                settlement_security_id__isnull=False,
            )
            .order_by("pk")
            .values_list("asset_code", "settlement_security_id")
        )
        security_ids_by_code: dict[str, set[str]] = defaultdict(set)
        for asset_code, security_id in rows:
            if type(asset_code) is str and type(security_id) is str and security_id.strip():
                security_ids_by_code[asset_code].add(security_id)
        return dict(security_ids_by_code)

    def _read_executed_usage(
        self,
        *,
        account_id: int,
        execution_session: date,
    ) -> tuple[tuple[ExecutedUsage, ...], bool]:
        """Aggregate only exact-session trades and surface unresolved legacy candidates."""

        rows = (
            SimulatedTradeModel._default_manager.using(self._using)
            .filter(account_id=account_id, status="executed")
            .filter(
                Q(settlement_market_session=execution_session)
                | Q(
                    settlement_market_session__isnull=True,
                    execution_date=execution_session,
                )
            )
            .select_for_update()
            .order_by("pk")
        )
        aggregates: dict[
            tuple[str, str | None, date | None, bool],
            tuple[Decimal | None, Decimal | None],
        ] = {}
        all_complete = True
        for row in rows:
            asset_code = row.asset_code
            raw_security_id = row.settlement_security_id
            security_id = (
                raw_security_id
                if type(raw_security_id) is str and raw_security_id.strip()
                else None
            )
            row_session = row.settlement_market_session
            exact_session = type(row_session) is date
            exact_identity = security_id is not None
            quantity = self._known_nonnegative_decimal(row.quantity)
            amount = self._known_nonnegative_decimal(row.amount)
            row_complete = (
                exact_session and exact_identity and quantity is not None and amount is not None
            )
            if not row_complete:
                all_complete = False
            key = (
                asset_code,
                security_id,
                row_session if exact_session else None,
                row_complete,
            )
            old_quantity, old_amount = aggregates.get(key, (Decimal("0"), Decimal("0")))
            aggregates[key] = (
                self._add_optional(old_quantity, quantity),
                self._add_optional(old_amount, amount),
            )
        usage = tuple(
            ExecutedUsage(
                asset_code=asset_code,
                security_id=security_id,
                execution_session=session,
                quantity=quantity,
                amount=amount,
                complete=(
                    row_complete
                    and quantity is not None
                    and amount is not None
                    and security_id is not None
                    and session is not None
                ),
            )
            for (asset_code, security_id, session, row_complete), (quantity, amount) in sorted(
                aggregates.items(),
                key=lambda item: (
                    item[0][0],
                    item[0][2].isoformat() if item[0][2] is not None else "",
                    item[0][1] or "",
                    item[0][3],
                ),
            )
        )
        return usage, all_complete

    @staticmethod
    def _known_nonnegative_decimal(value: object) -> Decimal | None:
        """Keep only finite exact nonnegative ledger Decimal values."""

        if type(value) is not Decimal or not value.is_finite() or value < 0:
            return None
        return value

    @staticmethod
    def _add_optional(left: Decimal | None, right: Decimal | None) -> Decimal | None:
        """Add exact measures while preserving an unknown component."""

        if left is None or right is None:
            return None
        return left + right

    @staticmethod
    def _decimal_text(value: Decimal | None) -> str | None:
        """Serialize exact amounts without a float conversion."""

        return format(value, "f") if value is not None else None

    @staticmethod
    def _unavailable_scope(
        *,
        money_unit_basis: MoneyUnitBasis = "unknown",
    ) -> AccountSnapshotReadResult:
        """Return an empty result that does not reveal whether an account exists."""

        return AccountSnapshotReadResult(
            snapshot=None,
            scope=None,
            native_account_limits=None,
            reason_codes=(),
            identity_issues=(),
            money_unit_basis=money_unit_basis,
        )

    @staticmethod
    def _scoped_unavailable(
        *,
        scope: PortfolioRiskAccountScope,
        reason_code: str,
        money_unit_basis: MoneyUnitBasis,
    ) -> AccountSnapshotReadResult:
        """Return an authorized scope with a stable unavailable reason."""

        return AccountSnapshotReadResult(
            snapshot=None,
            scope=scope,
            native_account_limits=None,
            reason_codes=(reason_code,),
            identity_issues=(),
            money_unit_basis=money_unit_basis,
        )

    def _scoped_unavailable_after_read_failure(
        self,
        *,
        user_id: int,
        account_id: int,
        money_unit_basis: MoneyUnitBasis,
    ) -> AccountSnapshotReadResult:
        """Recheck scope without returning internal read exception details."""

        try:
            with transaction.atomic(using=self._using):
                account = (
                    SimulatedAccountModel._default_manager.using(self._using)
                    .only("pk", "user_id", "account_type", "is_active")
                    .filter(pk=account_id, account_type="simulated", is_active=True)
                    .first()
                )
                if account is None or type(account.user_id) is not int or account.user_id <= 0:
                    return self._unavailable_scope(money_unit_basis=money_unit_basis)
                owner_user_id = account.user_id
                allowed = user_id == owner_user_id or self._has_valid_observer_grant(
                    owner_user_id=owner_user_id,
                    observer_user_id=user_id,
                )
                if not allowed:
                    return self._unavailable_scope(money_unit_basis=money_unit_basis)
                return self._scoped_unavailable(
                    scope=PortfolioRiskAccountScope(
                        owner_user_id=owner_user_id,
                        can_read=True,
                        can_write=user_id == owner_user_id,
                    ),
                    reason_code="simulated_resource_snapshot_invalid",
                    money_unit_basis=money_unit_basis,
                )
        except (AttributeError, TypeError, ValueError):
            return self._unavailable_scope(money_unit_basis=money_unit_basis)


__all__ = ["DjangoPortfolioRiskResourceRepository"]
