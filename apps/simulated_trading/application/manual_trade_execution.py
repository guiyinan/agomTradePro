"""Current-reference manual execution for normal simulated A-share equity trades."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from apps.simulated_trading.application.execution_settlement_uow import (
    ExecutionInstrumentIdentityUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeExecutionInputError,
    SimulatedTradeExecutionRepository,
    SimulatedTradeExecutionResultUnknown,
    SimulatedTradeIdempotencyConflict,
)
from apps.simulated_trading.domain.entities import SimulatedTrade
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    IdentityEvidenceValidationError,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeExecutionReceipt,
    SimulatedTradeIntent,
    SimulatedTradeSide,
    validate_ledger_price,
    validate_ledger_quantity,
)

_MAX_IDEMPOTENCY_KEY_LENGTH = 128
_MAX_ASSET_TOKEN_LENGTH = 192


class SimulatedTradeExecutionReadbackUnknown(SimulatedTradeExecutionResultUnknown):
    """Identify a failed receipt readback after an existing or new ledger write."""

    default_message = "模拟交易写入后的成交回读不确定"
    default_code = "SIMULATED_TRADE_EXECUTION_READBACK_UNKNOWN"


class CurrentReferenceManualIdentityReader(Protocol):
    """Resolve an asset code and re-read one exact identity at the same cutoff."""

    def resolve_current_reference_identity(
        self, *, asset_code: str, as_of: datetime
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        """Resolve only an explicitly configured current security mapping."""

    def get_execution_instrument_identity(
        self, *, security_id: str, asset_code: str, as_of: datetime
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        """Return the same exact mapping within the settlement UOW cutoff."""


class OwnedManualTradeReader(Protocol):
    """Read one existing trade only inside its persisted account-owner scope."""

    def get_owned_trade_by_id(
        self, *, trade_id: int, account_id: int, user_id: int
    ) -> SimulatedTrade | None:
        """Return an exact owned trade row or None."""


class SettlementBoundManualTradeExecutor(Protocol):
    """Apply one exact manual intent through the transactional ledger use case."""

    def execute(
        self,
        intent: SimulatedTradeIntent,
        *,
        as_of: datetime | None = None,
    ) -> SimulatedTradeExecutionReceipt:
        """Use the caller's cutoff when reading evidence and locking the ledger."""


