"""
宏观经济指标服务

提供指标查询、元数据获取等功能
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
from apps.macro.infrastructure.models import MacroIndicator


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
        distinct_codes = MacroIndicator.objects.values_list('code', flat=True).distinct()

        indicators = []
        for code in distinct_codes:
            # 获取最新数据
            latest = MacroIndicator.objects.filter(code=code).order_by('-reporting_period').first()

            if not latest:
                continue

            # 获取元数据
            metadata = cls.INDICATOR_METADATA.get(code, {})

            # 获取历史数据统计
            from django.db.models import Avg, Max, Min
            stats = MacroIndicator.objects.filter(
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
                'unit': metadata.get('unit', ''),
                'description': metadata.get('description', ''),
                'latest_value': float(latest.value),
                'latest_date': latest.reporting_period.isoformat(),
                'period_type': latest.period_type,
                # 推荐阈值
                'threshold_bullish': metadata.get('threshold_bullish'),
                'threshold_bearish': metadata.get('threshold_bearish'),
                # 历史统计
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
            latest = MacroIndicator.objects.filter(code=code).order_by('-reporting_period').first()
            if not latest:
                return None

            metadata = cls.INDICATOR_METADATA.get(code, {})

            return {
                'code': code,
                'name': metadata.get('name', code),
                'name_en': metadata.get('name_en', code),
                'category': metadata.get('category', '其他'),
                'unit': metadata.get('unit', ''),
                'description': metadata.get('description', ''),
                'latest_value': float(latest.value),
                'latest_date': latest.reporting_period.isoformat(),
                'period_type': latest.period_type,
            }
        except:
            return None

    @classmethod
    def get_indicator_history(cls, code: str, periods: int = 12) -> List[Dict]:
        """获取指标历史数据"""
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=periods * 35)

        data_points = MacroIndicator.objects.filter(
            code=code,
            reporting_period__gte=start_date,
            reporting_period__lte=end_date
        ).order_by('-reporting_period')[:periods]

        return [
            {
                'date': d.reporting_period.isoformat(),
                'value': float(d.value),
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
