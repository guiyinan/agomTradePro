"""
宏观经济指标服务

提供指标查询、元数据获取、单位转换等功能
"""

from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from apps.macro.infrastructure.models import MacroIndicator, IndicatorUnitConfig


class UnitDisplayService:
    """单位展示服务

    负责将存储值（统一为"元"）转换回展示值（原始单位）
    """

    @staticmethod
    def convert_for_display(
        stored_value: float,
        storage_unit: str,
        original_unit: str
    ) -> Tuple[float, str]:
        """
        将存储值转换为展示值

        Args:
            stored_value: 存储的值（货币类为元）
            storage_unit: 存储单位（货币类为"元"）
            original_unit: 原始单位（用于展示）

        Returns:
            tuple: (展示值, 展示单位)

        Examples:
            >>> # GDP: 存储为元，展示为亿元
            >>> UnitDisplayService.convert_for_display(150000000000, "元", "亿元")
            (1500.0, "亿元")

            >>> # PMI: 存储和展示都是原始单位
            >>> UnitDisplayService.convert_for_display(50.5, "指数", "指数")
            (50.5, "指数")
        """
        from ..domain.entities import UNIT_CONVERSION_FACTORS

        # 如果存储单位和原始单位相同，直接返回
        if storage_unit == original_unit:
            return (stored_value, original_unit)

        # 如果存储单位是"元"，需要转换回原始单位
        if storage_unit == "元" and original_unit in UNIT_CONVERSION_FACTORS:
            factor = UNIT_CONVERSION_FACTORS[original_unit]
            display_value = stored_value / factor
            return (display_value, original_unit)

        # 如果原始单位是"元"，说明已经是最小单位
        if original_unit == "元":
            return (stored_value, "元")

        # 其他情况，直接返回原始值和原始单位
        return (stored_value, original_unit)

    @classmethod
    def format_for_display(
        cls,
        stored_value: float,
        storage_unit: str,
        original_unit: str,
        precision: int = 2
    ) -> str:
        """
        格式化值为展示字符串

        Args:
            stored_value: 存储的值
            storage_unit: 存储单位
            original_unit: 原始单位
            precision: 小数点精度

        Returns:
            str: 格式化的展示字符串

        Examples:
            >>> UnitDisplayService.format_for_display(150000000000, "元", "亿元")
            "1500.00亿元"
        """
        display_value, display_unit = cls.convert_for_display(
            stored_value, storage_unit, original_unit
        )

        # 如果是百分比，不格式化小数
        if display_unit == "%":
            return f"{display_value:.{precision}f}%"

        # 如果是指数或点，不添加单位（原始数据可能已包含单位）
        if display_unit in ["指数", "点", ""]:
            return f"{display_value:.{precision}f}{display_unit}"

        # 其他单位，数值+单位
        return f"{display_value:.{precision}f}{display_unit}"

    @classmethod
    def get_indicator_config(cls, indicator_code: str, source: str = None) -> Optional[IndicatorUnitConfig]:
        """
        获取指标的单位配置

        优先级：
        1. 指定数据源的配置
        2. 手动配置
        3. 默认配置

        Args:
            indicator_code: 指标代码
            source: 数据源（可选）

        Returns:
            IndicatorUnitConfig: 单位配置，不存在则返回 None
        """
        queryset = IndicatorUnitConfig._default_manager.filter(
            indicator_code=indicator_code,
            is_active=True
        )

        if source:
            # 优先查找指定数据源的配置
            config = queryset.filter(source=source).first()
            if config:
                return config

        # 查找手动配置
        config = queryset.filter(source='manual').first()
        if config:
            return config

        # 返回优先级最高的配置
        return queryset.order_by('-priority').first()

    @classmethod
    def get_original_unit(cls, indicator_code: str, source: str = None) -> str:
        """
        获取指标的原始单位

        Args:
            indicator_code: 指标代码
            source: 数据源（可选）

        Returns:
            str: 原始单位，如果未配置则返回空字符串
        """
        config = cls.get_indicator_config(indicator_code, source)
        if config:
            return config.original_unit

        # 回退到 IndicatorUnitService 的配置
        return IndicatorUnitService.get_unit_for_indicator(indicator_code)


