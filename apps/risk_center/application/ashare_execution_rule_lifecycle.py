"""Internal, fail-closed lifecycle primitive for Risk-owned execution rules."""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from apps.risk_center.domain import ashare_execution_rule_retirement as retirement_domain
from apps.risk_center.domain.ashare_execution_rule_retirement import (
    AShareExecutionRuleRetirementAuthorization,
    AShareExecutionRuleRetirementEvidence,
    AShareExecutionRuleRetirementIntent,
    AShareExecutionRuleRetirementTarget,
    AShareExecutionRuleRetirementValidationError,
    build_retirement_evidence,
    verify_retirement_replay,
)
from core.exceptions import AuthorizationError, BusinessLogicError, InvalidInputError

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class ExecutionRuleRetirementInputError(InvalidInputError):
    """The requested retirement intent is malformed or out of rule bounds."""

    default_message = "A-share execution rule retirement input is invalid"
    default_code = "A_SHARE_EXECUTION_RULE_RETIREMENT_INPUT_INVALID"


class ExecutionRuleRetirementDenied(AuthorizationError):
    """The injected server authority denied or failed to identify this caller."""

    default_message = "A-share execution rule retirement is not authorized"
    default_code = "A_SHARE_EXECUTION_RULE_RETIREMENT_DENIED"


class ExecutionRuleRetirementConflict(BusinessLogicError):
    """A request conflicts with the immutable rule or an earlier operation."""

    default_message = "A-share execution rule retirement conflicts with a prior winner"
    default_code = "A_SHARE_EXECUTION_RULE_RETIREMENT_CONFLICT"
    default_status_code = 409


class ExecutionRuleRetirementCorruption(BusinessLogicError):
    """Stored rule lifecycle or its required Audit pair is inconsistent."""

    default_message = "A-share execution rule retirement state is inconsistent"
    default_code = "A_SHARE_EXECUTION_RULE_RETIREMENT_CORRUPT"
    default_status_code = 503


class ExecutionRuleRetirementUnavailable(BusinessLogicError):
    """The required rule store, trusted authority, or same-alias Audit is unavailable."""

    default_message = "A-share execution rule retirement is temporarily unavailable"
    default_code = "A_SHARE_EXECUTION_RULE_RETIREMENT_UNAVAILABLE"
    default_status_code = 503


class ExecutionRuleRetirementNotFound(ExecutionRuleRetirementUnavailable):
    """The exact rule hash named by a retirement intent is absent."""

    default_message = "The exact A-share execution rule retirement target was not found"
    default_code = "A_SHARE_EXECUTION_RULE_RETIREMENT_TARGET_NOT_FOUND"
    default_status_code = 404


class RuleLifecycleAuthorizationDenied(AuthorizationError):
    """The trusted lifecycle authority explicitly denied this request."""

    default_message = "Trusted authority denied A-share execution rule retirement"
    default_code = "A_SHARE_EXECUTION_RULE_RETIREMENT_AUTHORITY_DENIED"
    default_status_code = 403


class RuleLifecycleAuthorizer(Protocol):
    """Server-side identity and scope authority for internal lifecycle writes."""

    def authorize(
        self,
        *,
        intent: AShareExecutionRuleRetirementIntent,
        as_of: datetime,
    ) -> AShareExecutionRuleRetirementAuthorization:
        """Return trusted actor and Audit scope or deny the operation."""


class AShareExecutionRuleLifecycleClock(Protocol):
    """Clock port for the server-recorded retirement knowledge time."""

    def now(self) -> datetime:
        """Return one aware server time."""


class AShareExecutionRuleLifecycleRepository(Protocol):
    """Persistence capability fenced on one security and one database alias."""

    @property
    def database_alias(self) -> str:
        """Return the alias used by rule storage."""

    def retirement_transaction(self, *, security_id: str) -> AbstractContextManager[None]:
        """Open the outermost same-security transaction and acquire its writer fence."""

    def get_retirement_target(
        self,
        *,
        intent: AShareExecutionRuleRetirementIntent,
    ) -> AShareExecutionRuleRetirementTarget:
        """Read and validate the exact immutable rule and its retirement columns."""

    def persist_retirement(
        self,
        *,
        intent: AShareExecutionRuleRetirementIntent,
        evidence: AShareExecutionRuleRetirementEvidence,
    ) -> None:
        """Set all retirement columns once without changing canonical rule content."""


@dataclass(frozen=True, slots=True)
class AShareExecutionRuleRetirementAuditReceipt:
    """Risk-owned receipt for the exact canonical retirement Audit pair."""

    request_id: UUID
    request_hash: str
    event_content_hash: str
    outbox_id: UUID

    def __post_init__(self) -> None:
        """Reject receipts that do not identify one exact request and Audit pair."""

        if type(self.request_id) is not UUID:
            raise ValueError("request_id must be a UUID")
        for name, value in (
            ("request_hash", self.request_hash),
            ("event_content_hash", self.event_content_hash),
        ):
            if type(value) is not str or _HASH_RE.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if type(self.outbox_id) is not UUID:
            raise ValueError("outbox_id must be a UUID")


