"""Adapt automatic-order callbacks to the existing settlement-bound manual use case."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Lock
from typing import Protocol
from uuid import UUID

from apps.data_center.application.price_service import PriceLookupResult
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecutionCalendarUnavailable,
    ExecutionFeeScheduleUnavailable,
    ExecutionInstrumentIdentityUnavailable,
    PublishedExecutionCalendarReader,
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeExecutionInputError,
    SimulatedTradeExecutionResultUnknown,
    SimulatedTradeIdempotencyConflict,
)
from apps.simulated_trading.application.manual_trade_execution import (
    CurrentReferenceManualIdentityReader,
    ExecuteCurrentReferenceManualTradeUseCase,
    ManualSimulatedTradeRequest,
    ManualSimulatedTradeResult,
)
from apps.simulated_trading.application.ports import PriceProviderProtocol
from apps.simulated_trading.application.use_cases import PositionRepositoryProtocol
from apps.simulated_trading.domain.entities import Position, SimulatedTrade
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeSide,
)
from core.exceptions import BusinessLogicError

_ACTION_KEY_MAX_LENGTH = 128
_ASSET_TOKEN_MAX_LENGTH = 192


class AutomaticTradeExecutionPreflightBlocked(SimulatedTradeExecutionBlocked):
    """An automatic order failed a source or input check before manual execution."""

    default_message = "自动模拟交易预检未通过"
    default_code = "AUTO_TRADE_PREFLIGHT_BLOCKED"


class AutomaticTradeExecutionOutcomeUnknown(BusinessLogicError):
    """Manual execution may have written, so the started run must stay indeterminate."""

    default_message = "自动模拟交易结果不确定；该运行不得重入"
    default_code = "AUTO_TRADE_EXECUTION_OUTCOME_UNKNOWN"
    effects_indeterminate: bool = True


class AutomaticTradeOwnerReader(Protocol):
    """Read the exact persisted simulated-account owner before ledger execution."""

    def get_owner_id(self, *, account_id: int) -> int | None:
        """Return the active simulated account's persisted owner, or None outside that scope."""


class AutomaticTradePriceLookup(Protocol):
    """Read a canonical Data Center price result for one explicit asset date."""

    def get_price_result(
        self,
        asset_code: str,
        trade_date: date | None = None,
        asset_type: str | None = None,
    ) -> PriceLookupResult | None:
        """Return the complete price result without discarding its source fields."""


class AutomaticTradePriceProvider(PriceProviderProtocol):
    """Serve Engine float callbacks while retaining the exact lookup result used."""

    def __init__(self, lookup: AutomaticTradePriceLookup) -> None:
        """Bind the existing price lookup for one automatic run."""

        self._lookup = lookup
        self._results: dict[tuple[str, date], PriceLookupResult | None] = {}

    def get_price(self, asset_code: str, trade_date: date) -> float | None:
        """Return one cached historical equity price for the Engine."""

        result = self._load_result(asset_code, trade_date)
        return result.price if result is not None else None

    def require_price(self, asset_code: str, trade_date: date) -> float:
        """Return a required price or raise a stable preflight block."""

        result = self._load_result(asset_code, trade_date)
        if result is None:
            raise _blocked(
                "no historical equity price is available for the requested date",
                "AUTO_TRADE_PRICE_UNAVAILABLE",
            )
        return result.price

    def captured_result(self, asset_code: str, trade_date: date) -> PriceLookupResult | None:
        """Return the same result object that supplied the Engine's float value."""

        if type(asset_code) is not str or type(trade_date) is not date:
            return None
        key = (asset_code, trade_date)
        return self._results.get(key) if key in self._results else None

    def _load_result(self, asset_code: str, trade_date: date) -> PriceLookupResult | None:
        """Read once per exact asset/date key and preserve the original result object."""

        if type(asset_code) is not str or type(trade_date) is not date:
            return None
        key = (asset_code, trade_date)
        if key not in self._results:
            result = self._lookup.get_price_result(
                asset_code=asset_code,
                trade_date=trade_date,
                asset_type="equity",
            )
            if result is not None:
                if type(result) is not PriceLookupResult:
                    self._results[key] = None
                    return None
                try:
                    PriceLookupResult.__post_init__(result)
                except (ArithmeticError, TypeError, ValueError):
                    self._results[key] = None
                    return None
            self._results[key] = result
        return self._results[key]


