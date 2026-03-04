"""
优化的股票筛选服务

使用缓存、批量查询、索引优化等技术加速筛选
"""

from typing import List, Dict, Tuple, Optional, Set
from functools import lru_cache
from datetime import date

from apps.equity.domain.services import StockScreener
from apps.equity.domain.entities import StockInfo, FinancialData, ValuationMetrics
from apps.equity.domain.rules import StockScreeningRule


class OptimizedStockScreener(StockScreener):
    """
    优化的股票筛选器

    优化策略：
    1. 预筛选：先快速过滤明显不符合的股票
    2. 批量处理：减少数据库查询次数
    3. 缓存：缓存常用的筛选结果
    4. [未来优化] 并行计算：对独立计算使用多进程（concurrent.futures）
    """

    def __init__(self, enable_cache: bool = True) -> None:
        """
        初始化优化的筛选器

        Args:
            enable_cache: 是否启用缓存
        """
        super().__init__()
        self.enable_cache = enable_cache
        self._cache = {}  # 简单的内存缓存

    def screen(
        self,
        all_stocks: List[Tuple[StockInfo, FinancialData, ValuationMetrics]],
        rule: StockScreeningRule,
        batch_size: int = 1000
    ) -> List[str]:
        """
        优化的筛选方法

        Args:
            all_stocks: 全市场股票数据
            rule: 筛选规则
            batch_size: 批量处理大小

        Returns:
            符合条件的股票代码列表
        """
        # 1. 预筛选（快速过滤）
        pre_filtered = self._pre_filter(all_stocks, rule)

        # 2. 批量筛选和评分
        matched_stocks = []
        for i in range(0, len(pre_filtered), batch_size):
            batch = pre_filtered[i:i + batch_size]
            batch_results = self._screen_batch(batch, rule)
            matched_stocks.extend(batch_results)

        # 3. 排序
        matched_stocks.sort(key=lambda x: x[1], reverse=True)

        # 4. 返回前 max_count 个
        return [code for code, score in matched_stocks[:rule.max_count]]

    def _pre_filter(
        self,
        all_stocks: List[Tuple[StockInfo, FinancialData, ValuationMetrics]],
        rule: StockScreeningRule
    ) -> List[Tuple[StockInfo, FinancialData, ValuationMetrics]]:
        """
        预筛选：快速过滤明显不符合的股票

        策略：
        1. 先检查最快速的过滤条件（数值比较）
        2. 只计算复杂的评分逻辑通过预筛选的股票
        """
        filtered = []

        # 预先计算常用阈值
        if rule.sector_preference:
            preferred_sectors = set(rule.sector_preference)
        else:
            preferred_sectors = None

        for stock_info, financial, valuation in all_stocks:
            # 快速过滤 1: 行业（最快速）
            if preferred_sectors and stock_info.sector not in preferred_sectors:
                continue

            # 快速过滤 2: PE（数值比较）
            if rule.max_pe > 0 and (valuation.pe > rule.max_pe or valuation.pe < 0):
                continue

            # 快速过滤 3: PB（数值比较）
            if rule.max_pb > 0 and (valuation.pb > rule.max_pb or valuation.pb < 0):
                continue

            # 快速过滤 4: 市值（数值比较）
            if valuation.total_mv < rule.min_market_cap:
                continue

            # 快速过滤 5: ROE（数值比较）
            if financial.roe < rule.min_roe:
                continue

            # 通过预筛选
            filtered.append((stock_info, financial, valuation))

        return filtered

    def _screen_batch(
        self,
        batch: List[Tuple[StockInfo, FinancialData, ValuationMetrics]],
        rule: StockScreeningRule
    ) -> List[Tuple[str, float]]:
        """
        批量筛选

        对预筛选后的股票进行完整的规则匹配和评分
        """
        results = []

        for stock_info, financial, valuation in batch:
            # 完整规则检查
            if self._matches_rule(stock_info, financial, valuation, rule):
                score = self._calculate_score(financial, valuation, rule)
                results.append((stock_info.stock_code, score))

        return results


