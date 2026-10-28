"""
Compatibility exports for Decision Rhythm domain services.

Service implementations live in focused owner modules. This module remains the
stable import and patch surface used by applications, interfaces, and tests.

仅使用 Python 标准库。
"""

from __future__ import annotations

from .rhythm_services import (
    CooldownCheckResult,
    CooldownManager,
    DecisionScheduler,
    QuotaCheckResult,
    QuotaManager,
    RhythmManager,
    check_cooldown_status,
    check_quota_status,
    submit_decision_request,
)
from .unified_services import (
    DEFAULT_MODEL_PARAMS,
    MISSING_FEATURE_CONFIDENCE_PENALTY_PARAM_KEY,
    CompositeScoreCalculator,
    ConflictPair,
    GatePenalties,
    ModelWeights,
    RecommendationAggregator,
    apply_missing_feature_confidence_penalty,
    validate_missing_feature_confidence_penalty,
)
from .valuation_services import (
    ExecutionApprovalService,
    RecommendationConsolidationService,
    ValuationSnapshotService,
)
from .workflow_services import (
    ApprovalStatusStateMachine,
    CandidateStatusStateMachine,
    ExecutionResult,
    ExecutionStatusStateMachine,
    PrecheckResult,
)

__all__ = [
    "DEFAULT_MODEL_PARAMS",
    "MISSING_FEATURE_CONFIDENCE_PENALTY_PARAM_KEY",
    "ApprovalStatusStateMachine",
    "CandidateStatusStateMachine",
    "CompositeScoreCalculator",
    "ConflictPair",
    "CooldownCheckResult",
    "CooldownManager",
    "DecisionScheduler",
    "ExecutionApprovalService",
    "ExecutionResult",
    "ExecutionStatusStateMachine",
    "GatePenalties",
    "ModelWeights",
    "PrecheckResult",
    "QuotaCheckResult",
    "QuotaManager",
    "RecommendationAggregator",
    "RecommendationConsolidationService",
    "RhythmManager",
    "ValuationSnapshotService",
    "apply_missing_feature_confidence_penalty",
    "check_cooldown_status",
    "check_quota_status",
    "submit_decision_request",
    "validate_missing_feature_confidence_penalty",
]
