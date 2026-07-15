"""Decision model parameter query and update use cases."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Protocol

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.utils import timezone

if TYPE_CHECKING:
    from ..domain.entities import (
        GatePenalties,
        ModelParamAuditLog,
        ModelParamConfig,
        ModelWeights,
    )


logger = logging.getLogger(__name__)

RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    DatabaseError,
    ImportError,
    ImproperlyConfigured,
    LookupError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


class ModelParamConfigRepositoryProtocol(Protocol):
    """模型参数配置仓储协议"""

    def get_param(
        self,
        param_key: str,
        env: str,
    ) -> Optional["ModelParamConfig"]:
        """获取参数配置"""
        ...

    def get_all_params(self, env: str) -> list["ModelParamConfig"]:
        """获取所有参数配置"""
        ...

    def save_param(
        self,
        config: "ModelParamConfig",
    ) -> "ModelParamConfig":
        """保存参数配置"""
        ...

    def create_audit_log(
        self,
        log: "ModelParamAuditLog",
    ) -> "ModelParamAuditLog":
        """创建审计日志"""
        ...


class GetModelParamsUseCase:
    """
    获取模型参数用例

    实现参数读取的完整回退链：
    1. 数据库配置表
    2. 内置默认值（兜底）
    """

    def __init__(
        self,
        param_repo: ModelParamConfigRepositoryProtocol,
        default_env: str = "dev",
    ):
        """
        初始化用例

        Args:
            param_repo: 参数配置仓储
            default_env: 默认环境
        """
        self.param_repo = param_repo
        self.default_env = default_env

    def execute(
        self,
        env: str | None = None,
    ) -> dict[str, Any]:
        """
        获取所有模型参数

        Args:
            env: 环境（可选，默认使用 default_env）

        Returns:
            参数字典
        """
        from ..domain.services import DEFAULT_MODEL_PARAMS

        target_env = env or self.default_env

        # 从数据库获取参数
        db_params = self.param_repo.get_all_params(target_env)

        # 构建参数字典
        params = dict(DEFAULT_MODEL_PARAMS)  # 从默认值开始

        # 用数据库配置覆盖
        for config in db_params:
            if config.is_active:
                typed_value = config.get_typed_value()
                params[config.param_key] = typed_value

        return params

    def get_param(
        self,
        param_key: str,
        env: str | None = None,
    ) -> Any:
        """
        获取单个参数

        Args:
            param_key: 参数键
            env: 环境（可选）

        Returns:
            参数值
        """
        from ..domain.services import DEFAULT_MODEL_PARAMS

        target_env = env or self.default_env

        # 尝试从数据库获取
        config = self.param_repo.get_param(param_key, target_env)

        if config and config.is_active:
            return config.get_typed_value()

        # 回退到默认值
        if param_key in DEFAULT_MODEL_PARAMS:
            return DEFAULT_MODEL_PARAMS[param_key]

        raise ValueError(f"Unknown parameter: {param_key}")

    def get_model_weights(
        self,
        env: str | None = None,
    ) -> "ModelWeights":
        """
        获取模型权重配置

        Args:
            env: 环境（可选）

        Returns:
            ModelWeights 实例
        """
        from ..domain.services import ModelWeights

        params = self.execute(env)

        return ModelWeights(
            alpha_model_weight=params.get("alpha_model_weight", 0.40),
            sentiment_weight=params.get("sentiment_weight", 0.15),
            flow_weight=params.get("flow_weight", 0.15),
            technical_weight=params.get("technical_weight", 0.15),
            fundamental_weight=params.get("fundamental_weight", 0.15),
        )

    def get_gate_penalties(
        self,
        env: str | None = None,
    ) -> "GatePenalties":
        """
        获取 Gate 惩罚参数

        Args:
            env: 环境（可选）

        Returns:
            GatePenalties 实例
        """
        from ..domain.services import GatePenalties

        params = self.execute(env)

        return GatePenalties(
            cooldown_penalty=params.get("gate_penalty_cooldown", 0.10),
            quota_penalty=params.get("gate_penalty_quota", 0.10),
            volatility_penalty=params.get("gate_penalty_volatility", 0.10),
        )


@dataclass
class UpdateModelParamRequest:
    """更新模型参数请求"""

    param_key: str
    param_value: str
    param_type: str = "float"
    env: str = "dev"
    updated_by: str = ""
    updated_reason: str = ""


@dataclass
class UpdateModelParamResponse:
    """更新模型参数响应"""

    success: bool
    config: Optional["ModelParamConfig"] = None
    error: str = ""


class UpdateModelParamUseCase:
    """
    更新模型参数用例

    实现参数更新并记录审计日志。
    """

    def __init__(
        self,
        param_repo: ModelParamConfigRepositoryProtocol,
    ):
        """
        初始化用例

        Args:
            param_repo: 参数配置仓储
        """
        self.param_repo = param_repo

    def execute(
        self,
        request: UpdateModelParamRequest,
    ) -> UpdateModelParamResponse:
        """
        执行参数更新

        Args:
            request: 更新请求

        Returns:
            更新响应
        """

        from uuid import uuid4

        from ..domain.entities import ModelParamAuditLog, ModelParamConfig

        try:
            # 获取旧值
            old_config = self.param_repo.get_param(request.param_key, request.env)
            old_value = old_config.param_value if old_config else ""

            # 创建或更新配置
            if old_config:
                config = ModelParamConfig(
                    config_id=f"mpc_{uuid4().hex[:12]}",
                    param_key=request.param_key,
                    param_value=request.param_value,
                    param_type=request.param_type,
                    env=request.env,
                    version=old_config.version + 1,
                    is_active=True,
                    description=old_config.description,
                    updated_by=request.updated_by,
                    updated_reason=request.updated_reason,
                    created_at=old_config.created_at,
                    updated_at=timezone.now(),
                )
            else:
                config = ModelParamConfig(
                    config_id=f"mpc_{uuid4().hex[:12]}",
                    param_key=request.param_key,
                    param_value=request.param_value,
                    param_type=request.param_type,
                    env=request.env,
                    version=1,
                    is_active=True,
                    description="",
                    updated_by=request.updated_by,
                    updated_reason=request.updated_reason,
                )

            # 保存配置
            saved_config = self.param_repo.save_param(config)

            # 创建审计日志
            audit_log = ModelParamAuditLog(
                log_id=f"mpal_{uuid4().hex[:12]}",
                param_key=request.param_key,
                old_value=old_value,
                new_value=request.param_value,
                env=request.env,
                changed_by=request.updated_by,
                change_reason=request.updated_reason,
            )
            self.param_repo.create_audit_log(audit_log)

            logger.info(
                f"Model param updated: {request.param_key} = {request.param_value} "
                f"(env={request.env}, by={request.updated_by})"
            )

            return UpdateModelParamResponse(
                success=True,
                config=saved_config,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to update model param: {e}", exc_info=True)
            return UpdateModelParamResponse(
                success=False,
                error=str(e),
            )


__all__ = [
    "ModelParamConfigRepositoryProtocol",
    "GetModelParamsUseCase",
    "UpdateModelParamRequest",
    "UpdateModelParamResponse",
    "UpdateModelParamUseCase",
]
