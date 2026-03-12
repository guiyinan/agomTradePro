"""
Unit tests for Operation Audit Log Domain layer.
"""

import pytest
from datetime import datetime, timezone
from apps.audit.domain.entities import (
    OperationLog,
    OperationSource,
    OperationType,
    OperationAction,
    mask_sensitive_params,
    infer_action_from_tool,
    infer_module_from_tool,
)


class TestMaskSensitiveParams:
    """测试敏感参数脱敏"""

    def test_mask_password(self):
        """测试密码脱敏"""
        params = {"password": "secret123", "username": "test"}
        result = mask_sensitive_params(params)
        assert result["password"] == "***"
        assert result["username"] == "test"

    def test_mask_token(self):
        """测试 token 脱敏"""
        params = {"api_token": "abc123", "data": "value"}
        result = mask_sensitive_params(params)
        assert result["api_token"] == "***"
        assert result["data"] == "value"

    def test_mask_nested_dict(self):
        """测试嵌套字典脱敏"""
        params = {
            "user": {
                "name": "test",
                "password": "secret",
            },
            "config": {"api_key": "key123"},
        }
        result = mask_sensitive_params(params)
        assert result["user"]["password"] == "***"
        assert result["user"]["name"] == "test"
        assert result["config"]["api_key"] == "***"

    def test_mask_list(self):
        """测试列表脱敏"""
        params = [
            {"token": "abc"},
            {"name": "test"},
        ]
        result = mask_sensitive_params(params)
        assert result[0]["token"] == "***"
        assert result[1]["name"] == "test"


class TestInferActionFromTool:
    """测试从工具名推断动作"""

    def test_create_action(self):
        """测试创建动作推断"""
        assert infer_action_from_tool("create_signal") == OperationAction.CREATE
        assert infer_action_from_tool("add_position") == OperationAction.CREATE

    def test_update_action(self):
        """测试更新动作推断"""
        assert infer_action_from_tool("update_policy") == OperationAction.UPDATE
        assert infer_action_from_tool("modify_config") == OperationAction.UPDATE

    def test_delete_action(self):
        """测试删除动作推断"""
        assert infer_action_from_tool("delete_signal") == OperationAction.DELETE
        assert infer_action_from_tool("remove_user") == OperationAction.DELETE

    def test_execute_action(self):
        """测试执行动作推断"""
        assert infer_action_from_tool("execute_backtest") == OperationAction.EXECUTE
        assert infer_action_from_tool("run_task") == OperationAction.EXECUTE

    def test_read_action(self):
        """测试读取动作推断"""
        assert infer_action_from_tool("get_signal") == OperationAction.READ
        assert infer_action_from_tool("list_portfolios") == OperationAction.READ


class TestInferModuleFromTool:
    """测试从工具名推断模块"""

    def test_signal_module(self):
        """测试信号模块推断"""
        assert infer_module_from_tool("create_signal") == "signal"
        assert infer_module_from_tool("get_signals") == "signal"

    def test_policy_module(self):
        """测试政策模块推断"""
        assert infer_module_from_tool("get_policy_status") == "policy"

    def test_backtest_module(self):
        """测试回测模块推断"""
        assert infer_module_from_tool("run_backtest") == "backtest"

    def test_alpha_module(self):
        """测试 Alpha 模块推断"""
        assert infer_module_from_tool("get_alpha_scores") == "alpha"

    def test_unknown_module(self):
        """测试未知模块"""
        assert infer_module_from_tool("unknown_tool") == "general"


class TestOperationLogEntity:
    """测试操作日志实体"""

    def test_create_operation_log(self):
        """测试创建操作日志"""
        log = OperationLog.create(
            request_id="req-123",
            user_id=1,
            username="testuser",
            source=OperationSource.MCP,
            operation_type=OperationType.MCP_CALL,
            module="signal",
            action=OperationAction.CREATE,
            mcp_tool_name="create_signal",
            request_params={"asset_code": "000001.SH"},
            response_status=200,
        )

        assert log.request_id == "req-123"
        assert log.user_id == 1
        assert log.username == "testuser"
        assert log.source == OperationSource.MCP
        assert log.module == "signal"
        assert log.action == OperationAction.CREATE
        assert log.mcp_tool_name == "create_signal"
        assert log.response_status == 200
        assert len(log.id) == 36  # UUID format
        assert log.checksum != ""

    def test_checksum_generation(self):
        """测试校验和生成"""
        log1 = OperationLog.create(
            request_id="req-123",
            user_id=1,
            username="testuser",
            source=OperationSource.MCP,
            operation_type=OperationType.MCP_CALL,
            module="signal",
            action=OperationAction.CREATE,
        )

        log2 = OperationLog.create(
            request_id="req-456",  # Different request_id
            user_id=1,
            username="testuser",
            source=OperationSource.MCP,
            operation_type=OperationType.MCP_CALL,
            module="signal",
            action=OperationAction.CREATE,
        )

        # 不同的 request_id 应该产生不同的 checksum
        assert log1.checksum != log2.checksum

    def test_mask_sensitive_params_on_create(self):
        """测试创建时自动脱敏"""
        log = OperationLog.create(
            request_id="req-123",
            user_id=1,
            username="testuser",
            source=OperationSource.MCP,
            operation_type=OperationType.MCP_CALL,
            module="signal",
            action=OperationAction.CREATE,
            request_params={
                "password": "secret",
                "data": "value",
            },
        )

        assert log.request_params["password"] == "***"
        assert log.request_params["data"] == "value"

    def test_response_payload_masked_on_create(self):
        """测试响应载荷也会自动脱敏"""
        log = OperationLog.create(
            request_id="req-789",
            user_id=1,
            username="testuser",
            source=OperationSource.MCP,
            operation_type=OperationType.MCP_CALL,
            module="signal",
            action=OperationAction.READ,
            response_payload={
                "token": "secret-token",
                "nested": {"api_key": "k", "value": 1},
            },
            response_text='{"token":"secret-token"}',
        )

        assert log.response_payload["token"] == "***"
        assert log.response_payload["nested"]["api_key"] == "***"
        assert log.response_payload["nested"]["value"] == 1
        assert log.response_text == '{"token":"secret-token"}'