class _RunActionKeySequence:
    """Allocate unique action keys within one guarded in-process run attempt."""

    def __init__(self, run_id: UUID) -> None:
        """Bind a persisted run UUID without creating or loading run state."""

        self._run_id = run_id
        self._next_ordinal = 0
        self._lock = Lock()

    def next(self, side: SimulatedTradeSide) -> str:
        """Return one non-reused action key shared by BUY and SELL callbacks."""

        with self._lock:
            self._next_ordinal += 1
            ordinal = self._next_ordinal
        key = f"auto:{self._run_id.hex}:{ordinal}:{side.value}"
        if len(key) > _ACTION_KEY_MAX_LENGTH:
            raise _blocked(
                "the run action identity cannot form a ledger key",
                "AUTO_TRADE_ACTION_IDENTITY_INVALID",
            )
        return key


class _AutomaticTradeExecutionCore:
    """Preflight one order, then delegate all writes and readback to the manual use case."""

    def __init__(
        self,
        *,
        run_id: UUID,
        execution_date: date,
        account_ids: tuple[int, ...],
        owner_reader: AutomaticTradeOwnerReader,
        position_repository: PositionRepositoryProtocol,
        identity_reader: CurrentReferenceManualIdentityReader,
        calendar_reader: PublishedExecutionCalendarReader,
        manual_use_case: ExecuteCurrentReferenceManualTradeUseCase,
        clock: SimulatedTradeExecutionClock,
        price_provider: AutomaticTradePriceProvider,
        expected_owner_id: int | None,
    ) -> None:
        """Bind run identity, source reads, and the existing manual execution path."""

        self._run_id = run_id
        self._execution_date = execution_date
        self._account_ids = account_ids
        self._expected_owner_id = expected_owner_id
        self._owner_reader = owner_reader
        self._position_repository = position_repository
        self._identity_reader = identity_reader
        self._calendar_reader = calendar_reader
        self._manual_use_case = manual_use_case
        self._clock = clock
        self._price_provider = price_provider
        self._action_keys = _RunActionKeySequence(run_id)

    def execute_buy(
        self,
        *,
        account_id: int,
        asset_code: str,
        asset_name: str,
        asset_type: str,
        quantity: int,
        price: float,
        reason: str,
        signal_id: int | None,
        execution_date: date | None,
    ) -> SimulatedTrade:
        """Execute one explicitly typed BUY through the exact existing manual path."""

        return self._execute(
            account_id=account_id,
            asset_code=asset_code,
            asset_name=asset_name,
            asset_type=asset_type,
            side=SimulatedTradeSide.BUY,
            quantity=quantity,
            price=price,
            reason=reason,
            signal_id=signal_id,
            execution_date=execution_date,
        )

    def execute_sell(
        self,
        *,
        account_id: int,
        asset_code: str,
        quantity: int,
        price: float,
        reason: str,
        execution_date: date | None,
    ) -> SimulatedTrade:
        """Read the existing position's exact name/type before submitting one SELL."""

        return self._execute(
            account_id=account_id,
            asset_code=asset_code,
            asset_name=None,
            asset_type=None,
            side=SimulatedTradeSide.SELL,
            quantity=quantity,
            price=price,
            reason=reason,
            signal_id=None,
            execution_date=execution_date,
        )

    def _execute(
        self,
        *,
        account_id: int,
        asset_code: str,
        asset_name: str | None,
        asset_type: str | None,
        side: SimulatedTradeSide,
        quantity: int,
        price: float,
        reason: str,
        signal_id: int | None,
        execution_date: date | None,
    ) -> SimulatedTrade:
        """Validate one callback and delegate identity, UoW, and receipt readback."""

        self._require_order_scope(account_id, execution_date)
        self._require_asset_code(asset_code)
        if side is SimulatedTradeSide.SELL:
            try:
                position = self._position_repository.get_position(account_id, asset_code)
            except Exception as error:
                raise _blocked(
                    "current position metadata could not be read",
                    "AUTO_TRADE_POSITION_UNAVAILABLE",
                ) from error
            if type(position) is not Position:
                raise _blocked(
                    "SELL requires an exact current position",
                    "AUTO_TRADE_POSITION_UNAVAILABLE",
                )
            if (
                type(position.account_id) is not int
                or position.account_id != account_id
                or type(position.asset_code) is not str
                or position.asset_code != asset_code
                or type(position.asset_type) is not str
                or position.asset_type != "equity"
                or type(position.asset_name) is not str
                or not position.asset_name
            ):
                raise _blocked(
                    "SELL position metadata is not an exact equity identity",
                    "AUTO_TRADE_POSITION_IDENTITY_INVALID",
                )
            asset_name = position.asset_name
            asset_type = position.asset_type
            signal_id = position.signal_id
        else:
            if type(asset_name) is not str or not asset_name:
                raise _blocked(
                    "BUY asset name must be supplied by the automatic candidate",
                    "AUTO_TRADE_ASSET_NAME_INVALID",
                )
            if type(asset_type) is not str or asset_type != "equity":
                raise _blocked(
                    "automatic execution requires an explicit equity asset type",
                    "AUTO_TRADE_ASSET_TYPE_UNSUPPORTED",
                )
        quantity_decimal = self._quantity_decimal(quantity)
        price_decimal = self._price_decimal(price)
        self._require_captured_price(asset_code, price, price_decimal)

        try:
            user_id = self._owner_reader.get_owner_id(account_id=account_id)
        except Exception as error:
            raise _blocked(
                "simulated account ownership could not be read",
                "AUTO_TRADE_OWNER_UNAVAILABLE",
            ) from error
        if type(user_id) is not int or user_id <= 0:
            raise _blocked(
                "simulated account has no exact persisted owner",
                "AUTO_TRADE_OWNER_UNAVAILABLE",
            )
        if self._expected_owner_id is not None:
            if user_id != self._expected_owner_id:
                raise _blocked(
                    "account ownership differs from the authorized caller",
                    "AUTO_TRADE_OWNER_CHANGED",
                )
            user_id = self._expected_owner_id

        cutoff = self._current_cutoff()
        identity = self._validate_current_identity(asset_code=asset_code, cutoff=cutoff)
        self._validate_formal_session(identity=identity, cutoff=cutoff)
        key = self._action_keys.next(side)
        try:
            request = ManualSimulatedTradeRequest(
                account_id=account_id,
                user_id=user_id,
                idempotency_key=key,
                asset_code=asset_code,
                asset_name=asset_name,
                asset_type=asset_type,
                side=side,
                quantity=quantity_decimal,
                price=price_decimal,
                reason=reason,
                signal_id=signal_id,
            )
        except (ArithmeticError, TypeError, ValueError, SimulatedTradeExecutionInputError) as error:
            raise _blocked(
                "automatic trade request is not exactly representable",
                "AUTO_TRADE_INTENT_INVALID",
            ) from error

        try:
            result = self._manual_use_case.execute(request, as_of=cutoff)
        except SimulatedTradeExecutionResultUnknown:
            raise
        except SimulatedTradeAccountScopeUnavailable as error:
            raise _blocked(
                "the account no longer matches its active execution scope",
                "AUTO_TRADE_ACCOUNT_SCOPE_UNAVAILABLE",
            ) from error
        except (
            ExecutionCalendarUnavailable,
            ExecutionFeeScheduleUnavailable,
            ExecutionInstrumentIdentityUnavailable,
            SimulatedTradeExecutionInputError,
            SimulatedTradeIdempotencyConflict,
            SimulatedTradeExecutionBlocked,
        ) as error:
            try:
                current_owner = self._owner_reader.get_owner_id(account_id=account_id)
            except Exception as scope_error:
                raise _blocked(
                    "the account execution scope cannot be revalidated after rejection",
                    "AUTO_TRADE_ACCOUNT_SCOPE_UNAVAILABLE",
                ) from scope_error
            if type(current_owner) is not int or current_owner != user_id:
                raise _blocked(
                    "the account no longer matches the rejected order's owner scope",
                    "AUTO_TRADE_ACCOUNT_SCOPE_UNAVAILABLE",
                ) from error
            raise _blocked(
                "the existing settlement path rejected the order before a ledger result",
                "AUTO_TRADE_SETTLEMENT_PREFLIGHT_BLOCKED",
            ) from error
        except Exception as error:
            raise AutomaticTradeExecutionOutcomeUnknown(
                "manual execution may have written; preserve the run as indeterminate",
                code="AUTO_TRADE_EXECUTION_OUTCOME_UNKNOWN",
                details={"run_id": str(self._run_id)},
            ) from error
        if (
            type(result) is not ManualSimulatedTradeResult
            or type(result.trade) is not SimulatedTrade
        ):
            raise AutomaticTradeExecutionOutcomeUnknown(
                "manual execution returned no exact trade after the ledger call",
                code="AUTO_TRADE_EXECUTION_READBACK_UNKNOWN",
                details={"run_id": str(self._run_id)},
            )
        return result.trade

    def _require_captured_price(
        self,
        asset_code: str,
        engine_price: float,
        exact_price: Decimal,
    ) -> None:
        """Bind the order to the exact historical, non-fallback result seen by Engine."""

        result = self._price_provider.captured_result(asset_code, self._execution_date)
        if type(result) is not PriceLookupResult:
            raise _blocked(
                "the Engine did not use a captured source-backed price result",
                "AUTO_TRADE_PRICE_EVIDENCE_UNAVAILABLE",
            )
        try:
            PriceLookupResult.__post_init__(result)
        except (ArithmeticError, OverflowError, TypeError, ValueError) as error:
            raise _blocked(
                "the captured price result failed validation",
                "AUTO_TRADE_PRICE_EVIDENCE_INVALID",
            ) from error
        if (
            result.requested_code != asset_code
            or result.normalized_code != asset_code
            or type(result.as_of) is not date
            or result.as_of != self._execution_date
            or result.freshness != "historical"
            or result.is_fallback is not False
            or type(engine_price) is not float
            or not math.isfinite(engine_price)
            or Decimal(str(result.price)) != exact_price
        ):
            raise _blocked(
                "the captured historical price differs from the exact order",
                "AUTO_TRADE_PRICE_EVIDENCE_MISMATCH",
            )

    def _validate_current_identity(
        self,
        *,
        asset_code: str,
        cutoff: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV2:
        """Require the exact V2 current-reference identity at the shared cutoff."""

        try:
            identity = self._identity_reader.resolve_current_reference_identity(
                asset_code=asset_code,
                as_of=cutoff,
            )
            if type(identity) is not ExecutionInstrumentIdentityEvidenceV2:
                raise ValueError("exact V2 identity is unavailable")
            identity.validate_at(as_of=cutoff)
            if identity.asset_code != asset_code or identity.selection.selected_at != cutoff:
                raise ValueError("identity selection differs from the exact asset or cutoff")
            return identity
        except Exception as error:
            raise _blocked(
                "the exact current-reference identity is unavailable at the execution cutoff",
                "AUTO_TRADE_IDENTITY_UNAVAILABLE",
            ) from error

    def _validate_formal_session(
        self,
        *,
        identity: ExecutionInstrumentIdentityEvidenceV2,
        cutoff: datetime,
    ) -> None:
        """Require the formal published session to equal the persisted run date."""

        try:
            evidence = self._calendar_reader.get_effective_execution_calendar(
                exchange=identity.source_exchange,
                as_of=cutoff,
                coverage_start=None,
            )
            if type(evidence) is not ExecutionCalendarEvidence:
                raise ValueError("formal calendar evidence is unavailable")
            if evidence.snapshot.exchange != identity.source_exchange:
                raise ValueError("calendar exchange differs from exact identity")
            session = evidence.current_open_session(cutoff)
        except Exception as error:
            raise _blocked(
                "a valid published exchange session is unavailable",
                "AUTO_TRADE_FORMAL_CALENDAR_UNAVAILABLE",
            ) from error
        if session != self._execution_date:
            raise _blocked(
                "the formal exchange session differs from the persisted run date",
                "AUTO_TRADE_EXECUTION_DATE_MISMATCH",
            )

    def _require_order_scope(self, account_id: int, execution_date: date | None) -> None:
        """Bind callbacks to one valid account and the persisted run's exact date."""

        if type(account_id) is not int or account_id not in self._account_ids:
            raise _blocked("account id is invalid", "AUTO_TRADE_ACCOUNT_INVALID")
        if type(execution_date) is not date or execution_date != self._execution_date:
            raise _blocked(
                "the order date differs from the persisted run date",
                "AUTO_TRADE_EXECUTION_DATE_MISMATCH",
            )

    @staticmethod
    def _require_asset_code(asset_code: str) -> None:
        """Require a bounded canonical asset token without prefix inference."""

        if (
            type(asset_code) is not str
            or not asset_code
            or len(asset_code) > _ASSET_TOKEN_MAX_LENGTH
            or asset_code.strip() != asset_code
            or any(character.isspace() for character in asset_code)
        ):
            raise _blocked("asset code is invalid", "AUTO_TRADE_ASSET_CODE_INVALID")

    def _current_cutoff(self) -> datetime:
        """Capture one aware UTC cutoff for identity, calendar, and manual execution."""

        try:
            value = self._clock.now()
            if type(value) is not datetime or value.tzinfo is None:
                raise ValueError("clock must be aware")
            if value.utcoffset() != timedelta(0):
                raise ValueError("clock must be UTC")
            return value.astimezone(UTC)
        except (ArithmeticError, OverflowError, TypeError, ValueError) as error:
            raise _blocked(
                "execution cutoff is not aware UTC",
                "AUTO_TRADE_CUTOFF_INVALID",
            ) from error

    @staticmethod
    def _quantity_decimal(quantity: int) -> Decimal:
        """Convert only exact positive whole shares to the ledger representation."""

        if type(quantity) is not int or quantity <= 0:
            raise _blocked(
                "quantity must be a positive exact integer",
                "AUTO_TRADE_QUANTITY_INVALID",
            )
        return Decimal(quantity)

    @staticmethod
    def _price_decimal(price: float) -> Decimal:
        """Convert the Engine float through its exact displayed decimal text."""

        if type(price) is not float or not math.isfinite(price) or price <= 0:
            raise _blocked("price must be positive and finite", "AUTO_TRADE_PRICE_INVALID")
        try:
            return Decimal(str(price))
        except (ArithmeticError, TypeError, ValueError) as error:
            raise _blocked(
                "price cannot be represented exactly by the ledger",
                "AUTO_TRADE_PRICE_INVALID",
            ) from error


class AutomaticTradeBuyOrderExecutor:
    """Expose the existing AutoTradingEngine BUY callback signature."""

    def __init__(self, core: _AutomaticTradeExecutionCore) -> None:
        """Bind the shared per-run execution core."""

        self._core = core

    def execute(
        self,
        account_id: int,
        asset_code: str,
        asset_name: str,
        asset_type: str,
        quantity: int,
        price: float,
        reason: str = "",
        signal_id: int | None = None,
        execution_date: date | None = None,
    ) -> SimulatedTrade:
        """Submit one BUY and return the manual use case's owned trade readback."""

        return self._core.execute_buy(
            account_id=account_id,
            asset_code=asset_code,
            asset_name=asset_name,
            asset_type=asset_type,
            quantity=quantity,
            price=price,
            reason=reason,
            signal_id=signal_id,
            execution_date=execution_date,
        )


class AutomaticTradeSellOrderExecutor:
    """Expose the existing AutoTradingEngine SELL callback signature."""

    def __init__(self, core: _AutomaticTradeExecutionCore) -> None:
        """Bind the same per-run core and action-key sequence used by BUY."""

        self._core = core

    def execute(
        self,
        account_id: int,
        asset_code: str,
        quantity: int,
        price: float,
        reason: str = "",
        execution_date: date | None = None,
    ) -> SimulatedTrade:
        """Submit one SELL using its persisted position name and explicit asset type."""

        return self._core.execute_sell(
            account_id=account_id,
            asset_code=asset_code,
            quantity=quantity,
            price=price,
            reason=reason,
            execution_date=execution_date,
        )


class AutomaticTradeExecutionBridge:
    """Build Engine-compatible adapters for a persisted automatic-run UUID/date."""

    def __init__(
        self,
        *,
        run_id: UUID,
        execution_date: date,
        account_ids: tuple[int, ...],
        owner_reader: AutomaticTradeOwnerReader,
        position_repository: PositionRepositoryProtocol,
        identity_reader: CurrentReferenceManualIdentityReader,
        calendar_reader: PublishedExecutionCalendarReader,
        manual_use_case: ExecuteCurrentReferenceManualTradeUseCase,
        clock: SimulatedTradeExecutionClock,
        price_lookup: AutomaticTradePriceLookup,
        expected_owner_id: int | None = None,
    ) -> None:
        """Wire ports without reading sources or writing; the run guard starts execution."""

        if type(run_id) is not UUID or type(execution_date) is not date:
            raise ValueError("exact persisted run UUID and execution date are required")
        if expected_owner_id is not None and (
            type(expected_owner_id) is not int or expected_owner_id <= 0
        ):
            raise ValueError("expected owner must be an exact positive integer")
        if (
            type(account_ids) is not tuple
            or any(type(value) is not int or value <= 0 for value in account_ids)
            or len(set(account_ids)) != len(account_ids)
        ):
            raise ValueError("exact frozen account ids are required")
        self.price_provider = AutomaticTradePriceProvider(price_lookup)
        core = _AutomaticTradeExecutionCore(
            run_id=run_id,
            execution_date=execution_date,
            account_ids=account_ids,
            expected_owner_id=expected_owner_id,
            owner_reader=owner_reader,
            position_repository=position_repository,
            identity_reader=identity_reader,
            calendar_reader=calendar_reader,
            manual_use_case=manual_use_case,
            clock=clock,
            price_provider=self.price_provider,
        )
        self.buy_use_case = AutomaticTradeBuyOrderExecutor(core)
        self.sell_use_case = AutomaticTradeSellOrderExecutor(core)


def _blocked(message: str, code: str) -> AutomaticTradeExecutionPreflightBlocked:
    """Create a stable pre-write block without exposing provider payloads."""

    return AutomaticTradeExecutionPreflightBlocked(message, code=code)


_bridge_factory: Callable[[UUID, int | None], AutomaticTradeExecutionBridge] | None = None


def register_automatic_trade_execution_bridge(
    factory: Callable[[UUID, int | None], AutomaticTradeExecutionBridge],
) -> None:
    """Register the source-backed composition without reading sources at startup."""
    global _bridge_factory
    _bridge_factory = factory


def get_automatic_trade_execution_bridge(
    invocation_id: UUID, *, expected_owner_id: int | None = None
) -> AutomaticTradeExecutionBridge:
    """Build the guarded run's adapters with no legacy-writer fallback."""
    if _bridge_factory is None:
        raise AutomaticTradeExecutionPreflightBlocked(
            "automatic execution bridge is not registered"
        )
    return _bridge_factory(invocation_id, expected_owner_id)


__all__: tuple[str, ...] = (
    "AutomaticTradeBuyOrderExecutor",
    "AutomaticTradeExecutionBridge",
    "AutomaticTradeExecutionOutcomeUnknown",
    "AutomaticTradeExecutionPreflightBlocked",
    "AutomaticTradeOwnerReader",
    "AutomaticTradePriceLookup",
    "AutomaticTradePriceProvider",
    "AutomaticTradeSellOrderExecutor",
)
