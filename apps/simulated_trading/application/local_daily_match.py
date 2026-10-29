"""Application contracts for durable local daily-interval order matching."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
    LocalSimulatedFillEventReader,
    LocalSimulatedFillEventV1,
    OrderFillContext,
    validate_local_simulated_fill_event,
)
from apps.simulated_trading.domain.local_daily_simulation_policy import (
    LocalDailySimulationPolicyBinding,
)
from apps.simulated_trading.domain.local_order_matching import (
    LocalMatchObservation,
    LocalMatchOutcome,
    LocalOrderMatchResult,
)

LOCAL_DAILY_MATCH_SOURCE_NAMESPACE = "simulated-local-daily-match.v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OPERATION_KEY_MAX_LENGTH = 128
_IDENTITY_MAX_LENGTH = 512


class LocalDailyMatchEvidenceKind(StrEnum):
    """Known preserved evidence classes accepted by the local matcher."""

    PRICE_PUBLICATION = "price_publication"
    PRICE_MANIFEST = "price_manifest"
    PRICE_FACT = "price_fact"
    PRICE_RAW = "price_raw"
    PRICE_AUDIT = "price_audit"
    INSTRUMENT_SNAPSHOT = "instrument_snapshot"
    INSTRUMENT_RAW = "instrument_raw"
    INSTRUMENT_AUDIT = "instrument_audit"
    QMT_BATCH = "qmt_batch"
    LIMIT_PUBLICATION = "limit_publication"
    LIMIT_SNAPSHOT = "limit_snapshot"
    LIMIT_RAW = "limit_raw"
    CALENDAR = "calendar"


@dataclass(frozen=True, slots=True)
class LocalDailyMatchCommand:
    """Address one local match operation within an accepted simulated order."""

    account_id: int
    user_id: int
    order_idempotency_key: str
    operation_key: str
    session_date: date
    qmt_binding_id: str

    def __post_init__(self) -> None:
        """Reject malformed owner, operation, session, or source-binding identity."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("LOCAL_DAILY_MATCH_ACCOUNT_INVALID")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("LOCAL_DAILY_MATCH_USER_INVALID")
        _require_token(self.order_idempotency_key, "order_idempotency_key", 128)
        _require_token(self.operation_key, "operation_key", _OPERATION_KEY_MAX_LENGTH)
        if type(self.session_date) is not date:
            raise ValueError("LOCAL_DAILY_MATCH_SESSION_INVALID")
        _require_token(self.qmt_binding_id, "qmt_binding_id", _IDENTITY_MAX_LENGTH)
        try:
            binding_id = UUID(self.qmt_binding_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("LOCAL_DAILY_MATCH_QMT_BINDING_INVALID") from error
        if str(binding_id) != self.qmt_binding_id:
            raise ValueError("LOCAL_DAILY_MATCH_QMT_BINDING_INVALID")


@dataclass(frozen=True, slots=True)
class LocalDailyMatchSourceReference:
    """Point to one exact immutable input used to qualify a daily match."""

    kind: LocalDailyMatchEvidenceKind
    identity: str
    content_hash: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Require a known evidence kind, bare SHA-256 and aware record time."""

        if type(self.kind) is not LocalDailyMatchEvidenceKind:
            raise ValueError("LOCAL_DAILY_MATCH_EVIDENCE_KIND_INVALID")
        _require_token(self.identity, "evidence_identity", _IDENTITY_MAX_LENGTH)
        if type(self.content_hash) is not str or not _SHA256.fullmatch(self.content_hash):
            raise ValueError("LOCAL_DAILY_MATCH_EVIDENCE_HASH_INVALID")
        _require_aware_datetime(self.recorded_at, "evidence_recorded_at")


@dataclass(frozen=True, slots=True)
class QualifiedLocalDailyMatchInput:
    """Source-qualified policy and observation returned by an injected reader."""

    as_of: datetime
    policy_binding: LocalDailySimulationPolicyBinding
    observation: LocalMatchObservation
    evidence: tuple[LocalDailyMatchSourceReference, ...]

    def __post_init__(self) -> None:
        """Seal the cutoff and canonicalize the exact evidence-reference set."""

        _require_aware_datetime(self.as_of, "as_of")
        if type(self.policy_binding) is not LocalDailySimulationPolicyBinding:
            raise ValueError("LOCAL_DAILY_MATCH_POLICY_BINDING_INVALID")
        self.policy_binding.__post_init__()
        self.policy_binding.validate_at(as_of=self.as_of)
        if type(self.observation) is not LocalMatchObservation:
            raise ValueError("LOCAL_DAILY_MATCH_OBSERVATION_INVALID")
        if type(self.observation.session_date) is not date:
            raise ValueError("LOCAL_DAILY_MATCH_SESSION_INVALID")
        if self.observation.observation_id != stable_local_daily_observation_id(
            self.observation.security_id,
            self.observation.session_date,
        ):
            raise ValueError("LOCAL_DAILY_MATCH_OBSERVATION_ID_INVALID")
        if type(self.evidence) is not tuple or not self.evidence:
            raise ValueError("LOCAL_DAILY_MATCH_EVIDENCE_REQUIRED")

        by_reference: dict[tuple[str, str], LocalDailyMatchSourceReference] = {}
        for reference in self.evidence:
            if type(reference) is not LocalDailyMatchSourceReference:
                raise ValueError("LOCAL_DAILY_MATCH_EVIDENCE_INVALID")
            reference.__post_init__()
            if reference.recorded_at > self.as_of:
                raise ValueError("LOCAL_DAILY_MATCH_EVIDENCE_NOT_KNOWN_AS_OF")
            key = (reference.kind.value, reference.identity)
            prior = by_reference.get(key)
            if prior is not None:
                if prior.content_hash != reference.content_hash:
                    raise ValueError("LOCAL_DAILY_MATCH_EVIDENCE_IDENTITY_CONFLICT")
                if prior != reference:
                    raise ValueError("LOCAL_DAILY_MATCH_EVIDENCE_DUPLICATE_CONFLICT")
            by_reference[key] = reference
        canonical = tuple(by_reference[key] for key in sorted(by_reference))
        object.__setattr__(self, "evidence", canonical)


@dataclass(frozen=True, slots=True)
class LocalDailyMatchDecision:
    """Return one durable matched or known-no-match decision for an operation."""

    command: LocalDailyMatchCommand
    request_hash: str
    result: LocalOrderMatchResult
    event: LocalSimulatedFillEventV1 | None
    replayed: bool

    def __post_init__(self) -> None:
        """Keep the durable outcome, source event and exact command in agreement."""

        if type(self.command) is not LocalDailyMatchCommand:
            raise ValueError("LOCAL_DAILY_MATCH_COMMAND_INVALID")
        self.command.__post_init__()
        if type(self.request_hash) is not str or not _SHA256.fullmatch(self.request_hash):
            raise ValueError("LOCAL_DAILY_MATCH_REQUEST_HASH_INVALID")
        if self.request_hash != local_daily_match_request_hash(self.command):
            raise ValueError("LOCAL_DAILY_MATCH_REQUEST_HASH_MISMATCH")
        if type(self.result) is not LocalOrderMatchResult:
            raise ValueError("LOCAL_DAILY_MATCH_RESULT_INVALID")
        self.result.__post_init__()
        if self.result.outcome is LocalMatchOutcome.BLOCKED:
            raise ValueError("LOCAL_DAILY_MATCH_BLOCKED_RESULT_NOT_PERSISTABLE")
        if type(self.replayed) is not bool:
            raise ValueError("LOCAL_DAILY_MATCH_REPLAY_FLAG_INVALID")
        if self.result.outcome is LocalMatchOutcome.NO_MATCH:
            if self.event is not None:
                raise ValueError("LOCAL_DAILY_MATCH_NO_MATCH_HAS_EVENT")
            return
        if type(self.event) is not LocalSimulatedFillEventV1:
            raise ValueError("LOCAL_DAILY_MATCH_MATCHED_EVENT_REQUIRED")
        checked_event = validate_local_simulated_fill_event(self.event)
        if (
            checked_event.source_namespace != LOCAL_DAILY_MATCH_SOURCE_NAMESPACE
            or checked_event.source_version != LOCAL_DAILY_INTERVAL_SOURCE_VERSION
            or checked_event.source_event_id != self.command.operation_key
            or checked_event.account_id != self.command.account_id
            or checked_event.user_id != self.command.user_id
            or checked_event.order_idempotency_key != self.command.order_idempotency_key
            or checked_event.observation_basis != "daily_interval_end"
            or checked_event.quantity != self.result.matched_quantity
            or checked_event.price != self.result.matched_price
        ):
            raise ValueError("LOCAL_DAILY_MATCH_EVENT_BINDING_INVALID")


@dataclass(frozen=True, slots=True)
class LocalDailyMatchDecisionPage:
    """One owner-scoped read page; page exhaustion is not a capacity assertion."""

    items: tuple[LocalDailyMatchDecision, ...]
    has_more: bool
    next_cursor: int | None

    def __post_init__(self) -> None:
        """Require exact decisions and a usable continuation for a nonfinal page."""

        if type(self.items) is not tuple or any(
            type(item) is not LocalDailyMatchDecision for item in self.items
        ):
            raise ValueError("LOCAL_DAILY_MATCH_PAGE_ITEMS_INVALID")
        for item in self.items:
            item.__post_init__()
        if type(self.has_more) is not bool:
            raise ValueError("LOCAL_DAILY_MATCH_PAGE_FLAG_INVALID")
        if self.next_cursor is not None and (
            type(self.next_cursor) is not int or self.next_cursor <= 0
        ):
            raise ValueError("LOCAL_DAILY_MATCH_PAGE_CURSOR_INVALID")
        if self.has_more and (not self.items or self.next_cursor is None):
            raise ValueError("LOCAL_DAILY_MATCH_PAGE_CONTINUATION_INVALID")
        if not self.has_more and self.next_cursor is not None:
            raise ValueError("LOCAL_DAILY_MATCH_PAGE_FINAL_CURSOR_INVALID")


class LocalDailyMatchQualificationReader(Protocol):
    """Return already-retained and verified source facts for one locked order."""

    def read(
        self,
        *,
        command: LocalDailyMatchCommand,
        context: OrderFillContext,
        as_of: datetime,
    ) -> QualifiedLocalDailyMatchInput | None:
        """Return qualified inputs or no result without creating source evidence."""


class LocalDailyMatchDecisionDiscovery(LocalSimulatedFillEventReader, Protocol):
    """Discover previously recorded decisions for one exact owner/order scope."""

    def discover(
        self,
        *,
        account_id: int,
        user_id: int,
        order_idempotency_key: str,
        limit: int = 50,
        cursor: int | None,
        as_of: datetime,
    ) -> LocalDailyMatchDecisionPage:
        """Return one bounded point-in-time page; never infer missing capacity."""


class LocalDailyMatchRepository(Protocol):
    """Persist decisions under the simulated-account parent lock."""

    def find_operation(
        self,
        *,
        command: LocalDailyMatchCommand,
        request_hash: str,
    ) -> LocalDailyMatchDecision | None:
        """Read exact operation replay before resolving policy or market sources."""

    def resolve_order_context(
        self,
        *,
        command: LocalDailyMatchCommand,
    ) -> OrderFillContext | None:
        """Resolve the current owner-scoped order before qualification reads."""

    def record_decision(
        self,
        *,
        command: LocalDailyMatchCommand,
        request_hash: str,
        context: OrderFillContext,
        qualified_input: QualifiedLocalDailyMatchInput,
        as_of: datetime,
        qualification_reader: LocalDailyMatchQualificationReader,
        clock: SimulatedTradeExecutionClock,
    ) -> LocalDailyMatchDecision:
        """Re-read qualification under the account lock and append one decision."""


def stable_local_daily_observation_id(security_id: str, session_date: date) -> str:
    """Build one provider/publication-independent identity for a security session."""

    _require_token(security_id, "security_id", _IDENTITY_MAX_LENGTH)
    if type(session_date) is not date:
        raise ValueError("LOCAL_DAILY_MATCH_SESSION_INVALID")
    material = f"simulated-local-daily-observation.v1\n{security_id}\n{session_date.isoformat()}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"local-daily-observation.v1:{digest}"


def local_daily_match_request_hash(command: LocalDailyMatchCommand) -> str:
    """Hash only the immutable request locator, never today's policy or sources."""

    if type(command) is not LocalDailyMatchCommand:
        raise ValueError("LOCAL_DAILY_MATCH_COMMAND_INVALID")
    command.__post_init__()
    payload = {
        "schema": "local-daily-match-request.v1",
        "account_id": command.account_id,
        "user_id": command.user_id,
        "order_idempotency_key": command.order_idempotency_key,
        "operation_key": command.operation_key,
        "session_date": command.session_date.isoformat(),
        "qmt_binding_id": command.qmt_binding_id,
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_local_daily_match_input(
    *,
    command: LocalDailyMatchCommand,
    context: OrderFillContext,
    qualified_input: QualifiedLocalDailyMatchInput,
    as_of: datetime,
) -> None:
    """Bind qualified data to the exact owner, order, session and cutoff."""

    if type(command) is not LocalDailyMatchCommand:
        raise SimulatedTradeExecutionInputError("日线撮合请求类型无效")
    command.__post_init__()
    if type(context) is not OrderFillContext:
        raise SimulatedTradeAccountScopeUnavailable("撮合订单范围无法验证")
    if type(qualified_input) is not QualifiedLocalDailyMatchInput:
        raise SimulatedTradeExecutionBlocked(
            "日线撮合资格输入类型无效",
            code="LOCAL_DAILY_MATCH_QUALIFICATION_INVALID",
        )
    try:
        qualified_input.__post_init__()
        _require_aware_datetime(as_of, "as_of")
        context.reservation.__post_init__()
        identity = context.reservation.identity
        observation = qualified_input.observation
        if (
            context.account_id != command.account_id
            or context.owner_user_id != command.user_id
            or context.order_idempotency_key != command.order_idempotency_key
            or identity.account_id != command.account_id
            or identity.idempotency_key != command.order_idempotency_key
            or qualified_input.as_of != as_of
            or observation.security_id != identity.security_id
            or observation.session_date != command.session_date
            or observation.observation_id
            != stable_local_daily_observation_id(identity.security_id, command.session_date)
        ):
            raise ValueError("qualification differs from the requested order scope")
    except SimulatedTradeAccountScopeUnavailable:
        raise
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "日线撮合资格输入与订单范围或时点不符",
            code="LOCAL_DAILY_MATCH_QUALIFICATION_SCOPE_MISMATCH",
        ) from error


class RecordLocalDailyMatchUseCase:
    """Persist one source-qualified daily match without applying ledger effects."""

    def __init__(
        self,
        *,
        repository: LocalDailyMatchRepository,
        qualification_reader: LocalDailyMatchQualificationReader,
        clock: SimulatedTradeExecutionClock,
    ) -> None:
        """Inject durable storage, source qualification and a single aware clock."""

        self._repository = repository
        self._qualification_reader = qualification_reader
        self._clock = clock

    def execute(self, command: LocalDailyMatchCommand) -> LocalDailyMatchDecision:
        """Replay before reading sources, then persist an exact qualified decision."""

        if type(command) is not LocalDailyMatchCommand:
            raise SimulatedTradeExecutionInputError("日线撮合请求类型无效")
        command.__post_init__()
        request_hash = local_daily_match_request_hash(command)
        existing = self._repository.find_operation(
            command=command,
            request_hash=request_hash,
        )
        if existing is not None:
            checked = _validate_decision(existing, command=command, request_hash=request_hash)
            return checked if checked.replayed else replace(checked, replayed=True)

        context = self._repository.resolve_order_context(command=command)
        if context is None:
            raise SimulatedTradeAccountScopeUnavailable("指定账户下未找到可撮合的订单")
        as_of = _require_aware_datetime(self._clock.now(), "as_of")
        try:
            qualified_input = self._qualification_reader.read(
                command=command,
                context=context,
                as_of=as_of,
            )
        except SimulatedTradeExecutionBlocked:
            raise
        if qualified_input is None:
            raise SimulatedTradeExecutionBlocked(
                "当前时点无法取得完整的日线撮合资格证据",
                code="LOCAL_DAILY_MATCH_QUALIFICATION_UNAVAILABLE",
            )
        validate_local_daily_match_input(
            command=command,
            context=context,
            qualified_input=qualified_input,
            as_of=as_of,
        )
        recorded = self._repository.record_decision(
            command=command,
            request_hash=request_hash,
            context=context,
            qualified_input=qualified_input,
            as_of=as_of,
            qualification_reader=self._qualification_reader,
            clock=self._clock,
        )
        return _validate_decision(recorded, command=command, request_hash=request_hash)


def _validate_decision(
    decision: object,
    *,
    command: LocalDailyMatchCommand,
    request_hash: str,
) -> LocalDailyMatchDecision:
    """Verify exact replay/commit output before returning it to a caller."""

    if type(decision) is not LocalDailyMatchDecision:
        raise SimulatedTradeExecutionBlocked(
            "撮合仓储返回了不可验证的持久结果",
            code="LOCAL_DAILY_MATCH_RECORD_INVALID",
        )
    try:
        decision.__post_init__()
        if decision.command != command or decision.request_hash != request_hash:
            raise ValueError("repository result differs from the request")
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "撮合仓储结果与原请求无法精确核对",
            code="LOCAL_DAILY_MATCH_RECORD_INVALID",
        ) from error
    return decision


