#!/usr/bin/env python
"""
Train Qlib Model Script

训练一个基础的 Qlib 模型并注册到系统中。
"""

import hashlib
import sys
from datetime import datetime
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')

import django

django.setup()

import qlib
from qlib.utils import init_instance_by_config


def train_model():
    """训练并注册模型"""

    # 从数据库获取配置
    from apps.account.infrastructure.models import SystemSettingsModel
    from apps.alpha.infrastructure.models import QlibModelRegistryModel

    qlib_config = SystemSettingsModel.get_runtime_qlib_config()

    if not qlib_config['enabled']:
        print("Qlib 未启用")
        return

    provider_uri = qlib_config['provider_uri']
    print(f"初始化 Qlib: {provider_uri}")

    # 初始化 Qlib
    qlib.init(provider_uri=provider_uri, region="cn")

    # 训练配置 - 使用数据范围内的准确时间
    # 数据范围: 2005-01-01 ~ 2020-09-25
    universe = "csi300"
    start_time = "2015-01-01"
    end_time = "2020-09-25"

    print("\n训练参数:")
    print(f"  股票池: {universe}")
    print(f"  时间范围: {start_time} ~ {end_time}")

    # 数据集配置
    dataset_config = {
        "class": "DatasetH",
        "module_path": "qlib.data.dataset",
        "kwargs": {
            "handler": {
                "class": "Alpha158",
                "module_path": "qlib.contrib.data.handler",
                "kwargs": {
                    "start_time": start_time,
                    "end_time": end_time,
                    "fit_start_time": start_time,
                    "fit_end_time": "2019-12-31",
                    "instruments": universe,
                },
            },
            "segments": {
                "train": ("2015-01-01", "2019-06-30"),
                "valid": ("2019-07-01", "2019-12-31"),
                "test": ("2020-01-01", "2020-09-25"),
            },
        },
    }

    # 模型配置 - LightGBM
    model_config = {
        "class": "LGBModel",
        "module_path": "qlib.contrib.model.gbdt",
        "kwargs": {
            "loss": "mse",
            "colsample_bytree": 0.8879,
            "learning_rate": 0.0421,
            "subsample": 0.8789,
            "lambda_l1": 205.6999,
            "lambda_l2": 580.9768,
            "max_depth": 8,
            "num_leaves": 210,
            "num_threads": 4,
        },
    }

    print("\n开始训练...")

    # 创建数据集
    dataset = init_instance_by_config(dataset_config)

    # 创建模型
    model = init_instance_by_config(model_config)

    # 训练
    model.fit(dataset)
    print("训练完成!")

    # 保存模型
    model_dir = Path(project_root) / "data" / "qlib" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    model_name = f"lgb_{universe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    model_file = model_dir / f"{model_name}.pkl"

    # 使用 to_pickle 保存模型
    model.to_pickle(str(model_file))
    print(f"\n模型已保存: {model_file}")

    # 计算模型哈希
    with open(model_file, 'rb') as f:
        model_bytes = f.read()
        artifact_hash = hashlib.sha256(model_bytes).hexdigest()[:32]

    # 注册到数据库
    print("\n注册模型到数据库...")

    # 先停用其他模型
    QlibModelRegistryModel._default_manager.update(is_active=False)

    # 创建新模型记录
    model_record = QlibModelRegistryModel.objects.create(
        model_name=model_name,
        artifact_hash=artifact_hash,
        model_type=QlibModelRegistryModel.MODEL_LGB,
        universe=universe,
        train_config=model_config,
        feature_set_id="alpha158",
        label_id="ref_5d",
        data_version="v1",
        model_path=str(model_file),
        is_active=True,
        activated_at=datetime.now(),
    )

    print(f"模型已注册: {model_record.model_name}")
    print(f"  ID: {model_record.artifact_hash}")
    print(f"  激活状态: {model_record.is_active}")

    return model_record


if __name__ == '__main__':
    train_model()
