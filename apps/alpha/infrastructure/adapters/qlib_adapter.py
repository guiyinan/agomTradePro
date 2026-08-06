"""
Qlib Alpha Provider

使用 Qlib 模型进行推理的 Provider。
优先级为 1（最高），通过缓存提供快速响应。
"""

import logging
import math
import pickle
import re
import time
from datetime import date, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import TypedDict

from celery import current_app
from django.core.cache import cache

from ...domain.entities import AlphaPoolScope, AlphaResult, StockScore, normalize_stock_code
from ...domain.interfaces import AlphaProviderStatus
from ..scientific_runtime import get_pandas
from .base import BaseAlphaProvider, provider_safe, qlib_safe

logger = logging.getLogger(__name__)


class ActiveModelInfo(TypedDict, total=False):
    model_name: str
    artifact_hash: str
    model_type: str
    model_path: str
    feature_set_id: str
    label_id: str
    data_version: str
    ic: float | None
    icir: float | None


def _normalize_calendar_date(value: object) -> date | None:
    """Convert qlib calendar entries to Python dates."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    date_method = getattr(value, "date", None)
    if callable(date_method):
        candidate = date_method()
        if isinstance(candidate, date):
            return candidate
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _normalize_universe_id(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", normalized) is None:
        return None
    return normalized


class QlibAlphaProvider(BaseAlphaProvider):
    """
    Qlib Alpha 提供者

    使用 Qlib 训练的机器学习模型进行股票评分。
    优先级为 1（最高），但只读缓存，不直接调用 Qlib。

    工作流程：
    1. 快路径：从 AlphaScoreCache 读取缓存
    2. 慢路径：触发异步推理任务（Celery）
    3. 本地无可用 worker 时同步执行一次推理并回读缓存
    4. 推理不可用时返回 degraded，让 registry 去尝试下一个 provider

    Attributes:
        priority: 1（最高优先级）
        max_staleness_days: 2 天（ML 模型数据要求新鲜）

    Example:
        >>> provider = QlibAlphaProvider()
        >>> result = provider.get_stock_scores("csi300", date.today())
        >>> # 第一次可能返回 degraded（缓存未命中）
        >>> # 第二次命中缓存返回 available
    """

    INLINE_INFERENCE_MAX_POOL_SIZE = 120

    def __init__(
        self,
        provider_uri: str = "",
        model_path: str = "",
        region: str = "CN",
    ) -> None:
        """
        初始化 Qlib Provider

        Args:
            provider_uri: Qlib 数据路径
            model_path: 模型存储路径
            region: 区域配置
        """
        super().__init__()
        if not provider_uri or not model_path:
            from core.integration.runtime_settings import get_runtime_qlib_config

            runtime_qlib = get_runtime_qlib_config()
            provider_uri = provider_uri or str(runtime_qlib.get("provider_uri") or "")
            model_path = model_path or str(runtime_qlib.get("model_path") or "")
        if not provider_uri or not model_path:
            raise ValueError("Qlib provider requires typed runtime provider_uri and model_path")
        self._data_path = Path(provider_uri).expanduser()
        self._model_path = Path(model_path)
        self._region = region
        self._qlib_initialized = False
        self._model: object | None = None
        self._active_model_info: ActiveModelInfo | None = None

    @property
    def name(self) -> str:
        """Provider 名称"""
        return "qlib"

    @property
    def priority(self) -> int:
        """优先级"""
        return 1

    @property
    def max_staleness_days(self) -> int:
        """最大陈旧天数"""
        return 2

    @qlib_safe(default_return=AlphaProviderStatus.UNAVAILABLE)
    def health_check(self) -> AlphaProviderStatus:
        """
        健康检查

        检查：
        1. Qlib 数据目录是否存在
        2. 是否有激活的模型
        3. 模型文件是否完整

        Returns:
            Provider 状态
        """
        # 检查数据目录
        if not self._data_path.exists():
            logger.warning(f"Qlib 数据目录不存在: {self._data_path}")
            self._last_health_message = f"数据目录不存在: {self._data_path}"
            return AlphaProviderStatus.UNAVAILABLE

        # 检查是否有激活的模型
        active_model = self._get_active_model()
        if not active_model:
            logger.warning("没有激活的 Qlib 模型")
            self._last_health_message = "没有激活的模型，请在 Admin 中激活模型"
            return AlphaProviderStatus.UNAVAILABLE

        # 检查模型文件（active_model 是字典）
        model_file_path = Path(active_model["model_path"])
        if not model_file_path.exists():
            logger.warning(f"模型文件不存在: {model_file_path}")
            self._last_health_message = f"模型文件不存在: {model_file_path}"
            return AlphaProviderStatus.UNAVAILABLE

        latest_data_date = self._get_latest_data_date()
        if latest_data_date and latest_data_date < date.today() - timedelta(days=10):
            self._last_health_message = (
                f"Qlib 本地数据最新交易日为 {latest_data_date.isoformat()}，"
                "无法生成当天新鲜推理，将回退到缓存/降级结果。"
                "可先运行 `python manage.py build_qlib_data --check-only` 查看诊断，"
                "再执行 `python manage.py build_qlib_data` 进行最近窗口自建更新。"
            )
            return AlphaProviderStatus.DEGRADED

        # 检查缓存是否有数据
        has_recent_cache = self._has_recent_cache()
        if not has_recent_cache:
            self._last_health_message = "缓存无数据，需运行推理任务"
            return AlphaProviderStatus.DEGRADED

        self._last_health_message = None
        return AlphaProviderStatus.AVAILABLE

    @provider_safe()
    def get_stock_scores(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int = 30,
        pool_scope: AlphaPoolScope | None = None,
        user: object | None = None,
    ) -> AlphaResult:
        """
        获取股票评分

        1. 快路径：读缓存
        2. 如果缓存未命中，触发异步推理任务
        3. 如果本地没有可用 worker，同步执行一次推理并回读缓存
        4. 推理仍不可用时立即返回 degraded

        Args:
            universe_id: 股票池标识
            intended_trade_date: 计划交易日期
            top_n: 返回前 N 只

        Returns:
            AlphaResult
        """
        start_time = time.time()
        normalized_universe = _normalize_universe_id(universe_id)
        if normalized_universe is None:
            return self._create_error_result("Invalid universe ID")
        if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= 500:
            return self._create_error_result("top_n must be from 1 to 500")
        if pool_scope is not None and pool_scope.trade_date != intended_trade_date:
            return self._create_error_result("Pool scope trade date mismatch")
        universe_id = normalized_universe

        # 1. 快路径：读缓存
        cached = self._get_from_cache(
            universe_id,
            intended_trade_date,
            top_n,
            pool_scope=pool_scope,
        )
        if cached:
            latency_ms = int((time.time() - start_time) * 1000)
            cached.latency_ms = latency_ms
            if cached.status == "available" and cached.staleness_days is None:
                cached.staleness_days = 0
            logger.info(f"Qlib 缓存命中: {universe_id}@{intended_trade_date}")
            return cached

        # 2. 慢路径：触发异步推理任务
        logger.info(f"Qlib 缓存未命中，触发异步推理: {universe_id}@{intended_trade_date}")
        trigger_status = self._trigger_infer_task(
            universe_id,
            intended_trade_date,
            top_n,
            pool_scope=pool_scope,
        )
        inline_metadata: dict[str, object] = {}

        if trigger_status == "no_worker" and self._can_run_inline_inference(pool_scope):
            inline_metadata = self._run_inline_infer_task(
                universe_id=universe_id,
                intended_trade_date=intended_trade_date,
                top_n=top_n,
                pool_scope=pool_scope,
            )
            cached_after_inline = self._get_from_cache(
                universe_id,
                intended_trade_date,
                top_n,
                pool_scope=pool_scope,
            )
            if cached_after_inline:
                latency_ms = int((time.time() - start_time) * 1000)
                cached_after_inline.latency_ms = latency_ms
                if (
                    cached_after_inline.status == "available"
                    and cached_after_inline.staleness_days is None
                ):
                    cached_after_inline.staleness_days = 0
                cached_metadata = dict(cached_after_inline.metadata or {})
                cached_metadata.update(
                    {
                        "inline_inference_executed": True,
                        "inline_inference_result": inline_metadata,
                    }
                )
                cached_after_inline.metadata = cached_metadata
                logger.info(
                    "Qlib 同步推理完成并命中缓存: universe=%s, date=%s",
                    universe_id,
                    intended_trade_date,
                )
                return cached_after_inline
        elif trigger_status == "no_worker":
            inline_metadata = self._build_inline_skip_metadata(pool_scope)
            logger.info(
                "Qlib 同步推理跳过: universe=%s, date=%s, reason=%s",
                universe_id,
                intended_trade_date,
                inline_metadata.get("reason"),
            )

        # 3. 立即返回 degraded，让 registry 去走下一个 provider
        if trigger_status == "queued":
            error_message = "缓存缺失，已触发异步推理任务"
        elif trigger_status == "failed":
            error_message = "缓存缺失，推理任务投递失败"
        else:
            error_message = "缓存缺失，同步推理未生成可用结果"

        return AlphaResult(
            success=False,
            scores=[],
            source="qlib",
            timestamp=intended_trade_date.isoformat(),
            status="degraded",
            error_message=error_message,
            metadata={
                "universe_id": universe_id,
                "intended_trade_date": intended_trade_date.isoformat(),
                "async_task_triggered": trigger_status == "queued",
                "inference_trigger_status": trigger_status,
                "inline_inference_executed": trigger_status == "no_worker",
                "inline_inference_result": inline_metadata or None,
                "scope_hash": pool_scope.scope_hash if pool_scope else None,
                "scope_label": pool_scope.display_label if pool_scope else None,
                "scope_metadata": pool_scope.to_dict() if pool_scope else {},
            },
        )

    def _get_active_model(self) -> ActiveModelInfo | None:
        """
        获取激活的模型信息

        Returns:
            模型信息字典，如果没有激活的模型则返回 None
        """
        try:
            from ...infrastructure.models import QlibModelRegistryModel

            active_model = QlibModelRegistryModel._default_manager.filter(is_active=True).first()

            if not active_model:
                return None

            return {
                "model_name": active_model.model_name,
                "artifact_hash": active_model.artifact_hash,
                "model_type": active_model.model_type,
                "model_path": active_model.model_path,
                "feature_set_id": active_model.feature_set_id,
                "label_id": active_model.label_id,
                "data_version": active_model.data_version,
                "ic": float(active_model.ic) if active_model.ic else None,
                "icir": float(active_model.icir) if active_model.icir else None,
            }
        except Exception as exc:
            logger.error("获取激活模型失败: %s", type(exc).__name__)
            return None

    def _get_from_cache(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int,
        pool_scope: AlphaPoolScope | None = None,
    ) -> AlphaResult | None:
        """
        从缓存获取评分

        Args:
            universe_id: 股票池标识
            intended_trade_date: 计划交易日期
            top_n: 返回前 N 只

        Returns:
            AlphaResult，如果缓存不存在则返回 None
        """
        try:
            from ...infrastructure.models import AlphaScoreCacheModel

            # 获取激活的模型
            active_model = self._get_active_model()
            if not active_model:
                return None

            # 查询缓存
            cache_filter = {
                "universe_id": pool_scope.universe_id if pool_scope is not None else universe_id,
                "intended_trade_date": intended_trade_date,
                "provider_source": "qlib",
                "model_artifact_hash": active_model["artifact_hash"],
            }
            if pool_scope is not None:
                cache_filter["scope_hash"] = pool_scope.scope_hash

            cache = (
                AlphaScoreCacheModel._default_manager.filter(**cache_filter)
                .order_by("-created_at")
                .first()
            )

            if not cache:
                return None

            # 检查 staleness
            staleness_days = cache.get_staleness_days()
            if staleness_days > self.max_staleness_days:
                logger.debug(
                    "Qlib 缓存过期: %s 天 (最大允许 %s 天)",
                    staleness_days,
                    self.max_staleness_days,
                )
                # 仍然返回，但标记为 degraded
                status = "degraded"
            else:
                status = "available"

            # 解析评分
            scores = self._parse_scores(
                cache.scores,
                top_n,
                default_asof_date=cache.asof_date,
                default_intended_trade_date=cache.intended_trade_date,
            )

            # 添加审计信息
            enriched_scores: list[StockScore] = []
            for score in scores:
                # 创建新的 StockScore 实例（frozen）
                object_dict = score.to_dict()
                object_dict.update(
                    {
                        "model_id": cache.model_id,
                        "model_artifact_hash": cache.model_artifact_hash,
                        "feature_set_id": cache.feature_set_id,
                        "label_id": cache.label_id,
                        "data_version": cache.data_version,
                    }
                )
                enriched_scores.append(StockScore.from_dict(object_dict))
            scores = enriched_scores

            metrics_snapshot = cache.metrics_snapshot or {}

            return AlphaResult(
                success=True,
                scores=scores,
                source="qlib",
                timestamp=cache.created_at.isoformat(),
                status=status,
                staleness_days=staleness_days if staleness_days > 0 else None,
                metadata={
                    "cache_date": cache.intended_trade_date.isoformat(),
                    "asof_date": cache.asof_date.isoformat(),
                    "model_id": cache.model_id,
                    "model_artifact_hash": cache.model_artifact_hash,
                    "model_type": active_model.get("model_type"),
                    "ic": active_model.get("ic"),
                    "icir": active_model.get("icir"),
                    "scope_hash": cache.scope_hash,
                    "scope_label": cache.scope_label,
                    "scope_metadata": cache.scope_metadata or {},
                    "metrics_snapshot": metrics_snapshot,
                    **metrics_snapshot,
                },
            )

        except Exception as exc:
            logger.error("读取 Qlib 缓存失败: %s", type(exc).__name__)
            return None

    def _parse_scores(
        self,
        raw_scores: list[object],
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
        for item in raw_scores[:top_n]:
            try:
                if not isinstance(item, dict):
                    continue
                payload = dict(item)
                normalized_code = normalize_stock_code(payload.get("code"))
                if normalized_code is None:
                    continue
                payload["code"] = normalized_code
                raw_score = payload.get("score")
                raw_rank = payload.get("rank")
                raw_confidence = payload.get("confidence", 0.5)
                if (
                    raw_score is None
                    or raw_rank is None
                    or isinstance(raw_score, bool)
                    or isinstance(raw_rank, bool)
                    or isinstance(raw_confidence, bool)
                ):
                    continue
                score_value = float(raw_score)
                rank_value = int(raw_rank)
                confidence_value = float(raw_confidence)
                if (
                    not math.isfinite(score_value)
                    or not -1 <= score_value <= 1
                    or rank_value <= 0
                    or not math.isfinite(confidence_value)
                    or not 0 <= confidence_value <= 1
                ):
                    continue
                payload["score"] = score_value
                payload["rank"] = rank_value
                payload["confidence"] = confidence_value
                raw_factors = payload.get("factors", {})
                if not isinstance(raw_factors, dict):
                    continue
                factors: dict[str, float] = {}
                for raw_name, raw_value in raw_factors.items():
                    if isinstance(raw_value, bool):
                        continue
                    factor_value = float(raw_value)
                    if math.isfinite(factor_value):
                        factors[str(raw_name)] = factor_value
                payload["factors"] = factors
                payload.setdefault("source", "qlib")
                if default_asof_date and not payload.get("asof_date"):
                    payload["asof_date"] = default_asof_date.isoformat()
                if default_intended_trade_date:
                    payload["intended_trade_date"] = default_intended_trade_date.isoformat()
                score = StockScore.from_dict(payload)
                if (
                    score.asof_date is not None
                    and score.intended_trade_date is not None
                    and score.asof_date > score.intended_trade_date
                ):
                    continue
                scores.append(score)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("解析 Qlib 评分失败: %s", type(exc).__name__)
                continue

        return scores

    def _has_recent_cache(self) -> bool:
        """
        检查是否有最近的缓存

        Returns:
            是否有最近 10 天的缓存
        """
        try:
            from ...infrastructure.models import AlphaScoreCacheModel

            cutoff_date = date.today() - timedelta(days=10)

            has_cache = AlphaScoreCacheModel._default_manager.filter(
                provider_source="qlib", intended_trade_date__gte=cutoff_date
            ).exists()

            return has_cache
        except Exception as exc:
            logger.error("检查缓存失败: %s", type(exc).__name__)
            return False

    def _get_latest_data_date(self) -> date | None:
        """Return the latest trading date available in the local qlib dataset."""
        try:
            from apps.alpha.infrastructure.qlib_runtime_init import initialize_qlib_runtime
            from core.integration.runtime_settings import get_runtime_qlib_config

            qlib = import_module("qlib")
            data_api = import_module("qlib.data").D
            qlib_config = get_runtime_qlib_config()
            if qlib_config.get("enabled") is not True or qlib_config.get(
                "must_not_use_for_decision",
                False,
            ):
                return None
            provider_uri = str(qlib_config.get("provider_uri") or "").strip()
            region = str(qlib_config.get("region") or "CN")
            if not provider_uri:
                return None

            initialize_qlib_runtime(
                provider_uri=provider_uri,
                region=region,
                qlib_module=qlib,
            )

            calendar = data_api.calendar(start_time="2000-01-01", end_time="2100-12-31")
            if len(calendar) == 0:
                return None
            return _normalize_calendar_date(calendar[-1])
        except Exception as exc:
            logger.debug("读取本地 Qlib 数据最新日期失败: %s", type(exc).__name__)
            return None

    def _trigger_infer_task(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int,
        pool_scope: AlphaPoolScope | None = None,
    ) -> str:
        """
        触发异步推理任务

        Args:
            universe_id: 股票池标识
            intended_trade_date: 计划交易日期
            top_n: 返回前 N 只
        """
        throttle_key = (
            f"alpha:qlib_infer_trigger:{universe_id}:{intended_trade_date.isoformat()}:{top_n}"
        )
        if cache.get(throttle_key):
            logger.info(
                "Qlib 推理任务近期已触发，跳过重复投递: universe=%s, date=%s, top_n=%s",
                universe_id,
                intended_trade_date,
                top_n,
            )
            return "queued"
        try:
            from apps.alpha.application.tasks import qlib_predict_scores

            queue_name = self._resolve_live_inference_queue()
            if queue_name is None:
                logger.info(
                    "未检测到可用 Celery worker，准备同步执行 Qlib 推理: "
                    "universe=%s, date=%s, top_n=%s",
                    universe_id,
                    intended_trade_date,
                    top_n,
                )
                return "no_worker"

            # 异步投递任务，不等待结果
            result = qlib_predict_scores.apply_async(
                args=[universe_id, intended_trade_date.isoformat(), top_n],
                kwargs={
                    "scope_payload": pool_scope.to_dict() if pool_scope else None,
                },
                queue=queue_name,
            )

            logger.info(
                f"已触发 Qlib 推理任务: universe={universe_id}, "
                f"date={intended_trade_date}, top_n={top_n}, "
                f"queue={queue_name}, task_id={result.id}"
            )
            cache.set(throttle_key, result.id, timeout=180)
            return "queued"

        except Exception as exc:
            error_type = type(exc).__name__
            logger.error("触发推理任务失败: %s", error_type)
            # 发送告警通知
            self._send_inference_failure_alert(
                universe_id,
                intended_trade_date,
                error_type,
            )
            return "failed"

    def _resolve_inference_queue(self) -> str:
        """Pick a live inference queue, falling back to the default worker queue in dev."""
        return self._resolve_live_inference_queue() or "qlib_infer"

    def _resolve_live_inference_queue(self) -> str | None:
        """Return a live queue name, or None when no worker can consume the task."""
        preferred_queue = "qlib_infer"
        fallback_queue = "celery"

        try:
            inspect = current_app.control.inspect(timeout=1)
            if inspect is None:
                return None

            active_queues = inspect.active_queues()
            if not active_queues:
                return None
            queue_names = {
                queue_info.get("name")
                for worker_queues in active_queues.values()
                for queue_info in worker_queues
                if queue_info.get("name")
            }
            if preferred_queue in queue_names:
                return preferred_queue
            if fallback_queue in queue_names:
                logger.info("未检测到 qlib_infer 消费者，回退到默认 celery 队列投递 Qlib 推理任务")
                return fallback_queue
        except Exception as exc:
            logger.debug("检查 Celery 队列时出错: %s", type(exc).__name__)

        return None

    def _run_inline_infer_task(
        self,
        *,
        universe_id: str,
        intended_trade_date: date,
        top_n: int,
        pool_scope: AlphaPoolScope | None = None,
    ) -> dict[str, object]:
        """Run one local inference when there is no Celery worker to consume the task."""
        lock_key = (
            "alpha:qlib_inline_infer_lock:"
            f"{universe_id}:{intended_trade_date.isoformat()}:{top_n}"
        )
        if not cache.add(lock_key, "1", timeout=600):
            logger.info(
                "Qlib 同步推理已在执行中，跳过重复执行: universe=%s, date=%s, top_n=%s",
                universe_id,
                intended_trade_date,
                top_n,
            )
            return {
                "status": "skipped",
                "reason": "inline_inference_already_running",
            }

        try:
            from apps.alpha.application.tasks import qlib_predict_scores

            logger.info(
                "开始 Qlib 同步推理: universe=%s, date=%s, top_n=%s",
                universe_id,
                intended_trade_date,
                top_n,
            )
            task_result = qlib_predict_scores.apply(
                args=[universe_id, intended_trade_date.isoformat(), top_n],
                kwargs={
                    "scope_payload": pool_scope.to_dict() if pool_scope else None,
                },
            )
            payload = task_result.get(propagate=False)
            failed = bool(getattr(task_result, "failed", lambda: False)())
            if failed:
                logger.info(
                    "Qlib 同步推理任务失败: universe=%s, date=%s",
                    universe_id,
                    intended_trade_date,
                )
                return {
                    "status": "failed",
                    "error_code": "inline_inference_failed",
                }
            return {
                "status": "completed",
                "result": self._summarize_inline_payload(payload),
            }
        except Exception as exc:
            logger.error(
                "Qlib 同步推理执行失败: universe=%s, date=%s, error_type=%s",
                universe_id,
                intended_trade_date,
                type(exc).__name__,
            )
            return {
                "status": "failed",
                "error_code": "inline_inference_exception",
            }
        finally:
            cache.delete(lock_key)

    @staticmethod
    def _summarize_inline_payload(payload: object) -> dict[str, object] | None:
        """Expose only stable, non-sensitive inline task outcome fields."""
        if not isinstance(payload, dict):
            return None
        summary: dict[str, object] = {}
        status = payload.get("status")
        if status in {"success", "completed", "skipped"}:
            summary["status"] = status
        for key in ("count", "scores_count"):
            value = payload.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                summary[key] = value
        return summary or None

    def _can_run_inline_inference(self, pool_scope: AlphaPoolScope | None) -> bool:
        """Only small scoped pools are safe to run inside the request process."""
        if pool_scope is None:
            return False
        return pool_scope.pool_size <= self.INLINE_INFERENCE_MAX_POOL_SIZE

    def _build_inline_skip_metadata(
        self,
        pool_scope: AlphaPoolScope | None,
    ) -> dict[str, object]:
        if pool_scope is None:
            return {
                "status": "skipped",
                "reason": "inline_inference_requires_scoped_pool",
                "max_pool_size": self.INLINE_INFERENCE_MAX_POOL_SIZE,
            }
        return {
            "status": "skipped",
            "reason": "inline_inference_pool_too_large",
            "pool_size": pool_scope.pool_size,
            "max_pool_size": self.INLINE_INFERENCE_MAX_POOL_SIZE,
        }

    def _send_inference_failure_alert(
        self,
        universe_id: str,
        intended_trade_date: date,
        error_type: str,
    ) -> None:
        """
        发送推理失败告警

        Args:
            universe_id: 股票池标识
            intended_trade_date: 计划交易日期
            error_type: 异常类型
        """
        try:
            # 创建告警记录到数据库
            from ...infrastructure.models import AlphaAlertModel

            AlphaAlertModel._default_manager.create(
                alert_type="inference_failure",
                severity="warning",
                title=f"Qlib 推理任务触发失败: {universe_id}@{intended_trade_date}",
                message="无法触发异步推理任务，将使用降级数据源。",
                metadata={
                    "universe_id": universe_id,
                    "intended_trade_date": intended_trade_date.isoformat(),
                    "error_type": error_type,
                    "provider": "qlib",
                },
            )
            logger.warning(f"已创建推理失败告警: {universe_id}@{intended_trade_date}")
        except Exception as exc:
            # 告警失败不应影响主流程
            logger.error("发送推理失败告警时出错: %s", type(exc).__name__)

    def get_factor_exposure(self, stock_code: str, trade_date: date) -> dict[str, float]:
        """
        获取因子暴露（带异常保护）

        Args:
            stock_code: 股票代码
            trade_date: 交易日期

        Returns:
            因子暴露字典
        """
        try:
            pd = get_pandas()
            data_api = import_module("qlib.data").D
            normalized_code = normalize_stock_code(stock_code)
            if normalized_code is None:
                return {}

            # Qlib 使用 D.features 获取因子值
            trade_date_str = trade_date.strftime("%Y-%m-%d")
            instruments = [normalized_code]

            # Alpha360 常用因子列表
            factor_names = [
                "$close/Ref($close, 1) - 1",  # 日收益率 (momentum_1d)
                "$close/Ref($close, 5) - 1",  # 5日动量 (momentum_5d)
                "$close/Ref($close, 20) - 1",  # 20日动量 (momentum_20d)
                "$volume/Ref($volume, 1) - 1",  # 量比 (volume_ratio)
                "Std($close, 20)/$close",  # 20日波动率 (volatility_20d)
            ]
            factor_labels = [
                "momentum_1d",
                "momentum_5d",
                "momentum_20d",
                "volume_ratio",
                "volatility_20d",
            ]

            df = data_api.features(
                instruments=instruments,
                fields=factor_names,
                start_time=trade_date_str,
                end_time=trade_date_str,
            )

            if df is None or df.empty:
                logger.debug(f"股票 {stock_code} 在 {trade_date} 无因子数据")
                return {}

            # 取最后一行，转为 dict
            row = df.iloc[-1]
            result = {}
            for i, label in enumerate(factor_labels):
                val = row.iloc[i]
                if pd.notna(val):
                    numeric_value = float(val)
                    if math.isfinite(numeric_value):
                        result[label] = numeric_value

            return result

        except ImportError:
            logger.debug("Qlib 未安装，无法获取因子暴露")
            return {}
        except Exception as exc:
            logger.error("获取因子暴露失败: %s", type(exc).__name__)
            return {}

    def get_universe_stocks(self, universe_id: str) -> list[str]:
        """
        获取股票池的股票列表

        Args:
            universe_id: 股票池标识

        Returns:
            股票代码列表
        """
        qlib_universe = _normalize_universe_id(universe_id)
        if qlib_universe is None:
            logger.warning(f"不支持的股票池: {universe_id}")
            return []

        try:
            data_api = import_module("qlib.data").D

            instruments = data_api.instruments(market=qlib_universe)
            # D.instruments 返回的可能是 Instruments 对象，需要 list_instruments 解析
            if hasattr(instruments, "__iter__") and not isinstance(instruments, str):
                stock_list = list(instruments)
            else:
                # 使用 D.list_instruments 获取具体股票列表
                stock_list = data_api.list_instruments(
                    instruments=instruments,
                    as_list=True,
                )

            normalized_stocks = sorted(
                {
                    normalized
                    for raw_code in stock_list
                    if (normalized := normalize_stock_code(raw_code)) is not None
                }
            )
            logger.info(f"获取股票池 {qlib_universe}: {len(normalized_stocks)} 只股票")
            return normalized_stocks

        except ImportError:
            logger.debug("Qlib 未安装，无法获取股票池")
            return []
        except Exception as exc:
            logger.error("获取股票池失败: %s", type(exc).__name__)
            return []

    def load_model(self, model_path: str) -> bool:
        """
        加载 Qlib 模型

        Args:
            model_path: 模型文件路径

        Returns:
            是否成功加载
        """
        try:
            model_file = Path(model_path)

            if not model_file.exists():
                logger.error(f"模型文件不存在: {model_path}")
                return False

            # 加载模型
            with open(model_file, "rb") as f:
                self._model = pickle.load(f)

            logger.info(f"成功加载模型: {model_path}")
            return True

        except Exception as exc:
            logger.error("加载模型失败: %s", type(exc).__name__)
            return False

    def predict(self, universe_id: str, trade_date: date) -> dict[str, float]:
        """
        执行预测（同步方法，用于测试）

        Args:
            universe_id: 股票池标识
            trade_date: 交易日期

        Returns:
            股票代码到评分的映射
        """
        if not self._model:
            logger.error("模型未加载")
            return {}

        try:
            from apps.alpha.application.tasks import _resolve_qlib_handler_class

            pd = get_pandas()
            data_api = import_module("qlib.data").D
            dataset_class = import_module("qlib.data.dataset").DatasetH
            normalized_universe = _normalize_universe_id(universe_id)
            if normalized_universe is None:
                return {}
            trade_date_str = trade_date.strftime("%Y-%m-%d")
            # 需要几天的历史数据给 Alpha360 做特征
            lookback_start = (trade_date - timedelta(days=60)).strftime("%Y-%m-%d")

            # 获取股票池
            instruments = data_api.instruments(market=normalized_universe)

            handler_cls = _resolve_qlib_handler_class(
                self._active_model_info.get("feature_set_id") if self._active_model_info else None
            )
            handler = handler_cls(
                start_time=lookback_start,
                end_time=trade_date_str,
                fit_start_time=lookback_start,
                fit_end_time=trade_date_str,
                instruments=instruments,
            )

            dataset = dataset_class(
                handler=handler,
                segments={"test": (pd.Timestamp(trade_date_str), pd.Timestamp(trade_date_str))},
            )

            predict_method = getattr(self._model, "predict", None)
            if not callable(predict_method):
                return {}
            pred = predict_method(dataset)

            # pred 可能是 Series 或 DataFrame，统一转为 {stock_code: score}
            if isinstance(pred, pd.DataFrame):
                if pred.empty:
                    return {}
                # 多级索引 (datetime, instrument)
                if isinstance(pred.index, pd.MultiIndex):
                    last_date = pred.index.get_level_values(0)[-1]
                    pred = pred.loc[last_date]
                scores = pred.iloc[:, 0].to_dict() if pred.ndim > 1 else pred.to_dict()
            elif isinstance(pred, pd.Series):
                if isinstance(pred.index, pd.MultiIndex):
                    last_date = pred.index.get_level_values(0)[-1]
                    pred = pred.loc[last_date]
                scores = pred.to_dict()
            else:
                scores = {}

            # 确保值为 float
            normalized_scores: dict[str, float] = {}
            for raw_code, raw_score in scores.items():
                normalized_code = normalize_stock_code(raw_code)
                if normalized_code is None or not pd.notna(raw_score):
                    continue
                numeric_score = float(raw_score)
                if math.isfinite(numeric_score):
                    normalized_scores[normalized_code] = numeric_score
            return normalized_scores

        except ImportError:
            logger.debug("Qlib 未安装，无法执行预测")
            return {}
        except Exception as exc:
            logger.error("预测失败: %s", type(exc).__name__)
            return {}