@dataclass(frozen=True, slots=True)
class ManualSimulatedTradeRequest:
    """Validated caller intent before resolving current security identity."""

    account_id: int
    user_id: int
    idempotency_key: str
    asset_code: str
    asset_name: str
    asset_type: str
    side: SimulatedTradeSide
    quantity: Decimal
    price: Decimal
    reason: str
    signal_id: int | None

    def __post_init__(self) -> None:
        """Reject malformed requests before any source or ledger reads."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise SimulatedTradeExecutionInputError("account_id must be a positive integer")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise SimulatedTradeExecutionInputError("user_id must be a positive integer")
        _require_token(self.idempotency_key, "idempotency_key", _MAX_IDEMPOTENCY_KEY_LENGTH)
        _require_token(self.asset_code, "asset_code", _MAX_ASSET_TOKEN_LENGTH)
        if type(self.asset_name) is not str or not self.asset_name or len(self.asset_name) > 100:
            raise SimulatedTradeExecutionInputError(
                "asset_name must be nonempty text of at most 100 chars"
            )
        if type(self.asset_type) is not str or self.asset_type != "equity":
            raise SimulatedTradeExecutionInputError(
                "only explicit A-share equity trades are supported"
            )
        if type(self.side) is not SimulatedTradeSide:
            raise SimulatedTradeExecutionInputError("side must be buy or sell")
        try:
            quantity = validate_ledger_quantity(self.quantity, "quantity", allow_zero=False)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionInputError(
                "quantity is outside the exact ledger representation"
            ) from error
        if quantity != quantity.to_integral_value():
            raise SimulatedTradeExecutionInputError("quantity must be a whole number of shares")
        try:
            validate_ledger_price(self.price, "price", allow_zero=False)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionInputError(
                "price is outside the exact ledger representation"
            ) from error
        if type(self.reason) is not str or len(self.reason) > 200:
            raise SimulatedTradeExecutionInputError("reason must be text of at most 200 chars")
        if self.signal_id is not None and type(self.signal_id) is not int:
            raise SimulatedTradeExecutionInputError("signal_id must be an integer or None")


@dataclass(frozen=True, slots=True)
class ManualSimulatedTradeResult:
    """Return the user-visible trade together with its exact persisted receipt."""

    trade: SimulatedTrade
    receipt: SimulatedTradeExecutionReceipt


class ExecuteCurrentReferenceManualTradeUseCase:
    """Apply an owner-scoped manual order through current identity and the real UOW."""

    def __init__(
        self,
        *,
        identity_reader: CurrentReferenceManualIdentityReader,
        repository: SimulatedTradeExecutionRepository,
        trade_reader: OwnedManualTradeReader,
        execution_use_case: SettlementBoundManualTradeExecutor,
        clock: SimulatedTradeExecutionClock,
    ) -> None:
        """Require explicit source, receipt, trade, ledger, and clock ports."""

        self._identity_reader = identity_reader
        self._repository = repository
        self._trade_reader = trade_reader
        self._execution_use_case = execution_use_case
        self._clock = clock

    def execute(
        self,
        request: ManualSimulatedTradeRequest,
        *,
        as_of: datetime | None = None,
    ) -> ManualSimulatedTradeResult:
        """Replay or apply one exact intent at an optional Application cutoff."""

        if type(request) is not ManualSimulatedTradeRequest:
            raise SimulatedTradeExecutionInputError("a typed manual trade request is required")
        try:
            ManualSimulatedTradeRequest.__post_init__(request)
        except SimulatedTradeExecutionInputError:
            raise
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionInputError(
                "manual trade request validation failed"
            ) from error

        requested_cutoff = self._current_cutoff(as_of) if as_of is not None else None

        previous = self._repository.find_idempotent_result(
            account_id=request.account_id,
            user_id=request.user_id,
            idempotency_key=request.idempotency_key,
        )
        if previous is not None:
            trade = self._read_exact_trade(previous, request)
            if not self._matches_request(previous, trade, request):
                raise SimulatedTradeIdempotencyConflict(
                    "idempotency key already belongs to a different caller-visible trade"
                )
            return ManualSimulatedTradeResult(
                trade=trade,
                receipt=replace(previous, replayed=True),
            )

        cutoff = requested_cutoff if requested_cutoff is not None else self._current_cutoff()
        try:
            evidence = self._identity_reader.resolve_current_reference_identity(
                asset_code=request.asset_code,
                as_of=cutoff,
            )
        except IdentityEvidenceValidationError as error:
            raise SimulatedTradeExecutionBlocked(
                "current instrument identity evidence failed validation"
            ) from error
        if evidence is None:
            raise ExecutionInstrumentIdentityUnavailable(
                "no explicit current security mapping is available for this asset"
            )
        if type(evidence) is not ExecutionInstrumentIdentityEvidenceV2:
            raise SimulatedTradeExecutionBlocked(
                "current identity reader returned an invalid V2 contract"
            )
        try:
            ExecutionInstrumentIdentityEvidenceV2.__post_init__(evidence)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "current identity evidence failed exact integrity checks"
            ) from error
        if evidence.asset_code != request.asset_code or evidence.selection.selected_at != cutoff:
            raise SimulatedTradeExecutionBlocked(
                "current identity selection differs from the exact asset or cutoff"
            )

        intent = SimulatedTradeIntent(
            account_id=request.account_id,
            user_id=request.user_id,
            idempotency_key=request.idempotency_key,
            side=request.side,
            security_id=evidence.security_id,
            asset_code=request.asset_code,
            asset_name=request.asset_name,
            asset_type=request.asset_type,
            market=evidence.rule_market,
            board=evidence.board,
            quantity=request.quantity,
            price=request.price,
            reason=request.reason,
            signal_id=request.signal_id,
        )
        try:
            SimulatedTradeIntent.__post_init__(intent)
            receipt = self._execution_use_case.execute(intent, as_of=cutoff)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionInputError(
                "manual trade intent could not be represented exactly"
            ) from error
        return self._result_for_new_intent(receipt, intent, request)

    def _current_cutoff(self, requested: datetime | None = None) -> datetime:
        """Return the supplied or current normalized aware-UTC cutoff."""

        value = self._clock.now() if requested is None else requested
        if type(value) is not datetime or value.tzinfo is None:
            raise SimulatedTradeExecutionBlocked("manual trade clock must be aware UTC")
        try:
            offset = value.utcoffset()
            if offset != timedelta(0):
                raise SimulatedTradeExecutionBlocked("manual trade clock must be aware UTC")
            return value.astimezone(UTC)
        except SimulatedTradeExecutionBlocked:
            raise
        except (OverflowError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked("manual trade clock must be aware UTC") from error

    def _read_exact_trade(
        self,
        receipt: SimulatedTradeExecutionReceipt,
        request: ManualSimulatedTradeRequest,
    ) -> SimulatedTrade:
        """Validate one receipt and load its trade within the exact owner scope."""

        if type(receipt) is not SimulatedTradeExecutionReceipt:
            raise SimulatedTradeExecutionReadbackUnknown(
                "ledger returned an invalid idempotency receipt"
            )
        try:
            SimulatedTradeExecutionReceipt.__post_init__(receipt)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionReadbackUnknown(
                "saved idempotency receipt is damaged"
            ) from error
        if (
            receipt.account_id != request.account_id
            or receipt.idempotency_key != request.idempotency_key
        ):
            raise SimulatedTradeExecutionReadbackUnknown(
                "saved receipt differs from its owner-scoped lookup"
            )
        try:
            trade = self._trade_reader.get_owned_trade_by_id(
                trade_id=receipt.trade_id,
                account_id=request.account_id,
                user_id=request.user_id,
            )
        except Exception as error:
            raise SimulatedTradeExecutionReadbackUnknown(
                "owned trade readback could not be completed"
            ) from error
        if type(trade) is not SimulatedTrade:
            raise SimulatedTradeExecutionReadbackUnknown(
                "saved receipt has no exact owned trade row"
            )
        try:
            exact_receipt_scope = (
                trade.trade_id == receipt.trade_id
                and trade.account_id == receipt.account_id
                and trade.action.value == receipt.side.value
                and trade.asset_code == receipt.asset_code
            )
        except Exception as error:
            raise SimulatedTradeExecutionReadbackUnknown(
                "saved trade receipt fields could not be verified"
            ) from error
        if not exact_receipt_scope:
            raise SimulatedTradeExecutionReadbackUnknown(
                "saved trade row differs from its exact receipt"
            )
        return trade

    def _matches_request(
        self,
        receipt: SimulatedTradeExecutionReceipt,
        trade: SimulatedTrade,
        request: ManualSimulatedTradeRequest,
    ) -> bool:
        """Compare caller-visible intent while trusting the verified saved receipt."""

        return (
            receipt.side is request.side
            and receipt.asset_code == request.asset_code
            and receipt.quantity == request.quantity
            and receipt.price == request.price
            and trade.asset_name == request.asset_name
            and trade.asset_type == request.asset_type
            and trade.reason == request.reason
            and trade.signal_id == request.signal_id
        )

    def _result_for_new_intent(
        self,
        receipt: SimulatedTradeExecutionReceipt,
        intent: SimulatedTradeIntent,
        request: ManualSimulatedTradeRequest,
    ) -> ManualSimulatedTradeResult:
        """Read back and verify the exact trade committed for this intent."""

        if type(receipt) is not SimulatedTradeExecutionReceipt:
            raise SimulatedTradeExecutionReadbackUnknown(
                "ledger returned an invalid execution receipt"
            )
        try:
            SimulatedTradeExecutionReceipt.__post_init__(receipt)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionReadbackUnknown(
                "execution receipt failed validation"
            ) from error
        if (
            receipt.account_id != intent.account_id
            or receipt.idempotency_key != intent.idempotency_key
            or receipt.request_payload_hash != intent.request_payload_hash
        ):
            raise SimulatedTradeExecutionReadbackUnknown(
                "execution receipt differs from the exact intent"
            )
        trade = self._read_exact_trade(receipt, request)
        if not self._matches_request(receipt, trade, request):
            raise SimulatedTradeExecutionReadbackUnknown(
                "saved trade differs from the applied intent"
            )
        return ManualSimulatedTradeResult(trade=trade, receipt=receipt)


def _require_token(value: object, field_name: str, maximum: int) -> None:
    """Require a bounded canonical token without normalizing caller input."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise SimulatedTradeExecutionInputError(f"{field_name} must be a bounded canonical token")


__all__: tuple[str, ...] = (
    "CurrentReferenceManualIdentityReader",
    "ExecuteCurrentReferenceManualTradeUseCase",
    "ManualSimulatedTradeRequest",
    "ManualSimulatedTradeResult",
    "OwnedManualTradeReader",
    "SettlementBoundManualTradeExecutor",
    "SimulatedTradeExecutionReadbackUnknown",
)
