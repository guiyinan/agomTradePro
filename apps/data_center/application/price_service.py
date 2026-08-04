"""
Unified price service backed by data-center facts only.

This is the canonical price lookup entry for business modules.
"""

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, TypedDict, cast

from apps.data_center.application.dtos import QuoteResponse
from apps.data_center.application.public import (
    get_published_fund_nav_series,
    get_published_price_bar_series,
    get_published_quote_payloads,
)
from apps.data_center.application.query_use_cases import (
    QueryLatestQuoteUseCase,
    latest_daily_market_observation_is_current,
)
from apps.data_center.composition import (
    get_fund_nav_repository,
    get_price_bar_repository,
    get_quote_snapshot_repository,
)
from apps.data_center.domain.entities import FundNavFact, PriceBar
from apps.data_center.domain.protocols import (
    FundNavRepositoryProtocol,
    PriceBarRepositoryProtocol,
    QuoteSnapshotRepositoryProtocol,
)
from core.exceptions import DataFetchError

logger = logging.getLogger(__name__)


class FundPriceResult(TypedDict):
    """Validated fund price payload from a repository or external adapter."""

    price: float
    as_of: date
    source: str


@dataclass(frozen=True)
class PriceLookupResult:
    """Validated canonical price returned to business modules."""

    requested_code: str
    normalized_code: str
    price: float
    as_of: date | None
    source: str
    freshness: str
    is_fallback: bool = False
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        """Reject unusable prices and unauditable result metadata."""

        if not self.requested_code.strip() or not self.normalized_code.strip():
            raise ValueError("价格查询结果缺少资产代码")
        if isinstance(self.price, bool) or not math.isfinite(self.price) or self.price <= 0:
            raise ValueError("价格查询结果必须为正有限数")
        if self.as_of is not None and not isinstance(self.as_of, date):
            raise ValueError("价格查询结果日期无效")
        if not self.source.strip():
            raise ValueError("价格查询结果缺少数据来源")
        if self.freshness not in {"historical", "realtime", "close_fallback"}:
            raise ValueError("价格查询结果新鲜度类型无效")
        if self.observed_at is not None and (
            self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None
        ):
            raise ValueError("价格查询结果观测时间必须包含时区")
        if self.freshness == "realtime" and self.observed_at is None:
            raise ValueError("实时价格查询结果必须包含源观测时间")


