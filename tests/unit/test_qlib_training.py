"""
Unit Tests for Qlib Training

测试 Qlib 模型训练相关功能。
"""

import json
import os
import pickle
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.alpha.application.tasks import (
    _calculate_artifact_hash,
    _execute_qlib_prediction,
    _make_json_safe,
    _resolve_qlib_handler_class,
    _resolve_qlib_stock_list,
    _save_model_artifact,
    qlib_train_model,
)
from apps.alpha.infrastructure.models import QlibModelRegistryModel


@pytest.mark.django_db
class TestQlibTrainingTasks:
    """Qlib 训练任务测试"""

    @patch('apps.alpha.application.tasks._train_qlib_model')
    @patch('apps.alpha.application.tasks._evaluate_model_metrics')
    @patch('apps.alpha.application.tasks._save_model_artifact')
    def test_qlib_train_model_success(
        self,
        mock_save,
        mock_evaluate,
        mock_train
    ):
        """测试训练任务成功"""
        # 设置 mock
        mock_model = Mock()
        mock_train.return_value = mock_model

        mock_evaluate.return_value = {
            "ic": 0.05,
            "icir": 0.8,
            "rank_ic": 0.04,
        }

        mock_artifact_dir = Path("/models/qlib/test_model/abc123")
        mock_save.return_value = mock_artifact_dir

        # 执行任务
        result = qlib_train_model(
            model_name="test_model",
            model_type="LGBModel",
            train_config={
                "universe": "csi300",
                "start_date": "2025-01-01",
                "end_date": "2026-01-01",
                "learning_rate": 0.01,
                "epochs": 100,
            }
        )

        # 验证结果
        assert result["status"] == "success"
        assert result["model_name"] == "test_model"
        assert "artifact_hash" in result
        assert result["ic"] == 0.05

    @patch('apps.alpha.application.tasks._train_qlib_model')
    def test_qlib_train_model_failure(self, mock_train):
        """测试训练任务失败"""
        mock_train.side_effect = Exception("Training failed")

        with pytest.raises(Exception) as exc_info:
            qlib_train_model(
                model_name="test_model",
                model_type="LGBModel",
                train_config={}
            )

        assert "Training failed" in str(exc_info.value)


class TestQlibTrainingHelpers:
    """Qlib 训练辅助函数测试"""

    def test_resolve_qlib_handler_class_matches_feature_set(self):
        """feature_set_id 应映射到对应的 Qlib handler。"""
        assert _resolve_qlib_handler_class("alpha158").__name__ == "Alpha158"
        assert _resolve_qlib_handler_class("v158").__name__ == "Alpha158"
        assert _resolve_qlib_handler_class("v1").__name__ == "Alpha360"

    def test_make_json_safe_serializes_timestamp_like_values(self):
        """缓存元数据中的 pandas 时间类型应可安全落到 JSONField。"""
        payload = {
            "requested_trade_date": "2026-04-06",
            "effective_trade_date": datetime(2026, 4, 3, 0, 0),
        }

        result = _make_json_safe(payload)

        assert result["requested_trade_date"] == "2026-04-06"
        assert result["effective_trade_date"] == "2026-04-03T00:00:00"

    def test_resolve_qlib_stock_list_expands_universe_config(self):
        """Qlib 股票池配置应先展开为真实成分股列表。"""
        mock_data_api = Mock()
        mock_data_api.instruments.return_value = {
            "market": "csi300",
            "filter_pipe": [],
        }
        mock_data_api.list_instruments.return_value = [
            "000001.SH",
            "000002.SH",
        ]

        result = _resolve_qlib_stock_list(
            mock_data_api,
            universe_id="csi300",
            start_time="2025-01-01",
            end_time="2025-12-31",
        )

        assert result == ["000001.SH", "000002.SH"]
        mock_data_api.list_instruments.assert_called_once_with(
            {"market": "csi300", "filter_pipe": []},
            start_time="2025-01-01",
            end_time="2025-12-31",
            as_list=True,
        )

    @patch("apps.alpha.application.tasks._build_outdated_qlib_reason")
    def test_execute_prediction_short_circuits_when_local_data_is_outdated(
        self,
        mock_outdated_reason,
    ):
        """直调预测函数时也应先检查本地 Qlib 数据覆盖范围。"""
        mock_outdated_reason.return_value = (
            "本地 Qlib 数据最新交易日为 2020-09-25，早于请求交易日 2026-04-06，请先同步 Qlib 数据"
        )

        active_model = Mock(model_path="unused.pkl")

        with pytest.raises(RuntimeError, match="2020-09-25"):
            _execute_qlib_prediction(
                active_model=active_model,
                universe_id="csi300",
                trade_date=date(2026, 4, 6),
                top_n=30,
            )

    def test_calculate_artifact_hash(self):
        """测试计算 artifact hash"""
        # 创建临时文件
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content")
            temp_path = f.name

        try:
            artifact_hash = _calculate_artifact_hash(temp_path)

            # SHA256 hash 应该是 64 位十六进制
            assert len(artifact_hash) == 64
            assert all(c in "0123456789abcdef" for c in artifact_hash)

        finally:
            os.unlink(temp_path)

    def test_save_model_artifact(self):
        """测试保存模型 artifact"""
        import shutil
        import tempfile

        # 创建临时目录
        temp_dir = tempfile.mkdtemp()
        model_path = Path(temp_dir) / "models"

        try:
            # 创建模拟模型
            mock_model = {"type": "test_model"}

            # 保存 artifact
            artifact_dir = _save_model_artifact(
                model=mock_model,
                model_name="test_model",
                artifact_hash="abc123",
                model_path=str(model_path),
                train_config={"learning_rate": 0.01},
                metrics={"ic": 0.05}
            )

            # 验证文件创建
            assert artifact_dir.exists()
            assert (artifact_dir / "model.pkl").exists()
            assert (artifact_dir / "config.json").exists()
            assert (artifact_dir / "metrics.json").exists()
            assert (artifact_dir / "feature_schema.json").exists()
            assert (artifact_dir / "data_version.txt").exists()

            # 验证配置文件内容
            with open(artifact_dir / "config.json") as f:
                config = json.load(f)
                assert config["model_name"] == "test_model"
                assert config["artifact_hash"] == "abc123"

            # 验证指标文件内容
            with open(artifact_dir / "metrics.json") as f:
                metrics = json.load(f)
                assert metrics["ic"] == 0.05

        finally:
            shutil.rmtree(temp_dir)