class AShareExecutionRuleRetirementAuditPort(Protocol):
    """Risk-owned capability for an atomic retirement Audit pair operation."""

    @property
    def database_alias(self) -> str:
        """Return the alias shared by the rule transaction and Audit storage."""

    def execute_retirement_in_caller_transaction(
        self,
        *,
        intent: AShareExecutionRuleRetirementIntent,
        authorization: AShareExecutionRuleRetirementAuthorization,
        evidence: AShareExecutionRuleRetirementEvidence,
        exact_replay: bool,
    ) -> AShareExecutionRuleRetirementAuditReceipt:
        """Append or verify the exact retirement event and return its receipt."""


@dataclass(frozen=True, slots=True)
class AShareExecutionRuleRetirementResult:
    """Committed retirement facts and its exact Audit receipt."""

    security_id: str
    rule_id: str
    rule_version: str
    content_hash: str
    request_id: UUID
    effective_at: datetime
    recorded_at: datetime
    request_hash: str
    audit_event_hash: str
    audit_outbox_id: UUID
    exact_replay: bool


class RetireAShareExecutionRuleUseCase:
    """Retire one exact rule once, atomically with its canonical Audit pair."""

    def __init__(
        self,
        *,
        repository: AShareExecutionRuleLifecycleRepository,
        authorizer: RuleLifecycleAuthorizer,
        audit: AShareExecutionRuleRetirementAuditPort,
        clock: AShareExecutionRuleLifecycleClock,
    ) -> None:
        """Require explicit repository, trusted authority, Audit, and clock ports."""

        if repository is None or authorizer is None or audit is None or clock is None:
            raise ValueError("rule retirement requires every injected capability")
        if (
            type(repository.database_alias) is not str
            or not repository.database_alias
            or repository.database_alias != audit.database_alias
        ):
            raise ValueError("rule repository and Audit must share one database alias")
        self._repository = repository
        self._authorizer = authorizer
        self._audit = audit
        self._clock = clock

    def execute(
        self,
        *,
        intent: AShareExecutionRuleRetirementIntent,
    ) -> AShareExecutionRuleRetirementResult:
        """Record a one-time retirement or verify its exact idempotent replay."""

        if type(intent) is not AShareExecutionRuleRetirementIntent:
            raise ExecutionRuleRetirementInputError("retirement requires an exact typed intent")
        try:
            AShareExecutionRuleRetirementIntent.__post_init__(intent)
        except (TypeError, ValueError) as error:
            raise ExecutionRuleRetirementInputError("retirement intent is invalid") from error

        authorized_at = self._read_clock()
        authorization = self._authorize(intent=intent, as_of=authorized_at)

        try:
            with self._repository.retirement_transaction(security_id=intent.security_id):
                target = self._repository.get_retirement_target(intent=intent)
                if type(target) is not AShareExecutionRuleRetirementTarget:
                    raise ExecutionRuleRetirementCorruption(
                        "rule repository returned an invalid retirement target"
                    )
                recorded_at = self._read_clock()
                if recorded_at < authorized_at:
                    raise ExecutionRuleRetirementUnavailable(
                        "retirement clock moved backwards while acquiring its writer fence"
                    )
                final_authorization = self._authorize(intent=intent, as_of=recorded_at)
                if final_authorization != authorization:
                    raise ExecutionRuleRetirementDenied(
                        "trusted retirement authority changed during the operation"
                    )
                try:
                    AShareExecutionRuleRetirementTarget.__post_init__(target)
                    if target.retirement.is_empty:
                        if intent.effective_at < recorded_at:
                            raise ExecutionRuleRetirementInputError(
                                "retirement effective time passed before the write fence"
                            )
                        evidence = build_retirement_evidence(
                            target=target,
                            intent=intent,
                            authorization=final_authorization,
                            recorded_at=recorded_at,
                        )
                        self._repository.persist_retirement(intent=intent, evidence=evidence)
                        exact_replay = False
                    else:
                        evidence = verify_retirement_replay(
                            target=target,
                            intent=intent,
                            authorization=final_authorization,
                        )
                        exact_replay = True
                except retirement_domain.AShareExecutionRuleRetirementConflict as error:
                    raise ExecutionRuleRetirementConflict(str(error)) from error
                except AShareExecutionRuleRetirementValidationError as error:
                    raise ExecutionRuleRetirementInputError(str(error)) from error
                try:
                    receipt = self._audit.execute_retirement_in_caller_transaction(
                        intent=intent,
                        authorization=final_authorization,
                        evidence=evidence,
                        exact_replay=exact_replay,
                    )
                except (
                    ExecutionRuleRetirementConflict,
                    ExecutionRuleRetirementCorruption,
                    ExecutionRuleRetirementUnavailable,
                ):
                    raise
                receipt = _validate_audit_receipt(receipt=receipt, evidence=evidence)
                assert evidence.retirement_effective_at is not None
                assert evidence.retirement_recorded_at is not None
                assert evidence.retirement_request_hash is not None
                assert evidence.retirement_request_id is not None
                return AShareExecutionRuleRetirementResult(
                    security_id=intent.security_id,
                    rule_id=intent.rule_id,
                    rule_version=intent.rule_version,
                    content_hash=intent.expected_content_hash,
                    request_id=intent.request_id,
                    effective_at=evidence.retirement_effective_at,
                    recorded_at=evidence.retirement_recorded_at,
                    request_hash=evidence.retirement_request_hash,
                    audit_event_hash=receipt.event_content_hash,
                    audit_outbox_id=receipt.outbox_id,
                    exact_replay=exact_replay,
                )
        except (
            ExecutionRuleRetirementInputError,
            ExecutionRuleRetirementDenied,
            ExecutionRuleRetirementConflict,
            ExecutionRuleRetirementCorruption,
            ExecutionRuleRetirementUnavailable,
            ExecutionRuleRetirementNotFound,
        ):
            raise
        except Exception as error:
            raise ExecutionRuleRetirementUnavailable(
                "retirement transaction could not complete"
            ) from error

    def _read_clock(self) -> datetime:
        """Read one aware server time, classifying clock failures for callers."""

        try:
            value = self._clock.now()
        except Exception as error:
            raise ExecutionRuleRetirementUnavailable("retirement clock is unavailable") from error
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise ExecutionRuleRetirementUnavailable("retirement clock returned a naive time")
        return value

    def _authorize(
        self,
        *,
        intent: AShareExecutionRuleRetirementIntent,
        as_of: datetime,
    ) -> AShareExecutionRuleRetirementAuthorization:
        """Resolve and validate trusted actor and scope at one exact cutoff."""

        try:
            authorization = self._authorizer.authorize(intent=intent, as_of=as_of)
        except RuleLifecycleAuthorizationDenied as error:
            raise ExecutionRuleRetirementDenied() from error
        except Exception as error:
            raise ExecutionRuleRetirementUnavailable(
                "trusted retirement authority is unavailable"
            ) from error
        if type(authorization) is not AShareExecutionRuleRetirementAuthorization:
            raise ExecutionRuleRetirementDenied("trusted authority returned no exact actor/scope")
        try:
            AShareExecutionRuleRetirementAuthorization.__post_init__(authorization)
        except (TypeError, ValueError) as error:
            raise ExecutionRuleRetirementDenied(
                "trusted authority returned invalid actor/scope"
            ) from error
        return authorization