class UnifiedPriceService:
    """Unified price lookup over standardized data-center repositories."""

    def __init__(
        self,
        latest_quote_max_age_hours: float = QueryLatestQuoteUseCase.DEFAULT_MAX_AGE_HOURS,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        if (
            isinstance(latest_quote_max_age_hours, bool)
            or not isinstance(latest_quote_max_age_hours, int | float)
            or not math.isfinite(float(latest_quote_max_age_hours))
            or float(latest_quote_max_age_hours) <= 0.0
        ):
            raise ValueError("latest_quote_max_age_hours 必须为正有限数")
        self._fund_adapter: Any | None = None
        self._latest_quote_max_age_hours = float(latest_quote_max_age_hours)
        self._now_provider = now_provider or (lambda: datetime.now(UTC))
        self._dc_price_repo: PriceBarRepositoryProtocol = get_price_bar_repository()
        self._dc_quote_repo: QuoteSnapshotRepositoryProtocol = get_quote_snapshot_repository()
        self._dc_fund_nav_repo: FundNavRepositoryProtocol = get_fund_nav_repository()

    @property
    def fund_adapter(self) -> Any | None:
        """Return an explicitly injected migration adapter, never build one implicitly."""

        return self._fund_adapter

    def normalize_asset_code(
        self,
        asset_code: str,
        asset_type: str | None = None,
    ) -> str:
        code = (asset_code or "").strip().upper()
        if not code:
            raise ValueError("asset_code 不能为空")

        if "." in code:
            return code

        if asset_type == "fund":
            return code

        if code.startswith(("8", "4")):
            return f"{code}.BJ"
        if code.startswith(("5", "6")):
            return f"{code}.SH"
        if code.startswith(("0", "1", "2", "3")):
            return f"{code}.SZ"

        return code

    def get_price(
        self,
        asset_code: str,
        trade_date: date | None = None,
        asset_type: str | None = None,
    ) -> float | None:
        result = self.get_price_result(
            asset_code=asset_code,
            trade_date=trade_date,
            asset_type=asset_type,
        )
        return result.price if result else None

    def get_latest_price(
        self,
        asset_code: str,
        asset_type: str | None = None,
    ) -> float | None:
        return self.get_price(asset_code=asset_code, trade_date=None, asset_type=asset_type)

    def require_price(
        self,
        asset_code: str,
        trade_date: date | None = None,
        asset_type: str | None = None,
    ) -> float:
        return self.require_price_result(
            asset_code=asset_code,
            trade_date=trade_date,
            asset_type=asset_type,
        ).price

    def require_latest_price(
        self,
        asset_code: str,
        asset_type: str | None = None,
    ) -> float:
        return self.require_price(
            asset_code=asset_code,
            trade_date=None,
            asset_type=asset_type,
        )

    def require_latest_price_result(
        self,
        asset_code: str,
        asset_type: str | None = None,
    ) -> PriceLookupResult:
        """Return the latest decision-safe price with source observation metadata."""

        return self.require_price_result(
            asset_code=asset_code,
            trade_date=None,
            asset_type=asset_type,
        )

    def require_price_result(
        self,
        asset_code: str,
        trade_date: date | None = None,
        asset_type: str | None = None,
    ) -> PriceLookupResult:
        normalized_code = self.normalize_asset_code(asset_code, asset_type=asset_type)
        result = self.get_price_result(
            asset_code=asset_code,
            trade_date=trade_date,
            asset_type=asset_type,
        )
        if result is not None:
            return result

        when_label = (
            f"在 {trade_date.isoformat()} 的历史价格" if trade_date is not None else "的最新价格"
        )
        raise DataFetchError(
            message=f"无法获取 {asset_code} {when_label}",
            code="PRICE_UNAVAILABLE",
            details={
                "requested_code": asset_code,
                "normalized_code": normalized_code,
                "trade_date": trade_date.isoformat() if trade_date is not None else None,
                "asset_type": asset_type,
            },
        )

    def get_price_result(
        self,
        asset_code: str,
        trade_date: date | None = None,
        asset_type: str | None = None,
    ) -> PriceLookupResult | None:
        normalized_code = self.normalize_asset_code(asset_code, asset_type=asset_type)

        if trade_date is not None:
            historical = self._get_historical_price(normalized_code, trade_date)
            if historical is not None:
                result = self._build_price_result(
                    requested_code=asset_code,
                    normalized_code=normalized_code,
                    raw_price=historical.close,
                    as_of=historical.bar_date,
                    raw_source=historical.source,
                    freshness="historical",
                    is_fallback=False,
                )
                if result is not None:
                    return result

            if self._should_use_fund_nav(normalized_code, asset_type=asset_type):
                fund_nav = self._get_fund_nav_price(
                    normalized_code,
                    trade_date,
                    asset_type=asset_type,
                )
                if fund_nav is not None:
                    return self._build_price_result(
                        requested_code=asset_code,
                        normalized_code=normalized_code,
                        raw_price=fund_nav["price"],
                        as_of=fund_nav["as_of"],
                        raw_source=fund_nav["source"],
                        freshness="historical",
                        is_fallback=True,
                    )
            return None

        quote = self._get_realtime_quote(normalized_code)
        if quote is not None:
            result = self._build_price_result(
                requested_code=asset_code,
                normalized_code=normalized_code,
                raw_price=quote.current_price,
                as_of=None,
                raw_source=quote.source,
                freshness="realtime",
                is_fallback=False,
                observed_at=quote.snapshot_at,
            )
            if result is not None:
                return result

        recent_close = self._get_recent_close(normalized_code)
        if recent_close is not None:
            result = self._build_price_result(
                requested_code=asset_code,
                normalized_code=normalized_code,
                raw_price=recent_close.close,
                as_of=recent_close.bar_date,
                raw_source=recent_close.source,
                freshness="close_fallback",
                is_fallback=True,
            )
            if result is not None:
                return result

        if self._should_use_fund_nav(normalized_code, asset_type=asset_type):
            fund_nav = self._get_fund_nav_price(
                normalized_code,
                None,
                asset_type=asset_type,
            )
            if fund_nav is not None:
                return self._build_price_result(
                    requested_code=asset_code,
                    normalized_code=normalized_code,
                    raw_price=fund_nav["price"],
                    as_of=fund_nav["as_of"],
                    raw_source=fund_nav["source"],
                    freshness="close_fallback",
                    is_fallback=True,
                )

        return None

    @staticmethod
    def _build_price_result(
        *,
        requested_code: str,
        normalized_code: str,
        raw_price: object,
        as_of: date | None,
        raw_source: object,
        freshness: str,
        is_fallback: bool,
        observed_at: datetime | None = None,
    ) -> PriceLookupResult | None:
        """Build a canonical result only from positive, attributable prices."""

        if isinstance(raw_price, bool):
            return None
        try:
            price = float(cast(Any, raw_price))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(price) or price <= 0:
            return None
        if not isinstance(raw_source, str) or not raw_source.strip():
            return None
        return PriceLookupResult(
            requested_code=requested_code,
            normalized_code=normalized_code,
            price=price,
            as_of=as_of,
            source=raw_source.strip(),
            freshness=freshness,
            is_fallback=is_fallback,
            observed_at=observed_at,
        )

    def _get_realtime_quote(self, normalized_code: str) -> QuoteResponse | None:
        try:
            published = get_published_quote_payloads([normalized_code])
            if self._publication_blocked(published):
                return None
            rows = published.get("rows")
            if not isinstance(rows, list):
                return None
            row = next(
                (
                    item
                    for item in rows
                    if isinstance(item, dict)
                    and str(item.get("asset_code", "")).strip().upper() == normalized_code
                ),
                None,
            )
            if row is None:
                return None
            snapshot_at = self._parse_datetime(row.get("snapshot_at"))
            current_price = self._parse_float(row.get("current_price"))
            source = row.get("source")
            if snapshot_at is None or current_price is None or not isinstance(source, str):
                return None
            quote = QueryLatestQuoteUseCase.build_response(
                asset_code=normalized_code,
                snapshot_at=snapshot_at,
                fetched_at=self._parse_datetime(row.get("fetched_at")),
                current_price=current_price,
                open=self._parse_optional_float(row.get("open")),
                high=self._parse_optional_float(row.get("high")),
                low=self._parse_optional_float(row.get("low")),
                prev_close=self._parse_optional_float(row.get("prev_close")),
                volume=self._parse_optional_float(row.get("volume")),
                source=source,
                max_age_hours=self._latest_quote_max_age_hours,
                now=self._now_provider(),
            )
        except Exception as exc:
            logger.debug("Realtime quote lookup failed for %s: %s", normalized_code, exc)
            return None
        if quote is None:
            return None
        if quote.must_not_use_for_decision:
            logger.info(
                "Realtime quote rejected by freshness contract: asset_code=%s "
                "observed_at=%s freshness_status=%s",
                normalized_code,
                quote.snapshot_at.isoformat(),
                quote.freshness_status,
            )
            return None
        return quote

    def _get_historical_price(self, normalized_code: str, trade_date: date) -> PriceBar | None:
        try:
            bars = self._dc_price_repo.get_bars(
                normalized_code,
                start=trade_date,
                end=trade_date,
                limit=1,
            )
            return bars[0] if bars else None
        except Exception as exc:
            logger.debug(
                "Historical price lookup failed for %s on %s: %s",
                normalized_code,
                trade_date,
                exc,
            )
            return None

    def _get_recent_close(self, normalized_code: str) -> PriceBar | None:
        try:
            published = get_published_price_bar_series(normalized_code, limit=1)
            if self._publication_blocked(published):
                return None
            rows = published.get("rows")
            if not isinstance(rows, list) or not rows:
                return None
            latest = self._price_bar_from_payload(rows[-1], normalized_code)
            if latest is None:
                return None
            if not latest_daily_market_observation_is_current(
                asset_code=normalized_code,
                observed_at=latest.bar_date,
                now=self._now_provider(),
            ):
                logger.info(
                    "Daily close rejected by freshness contract: asset_code=%s as_of=%s",
                    normalized_code,
                    latest.bar_date.isoformat(),
                )
                return None
            return latest
        except Exception as exc:
            logger.debug("Recent close lookup failed for %s: %s", normalized_code, exc)
            return None

    def _get_fund_nav_price(
        self,
        normalized_code: str,
        trade_date: date | None,
        asset_type: str | None,
    ) -> FundPriceResult | None:
        if not self._should_use_fund_nav(normalized_code, asset_type=asset_type):
            return None

        bare_code = normalized_code.split(".")[0]
        try:
            if trade_date is not None:
                facts = self._dc_fund_nav_repo.get_series(
                    bare_code,
                    start=trade_date,
                    end=trade_date,
                )
                if facts:
                    fact = facts[0]
                    result = self._fund_fact_price(fact)
                    if result is not None:
                        return result
            else:
                published = get_published_fund_nav_series(bare_code, limit=1)
                if self._publication_blocked(published):
                    return None
                rows = published.get("rows")
                if not isinstance(rows, list) or not rows:
                    return None
                result = self._fund_nav_payload_price(rows[-1], bare_code)
                if result is not None:
                    if latest_daily_market_observation_is_current(
                        asset_code=normalized_code,
                        observed_at=result["as_of"],
                        now=self._now_provider(),
                    ):
                        return result
                    logger.info(
                        "Published fund NAV rejected by freshness contract: "
                        "asset_code=%s as_of=%s",
                        normalized_code,
                        result["as_of"].isoformat(),
                    )
                return None
        except Exception as exc:
            logger.debug("Fund NAV repository lookup failed for %s: %s", bare_code, exc)
            if trade_date is None:
                return None

        adapter = self.fund_adapter
        if adapter is None:
            logger.info(
                "Fund NAV is unavailable outside canonical Data Center facts: %s",
                bare_code,
            )
            return None
        try:
            df = adapter.fetch_fund_nav_em(bare_code)
        except Exception as exc:
            logger.debug("Fund adapter lookup failed for %s: %s", bare_code, exc)
            return None
        if df is None or df.empty:
            return None

        nav_date_col = None
        for candidate in ("nav_date", "日期"):
            if candidate in df.columns:
                nav_date_col = candidate
                break
        nav_col = None
        for candidate in ("unit_nav", "净值"):
            if candidate in df.columns:
                nav_col = candidate
                break
        if nav_date_col is None or nav_col is None:
            return None

        working_df = df.copy()
        working_df[nav_date_col] = working_df[nav_date_col].astype(str)
        if trade_date is not None:
            matched = working_df[working_df[nav_date_col] == trade_date.isoformat()]
            if matched.empty:
                return None
            row = matched.iloc[-1]
        else:
            row = working_df.iloc[-1]

        try:
            price = float(row[nav_col])
            nav_date = date.fromisoformat(str(row[nav_date_col]))
        except (TypeError, ValueError) as exc:
            logger.debug("Fund NAV price parse failed for %s: %s", bare_code, exc)
            return None
        if not math.isfinite(price) or price <= 0:
            logger.debug("Fund NAV price is invalid for %s: %r", bare_code, price)
            return None
        if trade_date is None and not latest_daily_market_observation_is_current(
            asset_code=normalized_code,
            observed_at=nav_date,
            now=self._now_provider(),
        ):
            logger.info(
                "External fund NAV rejected by freshness contract: asset_code=%s as_of=%s",
                normalized_code,
                nav_date.isoformat(),
            )
            return None

        return {
            "price": price,
            "as_of": nav_date,
            "source": "akshare_fund",
        }

    @staticmethod
    def _publication_blocked(payload: object) -> bool:
        """Return whether a published port response is not decision-safe."""

        if not isinstance(payload, dict):
            return True
        return bool(payload.get("must_not_use_for_decision"))

    @staticmethod
    def _parse_float(value: object) -> float | None:
        """Parse a finite numeric payload without treating booleans as numbers."""

        if isinstance(value, bool) or value is None:
            return None
        try:
            parsed = float(cast(Any, value))
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    @classmethod
    def _parse_optional_float(cls, value: object) -> float | None:
        """Parse an optional finite numeric field, preserving absent values."""

        if value is None or value == "":
            return None
        return cls._parse_float(value)

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        """Parse an ISO datetime while preserving the source observation instant."""

        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str) and value.strip():
            try:
                parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(UTC)

    @classmethod
    def _price_bar_from_payload(
        cls,
        payload: object,
        normalized_code: str,
    ) -> PriceBar | None:
        """Build a price bar from a member-bound published payload."""

        if not isinstance(payload, dict):
            return None
        payload_code = str(payload.get("asset_code", normalized_code)).strip().upper()
        if payload_code != normalized_code:
            return None
        raw_date = payload.get("bar_date", payload.get("timestamp"))
        if isinstance(raw_date, datetime):
            bar_date = raw_date.date()
        elif isinstance(raw_date, date):
            bar_date = raw_date
        elif isinstance(raw_date, str) and raw_date.strip():
            try:
                bar_date = date.fromisoformat(raw_date.strip()[:10])
            except ValueError:
                return None
        else:
            return None
        close = cls._parse_float(payload.get("close"))
        open_price = cls._parse_float(payload.get("open"))
        high = cls._parse_float(payload.get("high"))
        low = cls._parse_float(payload.get("low"))
        source = payload.get("source")
        if (
            close is None
            or open_price is None
            or high is None
            or low is None
            or not isinstance(source, str)
            or not source.strip()
        ):
            return None
        fetched_at = cls._parse_datetime(payload.get("fetched_at"))
        try:
            kwargs: dict[str, Any] = {
                "asset_code": normalized_code,
                "bar_date": bar_date,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "freq": str(payload.get("period") or payload.get("freq") or "1d"),
                "volume": cls._parse_optional_float(payload.get("volume")),
                "amount": cls._parse_optional_float(payload.get("amount")),
                "source": source.strip(),
            }
            if fetched_at is not None:
                kwargs["fetched_at"] = fetched_at
            return PriceBar(**kwargs)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _fund_nav_payload_price(
        cls,
        payload: object,
        bare_code: str,
    ) -> FundPriceResult | None:
        """Build a fund NAV price from a member-bound published payload."""

        if not isinstance(payload, dict):
            return None
        payload_code = str(payload.get("fund_code", bare_code)).strip().upper()
        if payload_code.split(".")[0] != bare_code.upper():
            return None
        raw_date = payload.get("nav_date")
        if isinstance(raw_date, datetime):
            nav_date = raw_date.date()
        elif isinstance(raw_date, date):
            nav_date = raw_date
        elif isinstance(raw_date, str) and raw_date.strip():
            try:
                nav_date = date.fromisoformat(raw_date.strip()[:10])
            except ValueError:
                return None
        else:
            return None
        nav = cls._parse_float(payload.get("nav"))
        source = payload.get("source")
        if nav is None or nav <= 0 or not isinstance(source, str) or not source.strip():
            return None
        return {"price": nav, "as_of": nav_date, "source": source.strip()}

    @staticmethod
    def _fund_fact_price(fact: FundNavFact) -> FundPriceResult | None:
        """Narrow a stored fund fact before exposing it as an executable price."""

        if (
            isinstance(fact.nav, bool)
            or not math.isfinite(fact.nav)
            or fact.nav <= 0
            or not fact.source.strip()
        ):
            return None
        return {
            "price": fact.nav,
            "as_of": fact.nav_date,
            "source": fact.source.strip(),
        }

    def _should_use_fund_nav(
        self,
        normalized_code: str,
        asset_type: str | None,
    ) -> bool:
        if normalized_code.endswith((".OF", ".OFC")):
            return True
        if normalized_code.endswith((".SH", ".SZ", ".BJ")):
            return False
        return asset_type == "fund"