@pytest.mark.django_db
class TestQlibModelRegistry:
    """Qlib 模型注册表测试"""

    def test_create_model_entry(self):
        """测试创建模型记录"""
        model = QlibModelRegistryModel.objects.create(
            model_name="test_model",
            artifact_hash="test_hash_001",
            model_type="LGBModel",
            universe="csi300",
            train_config={"learning_rate": 0.01},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            ic=0.05,
            icir=0.8,
            model_path="/models/test.pkl"
        )

        assert model.model_name == "test_model"
        assert model.is_active is False

    def test_activate_model(self):
        """测试激活模型"""
        # 创建两个模型
        model1 = QlibModelRegistryModel.objects.create(
            model_name="my_model",
            artifact_hash="hash1",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.01",
            model_path="/models/v1.pkl",
            is_active=True
        )

        model2 = QlibModelRegistryModel.objects.create(
            model_name="my_model",
            artifact_hash="hash2",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/v2.pkl",
            is_active=False
        )

        # 激活 model2
        model2.activate(activated_by="test_user")

        # 刷新并检查
        model1.refresh_from_db()
        model2.refresh_from_db()

        assert model1.is_active is False
        assert model2.is_active is True
        assert model2.activated_by == "test_user"

    def test_deactivate_model(self):
        """测试取消激活模型"""
        model = QlibModelRegistryModel.objects.create(
            model_name="test_model",
            artifact_hash="test_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/test.pkl",
            is_active=True
        )

        model.deactivate()

        model.refresh_from_db()
        assert model.is_active is False

    def test_get_active_model(self):
        """测试获取激活的模型"""
        # 创建多个模型
        QlibModelRegistryModel.objects.create(
            model_name="model_a",
            artifact_hash="hash_a1",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.01",
            model_path="/models/a1.pkl"
        )

        active = QlibModelRegistryModel.objects.create(
            model_name="model_a",
            artifact_hash="hash_a2",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/a2.pkl",
            is_active=True
        )

        # 获取激活的模型
        active_models = QlibModelRegistryModel.objects.active()

        assert len(active_models) == 1
        assert active_models[0].artifact_hash == "hash_a2"

    def test_model_uniqueness(self):
        """测试模型唯一性约束"""
        model1 = QlibModelRegistryModel.objects.create(
            model_name="test_model",
            artifact_hash="unique_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/test.pkl"
        )

        # 尝试创建相同 artifact_hash 的记录应该失败
        with pytest.raises(Exception):  # IntegrityError
            QlibModelRegistryModel.objects.create(
                model_name="another_model",
                artifact_hash="unique_hash",  # 相同
                model_type="LGBModel",
                universe="csi500",
                train_config={},
                feature_set_id="v1",
                label_id="return_5d",
                data_version="2026.02.06",
                model_path="/models/test2.pkl"
            )


