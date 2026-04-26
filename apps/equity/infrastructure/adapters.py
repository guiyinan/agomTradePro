"""
个股分析模块 Infrastructure 层适配器。

历史上这里直接连 Tushare；现在保留适配器类名，但读取统一改走
data_center 或本地持久化事实表，避免模块继续直连外部 SDK。
"""

import logging
from datetime import date, datetime
from typing import Dict, List, Optional, Union

import pandas as pd

from apps.data_center.domain.entities import PriceBar as DataCenterPriceBar
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.infrastructure.repositories import PriceBarRepository
from core.integration.runtime_benchmarks import get_runtime_benchmark_code

from ..domain.ports import MarketDataPort, RegimeDataPort, StockPoolPort
from .models import StockDailyModel, StockInfoModel

logger = logging.getLogger(__name__)


class TushareStockAdapter:
    """兼容旧调用方的股票日线适配器。"""

    def __init__(self):
        self._dc_price_repo = PriceBarRepository()

    def fetch_stock_list(self) -> pd.DataFrame:
        """获取 A 股基础信息。"""
        rows = list(
            StockInfoModel._default_manager.filter(is_active=True).values(
                "stock_code", "name", "sector", "market", "list_date"
            )
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        if "list_date" in df.columns:
            df["list_date"] = pd.to_datetime(df["list_date"], errors="coerce")
        df["symbol"] = df["stock_code"].astype(str).str.split(".").str[0]
        df["area"] = ""
        df["industry"] = df["sector"].fillna("")
        return df

    def fetch_daily_data(
        self,
        stock_code: str,
        start_date: str | date | datetime,
        end_date: str | date | datetime,
    ) -> pd.DataFrame:
        """获取股票日线行情。"""
        normalized_code = self._normalize_stock_code(stock_code)
        start_dt = pd.to_datetime(self._normalize_date(start_date), format="%Y%m%d").date()
        end_dt = pd.to_datetime(self._normalize_date(end_date), format="%Y%m%d").date()

        bars = list(
            reversed(self._dc_price_repo.get_bars(normalized_code, start=start_dt, end=end_dt, limit=5000))
        )
        if bars:
            df = pd.DataFrame(
                [
                    {
                        "ts_code": bar.asset_code,
                        "trade_date": pd.Timestamp(bar.bar_date),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "vol": bar.volume,
                        "amount": bar.amount,
                    }
                    for bar in bars
                ]
            )
        else:
            models = list(
                StockDailyModel._default_manager.filter(
                    stock_code=normalized_code,
                    trade_date__gte=start_dt,
                    trade_date__lte=end_dt,
                ).order_by("trade_date")
            )
            if not models:
                return pd.DataFrame()
            df = pd.DataFrame(
                [
                    {
                        "ts_code": model.stock_code,
                        "trade_date": pd.Timestamp(model.trade_date),
                        "open": model.open,
                        "high": model.high,
                        "low": model.low,
                        "close": model.close,
                        "vol": model.volume,
                        "amount": model.amount,
                    }
                    for model in models
                ]
            )

        df["pre_close"] = df["close"].shift(1)
        df["change"] = df["close"] - df["pre_close"]
        df["pct_chg"] = (df["change"] / df["pre_close"] * 100).fillna(0.0)
        return df.reset_index(drop=True)

    def fetch_stock_info(self, stock_code: str) -> dict:
        """获取单只股票基础信息。"""
        normalized_code = self._normalize_stock_code(stock_code)
        symbol = normalized_code.split(".")[0]
        row = (
            StockInfoModel._default_manager.filter(stock_code=normalized_code)
            .values("stock_code", "name", "sector", "market", "list_date")
            .first()
        )
        if row is None and symbol != normalized_code:
            row = (
                StockInfoModel._default_manager.filter(stock_code__startswith=symbol)
                .values("stock_code", "name", "sector", "market", "list_date")
                .first()
            )
        if row is None:
            return {}
        return {
            "ts_code": row["stock_code"],
            "symbol": symbol,
            "name": row["name"],
            "area": "",
            "industry": row.get("sector", ""),
            "market": row.get("market", ""),
            "list_date": pd.to_datetime(row.get("list_date"), errors="coerce"),
        }

    def _normalize_stock_code(self, stock_code: str) -> str:
        code = stock_code.strip().upper()
        if "." in code:
            return code
        if code.startswith("6"):
            return f"{code}.SH"
        if code.startswith(("0", "3")):
            return f"{code}.SZ"
        if code.startswith(("4", "8")):
            return f"{code}.BJ"
        return code

    def _normalize_date(self, value: str | date | datetime) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y%m%d")
        if isinstance(value, date):
            return value.strftime("%Y%m%d")
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            raise ValueError(f"无效日期格式: {value}")
        return parsed.strftime("%Y%m%d")


class RegimeRepositoryAdapter(RegimeDataPort):
    """
    Regime 数据仓储适配器

    适配 regime 模块的 DjangoRegimeRepository，实现 Domain 层定义的协议。
    """

    def __init__(self):
        # 延迟导入，避免循环依赖
        from apps.regime.infrastructure.repositories import DjangoRegimeRepository
        self._regime_repo = DjangoRegimeRepository()

    def get_snapshots_in_range(
        self,
        start_date: date,
        end_date: date
    ) -> list:
        """
        获取日期范围内的 Regime 快照列表

        Args:
            start_date: 起始日期（包含）
            end_date: 结束日期（包含）

        Returns:
            List[RegimeSnapshot]: 快照列表，按时间升序排列
        """
        return self._regime_repo.get_snapshots_in_range(start_date, end_date)

    def get_snapshot_by_date(
        self,
        observed_at: date
    ) -> Optional:
        """
        按日期获取 Regime 快照

        Args:
            observed_at: 观测日期

        Returns:
            Optional[RegimeSnapshot]: 快照实体，不存在则返回 None
        """
        return self._regime_repo.get_snapshot_by_date(observed_at)


class MarketDataRepositoryAdapter(MarketDataPort):
    """
    市场数据仓储适配器

    从 macro 模块获取指数数据，计算收益率。
    """

    def __init__(self):
        from apps.macro.infrastructure.models import MacroIndicator
        self._model = MacroIndicator
        self._bar_repo = PriceBarRepository()
        self._default_index_code = get_runtime_benchmark_code("equity_default_index")

    def _load_local_index_points(
        self,
        index_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, float]]:
        bars = list(reversed(self._bar_repo.get_bars(index_code, start=start_date, end=end_date, limit=5000)))
        if bars:
            return [
                (bar.bar_date, float(bar.close))
                for bar in bars
                if bar.close and bar.close > 0
            ]

        queryset = self._model.objects.filter(
            code=index_code,
            reporting_period__gte=start_date,
            reporting_period__lte=end_date,
        ).order_by("reporting_period")
        return [
            (item.reporting_period, float(item.value))
            for item in queryset
            if item.value and item.value > 0
        ]

    @staticmethod
    def _to_akshare_symbol(index_code: str) -> str | None:
        normalized = index_code.upper()
        if normalized.endswith(".SH"):
            return f"sh{normalized[:-3].lower()}"
        if normalized.endswith(".SZ"):
            return f"sz{normalized[:-3].lower()}"
        return None

    @staticmethod
    def _to_raw_index_code(index_code: str) -> str:
        return index_code.split(".")[0]

    @staticmethod
    def _extract_index_points(df: pd.DataFrame) -> list[tuple[date, float]]:
        if df is None or df.empty:
            return []

        date_column = None
        close_column = None

        for candidate in ("date", "日期", "trade_date", "datetime"):
            if candidate in df.columns:
                date_column = candidate
                break

        for candidate in ("close", "收盘", "收盘价", "Close"):
            if candidate in df.columns:
                close_column = candidate
                break

        if date_column is None or close_column is None:
            return []

        frame = df.copy()
        frame["trade_date"] = pd.to_datetime(frame[date_column], errors="coerce").dt.date
        frame["close_price"] = pd.to_numeric(frame[close_column], errors="coerce")
        frame = frame.dropna(subset=["trade_date", "close_price"])
        frame = frame[frame["close_price"] > 0]
        frame = frame.sort_values("trade_date").drop_duplicates(subset=["trade_date"], keep="last")
        return list(zip(frame["trade_date"], frame["close_price"].astype(float)))

    def _persist_index_points(
        self,
        index_code: str,
        data_points: list[tuple[date, float]],
        source: str,
    ) -> None:
        if not data_points:
            return

        bars = [
            DataCenterPriceBar(
                asset_code=index_code,
                bar_date=trade_date,
                open=close_price,
                high=close_price,
                low=close_price,
                close=close_price,
                freq="1d",
                adjustment=PriceAdjustment.NONE,
                source=source,
            )
            for trade_date, close_price in data_points
        ]
        self._bar_repo.bulk_upsert(bars)

        for trade_date, close_price in data_points:
            self._model.objects.update_or_create(
                code=index_code,
                reporting_period=trade_date,
                revision_number=1,
                defaults={
                    "value": close_price,
                    "unit": "点",
                    "original_unit": "点",
                    "period_type": "D",
                    "published_at": trade_date,
                    "publication_lag_days": 0,
                    "source": source,
                },
            )

    def _load_remote_index_points(
        self,
        index_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, float]]:
        from apps.data_center.infrastructure.legacy_sdk_bridge import get_akshare_module

        symbol = self._to_akshare_symbol(index_code)
        raw_code = self._to_raw_index_code(index_code)
        ak = get_akshare_module()

        fetch_attempts: list[tuple[str, callable]] = []
        if symbol is not None:
            fetch_attempts.extend(
                [
                    (
                        "akshare:stock_zh_index_daily_em",
                        lambda: ak.stock_zh_index_daily_em(
                            symbol=symbol,
                            start_date=start_date.strftime("%Y%m%d"),
                            end_date=end_date.strftime("%Y%m%d"),
                        ),
                    ),
                    (
                        "akshare:stock_zh_index_daily",
                        lambda: ak.stock_zh_index_daily(symbol=symbol),
                    ),
                    (
                        "akshare:stock_zh_index_daily_tx",
                        lambda: ak.stock_zh_index_daily_tx(symbol=symbol),
                    ),
                ]
            )

        fetch_attempts.append(
            (
                "akshare:index_zh_a_hist",
                lambda: ak.index_zh_a_hist(
                    symbol=raw_code,
                    period="daily",
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                ),
            )
        )

        for source_name, loader in fetch_attempts:
            try:
                points = self._extract_index_points(loader())
            except Exception as exc:
                logger.warning("获取指数 %s 历史行情失败(%s): %s", index_code, source_name, exc)
                continue

            filtered = [
                (trade_date, close_price)
                for trade_date, close_price in points
                if start_date <= trade_date <= end_date
            ]
            if not filtered:
                continue

            self._persist_index_points(index_code, filtered, source_name)
            return filtered

        return []

    def get_index_daily_returns(
        self,
        index_code: str,
        start_date: date,
        end_date: date
    ) -> dict[date, float]:
        """
        获取指数日收益率

        从 MacroIndicator 表获取指数日线价格数据，计算收益率。

        Args:
            index_code: 指数代码（如 000300.SH 表示沪深 300）
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            {日期: 收益率}，收益率以小数表示（如 0.01 表示 1%）
        """
        try:
            data_points = self._load_local_index_points(index_code, start_date, end_date)
            if len(data_points) < 2:
                data_points = self._load_remote_index_points(index_code, start_date, end_date)

            # 计算收益率
            returns = {}
            for i in range(1, len(data_points)):
                prev_date, prev_price = data_points[i - 1]
                curr_date, curr_price = data_points[i]

                if prev_price > 0:
                    daily_return = (curr_price - prev_price) / prev_price
                    returns[curr_date] = daily_return

            return returns

        except Exception as e:
            logger.error(f"获取指数 {index_code} 收益率失败: {e}")
            return {}


