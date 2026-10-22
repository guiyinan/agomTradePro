"""Read and reconcile current prices, portfolio value, and class values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from apps.account.application.market_price_contracts import MarketPriceProvider, MarketPriceResult
from apps.data_center.application.query_use_cases import latest_daily_market_observation_is_current
from apps.simulated_trading.domain.entities import Position, SimulatedAccount
from apps.simulated_trading.domain.rebalance_preview_math import (
    calculate_class_amount,
    calculate_portfolio_value,
)


@dataclass(frozen=True, slots=True)
class CurrentRebalanceValuation:
    """One price snapshot and all valuation totals derived from that snapshot."""

    prices: dict[str, MarketPriceResult | None]
    price_reasons: dict[str, str]
    portfolio_value: Decimal | None
    class_amounts: dict[str, Decimal | None]


class CurrentRebalanceValuationReader:
    """Read current formal price evidence once and reconcile every displayed total."""

    def __init__(self, price_reader: MarketPriceProvider) -> None:
        """Bind the formal data-center price application port."""

        self._price_reader = price_reader

    def read(
        self,
        *,
        asset_codes: set[str],
        account: SimulatedAccount,
        positions: tuple[Position, ...],
        checks: tuple[Mapping[str, object], ...],
        position_codes_valid: bool,
        cutoff: datetime,
        current_local_date: date,
    ) -> CurrentRebalanceValuation:
        """Return current prices plus class and total values at one cutoff."""

        prices, reasons = self._read_prices(
            asset_codes,
            cutoff=cutoff,
            current_local_date=current_local_date,
        )
        portfolio_value = self._portfolio_value(
            account=account,
            positions=positions,
            prices=prices,
            position_codes_valid=position_codes_valid,
        )
        class_amounts = self._class_amounts(
            checks=checks,
            positions=positions,
            prices=prices,
            position_codes_valid=position_codes_valid,
        )
        return CurrentRebalanceValuation(
            prices=prices,
            price_reasons=reasons,
            portfolio_value=portfolio_value,
            class_amounts=class_amounts,
        )

    def _read_prices(
        self,
        asset_codes: set[str],
        *,
        cutoff: datetime,
        current_local_date: date,
    ) -> tuple[dict[str, MarketPriceResult | None], dict[str, str]]:
        """Read current prices and enforce formal realtime/close freshness semantics."""

        results: dict[str, MarketPriceResult | None] = {}
        reasons: dict[str, str] = {}
        for raw_code in sorted(asset_codes):
            code = _normalized_code(raw_code)
            if code is None or code in results:
                continue
            try:
                result = self._price_reader.get_price_result(raw_code, trade_date=None)
                if result is None:
                    results[code] = None
                    reasons[code] = "QUOTE_UNAVAILABLE"
                    continue
                if type(result) is not MarketPriceResult:
                    results[code] = None
                    reasons[code] = "QUOTE_RESULT_INVALID"
                    continue
                MarketPriceResult.__post_init__(result)
                if _normalized_code(result.normalized_code) != code:
                    results[code] = None
                    reasons[code] = "QUOTE_CODE_MISMATCH"
                    continue
                if result.as_of is not None and result.as_of > current_local_date:
                    results[code] = None
                    reasons[code] = "QUOTE_DATE_IN_FUTURE"
                    continue
                if result.observed_at is not None and result.observed_at > cutoff:
                    results[code] = None
                    reasons[code] = "QUOTE_OBSERVATION_IN_FUTURE"
                    continue
                if result.freshness == "historical":
                    results[code] = None
                    reasons[code] = "QUOTE_NOT_CURRENT"
                    continue
                if result.freshness == "realtime":
                    if result.is_fallback or result.observed_at is None:
                        results[code] = None
                        reasons[code] = "QUOTE_TIME_UNKNOWN"
                        continue
                elif result.freshness == "close_fallback":
                    if not result.is_fallback:
                        results[code] = None
                        reasons[code] = "QUOTE_FALLBACK_FLAG_INVALID"
                        continue
                    if result.as_of is None:
                        results[code] = None
                        reasons[code] = "QUOTE_DATE_UNKNOWN"
                        continue
                    if not latest_daily_market_observation_is_current(
                        asset_code=code,
                        observed_at=result.as_of,
                        now=cutoff,
                    ):
                        results[code] = None
                        reasons[code] = "QUOTE_OBSERVATION_STALE"
                        continue
                else:
                    results[code] = None
                    reasons[code] = "QUOTE_FRESHNESS_INVALID"
                    continue
                results[code] = result
            except (ArithmeticError, AttributeError, TypeError, ValueError):
                results[code] = None
                reasons[code] = "QUOTE_RESULT_INVALID"
        return results, reasons

    def _portfolio_value(
        self,
        *,
        account: SimulatedAccount,
        positions: tuple[Position, ...],
        prices: dict[str, MarketPriceResult | None],
        position_codes_valid: bool,
    ) -> Decimal | None:
        """Recompute a consistent total from known cash and formal holding quotes."""

        cash = _known_cash(account)
        if cash is None or not position_codes_valid:
            return None
        holdings = tuple(
            (
                _decimal_value(position.quantity),
                _price_decimal(prices.get(_normalized_code(position.asset_code) or "")),
            )
            for position in positions
        )
        return calculate_portfolio_value(cash_before=cash, holdings=holdings)

    def _class_amounts(
        self,
        *,
        checks: tuple[Mapping[str, object], ...],
        positions: tuple[Position, ...],
        prices: dict[str, MarketPriceResult | None],
        position_codes_valid: bool,
    ) -> dict[str, Decimal | None]:
        """Mark classes from the same fresh per-position quotes as the total."""

        class_codes: dict[str, str] = {}
        class_names: set[str] = set()
        for check in checks:
            if check.get("scope") == "asset_class":
                name = _optional_text(check.get("asset_class"))
                if name is not None:
                    class_names.add(name)
            elif check.get("scope") == "asset":
                code = _normalized_code(check.get("asset_code"))
                name = _optional_text(check.get("asset_class"))
                if code is not None and name is not None:
                    if code in class_codes and class_codes[code] != name:
                        position_codes_valid = False
                    class_codes[code] = name
        amounts: dict[str, Decimal | None] = dict.fromkeys(class_names, None)
        if not position_codes_valid:
            return amounts
        grouped: dict[str, list[tuple[Decimal | None, Decimal | None]]] = {
            name: [] for name in class_names
        }
        for position in positions:
            code = _normalized_code(position.asset_code)
            class_name = class_codes.get(code or "")
            if class_name is None or class_name not in grouped:
                return amounts
            grouped[class_name].append(
                (
                    _decimal_value(position.quantity),
                    _price_decimal(prices.get(code or "")),
                )
            )
        return {name: calculate_class_amount(tuple(holdings)) for name, holdings in grouped.items()}


def _known_cash(account: SimulatedAccount) -> Decimal | None:
    """Expose cash only when its authoritative simulated-ledger flag is true."""

    if account.cash_known is not True:
        return None
    value = _decimal_value(account.current_cash)
    return value if value is not None and value >= 0 else None


def _optional_text(value: object) -> str | None:
    """Return only a nonempty string from an inspection JSON object."""

    return value if type(value) is str and value else None


def _decimal_value(value: object) -> Decimal | None:
    """Parse one finite decimal from a typed domain or JSON numeric value."""

    if isinstance(value, bool) or value is None:
        return None
    try:
        result = value if type(value) is Decimal else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _price_decimal(result: MarketPriceResult | None) -> Decimal | None:
    """Convert a validated provider price without synthesizing source fields."""

    return _decimal_value(result.price) if result is not None else None


def _normalized_code(value: object) -> str | None:
    """Normalize only case/outer whitespace for matching existing account codes."""

    if type(value) is not str or not value or value.strip() != value:
        return None
    return value.upper()


__all__: tuple[str, ...] = (
    "CurrentRebalanceValuation",
    "CurrentRebalanceValuationReader",
)