class IndicatorUnitService:
    """指标单位服务"""

    # 指标单位映射（指标代码 -> 单位）
    INDICATOR_UNITS: Dict[str, str] = {
        # 景气指标
        'CN_PMI': '指数',
        'CN_PMI_MANUFACTURING': '指数',
        'CN_NON_MAN_PMI': '指数',
        'CN_PMI_NON_MANUFACTURING': '指数',

        # 物价指标
        'CN_CPI': '%',
        'CN_CPI_YOY': '%',
        'CN_CPI_MOY': '%',
        'CN_CPI_NATIONAL_YOY': '%',
        'CN_CPI_NATIONAL_MOM': '%',
        'CN_PPI': '%',
        'CN_PPI_YOY': '%',
        'CN_PPI_MOM': '%',

        # 货币指标
        'CN_M2': '%',
        'CN_M2_YOY': '%',
        'CN_SOCIAL_FINANCING': '万亿元',
        'CN_SOCIAL_FINANCING_YOY': '%',

        # 利率指标
        'SHIBOR': '%',
        'SHIBOR_O_N': '%',
        'SHIBOR_1M': '%',
        'SHIBOR_1Y': '%',
        'CN_SHIBOR': '%',
        'CN_LPR': '%',
        'CN_LPR_1Y': '%',
        'CN_LPR_5Y': '%',
        'CN_RRR': '%',

        # 货币供应量（需要转换为元）
        'CN_FX_RESERVES': '万亿美元',  # 需要转换为元
        'CN_NEW_CREDIT': '万亿元',  # 需要转换为元
        'CN_RMB_DEPOSIT': '万亿元',  # 需要转换为元
        'CN_RMB_LOAN': '万亿元',  # 需要转换为元

        # GDP
        'CN_GDP': '%',
        'CN_GDP_YOY': '%',

        # 投资指标
        'CN_FAI': '%',
        'CN_FAI_YOY': '%',
        'CN_REALESTATE_INVESTMENT': '%',
        'CN_REALESTATE_INVESTMENT_YOY': '%',

        # 消费指标
        'CN_RETAIL_SALES': '%',
        'CN_RETAIL_SALES_YOY': '%',

        # 外贸指标
        'CN_EXPORTS': '%',
        'CN_EXPORT_YOY': '%',
        'CN_IMPORTS': '%',
        'CN_IMPORT_YOY': '%',
        'CN_TRADE_BALANCE': '亿美元',

        # 汇率
        'USDCNY': '',
        'USDCNH': '',

        # 股票指数
        '000001.SH': '点',
        '399001.SZ': '点',

        # 期货
        'TS_FUT': '元',
        'T_FUT': '元',
        'AU_FUT': '元/g',
        'CU_FUT': '元/吨',
    }

    @classmethod
    def get_unit_for_indicator(cls, indicator_code: str) -> str:
        """
        获取指标的单位

        Args:
            indicator_code: 指标代码

        Returns:
            str: 单位，如果没有配置则返回空字符串
        """
        return cls.INDICATOR_UNITS.get(indicator_code, "")

    @classmethod
    def get_normalized_unit_and_value(cls, indicator_code: str, value: float) -> tuple[float, str]:
        """
        获取标准化后的单位和值

        对于货币类指标，统一转换为"元"层级

        Args:
            indicator_code: 指标代码
            value: 原始值

        Returns:
            tuple: (转换后的值, 单位)
        """
        from ..domain.entities import normalize_currency_unit

        original_unit = cls.get_unit_for_indicator(indicator_code)

        # 如果是货币类单位，进行转换
        if original_unit in ['万亿元', '亿元', '万元', '万亿美元', '亿美元', '百万美元', '十亿美元']:
            normalized_value, normalized_unit = normalize_currency_unit(value, original_unit)
            return (normalized_value, normalized_unit)

        return (value, original_unit)


