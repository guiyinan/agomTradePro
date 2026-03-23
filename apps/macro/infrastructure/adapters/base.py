"""
Base Protocol and Exceptions for Macro Data Adapters.

Infrastructure layer - defines the interface that all adapters must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Protocol


class DataSourceUnavailableError(Exception):
    """数据源不可用异常"""
    pass


class DataValidationError(Exception):
    """数据验证异常"""
    pass


@dataclass
class PublicationLag:
    """发布延迟配置"""
    days: int
    description: str


# 各指标发布延迟配置（天）
BASE_PUBLICATION_LAGS: dict[str, PublicationLag] = {
    # 中国宏观数据
    "CN_PMI": PublicationLag(days=1, description="PMI 次月1日发布"),
    "CN_NON_MAN_PMI": PublicationLag(days=1, description="非制造业PMI 次月1日发布"),
    "CN_CPI": PublicationLag(days=10, description="CPI 月后10日左右发布"),
    "CN_CPI_NATIONAL_YOY": PublicationLag(days=10, description="全国CPI同比 月后10日左右发布"),
    "CN_CPI_NATIONAL_MOM": PublicationLag(days=10, description="全国CPI环比 月后10日左右发布"),
    "CN_CPI_URBAN_YOY": PublicationLag(days=10, description="城市CPI同比 月后10日左右发布"),
    "CN_CPI_URBAN_MOM": PublicationLag(days=10, description="城市CPI环比 月后10日左右发布"),
    "CN_CPI_RURAL_YOY": PublicationLag(days=10, description="农村CPI同比 月后10日左右发布"),
    "CN_CPI_RURAL_MOM": PublicationLag(days=10, description="农村CPI环比 月后10日左右发布"),
    "CN_PPI": PublicationLag(days=10, description="PPI 月后10日左右发布"),
    "CN_PPI_YOY": PublicationLag(days=10, description="PPI同比 月后10日左右发布"),
    "CN_M2": PublicationLag(days=15, description="M2 月后10-15日发布"),
    "CN_GDP": PublicationLag(days=20, description="GDP 季后20日左右发布"),
    "CN_VALUE_ADDED": PublicationLag(days=10, description="工业增加值 月后10日左右"),
    "CN_RETAIL_SALES": PublicationLag(days=10, description="社零 月后10日左右"),

    # 贸易数据
    "CN_EXPORTS": PublicationLag(days=10, description="出口数据 月后10日左右发布"),
    "CN_IMPORTS": PublicationLag(days=10, description="进口数据 月后10日左右发布"),
    "CN_TRADE_BALANCE": PublicationLag(days=10, description="贸易差额 月后10日左右发布"),

    # 房产数据
    "CN_NEW_HOUSE_PRICE": PublicationLag(days=15, description="新房价格指数 月后15日左右发布"),

    # 价格数据
    "CN_OIL_PRICE": PublicationLag(days=0, description="成品油价格 不定期调整"),

    # 就业数据
    "CN_UNEMPLOYMENT": PublicationLag(days=15, description="城镇调查失业率 月后15日左右发布"),

    # 金融数据
    "CN_FX_RESERVES": PublicationLag(days=10, description="外汇储备 月后10日左右发布"),

    # 利率数据
    "CN_SHIBOR": PublicationLag(days=0, description="SHIBOR 每日发布"),
    "CN_LPR": PublicationLag(days=1, description="LPR 每月20日发布"),
    "CN_RRR": PublicationLag(days=0, description="存款准备金率 不定期调整"),

    # 信贷数据
    "CN_NEW_CREDIT": PublicationLag(days=15, description="新增信贷 月后10-15日发布"),
    "CN_RMB_DEPOSIT": PublicationLag(days=15, description="人民币存款 月后10-15日发布"),
    "CN_RMB_LOAN": PublicationLag(days=15, description="人民币贷款 月后10-15日发布"),

    # 兼容旧代码
    "SHIBOR": PublicationLag(days=0, description="SHIBOR 每日发布"),
    "LPR": PublicationLag(days=1, description="LPR 每月20日发布"),

}


def get_publication_lags() -> dict[str, PublicationLag]:
    """获取发布延迟配置，动态合并数据库中的指数配置。"""
    lags = dict(BASE_PUBLICATION_LAGS)

    try:
        from apps.account.infrastructure.models import SystemSettingsModel

        dynamic_lags = SystemSettingsModel.get_runtime_macro_publication_lags()
        for code, item in dynamic_lags.items():
            lags[code] = PublicationLag(
                days=int(item.get("days", 0) or 0),
                description=item.get("description", "实时"),
            )
    except Exception:
        pass

    return lags


PUBLICATION_LAGS = BASE_PUBLICATION_LAGS


@dataclass
class MacroDataPoint:
    """宏观数据点"""
    code: str
    value: float
    observed_at: date
    published_at: date | None = None
    source: str = "unknown"
    unit: str = ""
    original_unit: str = ""  # 原始单位（数据源返回的单位）

    def __post_init__(self):
        """自动填充发布时间和计算延迟"""
        if self.published_at is None:
            # 如果未指定发布时间，根据配置延迟计算
            lag = get_publication_lags().get(self.code)
            if lag:
                from datetime import timedelta
                self.published_at = self.observed_at + timedelta(days=lag.days)


class MacroAdapterProtocol(Protocol):
    """
    宏观数据适配器协议

    所有数据源适配器必须实现此协议。
    """

    source_name: str

    def supports(self, indicator_code: str) -> bool:
        """
        检查是否支持指定指标

        Args:
            indicator_code: 指标代码

        Returns:
            bool: 是否支持
        """
        ...

    def fetch(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """
        获取指定指标的数据

        Args:
            indicator_code: 指标代码
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 数据点列表

        Raises:
            DataSourceUnavailableError: 数据源不可用
            DataValidationError: 数据验证失败
        """
        ...


class BaseMacroAdapter(ABC):
    """
    宏观数据适配器基类

    提供通用的辅助方法。
    """

    source_name: str = "base"

    def supports(self, indicator_code: str) -> bool:
        """默认实现：子类应覆盖"""
        return False

    def fetch(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """默认实现：子类必须覆盖"""
        raise NotImplementedError

    def _validate_data_point(self, point: MacroDataPoint) -> None:
        """
        验证数据点

        Args:
            point: 数据点

        Raises:
            DataValidationError: 验证失败
        """
        if not point.code:
            raise DataValidationError("指标代码不能为空")

        if not isinstance(point.value, (int, float)):
            raise DataValidationError(f"指标值必须是数值类型: {type(point.value)}")

        if point.value < 0 and point.code not in ["CN_M2", "SHIBOR", "LPR"]:
            # 某些指标允许负值
            pass

        if not isinstance(point.observed_at, date):
            raise DataValidationError(f"观测日期必须是 date 类型: {type(point.observed_at)}")

    def _sort_and_deduplicate(
        self,
        data_points: list[MacroDataPoint]
    ) -> list[MacroDataPoint]:
        """
        排序并去重

        Args:
            data_points: 原始数据点列表

        Returns:
            List[MacroDataPoint]: 处理后的数据点列表
        """
        # 按日期排序
        sorted_points = sorted(data_points, key=lambda x: x.observed_at)

        # 去重（保留最新的）
        seen = {}
        for point in sorted_points:
            key = (point.code, point.observed_at)
            if key not in seen:
                seen[key] = point

        return list(seen.values())
