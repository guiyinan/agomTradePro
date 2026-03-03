"""
默认参数初始化脚本单元测试

测试 init_decision_model_params management command。
"""

import pytest
from io import StringIO
from django.core.management import call_command
from django.test import TestCase

from apps.decision_rhythm.infrastructure.models import (
    DecisionModelParamConfigModel,
    DecisionModelParamAuditLogModel,
)


class TestInitDecisionModelParamsCommand(TestCase):
    """测试初始化模型参数命令"""

    def test_command_creates_params(self):
        """测试创建参数"""
        out = StringIO()

        # 运行命令
        call_command("init_decision_model_params", "--env", "dev", stdout=out)

        # 验证参数已创建
        params = DecisionModelParamConfigModel.objects.filter(env="dev")
        assert params.count() == 13

        # 验证关键参数
        alpha_weight = DecisionModelParamConfigModel.objects.get(
            param_key="alpha_model_weight", env="dev"
        )
        assert alpha_weight.param_value == "0.40"
        assert alpha_weight.param_type == "float"
        assert alpha_weight.is_active is True

    def test_command_is_idempotent(self):
        """测试幂等性（重复运行不重复创建）"""
        out = StringIO()

        # 第一次运行
        call_command("init_decision_model_params", "--env", "dev", stdout=out)

        # 验证创建了 13 个参数
        assert DecisionModelParamConfigModel.objects.filter(env="dev").count() == 13

        # 第二次运行
        call_command("init_decision_model_params", "--env", "dev", stdout=out)

        # 应该还是 13 个参数，没有重复创建
        assert DecisionModelParamConfigModel.objects.filter(env="dev").count() == 13

    def test_command_force_updates_existing(self):
        """测试 --force 强制更新已存在的参数"""
        out = StringIO()

        # 第一次运行
        call_command("init_decision_model_params", "--env", "dev", stdout=out)

        # 手动修改一个参数
        param = DecisionModelParamConfigModel.objects.get(
            param_key="alpha_model_weight", env="dev"
        )
        param.param_value = "0.50"
        param.save()

        # 强制重新运行
        call_command("init_decision_model_params", "--env", "dev", "--force", stdout=out)

        # 验证参数被更新回默认值
        param.refresh_from_db()
        assert param.param_value == "0.40"
        assert param.version == 2  # 版本应该增加

    def test_command_creates_audit_logs(self):
        """测试创建审计日志"""
        out = StringIO()

        # 运行命令
        call_command("init_decision_model_params", "--env", "dev", stdout=out)

        # 验证审计日志已创建
        logs = DecisionModelParamAuditLogModel.objects.filter(env="dev")
        assert logs.count() == 13

        # 验证日志内容
        alpha_log = logs.get(param_key="alpha_model_weight")
        assert alpha_log.old_value == ""
        assert alpha_log.new_value == "0.40"
        assert alpha_log.changed_by == "init_command"

    def test_command_separates_environments(self):
        """测试环境隔离"""
        out = StringIO()

        # 为 dev 环境初始化
        call_command("init_decision_model_params", "--env", "dev", stdout=out)

        # 为 test 环境初始化
        call_command("init_decision_model_params", "--env", "test", stdout=out)

        # 验证两个环境的参数是独立的
        dev_params = DecisionModelParamConfigModel.objects.filter(env="dev")
        test_params = DecisionModelParamConfigModel.objects.filter(env="test")

        assert dev_params.count() == 13
        assert test_params.count() == 13

        # 验证配置 ID 不同
        dev_alpha = dev_params.get(param_key="alpha_model_weight")
        test_alpha = test_params.get(param_key="alpha_model_weight")
        assert dev_alpha.config_id != test_alpha.config_id

    def test_command_validates_environment(self):
        """测试环境参数验证"""
        out = StringIO()

        # 运行无效环境应该报错
        with pytest.raises(Exception):  # CommandError
            call_command("init_decision_model_params", "--env", "invalid", stdout=out)

    def test_command_creates_all_weight_params(self):
        """测试创建所有权重参数"""
        out = StringIO()

        call_command("init_decision_model_params", "--env", "dev", stdout=out)

        # 验证所有权重参数
        expected_weights = [
            "alpha_model_weight",
            "sentiment_weight",
            "flow_weight",
            "technical_weight",
            "fundamental_weight",
        ]

        for weight_key in expected_weights:
            param = DecisionModelParamConfigModel.objects.get(
                param_key=weight_key, env="dev"
            )
            assert param.param_type == "float"

    def test_command_creates_all_penalty_params(self):
        """测试创建所有惩罚参数"""
        out = StringIO()

        call_command("init_decision_model_params", "--env", "dev", stdout=out)

        # 验证所有惩罚参数
        expected_penalties = [
            "gate_penalty_cooldown",
            "gate_penalty_quota",
            "gate_penalty_volatility",
        ]

        for penalty_key in expected_penalties:
            param = DecisionModelParamConfigModel.objects.get(
                param_key=penalty_key, env="dev"
            )
            assert param.param_type == "float"
