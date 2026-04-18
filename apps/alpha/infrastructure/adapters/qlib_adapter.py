"""
Qlib Alpha Provider

使用 Qlib 模型进行推理的 Provider。
优先级为 1（最高），通过缓存提供快速响应。
"""

import hashlib
import json
import logging
import pickle
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from celery import current_app
from django.core.cache import cache

from ...domain.entities import AlphaPoolScope, AlphaResult, StockScore, normalize_stock_code
from ...domain.interfaces import AlphaProviderStatus
from .base import BaseAlphaProvider, create_stock_score, provider_safe, qlib_safe

logger = logging.getLogger(__name__)


def _normalize_calendar_date(value) -> date | None:
    """Convert qlib calendar entries to Python dates."""
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class QlibAlphaProvider(BaseAlphaProvider):
    """
    Qlib Alpha 提供者

    使用 Qlib 训练的机器学习模型进行股票评分。
    优先级为 1（最高），但只读缓存，不直接调用 Qlib。

    工作流程：
    1. 快路径：从 AlphaScoreCache 读取缓存
    2. 慢路径：触发异步推理任务（Celery）
    3. 立即返回 degraded，让 registry 去尝试下一个 provider

    Attributes:
        priority: 1（最高优先级）
        max_staleness_days: 2 天（ML 模型数据要求新鲜）

    Example:
        >>> provider = QlibAlphaProvider()
        >>> result = provider.get_stock_scores("csi300", date.today())
        >>> # 第一次可能返回 degraded（缓存未命中）
        >>> # 第二次命中缓存返回 available
    """

    def __init__(
        self,
        provider_uri: str = "",
        model_path: str = "",
        region: str = "CN"
    ):
        """
        初始化 Qlib Provider

        Args:
            provider_uri: Qlib 数据路径
            model_path: 模型存储路径
            region: 区域配置
        """
        super().__init__()
        if not provider_uri or not model_path:
            from django.conf import settings
            qlib_settings = settings.QLIB_SETTINGS
            provider_uri = provider_uri or qlib_settings.get("provider_uri", "")
            model_path = model_path or qlib_settings.get("model_path", "")
        self._data_path = Path(provider_uri).expanduser()
        self._model_path = Path(model_path)
        self._region = region
        self._qlib_initialized = False
        self._model = None
        self._active_model_info = None

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
        model_file_path = Path(active_model['model_path'])
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
        user=None,
    ) -> AlphaResult:
        """
        获取股票评分

        1. 快路径：读缓存
        2. 如果缓存未命中，触发异步推理任务
        3. 立即返回 degraded

        Args:
            universe_id: 股票池标识
            intended_trade_date: 计划交易日期
            top_n: 返回前 N 只

        Returns:
            AlphaResult
        """
        start_time = time.time()

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
        self._trigger_infer_task(
            universe_id,
            intended_trade_date,
            top_n,
            pool_scope=pool_scope,
        )

        # 3. 立即返回 degraded，让 registry 去走下一个 provider
        return AlphaResult(
            success=False,
            scores=[],
            source="qlib",
            timestamp=intended_trade_date.isoformat(),
            status="degraded",
            error_message="缓存缺失，已触发异步推理任务",
            metadata={
                "universe_id": universe_id,
                "intended_trade_date": intended_trade_date.isoformat(),
                "async_task_triggered": True,
                "scope_hash": pool_scope.scope_hash if pool_scope else None,
                "scope_label": pool_scope.display_label if pool_scope else None,
                "scope_metadata": pool_scope.to_dict() if pool_scope else {},
            }
        )

    def _get_active_model(self) -> dict | None:
        """
        获取激活的模型信息

        Returns:
            模型信息字典，如果没有激活的模型则返回 None
        """
        try:
            from ...infrastructure.models import QlibModelRegistryModel

            active_model = QlibModelRegistryModel._default_manager.filter(
                is_active=True
            ).first()

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
        except Exception as e:
            logger.error(f"获取激活模型失败: {e}")
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

            cache = AlphaScoreCacheModel._default_manager.filter(
                **cache_filter
            ).order_by("-created_at").first()

            if not cache:
                return None

            # 检查 staleness
            staleness_days = cache.get_staleness_days()
            if staleness_days > self.max_staleness_days:
                logger.warning(
                    f"Qlib 缓存过期: {staleness_days} 天 "
                    f"(最大允许 {self.max_staleness_days} 天)"
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
            for score in scores:
                # 创建新的 StockScore 实例（frozen）
                object_dict = score.to_dict()
                object_dict.update({
                    "model_id": cache.model_id,
                    "model_artifact_hash": cache.model_artifact_hash,
                    "feature_set_id": cache.feature_set_id,
                    "label_id": cache.label_id,
                    "data_version": cache.data_version,
                })
                # 更新列表中的元素
                idx = scores.index(score)
                scores[idx] = StockScore.from_dict(object_dict)

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
                }
            )

        except Exception as e:
            logger.error(f"读取 Qlib 缓存失败: {e}", exc_info=True)
            return None

    def _parse_scores(
        self,
        raw_scores: list,
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
        scores = []
        for item in raw_scores[:top_n]:
            try:
                payload = dict(item)
                normalized_code = normalize_stock_code(payload.get("code"))
                if normalized_code:
                    payload["code"] = normalized_code
                payload.setdefault("source", "qlib")
                if default_asof_date and not payload.get("asof_date"):
                    payload["asof_date"] = default_asof_date.isoformat()
                if default_intended_trade_date and not payload.get("intended_trade_date"):
                    payload["intended_trade_date"] = default_intended_trade_date.isoformat()
                scores.append(StockScore.from_dict(payload))
            except Exception as e:
                logger.warning(f"解析评分失败: {item}, error: {e}")
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
                provider_source="qlib",
                intended_trade_date__gte=cutoff_date
            ).exists()

            return has_cache
        except Exception as e:
            logger.error(f"检查缓存失败: {e}")
            return False

    def _get_latest_data_date(self) -> date | None:
        """Return the latest trading date available in the local qlib dataset."""
        try:
            import qlib
            from qlib.data import D

            from apps.account.infrastructure.models import SystemSettingsModel

            qlib_config = SystemSettingsModel.get_runtime_qlib_config()
            provider_uri = qlib_config.get("provider_uri", "~/.qlib/qlib_data/cn_data")
            region = qlib_config.get("region", "CN")

            if not hasattr(self, "_qlib_initialized_for_calendar"):
                qlib.init(
                    provider_uri=provider_uri,
                    region=str(region).lower(),
                )
                self._qlib_initialized_for_calendar = True

            calendar = D.calendar(start_time="2000-01-01", end_time="2100-12-31")
            if len(calendar) == 0:
                return None
            return _normalize_calendar_date(calendar[-1])
        except Exception as exc:
            logger.debug("读取本地 Qlib 数据最新日期失败: %s", exc)
            return None

    def _trigger_infer_task(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int,
        pool_scope: AlphaPoolScope | None = None,
    ) -> None:
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
            return
        try:
            from apps.alpha.application.tasks import qlib_predict_scores

            queue_name = self._resolve_inference_queue()

            # 异步投递任务，不等待结果
            result = qlib_predict_scores.apply_async(
                args=[universe_id, intended_trade_date.isoformat(), top_n],
                kwargs={
                    "scope_payload": pool_scope.to_dict() if pool_scope else None,
                },
                queue=queue_name
            )

            logger.info(
                f"已触发 Qlib 推理任务: universe={universe_id}, "
                f"date={intended_trade_date}, top_n={top_n}, "
                f"queue={queue_name}, task_id={result.id}"
            )
            cache.set(throttle_key, result.id, timeout=180)

        except Exception as e:
            logger.error(f"触发推理任务失败: {e}", exc_info=True)
            # 发送告警通知
            self._send_inference_failure_alert(universe_id, intended_trade_date, str(e))

    def _resolve_inference_queue(self) -> str:
        """Pick a live inference queue, falling back to the default worker queue in dev."""
        preferred_queue = "qlib_infer"
        fallback_queue = "celery"

        try:
            inspect = current_app.control.inspect(timeout=1)
            if inspect is None:
                return preferred_queue

            active_queues = inspect.active_queues() or {}
            queue_names = {
                queue_info.get("name")
                for worker_queues in active_queues.values()
                for queue_info in worker_queues
                if queue_info.get("name")
            }
            if preferred_queue in queue_names:
                return preferred_queue
            if fallback_queue in queue_names:
                logger.warning(
                    "未检测到 qlib_infer 消费者，回退到默认 celery 队列投递 Qlib 推理任务"
                )
                return fallback_queue
        except Exception as exc:
            logger.debug("检查 Celery 队列时出错，继续使用 qlib_infer: %s", exc)

        return preferred_queue

    def _send_inference_failure_alert(
        self,
        universe_id: str,
        intended_trade_date: date,
        error_message: str
    ) -> None:
        """
        发送推理失败告警

        Args:
            universe_id: 股票池标识
            intended_trade_date: 计划交易日期
            error_message: 错误信息
        """
        try:
            # 创建告警记录到数据库
            from ...infrastructure.models import AlphaAlertModel

            AlphaAlertModel._default_manager.create(
                alert_type="inference_failure",
                severity="warning",
                title=f"Qlib 推理任务触发失败: {universe_id}@{intended_trade_date}",
                message=f"无法触发异步推理任务，将使用降级数据源。\n错误: {error_message}",
                metadata={
                    "universe_id": universe_id,
                    "intended_trade_date": intended_trade_date.isoformat(),
                    "error": error_message,
                    "provider": "qlib",
                }
            )
            logger.warning(f"已创建推理失败告警: {universe_id}@{intended_trade_date}")
        except Exception as e:
            # 告警失败不应影响主流程
            logger.error(f"发送推理失败告警时出错: {e}")

    def get_factor_exposure(
        self,
        stock_code: str,
        trade_date: date
    ) -> dict[str, float]:
        """
        获取因子暴露（带异常保护）

        Args:
            stock_code: 股票代码
            trade_date: 交易日期

        Returns:
            因子暴露字典
        """
        try:
            import pandas as pd
            from qlib.data import D

            # Qlib 使用 D.features 获取因子值
            trade_date_str = trade_date.strftime("%Y-%m-%d")
            instruments = [stock_code]

            # Alpha360 常用因子列表
            factor_names = [
                "$close/Ref($close, 1) - 1",   # 日收益率 (momentum_1d)
                "$close/Ref($close, 5) - 1",   # 5日动量 (momentum_5d)
                "$close/Ref($close, 20) - 1",  # 20日动量 (momentum_20d)
                "$volume/Ref($volume, 1) - 1",  # 量比 (volume_ratio)
                "Std($close, 20)/$close",        # 20日波动率 (volatility_20d)
            ]
            factor_labels = [
                "momentum_1d", "momentum_5d", "momentum_20d",
                "volume_ratio", "volatility_20d",
            ]

            df = D.features(
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
                    result[label] = float(val)

            return result

        except ImportError:
            logger.debug("Qlib 未安装，无法获取因子暴露")
            return {}
        except Exception as e:
            logger.error(f"获取因子暴露失败: {e}")
            return {}

    def get_universe_stocks(self, universe_id: str) -> list[str]:
        """
        获取股票池的股票列表

        Args:
            universe_id: 股票池标识

        Returns:
            股票代码列表
        """
        # 股票池映射
        universe_map = {
            "csi300": "csi300",
            "csi500": "csi500",
            "sse50": "sse50",
            "csi1000": "csi1000",
        }

        qlib_universe = universe_map.get(universe_id)
        if not qlib_universe:
            logger.warning(f"不支持的股票池: {universe_id}")
            return []

        try:
            from qlib.data import D

            instruments = D.instruments(market=qlib_universe)
            # D.instruments 返回的可能是 Instruments 对象，需要 list_instruments 解析
            if hasattr(instruments, '__iter__') and not isinstance(instruments, str):
                stock_list = list(instruments)
            else:
                # 使用 D.list_instruments 获取具体股票列表
                stock_list = D.list_instruments(
                    instruments=instruments,
                    as_list=True,
                )

            logger.info(f"获取股票池 {qlib_universe}: {len(stock_list)} 只股票")
            return stock_list

        except ImportError:
            logger.debug("Qlib 未安装，无法获取股票池")
            return []
        except Exception as e:
            logger.error(f"获取股票池失败: {e}")
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

        except Exception as e:
            logger.error(f"加载模型失败: {e}", exc_info=True)
            return False

    def predict(
        self,
        universe_id: str,
        trade_date: date
    ) -> dict[str, float]:
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
            import pandas as pd
            from qlib.data import D
            from qlib.data.dataset import DatasetH

            from apps.alpha.application.tasks import _resolve_qlib_handler_class

            trade_date_str = trade_date.strftime("%Y-%m-%d")
            # 需要几天的历史数据给 Alpha360 做特征
            lookback_start = (trade_date - timedelta(days=60)).strftime("%Y-%m-%d")

            # 获取股票池
            instruments = D.instruments(market=universe_id)

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

            dataset = DatasetH(
                handler=handler,
                segments={"test": (pd.Timestamp(trade_date_str), pd.Timestamp(trade_date_str))},
            )

            pred = self._model.predict(dataset)

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
            return {str(k): float(v) for k, v in scores.items() if pd.notna(v)}

        except ImportError:
            logger.debug("Qlib 未安装，无法执行预测")
            return {}
        except Exception as e:
            logger.error(f"预测失败: {e}", exc_info=True)
            return {}
