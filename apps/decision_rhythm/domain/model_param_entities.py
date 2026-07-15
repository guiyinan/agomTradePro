"""Decision model parameter configuration and audit entities."""

from datetime import UTC, datetime
from typing import Any


class ModelParamConfig:
    """
    模型参数配置

    保存推荐模型参数（按环境/版本）。

    Attributes:
        config_id: 配置唯一标识
        param_key: 参数键
        param_value: 参数值
        param_type: 参数类型 (float/int/str/bool)
        env: 环境 (dev/test/prod)
        version: 版本号
        is_active: 是否激活
        description: 参数描述
        updated_by: 最后修改人
        updated_reason: 变更说明
        created_at: 创建时间
        updated_at: 更新时间
    """

    config_id: str
    param_key: str
    param_value: str
    param_type: str
    env: str
    version: int
    is_active: bool
    description: str
    updated_by: str
    updated_reason: str
    created_at: datetime
    updated_at: datetime

    def __init__(
        self,
        config_id: str,
        param_key: str,
        param_value: str,
        param_type: str = "float",
        env: str = "dev",
        version: int = 1,
        is_active: bool = True,
        description: str = "",
        updated_by: str = "",
        updated_reason: str = "",
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ):
        self.config_id = config_id
        self.param_key = param_key
        self.param_value = param_value
        self.param_type = param_type
        self.env = env
        self.version = version
        self.is_active = is_active
        self.description = description
        self.updated_by = updated_by
        self.updated_reason = updated_reason
        self.created_at = created_at or datetime.now(UTC)
        self.updated_at = updated_at or datetime.now(UTC)

    def __repr__(self) -> str:
        return f"ModelParamConfig({self.param_key}={self.param_value}, env={self.env})"

    def get_typed_value(self) -> Any:
        """
        获取类型化的参数值

        Returns:
            根据参数类型转换后的值
        """
        if self.param_type == "float":
            return float(self.param_value)
        elif self.param_type == "int":
            return int(self.param_value)
        elif self.param_type == "bool":
            return self.param_value.lower() in ("true", "1", "yes")
        else:
            return self.param_value


class ModelParamAuditLog:
    """
    模型参数审计日志

    保存参数变更审计日志（前后值、操作者、时间、备注）。

    Attributes:
        log_id: 日志唯一标识
        param_key: 参数键
        old_value: 旧值
        new_value: 新值
        env: 环境
        changed_by: 变更人
        change_reason: 变更原因
        changed_at: 变更时间
    """

    log_id: str
    param_key: str
    old_value: str
    new_value: str
    env: str
    changed_by: str
    change_reason: str
    changed_at: datetime

    def __init__(
        self,
        log_id: str,
        param_key: str,
        old_value: str,
        new_value: str,
        env: str = "dev",
        changed_by: str = "",
        change_reason: str = "",
        changed_at: datetime | None = None,
    ):
        self.log_id = log_id
        self.param_key = param_key
        self.old_value = old_value
        self.new_value = new_value
        self.env = env
        self.changed_by = changed_by
        self.change_reason = change_reason
        self.changed_at = changed_at or datetime.now(UTC)

    def __repr__(self) -> str:
        return (
            f"ModelParamAuditLog({self.param_key}, "
            f"{self.old_value} -> {self.new_value}, by={self.changed_by})"
        )


__all__ = ["ModelParamConfig", "ModelParamAuditLog"]
