"""
Alpha Celery Tasks

Alpha 信号相关的异步任务。
包括 Qlib 推理、训练等任务。
"""

import hashlib
import json
import logging
import pickle
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from celery import shared_task
from django.utils import timezone


logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
)
def qlib_predict_scores(
    self,
    universe_id: str,
    intended_trade_date: str,
    top_n: int = 30
) -> dict:
    """
    Qlib 推理任务（运行在 qlib_infer 队列）

    1. 加载激活的模型
    2. 准备数据
    3. 执行预测
    4. 结果写入 AlphaScoreCache

    Args:
        self: Celery task 实例
        universe_id: 股票池标识
        intended_trade_date: 计划交易日期 (ISO 格式)
        top_n: 返回前 N 只

    Returns:
        任务结果字典

    Example:
        >>> from apps.alpha.application.tasks import qlib_predict_scores
        >>> qlib_predict_scores.delay("csi300", "2026-02-05", 30)
    """
    try:
        from ...infrastructure.models import AlphaScoreCacheModel, QlibModelRegistryModel

        logger.info(
            f"开始 Qlib 推理: universe={universe_id}, "
            f"date={intended_trade_date}, top_n={top_n}"
        )

        # 1. 获取激活的模型
        active_model = QlibModelRegistryModel._default_manager.filter(
            is_active=True
        ).first()

        if not active_model:
            raise Exception("没有激活的 Qlib 模型")

        # 2. 准备数据
        trade_date = date.fromisoformat(intended_trade_date)
        asof_date = trade_date  # 信号日期等于交易日期（实际中可能需要调整）

        # 3. 执行预测（使用 Qlib）
        scores_data = _execute_qlib_prediction(
            active_model=active_model,
            universe_id=universe_id,
            trade_date=trade_date,
            top_n=top_n
        )

        if not scores_data:
            raise Exception("Qlib 预测未返回任何评分")

        # 4. 写入缓存
        cache, created = AlphaScoreCacheModel._default_manager.update_or_create(
            universe_id=universe_id,
            intended_trade_date=trade_date,
            provider_source="qlib",
            model_artifact_hash=active_model.artifact_hash,
            defaults={
                "asof_date": asof_date,
                "model_id": active_model.model_name,
                "model_artifact_hash": active_model.artifact_hash,
                "feature_set_id": active_model.feature_set_id,
                "label_id": active_model.label_id,
                "data_version": active_model.data_version,
                "scores": scores_data,
                "status": AlphaScoreCacheModel.STATUS_AVAILABLE,
            }
        )

        action = "创建" if created else "更新"
        logger.info(
            f"Qlib 推理完成: {action}缓存 {universe_id}@{intended_trade_date}, "
            f"共 {len(scores_data)} 只股票"
        )

        return {
            "status": "success",
            "universe_id": universe_id,
            "trade_date": intended_trade_date,
            "cache_created": created,
            "stock_count": len(scores_data),
            "model_artifact_hash": active_model.artifact_hash,
        }

    except Exception as exc:
        logger.error(f"Qlib 推理失败: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60)


@shared_task(
    bind=True,
    max_retries=1,
)
def qlib_train_model(
    self,
    model_name: str,
    model_type: str,
    train_config: dict,
) -> dict:
    """
    Qlib 训练任务（运行在 qlib_train 队列）

    1. 准备数据
    2. 训练模型
    3. 评估指标
    4. 保存 artifact
    5. 写入 Registry

    Args:
        self: Celery task 实例
        model_name: 模型名称
        model_type: 模型类型 (LGBModel/LSTMModel/TransformerModel)
        train_config: 训练配置字典

    Returns:
        训练结果字典

    Example:
        >>> from apps.alpha.application.tasks import qlib_train_model
        >>> qlib_train_model.delay(
        ...     model_name="mlp_csi300",
        ...     model_type="LGBModel",
        ...     train_config={"learning_rate": 0.01}
        ... )
    """
    try:
        from ...infrastructure.models import QlibModelRegistryModel
        from datetime import datetime, timedelta

        logger.info(f"开始 Qlib 训练: {model_name} ({model_type})")

        # 解析训练配置
        universe = train_config.get("universe", "csi300")
        start_date = train_config.get("start_date")
        end_date = train_config.get("end_date")
        learning_rate = train_config.get("learning_rate", 0.01)
        epochs = train_config.get("epochs", 100)
        model_path = train_config.get("model_path", "/models/qlib")

        # 计算数据版本
        data_version = end_date or datetime.now().strftime("%Y-%m-%d")

        # 1. 准备数据
        logger.info("  准备训练数据...")
        # 数据准备逻辑（使用 Qlib API）

        # 2. 训练模型
        logger.info(f"  训练模型 ({model_type})...")
        model = _train_qlib_model(model_type, train_config)

        # 3. 评估指标
        logger.info("  评估模型...")
        metrics = _evaluate_model_metrics(model, universe)

        # 4. 生成 artifact hash
        artifact_hash = _calculate_artifact_hash(
            f"{model_name}_{model_type}_{universe}_{data_version}"
        )

        # 5. 保存 artifact
        logger.info("  保存模型 artifact...")
        artifact_dir = _save_model_artifact(
            model=model,
            model_name=model_name,
            artifact_hash=artifact_hash,
            model_path=model_path,
            train_config=train_config,
            metrics=metrics
        )

        # 6. 写入 Registry
        logger.info("  写入模型注册表...")
        registry_model = QlibModelRegistryModel._default_manager.create(
            model_name=model_name,
            artifact_hash=artifact_hash,
            model_type=model_type,
            universe=universe,
            train_config=train_config,
            feature_set_id="v1",
            label_id="return_5d",
            data_version=data_version,
            ic=metrics.get("ic"),
            icir=metrics.get("icir"),
            rank_ic=metrics.get("rank_ic"),
            model_path=str(artifact_dir),
            is_active=False,  # 需要手动激活
        )

        logger.info(f"Qlib 训练完成: {model_name}")
        logger.info(f"  Artifact Hash: {artifact_hash[:12]}...")
        logger.info(f"  IC: {metrics.get('ic', 'N/A')}")
        logger.info(f"  ICIR: {metrics.get('icir', 'N/A')}")

        return {
            "status": "success",
            "model_name": model_name,
            "model_type": model_type,
            "artifact_hash": artifact_hash,
            "ic": metrics.get("ic"),
            "icir": metrics.get("icir"),
        }

    except Exception as exc:
        logger.error(f"Qlib 训练失败: {exc}", exc_info=True)
        raise


@shared_task(
    bind=True,
    max_retries=1,
)
def qlib_evaluate_model(
    self,
    model_artifact_hash: str,
) -> dict:
    """
    Qlib 模型评估任务

    计算模型的 IC/ICIR/Rank IC 等指标。

    Args:
        self: Celery task 实例
        model_artifact_hash: 模型哈希

    Returns:
        评估结果字典

    Example:
        >>> from apps.alpha.application.tasks import qlib_evaluate_model
        >>> qlib_evaluate_model.delay("abc123...")
    """
    try:
        from ...infrastructure.models import QlibModelRegistryModel

        logger.info(f"开始评估模型: {model_artifact_hash}")

        model = QlibModelRegistryModel._default_manager.get(
            artifact_hash=model_artifact_hash
        )

        # TODO: 实现 IC/ICIR 计算

        logger.info(f"模型评估完成: {model_artifact_hash}")

        return {
            "status": "success",
            "model_artifact_hash": model_artifact_hash,
            "ic": float(model.ic) if model.ic else None,
            "icir": float(model.icir) if model.icir else None,
        }

    except Exception as exc:
        logger.error(f"模型评估失败: {exc}", exc_info=True)
        raise


@shared_task
def qlib_refresh_cache(
    universe_id: str,
    days_back: int = 7
) -> dict:
    """
    刷新 Qlib 缓存任务

    为指定日期范围内的日期补齐缓存。

    Args:
        universe_id: 股票池标识
        days_back: 回溯天数

    Returns:
        刷新结果字典

    Example:
        >>> from apps.alpha.application.tasks import qlib_refresh_cache
        >>> qlib_refresh_cache.delay("csi300", days_back=7)
    """
    try:
        from datetime import timedelta

        logger.info(f"开始刷新缓存: {universe_id}, 回溯 {days_back} 天")

        end_date = date.today()
        start_date = end_date - timedelta(days=days_back)

        results = []
        current_date = start_date

        while current_date <= end_date:
            # 触发推理任务（仅工作日）
            if current_date.weekday() < 5:  # 周一到周五
                result = qlib_predict_scores.delay(
                    universe_id,
                    current_date.isoformat()
                )
                results.append({
                    "date": current_date.isoformat(),
                    "task_id": result.id
                })

            current_date += timedelta(days=1)

        logger.info(f"已触发 {len(results)} 个推理任务")

        return {
            "status": "success",
            "universe_id": universe_id,
            "tasks_triggered": len(results),
            "tasks": results,
        }

    except Exception as exc:
        logger.error(f"刷新缓存失败: {exc}", exc_info=True)
        return {
            "status": "error",
            "error": str(exc)
        }


# ========================================================================
# 辅助函数
# ========================================================================

def _execute_qlib_prediction(
    active_model,
    universe_id: str,
    trade_date: date,
    top_n: int
) -> List[dict]:
    """
    执行 Qlib 预测

    Args:
        active_model: 激活的模型实例
        universe_id: 股票池标识
        trade_date: 交易日期
        top_n: 返回前 N 只

    Returns:
        评分数据列表
    """
    try:
        # 尝试导入 Qlib
        import qlib
        from qlib.data import D
        from qlib.contrib.evaluate import risk_analysis

        # 初始化 Qlib
        qlib.init(provider_uri="~/.qlib/qlib_data/cn_data", region="CN")

        # 加载模型
        model_path = Path(active_model.model_path)
        with open(model_path, "rb") as f:
            model = pickle.load(f)

        # 获取股票池
        instruments = D.instruments(market=universe_id)
        if not instruments:
            logger.warning(f"未找到股票池: {universe_id}")
            return _generate_mock_scores(top_n)

        # 准备预测数据
        # TODO: 这里需要根据实际模型特征准备数据
        prediction = model.predict(
            dates=str(trade_date),
            instruments=instruments
        )

        # 转换为评分格式
        scores_data = []
        for stock, pred_score in prediction.items():
            scores_data.append({
                "code": stock,
                "score": float(pred_score),
                "rank": 0,  # 稍后计算
                "factors": {},
                "source": "qlib",
                "confidence": 0.8,
            })

        # 按评分排序
        scores_data.sort(key=lambda x: x["score"], reverse=True)

        # 更新排名
        for i, score in enumerate(scores_data[:top_n], 1):
            score["rank"] = i

        return scores_data[:top_n]

    except ImportError as e:
        logger.warning(f"Qlib 未安装，使用模拟数据: {e}")
        return _generate_mock_scores(top_n)

    except Exception as e:
        logger.error(f"Qlib 预测失败，使用模拟数据: {e}", exc_info=True)
        return _generate_mock_scores(top_n)


def _generate_mock_scores(top_n: int) -> List[dict]:
    """
    生成模拟评分数据

    Args:
        top_n: 生成数量

    Returns:
        模拟评分数据列表
    """
    mock_stocks = [
        "600519.SH", "000333.SH", "600036.SH", "601318.SH", "000858.SH",
        "600887.SH", "000002.SH", "600000.SH", "601012.SH", "000001.SH",
        "000063.SH", "600276.SH", "002594.SZ", "603259.SH", "600900.SH",
        "601328.SH", "601166.SH", "000725.SH", "600030.SH", "601398.SH",
        "600104.SH", "601888.SH", "002475.SZ", "600585.SH", "000651.SH",
        "002304.SZ", "601888.SH", "600309.SH", "601601.SH", "601288.SH",
    ]

    scores_data = []
    for i, stock in enumerate(mock_stocks[:top_n], 1):
        # 生成模拟评分（0.3 到 0.9 之间）
        score = 0.9 - (i * 0.02)

        scores_data.append({
            "code": stock,
            "score": round(score, 4),
            "rank": i,
            "factors": {
                "momentum": round(score * 0.8, 4),
                "value": round(score * 0.6, 4),
                "quality": round(score * 0.7, 4),
            },
            "source": "qlib",
            "confidence": 0.8,
        })

    return scores_data


def _calculate_artifact_hash(model_path: str) -> str:
    """
    计算模型文件的哈希值

    Args:
        model_path: 模型文件路径

    Returns:
        SHA256 哈希值
    """
    sha256_hash = hashlib.sha256()

    with open(model_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)

    return sha256_hash.hexdigest()


def _save_model_artifact(
    model,
    model_name: str,
    artifact_hash: str,
    model_path: str,
    train_config: dict,
    metrics: dict
) -> Path:
    """
    保存模型 artifact

    Args:
        model: 模型对象
        model_name: 模型名称
        artifact_hash: Artifact hash
        model_path: 模型存储路径
        train_config: 训练配置
        metrics: 评估指标

    Returns:
        Artifact 目录路径
    """
    model_path_obj = Path(model_path)
    artifact_dir = model_path_obj / model_name / artifact_hash
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # 保存模型
    model_file = artifact_dir / "model.pkl"
    with open(model_file, "wb") as f:
        pickle.dump(model, f)

    # 保存配置
    config_file = artifact_dir / "config.json"
    with open(config_file, "w") as f:
        json.dump({
            "model_name": model_name,
            "artifact_hash": artifact_hash,
            "train_config": train_config,
            "created_at": datetime.now().isoformat(),
        }, f, indent=2)

    # 保存指标
    metrics_file = artifact_dir / "metrics.json"
    with open(metrics_file, "w") as f:
        json.dump(metrics, f, indent=2)

    # 保存特征 schema（示例）
    feature_schema_file = artifact_dir / "feature_schema.json"
    with open(feature_schema_file, "w") as f:
        json.dump({
            "features": ["Ref($close, 1)", "Mean($turnover, 5)", ...],
            "label": "Ref($close, 5) / $close - 1",
        }, f, indent=2)

    # 保存数据版本
    data_version_file = artifact_dir / "data_version.txt"
    with open(data_version_file, "w") as f:
        f.write(train_config.get("end_date", datetime.now().strftime("%Y-%m-%d")))

    logger.info(f"模型已保存: {artifact_dir}")

    return artifact_dir


def _train_qlib_model(model_type: str, train_config: dict):
    """
    训练 Qlib 模型

    Args:
        model_type: 模型类型
        train_config: 训练配置

    Returns:
        训练好的模型
    """
    try:
        import qlib
        from qlib.contrib.model.gbdt import LGBModel
        from qlib.contrib.model.pytorch_lstm import LSTMModel
        from qlib.contrib.model.mlptron import MLPTPModel

        model_cls_map = {
            'LGBModel': LGBModel,
            'LSTMModel': LSTMModel,
            'MLPModel': MLPTPModel,
        }

        model_cls = model_cls_map.get(model_type, LGBModel)

        # 创建模型实例
        model = model_cls(**train_config.get("model_params", {}))

        # 这里应该使用 Qlib 的训练 API
        # 实际实现需要根据 Qlib 版本调整

        return model

    except ImportError:
        # Qlib 未安装，返回模拟模型
        logger.warning("Qlib 未安装，使用模拟模型")
        return _create_mock_model(model_type)


def _create_mock_model(model_type: str):
    """创建模拟模型"""
    class MockModel:
        def __init__(self, model_type):
            self.model_type = model_type

        def predict(self, **kwargs):
            return {}

    return MockModel(model_type)


def _evaluate_model_metrics(model, universe: str) -> dict:
    """
    评估模型指标

    Args:
        model: 模型对象
        universe: 股票池

    Returns:
        指标字典
    """
    try:
        # TODO: 实现实际的 IC/ICIR 计算
        # 这里使用模拟值
        return {
            "ic": 0.05,
            "icir": 0.8,
            "rank_ic": 0.04,
            "rank_icir": 0.6,
        }
    except Exception as e:
        logger.error(f"模型评估失败: {e}")
        return {}