class StockPoolRepositoryAdapter(StockPoolPort):
    """
    股票池仓储适配器

    使用 Django 缓存和数据库存储股票池信息。
    """

    def __init__(self):
        from django.core.cache import cache
        self._cache = cache
        self._cache_key_prefix = "equity:stock_pool"

    def get_current_pool(self) -> list[str]:
        """
        获取当前股票池

        Returns:
            股票代码列表
        """
        from django.core.cache import cache

        pool_key = f"{self._cache_key_prefix}:current"
        cached_pool = cache.get(pool_key)

        if cached_pool:
            return cached_pool

        # 如果缓存没有，从数据库读取
        return self._load_pool_from_db()

    def save_pool(
        self,
        stock_codes: list[str],
        regime: str,
        as_of_date: date
    ) -> None:
        """
        保存股票池

        Args:
            stock_codes: 股票代码列表
            regime: 当前的 Regime
            as_of_date: 截止日期
        """
        import json

        from django.core.cache import cache

        # 保存到缓存（24 小时过期）
        pool_key = f"{self._cache_key_prefix}:current"
        cache.set(pool_key, stock_codes, timeout=86400)

        # 保存元数据
        meta_key = f"{self._cache_key_prefix}:meta"
        meta = {
            'regime': regime,
            'as_of_date': as_of_date.isoformat(),
            'count': len(stock_codes),
            'updated_at': date.today().isoformat()
        }
        cache.set(meta_key, json.dumps(meta), timeout=86400)

        # 同时保存到数据库（持久化）
        self._save_pool_to_db(stock_codes, regime, as_of_date)

    def get_latest_pool_info(self) -> dict | None:
        """
        获取最新的股票池信息

        Returns:
            包含股票池元数据的字典，或 None
        """
        import json

        from django.core.cache import cache

        meta_key = f"{self._cache_key_prefix}:meta"
        meta_str = cache.get(meta_key)

        if meta_str:
            return json.loads(meta_str)

        return self._load_pool_meta_from_db()

    def _load_pool_from_db(self) -> list[str]:
        """从数据库加载股票池"""
        try:
            from .models import StockPoolSnapshot

            latest = StockPoolSnapshot.objects.filter(
                is_active=True
            ).order_by('-created_at').first()

            if latest:
                return latest.stock_codes

            return []

        except Exception as e:
            logger.error(f"从数据库加载股票池失败: {e}")
            return []

    def _save_pool_to_db(
        self,
        stock_codes: list[str],
        regime: str,
        as_of_date: date
    ) -> None:
        """保存股票池到数据库"""
        try:
            from .models import StockPoolSnapshot

            # 先将旧的快照设为非活跃
            StockPoolSnapshot.objects.filter(is_active=True).update(is_active=False)

            # 创建新快照
            StockPoolSnapshot.objects.create(
                stock_codes=stock_codes,
                regime=regime,
                as_of_date=as_of_date,
                is_active=True
            )

        except Exception as e:
            logger.error(f"保存股票池到数据库失败: {e}")

    def _load_pool_meta_from_db(self) -> dict | None:
        """从数据库加载股票池元数据"""
        try:
            from .models import StockPoolSnapshot

            latest = StockPoolSnapshot.objects.filter(
                is_active=True
            ).order_by('-created_at').first()

            if latest:
                return {
                    'regime': latest.regime,
                    'as_of_date': latest.as_of_date.isoformat(),
                    'count': len(latest.stock_codes),
                    'updated_at': latest.created_at.date().isoformat()
                }

            return None

        except Exception as e:
            logger.error(f"从数据库加载股票池元数据失败: {e}")
            return None
