"""Read and reconcile current prices, portfolio value, and class values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from apps.account.application.market_price_contracts import MarketPriceProvider, MarketPriceResult
from apps.data_center.application.query_use_cases import latest_daily_market_observation_is_current
from apps.simulated_trading.application.rebalance_preview_reference_close import (
    M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    PricePublicationReference,
    ReferenceClosePriceReader,
    ReferenceCloseReadResult,
    ReferencePriceBasis,
)
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
    price_publications: dict[str, PricePublicationReference] = field(default_factory=dict)
    reference_price_basis: ReferencePriceBasis = "market"


class CurrentRebalanceValuationReader:
    """Read current formal price evidence once and reconcile every displayed total."""

    def __init__(
        self,
        price_reader: MarketPriceProvider,
        reference_close_reader: ReferenceClosePriceReader | None = None,
    ) -> None:
        """Bind normal market prices and the optional M1 publication-close port."""

        self._price_reader = price_reader
        self._reference_close_reader = reference_close_reader

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
        reference_price_basis: ReferencePriceBasis = "market",
    ) -> CurrentRebalanceValuation:
        """Return current prices plus class and total values at one cutoff."""

        prices, reasons, publications = self._read_prices(
            asset_codes,
            cutoff=cutoff,
            current_local_date=current_local_date,
            reference_price_basis=reference_price_basis,
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
            price_publications=publications,
            reference_price_basis=reference_price_basis,
        )

    def _read_prices(
        self,
        asset_codes: set[str],
        *,
        cutoff: datetime,
        current_local_date: date,
        reference_price_basis: ReferencePriceBasis,
    ) -> tuple[
        dict[str, MarketPriceResult | None],
        dict[str, str],
        dict[str, PricePublicationReference],
    ]:
        """Read current prices and enforce formal realtime/close freshness semantics."""

        results: dict[str, MarketPriceResult | None] = {}
        reasons: dict[str, str] = {}
        publications: dict[str, PricePublicationReference] = {}
        for raw_code in sorted(asset_codes):
            code = _normalized_code(raw_code)
            if code is None or code in results:
                continue
            try:
                if reference_price_basis == "published_close":
                    self._read_published_close(
                        code=code,
                        cutoff=cutoff,
                        results=results,
                        reasons=reasons,
                        publications=publications,
                    )
                    continue
                if reference_price_basis != "market":
                    results[code] = None
                    reasons[code] = "M1_REFERENCE_PRICE_BASIS_INVALID"
                    continue
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
        identities = {
            (
                reference.publication_id,
                reference.publication_hash,
                reference.publication_run_id,
            )
            for reference in publications.values()
        }
        if reference_price_basis == "published_close" and len(identities) > 1:
            for code in publications:
                results[code] = None
                reasons[code] = "M1_REFERENCE_PUBLICATION_MIXED"
            publications.clear()
        return results, reasons, publications

    def _read_published_close(
        self,
        *,
        code: str,
        cutoff: datetime,
        results: dict[str, MarketPriceResult | None],
        reasons: dict[str, str],
        publications: dict[str, PricePublicationReference],
    ) -> None:
        """Validate one typed close result before it contributes to valuation."""

        reader = self._reference_close_reader
        if reader is None:
            results[code] = None
            reasons[code] = "M1_REFERENCE_CLOSE_READER_UNAVAILABLE"
            return
        observation = reader.read(asset_code=code, cutoff=cutoff)
        if type(observation) is not ReferenceCloseReadResult:
            results[code] = None
            reasons[code] = "M1_REFERENCE_CLOSE_RESULT_INVALID"
            return
        price = observation.price_result
        publication = observation.publication
        if price is None:
            results[code] = None
            reasons[code] = observation.blocked_reason or "M1_REFERENCE_CLOSE_RESULT_INVALID"
            return
        if publication is None or not _valid_published_close_result(
            code=code,
            cutoff=cutoff,
            price=price,
            publication=publication,
        ):
            results[code] = None
            reasons[code] = "M1_REFERENCE_PUBLICATION_SCOPE_INVALID"
            return
        results[code] = price
        publications[code] = publication

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


def _valid_published_close_result(
    *,
    code: str,
    cutoff: datetime,
    price: MarketPriceResult,
    publication: PricePublicationReference,
) -> bool:
    """Require the price and provenance DTO to describe the same exact close."""

    if (
        type(price) is not MarketPriceResult
        or price.normalized_code != code
        or type(price.as_of) is not date
        or price.as_of != publication.bar_date
        or price.freshness != "close_fallback"
        or price.is_fallback is not True
        or price.observed_at != publication.source_observed_at
        or publication.dataset_key != "equity.price.bar"
        or publication.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
        or publication.knowledge_cutoff != cutoff
        or publication.source_observed_at > cutoff
        or publication.publication_as_of > cutoff
        or publication.published_at > cutoff
    ):
        return False
    try:
        MarketPriceResult.__post_init__(price)
    except (ArithmeticError, TypeError, ValueError):
        return False
    return True


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
