"""Decision model parameter query and update use cases."""

import logging
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.utils import timezone

if TYPE_CHECKING:
    from ..domain.entities import ModelParamAuditLog, ModelParamConfig
    from ..domain.services import GatePenalties, ModelWeights


logger = logging.getLogger(__name__)

_PARAM_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_PARAM_TYPES = frozenset({"float", "int", "str", "bool"})
_PARAM_ENVS = frozenset({"dev", "test", "prod"})
_TRUE_VALUES = frozenset({"true", "1", "yes"})
_FALSE_VALUES = frozenset({"false", "0", "no"})

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
    ) -> "ModelParamConfig | None":
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
    ) -> None:
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
        params: dict[str, Any] = dict(DEFAULT_MODEL_PARAMS)  # 从默认值开始

        # 用数据库配置覆盖
        for config in db_params:
            if config.is_active:
                typed_value = _parse_param_value(config.param_value, config.param_type)
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
            return _parse_param_value(config.param_value, config.param_type)

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
            alpha_model_weight=_finite_float(params.get("alpha_model_weight", 0.40)),
            sentiment_weight=_finite_float(params.get("sentiment_weight", 0.15)),
            flow_weight=_finite_float(params.get("flow_weight", 0.15)),
            technical_weight=_finite_float(params.get("technical_weight", 0.15)),
            fundamental_weight=_finite_float(params.get("fundamental_weight", 0.15)),
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
            cooldown_penalty=_finite_float(params.get("gate_penalty_cooldown", 0.10)),
            quota_penalty=_finite_float(params.get("gate_penalty_quota", 0.10)),
            volatility_penalty=_finite_float(params.get("gate_penalty_volatility", 0.10)),
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
    config: "ModelParamConfig | None" = None
    error: str = ""


class UpdateModelParamUseCase:
    """
    更新模型参数用例

    实现参数更新并记录审计日志。
    """

    def __init__(
        self,
        param_repo: ModelParamConfigRepositoryProtocol,
    ) -> None:
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
            _validate_update_request(request)
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
                "Model parameter updated (key=%s, env=%s, actor=%s)",
                request.param_key,
                request.env,
                request.updated_by or "system",
            )

            return UpdateModelParamResponse(
                success=True,
                config=saved_config,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as exc:
            logger.error(
                "Model parameter update failed (key=%s, error_type=%s)",
                request.param_key[:128],
                type(exc).__name__,
            )
            return UpdateModelParamResponse(
                success=False,
                error="decision_model_parameter_update_failed",
            )


def _finite_float(value: object) -> float:
    """Return a finite numeric parameter value."""

    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("boolean is not a numeric parameter")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("numeric parameter must be finite")
    return parsed


def _parse_param_value(value: str, param_type: str) -> float | int | str | bool:
    """Validate and parse one persisted model parameter value."""

    if param_type not in _PARAM_TYPES:
        raise ValueError("unsupported model parameter type")
    if len(value) > 4096 or any(ord(character) < 32 for character in value):
        raise ValueError("invalid model parameter value")
    if param_type == "float":
        return _finite_float(value)
    if param_type == "int":
        return int(value)
    if param_type == "bool":
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
        raise ValueError("invalid boolean model parameter")
    return value


def _validate_update_request(request: UpdateModelParamRequest) -> None:
    """Fail closed on malformed or unbounded model parameter updates."""

    if not _PARAM_KEY_PATTERN.fullmatch(request.param_key):
        raise ValueError("invalid model parameter key")
    if request.env not in _PARAM_ENVS:
        raise ValueError("invalid model parameter environment")
    _parse_param_value(request.param_value, request.param_type)
    if len(request.updated_by) > 128 or len(request.updated_reason) > 2000:
        raise ValueError("model parameter audit metadata is too long")


__all__ = [
    "ModelParamConfigRepositoryProtocol",
    "GetModelParamsUseCase",
    "UpdateModelParamRequest",
    "UpdateModelParamResponse",
    "UpdateModelParamUseCase",
]
