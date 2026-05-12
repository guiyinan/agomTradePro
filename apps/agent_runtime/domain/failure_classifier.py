"""
Domain Failure Classification And Recovery Service.

WP-M4-03: Classifies failures into deterministic types with recovery advice.

Failure types:
- validation_error: Input or state validation failed
- dependency_unavailable: External service unreachable
- data_stale: Upstream data is outdated
- authorization_blocked: RBAC or guardrail denied
- execution_failure: Action execution failed
- unknown_system_error: Unclassifiable error
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FailureType(str, Enum):
    VALIDATION_ERROR = "validation_error"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    DATA_STALE = "data_stale"
    AUTHORIZATION_BLOCKED = "authorization_blocked"
    EXECUTION_FAILURE = "execution_failure"
    UNKNOWN_SYSTEM_ERROR = "unknown_system_error"


@dataclass(frozen=True)
class FailureClassification:
    """Deterministic failure classification with recovery advice."""

    failure_type: FailureType
    retryable: bool
    recommended_action: str
    human_required: bool
    original_error: str | None = None
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for API responses and audit."""
        return {
            "failure_type": self.failure_type.value,
            "retryable": self.retryable,
            "recommended_action": self.recommended_action,
            "human_required": self.human_required,
            "original_error": self.original_error,
            "evidence": self.evidence or {},
        }


# ── Classification rules ─────────────────────────────────────

# Keywords → FailureType mapping for automated classification
_KEYWORD_RULES = [
    (["invalid", "validation", "must be one of", "required field"],
     FailureType.VALIDATION_ERROR),
    (["connection", "timeout", "unreachable", "503", "502", "unavailable"],
     FailureType.DEPENDENCY_UNAVAILABLE),
    (["stale", "freshness", "outdated", "expired data"],
     FailureType.DATA_STALE),
    (["permission", "forbidden", "403", "unauthorized", "rbac", "guardrail_blocked", "approval_not_granted"],
     FailureType.AUTHORIZATION_BLOCKED),
    (["execution", "failed to execute", "partial_failure", "execution_failed"],
     FailureType.EXECUTION_FAILURE),
]

_RECOVERY_MAP: dict[FailureType, tuple[bool, str, bool]] = {
    # (retryable, recommended_action, human_required)
    FailureType.VALIDATION_ERROR: (
        False,
        "Fix input data and re-submit the request",
        False,
    ),
    FailureType.DEPENDENCY_UNAVAILABLE: (
        True,
        "Retry after verifying the dependent service is available",
        False,
    ),
    FailureType.DATA_STALE: (
        True,
        "Trigger a data refresh and retry the task",
        False,
    ),
    FailureType.AUTHORIZATION_BLOCKED: (
        False,
        "Request elevated permissions or have an authorized user approve the action",
        True,
    ),
    FailureType.EXECUTION_FAILURE: (
        True,
        "Investigate the execution logs and retry or escalate to human",
        True,
    ),
    FailureType.UNKNOWN_SYSTEM_ERROR: (
        False,
        "Investigate system logs; escalate to support",
        True,
    ),
}


def classify_failure(
    error_message: str,
    error_code: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> FailureClassification:
    """
    Classify an error into a deterministic failure type.

    Args:
        error_message: The error message string
        error_code: Optional machine-readable error code
        evidence: Optional supporting evidence

    Returns:
        FailureClassification with type, retryability, and recovery advice
    """
    search_text = (error_message + " " + (error_code or "")).lower()

    failure_type = FailureType.UNKNOWN_SYSTEM_ERROR
    for keywords, ftype in _KEYWORD_RULES:
        if any(kw in search_text for kw in keywords):
            failure_type = ftype
            break

    retryable, action, human_required = _RECOVERY_MAP[failure_type]

    return FailureClassification(
        failure_type=failure_type,
        retryable=retryable,
        recommended_action=action,
        human_required=human_required,
        original_error=error_message,
        evidence=evidence,
    )