def _require_token(value: object, field_name: str, max_length: int) -> None:
    """Require bounded exact text while preserving its original representation."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > max_length
        or any(character.isspace() for character in value)
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError(f"LOCAL_DAILY_MATCH_{field_name.upper()}_INVALID")


def _require_aware_datetime(value: object, field_name: str) -> datetime:
    """Require one exact timezone-aware timestamp without replacing its clock."""

    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError(f"LOCAL_DAILY_MATCH_{field_name.upper()}_INVALID")
    try:
        if value.utcoffset() is None:
            raise ValueError(f"LOCAL_DAILY_MATCH_{field_name.upper()}_INVALID")
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(f"LOCAL_DAILY_MATCH_{field_name.upper()}_INVALID") from error
    return value


__all__ = (
    "LOCAL_DAILY_MATCH_SOURCE_NAMESPACE",
    "LocalDailyMatchCommand",
    "LocalDailyMatchDecision",
    "LocalDailyMatchDecisionPage",
    "LocalDailyMatchDecisionDiscovery",
    "LocalDailyMatchEvidenceKind",
    "LocalDailyMatchRepository",
    "LocalDailyMatchQualificationReader",
    "LocalDailyMatchSourceReference",
    "RecordLocalDailyMatchUseCase",
    "QualifiedLocalDailyMatchInput",
    "local_daily_match_request_hash",
    "stable_local_daily_observation_id",
    "validate_local_daily_match_input",
)
