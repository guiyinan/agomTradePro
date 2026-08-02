"""
Realtime Module - Infrastructure Layer Repositories

This module provides concrete implementations of the repository protocols.
Following AgomSaaS architecture rules:
- Infrastructure layer can use Django ORM and external libraries
- Implements the Protocol interfaces defined in Domain layer
"""

import logging
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from importlib import import_module
from types import ModuleType
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.asset_analysis.application.query_services import (
    list_active_watchlist_asset_codes,
)
from apps.data_center.application.public import (
    get_akshare_eastmoney_gateway_port,
    get_akshare_module_port,
    get_price_bar_repository_port,
    get_quote_snapshot_repository_port,
)
from apps.data_center.domain.entities import QuoteSnapshot as DataCenterQuoteSnapshot
from apps.realtime.application.simulated_trading_gateway import (
    list_held_asset_codes as _list_held_asset_codes,
)
from apps.realtime.domain.entities import (
    AlertCondition,
    AlertStatus,
    AssetType,
    PriceAlert,
    PriceSubscription,
    RealtimePrice,
    normalize_asset_code,
)
from apps.realtime.domain.protocols import (
    PriceAlertRepositoryProtocol,
    PriceDataProviderProtocol,
    PriceSubscriptionRepositoryProtocol,
    RealtimePriceRepositoryProtocol,
    WatchlistProviderProtocol,
)

logger = logging.getLogger(__name__)
_CHINA_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")


class _EastMoneyQuoteGateway(Protocol):
    """Minimal quote gateway contract consumed by the realtime adapter."""

    def get_quote_snapshots(self, asset_codes: list[str]) -> list[Any]: ...


def _daily_bar_observed_at(bar_date: date) -> datetime:
    """Return the actual China-market close time represented by a daily bar."""

    return datetime.combine(
        bar_date,
        time(hour=15),
        tzinfo=_CHINA_MARKET_TIMEZONE,
    ).astimezone(UTC)


def get_akshare_module() -> ModuleType:
    """Load AkShare through a typed, patchable infrastructure boundary."""

    module = get_akshare_module_port()
    if not isinstance(module, ModuleType):
        raise TypeError("AkShare loader must return a module")
    return module


pd = import_module("pandas")


