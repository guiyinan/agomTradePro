"""
Repositories for Macro Data.

Infrastructure layer implementation using Django ORM.
"""

from datetime import date, datetime
from typing import List, Optional, Dict

from django.db import transaction
from django.db.models import Max, Q

from ..domain.entities import MacroIndicator, PeriodType
from .models import MacroIndicator as MacroIndicatorORM


class MacroRepositoryError(Exception):
    """数据仓储异常"""
    pass


class DjangoMacroRepository:
    """
    Django ORM 实现的宏观数据仓储

    提供宏观数据的增删改查操作。
    """

    # 增长指标代码映射
    GROWTH_INDICATORS = {
        "PMI": "CN_PMI",
        "工业增加值": "CN_VALUE_ADDED",
        "社会消费品零售": "CN_RETAIL_SALES",
    }

    # 通胀指标代码映射
    # 注意：CPI 需要使用同比增长率（百分比形式），而非指数形式
    # CN_CPI: 指数形式（上年同月=100），值如 100.8
    # CN_CPI_NATIONAL_YOY: 同比增长率（百分比），值如 0.008（即 0.8%）
    INFLATION_INDICATORS = {
        # 线上历史数据常见只有 CN_CPI（指数形式，上年同月=100）。
        # 为保证 Regime 面板可用，默认先使用 CN_CPI。
        # 若库中有 CN_CPI_NATIONAL_YOY，可在后续切回同比口径。
        "CPI": "CN_CPI",
        "PPI": "CN_PPI",
        "GDP平减指数": "CN_GDP_DEFLATOR",
    }

    def __init__(self):
        self._model = MacroIndicatorORM

    def save_indicator(
        self,
        indicator: MacroIndicator,
        revision_number: int = 1,
        period_type_override: Optional[str] = None
    ) -> MacroIndicator:
        """
        保存单个指标

        Args:
            indicator: 指标实体
            revision_number: 修订版本号
            period_type_override: 覆盖 period_type 值（用于 ORM 层存储扩展类型如 10Y）

        Returns:
            MacroIndicator: 保存后的指标
        """
        # 获取 period_type 值（使用 override 或从 entity 获取）
        if period_type_override:
            period_type_value = period_type_override
        else:
            period_type_value = (
                indicator.period_type.value if isinstance(indicator.period_type, PeriodType)
                else indicator.period_type
            )

        # 检查是否已存在
        existing = self._model.objects.filter(
            code=indicator.code,
            reporting_period=indicator.reporting_period,
            revision_number=revision_number
        ).first()

        if existing:
            # 更新
            existing.value = indicator.value
            existing.published_at = indicator.published_at
            existing.source = indicator.source
            # 使用 period_type_value（可能包含 override）
            existing.period_type = period_type_value
            existing.unit = indicator.unit
            existing.original_unit = indicator.original_unit
            existing.save()
            orm_obj = existing
        else:
            # 新建
            orm_obj = self._model.objects.create(
                code=indicator.code,
                value=indicator.value,
                reporting_period=indicator.reporting_period,
                period_type=period_type_value,
                unit=indicator.unit,
                original_unit=indicator.original_unit,
                published_at=indicator.published_at,
                source=indicator.source,
                revision_number=revision_number
            )

        return self._orm_to_entity(orm_obj)

    def save_indicators_batch(
        self,
        indicators: List[MacroIndicator],
        revision_number: int = 1
    ) -> List[MacroIndicator]:
        """
        批量保存指标

        Args:
            indicators: 指标实体列表
            revision_number: 修订版本号

        Returns:
            List[MacroIndicator]: 保存后的指标列表
        """
        results = []
        with transaction.atomic():
            for indicator in indicators:
                results.append(self.save_indicator(indicator, revision_number))
        return results

    def get_by_code_and_date(
        self,
        code: str,
        observed_at: date,
        revision_number: Optional[int] = None
    ) -> Optional[MacroIndicator]:
        """
        按代码和日期查询指标

        Args:
            code: 指标代码
            observed_at: 观测日期（兼容旧 API，实际使用 reporting_period）
            revision_number: 修订版本号（None 表示最新版本）

        Returns:
            Optional[MacroIndicator]: 指标实体，不存在则返回 None
        """
        query = self._model.objects.filter(
            code=code,
            reporting_period=observed_at
        )

        if revision_number is not None:
            query = query.filter(revision_number=revision_number)
        else:
            # 获取最新修订版本
            max_rev = query.aggregate(max_rev=Max('revision_number'))['max_rev']
            if max_rev is not None:
                query = query.filter(revision_number=max_rev)

        orm_obj = query.first()
        if orm_obj:
            return self._orm_to_entity(orm_obj)
        return None

    def get_series(
        self,
        code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        use_pit: bool = False,
        source: Optional[str] = None
    ) -> List[MacroIndicator]:
        """
        获取指定指标的时序数据

        Args:
            code: 指标代码
            start_date: 起始日期（包含）
            end_date: 结束日期（包含）
            use_pit: 是否使用 Point-in-Time 模式（考虑发布延迟）
            source: 数据源过滤（akshare, tushare 等，None 表示不限）

        Returns:
            List[MacroIndicator]: 按时间排序的指标列表
        """
        query = self._model.objects.filter(code=code)

        if start_date:
            query = query.filter(reporting_period__gte=start_date)
        if end_date:
            query = query.filter(reporting_period__lte=end_date)
        if source:
            query = query.filter(source=source)

        if use_pit:
            # 获取每个观测日期的最新修订版本
            # 先获取所有 (reporting_period, max_revision_number)
            subquery = self._model.objects.filter(
                code=code
            ).values('reporting_period').annotate(
                max_rev=Max('revision_number')
            )

            conditions = Q()
            for item in subquery:
                conditions |= Q(
                    reporting_period=item['reporting_period'],
                    revision_number=item['max_rev']
                )
            query = query.filter(conditions)

        query = query.order_by('reporting_period')

        return [self._orm_to_entity(obj) for obj in query]

    def get_growth_series(
        self,
        indicator_code: str = "PMI",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        use_pit: bool = False,
        source: Optional[str] = None
    ) -> List[float]:
        """
        获取增长指标序列（用于 Regime 计算）

        Args:
            indicator_code: 指标代码（PMI, 工业增加值, 等）
            start_date: 起始日期
            end_date: 结束日期
            use_pit: 是否使用 Point-in-Time 模式
            source: 数据源过滤

        Returns:
            List[float]: 指标值列表
        """
        # 映射指标代码
        code = self.GROWTH_INDICATORS.get(indicator_code, indicator_code)
        indicators = self.get_series(code, start_date, end_date, use_pit, source)
        return [ind.value for ind in indicators]

    def get_growth_series_full(
        self,
        indicator_code: str = "PMI",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        use_pit: bool = False,
        source: Optional[str] = None
    ) -> List[MacroIndicator]:
        """
        获取增长指标完整序列（包含日期等元数据）

        Args:
            indicator_code: 指标代码（PMI, 工业增加值, 等）
            start_date: 起始日期
            end_date: 结束日期
            use_pit: 是否使用 Point-in-Time 模式
            source: 数据源过滤

        Returns:
            List[MacroIndicator]: 完整指标列表
        """
        code = self.GROWTH_INDICATORS.get(indicator_code, indicator_code)
        return self.get_series(code, start_date, end_date, use_pit, source)

    def get_inflation_series(
        self,
        indicator_code: str = "CPI",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        use_pit: bool = False,
        source: Optional[str] = None
    ) -> List[float]:
        """
        获取通胀指标序列（用于 Regime 计算）

        Args:
            indicator_code: 指标代码（CPI, PPI, 等）
            start_date: 起始日期
            end_date: 结束日期
            use_pit: 是否使用 Point-in-Time 模式
            source: 数据源过滤

        Returns:
            List[float]: 指标值列表
        """
        # 映射指标代码
        code = self.INFLATION_INDICATORS.get(indicator_code, indicator_code)
        indicators = self.get_series(code, start_date, end_date, use_pit, source)
        return [ind.value for ind in indicators]

    def get_inflation_series_full(
        self,
        indicator_code: str = "CPI",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        use_pit: bool = False,
        source: Optional[str] = None
    ) -> List[MacroIndicator]:
        """
        获取通胀指标完整序列（包含日期等元数据）

        Args:
            indicator_code: 指标代码（CPI, PPI, 等）
            start_date: 起始日期
            end_date: 结束日期
            use_pit: 是否使用 Point-in-Time 模式
            source: 数据源过滤

        Returns:
            List[MacroIndicator]: 完整指标列表
        """
        code = self.INFLATION_INDICATORS.get(indicator_code, indicator_code)
        return self.get_series(code, start_date, end_date, use_pit, source)

    def get_latest_observation_date(
        self,
        code: str,
        as_of_date: Optional[date] = None
    ) -> Optional[date]:
        """
        获取指定日期前可用的最新观测日期

        用于 Point-in-Time 数据处理，考虑发布延迟。

        Args:
            code: 指标代码
            as_of_date: 查询截止日期（None 表示当前）

        Returns:
            Optional[date]: 最新观测日期，无数据则返回 None
        """
        query = self._model.objects.filter(code=code)

        if as_of_date:
            # 考虑发布延迟
            query = query.filter(published_at__lte=as_of_date)
        else:
            query = query.filter(published_at__lte=datetime.now().date())

        latest = query.order_by('-reporting_period').first()
        if latest:
            return latest.reporting_period
        return None

    def get_latest_observation(
        self,
        code: str,
        before_date: Optional[date] = None
    ) -> Optional[MacroIndicator]:
        """
        获取指定指标在某个日期前的最新观测值

        用于容错机制，当数据缺失时可以使用前值填充。

        Args:
            code: 指标代码
            before_date: 截止日期（None 表示最新）

        Returns:
            Optional[MacroIndicator]: 最新观测值，无数据则返回 None
        """
        query = self._model.objects.filter(code=code)

        if before_date:
            query = query.filter(reporting_period__lt=before_date)

        latest = query.order_by('-reporting_period').first()
        if latest:
            return self._orm_to_entity(latest)
        return None

    def get_available_dates(
        self,
        codes: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[date]:
        """
        获取指定指标的可用日期列表

        用于回测时确定有数据的日期点。

        Args:
            codes: 指标代码列表（None 表示所有）
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[date]: 按时间排序的日期列表
        """
        query = self._model.objects.all()

        if codes:
            query = query.filter(code__in=codes)
        if start_date:
            query = query.filter(reporting_period__gte=start_date)
        if end_date:
            query = query.filter(reporting_period__lte=end_date)

        # 获取去重后的日期列表
        dates = query.values_list('reporting_period', flat=True).distinct().order_by('reporting_period')
        return list(dates)

    def delete_indicator(
        self,
        code: str,
        observed_at: date,
        revision_number: Optional[int] = None
    ) -> bool:
        """
        删除指定指标

        Args:
            code: 指标代码
            observed_at: 观测日期（兼容旧 API，实际使用 reporting_period）
            revision_number: 修订版本号（None 表示删除所有版本）

        Returns:
            bool: 是否成功删除
        """
        query = self._model.objects.filter(
            code=code,
            reporting_period=observed_at
        )

        if revision_number is not None:
            query = query.filter(revision_number=revision_number)

        count, _ = query.delete()
        return count > 0

    def get_indicator_count(
        self,
        code: Optional[str] = None
    ) -> int:
        """
        获取指标数量

        Args:
            code: 指标代码（None 表示统计所有）

        Returns:
            int: 指标数量
        """
        query = self._model.objects.all()
        if code:
            query = query.filter(code=code)
        return query.count()

    def delete_by_conditions(
        self,
        indicator_code: Optional[str] = None,
        source: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> int:
        """
        按条件删除数据

        Args:
            indicator_code: 指标代码（None 表示不限制）
            source: 数据源（None 表示不限制）
            start_date: 起始日期（None 表示不限制）
            end_date: 结束日期（None 表示不限制）

        Returns:
            int: 删除的记录数
        """
        query = self._model.objects.all()

        if indicator_code:
            query = query.filter(code=indicator_code)
        if source:
            query = query.filter(source=source)
        if start_date:
            query = query.filter(reporting_period__gte=start_date)
        if end_date:
            query = query.filter(reporting_period__lte=end_date)

        count, _ = query.delete()
        return count

    def get_statistics(self) -> Dict:
        """
        获取数据统计信息

        Returns:
            Dict: 统计信息字典
        """
        from django.db.models import Count

        # 基础统计
        total_indicators = self._model.objects.values('code').distinct().count()
        total_records = self._model.objects.count()

        # 数据源统计
        sources_stats = []
        for source in self._model.objects.values('source').annotate(
            count=Count('id')
        ).order_by('-count'):
            # 获取该数据源的最新数据时间
            latest = self._model.objects.filter(
                source=source['source']
            ).order_by('-reporting_period').first()

            sources_stats.append({
                'name': source['source'],
                'type': source['source'],
                'priority': 0,
                'is_active': True,
                'last_sync': latest.reporting_period if latest else None,
                'record_count': source['count']
            })

        # 获取最新数据日期
        latest_date = self._model.objects.aggregate(
            latest=Max('reporting_period')
        )['latest']

        return {
            'total_indicators': total_indicators,
            'total_records': total_records,
            'latest_date': latest_date,
            'sources': sources_stats
        }

    def get_recent_syncs(self, limit: int = 10) -> List[Dict]:
        """
        获取最近的同步记录

        Args:
            limit: 返回记录数

        Returns:
            List[Dict]: 同步记录列表
        """
        # 这里可以扩展为真正的同步日志表
        # 当前返回最近添加的数据记录
        recent = self._model.objects.order_by('-published_at').values(
            'code', 'source', 'published_at', 'reporting_period'
        ).distinct()[:limit]

        return [
            {
                'indicator': r['code'],
                'source': r['source'],
                'sync_time': r['published_at'] or r['reporting_period'],
                'status': 'success'
            }
            for r in recent
        ]

    @staticmethod
    def _orm_to_entity(orm_obj: MacroIndicatorORM) -> MacroIndicator:
        """将 ORM 对象转换为 Domain 实体"""
        # 尝试将 period_type 字符串转换为枚举
        # 如果失败（如扩展类型 10Y, 5Y 等），使用 PeriodType.DAY
        try:
            if orm_obj.period_type:
                period_type = PeriodType(orm_obj.period_type)
            else:
                period_type = PeriodType.DAY
        except (ValueError, KeyError):
            # 扩展类型（如 10Y, 5Y 等）不匹配枚举，使用 DAY 作为默认
            period_type = PeriodType.DAY

        return MacroIndicator(
            code=orm_obj.code,
            value=float(orm_obj.value),
            reporting_period=orm_obj.reporting_period,
            period_type=period_type,
            unit=orm_obj.unit,
            original_unit=orm_obj.original_unit,
            published_at=orm_obj.published_at,
            source=orm_obj.source,
        )
