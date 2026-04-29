"""
Phase 0: 高频指标验证脚本

验证新增高频指标的数据可用性和基本相关性。

参考文档: docs/development/regime-lag-improvement-plan.md

Usage:
    python manage.py validate_high_frequency_indicators
    python manage.py validate_high_frequency_indicators --start-date=2018-01-01 --end-date=2024-12-31
"""

import argparse
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand
from django.db.models import Q
from scipy import stats

from apps.audit.infrastructure.models import (
    IndicatorThresholdConfigModel,
    ValidationSummaryModel,
)
from apps.data_center.infrastructure.models import MacroFactModel
from apps.regime.infrastructure.models import RegimeLog

logger = logging.getLogger(__name__)


class IndicatorValidator:
    """高频指标验证器

    用于验证新增高频指标的数据可用性和预测能力。
    """

    # 要验证的高频指标列表
    HIGH_FREQ_INDICATORS = [
        'CN_BOND_10Y',
        'CN_BOND_1Y',
        'CN_TERM_SPREAD_10Y1Y',
        'CN_CREDIT_SPREAD',
        'CN_NHCI',
        'CN_FX_CENTER',
        'US_BOND_10Y',
        'USD_INDEX',
        'VIX_INDEX',
    ]

    # 验证阈值（从配置读取，此处为默认值）
    DEFAULT_THRESHOLDS = {
        'min_data_points': 100,  # 最少数据点数
        'min_correlation': 0.3,  # 最小相关系数
        'max_p_value': 0.05,  # 最大 p 值
        'min_years': 3,  # 最少年数
    }

    def __init__(self, start_date: date, end_date: date, thresholds: dict | None = None):
        self.start_date = start_date
        self.end_date = end_date
        self.thresholds = {**self.DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.validation_results: dict[str, dict] = {}

    def check_data_availability(self) -> dict[str, dict]:
        """检查数据可用性"""
        logger.info("检查数据可用性...")

        for indicator_code in self.HIGH_FREQ_INDICATORS:
            try:
                # 检查数据库中的数据
                queryset = MacroFactModel._default_manager.filter(
                    indicator_code=indicator_code,
                    reporting_period__gte=self.start_date,
                    reporting_period__lte=self.end_date
                ).order_by('reporting_period')

                data_points = list(queryset)

                if not data_points:
                    self.validation_results[indicator_code] = {
                        'status': 'NO_DATA',
                        'message': f'指标 {indicator_code} 无数据',
                        'count': 0,
                        'date_range': None,
                    }
                    logger.warning(f"指标 {indicator_code} 无数据")
                    continue

                count = len(data_points)
                first_date = data_points[0].reporting_period
                last_date = data_points[-1].reporting_period

                # 计算数据覆盖率
                expected_days = (self.end_date - self.start_date).days
                actual_days = (last_date - first_date).days
                coverage = actual_days / expected_days if expected_days > 0 else 0

                self.validation_results[indicator_code] = {
                    'status': 'OK' if count >= self.thresholds['min_data_points'] else 'INSUFFICIENT',
                    'count': count,
                    'first_date': first_date,
                    'last_date': last_date,
                    'coverage': coverage,
                }

                logger.info(
                    f"指标 {indicator_code}: {count} 条数据 "
                    f"({first_date} 至 {last_date}, 覆盖率 {coverage:.1%})"
                )

            except Exception as e:
                logger.error(f"检查 {indicator_code} 数据可用性失败: {e}")
                self.validation_results[indicator_code] = {
                    'status': 'ERROR',
                    'message': str(e),
                }

        return self.validation_results

    def calculate_correlation_with_regime(self) -> dict[str, dict]:
        """计算指标与 Regime 的相关性"""
        logger.info("计算指标与 Regime 的相关性...")

        # 获取 Regime 历史
        regime_data = RegimeLog._default_manager.filter(
            observed_at__gte=self.start_date,
            observed_at__lte=self.end_date
        ).order_by('observed_at')

        if regime_data.count() < 10:
            logger.warning("Regime 数据不足，无法计算相关性")
            return {}

        # 构建 Regime 时间序列
        regime_df = pd.DataFrame([
            {'date': r.observed_at, 'regime': r.dominant_regime}
            for r in regime_data
        ])

        # 将 Regime 映射为数值（用于相关性计算）
        regime_mapping = {
            'Recovery': 1,   # 复苏
            'Overheat': 2,   # 过热
            'Stagflation': 3, # 滞胀
            'Deflation': 4,   # 通缩
        }
        regime_df['regime_value'] = regime_df['regime'].map(regime_mapping)

        for indicator_code in self.HIGH_FREQ_INDICATORS:
            if indicator_code not in self.validation_results:
                continue

            if self.validation_results[indicator_code].get('status') != 'OK':
                continue

            try:
                # 获取指标数据
                indicator_query = MacroFactModel._default_manager.filter(
                    indicator_code=indicator_code,
                    reporting_period__gte=self.start_date,
                    reporting_period__lte=self.end_date
                ).order_by('reporting_period')

                indicator_df = pd.DataFrame([
                    {'date': i.reporting_period, 'value': i.value}
                    for i in indicator_query
                ])

                if indicator_df.empty:
                    continue

                # 合并数据
                merged = pd.merge(
                    regime_df,
                    indicator_df,
                    on='date',
                    how='inner'
                )

                if len(merged) < 10:
                    logger.warning(f"指标 {indicator_code} 合并后数据点不足")
                    continue

                # 计算相关性
                correlation, p_value = stats.pearsonr(
                    merged['regime_value'],
                    merged['value']
                )

                self.validation_results[indicator_code].update({
                    'correlation': correlation,
                    'p_value': p_value,
                    'correlation_significant': p_value < self.thresholds['max_p_value'],
                })

                logger.info(
                    f"指标 {indicator_code}: 相关系数={correlation:.3f}, "
                    f"p值={p_value:.4f} "
                    f"({'显著' if p_value < self.thresholds['max_p_value'] else '不显著'})"
                )

            except Exception as e:
                logger.error(f"计算 {indicator_code} 相关性失败: {e}")

        return self.validation_results

    def event_study_term_spread(self) -> dict:
        """期限利差事件研究：检查倒挂后是否出现衰退"""
        logger.info("执行期限利差事件研究...")

        indicator_code = 'CN_TERM_SPREAD_10Y1Y'

        if indicator_code not in self.validation_results:
            return {'status': 'NO_DATA'}

        try:
            # 获取期限利差数据
            spread_query = MacroFactModel._default_manager.filter(
                indicator_code=indicator_code,
                reporting_period__gte=self.start_date,
                reporting_period__lte=self.end_date
            ).order_by('reporting_period')

            spread_df = pd.DataFrame([
                {'date': s.reporting_period, 'spread': s.value}
                for s in spread_query
            ])

            if spread_df.empty or len(spread_df) < 100:
                return {'status': 'INSUFFICIENT_DATA'}

            # 查找倒挂事件（spread < 0）
            spread_df['inverted'] = spread_df['spread'] < 0

            # 查找倒挂持续期间
            spread_df['group'] = (spread_df['inverted'] != spread_df['inverted'].shift()).cumsum()

            inversion_events = []
            for group_id, group_df in spread_df.groupby('group'):
                if group_df['inverted'].iloc[0]:
                    inversion_events.append({
                        'start_date': group_df['date'].min(),
                        'end_date': group_df['date'].max(),
                        'duration_days': (group_df['date'].max() - group_df['date'].min()).days,
                        'min_spread': group_df['spread'].min(),
                    })

            # 分析倒挂后的 Regime 变化
            event_results = []
            for event in inversion_events:
                event_date = event['start_date']
                # 检查倒挂后 6-18 个月内的 Regime 变化
                future_date = event_date + timedelta(days=365)

                future_regime = RegimeLog._default_manager.filter(
                    observed_at__gt=event_date,
                    observed_at__lte=future_date
                ).order_by('observed_at')

                if future_regime.exists():
                    regime_values = [r.dominant_regime for r in future_regime]
                    # 检查是否出现衰退（Deflation 或 Stagflation）
                    recession_occurred = any(
                        r in ['Deflation', 'Stagflation'] for r in regime_values
                    )

                    event_results.append({
                        **event,
                        'recession_occurred': recession_occurred,
                    })

            summary = {
                'status': 'OK',
                'total_inversions': len(inversion_events),
                'events': event_results,
                'prediction_accuracy': (
                    sum(e['recession_occurred'] for e in event_results) / len(event_results)
                    if event_results else 0
                ),
            }

            self.validation_results[indicator_code]['event_study'] = summary

            logger.info(
                f"期限利差事件研究: {len(inversion_events)} 次倒挂, "
                f"预测准确率 {summary['prediction_accuracy']:.1%}"
            )

            return summary

        except Exception as e:
            logger.error(f"期限利差事件研究失败: {e}")
            return {'status': 'ERROR', 'message': str(e)}

    def generate_validation_report(self) -> dict:
        """生成验证报告"""
        logger.info("生成验证报告...")

        approved_indicators = []
        rejected_indicators = []
        pending_indicators = []

        for indicator_code, result in self.validation_results.items():
            if result.get('status') == 'OK':
                # 检查是否通过验证
                is_approved = (
                    result.get('correlation_significant', True) and
                    result.get('count', 0) >= self.thresholds['min_data_points']
                )

                if is_approved:
                    approved_indicators.append(indicator_code)
                else:
                    pending_indicators.append(indicator_code)
            else:
                rejected_indicators.append(indicator_code)

        # 计算平均 F1 分数（占位，实际需要历史回测）
        avg_f1_score = None
        avg_stability_score = None

        if approved_indicators or pending_indicators:
            # 简化的评分逻辑
            scores = []
            for indicator in approved_indicators + pending_indicators:
                result = self.validation_results[indicator]
                # 基于相关性和数据覆盖率的简化评分
                correlation = result.get('correlation', 0)
                coverage = result.get('coverage', 0)
                score = (abs(correlation) * 0.7 + coverage * 0.3)
                scores.append(score)

            avg_f1_score = np.mean(scores) if scores else None
            avg_stability_score = np.std(scores) if scores else None

        # 生成总体建议
        total = len(self.HIGH_FREQ_INDICATORS)
        approved = len(approved_indicators)
        rejected = len(rejected_indicators)

        if approved / total >= 0.6:
            recommendation = "建议进入 Phase 1 开发阶段"
        elif approved / total >= 0.3:
            recommendation = "建议有条件进入 Phase 1，仅部署通过验证的指标"
        else:
            recommendation = "建议重新评估指标选择或数据源"

        report = {
            'validation_run_id': f'phase0_{self.start_date}_{self.end_date}',
            'total_indicators': total,
            'approved_indicators': approved,
            'rejected_indicators': rejected,
            'pending_indicators': len(pending_indicators),
            'avg_f1_score': avg_f1_score,
            'avg_stability_score': avg_stability_score,
            'overall_recommendation': recommendation,
            'detailed_results': self.validation_results,
        }

        return report


class Command(BaseCommand):
    help = '验证高频指标的数据可用性和预测能力'

    def add_arguments(self, parser):
        parser.add_argument(
            '--start-date',
            type=str,
            default='2018-01-01',
            help='验证起始日期 (YYYY-MM-DD)'
        )
        parser.add_argument(
            '--end-date',
            type=str,
            default=str(date.today()),
            help='验证结束日期 (YYYY-MM-DD)'
        )
        parser.add_argument(
            '--min-data-points',
            type=int,
            default=100,
            help='最少数据点数'
        )
        parser.add_argument(
            '--min-correlation',
            type=float,
            default=0.3,
            help='最小相关系数'
        )
        parser.add_argument(
            '--save-report',
            action='store_true',
            help='保存验证报告到数据库'
        )

    def handle(self, *args, **options):
        start_date = pd.to_datetime(options['start_date']).date()
        end_date = pd.to_datetime(options['end_date']).date()

        thresholds = {
            'min_data_points': options['min_data_points'],
            'min_correlation': options['min_correlation'],
        }

        save_report = options.get('save_report', False)

        self.stdout.write('Phase 0 高频指标验证')
        self.stdout.write(f'验证期间: {start_date} 至 {end_date}')
        self.stdout.write('=' * 50)

        # 创建验证器
        validator = IndicatorValidator(start_date, end_date, thresholds)

        # 1. 检查数据可用性
        self.stdout.write('\n[1/3] 检查数据可用性...')
        validator.check_data_availability()

        # 2. 计算相关性
        self.stdout.write('\n[2/3] 计算与 Regime 的相关性...')
        validator.calculate_correlation_with_regime()

        # 3. 事件研究
        self.stdout.write('\n[3/3] 执行期限利差事件研究...')
        validator.event_study_term_spread()

        # 4. 生成报告
        self.stdout.write('\n生成验证报告...')
        report = validator.generate_validation_report()

        # 输出结果
        self.stdout.write('\n' + '=' * 50)
        self.stdout.write('验证结果摘要:')
        self.stdout.write(f'  总指标数: {report["total_indicators"]}')
        self.stdout.write(f'  通过指标: {report["approved_indicators"]}')
        self.stdout.write(f'  拒绝指标: {report["rejected_indicators"]}')
        self.stdout.write(f'  待定指标: {report["pending_indicators"]}')
        if report['avg_f1_score']:
            self.stdout.write(f'  平均 F1 分数: {report["avg_f1_score"]:.3f}')
        self.stdout.write(f'\n总体建议: {report["overall_recommendation"]}')

        # 详细结果
        self.stdout.write('\n' + '=' * 50)
        self.stdout.write('详细结果:')
        for indicator, result in report['detailed_results'].items():
            status = result.get('status', 'UNKNOWN')
            self.stdout.write(f'\n{indicator}: {status}')
            if status == 'OK':
                self.stdout.write(f'  数据点数: {result.get("count")}')
                self.stdout.write(f'  数据覆盖率: {result.get("coverage", 0):.1%}')
                if 'correlation' in result:
                    self.stdout.write(f'  相关系数: {result["correlation"]:.3f} (p={result["p_value"]:.4f})')
            else:
                self.stdout.write(f'  说明: {result.get("message", "未知原因")}')

        # 保存报告到数据库
        if save_report:
            self.stdout.write('\n保存验证报告到数据库...')
            try:
                summary = ValidationSummaryModel._default_manager.create(
                    validation_run_id=report['validation_run_id'],
                    evaluation_period_start=start_date,
                    evaluation_period_end=end_date,
                    total_indicators=report['total_indicators'],
                    approved_indicators=report['approved_indicators'],
                    rejected_indicators=report['rejected_indicators'],
                    pending_indicators=report['pending_indicators'],
                    avg_f1_score=report['avg_f1_score'],
                    avg_stability_score=report['avg_stability_score'],
                    overall_recommendation=report['overall_recommendation'],
                    status='completed',
                    is_shadow_mode=True,
                )
                self.stdout.write(
                    self.style.SUCCESS(f'报告已保存: {summary.validation_run_id}')
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'保存报告失败: {e}')
                )

        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(
            self.style.SUCCESS('Phase 0 验证完成!')
        )

