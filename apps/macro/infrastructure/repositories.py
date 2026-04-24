"""
Repositories for Macro Data.

Infrastructure layer implementation using Django ORM.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.db.models import Avg, Count, Max, Min, Q
from django.utils import timezone

from ..domain.entities import MacroIndicator, PeriodType
from .models import IndicatorUnitConfig, MacroIndicator as MacroIndicatorORM


def _get_period_type_display(period_type: str) -> str:
    """Return a display label for standard and extended period types."""

    standard_types = dict(MacroIndicatorORM.PERIOD_TYPE_CHOICES)
    if period_type in standard_types:
        return standard_types[period_type]
    return MacroIndicatorORM.EXTENDED_PERIOD_TYPES.get(period_type, period_type)


def _serialize_indicator_row(orm_obj: MacroIndicatorORM) -> dict[str, Any]:
    """Serialize an ORM row into a lightweight application payload."""

    return {
        "id": orm_obj.id,
        "code": orm_obj.code,
        "value": float(orm_obj.value),
        "unit": orm_obj.unit,
        "original_unit": orm_obj.original_unit,
        "reporting_period": orm_obj.reporting_period,
        "period_type": orm_obj.period_type,
        "period_type_display": _get_period_type_display(orm_obj.period_type),
        "observed_at": orm_obj.observed_at,
        "published_at": orm_obj.published_at,
        "source": orm_obj.source,
        "revision_number": orm_obj.revision_number,
        "publication_lag_days": orm_obj.publication_lag_days,
    }


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
    # CN_CPI_NATIONAL_YOY: 同比增长率，部分源可能给 0.008（比例）或 0.8（百分比）
    INFLATION_INDICATORS = {
        # 默认使用同比口径；若无数据，在读取时回退到 CN_CPI 并做 value-100 转换。
        "CPI": "CN_CPI_NATIONAL_YOY",
        "PPI": "CN_PPI",
        "GDP平减指数": "CN_GDP_DEFLATOR",
    }

    @staticmethod
    def _normalize_cpi_value(code: str, value: float) -> float:
        """
        统一 CPI 口径为“百分比（%）”。

        - CN_CPI（指数口径，100.2） -> 0.2
        - CN_CPI_NATIONAL_YOY 可能是比例值（0.008）或百分比值（0.8）
          这里将绝对值小于 0.2 的视为比例并 *100 转百分比。
        """
        if code == "CN_CPI":
            return float(value) - 100.0
        if code == "CN_CPI_NATIONAL_YOY":
            v = float(value)
            if -0.2 < v < 0.2:
                return v * 100.0
            return v
        return float(value)

    def __init__(self):
        self._model = MacroIndicatorORM

    def save_indicator(
        self,
        indicator: MacroIndicator,
        revision_number: int = 1,
        period_type_override: str | None = None
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
        indicators: list[MacroIndicator],
        revision_number: int = 1
    ) -> list[MacroIndicator]:
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
        revision_number: int | None = None
    ) -> MacroIndicator | None:
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
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None
    ) -> list[MacroIndicator]:
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
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None
    ) -> list[float]:
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
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None
    ) -> list[MacroIndicator]:
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
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None
    ) -> list[float]:
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

        # CPI 优先同比口径，若无数据则回退到指数口径并转换为同比百分比
        if indicator_code == "CPI" and not indicators and code == "CN_CPI_NATIONAL_YOY":
            code = "CN_CPI"
            indicators = self.get_series(code, start_date, end_date, use_pit, source)

        if indicator_code == "CPI":
            return [self._normalize_cpi_value(code, ind.value) for ind in indicators]

        return [ind.value for ind in indicators]

    def get_inflation_series_full(
        self,
        indicator_code: str = "CPI",
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None
    ) -> list[MacroIndicator]:
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
        indicators = self.get_series(code, start_date, end_date, use_pit, source)

        # 与 get_inflation_series 保持一致：CPI 支持同比->指数回退，并统一为百分比口径。
        if indicator_code == "CPI" and not indicators and code == "CN_CPI_NATIONAL_YOY":
            code = "CN_CPI"
            indicators = self.get_series(code, start_date, end_date, use_pit, source)

        if indicator_code != "CPI":
            return indicators

        normalized: list[MacroIndicator] = []
        for ind in indicators:
            normalized.append(
                MacroIndicator(
                    code=ind.code,
                    value=self._normalize_cpi_value(code, ind.value),
                    reporting_period=ind.reporting_period,
                    period_type=ind.period_type,
                    unit='%',
                    original_unit=ind.original_unit,
                    published_at=ind.published_at,
                    source=ind.source,
                )
            )
        return normalized

    def get_latest_observation_date(
        self,
        code: str,
        as_of_date: date | None = None
    ) -> date | None:
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
            query = query.filter(published_at__lte=timezone.now().date())

        latest = query.order_by('-reporting_period').first()
        if latest:
            return latest.reporting_period
        return None

    def get_latest_observation(
        self,
        code: str,
        before_date: date | None = None
    ) -> MacroIndicator | None:
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
        codes: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None
    ) -> list[date]:
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
        revision_number: int | None = None
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
        code: str | None = None
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
        indicator_code: str | None = None,
        source: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None
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

    def get_record_by_id(self, record_id: int) -> dict[str, Any] | None:
        """Return one persisted indicator row by primary key."""

        record = self._model.objects.filter(id=record_id).first()
        if record is None:
            return None
        return _serialize_indicator_row(record)

    def create_record(
        self,
        *,
        code: str,
        value: float,
        reporting_period: date,
        period_type: str = "D",
        published_at: date | None = None,
        source: str = "manual",
        revision_number: int = 1,
    ) -> dict[str, Any]:
        """Create one indicator row and return a lightweight payload."""

        record = self._model.objects.create(
            code=code,
            value=value,
            reporting_period=reporting_period,
            period_type=period_type,
            published_at=published_at,
            source=source,
            revision_number=revision_number,
        )
        return _serialize_indicator_row(record)

    def update_record(
        self,
        record_id: int,
        **updates: Any,
    ) -> dict[str, Any] | None:
        """Apply partial updates to one indicator row."""

        record = self._model.objects.filter(id=record_id).first()
        if record is None:
            return None

        for field_name, value in updates.items():
            setattr(record, field_name, value)
        record.save()
        record.refresh_from_db()
        return _serialize_indicator_row(record)

    def delete_record_by_id(self, record_id: int) -> bool:
        """Delete one indicator row by primary key."""

        deleted_count, _ = self._model.objects.filter(id=record_id).delete()
        return deleted_count > 0

    def delete_records_by_ids(self, record_ids: list[int]) -> int:
        """Delete multiple indicator rows by primary key list."""

        deleted_count, _ = self._model.objects.filter(id__in=record_ids).delete()
        return deleted_count

    def count_records_before_date(self, cutoff_date: date) -> int:
        """统计指定日期之前的指标记录数量。"""
        return self._model.objects.filter(reporting_period__lt=cutoff_date).count()

    def get_statistics(self) -> dict:
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

    def get_recent_syncs(self, limit: int = 10) -> list[dict]:
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


class MacroIndicatorReadRepository:
    """Read-model repository for macro indicator application queries."""

    @staticmethod
    def _build_filtered_queryset(
        *,
        code: str | None = None,
        code_filter: str = "",
        source_filter: str = "",
        period_type_filter: str = "",
        start_date: date | None = None,
        end_date: date | None = None,
    ):
        """Build the common queryset for interface-facing indicator queries."""

        queryset = MacroIndicatorORM._default_manager.all()
        if code:
            queryset = queryset.filter(code=code)
        if code_filter:
            queryset = queryset.filter(code__icontains=code_filter)
        if source_filter:
            queryset = queryset.filter(source=source_filter)
        if period_type_filter:
            queryset = queryset.filter(period_type=period_type_filter)
        if start_date:
            queryset = queryset.filter(reporting_period__gte=start_date)
        if end_date:
            queryset = queryset.filter(reporting_period__lte=end_date)
        return queryset

    def get_indicator_unit_config(
        self,
        indicator_code: str,
        source: str | None = None,
    ) -> dict | None:
        """Return the best matching unit config as a lightweight dict."""

        queryset = IndicatorUnitConfig._default_manager.filter(
            indicator_code=indicator_code,
            is_active=True,
        )
        if source:
            config = queryset.filter(source=source).values(
                "indicator_code",
                "source",
                "original_unit",
                "priority",
            ).first()
            if config:
                return config

        config = queryset.filter(source="manual").values(
            "indicator_code",
            "source",
            "original_unit",
            "priority",
        ).first()
        if config:
            return config

        return queryset.order_by("-priority").values(
            "indicator_code",
            "source",
            "original_unit",
            "priority",
        ).first()

    def list_distinct_codes(self) -> list[str]:
        """Return distinct indicator codes stored in the database."""

        return list(
            MacroIndicatorORM._default_manager.values_list("code", flat=True).distinct()
        )

    def get_storage_summary(self) -> dict[str, Any]:
        """Return aggregate counts and date range for stored macro data."""

        queryset = MacroIndicatorORM._default_manager.all()
        aggregates = queryset.aggregate(
            latest_date=Max("reporting_period"),
            min_date=Min("reporting_period"),
            max_date=Max("reporting_period"),
        )
        return {
            "total_indicators": queryset.values("code").distinct().count(),
            "total_records": queryset.count(),
            "latest_date": aggregates["latest_date"],
            "min_date": aggregates["min_date"],
            "max_date": aggregates["max_date"],
        }

    def list_indicator_rollups(self) -> list[dict[str, Any]]:
        """Return per-code counts and latest reporting date for the controller page."""

        return list(
            MacroIndicatorORM._default_manager.values("code")
            .annotate(count=Count("id"), latest=Max("reporting_period"))
            .order_by("code")
        )

    def list_source_rollups(self) -> list[dict[str, Any]]:
        """Return per-source counts for the controller page."""

        return list(
            MacroIndicatorORM._default_manager.values("source")
            .annotate(count=Count("id"))
            .order_by("-count", "source")
        )

    def get_indicator_rows(
        self,
        *,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int | None = None,
        ascending: bool = True,
    ) -> list[dict[str, Any]]:
        """Return serialized rows for one indicator code."""

        queryset = self._build_filtered_queryset(
            code=code,
            start_date=start_date,
            end_date=end_date,
        )
        if ascending:
            queryset = queryset.order_by("reporting_period", "revision_number")
        else:
            queryset = queryset.order_by("-reporting_period", "-revision_number")
        if limit is not None:
            queryset = queryset[:limit]
        return [_serialize_indicator_row(row) for row in queryset]

    def count_table_rows(
        self,
        *,
        code_filter: str = "",
        source_filter: str = "",
        period_type_filter: str = "",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        """Return row count for the table endpoint filters."""

        queryset = self._build_filtered_queryset(
            code_filter=code_filter,
            source_filter=source_filter,
            period_type_filter=period_type_filter,
            start_date=start_date,
            end_date=end_date,
        )
        return queryset.count()

    def get_table_rows(
        self,
        *,
        code_filter: str = "",
        source_filter: str = "",
        period_type_filter: str = "",
        start_date: date | None = None,
        end_date: date | None = None,
        sort_field: str = "-reporting_period",
        offset: int = 0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return paginated serialized rows for the table endpoint."""

        queryset = self._build_filtered_queryset(
            code_filter=code_filter,
            source_filter=source_filter,
            period_type_filter=period_type_filter,
            start_date=start_date,
            end_date=end_date,
        ).order_by(sort_field, "-revision_number")
        rows = queryset[offset:offset + limit]
        return [_serialize_indicator_row(row) for row in rows]

    def get_latest_indicator(self, code: str) -> dict | None:
        """Return the latest indicator row for one code."""

        return MacroIndicatorORM._default_manager.filter(code=code).order_by(
            "-reporting_period"
        ).values(
            "code",
            "value",
            "unit",
            "original_unit",
            "reporting_period",
            "period_type",
        ).first()

    def get_indicator_stats(self, code: str, start_date: date) -> dict[str, float | None]:
        """Return aggregate stats for one indicator code from a start date."""

        stats = MacroIndicatorORM._default_manager.filter(
            code=code,
            reporting_period__gte=start_date,
        ).aggregate(
            avg_value=Avg("value"),
            max_value=Max("value"),
            min_value=Min("value"),
        )
        return {
            "avg_value": float(stats["avg_value"]) if stats["avg_value"] is not None else None,
            "max_value": float(stats["max_value"]) if stats["max_value"] is not None else None,
            "min_value": float(stats["min_value"]) if stats["min_value"] is not None else None,
        }

    def get_indicator_history(
        self,
        code: str,
        *,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[dict]:
        """Return recent indicator history rows for one code."""

        rows = MacroIndicatorORM._default_manager.filter(
            code=code,
            reporting_period__gte=start_date,
            reporting_period__lte=end_date,
        ).order_by("-reporting_period").values(
            "value",
            "unit",
            "original_unit",
            "reporting_period",
            "period_type",
        )[:limit]
        return list(rows)

    def get_latest_values_by_codes(self, codes: list[str]) -> list[dict]:
        """Return ordered code/value rows for latest-value projection."""

        rows = (
            MacroIndicatorORM._default_manager
            .filter(code__in=codes)
            .order_by("code", "-reporting_period")
            .values("code", "value")
        )
        return list(rows)