def _validate_audit_receipt(
    *,
    receipt: AShareExecutionRuleRetirementAuditReceipt,
    evidence: AShareExecutionRuleRetirementEvidence,
) -> AShareExecutionRuleRetirementAuditReceipt:
    """Validate the Risk port receipt against persisted retirement evidence."""

    if type(receipt) is not AShareExecutionRuleRetirementAuditReceipt:
        raise ExecutionRuleRetirementCorruption("Audit port returned an invalid receipt type")
    try:
        AShareExecutionRuleRetirementAuditReceipt.__post_init__(receipt)
    except (TypeError, ValueError) as error:
        raise ExecutionRuleRetirementCorruption(
            "Audit port receipt failed integrity validation"
        ) from error
    if (
        evidence.retirement_request_id is None
        or evidence.retirement_request_hash is None
        or receipt.request_id != evidence.retirement_request_id
        or receipt.request_hash != evidence.retirement_request_hash
    ):
        raise ExecutionRuleRetirementCorruption(
            "Audit port receipt does not bind the persisted retirement request"
        )
    return receipt


__all__ = [
    "AShareExecutionRuleLifecycleClock",
    "AShareExecutionRuleLifecycleRepository",
    "AShareExecutionRuleRetirementAuditPort",
    "AShareExecutionRuleRetirementAuditReceipt",
    "AShareExecutionRuleRetirementResult",
    "ExecutionRuleRetirementConflict",
    "ExecutionRuleRetirementCorruption",
    "ExecutionRuleRetirementDenied",
    "ExecutionRuleRetirementInputError",
    "ExecutionRuleRetirementNotFound",
    "ExecutionRuleRetirementUnavailable",
    "RetireAShareExecutionRuleUseCase",
    "RuleLifecycleAuthorizationDenied",
    "RuleLifecycleAuthorizer",
]
