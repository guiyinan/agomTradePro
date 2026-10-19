"""Claim one automatic invocation before starting its non-resumable engine run."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from typing import Protocol, TypedDict
from uuid import UUID

from apps.simulated_trading.application.auto_trading_outcome_reporting import (
    build_auto_trading_batch_outcome_from_engine_results,
    build_indeterminate_auto_trading_batch,
)
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingBatchOutcome,
    AutoTradingIssue,
    AutoTradingIssueKind,
    build_auto_trading_batch_outcome,
)
from core.exceptions import BusinessLogicError, DuplicateResourceError, InvalidInputError

logger = logging.getLogger(__name__)


class AutoTradingInvocationConflict(DuplicateResourceError):
    """Reject rebinding a caller's run key to another exact request."""

    default_code = "AUTO_TRADING_RUN_IDEMPOTENCY_CONFLICT"
    default_message = "该自动交易操作已绑定其他输入，请使用新的操作重新提交"


class AutoTradingInvocationUnavailable(BusinessLogicError):
    """Reject an invalid or unavailable persisted run without restarting it."""

    default_code = "AUTO_TRADING_RUN_UNAVAILABLE"
    default_message = "自动交易运行记录不可用，未重新执行交易"


def validate_auto_invocation_key(value: object) -> str:
    """Require an opaque caller key without manufacturing an identity on retry."""
    if (
        type(value) is not str
        or not value
        or len(value) > 128
        or any(character.isspace() for character in value)
    ):
        raise InvalidInputError(
            "自动交易需要有效的操作标识", code="AUTO_TRADING_INVOCATION_KEY_REQUIRED"
        )
    return value


def _validate_ids(value: tuple[int, ...]) -> None:
    if type(value) is not tuple or any(type(item) is not int or item <= 0 for item in value):
        raise InvalidInputError("account_ids must contain exact positive integers")
    if len(set(value)) != len(value):
        raise InvalidInputError("account_ids must not contain duplicates")


class AutoTradingRequestPayload(TypedDict, total=False):
    """Validated serializer fields; omitted fields remain omitted in run identity."""

    trade_date: date
    account_ids: list[int]


@dataclass(frozen=True, slots=True)
class AutoTradingRequestActor:
    """Authenticated caller attributes copied at the HTTP authorization boundary."""

    id: int
    is_superuser: bool

    def __post_init__(self) -> None:
        """Reject an invalid authenticated principal before any repository call."""
        if type(self.id) is not int or self.id <= 0 or type(self.is_superuser) is not bool:
            raise InvalidInputError("authenticated automatic-trading actor is invalid")

    @property
    def is_authenticated(self) -> bool:
        """Expose the existing owner-scope authorization interface."""
        return True


