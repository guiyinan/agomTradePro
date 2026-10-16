"""Exact, versioned fee applicability contracts for new simulated orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from enum import StrEnum
from typing import cast

from apps.simulated_trading.domain.execution_settlement_uow import (
    _MAX_MONEY_VALUE,
    _MONEY_QUANTUM,
    ExecutionFeeSchedule,
    SimulatedSettlementContractError,
    SimulatedTradeSide,
    TradeFeeBreakdown,
    _require_aware,
    _require_decimal_storage,
    _require_token,
    _seal_hash,
    _utc_text,
)


class FeeApplicability(StrEnum):
    """State whether one fee component applies to one exact transaction case."""

    APPLIES = "APPLIES"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class FeePolicyAccountScope(StrEnum):
    """Only the explicitly declared global simulated-account scope is supported."""

    ALL_SIMULATED_ACCOUNTS = "ALL_SIMULATED_ACCOUNTS"


class FeeTransactionCaseUnavailable(SimulatedSettlementContractError):
    """Raised when no exact fee applicability case covers a transaction."""


@dataclass(frozen=True, slots=True)
class FeeTransactionCase:
    """Declare every fee component for one exact asset/market/board/side tuple."""

    asset_type: str
    market: str
    board: str
    side: SimulatedTradeSide
    commission: FeeApplicability
    transfer_fee: FeeApplicability
    stamp_duty: FeeApplicability
    slippage: FeeApplicability

    def __post_init__(self) -> None:
        """Reject wildcard dimensions and implicit component states."""

        for field_name in ("asset_type", "market", "board"):
            value = getattr(self, field_name)
            _require_token(value, field_name)
            if value in {"*", "all", "ALL", "any", "ANY"}:
                raise SimulatedSettlementContractError(
                    f"{field_name} cannot be a wildcard transaction dimension"
                )
        if type(self.side) is not SimulatedTradeSide:
            raise SimulatedSettlementContractError("case side must be an exact trade side")
        for field_name in ("commission", "transfer_fee", "stamp_duty", "slippage"):
            if type(getattr(self, field_name)) is not FeeApplicability:
                raise SimulatedSettlementContractError(
                    f"{field_name} applicability must be explicit"
                )

    @property
    def key(self) -> tuple[str, str, str, str]:
        """Return the exact transaction tuple used for deterministic selection."""

        self.__post_init__()
        return (self.asset_type, self.market, self.board, self.side.value)

    def to_payload(self) -> dict[str, str]:
        """Return the complete exact-case payload."""

        self.__post_init__()
        return {
            "asset_type": self.asset_type,
            "market": self.market,
            "board": self.board,
            "side": self.side.value,
            "commission": self.commission.value,
            "transfer_fee": self.transfer_fee.value,
            "stamp_duty": self.stamp_duty.value,
            "slippage": self.slippage.value,
        }

    @classmethod
    def from_payload(cls, payload: object) -> FeeTransactionCase:
        """Decode one strict transaction-case object."""

        expected_keys = {
            "asset_type",
            "market",
            "board",
            "side",
            "commission",
            "transfer_fee",
            "stamp_duty",
            "slippage",
        }
        if type(payload) is not dict:
            raise SimulatedSettlementContractError("transaction case must be an object")
        fields = cast(dict[str, object], payload)
        if set(fields) != expected_keys or any(type(value) is not str for value in fields.values()):
            raise SimulatedSettlementContractError(
                "transaction case has missing, unknown, or invalid fields"
            )
        try:
            return cls(
                asset_type=cast(str, fields["asset_type"]),
                market=cast(str, fields["market"]),
                board=cast(str, fields["board"]),
                side=SimulatedTradeSide(cast(str, fields["side"])),
                commission=FeeApplicability(cast(str, fields["commission"])),
                transfer_fee=FeeApplicability(cast(str, fields["transfer_fee"])),
                stamp_duty=FeeApplicability(cast(str, fields["stamp_duty"])),
                slippage=FeeApplicability(cast(str, fields["slippage"])),
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, SimulatedSettlementContractError):
                raise
            raise SimulatedSettlementContractError(
                "transaction case contains an unknown enum value"
            ) from error


@dataclass(frozen=True, slots=True)
class SimulatedFeePolicyV2:
    """Versioned exact-case policy wrapping an unchanged V1 binary64 snapshot."""

    fee_schedule_v1: ExecutionFeeSchedule
    policy_id: str
    policy_version: int
    account_scope: FeePolicyAccountScope
    effective_from: datetime
    valid_until: datetime
    recorded_at: datetime
    transaction_cases: tuple[FeeTransactionCase, ...]
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Revalidate the nested schedule, complete case set, clocks, and outer hash."""

        if type(self.fee_schedule_v1) is not ExecutionFeeSchedule:
            raise SimulatedSettlementContractError("V2 fee policy requires an exact V1 schedule")
        self.fee_schedule_v1.__post_init__()
        _require_token(self.policy_id, "policy_id")
        if type(self.policy_version) is not int or not 1 <= self.policy_version <= 2_147_483_647:
            raise SimulatedSettlementContractError(
                "policy_version must be a positive bounded integer"
            )
        if type(self.account_scope) is not FeePolicyAccountScope:
            raise SimulatedSettlementContractError("fee policy account scope must be explicit")
        for field_name in ("effective_from", "valid_until", "recorded_at"):
            _require_aware(getattr(self, field_name), field_name)
        if self.effective_from >= self.valid_until or self.recorded_at >= self.valid_until:
            raise SimulatedSettlementContractError("fee policy time window is empty or unavailable")
        if type(self.transaction_cases) is not tuple or not self.transaction_cases:
            raise SimulatedSettlementContractError(
                "fee policy requires a nonempty exact case tuple"
            )
        cases: list[FeeTransactionCase] = []
        for case in self.transaction_cases:
            if type(case) is not FeeTransactionCase:
                raise SimulatedSettlementContractError("fee policy case type is invalid")
            case.__post_init__()
            cases.append(case)
        keys = [case.key for case in cases]
        if len(keys) != len(set(keys)):
            raise SimulatedSettlementContractError("fee policy contains duplicate exact cases")
        object.__setattr__(
            self, "transaction_cases", tuple(sorted(cases, key=lambda case: case.key))
        )
        object.__setattr__(
            self,
            "content_hash",
            _seal_hash(
                self._content_payload(),
                self.content_hash,
                "fee_policy_v2.content_hash",
            ),
        )

    def _content_payload(self) -> dict[str, object]:
        return {
            "schema": "simulated-fee-policy.v2",
            "fee_schedule_v1": self.fee_schedule_v1.to_payload(),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "account_scope": self.account_scope.value,
            "effective_from": _utc_text(self.effective_from),
            "valid_until": _utc_text(self.valid_until),
            "recorded_at": _utc_text(self.recorded_at),
            "transaction_cases": [case.to_payload() for case in self.transaction_cases],
        }

    def to_payload(self) -> dict[str, object]:
        """Return a schema-tagged exact snapshot with an independent V2 outer hash."""

        self.__post_init__()
        return {**self._content_payload(), "content_hash": self.content_hash}

    @classmethod
    def from_payload(cls, payload: object) -> SimulatedFeePolicyV2:
        """Decode and revalidate a strict V2 snapshot while preserving its nested V1 hash."""

        expected_keys = {
            "schema",
            "fee_schedule_v1",
            "policy_id",
            "policy_version",
            "account_scope",
            "effective_from",
            "valid_until",
            "recorded_at",
            "transaction_cases",
            "content_hash",
        }
        if type(payload) is not dict:
            raise SimulatedSettlementContractError("V2 fee policy snapshot must be an object")
        fields = cast(dict[str, object], payload)
        if set(fields) != expected_keys or fields["schema"] != "simulated-fee-policy.v2":
            raise SimulatedSettlementContractError(
                "V2 fee policy snapshot has an unknown schema or incomplete fields"
            )
        if (
            type(fields["policy_id"]) is not str
            or type(fields["policy_version"]) is not int
            or type(fields["account_scope"]) is not str
            or type(fields["content_hash"]) is not str
            or type(fields["transaction_cases"]) is not list
        ):
            raise SimulatedSettlementContractError("V2 fee policy snapshot fields are invalid")
        try:
            cases = tuple(
                FeeTransactionCase.from_payload(case)
                for case in cast(list[object], fields["transaction_cases"])
            )
            return cls(
                fee_schedule_v1=ExecutionFeeSchedule.from_payload(fields["fee_schedule_v1"]),
                policy_id=fields["policy_id"],
                policy_version=fields["policy_version"],
                account_scope=FeePolicyAccountScope(fields["account_scope"]),
                effective_from=_parse_fee_policy_utc(fields["effective_from"], "effective_from"),
                valid_until=_parse_fee_policy_utc(fields["valid_until"], "valid_until"),
                recorded_at=_parse_fee_policy_utc(fields["recorded_at"], "recorded_at"),
                transaction_cases=cases,
                content_hash=fields["content_hash"],
            )
        except (ArithmeticError, TypeError, ValueError) as error:
            if isinstance(error, SimulatedSettlementContractError):
                raise
            raise SimulatedSettlementContractError("V2 fee policy snapshot is invalid") from error

    def validate_at(self, as_of: datetime) -> None:
        """Require this policy to have been recorded and effective at one cutoff."""

        self.__post_init__()
        _require_aware(as_of, "as_of")
        if not (self.recorded_at <= as_of and self.effective_from <= as_of < self.valid_until):
            raise SimulatedSettlementContractError("fee policy is not known and effective at as_of")

    def case_for(
        self,
        *,
        asset_type: str,
        market: str,
        board: str,
        side: SimulatedTradeSide,
        as_of: datetime,
    ) -> FeeTransactionCase:
        """Select one exact case only while the recorded policy is known and effective."""

        self.validate_at(as_of)
        request = FeeTransactionCase(
            asset_type=asset_type,
            market=market,
            board=board,
            side=side,
            commission=FeeApplicability.APPLIES,
            transfer_fee=FeeApplicability.APPLIES,
            stamp_duty=FeeApplicability.APPLIES,
            slippage=FeeApplicability.APPLIES,
        )
        for case in self.transaction_cases:
            if case.key == request.key:
                return case
        raise FeeTransactionCaseUnavailable("no exact fee transaction case is configured")

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
        """Calculate all rounded components from the exact configured case."""

        return calculate_trade_fees_v2(
            self,
            asset_type=asset_type,
            market=market,
            board=board,
            side=side,
            amount=amount,
            as_of=as_of,
        )


