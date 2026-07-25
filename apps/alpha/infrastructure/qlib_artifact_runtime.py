"""Qlib artifact, training, and evaluation runtime helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from django.utils import timezone

from apps.alpha.infrastructure.qlib_runtime_init import (
    _get_runtime_qlib_config,
    _normalize_qlib_region,
    _resolve_qlib_stock_list,
)
from apps.alpha.infrastructure.scientific_runtime import get_numpy, get_pandas

logger = logging.getLogger(__name__)

_MINIMUM_CROSS_SECTION_SIZE = 10


class _QlibModel(Protocol):
    """Runtime contract shared by the supported Qlib models."""

    def fit(self, dataset: object) -> None:
        """Fit the model against a Qlib dataset."""

    def predict(self, dataset: object) -> object:
        """Return prediction scores for a Qlib dataset."""


def _calculate_artifact_hash(model_path: str) -> str:
    """Return a SHA-256 hash for a model file or stable pre-save identifier."""

    sha256_hash = hashlib.sha256()
    path_obj = Path(model_path)
    if path_obj.is_file():
        with path_obj.open("rb") as file_handle:
            for byte_block in iter(lambda: file_handle.read(4096), b""):
                sha256_hash.update(byte_block)
    else:
        sha256_hash.update(model_path.encode("utf-8"))
    return sha256_hash.hexdigest()


def _resolve_artifact_directory(
    model_path: str,
    model_name: str,
    artifact_hash: str,
) -> Path:
    """Resolve an artifact directory while preventing path traversal."""

    artifact_root = Path(model_path).resolve()
    artifact_dir = (artifact_root / model_name / artifact_hash).resolve()
    try:
        artifact_dir.relative_to(artifact_root)
    except ValueError as exc:
        raise ValueError("模型名称或 artifact hash 不能逃逸模型存储目录") from exc
    return artifact_dir


def _json_bytes(payload: object) -> bytes:
    """Serialize reproducible metadata as UTF-8 JSON."""

    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _build_feature_schema(train_config: Mapping[str, object]) -> dict[str, object]:
    """Build honest feature metadata from the actual training configuration."""

    feature_set_id = str(train_config.get("feature_set_id") or "alpha360")
    schema: dict[str, object] = {"feature_set_id": feature_set_id}
    feature_columns = train_config.get("feature_columns")
    if isinstance(feature_columns, (list, tuple)) and all(
        isinstance(column, str) for column in feature_columns
    ):
        schema["feature_columns"] = list(feature_columns)

    label_id = train_config.get("label_id")
    if isinstance(label_id, str) and label_id.strip():
        schema["label_id"] = label_id.strip()
    label_expression = train_config.get("label_expression")
    if isinstance(label_expression, str) and label_expression.strip():
        schema["label_expression"] = label_expression.strip()
    return schema


def _save_model_artifact(
    model: object,
    model_name: str,
    artifact_hash: str,
    model_path: str,
    train_config: Mapping[str, object],
    metrics: Mapping[str, object],
) -> Path:
    """Persist one immutable model artifact and publish its manifest last."""

    artifact_dir = _resolve_artifact_directory(model_path, model_name, artifact_hash)
    if artifact_dir.exists():
        raise FileExistsError(f"模型 artifact 已存在，禁止覆盖: {artifact_dir}")

    model_bytes = pickle.dumps(model)
    created_at = timezone.now().isoformat()
    data_version = str(train_config.get("end_date") or "unknown")
    artifact_files = {
        "model.pkl": model_bytes,
        "config.json": _json_bytes(
            {
                "model_name": model_name,
                "artifact_hash": artifact_hash,
                "train_config": dict(train_config),
                "created_at": created_at,
            }
        ),
        "metrics.json": _json_bytes(dict(metrics)),
        "feature_schema.json": _json_bytes(_build_feature_schema(train_config)),
        "data_version.txt": f"{data_version}\n".encode(),
    }
    manifest = {
        "artifact_hash": artifact_hash,
        "created_at": created_at,
        "files": {
            filename: {
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
            for filename, content in artifact_files.items()
        },
    }

    artifact_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{artifact_hash}.",
            dir=artifact_dir.parent,
        )
    )
    try:
        for filename, content in artifact_files.items():
            (temporary_dir / filename).write_bytes(content)
        (temporary_dir / "manifest.json").write_bytes(_json_bytes(manifest))
        temporary_dir.replace(artifact_dir)
    except Exception:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise

    logger.info("模型 artifact 已保存: %s", artifact_dir)
    return artifact_dir


def _parse_training_period(
    train_config: Mapping[str, object],
    pd: Any,
) -> tuple[Any, Any, Any]:
    """Parse and validate the configured train/validation period."""

    start_dt = pd.Timestamp(train_config.get("start_date") or "2020-01-01")
    end_dt = pd.Timestamp(train_config.get("end_date") or pd.Timestamp.now().strftime("%Y-%m-%d"))
    if pd.isna(start_dt) or pd.isna(end_dt):
        raise ValueError("训练日期不能为空")
    if start_dt >= end_dt:
        raise ValueError("训练开始日期必须早于结束日期")

    train_period_days = int((end_dt - start_dt).days)
    valid_start = start_dt + pd.Timedelta(days=max(1, int(train_period_days * 0.8)))
    if valid_start >= end_dt:
        raise ValueError("训练日期范围过短，无法划分独立验证集")
    return start_dt, valid_start, end_dt


def _select_handler(
    feature_set_id: object,
    alpha158: type[Any],
    alpha360: type[Any],
) -> type[Any]:
    """Select only a supported, explicit Qlib feature handler."""

    normalized = str(feature_set_id or "alpha360").strip().lower()
    if normalized in {"alpha158", "158", "v158"}:
        return alpha158
    if normalized in {"alpha360", "360", "v360"}:
        return alpha360
    raise ValueError(f"不支持的 Qlib 特征集: {feature_set_id}")


def _train_qlib_model(
    model_type: str,
    train_config: Mapping[str, object],
    model_path: str = "/models/qlib",
) -> _QlibModel:
    """Train a supported Qlib model using an independent validation segment."""

    del model_path  # Artifact persistence is handled separately.
    try:
        pd = get_pandas()
        import qlib  # type: ignore[import-untyped]
        from qlib.contrib.data.handler import Alpha158, Alpha360  # type: ignore[import-untyped]
        from qlib.contrib.model.gbdt import LGBModel  # type: ignore[import-untyped]
        from qlib.contrib.model.mlptron import MLPTPModel  # type: ignore[import-untyped]
        from qlib.contrib.model.pytorch_gru import GRUModel  # type: ignore[import-untyped]
        from qlib.contrib.model.pytorch_lstm import LSTMModel  # type: ignore[import-untyped]
        from qlib.data import D  # type: ignore[import-untyped]
        from qlib.data.dataset import DatasetH  # type: ignore[import-untyped]

        qlib_config = _get_runtime_qlib_config()
        if not qlib_config.get("enabled"):
            raise ValueError("Qlib 未启用，请先在系统配置中启用 Qlib")

        provider_uri = str(qlib_config.get("provider_uri") or "~/.qlib/qlib_data/cn_data")
        region = _normalize_qlib_region(str(qlib_config.get("region") or "CN"))
        qlib.init(provider_uri=provider_uri, region=region)

        start_dt, valid_start, end_dt = _parse_training_period(train_config, pd)
        universe = str(train_config.get("universe") or "csi300")
        stock_list = _resolve_qlib_stock_list(
            D,
            universe_id=universe,
            start_time=start_dt,
            end_time=end_dt,
        )
        logger.info("准备训练数据: universe=%s, stocks=%d", universe, len(stock_list))

        handler_cls = _select_handler(
            train_config.get("feature_set_id"),
            Alpha158,
            Alpha360,
        )
        handler = handler_cls(
            start_time=(start_dt.year, start_dt.month, start_dt.day),
            end_time=(end_dt.year, end_dt.month, end_dt.day),
            fit_start_time=(start_dt.year, start_dt.month, start_dt.day),
            fit_end_time=(valid_start.year, valid_start.month, valid_start.day),
            instruments=stock_list,
        )
        dataset = DatasetH(
            handler=handler,
            segments={
                "train": (pd.Timestamp(start_dt), pd.Timestamp(valid_start)),
                "valid": (pd.Timestamp(valid_start), pd.Timestamp(end_dt)),
            },
        )

        model_classes: dict[str, type[Any]] = {
            "LGBModel": LGBModel,
            "GRUModel": GRUModel,
            "LSTMModel": LSTMModel,
            "MLPModel": MLPTPModel,
        }
        model_cls = model_classes.get(model_type)
        if model_cls is None:
            raise ValueError(f"不支持的模型类型: {model_type}")

        lgb_defaults: dict[str, object] = {
            "loss": "mse",
            "col_sample_bytree": 0.8,
            "learning_rate": 0.01,
            "bagging_freq": 5,
            "bagging_fraction": 0.85,
            "bagging_seed": 3,
        }
        configured_params = train_config.get("model_params", {})
        if not isinstance(configured_params, Mapping):
            raise ValueError("model_params 必须是对象")
        model_params = {
            **(lgb_defaults if model_type == "LGBModel" else {}),
            **dict(configured_params),
        }
        model = cast(_QlibModel, model_cls(**model_params))
        model.fit(dataset)
        logger.info("%s 训练完成", model_type)
        return model
    except ImportError as exc:
        logger.error("Qlib 未安装，无法训练模型: %s", exc)
        raise RuntimeError("Qlib 未安装。请安装 qlib: pip install pyqlib") from exc
    except Exception:
        logger.exception("训练 Qlib 模型失败")
        raise


def _prepare_labels(dataset: object) -> object:
    """Read validation labels through the supported Qlib dataset contracts."""

    prepare = getattr(dataset, "prepare", None)
    if callable(prepare):
        try:
            labels = prepare("test", col_set="label")
        except TypeError:
            labels = None
        if labels is not None:
            return labels

    fetch = getattr(dataset, "fetch", None)
    if callable(fetch):
        return fetch(cols=["label"])
    raise RuntimeError("Qlib 数据集未提供验证标签读取接口")


def _as_cross_section_series(value: object, pd: Any) -> Any:
    """Normalize Series, single-column, and wide DataFrame values."""

    if isinstance(value, pd.Series):
        return value
    if not isinstance(value, pd.DataFrame):
        raise TypeError(f"评估数据类型不受支持: {type(value).__name__}")
    if value.empty:
        return pd.Series(dtype=float)
    if value.shape[1] == 1:
        return value.iloc[:, 0]
    return value.stack()


def _calculate_cross_section_metrics(
    predictions: object,
    labels: object,
    pd: Any,
    np: Any,
) -> dict[str, Any]:
    """Calculate real cross-sectional rank correlations from aligned labels."""

    prediction_series = _as_cross_section_series(predictions, pd).rename("prediction")
    label_series = _as_cross_section_series(labels, pd).rename("label")
    aligned = pd.concat([prediction_series, label_series], axis=1, join="inner").dropna()
    if aligned.empty:
        raise RuntimeError("预测结果与验证标签没有可对齐样本")

    index = aligned.index
    if not isinstance(index, pd.MultiIndex) or index.nlevels < 2:
        raise RuntimeError("评估数据必须包含日期和证券代码两级索引")

    correlations: list[float] = []
    for _, cross_section in aligned.groupby(level=0):
        if len(cross_section) < _MINIMUM_CROSS_SECTION_SIZE:
            continue
        correlation = cross_section["prediction"].corr(
            cross_section["label"],
            method="spearman",
        )
        if correlation is not None and np.isfinite(correlation):
            correlations.append(float(correlation))

    if not correlations:
        raise RuntimeError(f"没有达到至少 {_MINIMUM_CROSS_SECTION_SIZE} 只证券的有效横截面")

    mean_ic = float(np.mean(correlations))
    std_ic = float(np.std(correlations))
    icir = mean_ic / std_ic if std_ic > 0 else 0.0
    return {
        "ic": mean_ic,
        "icir": icir,
        "rank_ic": mean_ic,
        "rank_icir": icir,
        "ic_std": std_ic,
        "rank_ic_std": std_ic,
        "sample_count": len(correlations),
        "evaluation_method": "validation_labels",
    }


def _evaluate_model_metrics(
    model: _QlibModel,
    universe: str,
    train_config: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Evaluate a model from real validation labels; never fabricate IC values."""

    try:
        np = get_numpy()
        pd = get_pandas()
        from qlib.contrib.data.handler import Alpha158, Alpha360
        from qlib.data import D
        from qlib.data.dataset import DatasetH

        effective_config = train_config or {}
        start_dt, valid_start, end_dt = _parse_training_period(effective_config, pd)
        stock_list = _resolve_qlib_stock_list(
            D,
            universe_id=universe,
            start_time=start_dt,
            end_time=end_dt,
        )
        handler_cls = _select_handler(
            effective_config.get("feature_set_id"),
            Alpha158,
            Alpha360,
        )
        handler = handler_cls(
            start_time=(start_dt.year, start_dt.month, start_dt.day),
            end_time=(end_dt.year, end_dt.month, end_dt.day),
            fit_start_time=(start_dt.year, start_dt.month, start_dt.day),
            fit_end_time=(end_dt.year, end_dt.month, end_dt.day),
            instruments=stock_list,
        )
        dataset = DatasetH(
            handler=handler,
            segments={"test": (pd.Timestamp(valid_start), pd.Timestamp(end_dt))},
        )
        metrics = _calculate_cross_section_metrics(
            model.predict(dataset),
            _prepare_labels(dataset),
            pd,
            np,
        )
        logger.info(
            "模型评估完成: IC=%.4f, ICIR=%.4f, sample_count=%d",
            metrics["ic"],
            metrics["icir"],
            metrics["sample_count"],
        )
        return metrics
    except ImportError as exc:
        logger.error("Qlib 评估依赖未安装: %s", exc)
        raise RuntimeError("Qlib 评估依赖未安装。请安装 pyqlib") from exc
    except Exception as exc:
        logger.exception("模型评估失败")
        raise RuntimeError(f"模型评估失败: {exc}") from exc


calculate_artifact_hash = _calculate_artifact_hash
save_model_artifact = _save_model_artifact
train_qlib_model = _train_qlib_model
evaluate_model_metrics = _evaluate_model_metrics
