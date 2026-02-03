"""
Alpha Trigger Application Module

Alpha 事件触发的 Application 层。

负责用例编排和事件处理。
"""

from .use_cases import (
    # DTOs
    CreateTriggerRequest,
    CreateTriggerResponse,
    CheckInvalidationRequest,
    CheckInvalidationResponse,
    EvaluateTriggerRequest,
    EvaluateTriggerResponse,
    GenerateCandidateRequest,
    GenerateCandidateResponse,
    GetActiveTriggersRequest,
    GetActiveTriggersResponse,
    # Use Cases
    CreateAlphaTriggerUseCase,
    CheckTriggerInvalidationUseCase,
    EvaluateAlphaTriggerUseCase,
    GenerateCandidateUseCase,
)

from .handlers import (
    AlphaTriggerEventHandler,
    TriggerInvalidationHandler,
    CandidatePromotionHandler,
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