def _parse_fee_policy_utc(value: object, field_name: str) -> datetime:
    """Parse one canonical UTC timestamp in a fee-policy payload."""

    if type(value) is not str or not value.endswith("Z"):
        raise SimulatedSettlementContractError(f"{field_name} must use canonical UTC text")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as error:
        raise SimulatedSettlementContractError(
            f"{field_name} is not a valid UTC instant"
        ) from error
    if _utc_text(parsed) != value:
        raise SimulatedSettlementContractError(f"{field_name} is not canonical UTC text")
    return parsed


def calculate_trade_fees_v2(
    policy: SimulatedFeePolicyV2,
    *,
    asset_type: str,
    market: str,
    board: str,
    side: SimulatedTradeSide,
    amount: Decimal,
    as_of: datetime,
) -> TradeFeeBreakdown:
    """Apply only fee components explicitly declared for one exact V2 case."""

    if type(policy) is not SimulatedFeePolicyV2:
        raise SimulatedSettlementContractError("policy must be SimulatedFeePolicyV2")
    case = policy.case_for(
        asset_type=asset_type,
        market=market,
        board=board,
        side=side,
        as_of=as_of,
    )
    _require_decimal_storage(
        amount,
        "amount",
        quantum=_MONEY_QUANTUM,
        exclusive_maximum=_MAX_MONEY_VALUE,
    )
    schedule = policy.fee_schedule_v1
    try:
        with localcontext() as context:
            context.prec = 160
            if case.commission is FeeApplicability.APPLIES:
                rate = (
                    schedule.commission_rate_buy
                    if side is SimulatedTradeSide.BUY
                    else schedule.commission_rate_sell
                )
                commission = max(amount * rate, schedule.min_commission)
            else:
                commission = Decimal("0")
            transfer_fee = (
                max(amount * schedule.transfer_fee_rate, schedule.min_transfer_fee)
                if case.transfer_fee is FeeApplicability.APPLIES
                else Decimal("0")
            )
            stamp_duty = (
                amount * schedule.stamp_duty_rate
                if case.stamp_duty is FeeApplicability.APPLIES
                else Decimal("0")
            )
            slippage = (
                amount * schedule.slippage_rate
                if case.slippage is FeeApplicability.APPLIES
                else Decimal("0")
            )
            rounded_commission = commission.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            rounded_transfer = transfer_fee.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            rounded_stamp = stamp_duty.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            rounded_slippage = slippage.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            total_fee = rounded_commission + rounded_transfer + rounded_stamp + rounded_slippage
    except (InvalidOperation, OverflowError) as error:
        raise SimulatedSettlementContractError(
            "configured fee policy cannot be represented at ledger precision"
        ) from error
    return TradeFeeBreakdown(
        commission=rounded_commission,
        transfer_fee=rounded_transfer,
        stamp_duty=rounded_stamp,
        slippage=rounded_slippage,
        total_fee=total_fee,
    )


__all__: tuple[str, ...] = (
    "FeeApplicability",
    "FeePolicyAccountScope",
    "FeeTransactionCase",
    "FeeTransactionCaseUnavailable",
    "SimulatedFeePolicyV2",
    "calculate_trade_fees_v2",
)
