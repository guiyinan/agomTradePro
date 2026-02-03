"""
Initialize Indicator Threshold Configurations.

This command initializes the default threshold configurations for macro indicators.
All thresholds are stored in the database (no hard-coding).

Usage:
    python manage.py init_indicator_thresholds
    python manage.py init_indicator_thresholds --refresh
"""

from django.core.management.base import BaseCommand
from apps.audit.infrastructure.models import IndicatorThresholdConfigModel


class Command(BaseCommand):
    help = 'Initialize default indicator threshold configurations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--refresh',
            action='store_true',
            dest='refresh',
            help='Refresh existing configurations (update instead of skip)',
        )

    def handle(self, *args, **options):
        refresh = options.get('refresh', False)

        # 默认指标阈值配置
        default_configs = [
            # ============ 增长类指标 ============
            {
                'indicator_code': 'PMI',
                'indicator_name': '制造业采购经理指数',
                'category': 'growth',
                'level_low': 50.0,
                'level_high': 50.0,
                'base_weight': 1.0,
                'description': 'PMI > 50 表示经济扩张，< 50 表示收缩',
            },
            {
                'indicator_code': 'CN_GDP',
                'indicator_name': '国内生产总值',
                'category': 'growth',
                'level_low': 6.0,
                'level_high': 7.0,
                'base_weight': 0.8,
                'description': 'GDP 增长率阈值',
            },
            {
                'indicator_code': 'CN_IND_PROD',
                'indicator_name': '工业增加值',
                'category': 'growth',
                'level_low': 5.0,
                'level_high': 7.0,
                'base_weight': 0.7,
                'description': '工业增加值同比增长率',
            },
            {
                'indicator_code': 'CN_RETAIL_SALES',
                'indicator_name': '社会消费品零售总额',
                'category': 'growth',
                'level_low': 8.0,
                'level_high': 10.0,
                'base_weight': 0.6,
                'description': '消费增长率',
            },
            {
                'indicator_code': 'CN_FIXED_INVEST',
                'indicator_name': '固定资产投资',
                'category': 'growth',
                'level_low': 5.0,
                'level_high': 8.0,
                'base_weight': 0.6,
                'description': '固定资产投资增长率',
            },
            {
                'indicator_code': 'CN_EXPORT_YOY',
                'indicator_name': '出口同比',
                'category': 'growth',
                'level_low': 0.0,
                'level_high': 5.0,
                'base_weight': 0.5,
                'description': '出口同比增长率',
            },
            {
                'indicator_code': 'CN_IMPORT_YOY',
                'indicator_name': '进口同比',
                'category': 'growth',
                'level_low': 0.0,
                'level_high': 5.0,
                'base_weight': 0.5,
                'description': '进口同比增长率',
            },

            # ============ 通胀类指标 ============
            {
                'indicator_code': 'CPI',
                'indicator_name': '居民消费价格指数',
                'category': 'inflation',
                'level_low': 1.0,
                'level_high': 2.0,
                'base_weight': 1.0,
                'description': 'CPI 同比，<1% 通缩，>2% 通胀',
            },
            {
                'indicator_code': 'PPI',
                'indicator_name': '工业生产者出厂价格指数',
                'category': 'inflation',
                'level_low': 0.0,
                'level_high': 2.0,
                'base_weight': 0.8,
                'description': 'PPI 同比',
            },
            {
                'indicator_code': 'CPI_CORE',
                'indicator_name': '核心CPI',
                'category': 'inflation',
                'level_low': 1.0,
                'level_high': 1.5,
                'base_weight': 0.7,
                'description': '核心CPI（剔除食品能源）',
            },
            {
                'indicator_code': 'PPIRM',
                'indicator_name': '工业生产者购进价格指数',
                'category': 'inflation',
                'level_low': 0.0,
                'level_high': 2.0,
                'base_weight': 0.6,
                'description': '购进价格指数',
            },

            # ============ 货币类指标 ============
            {
                'indicator_code': 'M2',
                'indicator_name': 'M2货币供应',
                'category': 'money',
                'level_low': 8.0,
                'level_high': 10.0,
                'base_weight': 0.8,
                'description': 'M2 同比增长率',
            },
            {
                'indicator_code': 'M1',
                'indicator_name': 'M1货币供应',
                'category': 'money',
                'level_low': 5.0,
                'level_high': 10.0,
                'base_weight': 0.7,
                'description': 'M1 同比增长率',
            },
            {
                'indicator_code': 'M0',
                'indicator_name': 'M0货币供应',
                'category': 'money',
                'level_low': 3.0,
                'level_high': 8.0,
                'base_weight': 0.5,
                'description': 'M0 同比增长率',
            },
            {
                'indicator_code': 'SOCIAL_FINANCING',
                'indicator_name': '社会融资规模',
                'category': 'money',
                'level_low': 20000.0,
                'level_high': 35000.0,
                'base_weight': 0.7,
                'description': '月度社会融资规模（亿元）',
            },
            {
                'indicator_code': 'NEW_LOANS',
                'indicator_name': '新增人民币贷款',
                'category': 'money',
                'level_low': 10000.0,
                'level_high': 20000.0,
                'base_weight': 0.6,
                'description': '月度新增贷款（亿元）',
            },

            # ============ 利率类指标 ============
            {
                'indicator_code': 'SHIBOR_ON',
                'indicator_name': 'Shibor隔夜',
                'category': 'interest_rate',
                'level_low': 1.5,
                'level_high': 3.0,
                'base_weight': 0.6,
                'description': 'Shibor 隔夜利率',
            },
            {
                'indicator_code': 'SHIBOR_1W',
                'indicator_name': 'Shibor1周',
                'category': 'interest_rate',
                'level_low': 2.0,
                'level_high': 3.5,
                'base_weight': 0.6,
                'description': 'Shibor 1周利率',
            },
            {
                'indicator_code': 'LPR_1Y',
                'indicator_name': '1年期LPR',
                'category': 'interest_rate',
                'level_low': 3.5,
                'level_high': 4.5,
                'base_weight': 0.7,
                'description': '1年期贷款市场报价利率',
            },
            {
                'indicator_code': 'LPR_5Y',
                'indicator_name': '5年期LPR',
                'category': 'interest_rate',
                'level_low': 4.0,
                'level_high': 5.0,
                'base_weight': 0.7,
                'description': '5年期贷款市场报价利率',
            },
            {
                'indicator_code': 'DR007',
                'indicator_name': 'DR007',
                'category': 'interest_rate',
                'level_low': 1.5,
                'level_high': 3.0,
                'base_weight': 0.6,
                'description': '银行间存款类机构7天质押式回购利率',
            },

            # ============ 情绪类指标 ============
            {
                'indicator_code': 'HS300',
                'indicator_name': '沪深300指数',
                'category': 'sentiment',
                'level_low': 3500.0,
                'level_high': 4500.0,
                'base_weight': 0.5,
                'description': '沪深300指数点位',
            },
            {
                'indicator_code': 'SCI',
                'indicator_name': '上证综指',
                'category': 'sentiment',
                'level_low': 2800.0,
                'level_high': 3500.0,
                'base_weight': 0.5,
                'description': '上证综指点位',
            },
            {
                'indicator_code': 'VOL_INDEX',
                'indicator_name': '波动率指数',
                'category': 'sentiment',
                'level_low': 15.0,
                'level_high': 25.0,
                'base_weight': 0.4,
                'description': '市场波动率指数',
            },

            # ============ 高频日度指标（Regime 滞后性改进方案 Phase 1）============
            {
                'indicator_code': 'CN_BOND_10Y',
                'indicator_name': '10年期国债收益率',
                'category': 'high_freq_bond',
                'level_low': 2.5,
                'level_high': 3.5,
                'base_weight': 1.0,
                'description': '10年期国债收益率，无风险利率，长期增长预期',
            },
            {
                'indicator_code': 'CN_BOND_5Y',
                'indicator_name': '5年期国债收益率',
                'category': 'high_freq_bond',
                'level_low': 2.0,
                'level_high': 3.0,
                'base_weight': 0.8,
                'description': '5年期国债收益率',
            },
            {
                'indicator_code': 'CN_BOND_2Y',
                'indicator_name': '2年期国债收益率',
                'category': 'high_freq_bond',
                'level_low': 1.8,
                'level_high': 2.8,
                'base_weight': 0.7,
                'description': '2年期国债收益率',
            },
            {
                'indicator_code': 'CN_BOND_1Y',
                'indicator_name': '1年期国债收益率',
                'category': 'high_freq_bond',
                'level_low': 1.5,
                'level_high': 2.5,
                'base_weight': 0.9,
                'description': '1年期国债收益率，短端利率，货币政策',
            },
            {
                'indicator_code': 'CN_TERM_SPREAD_10Y1Y',
                'indicator_name': '期限利差(10Y-1Y)',
                'category': 'high_freq_spread',
                'level_low': 0.0,
                'level_high': 0.8,
                'base_weight': 1.0,
                'description': '期限利差（10年期-1年期），收益率曲线，衰退预警指标',
            },
            {
                'indicator_code': 'CN_TERM_SPREAD_10Y2Y',
                'indicator_name': '期限利差(10Y-2Y)',
                'category': 'high_freq_spread',
                'level_low': 0.0,
                'level_high': 0.6,
                'base_weight': 0.8,
                'description': '期限利差（10年期-2年期）',
            },
            {
                'indicator_code': 'CN_CORP_YIELD_AAA',
                'indicator_name': 'AAA级企业债收益率',
                'category': 'high_freq_credit',
                'level_low': 3.0,
                'level_high': 4.5,
                'base_weight': 0.8,
                'description': 'AAA级企业债收益率（10年期）',
            },
            {
                'indicator_code': 'CN_CORP_YIELD_AA',
                'indicator_name': 'AA级企业债收益率',
                'category': 'high_freq_credit',
                'level_low': 3.5,
                'level_high': 5.5,
                'base_weight': 0.8,
                'description': 'AA级企业债收益率（10年期）',
            },
            {
                'indicator_code': 'CN_CREDIT_SPREAD',
                'indicator_name': '信用利差(AA-AAA)',
                'category': 'high_freq_spread',
                'level_low': 0.5,
                'level_high': 2.0,
                'base_weight': 1.0,
                'description': '信用利差（AA-AAA），金融压力实时指标，单位：BP（百分点*100）',
            },
            {
                'indicator_code': 'CN_NHCI',
                'indicator_name': '南华商品指数',
                'category': 'high_freq_commodity',
                'level_low': 1500.0,
                'level_high': 2500.0,
                'base_weight': 0.8,
                'description': '南华商品指数，工业品通胀，实体经济需求指标',
            },
            {
                'indicator_code': 'CN_FX_CENTER',
                'indicator_name': '人民币中间价',
                'category': 'high_freq_fx',
                'level_low': 6.5,
                'level_high': 7.3,
                'base_weight': 0.7,
                'description': '美元兑人民币中间价，汇率压力，资本流动',
            },
            {
                'indicator_code': 'US_BOND_10Y',
                'indicator_name': '美国10年期国债',
                'category': 'high_freq_global',
                'level_low': 2.0,
                'level_high': 5.0,
                'base_weight': 0.7,
                'description': '美国10年期国债收益率，全球定价锚',
            },
            {
                'indicator_code': 'USD_INDEX',
                'indicator_name': '美元指数',
                'category': 'high_freq_global',
                'level_low': 95.0,
                'level_high': 110.0,
                'base_weight': 0.6,
                'description': '美元指数，新兴市场压力',
            },
            {
                'indicator_code': 'VIX_INDEX',
                'indicator_name': 'VIX波动率指数',
                'category': 'high_freq_global',
                'level_low': 12.0,
                'level_high': 25.0,
                'base_weight': 0.5,
                'description': 'VIX波动率指数，全球风险偏好',
            },
            # ============ 周度指标（Regime 滞后性改进 Phase 2）============
            {
                'indicator_code': 'CN_POWER_GEN',
                'indicator_name': '发电量',
                'category': 'weekly_industrial',
                'level_low': 5000.0,
                'level_high': 8000.0,
                'base_weight': 0.9,
                'description': '发电量（周度），实时工业活动指标，单位：亿千瓦时',
            },
            {
                'indicator_code': 'CN_BLAST_FURNACE',
                'indicator_name': '高炉开工率',
                'category': 'weekly_industrial',
                'level_low': 45.0,
                'level_high': 75.0,
                'base_weight': 0.85,
                'description': '高炉开工率（周度），钢铁需求指标，单位：%',
            },
            {
                'indicator_code': 'CN_CCFI',
                'indicator_name': '集装箱运价指数(CCFI)',
                'category': 'weekly_trade',
                'level_low': 800.0,
                'level_high': 1500.0,
                'base_weight': 0.7,
                'description': '中国出口集装箱运价指数（周度），外贸活跃度，单位：点',
            },
            {
                'indicator_code': 'CN_SCFI',
                'indicator_name': '上海出口运价指数(SCFI)',
                'category': 'weekly_trade',
                'level_low': 900.0,
                'level_high': 2500.0,
                'base_weight': 0.7,
                'description': '上海出口集装箱运价指数（周度），出口市场短期波动，单位：点',
            },
            # ============ PMI 分项指标（Regime 滞后性改进 Phase 3）============
            {
                'indicator_code': 'CN_PMI_NEW_ORDER',
                'indicator_name': 'PMI新订单指数',
                'category': 'pmi_subitem',
                'level_low': 48.0,
                'level_high': 52.0,
                'base_weight': 1.0,
                'description': 'PMI新订单指数（月度），需求先行指标，领先整体经济1-2个月，单位：指数',
            },
            {
                'indicator_code': 'CN_PMI_INVENTORY',
                'indicator_name': 'PMI产成品库存指数',
                'category': 'pmi_subitem',
                'level_low': 46.0,
                'level_high': 50.0,
                'base_weight': 0.8,
                'description': 'PMI产成品库存指数（月度），去库/补库周期指标，单位：指数',
            },
            {
                'indicator_code': 'CN_PMI_RAW_MAT',
                'indicator_name': 'PMI原材料库存指数',
                'category': 'pmi_subitem',
                'level_low': 47.0,
                'level_high': 51.0,
                'base_weight': 0.7,
                'description': 'PMI原材料库存指数（月度），采购意愿指标，单位：指数',
            },
            {
                'indicator_code': 'CN_PMI_PURCHASE',
                'indicator_name': 'PMI采购量指数',
                'category': 'pmi_subitem',
                'level_low': 48.0,
                'level_high': 52.0,
                'base_weight': 0.8,
                'description': 'PMI采购量指数（月度），生产预期指标，单位：指数',
            },
            {
                'indicator_code': 'CN_PMI_PRODUCTION',
                'indicator_name': 'PMI生产指数',
                'category': 'pmi_subitem',
                'level_low': 49.0,
                'level_high': 53.0,
                'base_weight': 0.9,
                'description': 'PMI生产指数（月度），生产活动活跃度，单位：指数',
            },
            {
                'indicator_code': 'CN_PMI_EMPLOYMENT',
                'indicator_name': 'PMI从业人员指数',
                'category': 'pmi_subitem',
                'level_low': 47.0,
                'level_high': 51.0,
                'base_weight': 0.6,
                'description': 'PMI从业人员指数（月度），就业状况指标，单位：指数',
            },
        ]

        # 分段验证配置（用于稳定性分析）
        default_validation_periods = [
            {
                'name': '刚兑时期',
                'start': '2005-01-01',
                'end': '2017-12-31',
                'description': '刚性兑付时期，利率双轨制'
            },
            {
                'name': '破刚兑时期',
                'start': '2018-01-01',
                'end': '2024-12-31',
                'description': '打破刚兑后，利率市场化'
            },
        ]

        # 默认行为阈值
        default_action_thresholds = {
            'keep_min_f1': 0.6,
            'reduce_min_f1': 0.4,
            'remove_max_f1': 0.3,
        }

        created_count = 0
        updated_count = 0
        skipped_count = 0

        for config_data in default_configs:
            indicator_code = config_data['indicator_code']

            try:
                existing = IndicatorThresholdConfigModel.objects.get(
                    indicator_code=indicator_code
                )

                if refresh:
                    # 更新现有配置
                    for key, value in config_data.items():
                        if key not in ['indicator_code', 'indicator_name']:
                            setattr(existing, key, value)
                    existing.action_thresholds = default_action_thresholds
                    existing.validation_periods = default_validation_periods
                    existing.save()
                    updated_count += 1
                    self.stdout.write(
                        self.style.WARNING(f'Updated: {indicator_code}')
                    )
                else:
                    skipped_count += 1
                    self.stdout.write(
                        self.style.WARNING(f'Skipped (exists): {indicator_code}')
                    )

            except IndicatorThresholdConfigModel.DoesNotExist:
                # 创建新配置
                config_data['action_thresholds'] = default_action_thresholds
                config_data['validation_periods'] = default_validation_periods
                IndicatorThresholdConfigModel.objects.create(**config_data)
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Created: {indicator_code}')
                )

        # 输出摘要
        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(f'Created: {created_count} configurations')
        self.stdout.write(f'Updated: {updated_count} configurations')
        self.stdout.write(f'Skipped: {skipped_count} configurations')
        self.stdout.write('=' * 50)

        if refresh:
            self.stdout.write(
                self.style.SUCCESS('Indicator threshold configurations refreshed successfully.')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS('Indicator threshold configurations initialized successfully.')
            )
        self.stdout.write('Run "python manage.py init_indicator_thresholds --refresh" to update existing configs.')
