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

from ...domain.entities import AlphaResult, StockScore
from ...domain.interfaces import AlphaProviderStatus
from .base import BaseAlphaProvider, qlib_safe, create_stock_score, provider_safe


logger = logging.getLogger(__name__)


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
        provider_uri: str = "~/.qlib/qlib_data/cn_data",
        model_path: str = "/models/qlib",
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
            return AlphaProviderStatus.UNAVAILABLE

        # 检查是否有激活的模型
        active_model = self._get_active_model()
        if not active_model:
            logger.warning("没有激活的 Qlib 模型")
            return AlphaProviderStatus.UNAVAILABLE

        # 检查模型文件
        model_file_path = Path(active_model.model_path)
        if not model_file_path.exists():
            logger.warning(f"模型文件不存在: {model_file_path}")
            return AlphaProviderStatus.UNAVAILABLE

        # 检查缓存是否有数据
        has_recent_cache = self._has_recent_cache()
        if not has_recent_cache:
            return AlphaProviderStatus.DEGRADED

        return AlphaProviderStatus.AVAILABLE

    @provider_safe()
    def get_stock_scores(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int = 30
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
        cached = self._get_from_cache(universe_id, intended_trade_date, top_n)
        if cached:
            latency_ms = int((time.time() - start_time) * 1000)
            cached.latency_ms = latency_ms
            cached.staleness_days = 0
            logger.info(f"Qlib 缓存命中: {universe_id}@{intended_trade_date}")
            return cached

        # 2. 慢路径：触发异步推理任务
        logger.info(f"Qlib 缓存未命中，触发异步推理: {universe_id}@{intended_trade_date}")
        self._trigger_infer_task(universe_id, intended_trade_date, top_n)

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
            }
        )

    def _get_active_model(self) -> Optional[Dict]:
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
        top_n: int
    ) -> Optional[AlphaResult]:
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
            cache = AlphaScoreCacheModel._default_manager.filter(
                universe_id=universe_id,
                intended_trade_date=intended_trade_date,
                provider_source="qlib",
                model_artifact_hash=active_model["artifact_hash"]
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
            scores = self._parse_scores(cache.scores, top_n)

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
                }
            )

        except Exception as e:
            logger.error(f"读取 Qlib 缓存失败: {e}", exc_info=True)
            return None

    def _parse_scores(self, raw_scores: list, top_n: int) -> List[StockScore]:
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
                scores.append(StockScore.from_dict(item))
            except Exception as e:
                logger.warning(f"解析评分失败: {item}, error: {e}")
                continue

        return scores

    def _has_recent_cache(self) -> bool:
        """
        检查是否有最近的缓存

        Returns:
            是否有最近 7 天的缓存
        """
        try:
            from ...infrastructure.models import AlphaScoreCacheModel

            cutoff_date = date.today() - timedelta(days=7)

            has_cache = AlphaScoreCacheModel._default_manager.filter(
                provider_source="qlib",
                intended_trade_date__gte=cutoff_date
            ).exists()

            return has_cache
        except Exception as e:
            logger.error(f"检查缓存失败: {e}")
            return False

    def _trigger_infer_task(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int
    ) -> None:
        """
        触发异步推理任务

        Args:
            universe_id: 股票池标识
            intended_trade_date: 计划交易日期
            top_n: 返回前 N 只
        """
        try:
            from ..tasks import qlib_predict_scores

            # 异步投递任务，不等待结果
            qlib_predict_scores.apply_async(
                args=[universe_id, intended_trade_date.isoformat(), top_n],
                queue="qlib_infer"
            )

            logger.info(
                f"已触发 Qlib 推理任务: universe={universe_id}, "
                f"date={intended_trade_date}, top_n={top_n}"
            )

        except Exception as e:
            logger.error(f"触发推理任务失败: {e}", exc_info=True)

    def get_factor_exposure(
        self,
        stock_code: str,
        trade_date: date
    ) -> Dict[str, float]:
        """
        获取因子暴露（带异常保护）

        Args:
            stock_code: 股票代码
            trade_date: 交易日期

        Returns:
            因子暴露字典
        """
        try:
            # TODO: 实现从 Qlib 获取因子暴露
            # 这里需要 Qlib 的 API 来获取单个股票的因子值
            return {}
        except Exception as e:
            logger.error(f"获取因子暴露失败: {e}")
            return {}

    def get_universe_stocks(self, universe_id: str) -> List[str]:
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
            # TODO: 使用 Qlib API 获取股票池
            # from qlib.data import D
            # instruments = D.instruments(market="csi300")
            # return list(instruments)
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
    ) -> Dict[str, float]:
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
            # TODO: 使用 Qlib API 执行预测
            # scores = self._model.predict(dates=trade_date)
            return {}
        except Exception as e:
            logger.error(f"预测失败: {e}", exc_info=True)
            return {}

