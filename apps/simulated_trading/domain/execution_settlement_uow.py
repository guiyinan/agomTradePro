"""Exact simulated-ledger contracts for settlement-bound A-share trades.

The calendar values in this module describe complete date-level exchange
sessions. They do not establish an intraday phase, security tradability,
market-price validity, account authority, or broker execution permission.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from typing import Literal, Protocol, TypeAlias, cast, runtime_checkable

from .execution_settlement_calendar import (
    CalendarPublicationReference as CalendarPublicationReference,
)
from .execution_settlement_calendar import ExchangeCalendarDay as ExchangeCalendarDay
from .execution_settlement_calendar import ExchangeCalendarSnapshot as ExchangeCalendarSnapshot
from .execution_settlement_calendar import ExecutionCalendarEvidence as ExecutionCalendarEvidence
from .execution_settlement_calendar import RawCalendarReference as RawCalendarReference
from .execution_settlement_primitives import _HASH_LENGTH as _HASH_LENGTH
from .execution_settlement_primitives import _MAX_IDEMPOTENCY_LENGTH as _MAX_IDEMPOTENCY_LENGTH
from .execution_settlement_primitives import _MAX_MONEY_VALUE as _MAX_MONEY_VALUE
from .execution_settlement_primitives import _MAX_PRICE_VALUE as _MAX_PRICE_VALUE
from .execution_settlement_primitives import _MAX_SHARE_VALUE as _MAX_SHARE_VALUE
from .execution_settlement_primitives import _MAX_TOKEN_LENGTH as _MAX_TOKEN_LENGTH
from .execution_settlement_primitives import _MONEY_QUANTUM as _MONEY_QUANTUM
from .execution_settlement_primitives import _PRICE_QUANTUM as _PRICE_QUANTUM
from .execution_settlement_primitives import _SHARE_QUANTUM as _SHARE_QUANTUM
from .execution_settlement_primitives import (
    CalendarEvidenceValidationError as CalendarEvidenceValidationError,
)
from .execution_settlement_primitives import FeeCalculationPurpose as FeeCalculationPurpose
from .execution_settlement_primitives import FeeRateStoragePrecision as FeeRateStoragePrecision
from .execution_settlement_primitives import FeeRoundingPolicy as FeeRoundingPolicy
from .execution_settlement_primitives import (
    SimulatedSettlementContractError as SimulatedSettlementContractError,
)
from .execution_settlement_primitives import (
    SimulatedTradeIntentValidationError as SimulatedTradeIntentValidationError,
)
from .execution_settlement_primitives import SimulatedTradeSide as SimulatedTradeSide
from .execution_settlement_primitives import _decimal_from_text as _decimal_from_text
from .execution_settlement_primitives import _decimal_numeric_text as _decimal_numeric_text
from .execution_settlement_primitives import _decimal_text as _decimal_text
from .execution_settlement_primitives import _hash_calendar_payload as _hash_calendar_payload
from .execution_settlement_primitives import _hash_payload as _hash_payload
from .execution_settlement_primitives import _require_aware as _require_aware
from .execution_settlement_primitives import (
    _require_calendar_fact_hash as _require_calendar_fact_hash,
)
from .execution_settlement_primitives import _require_calendar_hash as _require_calendar_hash
from .execution_settlement_primitives import _require_decimal_storage as _require_decimal_storage
from .execution_settlement_primitives import _require_hash as _require_hash
from .execution_settlement_primitives import _require_token as _require_token
from .execution_settlement_primitives import _require_utc as _require_utc
from .execution_settlement_primitives import _seal_hash as _seal_hash
from .execution_settlement_primitives import _utc_text as _utc_text
from .execution_settlement_primitives import validate_ledger_money as validate_ledger_money
from .execution_settlement_primitives import validate_ledger_price as validate_ledger_price
from .execution_settlement_primitives import validate_ledger_quantity as validate_ledger_quantity

QuantityRuleDenyCode: TypeAlias = Literal[
    "QUANTITY_BELOW_MINIMUM",
    "QUANTITY_NOT_ON_STEP",
    "QUANTITY_ABOVE_MAXIMUM",
    "SELLABLE_BALANCE_INSUFFICIENT",
    "ODD_LOT_HAS_RESTRICTED_BALANCE",
    "ODD_LOT_NOT_FULL_SELLABLE_BALANCE",
]


def _execution_quantity_deny_code(
    *,
    side: SimulatedTradeSide,
    quantity: Decimal,
    minimum: Decimal,
    step: Decimal,
    maximum: Decimal,
    sell_odd_lot_mode: str,
    locked_position: tuple[Decimal, Decimal] | None = None,
) -> QuantityRuleDenyCode | None:
    """Return an existing Risk deny code for quantity and locked SELL balance."""

    if quantity > maximum:
        return "QUANTITY_ABOVE_MAXIMUM"

    on_step = quantity % step == 0
    if side is SimulatedTradeSide.BUY:
        if quantity < minimum:
            return "QUANTITY_BELOW_MINIMUM"
        return None if on_step else "QUANTITY_NOT_ON_STEP"
    if side is not SimulatedTradeSide.SELL:
        return "QUANTITY_NOT_ON_STEP"
    if quantity != quantity.to_integral_value():
        return "QUANTITY_NOT_ON_STEP"

    clear_balance = sell_odd_lot_mode == "SELLABLE_BALANCE_TO_ZERO" and (
        not on_step or quantity < minimum
    )
    odd_remainder = sell_odd_lot_mode == "SELL_ODD_REMAINDER_ONCE" and not on_step
    if sell_odd_lot_mode not in {
        "FORBID",
        "SELLABLE_BALANCE_TO_ZERO",
        "SELL_ODD_REMAINDER_ONCE",
    }:
        return "QUANTITY_NOT_ON_STEP"
    if not clear_balance and not odd_remainder:
        if not on_step:
            return "QUANTITY_NOT_ON_STEP"
        if quantity < minimum:
            return "QUANTITY_BELOW_MINIMUM"
        return None
    if locked_position is None:
        return None

    total_quantity, available_quantity = locked_position
    if quantity > available_quantity or quantity > total_quantity:
        return "SELLABLE_BALANCE_INSUFFICIENT"
    if total_quantity != available_quantity:
        return "ODD_LOT_HAS_RESTRICTED_BALANCE"
    if clear_balance:
        return None if quantity == available_quantity else "ODD_LOT_NOT_FULL_SELLABLE_BALANCE"
    if (available_quantity - quantity) % step != 0:
        return "QUANTITY_NOT_ON_STEP"
    return None


@dataclass(frozen=True, slots=True)
class SimulatedTradeIntent:
    """Exact caller intent to apply to a simulated account's local ledger."""

    account_id: int
    user_id: int
    idempotency_key: str
    side: SimulatedTradeSide
    security_id: str
    asset_code: str
    asset_name: str
    asset_type: str
    market: str
    board: str
    quantity: Decimal
    price: Decimal
    reason: str
    signal_id: int | None

    def __post_init__(self) -> None:
        """Validate stable identity and exact values before any I/O."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise SimulatedTradeIntentValidationError("account_id must be a positive integer")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise SimulatedTradeIntentValidationError("user_id must be a positive integer")
        _require_token(
            self.idempotency_key,
            "idempotency_key",
            max_length=_MAX_IDEMPOTENCY_LENGTH,
        )
        if type(self.side) is not SimulatedTradeSide:
            raise SimulatedTradeIntentValidationError("side must be a recognized trade side")
        for field_name in (
            "security_id",
            "asset_code",
            "asset_type",
            "market",
            "board",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.asset_name) is not str or not self.asset_name or len(self.asset_name) > 100:
            raise SimulatedTradeIntentValidationError(
                "asset_name must be nonempty text of at most 100 chars"
            )
        _require_decimal_storage(
            self.quantity,
            "quantity",
            quantum=_SHARE_QUANTUM,
            exclusive_maximum=_MAX_SHARE_VALUE,
        )
        _require_decimal_storage(
            self.price,
            "price",
            quantum=_PRICE_QUANTUM,
            exclusive_maximum=_MAX_PRICE_VALUE,
        )
        if type(self.reason) is not str or len(self.reason) > 200:
            raise SimulatedTradeIntentValidationError("reason must be text of at most 200 chars")
        if self.signal_id is not None and type(self.signal_id) is not int:
            raise SimulatedTradeIntentValidationError("signal_id must be an integer or None")

    @property
    def request_payload_hash(self) -> str:
        """Return a deterministic hash of all intent fields except the idempotency key."""

        self.__post_init__()
        return _hash_payload(
            {
                "account_id": self.account_id,
                "user_id": self.user_id,
                "side": self.side.value,
                "security_id": self.security_id,
                "asset_code": self.asset_code,
                "asset_name": self.asset_name,
                "asset_type": self.asset_type,
                "market": self.market,
                "board": self.board,
                "quantity": _decimal_numeric_text(self.quantity),
                "price": _decimal_numeric_text(self.price),
                "reason": self.reason,
                "signal_id": self.signal_id,
            }
        )


@runtime_checkable
class SimulatedFeePolicyContract(Protocol):
    """Runtime-checkable V2 fee snapshot boundary used by the execution plan."""

    @property
    def fee_schedule_v1(self) -> ExecutionFeeSchedule:
        """Return the immutable V1 numeric schedule nested in this snapshot."""

    @property
    def content_hash(self) -> str:
        """Return the canonical hash of the complete V2 policy snapshot."""

    def __post_init__(self) -> None:
        """Revalidate the complete exact policy snapshot."""

    def validate_at(self, as_of: datetime) -> None:
        """Require recorded and effective policy clocks at one instant."""

    def to_payload(self) -> dict[str, object]:
        """Return the complete immutable V2 snapshot payload."""

    def calculate_for(
        self,
        *,
        asset_type: str,
        market: str,
        board: str,
        side: SimulatedTradeSide,
        amount: Decimal,
        as_of: datetime,
    ) -> TradeFeeBreakdown:
        """Calculate exact fee components for one transaction case."""


@dataclass(frozen=True, slots=True)
class SettlementExecutionPlan:
    """Bind an exact intent to one V3 bundle and one published calendar reference."""

    intent: SimulatedTradeIntent
    market_session: date
    pre_read_at: datetime
    settlement_lag_sessions: int
    settlement_release_date: date | None
    settlement_bundle_id: str
    settlement_bundle_version: str
    settlement_bundle_hash: str
    settlement_policy_id: str
    settlement_policy_version: str
    settlement_policy_hash: str
    execution_rule_v2_hash: str
    bundle_source_observed_at: datetime
    bundle_source_available_at: datetime
    bundle_effective_from: datetime
    bundle_valid_until: datetime
    calendar_evidence: ExecutionCalendarEvidence
    fee_policy_v2: SimulatedFeePolicyContract

    @property
    def _expected_calendar_exchange(self) -> str:
        """Return the exchange required by this plan's versioned identity contract."""

        return self.intent.market

    def __post_init__(self) -> None:
        """Validate settlement scope, source clocks, and the computed release session."""

        if type(self.intent) is not SimulatedTradeIntent:
            raise SimulatedTradeIntentValidationError("intent must be SimulatedTradeIntent")
        try:
            SimulatedTradeIntent.__post_init__(self.intent)
        except SimulatedTradeIntentValidationError:
            raise
        except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeIntentValidationError("intent failed revalidation") from error
        if type(self.market_session) is not date:
            raise SimulatedSettlementContractError("market_session must be an exact date")
        _require_aware(self.pre_read_at, "pre_read_at")
        if type(self.settlement_lag_sessions) is not int or self.settlement_lag_sessions < 0:
            raise SimulatedSettlementContractError(
                "settlement_lag_sessions must be an explicit nonnegative integer"
            )
        for field_name in (
            "settlement_bundle_id",
            "settlement_bundle_version",
            "settlement_policy_id",
            "settlement_policy_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        for field_name in (
            "settlement_bundle_hash",
            "settlement_policy_hash",
            "execution_rule_v2_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)
        for field_name in (
            "bundle_source_observed_at",
            "bundle_source_available_at",
            "bundle_effective_from",
            "bundle_valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if not (
            self.bundle_source_observed_at <= self.bundle_source_available_at
            and self.bundle_source_available_at < self.bundle_valid_until
            and self.bundle_effective_from < self.bundle_valid_until
        ):
            raise SimulatedSettlementContractError("settlement bundle time window is invalid")
        if type(self.calendar_evidence) is not ExecutionCalendarEvidence:
            raise CalendarEvidenceValidationError(
                "calendar_evidence must be ExecutionCalendarEvidence"
            )
        self.calendar_evidence.__post_init__()
        if not isinstance(self.fee_policy_v2, SimulatedFeePolicyContract):
            raise SimulatedSettlementContractError(
                "fee_policy_v2 must implement the exact fee-policy contract"
            )
        self.fee_policy_v2.__post_init__()
        if type(self.fee_policy_v2.fee_schedule_v1) is not ExecutionFeeSchedule:
            raise SimulatedSettlementContractError("fee policy has no exact V1 numeric schedule")
        self.fee_policy_v2.fee_schedule_v1.__post_init__()
        if self.calendar_evidence.snapshot.exchange != self._expected_calendar_exchange:
            raise CalendarEvidenceValidationError(
                "calendar exchange differs from the order market scope"
            )
        try:
            self.calendar_evidence.validate_for(self.pre_read_at)
            if self.calendar_evidence.current_open_session(self.pre_read_at) != self.market_session:
                raise CalendarEvidenceValidationError(
                    "market_session differs from the pre-lock calendar cutoff"
                )
        except CalendarEvidenceValidationError:
            raise
        except (ArithmeticError, TypeError, ValueError) as error:
            raise CalendarEvidenceValidationError(
                "calendar is not valid at the pre-lock evidence cutoff"
            ) from error
        if not (
            self.bundle_source_observed_at <= self.pre_read_at
            and self.bundle_source_available_at <= self.pre_read_at
            and self.bundle_effective_from <= self.pre_read_at < self.bundle_valid_until
        ):
            raise SimulatedSettlementContractError(
                "settlement bundle was not valid at the pre-lock evidence cutoff"
            )
        if self.intent.side is SimulatedTradeSide.BUY:
            if type(self.settlement_release_date) is not date:
                raise SimulatedSettlementContractError(
                    "BUY intent requires a source-derived settlement release date"
                )
            expected_release = self.calendar_evidence.release_session(
                self.market_session,
                self.settlement_lag_sessions,
            )
            if self.settlement_release_date != expected_release:
                raise SimulatedSettlementContractError(
                    "settlement release date differs from explicit calendar advancement"
                )
        elif self.settlement_release_date is not None:
            raise SimulatedSettlementContractError(
                "SELL intent cannot create a pending buy-settlement date"
            )

    @property
    def settlement_calendar_reference(self) -> str:
        """Return the exact formal calendar publication/member reference."""

        return self.calendar_evidence.publication_reference

    @property
    def settlement_calendar_evidence_hash(self) -> str:
        """Return the digest over the exact calendar snapshot and publication binding."""

        return self.calendar_evidence.evidence_hash

    @property
    def amount(self) -> Decimal:
        """Return the ledger-cent amount under the explicit V1 fee rounding policy."""

        self.__post_init__()
        try:
            with localcontext() as context:
                context.prec = 80
                value = (self.intent.quantity * self.intent.price).quantize(
                    _MONEY_QUANTUM,
                    rounding=ROUND_HALF_EVEN,
                )
        except (InvalidOperation, OverflowError) as error:
            raise SimulatedTradeIntentValidationError(
                "trade amount cannot be represented at ledger precision"
            ) from error
        return _require_decimal_storage(
            value,
            "amount",
            quantum=_MONEY_QUANTUM,
            exclusive_maximum=_MAX_MONEY_VALUE,
        )

    @property
    def fee_breakdown(self) -> TradeFeeBreakdown:
        """Return the explicit estimated fee components for this exact intent."""

        self.__post_init__()
        return self.fee_policy_v2.calculate_for(
            asset_type=self.intent.asset_type,
            market=self.intent.market,
            board=self.intent.board,
            side=self.intent.side,
            amount=self.amount,
            as_of=self.pre_read_at,
        )

    def validate_at(self, as_of: datetime) -> None:
        """Revalidate immutable evidence after the repository has acquired row locks."""

        self.__post_init__()
        _require_aware(as_of, "as_of")
        if as_of < self.pre_read_at:
            raise SimulatedSettlementContractError(
                "locked execution clock cannot precede the pre-lock evidence cutoff"
            )
        self.calendar_evidence.validate_for(as_of)
        self.fee_policy_v2.validate_at(as_of)
        if not (
            self.bundle_source_observed_at <= as_of
            and self.bundle_source_available_at <= as_of
            and self.bundle_effective_from <= as_of < self.bundle_valid_until
        ):
            raise SimulatedSettlementContractError(
                "settlement bundle is unavailable or outside its window after row locking"
            )
        if self.calendar_evidence.current_open_session(as_of) != self.market_session:
            raise CalendarEvidenceValidationError(
                "exchange-local session changed while the order waited for row locks"
            )


@dataclass(frozen=True, slots=True)
class ExecutionFeeSchedule:
    """Explicit database-backed fee terms, including their stored precision basis."""

    config_id: int
    asset_type: str
    commission_rate_buy: Decimal
    commission_rate_sell: Decimal
    min_commission: Decimal
    stamp_duty_rate: Decimal
    transfer_fee_rate: Decimal
    min_transfer_fee: Decimal
    slippage_rate: Decimal
    precision_basis: FeeRateStoragePrecision
    calculation_purpose: FeeCalculationPurpose
    rounding_policy: FeeRoundingPolicy
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Reject missing or nonfinite persisted fee terms without adding defaults."""

        if type(self.config_id) is not int or self.config_id <= 0:
            raise SimulatedSettlementContractError("config_id must be a positive integer")
        _require_token(self.asset_type, "asset_type")
        if type(self.precision_basis) is not FeeRateStoragePrecision:
            raise SimulatedSettlementContractError("fee precision basis must be explicit")
        if type(self.calculation_purpose) is not FeeCalculationPurpose:
            raise SimulatedSettlementContractError("fee calculation purpose must be explicit")
        if type(self.rounding_policy) is not FeeRoundingPolicy:
            raise SimulatedSettlementContractError("fee rounding policy must be explicit")
        if self.asset_type not in {"equity", "fund", "bond", "all"}:
            raise SimulatedSettlementContractError("fee asset_type is unsupported")
        for field_name in (
            "commission_rate_buy",
            "commission_rate_sell",
            "min_commission",
            "stamp_duty_rate",
            "transfer_fee_rate",
            "min_transfer_fee",
            "slippage_rate",
        ):
            value = getattr(self, field_name)
            decimal_exponent = value.as_tuple().exponent if type(value) is Decimal else None
            if (
                type(value) is not Decimal
                or not value.is_finite()
                or value < 0
                or len(value.as_tuple().digits) > 128
                or not isinstance(decimal_exponent, int)
                or abs(decimal_exponent) > 128
            ):
                raise SimulatedSettlementContractError(
                    f"{field_name} must be a bounded nonnegative exact Decimal"
                )
            if field_name.endswith("_rate") and value > Decimal("1"):
                raise SimulatedSettlementContractError(
                    f"{field_name} cannot exceed the persisted FeeConfig range"
                )
        payload = self._content_payload()
        object.__setattr__(
            self,
            "content_hash",
            _seal_hash(payload, self.content_hash, "fee_schedule.content_hash"),
        )

    def _content_payload(self) -> dict[str, object]:
        return {
            "config_id": self.config_id,
            "asset_type": self.asset_type,
            "commission_rate_buy": _decimal_text(self.commission_rate_buy),
            "commission_rate_sell": _decimal_text(self.commission_rate_sell),
            "min_commission": _decimal_text(self.min_commission),
            "stamp_duty_rate": _decimal_text(self.stamp_duty_rate),
            "transfer_fee_rate": _decimal_text(self.transfer_fee_rate),
            "min_transfer_fee": _decimal_text(self.min_transfer_fee),
            "slippage_rate": _decimal_text(self.slippage_rate),
            "precision_basis": self.precision_basis.value,
            "calculation_purpose": self.calculation_purpose.value,
            "rounding_policy": self.rounding_policy.value,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete immutable fee snapshot used for the trade."""

        self.__post_init__()
        return {**self._content_payload(), "content_hash": self.content_hash}

    @classmethod
    def from_payload(cls, payload: object) -> ExecutionFeeSchedule:
        """Rebuild and revalidate one persisted exact fee snapshot."""

        expected_keys = {
            "config_id",
            "asset_type",
            "commission_rate_buy",
            "commission_rate_sell",
            "min_commission",
            "stamp_duty_rate",
            "transfer_fee_rate",
            "min_transfer_fee",
            "slippage_rate",
            "precision_basis",
            "calculation_purpose",
            "rounding_policy",
            "content_hash",
        }
        if type(payload) is not dict:
            raise SimulatedSettlementContractError("fee snapshot must be an object")
        fields = cast(dict[str, object], payload)
        if set(fields) != expected_keys:
            raise SimulatedSettlementContractError("fee snapshot fields are incomplete or unknown")
        if type(fields["config_id"]) is not int or type(fields["asset_type"]) is not str:
            raise SimulatedSettlementContractError("fee snapshot identity fields are invalid")
        if any(
            type(fields[name]) is not str
            for name in (
                "precision_basis",
                "calculation_purpose",
                "rounding_policy",
                "content_hash",
            )
        ):
            raise SimulatedSettlementContractError("fee snapshot policy fields are invalid")
        try:
            return cls(
                config_id=fields["config_id"],
                asset_type=fields["asset_type"],
                commission_rate_buy=_decimal_from_text(
                    fields["commission_rate_buy"], "commission_rate_buy"
                ),
                commission_rate_sell=_decimal_from_text(
                    fields["commission_rate_sell"], "commission_rate_sell"
                ),
                min_commission=_decimal_from_text(fields["min_commission"], "min_commission"),
                stamp_duty_rate=_decimal_from_text(fields["stamp_duty_rate"], "stamp_duty_rate"),
                transfer_fee_rate=_decimal_from_text(
                    fields["transfer_fee_rate"], "transfer_fee_rate"
                ),
                min_transfer_fee=_decimal_from_text(fields["min_transfer_fee"], "min_transfer_fee"),
                slippage_rate=_decimal_from_text(fields["slippage_rate"], "slippage_rate"),
                precision_basis=FeeRateStoragePrecision(cast(str, fields["precision_basis"])),
                calculation_purpose=FeeCalculationPurpose(cast(str, fields["calculation_purpose"])),
                rounding_policy=FeeRoundingPolicy(cast(str, fields["rounding_policy"])),
                content_hash=cast(str, fields["content_hash"]),
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, SimulatedSettlementContractError):
                raise
            raise SimulatedSettlementContractError("fee snapshot fields are invalid") from error


@dataclass(frozen=True, slots=True)
class TradeFeeBreakdown:
    """Rounded fee components calculated from one explicit stored fee schedule."""

    commission: Decimal
    transfer_fee: Decimal
    stamp_duty: Decimal
    slippage: Decimal
    total_fee: Decimal


def calculate_trade_fees(
    schedule: ExecutionFeeSchedule,
    *,
    side: SimulatedTradeSide,
    amount: Decimal,
    market: str,
) -> TradeFeeBreakdown:
    """Apply exact stored-rate formulas and sum individually rounded fee components.

    FloatField values use their exact binary64 value. Fees are calculated solely
    for normal simulated orders; imported actual execution facts never use this
    estimate path.
    """

    if type(schedule) is not ExecutionFeeSchedule:
        raise SimulatedSettlementContractError("schedule must be ExecutionFeeSchedule")
    schedule.__post_init__()
    if type(side) is not SimulatedTradeSide:
        raise SimulatedSettlementContractError("side must be a recognized trade side")
    _require_token(market, "market")
    _require_decimal_storage(
        amount,
        "amount",
        quantum=_MONEY_QUANTUM,
        exclusive_maximum=_MAX_MONEY_VALUE,
    )
    try:
        with localcontext() as context:
            context.prec = 160
            if side is SimulatedTradeSide.BUY:
                commission = max(
                    amount * schedule.commission_rate_buy,
                    schedule.min_commission,
                )
                stamp_duty = Decimal("0")
            else:
                commission = max(
                    amount * schedule.commission_rate_sell,
                    schedule.min_commission,
                )
                stamp_duty = (
                    amount * schedule.stamp_duty_rate
                    if schedule.asset_type == "equity"
                    else Decimal("0")
                )
            transfer_fee = Decimal("0")
            if market == "SH" and schedule.asset_type == "equity":
                transfer_fee = max(
                    amount * schedule.transfer_fee_rate,
                    schedule.min_transfer_fee,
                )
            slippage = amount * schedule.slippage_rate
            rounded_commission = commission.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            rounded_transfer = transfer_fee.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            rounded_stamp = stamp_duty.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            rounded_slippage = slippage.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            total_fee = rounded_commission + rounded_transfer + rounded_stamp + rounded_slippage
    except (InvalidOperation, OverflowError) as error:
        raise SimulatedSettlementContractError(
            "configured fee values cannot be represented at ledger precision"
        ) from error
    return TradeFeeBreakdown(
        commission=rounded_commission,
        transfer_fee=rounded_transfer,
        stamp_duty=rounded_stamp,
        slippage=rounded_slippage,
        total_fee=total_fee,
    )


@dataclass(frozen=True, slots=True)
class SimulatedTradeExecutionReceipt:
    """Exact persisted result returned by the settlement-bound ledger UoW."""

    trade_id: int
    account_id: int
    idempotency_key: str
    request_payload_hash: str
    side: SimulatedTradeSide
    asset_code: str
    quantity: Decimal
    price: Decimal
    amount: Decimal
    commission: Decimal
    transfer_fee: Decimal
    stamp_duty: Decimal
    slippage: Decimal
    total_cost: Decimal
    settlement_status: str | None
    settlement_release_date: date | None
    replayed: bool

    def __post_init__(self) -> None:
        """Validate the exact saved result and its optional settlement relation."""

        if type(self.trade_id) is not int or self.trade_id <= 0:
            raise SimulatedSettlementContractError("trade_id must be positive")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise SimulatedSettlementContractError("account_id must be positive")
        _require_token(self.idempotency_key, "idempotency_key", max_length=_MAX_IDEMPOTENCY_LENGTH)
        _require_hash(self.request_payload_hash, "request_payload_hash")
        if type(self.side) is not SimulatedTradeSide:
            raise SimulatedSettlementContractError("receipt side is invalid")
        _require_token(self.asset_code, "asset_code")
        for field_name, value, quantum, maximum in (
            ("quantity", self.quantity, _SHARE_QUANTUM, _MAX_SHARE_VALUE),
            ("price", self.price, _PRICE_QUANTUM, _MAX_PRICE_VALUE),
            ("amount", self.amount, _MONEY_QUANTUM, _MAX_MONEY_VALUE),
            ("commission", self.commission, _MONEY_QUANTUM, _MAX_MONEY_VALUE),
            ("transfer_fee", self.transfer_fee, _MONEY_QUANTUM, _MAX_MONEY_VALUE),
            ("stamp_duty", self.stamp_duty, _MONEY_QUANTUM, _MAX_MONEY_VALUE),
            ("slippage", self.slippage, _MONEY_QUANTUM, _MAX_MONEY_VALUE),
            ("total_cost", self.total_cost, _MONEY_QUANTUM, _MAX_MONEY_VALUE),
        ):
            _require_decimal_storage(
                value,
                field_name,
                quantum=quantum,
                exclusive_maximum=maximum,
                allow_zero=field_name
                in {
                    "commission",
                    "transfer_fee",
                    "stamp_duty",
                    "slippage",
                    "total_cost",
                },
            )
        if self.side is SimulatedTradeSide.BUY:
            if self.settlement_status not in {"pending", "released"}:
                raise SimulatedSettlementContractError("BUY receipt requires settlement status")
            if type(self.settlement_release_date) is not date:
                raise SimulatedSettlementContractError("BUY receipt requires a release date")
            expected_total_cost = (
                self.amount + self.commission + self.transfer_fee + self.stamp_duty + self.slippage
            )
        elif self.settlement_status is not None or self.settlement_release_date is not None:
            raise SimulatedSettlementContractError("SELL receipt cannot carry buy settlement state")
        else:
            expected_total_cost = (
                self.commission + self.transfer_fee + self.stamp_duty + self.slippage
            )
        if self.total_cost != expected_total_cost:
            raise SimulatedSettlementContractError(
                "receipt total_cost must reconcile to its stored fee components"
            )
        if type(self.replayed) is not bool:
            raise SimulatedSettlementContractError("replayed must be a boolean")


__all__: tuple[str, ...] = (
    "CalendarEvidenceValidationError",
    "CalendarPublicationReference",
    "ExecutionCalendarEvidence",
    "ExecutionFeeSchedule",
    "FeeCalculationPurpose",
    "FeeRoundingPolicy",
    "ExchangeCalendarDay",
    "ExchangeCalendarSnapshot",
    "FeeRateStoragePrecision",
    "RawCalendarReference",
    "SettlementExecutionPlan",
    "SimulatedFeePolicyContract",
    "SimulatedSettlementContractError",
    "SimulatedTradeExecutionReceipt",
    "SimulatedTradeIntent",
    "SimulatedTradeIntentValidationError",
    "SimulatedTradeSide",
    "TradeFeeBreakdown",
    "calculate_trade_fees",
    "validate_ledger_money",
    "validate_ledger_price",
    "validate_ledger_quantity",
)
