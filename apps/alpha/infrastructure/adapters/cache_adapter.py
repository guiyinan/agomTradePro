"""
Cache Alpha Provider

从数据库缓存读取 Alpha 评分的 Provider。
优先级较高，因为缓存数据稳定且快速。
"""

import logging
import math
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from ...domain.entities import AlphaPoolScope, AlphaResult, StockScore, normalize_stock_code
from ...domain.interfaces import AlphaProviderStatus
from ...infrastructure.models import AlphaScoreCacheModel
from .base import BaseAlphaProvider, provider_safe

logger = logging.getLogger(__name__)

MAX_CACHE_RESULTS = 5000
MAX_CACHE_RETENTION_DAYS = 3650
MAX_CACHE_DATE_RANGE_DAYS = 3650


class CacheAlphaProvider(BaseAlphaProvider):
    """
    缓存 Alpha 提供者

    从 AlphaScoreCache 数据库表读取历史缓存数据。
    优先级为 10，仅次于 Qlib。

    Attributes:
        priority: 10（高优先级）
        max_staleness_days: 5 天（缓存可以接受更旧的数据）

    Example:
        >>> provider = CacheAlphaProvider()
        >>> result = provider.get_stock_scores("csi300", date.today())
        >>> if result.success:
        ...     print(f"Found {len(result.scores)} cached scores")
    """

    def __init__(self, max_staleness_days: int = 5) -> None:
        """
        初始化缓存 Provider

        Args:
            max_staleness_days: 最大可接受的数据陈旧天数（默认 5 天）
        """
        if (
            isinstance(max_staleness_days, bool)
            or not isinstance(max_staleness_days, int)
            or not 0 <= max_staleness_days <= 365
        ):
            raise ValueError("max_staleness_days must be an integer between 0 and 365")
        super().__init__()
        self._max_staleness_days = max_staleness_days

    @property
    def name(self) -> str:
        """Provider 名称"""
        return "cache"

    @property
    def priority(self) -> int:
        """优先级"""
        return 10

    @property
    def max_staleness_days(self) -> int:
        """最大陈旧天数"""
        return self._max_staleness_days

    def health_check(self) -> AlphaProviderStatus:
        """
        健康检查

        检查缓存表是否存在且最新缓存是否仍在有效期内。

        Returns:
            Provider 状态
        """
        try:
            latest_cache = AlphaScoreCacheModel._default_manager.order_by(
                "-asof_date", "-created_at"
            ).first()
            if not latest_cache:
                self._last_health_message = "暂无缓存数据"
                return AlphaProviderStatus.DEGRADED

            today = timezone.localdate()
            if latest_cache.asof_date > today:
                self._last_health_message = "最新缓存包含未来 asof_date，已拒绝使用"
                return AlphaProviderStatus.UNAVAILABLE
            staleness_days = (today - latest_cache.asof_date).days
            if staleness_days <= self.max_staleness_days:
                self._last_health_message = None
                return AlphaProviderStatus.AVAILABLE

            self._last_health_message = (
                f"最新缓存日期 {latest_cache.intended_trade_date.isoformat()}，"
                f"已过期 {staleness_days} 天"
            )
            return AlphaProviderStatus.DEGRADED

        except Exception as e:
            logger.error(f"Cache health check failed: {e}")
            return AlphaProviderStatus.UNAVAILABLE

    @provider_safe()
    def get_stock_scores(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int = 30,
        pool_scope: AlphaPoolScope | None = None,
        user: Any | None = None,
    ) -> AlphaResult:
        """
        从缓存获取股票评分（支持用户隔离）

        读取优先级：用户个人评分 > 系统级评分（user=None）

        1. 优先查找用户个人评分（精确日期匹配）
        2. 若无，fallback 到系统级评分（精确日期匹配）
        3. 若无精确匹配，向前查找最近的有效缓存
        4. 检查 staleness，如果过期返回 degraded

        Args:
            universe_id: 股票池标识
            intended_trade_date: 计划交易日期
            top_n: 返回前 N 只
            user: 当前用户（None 表示匿名或仅查系统级）

        Returns:
            AlphaResult
        """
        validation_error = self._validate_score_request(
            universe_id=universe_id,
            intended_trade_date=intended_trade_date,
            top_n=top_n,
            pool_scope=pool_scope,
        )
        if validation_error is not None:
            return self._create_error_result(validation_error)

        cache: AlphaScoreCacheModel | None = None
        universe_filter = self._build_universe_filter(
            universe_id=universe_id,
            pool_scope=pool_scope,
        )

        # 1. 优先查用户个人评分
        if user is not None and getattr(user, "is_authenticated", False) is True:
            cache = self._select_best_cache(
                AlphaScoreCacheModel._default_manager.filter(
                    user=user,
                    **universe_filter,
                ),
                intended_trade_date=intended_trade_date,
            )

        # 2. Fallback 到系统级评分
        if not cache:
            cache = self._select_best_cache(
                AlphaScoreCacheModel._default_manager.filter(
                    user=None,
                    **universe_filter,
                ),
                intended_trade_date=intended_trade_date,
            )

        if (
            cache is not None
            and pool_scope is not None
            and self._should_prefer_broader_qlib_cache(
                cache=cache,
            )
        ):
            broader_cache_result = self._select_broader_cache_for_scope(
                intended_trade_date=intended_trade_date,
                top_n=top_n,
                pool_scope=pool_scope,
            )
            if broader_cache_result is not None:
                broader_cache, scores, metadata = broader_cache_result
                staleness_days = self._calculate_staleness_days(
                    cache=broader_cache,
                    intended_trade_date=intended_trade_date,
                )
                if not self._is_cache_degraded(
                    cache=broader_cache,
                    staleness_days=staleness_days,
                ):
                    result = self._create_success_result(
                        scores=scores,
                        staleness_days=staleness_days,
                        metadata=metadata,
                    )
                    result.metadata = {
                        **dict(getattr(result, "metadata", {}) or {}),
                        **metadata,
                    }
                    return result

        if not cache and pool_scope is not None:
            broader_cache_result = self._select_broader_cache_for_scope(
                intended_trade_date=intended_trade_date,
                top_n=top_n,
                pool_scope=pool_scope,
            )
            if broader_cache_result is not None:
                broader_cache, scores, metadata = broader_cache_result
                staleness_days = self._calculate_staleness_days(
                    cache=broader_cache,
                    intended_trade_date=intended_trade_date,
                )
                if self._is_cache_degraded(
                    cache=broader_cache,
                    staleness_days=staleness_days,
                ):
                    result = self._create_degraded_result(
                        scores=scores,
                        staleness_days=staleness_days,
                        reason=self._build_cache_degraded_reason(
                            cache=broader_cache,
                            staleness_days=staleness_days,
                            fallback_reason=(
                                f"账户池专属缓存缺失，改用 {metadata['scope_fallback_source_universe_id']} "
                                f"裁剪后的历史缓存，数据过期 {staleness_days} 天"
                            ),
                        ),
                    )
                else:
                    result = self._create_success_result(
                        scores=scores,
                        staleness_days=staleness_days,
                        metadata=metadata,
                    )
                result.metadata = {
                    **dict(getattr(result, "metadata", {}) or {}),
                    **metadata,
                }
                return result

        if not cache:
            return self._create_error_result(
                f"未找到 {universe_id} 的缓存数据", status="unavailable"
            )

        # 3. 检查 staleness
        staleness_days = self._calculate_staleness_days(
            cache=cache,
            intended_trade_date=intended_trade_date,
        )

        # 4. 解析评分
        scores = self._parse_scores(
            cache.scores,
            top_n,
            default_asof_date=cache.asof_date,
            default_intended_trade_date=cache.intended_trade_date,
        )
        if not scores:
            return self._create_error_result(
                f"{universe_id} 缓存存在但评分为空或损坏",
                status="unavailable",
            )

        metadata = {
            **self._build_cache_metadata(cache=cache),
        }
        if self._is_cache_degraded(
            cache=cache,
            staleness_days=staleness_days,
        ):
            degraded_reason = self._build_cache_degraded_reason(
                cache=cache,
                staleness_days=staleness_days,
            )
            result = self._create_degraded_result(
                scores=scores,
                staleness_days=staleness_days,
                reason=degraded_reason,
            )
            result.metadata = {
                **metadata,
                "fallback_reason": degraded_reason,
            }
            return result

        return self._create_success_result(
            scores=scores,
            staleness_days=staleness_days,
            metadata=metadata,
        )

    @staticmethod
    def _validate_score_request(
        *,
        universe_id: str,
        intended_trade_date: date,
        top_n: int,
        pool_scope: AlphaPoolScope | None,
    ) -> str | None:
        """Validate cache lookup bounds before accessing the database."""
        if not isinstance(universe_id, str) or not universe_id.strip():
            return "universe_id must be a non-empty string"
        if len(universe_id) > 50:
            return "universe_id exceeds 50 characters"
        if not isinstance(intended_trade_date, date):
            return "intended_trade_date must be a date"
        if (
            isinstance(top_n, bool)
            or not isinstance(top_n, int)
            or not 1 <= top_n <= MAX_CACHE_RESULTS
        ):
            return f"top_n must be an integer between 1 and {MAX_CACHE_RESULTS}"
        if pool_scope is not None and pool_scope.trade_date != intended_trade_date:
            return "pool_scope trade_date must match intended_trade_date"
        return None

    def _build_universe_filter(
        self,
        *,
        universe_id: str,
        pool_scope: AlphaPoolScope | None,
    ) -> dict[str, object]:
        if pool_scope is not None:
            return {
                "scope_hash": pool_scope.scope_hash,
                "universe_id": pool_scope.universe_id,
            }
        return {"universe_id": universe_id}

    def _select_best_cache(
        self,
        queryset: QuerySet[AlphaScoreCacheModel],
        intended_trade_date: date,
    ) -> AlphaScoreCacheModel | None:
        """
        Prefer an exact-date cache when it is fresh; otherwise fall back to the
        freshest historical cache on or before the requested trade date.
        """
        exact_cache = (
            queryset.filter(
                intended_trade_date=intended_trade_date,
                asof_date__lte=intended_trade_date,
            )
            .order_by("-asof_date", "-created_at")
            .first()
        )
        historical_cache = (
            queryset.filter(
                intended_trade_date__lte=intended_trade_date,
                asof_date__lte=intended_trade_date,
            )
            .order_by("-asof_date", "-intended_trade_date", "-created_at")
            .first()
        )

        if exact_cache is None:
            return historical_cache
        if historical_cache is None:
            return exact_cache

        exact_staleness = self._calculate_staleness_days(
            cache=exact_cache,
            intended_trade_date=intended_trade_date,
        )
        history_staleness = self._calculate_staleness_days(
            cache=historical_cache,
            intended_trade_date=intended_trade_date,
        )
        if exact_staleness <= self.max_staleness_days:
            return exact_cache
        if history_staleness <= self.max_staleness_days:
            return historical_cache
        if history_staleness < exact_staleness:
            return historical_cache
        if historical_cache.asof_date and exact_cache.asof_date:
            if historical_cache.asof_date > exact_cache.asof_date:
                return historical_cache
        return exact_cache

    def _select_broader_cache_for_scope(
        self,
        *,
        intended_trade_date: date,
        top_n: int,
        pool_scope: AlphaPoolScope,
    ) -> tuple[AlphaScoreCacheModel, list[StockScore], dict[str, object]] | None:
        scope_codes = {normalize_stock_code(code) for code in pool_scope.instrument_codes}
        if not scope_codes:
            return None

        broader_caches = (
            AlphaScoreCacheModel._default_manager.filter(
                user=None,
                provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
                intended_trade_date__lte=intended_trade_date,
                asof_date__lte=intended_trade_date,
            )
            .exclude(scores=[])
            .exclude(scope_hash=pool_scope.scope_hash)
            .order_by("-asof_date", "-intended_trade_date", "-created_at")[:30]
        )

        for broader_cache in broader_caches:
            filtered_scores = self._filter_scores_by_scope(
                raw_scores=broader_cache.scores or [],
                allowed_codes=scope_codes,
                top_n=top_n,
                default_asof_date=broader_cache.asof_date,
                default_intended_trade_date=broader_cache.intended_trade_date,
            )
            if not filtered_scores:
                continue
            return (
                broader_cache,
                filtered_scores,
                {
                    **self._build_cache_metadata(cache=broader_cache),
                    "cache_date": broader_cache.intended_trade_date.isoformat(),
                    "asof_date": broader_cache.asof_date.isoformat(),
                    "provider_source": broader_cache.provider_source,
                    "created_at": broader_cache.created_at.isoformat(),
                    "scope_hash": pool_scope.scope_hash,
                    "scope_label": pool_scope.display_label,
                    "scope_metadata": pool_scope.to_dict(),
                    "scope_fallback": True,
                    "scope_fallback_universe_id": broader_cache.universe_id,
                    "scope_fallback_source_universe_id": broader_cache.universe_id,
                    "scope_fallback_reason": (
                        f"账户池专属缓存缺失，已使用 {broader_cache.universe_id} 的最近 Qlib 缓存，"
                        "并按当前账户池成分裁剪。"
                    ),
                    "derived_from_broader_cache": True,
                    "derived_from_broader_cache_universe_id": broader_cache.universe_id,
                    "derived_from_broader_cache_reason": (
                        f"账户池专属缓存缺失，已使用 {broader_cache.universe_id} 的最近 Qlib 缓存，"
                        "并按当前账户池成分裁剪。"
                    ),
                    "reliability_notice": {
                        "level": "warning",
                        "code": "scoped_cache_derived_from_broader_cache",
                        "title": "Alpha 当前使用账户池映射缓存",
                        "message": (
                            f"账户池专属缓存尚未生成，当前展示的是 {broader_cache.intended_trade_date.isoformat()} "
                            f"的 {broader_cache.universe_id} Qlib 缓存，并按当前账户池成分裁剪后的结果。"
                        ),
                    },
                },
            )
        return None

    def _filter_scores_by_scope(
        self,
        *,
        raw_scores: Sequence[object],
        allowed_codes: set[str],
        top_n: int,
        default_asof_date: date | None,
        default_intended_trade_date: date | None,
    ) -> list[StockScore]:
        filtered_raw_scores: list[dict[str, Any]] = []
        for item in raw_scores:
            if not isinstance(item, Mapping):
                continue
            payload = dict(item)
            normalized_code = normalize_stock_code(payload.get("code"))
            if normalized_code and normalized_code in allowed_codes:
                payload["code"] = normalized_code
                filtered_raw_scores.append(payload)
        return self._parse_scores(
            filtered_raw_scores,
            top_n,
            default_asof_date=default_asof_date,
            default_intended_trade_date=default_intended_trade_date,
        )

    @staticmethod
    def _calculate_staleness_days(
        *,
        cache: AlphaScoreCacheModel,
        intended_trade_date: date,
    ) -> int:
        """Calculate cache age relative to the requested signal date."""
        if not cache.asof_date:
            return 999
        return max((intended_trade_date - cache.asof_date).days, 0)

    @staticmethod
    def _build_cache_metadata(*, cache: AlphaScoreCacheModel) -> dict[str, object]:
        metrics_snapshot = cache.metrics_snapshot
        metadata: dict[str, object] = (
            dict(metrics_snapshot) if isinstance(metrics_snapshot, Mapping) else {}
        )
        metadata.update(
            {
                "cache_date": cache.intended_trade_date.isoformat(),
                "asof_date": cache.asof_date.isoformat() if cache.asof_date else None,
                "provider_source": cache.provider_source,
                "created_at": cache.created_at.isoformat(),
                "cache_status": cache.status,
                "scope_hash": cache.scope_hash,
                "scope_label": cache.scope_label,
                "scope_metadata": cache.scope_metadata or {},
            }
        )
        return metadata

    def _is_cache_degraded(
        self,
        *,
        cache: AlphaScoreCacheModel,
        staleness_days: int,
    ) -> bool:
        if staleness_days > self.max_staleness_days:
            return True
        return cache.status == AlphaScoreCacheModel.STATUS_DEGRADED

    @staticmethod
    def _should_prefer_broader_qlib_cache(*, cache: AlphaScoreCacheModel) -> bool:
        if cache.status != AlphaScoreCacheModel.STATUS_DEGRADED:
            return False
        metrics_snapshot = (
            cache.metrics_snapshot if isinstance(cache.metrics_snapshot, Mapping) else {}
        )
        return metrics_snapshot.get("fallback_mode") == "forward_fill_latest_qlib_cache"

    def _build_cache_degraded_reason(
        self,
        *,
        cache: AlphaScoreCacheModel,
        staleness_days: int,
        fallback_reason: str | None = None,
    ) -> str:
        if staleness_days > self.max_staleness_days:
            return f"缓存数据过期 {staleness_days} 天（最大允许 {self.max_staleness_days} 天）"
        if cache.status == AlphaScoreCacheModel.STATUS_DEGRADED:
            metrics_snapshot = (
                cache.metrics_snapshot if isinstance(cache.metrics_snapshot, Mapping) else {}
            )
            return str(
                metrics_snapshot.get("fallback_reason")
                or fallback_reason
                or "缓存结果当前为降级状态"
            )
        return str(fallback_reason or "")

    def _parse_scores(
        self,
        raw_scores: Sequence[object],
        top_n: int,
        default_asof_date: date | None = None,
        default_intended_trade_date: date | None = None,
    ) -> list[StockScore]:
        """
        解析原始评分数据

        Args:
            raw_scores: 原始 JSON 数据
            top_n: 返回前 N 只

        Returns:
            StockScore 列表
        """
        scores: list[StockScore] = []
        seen_codes: set[str] = set()
        for item in raw_scores[:MAX_CACHE_RESULTS]:
            if len(scores) >= top_n:
                break
            try:
                if not isinstance(item, Mapping):
                    raise TypeError("score item must be a mapping")
                payload = dict(item)
                normalized_code = normalize_stock_code(payload.get("code"))
                if not normalized_code or normalized_code in seen_codes:
                    continue
                payload["code"] = normalized_code
                payload.setdefault("source", "cache")
                if default_asof_date:
                    payload["asof_date"] = default_asof_date.isoformat()
                if default_intended_trade_date:
                    payload["intended_trade_date"] = default_intended_trade_date.isoformat()
                if any(
                    isinstance(payload.get(field), bool)
                    for field in ("score", "rank", "confidence")
                ):
                    raise ValueError("boolean values are not valid score numerics")
                score = StockScore.from_dict(payload)
                if (
                    score.rank <= 0
                    or not math.isfinite(score.score)
                    or not -1.0 <= score.score <= 1.0
                    or not math.isfinite(score.confidence)
                    or not 0.0 <= score.confidence <= 1.0
                ):
                    raise ValueError("score payload contains invalid numeric values")
                seen_codes.add(normalized_code)
                scores.append(score)
            except Exception as e:
                logger.warning(f"解析评分失败: {item}, error: {e}")
                continue

        return scores

    def get_available_dates(self, universe_id: str, start_date: date, end_date: date) -> list[date]:
        """
        获取指定日期范围内的可用缓存日期

        Args:
            universe_id: 股票池标识
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            可用日期列表
        """
        self._validate_universe_id(universe_id)
        if not isinstance(start_date, date) or not isinstance(end_date, date):
            raise ValueError("start_date and end_date must be dates")
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if (end_date - start_date).days > MAX_CACHE_DATE_RANGE_DAYS:
            raise ValueError(f"cache date range cannot exceed {MAX_CACHE_DATE_RANGE_DAYS} days")

        caches = (
            AlphaScoreCacheModel._default_manager.filter(
                universe_id=universe_id,
                intended_trade_date__gte=start_date,
                intended_trade_date__lte=end_date,
            )
            .values_list("intended_trade_date", flat=True)
            .distinct()
        )

        return sorted(set(caches))

    def get_latest_cache_date(self, universe_id: str) -> date | None:
        """
        获取指定股票池的最新缓存日期

        Args:
            universe_id: 股票池标识

        Returns:
            最新缓存日期，如果没有则返回 None
        """
        self._validate_universe_id(universe_id)

        cache = (
            AlphaScoreCacheModel._default_manager.filter(universe_id=universe_id)
            .order_by("-intended_trade_date")
            .first()
        )

        return cache.intended_trade_date if cache else None

    def clear_stale_cache(self, universe_id: str, days_to_keep: int = 30) -> int:
        """
        清理过期缓存

        Args:
            universe_id: 股票池标识
            days_to_keep: 保留最近多少天的缓存

        Returns:
            删除的记录数
        """
        self._validate_universe_id(universe_id)
        if (
            isinstance(days_to_keep, bool)
            or not isinstance(days_to_keep, int)
            or not 1 <= days_to_keep <= MAX_CACHE_RETENTION_DAYS
        ):
            raise ValueError(
                f"days_to_keep must be an integer between 1 and {MAX_CACHE_RETENTION_DAYS}"
            )

        cutoff_date = timezone.localdate() - timedelta(days=days_to_keep)

        deleted, _ = AlphaScoreCacheModel._default_manager.filter(
            universe_id=universe_id, intended_trade_date__lt=cutoff_date
        ).delete()

        logger.info(f"清理了 {deleted} 条过期缓存（{universe_id}）")
        return int(deleted)

    @staticmethod
    def _validate_universe_id(universe_id: str) -> None:
        """Validate a persisted universe identifier."""
        if not isinstance(universe_id, str) or not universe_id.strip():
            raise ValueError("universe_id must be a non-empty string")
        if len(universe_id) > 50:
            raise ValueError("universe_id exceeds 50 characters")
