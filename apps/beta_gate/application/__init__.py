"""
Beta Gate Application Module

硬闸门过滤的 Application 层。

负责用例编排和事件处理。
"""

from .handlers import (
    BetaGateEventHandler,
    GateInvalidationHandler,
)
from .use_cases import (
    BuildUniverseRequest,
    BuildUniverseResponse,
    BuildVisibilityUniverseUseCase,
    EvaluateBatchRequest,
    EvaluateBatchResponse,
    EvaluateBatchUseCase,
    # Use Cases
    EvaluateBetaGateUseCase,
    # DTOs
    EvaluateGateRequest,
    EvaluateGateResponse,
    GetGateConfigRequest,
    GetGateConfigResponse,
    GetGateConfigUseCase,
)

__all__ = [
    # DTOs
    "EvaluateGateRequest",
    "EvaluateGateResponse",
    "GetGateConfigRequest",
    "GetGateConfigResponse",
    "BuildUniverseRequest",
    "BuildUniverseResponse",
    "EvaluateBatchRequest",
    "EvaluateBatchResponse",
    # Use Cases
    "EvaluateBetaGateUseCase",
    "EvaluateBatchUseCase",
    "GetGateConfigUseCase",
    "BuildVisibilityUniverseUseCase",
    # Event Handlers
    "BetaGateEventHandler",
    "GateInvalidationHandler",
]