@pytest.mark.django_db
class TestQlibManagementCommands:
    """Qlib 管理命令测试"""

    def test_list_models_no_models(self):
        """测试列出模型（没有模型）"""
        out = StringIO()
        call_command('list_models', stdout=out)

        output = out.getvalue()
        assert "没有找到模型" in output

    def test_list_models_with_models(self):
        """测试列出模型（有模型）"""
        # 创建一些模型
        for i in range(3):
            QlibModelRegistryModel.objects.create(
                model_name=f"model_{i % 2}",  # model_0, model_1, model_0
                artifact_hash=f"hash_{i}",
                model_type="LGBModel",
                universe="csi300",
                train_config={},
                feature_set_id="v1",
                label_id="return_5d",
                data_version="2026.02.05",
                model_path=f"/models/model_{i}.pkl",
                is_active=(i == 1)
            )

        out = StringIO()
        call_command('list_models', stdout=out)

        output = out.getvalue()
        assert "找到 3 个模型" in output

    def test_list_models_filter_by_name(self):
        """测试按名称过滤模型"""
        QlibModelRegistryModel.objects.create(
            model_name="test_model",
            artifact_hash="hash_x",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/test.pkl"
        )

        out = StringIO()
        call_command('list_models', '--model-name', 'test', stdout=out)

        output = out.getvalue()
        assert "test_model" in output

    def test_list_models_active_only(self):
        """测试只列出激活的模型"""
        QlibModelRegistryModel.objects.create(
            model_name="inactive_model",
            artifact_hash="hash1",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/inactive.pkl"
        )

        active = QlibModelRegistryModel.objects.create(
            model_name="active_model",
            artifact_hash="hash2",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/active.pkl",
            is_active=True
        )

        out = StringIO()
        call_command('list_models', '--active', stdout=out)

        output = out.getvalue()
        assert "active_model" in output
        assert "inactive_model" not in output

    def test_activate_command(self):
        """测试激活命令"""
        model = QlibModelRegistryModel.objects.create(
            model_name="test_model",
            artifact_hash="test_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/test.pkl"
        )

        out = StringIO()
        call_command('activate_model', 'test_hash', stdout=out)

        output = out.getvalue()
        assert "已激活" in output or "已经是激活状态" in output

        # 验证数据库状态
        model.refresh_from_db()
        assert model.is_active is True

    def test_activate_command_not_exist(self):
        """测试激活不存在的模型"""
        out = StringIO()
        call_command('activate_model', 'nonexistent_hash', stdout=out)

        output = out.getvalue()
        assert "不存在" in output

    def test_rollback_to_prev(self):
        """测试回滚到上一个版本"""
        # 创建模型序列
        old_model = QlibModelRegistryModel.objects.create(
            model_name="my_model",
            artifact_hash="old_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.01.01",
            model_path="/models/old.pkl"
        )

        current = QlibModelRegistryModel.objects.create(
            model_name="my_model",
            artifact_hash="current_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/current.pkl",
            is_active=True
        )

        out = StringIO()
        call_command(
            'rollback_model',
            '--model-name', 'my_model',
            '--prev',
            stdout=out
        )

        output = out.getvalue()
        assert "已回滚" in output or "old_hash" in output


class TestModelArtifacts:
    """模型 Artifact 测试"""

    def test_artifact_directory_structure(self):
        """测试 artifact 目录结构"""
        import shutil
        import tempfile

        temp_dir = tempfile.mkdtemp()
        model_path = Path(temp_dir)

        try:
            # 创建模拟模型
            mock_model = {"type": "LGBModel"}

            # 保存 artifact
            from apps.alpha.application.tasks import _save_model_artifact
            artifact_dir = _save_model_artifact(
                model=mock_model,
                model_name="test_model",
                artifact_hash="test_hash_123",
                model_path=str(model_path / "qlib"),
                train_config={},
                metrics={"ic": 0.05}
            )

            # 验证目录结构
            expected_files = [
                "model.pkl",
                "config.json",
                "metrics.json",
                "feature_schema.json",
                "data_version.txt"
            ]

            for filename in expected_files:
                assert (artifact_dir / filename).exists(), f"Missing {filename}"

        finally:
            shutil.rmtree(temp_dir)

    def test_model_artifact_persistence(self):
        """测试模型 artifact 持久化"""
        import shutil
        import tempfile

        temp_dir = tempfile.mkdtemp()
        model_path = Path(temp_dir)

        try:
            # 创建并保存模型
            mock_model = {"data": "test_data", "params": {"lr": 0.01}}

            from apps.alpha.application.tasks import _save_model_artifact
            artifact_dir = _save_model_artifact(
                model=mock_model,
                model_name="test_model",
                artifact_hash="test_hash_456",
                model_path=str(model_path / "qlib"),
                train_config={"learning_rate": 0.01},
                metrics={"ic": 0.05}
            )

            # 加载并验证模型
            model_file = artifact_dir / "model.pkl"
            with open(model_file, "rb") as f:
                loaded_model = pickle.load(f)

            assert loaded_model == mock_model

            # 加载配置
            config_file = artifact_dir / "config.json"
            with open(config_file) as f:
                config = json.load(f)

            assert config["artifact_hash"] == "test_hash_456"

        finally:
            shutil.rmtree(temp_dir)