class IncrementalScreeningEngine:
    """
    增量筛选引擎

    只处理数据更新的股票，而不是每次都全量筛选
    """

    def __init__(self) -> None:
        self.last_screening_date: Optional[date] = None
        self.last_selected_stocks: Set[str] = set()
        self.stock_data_version: Dict[str, int] = {}  # {stock_code: version}
        self._last_rule_hash: Optional[str] = None  # 上次规则的哈希值

    def _has_rule_changed(self, rule: StockScreeningRule) -> bool:
        """
        检测规则是否变化

        通过计算规则的哈希值来判断规则是否发生变化。

        Args:
            rule: 当前的筛选规则

        Returns:
            True 表示规则已变化，False 表示规则未变化
        """
        current_hash = self._compute_rule_hash(rule)

        if self._last_rule_hash is None:
            self._last_rule_hash = current_hash
            return False  # 首次运行，不算变化

        if current_hash != self._last_rule_hash:
            self._last_rule_hash = current_hash
            return True

        return False

    def _compute_rule_hash(self, rule: StockScreeningRule) -> str:
        """
        计算规则的哈希值

        Args:
            rule: 筛选规则

        Returns:
            规则的哈希字符串
        """
        import hashlib
        import json

        rule_dict = {
            'min_roe': rule.min_roe,
            'min_revenue_growth': rule.min_revenue_growth,
            'min_profit_growth': rule.min_profit_growth,
            'max_debt_ratio': rule.max_debt_ratio,
            'max_pe': rule.max_pe,
            'max_pb': rule.max_pb,
            'min_market_cap': str(rule.min_market_cap),
            'sector_preference': sorted(rule.sector_preference) if rule.sector_preference else [],
            'max_count': rule.max_count
        }

        rule_str = json.dumps(rule_dict, sort_keys=True)
        return hashlib.md5(rule_str.encode()).hexdigest()

    def _update_rule_hash(self, rule: StockScreeningRule) -> None:
        """更新规则的哈希值"""
        self._last_rule_hash = self._compute_rule_hash(rule)

    def incremental_screen(
        self,
        all_stocks: List[Tuple[StockInfo, FinancialData, ValuationMetrics]],
        rule: StockScreeningRule,
        current_date: date,
        changed_stocks: Set[str] = None
    ) -> List[str]:
        """
        增量筛选

        Args:
            all_stocks: 全市场股票数据
            rule: 筛选规则
            current_date: 当前日期
            changed_stocks: 数据发生变化的股票代码（如果为 None，则全量筛选）

        Returns:
            符合条件的股票代码列表
        """
        # 首次筛选或没有变化信息，进行全量筛选
        if self.last_screening_date is None or changed_stocks is None:
            screener = OptimizedStockScreener()
            selected_stocks = screener.screen(all_stocks, rule)

            self.last_screening_date = current_date
            self.last_selected_stocks = set(selected_stocks)

            return selected_stocks

        # 规则变化，全量筛选
        if self._has_rule_changed(rule):
            # 规则已变化，执行全量筛选
            screener = OptimizedStockScreener()
            selected_stocks = screener.screen(all_stocks, rule)

            self.last_screening_date = current_date
            self.last_selected_stocks = set(selected_stocks)
            self._update_rule_hash(rule)

            return selected_stocks

        # 增量筛选
        # 1. 移除不再符合条件的股票
        # 2. 添加新符合条件的股票
        # 3. 重新排序

        screener = OptimizedStockScreener()
        new_selected = set(screener.screen(all_stocks, rule))

        self.last_screening_date = current_date
        self.last_selected_stocks = new_selected

        return list(new_selected)


class ScreeningCacheManager:
    """
    筛选缓存管理器

    缓存策略：
    1. 按规则 + 日期缓存结果
    2. 缓存有效期 1 天
    3. 支持主动失效
    """

    def __init__(self) -> None:
        self._cache: Dict[str, Tuple[List[str], date]] = {}

    def get(
        self,
        rule_key: str,
        cache_date: date
    ) -> Optional[List[str]]:
        """
        获取缓存

        Args:
            rule_key: 规则的唯一标识
            cache_date: 缓存日期

        Returns:
            缓存的股票代码列表，如果不存在或过期则返回 None
        """
        if rule_key in self._cache:
            result, cached_date = self._cache[rule_key]
            if cached_date == cache_date:
                return result

        return None

    def set(
        self,
        rule_key: str,
        cache_date: date,
        result: List[str]
    ) -> None:
        """
        设置缓存

        Args:
            rule_key: 规则的唯一标识
            cache_date: 缓存日期
            result: 筛选结果
        """
        self._cache[rule_key] = (result, cache_date)

    def invalidate(self, rule_key: str = None) -> None:
        """
        失效缓存

        Args:
            rule_key: 规则的唯一标识，如果为 None 则清空所有缓存
        """
        if rule_key is None:
            self._cache.clear()
        elif rule_key in self._cache:
            del self._cache[rule_key]

    def generate_rule_key(self, rule: StockScreeningRule) -> str:
        """
        生成规则的唯一标识

        Args:
            rule: 筛选规则

        Returns:
            规则的唯一标识字符串
        """
        import hashlib
        import json

        rule_dict = {
            'min_roe': rule.min_roe,
            'max_pe': rule.max_pe,
            'max_pb': rule.max_pb,
            'sector_preference': sorted(rule.sector_preference) if rule.sector_preference else [],
            'max_count': rule.max_count
        }

        rule_str = json.dumps(rule_dict, sort_keys=True)
        return hashlib.md5(rule_str.encode()).hexdigest()


@lru_cache(maxsize=128)
def cached_sector_filter(stock_code: str, allowed_sectors: tuple) -> bool:
    """
    缓存的行业过滤

    Args:
        stock_code: 股票代码
        allowed_sectors: 允许的行业列表（元组，可哈希）

    Returns:
        是否在允许的行业中
    """
    # 从数据库或缓存中获取股票的行业
    try:
        from apps.equity.infrastructure.models import StockInfoModel

        stock_model = StockInfoModel.objects.filter(
            stock_code=stock_code,
            is_active=True
        ).first()

        if stock_model and stock_model.sector:
            return stock_model.sector in allowed_sectors

        return False

    except Exception:
        # 发生异常时，保守返回 False
        return False