@dataclass(frozen=True, slots=True)
class AutoTradingInvocationRequest:
    """Preserve omitted date/scope separately from their first resolved values."""

    namespace: str
    invocation_key: str
    trade_date: date | None
    requested_account_ids: tuple[int, ...] | None

    def __post_init__(self) -> None:
        """Validate technical identity and exact caller input before persistence."""
        validate_auto_invocation_key(self.invocation_key)
        if (
            type(self.namespace) is not str
            or not self.namespace
            or len(self.namespace) > 96
            or any(character.isspace() for character in self.namespace)
        ):
            raise InvalidInputError("automatic invocation namespace is invalid")
        if self.trade_date is not None and type(self.trade_date) is not date:
            raise InvalidInputError("trade_date must be an exact date or omitted")
        if self.requested_account_ids is not None:
            _validate_ids(self.requested_account_ids)

    def to_payload(self) -> dict[str, object]:
        """Return only original input, excluding changing default scope and date."""
        return {
            "schema": "simulated_auto_invocation_request.v1",
            "trade_date": self.trade_date.isoformat() if self.trade_date is not None else None,
            "account_ids": (
                list(self.requested_account_ids) if self.requested_account_ids is not None else None
            ),
        }

    @property
    def content_hash(self) -> str:
        """Bind exact input and omission semantics within the caller namespace."""
        payload = json.dumps(self.to_payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FrozenAutoTradingScope:
    """The actual date and authorized accounts selected for one invocation."""

    trade_date: date
    account_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        """Reject malformed stored scope before invoking an engine."""
        if type(self.trade_date) is not date:
            raise InvalidInputError("frozen trade_date must be an exact date")
        _validate_ids(self.account_ids)


@dataclass(frozen=True, slots=True)
class AutoTradingInvocationClaim:
    """A single acquired preparation token or a read-only prior invocation."""

    invocation_id: UUID
    claim_token: UUID
    scope: FrozenAutoTradingScope
    acquired: bool
    outcome: AutoTradingBatchOutcome | None


class AutoTradingInvocationRepository(Protocol):
    """Durable invocation guard; it never resumes or regenerates action lists."""

    def find_scope(self, request: AutoTradingInvocationRequest) -> FrozenAutoTradingScope | None:
        """Read an exact prior scope, rejecting a key/input conflict."""
        ...

    def claim(
        self, request: AutoTradingInvocationRequest, scope: FrozenAutoTradingScope
    ) -> AutoTradingInvocationClaim:
        """Atomically acquire only a new or explicitly released preparation."""
        ...

    def release_preparation(self, *, invocation_id: UUID, claim_token: UUID) -> None:
        """Release a known pre-engine setup failure using its exact claim token."""
        ...

    def mark_started(self, *, invocation_id: UUID, claim_token: UUID) -> None:
        """Persist the no-reentry boundary before calling the engine."""
        ...

    def finish(
        self, *, invocation_id: UUID, claim_token: UUID, outcome: AutoTradingBatchOutcome
    ) -> None:
        """Save the typed result without changing immutable request or scope."""
        ...


class AutomaticInvocationEngine(Protocol):
    """The existing automatic engine surface used by one claimed invocation."""

    def run_daily_trading(
        self, trade_date: date, account_ids: list[int] | None = None
    ) -> dict[int, AccountAutoTradingOutcome]:
        """Execute once, retaining per-account business outcomes."""
        ...


@dataclass(frozen=True, slots=True)
class AutoTradingInvocationResult:
    """Return the original date and result, including replayed default scopes."""

    invocation_id: UUID
    scope: FrozenAutoTradingScope
    outcome: AutoTradingBatchOutcome
    replayed: bool


class ExecuteAutomaticInvocation:
    """Guard entry and preserve the existing no-whole-batch-retry boundary."""

    def __init__(self, repository: AutoTradingInvocationRepository) -> None:
        """Require the durable infrastructure implementation through its port."""
        self._repository = repository

    def execute(
        self,
        request: AutoTradingInvocationRequest,
        *,
        resolve_scope: Callable[[], FrozenAutoTradingScope],
        authorize_scope: Callable[[FrozenAutoTradingScope], None],
        build_engine: Callable[[UUID], AutomaticInvocationEngine],
    ) -> AutoTradingInvocationResult:
        """Replay a saved result or start exactly one initial engine execution."""
        if type(request) is not AutoTradingInvocationRequest:
            raise InvalidInputError("an exact automatic invocation request is required")
        request.__post_init__()
        scope = self._repository.find_scope(request)
        if scope is None:
            scope = resolve_scope()
        authorize_scope(scope)
        claim = self._repository.claim(request, scope)
        if claim.scope != scope:
            authorize_scope(claim.scope)
        if not claim.acquired:
            outcome = claim.outcome
            if outcome is None:
                outcome = build_indeterminate_auto_trading_batch(
                    claim.scope.account_ids, code="EXECUTION_OUTCOME_UNKNOWN"
                )
            return AutoTradingInvocationResult(claim.invocation_id, claim.scope, outcome, True)

        try:
            engine = build_engine(claim.invocation_id) if claim.scope.account_ids else None
        except Exception:
            # Only preparation is released. Never release a started execution.
            self._repository.release_preparation(
                invocation_id=claim.invocation_id, claim_token=claim.claim_token
            )
            raise
        self._repository.mark_started(
            invocation_id=claim.invocation_id, claim_token=claim.claim_token
        )
        try:
            if engine is None:
                outcome = build_auto_trading_batch_outcome((), {})
            else:
                results = engine.run_daily_trading(
                    claim.scope.trade_date, account_ids=list(claim.scope.account_ids)
                )
                outcome = build_auto_trading_batch_outcome_from_engine_results(
                    claim.scope.account_ids, results
                )
        except Exception:
            logger.exception("自动交易执行结果不确定；保留已开始记录，不重新进入引擎")
            outcome = build_indeterminate_auto_trading_batch(
                claim.scope.account_ids, code="EXECUTION_OUTCOME_UNKNOWN"
            )
        try:
            self._repository.finish(
                invocation_id=claim.invocation_id,
                claim_token=claim.claim_token,
                outcome=outcome,
            )
        except Exception:
            logger.exception("自动交易结果保存不确定；保留运行阻断，不重试整批")
            issue = AutoTradingIssue(
                kind=AutoTradingIssueKind.FAILED,
                stage="invocation_result",
                code="EXECUTION_OUTCOME_UNKNOWN",
                effects_indeterminate=True,
            )
            outcome = AutoTradingBatchOutcome(
                requested_account_ids=outcome.requested_account_ids,
                accounts=tuple(
                    replace(account, issues=(*account.issues, issue))
                    for account in outcome.accounts
                ),
            )
        return AutoTradingInvocationResult(claim.invocation_id, claim.scope, outcome, False)


_repository_factory: Callable[[], AutoTradingInvocationRepository] | None = None


def register_auto_invocation_repository(
    factory: Callable[[], AutoTradingInvocationRepository],
) -> None:
    """Register composition without reading configuration, sources or the ledger."""
    global _repository_factory
    _repository_factory = factory


def get_auto_invocation_repository() -> AutoTradingInvocationRepository:
    """Resolve the registered implementation, never falling back to an unsafe run."""
    if _repository_factory is None:
        raise AutoTradingInvocationUnavailable("automatic invocation repository is not registered")
    return _repository_factory()