def _alert_to_domain(model: Any) -> PriceAlert:
    """Map a price-alert ORM record to its domain value."""

    return PriceAlert(
        id=model.id,
        owner_id=model.owner_id,
        asset_code=model.asset_code,
        condition=AlertCondition(model.condition),
        threshold=model.threshold,
        status=AlertStatus(model.status),
        message=model.message,
        triggered_price=model.triggered_price,
        triggered_at=model.triggered_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _subscription_to_domain(model: Any) -> PriceSubscription:
    """Map a subscription ORM record to its domain value."""

    return PriceSubscription(
        id=model.id,
        owner_id=model.owner_id,
        asset_code=model.asset_code,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class DjangoPriceAlertRepository(PriceAlertRepositoryProtocol):
    """Django ORM repository for durable price alerts."""

    def list_for_owner(self, owner_id: int) -> list[PriceAlert]:
        """List alerts belonging to one owner."""

        from apps.realtime.infrastructure.models import PriceAlertModel

        return [
            _alert_to_domain(model) for model in PriceAlertModel.objects.filter(owner_id=owner_id)
        ]

    def get_for_owner(self, owner_id: int, alert_id: int) -> PriceAlert | None:
        """Return an alert only when it belongs to the owner."""

        from apps.realtime.infrastructure.models import PriceAlertModel

        model = PriceAlertModel.objects.filter(id=alert_id, owner_id=owner_id).first()
        return _alert_to_domain(model) if model is not None else None

    def create(self, alert: PriceAlert) -> PriceAlert:
        """Persist a new owner-scoped alert."""

        from apps.realtime.infrastructure.models import PriceAlertModel

        model = PriceAlertModel.objects.create(
            owner_id=alert.owner_id,
            asset_code=alert.asset_code,
            condition=alert.condition.value,
            threshold=alert.threshold,
            status=alert.status.value,
            message=alert.message,
            triggered_price=alert.triggered_price,
            triggered_at=alert.triggered_at,
        )
        return _alert_to_domain(model)

    def update(self, alert: PriceAlert) -> PriceAlert | None:
        """Persist an alert update within its owner scope."""

        from apps.realtime.infrastructure.models import PriceAlertModel

        if alert.id is None:
            return None
        model = PriceAlertModel.objects.filter(
            id=alert.id,
            owner_id=alert.owner_id,
        ).first()
        if model is None:
            return None
        model.asset_code = alert.asset_code
        model.condition = alert.condition.value
        model.threshold = alert.threshold
        model.status = alert.status.value
        model.message = alert.message
        model.triggered_price = alert.triggered_price
        model.triggered_at = alert.triggered_at
        model.save()
        return _alert_to_domain(model)

    def delete(self, owner_id: int, alert_id: int) -> bool:
        """Delete an owner-scoped alert."""

        from apps.realtime.infrastructure.models import PriceAlertModel

        deleted, _ = PriceAlertModel.objects.filter(
            id=alert_id,
            owner_id=owner_id,
        ).delete()
        return deleted > 0

    def list_active_for_assets(self, asset_codes: list[str]) -> list[PriceAlert]:
        """List active alerts for canonical assets."""

        from apps.realtime.infrastructure.models import PriceAlertModel

        canonical = [normalize_asset_code(code) for code in asset_codes]
        return [
            _alert_to_domain(model)
            for model in PriceAlertModel.objects.filter(
                asset_code__in=canonical,
                status=AlertStatus.ACTIVE.value,
            )
        ]

    def claim_trigger(
        self,
        alert_id: int,
        trigger_price: Decimal,
        triggered_at: datetime,
    ) -> PriceAlert | None:
        """Atomically claim one active alert for notification."""

        from apps.realtime.infrastructure.models import PriceAlertModel

        with transaction.atomic():
            model = (
                PriceAlertModel.objects.select_for_update()
                .filter(id=alert_id, status=AlertStatus.ACTIVE.value)
                .first()
            )
            if model is None:
                return None
            model.status = AlertStatus.TRIGGERED.value
            model.triggered_price = trigger_price
            model.triggered_at = triggered_at
            model.save(
                update_fields=[
                    "status",
                    "triggered_price",
                    "triggered_at",
                    "updated_at",
                ]
            )
            return _alert_to_domain(model)


class DjangoPriceSubscriptionRepository(PriceSubscriptionRepositoryProtocol):
    """Django ORM repository for durable realtime subscriptions."""

    def list_for_owner(self, owner_id: int) -> list[PriceSubscription]:
        """List active subscriptions for one owner."""

        from apps.realtime.infrastructure.models import PriceSubscriptionModel

        return [
            _subscription_to_domain(model)
            for model in PriceSubscriptionModel.objects.filter(
                owner_id=owner_id,
                is_active=True,
            )
        ]

    def subscribe(self, owner_id: int, asset_code: str) -> PriceSubscription:
        """Create or reactivate a canonical owner subscription."""

        from apps.realtime.infrastructure.models import PriceSubscriptionModel

        model, _ = PriceSubscriptionModel.objects.update_or_create(
            owner_id=owner_id,
            asset_code=normalize_asset_code(asset_code),
            defaults={"is_active": True},
        )
        return _subscription_to_domain(model)

    def unsubscribe(self, owner_id: int, asset_code: str) -> bool:
        """Deactivate one owner subscription."""

        from apps.realtime.infrastructure.models import PriceSubscriptionModel

        updated = PriceSubscriptionModel.objects.filter(
            owner_id=owner_id,
            asset_code=normalize_asset_code(asset_code),
            is_active=True,
        ).update(is_active=False, updated_at=timezone.now())
        return updated > 0

    def count_active(self, owner_id: int) -> int:
        """Count active subscriptions for one owner."""

        from apps.realtime.infrastructure.models import PriceSubscriptionModel

        return PriceSubscriptionModel.objects.filter(
            owner_id=owner_id,
            is_active=True,
        ).count()

    def list_active_asset_codes(self) -> list[str]:
        """List distinct active assets across all owners."""

        from apps.realtime.infrastructure.models import PriceSubscriptionModel

        return list(
            PriceSubscriptionModel.objects.filter(is_active=True)
            .values_list("asset_code", flat=True)
            .distinct()
            .order_by("asset_code")
        )


def list_held_simulated_asset_codes() -> list[str]:
    """Return distinct asset codes held in simulated-trading positions."""

    return _list_held_asset_codes()


class RedisRealtimePriceRepository(RealtimePriceRepositoryProtocol):
    """基于 Redis 的实时价格仓储

    使用 Django cache 后端（配置为 Redis）存储实时价格
    缓存键格式: realtime:price:{asset_code}
    缓存过期时间: 5 分钟
    """

    CACHE_KEY_PREFIX = "realtime:price"
    CACHE_TIMEOUT = 300  # 5分钟过期

    def save_price(self, price: RealtimePrice) -> None:
        """保存单个实时价格到 Redis"""
        cache_key = f"{self.CACHE_KEY_PREFIX}:{price.asset_code}"
        cache.set(cache_key, price.to_dict(), timeout=self.CACHE_TIMEOUT)
        logger.debug(f"Saved price for {price.asset_code}: {price.price}")

    def save_prices_batch(self, prices: list[RealtimePrice]) -> None:
        """批量保存实时价格到 Redis"""
        cache_data = {f"{self.CACHE_KEY_PREFIX}:{p.asset_code}": p.to_dict() for p in prices}
        # 使用 cache.set_many 批量设置
        cache.set_many(cache_data, timeout=self.CACHE_TIMEOUT)
        logger.info(f"Batch saved {len(prices)} prices to Redis")

    def get_latest_price(self, asset_code: str) -> RealtimePrice | None:
        """从 Redis 获取资产的最新价格"""
        cache_key = f"{self.CACHE_KEY_PREFIX}:{asset_code}"
        data = cache.get(cache_key)

        if data is None:
            return None

        try:
            return self._dict_to_price(data)
        except Exception as e:
            logger.error(f"Failed to deserialize price for {asset_code}: {e}")
            return None

    def get_latest_prices(self, asset_codes: list[str]) -> list[RealtimePrice]:
        """批量获取多个资产的最新价格"""
        cache_keys = [f"{self.CACHE_KEY_PREFIX}:{code}" for code in asset_codes]
        cache_data_dict = cache.get_many(cache_keys)

        result = []
        for code in asset_codes:
            cache_key = f"{self.CACHE_KEY_PREFIX}:{code}"
            data = cache_data_dict.get(cache_key)
            if data:
                try:
                    result.append(self._dict_to_price(data))
                except Exception as e:
                    logger.error(f"Failed to deserialize price for {code}: {e}")

        return result

    def _dict_to_price(self, data: dict[str, Any]) -> RealtimePrice:
        """将字典转换为 RealtimePrice 对象"""
        return RealtimePrice(
            asset_code=data["asset_code"],
            asset_type=AssetType(data["asset_type"]),
            price=Decimal(str(data["price"])),
            change=(Decimal(str(data["change"])) if data.get("change") is not None else None),
            change_pct=(
                Decimal(str(data["change_pct"])) if data.get("change_pct") is not None else None
            ),
            volume=data.get("volume"),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            source=data["source"],
            fetched_at=(
                datetime.fromisoformat(data["fetched_at"]) if data.get("fetched_at") else None
            ),
        )


class TusharePriceDataProvider(PriceDataProviderProtocol):
    """Tushare 价格数据提供者

    从 Tushare Pro API 获取实时行情数据
    使用现有的 TushareAdapter 适配器
    """

    def __init__(self) -> None:
        self._quote_repo = get_quote_snapshot_repository_port()
        self._price_repo = get_price_bar_repository_port()
        self._is_available = True

    def get_realtime_price(self, asset_code: str) -> RealtimePrice | None:
        """获取单个资产的实时价格

        注意：Tushare免费版只能获取历史数据，"实时"实际上是最新交易日数据
        """
        try:
            quote = self._quote_repo.get_latest(asset_code)
            if quote is not None:
                return RealtimePrice(
                    asset_code=asset_code,
                    asset_type=self._get_asset_type(asset_code),
                    price=Decimal(str(quote.current_price)),
                    change=None,
                    change_pct=None,
                    volume=int(quote.volume) if quote.volume is not None else None,
                    timestamp=quote.snapshot_at,
                    source=quote.source or "data_center",
                    fetched_at=quote.fetched_at,
                )

            latest_bar = self._price_repo.get_latest(asset_code)
            if latest_bar is None:
                logger.warning(f"No price data found for {asset_code}")
                return None

            return RealtimePrice(
                asset_code=asset_code,
                asset_type=self._get_asset_type(asset_code),
                price=Decimal(str(latest_bar.close)),
                change=None,
                change_pct=None,
                volume=int(latest_bar.volume) if latest_bar.volume is not None else None,
                timestamp=_daily_bar_observed_at(latest_bar.bar_date),
                source=latest_bar.source or "data_center",
            )

        except Exception as e:
            logger.error(f"Failed to get realtime price for {asset_code}: {e}")
            return None

    def get_realtime_prices_batch(self, asset_codes: list[str]) -> list[RealtimePrice]:
        """批量获取多个资产的实时价格"""
        prices = []

        for code in asset_codes:
            price = self.get_realtime_price(code)
            if price:
                prices.append(price)

        logger.info(f"Retrieved {len(prices)}/{len(asset_codes)} prices from Tushare")
        return prices

    def is_available(self) -> bool:
        """检查 Tushare 数据源是否可用"""
        if not self._is_available:
            return False

        try:
            # 尝试获取一个测试数据
            test_price = self.get_realtime_price("000001.SZ")
            return test_price is not None
        except Exception as e:
            logger.error(f"Tushare data source unavailable: {e}")
            self._is_available = False
            return False

    def _convert_to_tushare_code(self, asset_code: str) -> str:
        """转换资产代码为 Tushare 格式

        例如: 600000.SH -> 600000.SH (已符合格式)
        """
        # 假设输入已经是 Tushare 格式
        return asset_code

    def _get_asset_type(self, asset_code: str) -> AssetType:
        """根据资产代码判断资产类型"""
        if "." in asset_code:
            suffix = asset_code.split(".")[1]
            if suffix in ["SH", "SZ", "BJ"]:
                return AssetType.EQUITY
        elif asset_code.startswith("000"):
            return AssetType.INDEX
        return AssetType.UNKNOWN


class AKSharePriceDataProvider(PriceDataProviderProtocol):
    """AKShare 价格数据提供者

    从 AKShare 获取实时行情数据
    完全免费，无需 Token
    """

    def __init__(self) -> None:
        self._quote_repo = get_quote_snapshot_repository_port()
        self._price_repo = get_price_bar_repository_port()
        self._is_available = True
        self._ak: ModuleType | None = None
        self._eastmoney_gateway: _EastMoneyQuoteGateway | None = None

    def _get_ak(self) -> ModuleType:
        if self._ak is None:
            self._ak = get_akshare_module()
        return self._ak

    def _get_eastmoney_gateway(self) -> _EastMoneyQuoteGateway:
        if self._eastmoney_gateway is None:
            self._eastmoney_gateway = cast(
                _EastMoneyQuoteGateway,
                get_akshare_eastmoney_gateway_port(),
            )
        return self._eastmoney_gateway

    @staticmethod
    def _pick_value(row: Any, candidates: list[str]) -> object | None:
        for candidate in candidates:
            if candidate in row and pd.notna(row[candidate]):
                return cast(object, row[candidate])
        return None

    def _build_price_from_spot_row(
        self,
        asset_code: str,
        row: Any,
    ) -> RealtimePrice | None:
        latest_price = self._pick_value(row, ["最新价", "最新", "现价"])
        observed_at = self._extract_spot_observed_at(row)
        if latest_price is None or observed_at is None:
            return None

        change = self._pick_value(row, ["涨跌额", "涨跌"])
        change_pct = self._pick_value(row, ["涨跌幅"])
        volume = self._pick_value(row, ["成交量", "总手"])

        return RealtimePrice(
            asset_code=asset_code,
            asset_type=self._get_asset_type(asset_code),
            price=Decimal(str(latest_price)),
            change=Decimal(str(change)) if change is not None else None,
            change_pct=Decimal(str(change_pct)) if change_pct is not None else None,
            volume=int(float(str(volume))) if volume is not None else None,
            timestamp=observed_at,
            source="akshare",
            fetched_at=timezone.now(),
        )

    def _build_quote_snapshot_from_spot_row(
        self,
        asset_code: str,
        row: Any,
    ) -> DataCenterQuoteSnapshot | None:
        latest_price = self._pick_value(row, ["最新价", "最新", "现价"])
        observed_at = self._extract_spot_observed_at(row)
        if latest_price is None or observed_at is None:
            return None

        volume = self._pick_value(row, ["成交量", "总手"])
        amount = self._pick_value(row, ["成交额"])
        fetched_at = timezone.now()
        return DataCenterQuoteSnapshot(
            asset_code=asset_code,
            snapshot_at=observed_at,
            fetched_at=fetched_at,
            current_price=float(str(latest_price)),
            source="akshare",
            open=self._pick_float(row, ["今开", "开盘"]),
            high=self._pick_float(row, ["最高"]),
            low=self._pick_float(row, ["最低"]),
            prev_close=self._pick_float(row, ["昨收", "昨结"]),
            volume=float(str(volume)) if volume is not None else None,
            amount=float(str(amount)) if amount is not None else None,
        )

    @staticmethod
    def _extract_spot_observed_at(row: Any) -> datetime | None:
        """Read an explicit source observation time from an AKShare row."""

        raw_value = AKSharePriceDataProvider._pick_value(
            row,
            ["更新时间", "数据时间", "日期时间", "timestamp"],
        )
        if raw_value is None:
            return None
        try:
            observed_at = pd.Timestamp(raw_value).to_pydatetime()
        except (TypeError, ValueError, OverflowError):
            return None
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=_CHINA_MARKET_TIMEZONE)
        return cast(datetime, observed_at.astimezone(UTC))

    def _build_price_from_quote_snapshot(
        self,
        asset_code: str,
        snapshot: Any,
    ) -> RealtimePrice | None:
        price = getattr(snapshot, "price", None)
        if price is None:
            return None

        volume = getattr(snapshot, "volume", None)
        observed_at = getattr(snapshot, "observed_at", None)
        if not isinstance(observed_at, datetime) or observed_at.utcoffset() is None:
            logger.warning(
                "Dropping quote without source observation time: asset=%s source=%s",
                asset_code,
                getattr(snapshot, "source", ""),
            )
            return None
        return RealtimePrice(
            asset_code=asset_code,
            asset_type=self._get_asset_type(asset_code),
            price=Decimal(str(price)),
            change=(
                Decimal(str(snapshot.change))
                if getattr(snapshot, "change", None) is not None
                else None
            ),
            change_pct=(
                Decimal(str(snapshot.change_pct))
                if getattr(snapshot, "change_pct", None) is not None
                else None
            ),
            volume=int(volume) if volume is not None else None,
            timestamp=observed_at,
            source=getattr(snapshot, "source", None) or "eastmoney",
            fetched_at=getattr(snapshot, "fetched_at", None),
        )

    @staticmethod
    def _pick_float(row: Any, candidates: list[str]) -> float | None:
        value = AKSharePriceDataProvider._pick_value(row, candidates)
        if value in (None, ""):
            return None
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None

    def _build_market_quote_snapshot(
        self,
        asset_code: str,
        snapshot: Any,
    ) -> DataCenterQuoteSnapshot | None:
        price = getattr(snapshot, "price", None)
        if price is None:
            return None

        observed_at = getattr(snapshot, "observed_at", None)
        fetched_at = getattr(snapshot, "fetched_at", None)
        if not isinstance(observed_at, datetime) or observed_at.utcoffset() is None:
            return None
        if not isinstance(fetched_at, datetime) or fetched_at.utcoffset() is None:
            return None
        return DataCenterQuoteSnapshot(
            asset_code=asset_code,
            snapshot_at=observed_at,
            fetched_at=fetched_at,
            current_price=float(str(price)),
            source=snapshot.source or "eastmoney",
            open=float(snapshot.open) if snapshot.open is not None else None,
            high=float(snapshot.high) if snapshot.high is not None else None,
            low=float(snapshot.low) if snapshot.low is not None else None,
            prev_close=(float(snapshot.pre_close) if snapshot.pre_close is not None else None),
            volume=(float(snapshot.volume) if snapshot.volume is not None else None),
            amount=(float(snapshot.amount) if snapshot.amount is not None else None),
            bid=None,
            ask=None,
        )

    def _persist_quote_snapshots(
        self,
        quotes: list[DataCenterQuoteSnapshot],
    ) -> None:
        if not quotes:
            return
        try:
            self._quote_repo.bulk_upsert(quotes)
        except Exception as exc:
            logger.warning("Persisting remote quote snapshots failed: %s", exc)

    def _load_direct_quotes(
        self,
        asset_codes: list[str],
    ) -> dict[str, RealtimePrice]:
        if not asset_codes:
            return {}

        try:
            snapshots = self._get_eastmoney_gateway().get_quote_snapshots(asset_codes)
        except Exception as exc:
            logger.warning("EastMoney direct quote fallback failed: %s", exc)
            return {}

        results: dict[str, RealtimePrice] = {}
        for snapshot in snapshots:
            stock_code = getattr(snapshot, "stock_code", None)
            if not stock_code:
                continue
            price = self._build_price_from_quote_snapshot(stock_code, snapshot)
            if price is not None:
                results[stock_code] = price
        return results

    def _find_spot_row(self, frame: Any, asset_code: str) -> Any | None:
        if frame is None or frame.empty:
            return None

        code_col = None
        for candidate in ["代码", "基金代码", "证券代码"]:
            if candidate in frame.columns:
                code_col = candidate
                break
        if code_col is None:
            return None

        raw_code = self._convert_to_akshare_code(asset_code)
        matches = frame.loc[frame[code_col].astype(str) == raw_code]
        if matches.empty:
            return None
        return matches.iloc[0]

    def _load_spot_frame(self, loader_name: str) -> Any:
        loader = getattr(self._get_ak(), loader_name, None)
        if loader is None:
            return pd.DataFrame()
        try:
            frame = loader()
            return frame if frame is not None else pd.DataFrame()
        except Exception as exc:
            logger.warning("AKShare spot loader %s failed: %s", loader_name, exc)
            return pd.DataFrame()

    def _get_cached_or_historical_price(
        self,
        asset_code: str,
    ) -> RealtimePrice | None:
        """读取已持久化的最新报价或价格条，避免重复触发远端抓取。"""
        quote = self._quote_repo.get_latest(asset_code)
        if quote is not None:
            return RealtimePrice(
                asset_code=asset_code,
                asset_type=self._get_asset_type(asset_code),
                price=Decimal(str(quote.current_price)),
                change=None,
                change_pct=None,
                volume=int(quote.volume) if quote.volume is not None else None,
                timestamp=quote.snapshot_at,
                source=quote.source or "data_center",
                fetched_at=quote.fetched_at,
            )

        latest_bar = self._price_repo.get_latest(asset_code)
        if latest_bar is None:
            return None

        return RealtimePrice(
            asset_code=asset_code,
            asset_type=self._get_asset_type(asset_code),
            price=Decimal(str(latest_bar.close)),
            change=None,
            change_pct=None,
            volume=int(latest_bar.volume) if latest_bar.volume is not None else None,
            timestamp=_daily_bar_observed_at(latest_bar.bar_date),
            source=latest_bar.source or "data_center",
        )

    def get_realtime_price(self, asset_code: str) -> RealtimePrice | None:
        """获取单个资产的实时价格

        AKShare 提供实时行情数据，无需 Token
        """
        try:
            cached_price = self._get_cached_or_historical_price(asset_code)
            if cached_price is not None:
                return cached_price

            fund_row = self._find_spot_row(
                self._load_spot_frame("fund_etf_spot_em"),
                asset_code,
            )
            if fund_row is not None:
                return self._build_price_from_spot_row(asset_code, fund_row)

            stock_row = self._find_spot_row(
                self._load_spot_frame("stock_zh_a_spot_em"),
                asset_code,
            )
            if stock_row is not None:
                return self._build_price_from_spot_row(asset_code, stock_row)

            direct_price = self._load_direct_quotes([asset_code]).get(asset_code)
            if direct_price is not None:
                return direct_price

            logger.warning(f"No price data found for {asset_code}")
            return None

        except Exception as e:
            logger.error(f"Failed to get realtime price for {asset_code} from AKShare: {e}")
            return None

    def get_realtime_prices_batch(self, asset_codes: list[str]) -> list[RealtimePrice]:
        """批量获取多个资产的实时价格

        AKShare 可以一次性获取所有股票的实时行情
        """
        fund_frame = self._load_spot_frame("fund_etf_spot_em")
        stock_frame = self._load_spot_frame("stock_zh_a_spot_em")
        direct_quotes: dict[str, RealtimePrice] = {}
        prices: list[RealtimePrice] = []
        missing_codes: list[str] = []
        for code in asset_codes:
            price = None
            fund_row = self._find_spot_row(fund_frame, code)
            if fund_row is not None:
                price = self._build_price_from_spot_row(code, fund_row)
            else:
                stock_row = self._find_spot_row(stock_frame, code)
                if stock_row is not None:
                    price = self._build_price_from_spot_row(code, stock_row)
            if price is None:
                missing_codes.append(code)
                continue
            if price is not None:
                prices.append(price)

        if missing_codes:
            direct_quotes = self._load_direct_quotes(missing_codes)

        still_missing: list[str] = []
        for code in missing_codes:
            price = direct_quotes.get(code)
            if price is None:
                price = self._get_cached_or_historical_price(code)
            if price is not None:
                prices.append(price)
            else:
                still_missing.append(code)

        if still_missing:
            logger.warning(
                "AKShare batch fallback exhausted with %d missing codes: %s",
                len(still_missing),
                ", ".join(still_missing[:10]),
            )
        logger.info(f"Retrieved {len(prices)}/{len(asset_codes)} prices from AKShare")
        return prices

    def is_available(self) -> bool:
        """检查 AKShare 数据源是否可用"""
        return self._is_available

    def _convert_to_akshare_code(self, asset_code: str) -> str:
        """转换资产代码为 AKShare 格式

        Tushare格式: 000001.SZ → AKShare格式: 000001
        Tushare格式: 600000.SH → AKShare格式: 600000
        """
        if "." in asset_code:
            code, _ = asset_code.split(".")
            return code
        return asset_code

    def _get_asset_type(self, asset_code: str) -> AssetType:
        """根据资产代码判断资产类型"""
        raw_code = self._convert_to_akshare_code(asset_code)
        if raw_code.startswith(("5", "15", "16", "18")):
            return AssetType.FUND
        if "." in asset_code:
            suffix = asset_code.split(".")[1]
            if suffix in ["SH", "SZ", "BJ"]:
                return AssetType.EQUITY
        elif asset_code.startswith("000"):
            return AssetType.INDEX
        return AssetType.UNKNOWN


class DatabaseWatchlistProvider(WatchlistProviderProtocol):
    """基于数据库的关注池提供者

    从数据库中获取持仓资产和关注池资产
    """

    def get_held_assets(self) -> list[str]:
        """获取所有持仓资产代码"""
        return list_held_simulated_asset_codes()

    def get_watchlist_assets(self, user_id: str | None = None) -> list[str]:
        """获取关注池资产代码

        从 asset_analysis 模块的 AssetPoolEntry 中查询
        pool_type='watch' 且 is_active=True 的资产。
        """
        try:
            result = list_active_watchlist_asset_codes()
            if result:
                logger.info("Loaded %d watchlist assets from asset pool", len(result))
            return [str(asset_code) for asset_code in result]

        except Exception as e:
            logger.warning("Failed to load watchlist assets: %s", e)
            return []

    def get_all_monitored_assets(self) -> list[str]:
        """获取所有需要监控的资产（持仓 + 关注池）"""
        held = set(self.get_held_assets())
        watchlist = set(self.get_watchlist_assets())

        # 去重并返回
        return list(held | watchlist)


class DataCenterPriceDataProvider(PriceDataProviderProtocol):
    """Price provider backed by data_center quote/price facts."""

    def __init__(self) -> None:
        self._quote_repo = get_quote_snapshot_repository_port()
        self._bar_repo = get_price_bar_repository_port()

    def get_realtime_price(self, asset_code: str) -> RealtimePrice | None:
        try:
            quote = self._quote_repo.get_latest(asset_code)
            if quote is not None:
                return RealtimePrice(
                    asset_code=asset_code,
                    asset_type=self._get_asset_type(asset_code),
                    price=Decimal(str(quote.current_price)),
                    change=None,
                    change_pct=None,
                    volume=int(quote.volume) if quote.volume is not None else None,
                    timestamp=quote.snapshot_at,
                    source=quote.source,
                    fetched_at=quote.fetched_at,
                )

            bar = self._bar_repo.get_latest(asset_code)
            if bar is None:
                return None
            return RealtimePrice(
                asset_code=asset_code,
                asset_type=self._get_asset_type(asset_code),
                price=Decimal(str(bar.close)),
                change=None,
                change_pct=None,
                volume=int(bar.volume) if bar.volume is not None else None,
                timestamp=_daily_bar_observed_at(bar.bar_date),
                source=bar.source,
            )
        except Exception:
            logger.warning(
                "Failed to read realtime price from data_center: %s",
                asset_code,
                exc_info=True,
            )
            return None

    def get_realtime_prices_batch(self, asset_codes: list[str]) -> list[RealtimePrice]:
        prices: list[RealtimePrice] = []
        for code in asset_codes:
            price = self.get_realtime_price(code)
            if price is not None:
                prices.append(price)
        return prices

    def is_available(self) -> bool:
        return True

    def _get_asset_type(self, asset_code: str) -> AssetType:
        if asset_code.endswith(".OF") or asset_code.endswith(".OFC"):
            return AssetType.FUND
        if asset_code.startswith(("000", "399")) and "." not in asset_code:
            return AssetType.INDEX
        if "." in asset_code:
            suffix = asset_code.split(".")[1]
            if suffix in ["SH", "SZ", "BJ"]:
                return AssetType.EQUITY
        return AssetType.UNKNOWN


class CompositePriceDataProvider(PriceDataProviderProtocol):
    """组合价格数据提供者

    支持多个数据源，自动故障转移
    """

    def __init__(
        self,
        providers: list[PriceDataProviderProtocol],
        *,
        max_price_age_seconds: int = 300,
    ) -> None:
        if max_price_age_seconds <= 0:
            raise ValueError("max_price_age_seconds must be positive")
        self.providers = providers
        self.max_price_age = timedelta(seconds=max_price_age_seconds)

    def _is_fresh(self, price: RealtimePrice) -> bool:
        """Reject stale provider results so failover can continue."""

        return price.is_fresh(
            reference_time=timezone.now(),
            max_age=self.max_price_age,
        )

    def get_realtime_price(self, asset_code: str) -> RealtimePrice | None:
        """依次尝试从各个数据源获取价格"""
        last_error = None

        for provider in self.providers:
            try:
                price = provider.get_realtime_price(asset_code)
                if price and self._is_fresh(price):
                    return price
                if price:
                    logger.warning(
                        "Ignoring stale realtime price from %s for %s observed_at=%s",
                        provider.__class__.__name__,
                        asset_code,
                        price.timestamp.isoformat(),
                    )
            except Exception as e:
                last_error = e
                logger.warning(f"Provider {provider.__class__.__name__} failed: {e}")

        logger.error(f"All providers failed for {asset_code}, last error: {last_error}")
        return None

    def get_realtime_prices_batch(self, asset_codes: list[str]) -> list[RealtimePrice]:
        """批量获取价格，按 provider 顺序逐层补齐缺失资产。"""
        prices_by_code: dict[str, RealtimePrice] = {}
        missing_codes = list(dict.fromkeys(asset_codes))

        for provider in self.providers:
            if not missing_codes:
                break
            try:
                prices = provider.get_realtime_prices_batch(missing_codes)
            except Exception as e:
                logger.warning(f"Provider {provider.__class__.__name__} batch failed: {e}")
                continue

            if not prices:
                continue

            for price in prices:
                if self._is_fresh(price):
                    prices_by_code[price.asset_code] = price
                else:
                    logger.warning(
                        "Ignoring stale realtime price from %s for %s observed_at=%s",
                        provider.__class__.__name__,
                        price.asset_code,
                        price.timestamp.isoformat(),
                    )

            missing_codes = [
                asset_code for asset_code in missing_codes if asset_code not in prices_by_code
            ]

        return [
            prices_by_code[asset_code] for asset_code in asset_codes if asset_code in prices_by_code
        ]

    def is_available(self) -> bool:
        """检查是否有可用的数据源"""
        return any(provider.is_available() for provider in self.providers)
