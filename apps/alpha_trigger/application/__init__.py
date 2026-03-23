"""
Alpha Trigger Application Module

Alpha 事件触发的 Application 层。

负责用例编排和事件处理。
"""

from .handlers import (
    AlphaTriggerEventHandler,
    CandidatePromotionHandler,
    TriggerInvalidationHandler,
)
from .use_cases import (
    CheckInvalidationRequest,
    CheckInvalidationResponse,
    CheckTriggerInvalidationUseCase,
    # Use Cases
    CreateAlphaTriggerUseCase,
    # DTOs
    CreateTriggerRequest,
    CreateTriggerResponse,
    EvaluateAlphaTriggerUseCase,
    EvaluateTriggerRequest,
    EvaluateTriggerResponse,
    GenerateCandidateRequest,
    GenerateCandidateResponse,
    GenerateCandidateUseCase,
    GetActiveTriggersRequest,
    GetActiveTriggersResponse,
)

__all__ = [
    # DTOs
    "CreateTriggerRequest",
    "CreateTriggerResponse",
    "CheckInvalidationRequest",
    "CheckInvalidationResponse",
    "EvaluateTriggerRequest",
    "EvaluateTriggerResponse",
    "GenerateCandidateRequest",
    "GenerateCandidateResponse",
    "GetActiveTriggersRequest",
    "GetActiveTriggersResponse",
    # Use Cases
    "CreateAlphaTriggerUseCase",
    "CheckTriggerInvalidationUseCase",
    "EvaluateAlphaTriggerUseCase",
    "GenerateCandidateUseCase",
    # Event Handlers
    "AlphaTriggerEventHandler",
    "TriggerInvalidationHandler",
    "CandidatePromotionHandler",
]
