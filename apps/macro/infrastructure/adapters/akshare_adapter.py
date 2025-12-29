"""
AKShare Data Adapter.

Infrastructure layer - fetches China macro data from AKShare.

重构说明：
- 原单个文件 (1778行) 已按指标类别拆分为多个 fetcher 模块
- 主适配器现在只负责路由请求到相应的 fetcher
"""

import pandas as pd
from datetime import date
from typing import List
import logging

from .base import (
    BaseMacroAdapter,
    MacroDataPoint,
    DataSourceUnavailableError,
)
from .fetchers import (
    BaseIndicatorFetcher,
    EconomicIndicatorFetcher,
    TradeIndicatorFetcher,
    FinancialIndicatorFetcher,
    OtherIndicatorFetcher,
)

logger = logging.getLogger(__name__)


class AKShareAdapter(BaseMacroAdapter):
    """
    AKShare 数据适配器

    支持的中国宏观数据：
    - PMI（制造业采购经理指数）
    - CPI（居民消费价格指数）
    - PPI（工业生产者出厂价格指数）
    - M2（货币供应量）
    - 工业增加值
    - 社会消费品零售总额
    """

    source_name = "akshare"

    # 支持的指标代码映射
    SUPPORTED_INDICATORS = {
        # 基础指标
        "CN_PMI": "PMI",
        "CN_NON_MAN_PMI": "非制造业PMI",
        "CN_CPI": "CPI",
        "CN_CPI_NATIONAL_YOY": "全国CPI同比",
        "CN_CPI_NATIONAL_MOM": "全国CPI环比",
        "CN_CPI_URBAN_YOY": "城市CPI同比",
        "CN_CPI_URBAN_MOM": "城市CPI环比",
        "CN_CPI_RURAL_YOY": "农村CPI同比",
        "CN_CPI_RURAL_MOM": "农村CPI环比",
        "CN_PPI": "PPI",
        "CN_PPI_YOY": "PPI同比",
        "CN_M2": "M2",
        "CN_VALUE_ADDED": "工业增加值",
        "CN_RETAIL_SALES": "社会消费品零售总额",
        "CN_GDP": "GDP",

        # 贸易数据
        "CN_EXPORTS": "出口同比增长",
        "CN_IMPORTS": "进口同比增长",
        "CN_TRADE_BALANCE": "贸易差额",

        # 房产数据
        "CN_NEW_HOUSE_PRICE": "新房价格指数",

        # 价格数据
        "CN_OIL_PRICE": "成品油价格",

        # 就业数据
        "CN_UNEMPLOYMENT": "城镇调查失业率",

        # 金融数据
        "CN_FX_RESERVES": "外汇储备",
        "CN_LPR": "LPR",
        "CN_SHIBOR": "SHIBOR",
        "CN_RRR": "存款准备金率",

        # 信贷数据
        "CN_NEW_CREDIT": "新增信贷",
        "CN_RMB_DEPOSIT": "人民币存款",
        "CN_RMB_LOAN": "人民币贷款",
    }

    def __init__(self):
        """初始化 AKShare 适配器"""
        self._ak = None
        self._base_fetcher = None
        self._economic_fetcher = None
        self._trade_fetcher = None
        self._financial_fetcher = None
        self._other_fetcher = None

    @property
    def ak(self):
        """延迟初始化 akshare"""
        if self._ak is None:
            try:
                import akshare as ak
                self._ak = ak
                logger.info("AKShare 初始化成功")
            except ImportError:
                raise DataSourceUnavailableError("akshare 库未安装，请运行: pip install akshare")
            except Exception as e:
                raise DataSourceUnavailableError(f"AKShare 初始化失败: {e}")
        return self._ak

    @property
    def base_fetcher(self):
        """基础指标获取器"""
        if self._base_fetcher is None:
            self._base_fetcher = BaseIndicatorFetcher(
                self.ak, self.source_name, self._validate_data_point, self._sort_and_deduplicate
            )
        return self._base_fetcher

    @property
    def economic_fetcher(self):
        """经济活动指标获取器"""
        if self._economic_fetcher is None:
            self._economic_fetcher = EconomicIndicatorFetcher(
                self.ak, self.source_name, self._validate_data_point, self._sort_and_deduplicate
            )
        return self._economic_fetcher

    @property
    def trade_fetcher(self):
        """贸易指标获取器"""
        if self._trade_fetcher is None:
            self._trade_fetcher = TradeIndicatorFetcher(
                self.ak, self.source_name, self._validate_data_point, self._sort_and_deduplicate
            )
        return self._trade_fetcher

    @property
    def financial_fetcher(self):
        """金融指标获取器"""
        if self._financial_fetcher is None:
            self._financial_fetcher = FinancialIndicatorFetcher(
                self.ak, self.source_name, self._validate_data_point, self._sort_and_deduplicate
            )
        return self._financial_fetcher

    @property
    def other_fetcher(self):
        """其他指标获取器"""
        if self._other_fetcher is None:
            self._other_fetcher = OtherIndicatorFetcher(
                self.ak, self.source_name, self._validate_data_point, self._sort_and_deduplicate
            )
        return self._other_fetcher

    def supports(self, indicator_code: str) -> bool:
        """检查是否支持指定指标"""
        return indicator_code in self.SUPPORTED_INDICATORS

    def fetch(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """
        获取指定指标的数据

        Args:
            indicator_code: 指标代码
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 数据点列表
        """
        if not self.supports(indicator_code):
            raise DataSourceUnavailableError(
                f"AKShare 不支持的指标: {indicator_code}，"
                f"支持的指标: {list(self.SUPPORTED_INDICATORS.keys())}"
            )

        try:
            # 基础指标
            if indicator_code == "CN_PMI":
                return self.base_fetcher.fetch_pmi(start_date, end_date)
            elif indicator_code == "CN_NON_MAN_PMI":
                return self.base_fetcher.fetch_non_man_pmi(start_date, end_date)
            elif indicator_code == "CN_CPI":
                return self.base_fetcher.fetch_cpi(start_date, end_date)
            elif indicator_code in ["CN_CPI_NATIONAL_YOY", "CN_CPI_NATIONAL_MOM",
                                   "CN_CPI_URBAN_YOY", "CN_CPI_URBAN_MOM",
                                   "CN_CPI_RURAL_YOY", "CN_CPI_RURAL_MOM"]:
                return self.base_fetcher.fetch_cpi_detailed(start_date, end_date, indicator_code)
            elif indicator_code == "CN_PPI":
                return self.base_fetcher.fetch_ppi(start_date, end_date)
            elif indicator_code == "CN_PPI_YOY":
                return self.base_fetcher.fetch_ppi_yoy(start_date, end_date)
            elif indicator_code == "CN_M2":
                return self.base_fetcher.fetch_m2(start_date, end_date)

            # 经济活动指标
            elif indicator_code == "CN_VALUE_ADDED":
                return self.economic_fetcher.fetch_value_added(start_date, end_date)
            elif indicator_code == "CN_RETAIL_SALES":
                return self.economic_fetcher.fetch_retail_sales(start_date, end_date)
            elif indicator_code == "CN_GDP":
                return self.economic_fetcher.fetch_gdp(start_date, end_date)

            # 贸易指标
            elif indicator_code == "CN_EXPORTS":
                return self.trade_fetcher.fetch_exports(start_date, end_date)
            elif indicator_code == "CN_IMPORTS":
                return self.trade_fetcher.fetch_imports(start_date, end_date)
            elif indicator_code == "CN_TRADE_BALANCE":
                return self.trade_fetcher.fetch_trade_balance(start_date, end_date)

            # 金融指标
            elif indicator_code == "CN_UNEMPLOYMENT":
                return self.other_fetcher.fetch_unemployment(start_date, end_date)
            elif indicator_code == "CN_FX_RESERVES":
                return self.financial_fetcher.fetch_fx_reserves(start_date, end_date)
            elif indicator_code == "CN_LPR":
                return self.financial_fetcher.fetch_lpr(start_date, end_date)
            elif indicator_code == "CN_SHIBOR":
                return self.financial_fetcher.fetch_shibor(start_date, end_date)
            elif indicator_code == "CN_RRR":
                return self.financial_fetcher.fetch_rrr(start_date, end_date)
            elif indicator_code == "CN_NEW_HOUSE_PRICE":
                return self.other_fetcher.fetch_new_house_price(start_date, end_date)
            elif indicator_code == "CN_OIL_PRICE":
                return self.other_fetcher.fetch_oil_price(start_date, end_date)
            elif indicator_code == "CN_NEW_CREDIT":
                return self.financial_fetcher.fetch_new_credit(start_date, end_date)
            elif indicator_code == "CN_RMB_DEPOSIT":
                return self.financial_fetcher.fetch_rmb_deposit(start_date, end_date)
            elif indicator_code == "CN_RMB_LOAN":
                return self.financial_fetcher.fetch_rmb_loan(start_date, end_date)
            else:
                return []

        except Exception as e:
            logger.error(f"获取 {indicator_code} 数据失败: {e}")
            raise DataSourceUnavailableError(f"获取数据失败: {e}")
