"""
AKShare Data Adapter.

Infrastructure layer - fetches China macro data from AKShare.

重构说明：
- 原单个文件 (1778行) 已按指标类别拆分为多个 fetcher 模块
- 主适配器现在只负责路由请求到相应的 fetcher
"""

import logging
from datetime import date
from typing import List

import pandas as pd

from shared.infrastructure.sdk_bridge import get_akshare_module

from .base import (
    BaseMacroAdapter,
    DataSourceUnavailableError,
    MacroDataPoint,
)
from .fetchers import (
    BaseIndicatorFetcher,
    EconomicIndicatorFetcher,
    FinancialIndicatorFetcher,
    HighFrequencyIndicatorFetcher,
    OtherIndicatorFetcher,
    PMISubitemsFetcher,
    TradeIndicatorFetcher,
    WeeklyIndicatorFetcher,
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
        "CN_DR007": "存款类机构7天期回购加权平均利率",
        "CN_PBOC_NET_INJECTION": "央行公开市场净投放",
        # ============ 高频指标（Regime 滞后性改进 Phase 1）============
        "CN_BOND_10Y": "10年期国债收益率",
        "CN_BOND_5Y": "5年期国债收益率",
        "CN_BOND_2Y": "2年期国债收益率",
        "CN_BOND_1Y": "1年期国债收益率",
        "CN_TERM_SPREAD_10Y1Y": "期限利差(10Y-1Y)",
        "CN_TERM_SPREAD_10Y2Y": "期限利差(10Y-2Y)",
        "CN_CORP_YIELD_AAA": "AAA级企业债收益率",
        "CN_CORP_YIELD_AA": "AA级企业债收益率",
        "CN_CREDIT_SPREAD": "信用利差(AA-AAA)",
        "CN_NHCI": "南华商品指数",
        "CN_FX_CENTER": "人民币中间价",
        "US_BOND_10Y": "美国10年期国债",
        "USD_INDEX": "美元指数",
        "VIX_INDEX": "VIX波动率指数",
        # ============ 周度指标（Regime 滞后性改进 Phase 2）============
        "CN_POWER_GEN": "发电量",
        "CN_BLAST_FURNACE": "高炉开工率",
        "CN_CCFI": "集装箱运价指数(CCFI)",
        "CN_SCFI": "上海出口运价指数(SCFI)",
        # ============ PMI 分项指标（Regime 滞后性改进 Phase 3）============
        "CN_PMI_NEW_ORDER": "PMI新订单指数",
        "CN_PMI_INVENTORY": "PMI产成品库存指数",
        "CN_PMI_RAW_MAT": "PMI原材料库存指数",
        "CN_PMI_PURCHASE": "PMI采购量指数",
        "CN_PMI_PRODUCTION": "PMI生产指数",
        "CN_PMI_EMPLOYMENT": "PMI从业人员指数",
    }

    def __init__(self):
        """初始化 AKShare 适配器"""
        self._ak = None
        self._base_fetcher = None
        self._economic_fetcher = None
        self._trade_fetcher = None
        self._financial_fetcher = None
        self._other_fetcher = None
        self._high_frequency_fetcher = None
        self._weekly_fetcher = None
        self._pmi_subitems_fetcher = None

    @property
    def ak(self):
        """延迟初始化 akshare"""
        if self._ak is None:
            try:
                self._ak = get_akshare_module()
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

    @property
    def high_frequency_fetcher(self):
        """高频指标获取器"""
        if self._high_frequency_fetcher is None:
            self._high_frequency_fetcher = HighFrequencyIndicatorFetcher(
                self.ak, self.source_name, self._validate_data_point, self._sort_and_deduplicate
            )
        return self._high_frequency_fetcher

    @property
    def weekly_fetcher(self):
        """周度指标获取器"""
        if self._weekly_fetcher is None:
            self._weekly_fetcher = WeeklyIndicatorFetcher(
                self.ak, self.source_name, self._validate_data_point, self._sort_and_deduplicate
            )
        return self._weekly_fetcher

    @property
    def pmi_subitems_fetcher(self):
        """PMI分项指标获取器（手动维护数据文件）"""
        if self._pmi_subitems_fetcher is None:
            self._pmi_subitems_fetcher = PMISubitemsFetcher(
                self.ak, self.source_name, self._validate_data_point, self._sort_and_deduplicate
            )
        return self._pmi_subitems_fetcher

    def supports(self, indicator_code: str) -> bool:
        """检查是否支持指定指标"""
        return indicator_code in self.SUPPORTED_INDICATORS

    def fetch(self, indicator_code: str, start_date: date, end_date: date) -> list[MacroDataPoint]:
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
            elif indicator_code in [
                "CN_CPI_NATIONAL_YOY",
                "CN_CPI_NATIONAL_MOM",
                "CN_CPI_URBAN_YOY",
                "CN_CPI_URBAN_MOM",
                "CN_CPI_RURAL_YOY",
                "CN_CPI_RURAL_MOM",
            ]:
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
            elif indicator_code == "CN_DR007":
                return self.financial_fetcher.fetch_dr007(start_date, end_date)
            elif indicator_code == "CN_PBOC_NET_INJECTION":
                return self.financial_fetcher.fetch_pboc_open_market(start_date, end_date)

            # ============ 高频指标（Regime 滞后性改进 Phase 1）============
            elif indicator_code in ["CN_BOND_10Y", "CN_BOND_5Y", "CN_BOND_2Y", "CN_BOND_1Y"]:
                term = indicator_code.split("_")[-1]  # 10Y, 5Y, 2Y, 1Y
                return self.high_frequency_fetcher.fetch_bond_yield(term, start_date, end_date)
            elif indicator_code == "CN_TERM_SPREAD_10Y1Y":
                return self.high_frequency_fetcher.fetch_term_spread(
                    "10Y", "1Y", start_date, end_date
                )
            elif indicator_code == "CN_TERM_SPREAD_10Y2Y":
                return self.high_frequency_fetcher.fetch_term_spread(
                    "10Y", "2Y", start_date, end_date
                )
            elif indicator_code in ["CN_CORP_YIELD_AAA", "CN_CORP_YIELD_AA"]:
                rating = indicator_code.split("_")[-1]  # AAA, AA
                return self.high_frequency_fetcher.fetch_corp_bond_yield(
                    rating, start_date, end_date
                )
            elif indicator_code == "CN_CREDIT_SPREAD":
                return self.high_frequency_fetcher.fetch_credit_spread(start_date, end_date)
            elif indicator_code == "CN_NHCI":
                return self.high_frequency_fetcher.fetch_nhci(start_date, end_date)
            elif indicator_code == "CN_FX_CENTER":
                return self.high_frequency_fetcher.fetch_fx_center_rate(start_date, end_date)
            elif indicator_code == "US_BOND_10Y":
                return self.high_frequency_fetcher.fetch_us_bond_10y(start_date, end_date)
            elif indicator_code == "USD_INDEX":
                return self.high_frequency_fetcher.fetch_usd_index(start_date, end_date)
            elif indicator_code == "VIX_INDEX":
                return self.high_frequency_fetcher.fetch_vix_index(start_date, end_date)

            # ============ 周度指标（Regime 滞后性改进 Phase 2）============
            elif indicator_code == "CN_POWER_GEN":
                return self.weekly_fetcher.fetch_power_generation(start_date, end_date)
            elif indicator_code == "CN_BLAST_FURNACE":
                return self.weekly_fetcher.fetch_blast_furnace_utilization(start_date, end_date)
            elif indicator_code == "CN_CCFI":
                return self.weekly_fetcher.fetch_ccfi(start_date, end_date)
            elif indicator_code == "CN_SCFI":
                return self.weekly_fetcher.fetch_scfi(start_date, end_date)

            # ============ PMI 分项指标（Regime 滞后性改进 Phase 3）============
            elif indicator_code == "CN_PMI_NEW_ORDER":
                return self.pmi_subitems_fetcher.fetch_pmi_new_order(start_date, end_date)
            elif indicator_code == "CN_PMI_INVENTORY":
                return self.pmi_subitems_fetcher.fetch_pmi_inventory(start_date, end_date)
            elif indicator_code == "CN_PMI_RAW_MAT":
                return self.pmi_subitems_fetcher.fetch_pmi_raw_material(start_date, end_date)
            elif indicator_code == "CN_PMI_PURCHASE":
                return self.pmi_subitems_fetcher.fetch_pmi_purchase(start_date, end_date)
            elif indicator_code == "CN_PMI_PRODUCTION":
                return self.pmi_subitems_fetcher.fetch_pmi_production(start_date, end_date)
            elif indicator_code == "CN_PMI_EMPLOYMENT":
                return self.pmi_subitems_fetcher.fetch_pmi_employment(start_date, end_date)
            else:
                return []

        except Exception as e:
            logger.error(f"获取 {indicator_code} 数据失败: {e}")
            raise DataSourceUnavailableError(f"获取数据失败: {e}")