class IndicatorService:
    """宏观经济指标服务"""

    # 指标元数据配置
    INDICATOR_METADATA = {
        # 中国制造业PMI
        'CN_PMI_MANUFACTURING': {
            'name': 'PMI (制造业采购经理指数)',
            'name_en': 'Manufacturing PMI',
            'category': '景气',
            'unit': '指数',
            'threshold_bullish': 50,  # 高于此值看多
            'threshold_bearish': 50,  # 低于此值看空
            'description': '反映制造业景气度，50为荣枯线',
        },
        # 中国非制造业PMI
        'CN_PMI_NON_MANUFACTURING': {
            'name': '非制造业PMI',
            'name_en': 'Non-Manufacturing PMI',
            'category': '景气',
            'unit': '指数',
            'threshold_bullish': 50,
            'threshold_bearish': 50,
            'description': '反映服务业景气度，50为荣枯线',
        },
        # CPI
        'CN_CPI_YOY': {
            'name': 'CPI (消费者物价指数同比)',
            'name_en': 'CPI YoY',
            'category': '物价',
            'unit': '%',
            'threshold_bullish': 2.0,
            'threshold_bearish': 3.0,
            'description': '居民消费价格指数同比涨幅',
        },
        'CN_CPI_MOY': {
            'name': 'CPI (消费者物价指数环比)',
            'name_en': 'CPI MoM',
            'category': '物价',
            'unit': '%',
            'description': '居民消费价格指数环比涨幅',
        },
        # PPI
        'CN_PPI_YOY': {
            'name': 'PPI (生产者物价指数同比)',
            'name_en': 'PPI YoY',
            'category': '物价',
            'unit': '%',
            'threshold_bullish': 0,
            'threshold_bearish': -3.0,
            'description': '工业生产者出厂价格指数同比',
        },
        # M2
        'CN_M2_YOY': {
            'name': 'M2 (货币供应量同比)',
            'name_en': 'M2 YoY',
            'category': '货币',
            'unit': '%',
            'threshold_bullish': 8.0,
            'threshold_bearish': 12.0,
            'description': '广义货币供应量同比增速',
        },
        # SHIBOR
        'SHIBOR_O_N': {
            'name': 'SHIBOR隔夜',
            'name_en': 'SHIBOR O/N',
            'category': '利率',
            'unit': '%',
            'threshold_bullish': 2.0,
            'threshold_bearish': 4.0,
            'description': '上海银行间同业拆放利率-隔夜',
        },
        'SHIBOR_1M': {
            'name': 'SHIBOR1月期',
            'name_en': 'SHIBOR 1M',
            'category': '利率',
            'unit': '%',
            'threshold_bullish': 2.5,
            'threshold_bearish': 4.5,
            'description': '上海银行间同业拆放利率-1月期',
        },
        'SHIBOR_1Y': {
            'name': 'SHIBOR1年期',
            'name_en': 'SHIBOR 1Y',
            'category': '利率',
            'unit': '%',
            'description': '上海银行间同业拆放利率-1年期',
        },
        # LPR
        'CN_LPR_1Y': {
            'name': 'LPR(贷款市场报价利率-1年)',
            'name_en': 'LPR 1Y',
            'category': '利率',
            'unit': '%',
            'description': '贷款市场报价利率-1年期',
        },
        'CN_LPR_5Y': {
            'name': 'LPR(贷款市场报价利率-5年)',
            'name_en': 'LPR 5Y',
            'category': '利率',
            'unit': '%',
            'description': '贷款市场报价利率-5年期',
        },
        # GDP
        'CN_GDP_YOY': {
            'name': 'GDP(国内生产总值同比)',
            'name_en': 'GDP YoY',
            'category': '增长',
            'unit': '%',
            'threshold_bullish': 6.0,
            'threshold_bearish': 5.0,
            'description': '国内生产总值同比增速',
        },
        # 社会融资规模
        'CN_SOCIAL_FINANCING_YOY': {
            'name': '社融同比',
            'name_en': 'Social Financing YoY',
            'category': '货币',
            'unit': '%',
            'description': '社会融资规模存量同比增速',
        },
        # 固定资产投资
        'CN_FAI_YOY': {
            'name': '固定资产投资同比',
            'name_en': 'Fixed Asset Investment YoY',
            'category': '投资',
            'unit': '%',
            'threshold_bullish': 5.0,
            'description': '固定资产投资同比增速',
        },
        # 房地产投资
        'CN_REALESTATE_INVESTMENT_YOY': {
            'name': '房地产投资同比',
            'name_en': 'Real Estate Investment YoY',
            'category': '投资',
            'unit': '%',
            'description': '房地产开发投资同比增速',
        },
        # 社会消费品零售
        'CN_RETAIL_SALES_YOY': {
            'name': '社零同比',
            'name_en': 'Retail Sales YoY',
            'category': '消费',
            'unit': '%',
            'threshold_bullish': 5.0,
            'description': '社会消费品零售总额同比',
        },
        # 出口
        'CN_EXPORT_YOY': {
            'name': '出口同比',
            'name_en': 'Export YoY',
            'category': '外贸',
            'unit': '%',
            'description': '出口额同比增速',
        },
        # 进口
        'CN_IMPORT_YOY': {
            'name': '进口同比',
            'name_en': 'Import YoY',
            'category': '外贸',
            'unit': '%',
            'description': '进口额同比增速',
        },
        # 汇率
        'USDCNY': {
            'name': '美元/人民币',
            'name_en': 'USD/CNY',
            'category': '汇率',
            'unit': '',
            'description': '美元兑人民币汇率',
        },
        'USDCNH': {
            'name': '美元/离岸人民币',
            'name_en': 'USD/CNH',
            'category': '汇率',
            'unit': '',
            'description': '美元兑离岸人民币汇率',
        },
        # 股票指数
        '000001.SH': {
            'name': '上证指数',
            'name_en': 'SSE Composite',
            'category': '股票',
            'unit': '点',
            'description': '上海证券交易所综合指数',
        },
        '399001.SZ': {
            'name': '深证成指',
            'name_en': 'SZSE Component',
            'category': '股票',
            'unit': '点',
            'description': '深圳证券交易所成分指数',
        },
        # 国债期货
        'TS_FUT': {
            'name': '2年期国债期货',
            'name_en': '2Y T-Bond Future',
            'category': '期货',
            'unit': '元',
            'description': '2年期国债期货',
        },
        'T_FUT': {
            'name': '10年期国债期货',
            'name_en': '10Y T-Bond Future',
            'category': '期货',
            'unit': '元',
            'description': '10年期国债期货',
        },
        # 商品期货
        'AU_FUT': {
            'name': '黄金期货',
            'name_en': 'Gold Future',
            'category': '期货',
            'unit': '元/g',
            'description': '上海黄金交易所黄金期货',
        },
        'CU_FUT': {
            'name': '铜期货',
            'name_en': 'Copper Future',
            'category': '期货',
            'unit': '元/吨',
            'description': '上海期货交易所铜期货',
        },
    }

    @classmethod
    def get_available_indicators(cls) -> List[Dict]:
        """
        获取所有可用的指标列表

        返回数据库中实际存在数据的指标
        """
        # 获取数据库中存在的指标代码
        distinct_codes = MacroIndicator._default_manager.values_list('code', flat=True).distinct()

        indicators = []
        for code in distinct_codes:
            # 获取最新数据
            latest = MacroIndicator._default_manager.filter(code=code).order_by('-reporting_period').first()

            if not latest:
                continue

            # 获取元数据
            metadata = cls.INDICATOR_METADATA.get(code, {})

            # 转换最新值为展示值
            display_value, display_unit = UnitDisplayService.convert_for_display(
                float(latest.value),
                latest.unit,
                latest.original_unit or metadata.get('unit', '')
            )

            # 获取历史数据统计
            from django.db.models import Avg, Max, Min
            stats = MacroIndicator._default_manager.filter(
                code=code,
                reporting_period__gte=datetime.now().date() - timedelta(days=365)
            ).aggregate(
                avg_value=Avg('value'),
                max_value=Max('value'),
                min_value=Min('value')
            )

            indicators.append({
                'code': code,
                'name': metadata.get('name', code),
                'name_en': metadata.get('name_en', code),
                'category': metadata.get('category', '其他'),
                'unit': display_unit,  # 使用展示单位
                'description': metadata.get('description', ''),
                'latest_value': display_value,  # 使用展示值
                'latest_date': latest.reporting_period.isoformat(),
                'period_type': latest.period_type,
                # 推荐阈值
                'threshold_bullish': metadata.get('threshold_bullish'),
                'threshold_bearish': metadata.get('threshold_bearish'),
                # 历史统计（存储值，用于趋势分析）
                'avg_value': float(stats['avg_value']) if stats['avg_value'] else None,
                'max_value': float(stats['max_value']) if stats['max_value'] else None,
                'min_value': float(stats['min_value']) if stats['min_value'] else None,
            })

        # 按类别和代码排序
        indicators.sort(key=lambda x: (x['category'], x['code']))

        return indicators

    @classmethod
    def get_indicator_by_code(cls, code: str) -> Optional[Dict]:
        """获取单个指标的详细信息"""
        try:
            latest = MacroIndicator._default_manager.filter(code=code).order_by('-reporting_period').first()
            if not latest:
                return None

            metadata = cls.INDICATOR_METADATA.get(code, {})

            # 转换为展示值
            display_value, display_unit = UnitDisplayService.convert_for_display(
                float(latest.value),
                latest.unit,
                latest.original_unit or metadata.get('unit', '')
            )

            return {
                'code': code,
                'name': metadata.get('name', code),
                'name_en': metadata.get('name_en', code),
                'category': metadata.get('category', '其他'),
                'unit': display_unit,  # 使用展示单位
                'description': metadata.get('description', ''),
                'latest_value': display_value,  # 使用展示值
                'latest_date': latest.reporting_period.isoformat(),
                'period_type': latest.period_type,
            }
        except:
            return None

    @classmethod
    def get_indicator_history(cls, code: str, periods: int = 12) -> List[Dict]:
        """获取指标历史数据（返回展示值）"""
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=periods * 35)

        data_points = MacroIndicator._default_manager.filter(
            code=code,
            reporting_period__gte=start_date,
            reporting_period__lte=end_date
        ).order_by('-reporting_period')[:periods]

        # 获取元数据中的单位配置
        metadata = cls.INDICATOR_METADATA.get(code, {})
        default_unit = metadata.get('unit', '')

        return [
            {
                'date': d.reporting_period.isoformat(),
                'value': UnitDisplayService.convert_for_display(
                    float(d.value),
                    d.unit,
                    d.original_unit or default_unit
                )[0],  # 只返回值
                'unit': d.original_unit or default_unit,  # 返回原始单位
                'period_type': d.period_type,
            }
            for d in data_points
        ]


def get_available_indicators_for_frontend() -> List[Dict]:
    """
    获取前端需要的指标列表

    格式简化，用于下拉选择
    """
    indicators = IndicatorService.get_available_indicators()

    return [
        {
            'code': ind['code'],
            'name': ind['name'],
            'category': ind['category'],
            'latest_value': ind['latest_value'],
            'suggested_threshold': ind['threshold_bullish'] or ind['threshold_bearish'] or ind['avg_value'],
        }
        for ind in indicators
    ]

