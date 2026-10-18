"""Typed application contracts for preserving and reconciling broker trade facts."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol, TypeAlias

from apps.account.domain.broker_trade_reconciliation import BrokerReconciliationState

BrokerTradeAction: TypeAlias = Literal["buy", "sell"]
BrokerBaselineDecision: TypeAlias = Literal["included", "excluded", "pending"]
BrokerFactWriteDisposition: TypeAlias = Literal[
    "created",
    "identical_duplicate",
    "stable_key_conflict",
]
BrokerFactPreviewConflictCode: TypeAlias = Literal[
    "BROKER_FACT_PREVIEW_CHANGED",
    "BROKER_BALANCE_PREVIEW_CHANGED",
]
BalanceSnapshotKind: TypeAlias = Literal["legacy", "unified", "empty", "blocked"]
ValuationStatus: TypeAlias = Literal["confirmed", "unconfirmed", "unknown"]
ProjectionOutcomeKind: TypeAlias = Literal[
    "projected",
    "already_in_baseline",
    "awaiting_baseline",
    "blocked",
]
MatchingOutcomeKind: TypeAlias = Literal["matched", "manual_only", "deferred", "failed"]

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class NormalizedTradeRow:
    """Validated broker execution row shared structurally with Infrastructure."""

    row_number: int
    traded_at: datetime
    action: BrokerTradeAction
    asset_code: str
    shares: float
    price: Decimal
    commission: Decimal | None
    stamp_duty: Decimal | None
    transfer_fee: Decimal | None
    external_trade_id: str
    notes: str
    broker_trade_key: str
    raw_payload: JsonObject

    def to_preview_dict(self, *, duplicate: bool = False) -> dict[str, JsonValue]:
        """Return a JSON-safe public row without persistence-only values."""
        return {
            "row_number": self.row_number,
            "traded_at": self.traded_at.isoformat(),
            "action": self.action,
            "asset_code": self.asset_code,
            "shares": self.shares,
            "price": str(self.price),
            "commission": str(self.commission) if self.commission is not None else None,
            "stamp_duty": str(self.stamp_duty) if self.stamp_duty is not None else None,
            "transfer_fee": str(self.transfer_fee) if self.transfer_fee is not None else None,
            "external_trade_id": self.external_trade_id,
            "broker_trade_key": self.broker_trade_key,
            "duplicate": duplicate,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class BrokerTradeParseIssue:
    """One row-level validation issue emitted at the Infrastructure boundary."""

    row_number: int
    error_code: str
    message: str


@dataclass(frozen=True, slots=True)
class BrokerTradeParseResult:
    """Normalized rows and typed row issues returned by the broker parser."""

    rows: tuple[NormalizedTradeRow, ...]
    errors: tuple[BrokerTradeParseIssue, ...]


class BrokerTradeFactParser(Protocol):
    """Parse external broker bytes into validated, JSON-safe fact rows."""

    def parse_normalized_facts(
        self,
        *,
        content: bytes,
        filename: str,
        broker_name: str,
        portfolio_id: int,
    ) -> BrokerTradeParseResult:
        """Normalize inputs before they cross into Application orchestration."""
        ...


@dataclass(frozen=True, slots=True)
class BrokerFactCandidate:
    """One fact and immutable source evidence for a possibly absent batch summary."""

    owner_user_id: int
    portfolio_id: int
    first_import_batch_id: int | None
    source_file_sha256: str
    source_filename: str
    broker_name: str
    source_row: NormalizedTradeRow


@dataclass(frozen=True, slots=True)
class BaselineRequest:
    """One explicit batch choice; pending needs no preview or balance read."""

    decision: BrokerBaselineDecision = "pending"
    baseline_as_of: datetime | None = None
    expected_fact_set_fingerprint: str | None = None
    expected_balance_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class BaselineDeclarationView:
    """Typed, already-validated view of one persisted baseline decision."""

    decision: BrokerBaselineDecision
    actor_user_id: int
    declared_at: datetime
    expected_fact_set_fingerprint: str | None
    expected_balance_fingerprint: str | None
    baseline_as_of: datetime | None


@dataclass(frozen=True, slots=True)
class ProjectionAttemptView:
    """Typed view of a fact's latest projection attempt."""

    attempted_at: datetime
    outcome: ProjectionOutcomeKind
    reason_code: str | None
    account_id: int | None
    unified_position_id: int | None
    legacy_position_id: int | None
    resulting_balance_fingerprint: str | None


@dataclass(frozen=True, slots=True)
class MatchingAttemptView:
    """Typed view of recommendation matching persisted beside a broker fact."""

    attempted_at: datetime
    outcome: MatchingOutcomeKind
    link_id: int | None
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class BrokerReconciliationView:
    """Typed reconciliation data parsed from persistence before Application use."""

    state: BrokerReconciliationState
    baseline: BaselineDeclarationView | None
    last_projection: ProjectionAttemptView | None
    last_reason_code: str | None


@dataclass(frozen=True, slots=True)
class BrokerFactRecord:
    """Immutable persisted execution fact with source and reconciliation provenance."""

    transaction_id: int
    owner_user_id: int
    portfolio_id: int
    position_id: int | None
    action: BrokerTradeAction
    asset_code: str
    shares: float
    price: Decimal
    notional: Decimal
    commission: Decimal
    commission_known: bool | None
    slippage: Decimal
    slippage_known: bool | None
    stamp_duty: Decimal
    stamp_duty_known: bool | None
    transfer_fee: Decimal
    transfer_fee_known: bool | None
    broker_name: str
    external_trade_id: str
    broker_trade_key: str | None
    first_import_batch_id: int | None
    raw_payload: JsonObject
    notes: str
    traded_at: datetime
    created_at: datetime
    reconciliation: BrokerReconciliationView
    matching_attempt: MatchingAttemptView | None


@dataclass(frozen=True, slots=True)
class BrokerFactWriteResult:
    """Result of key-based fact persistence without mutation of an existing row."""

    disposition: BrokerFactWriteDisposition
    record: BrokerFactRecord | None
    conflict_reason_code: str | None


@dataclass(frozen=True, slots=True)
class BalanceSnapshot:
    """Owner-scoped local balance snapshot; unknown quantities remain None."""

    owner_user_id: int
    portfolio_id: int
    account_id: int | None
    account_mapping_id: int | None
    asset_code: str
    kind: BalanceSnapshotKind
    unified_position_id: int | None
    legacy_position_id: int | None
    total_shares: float | None
    available_quantity: float | None
    available_quantity_known: bool | None
    average_cost: Decimal | None
    reference_mark: Decimal | None
    reference_mark_as_of: datetime | None
    valuation_status: ValuationStatus
    source_updated_at: datetime | None
    observed_at: datetime
    fingerprint: str
    blocked_reason_code: str | None


@dataclass(frozen=True, slots=True)
class BrokerBalanceSnapshotSummary:
    """Public balance preview fields, excluding internal IDs and CAS hashes."""

    asset_code: str
    kind: BalanceSnapshotKind
    total_shares: float | None
    available_quantity: float | None
    available_quantity_known: bool | None
    average_cost: Decimal | None
    reference_mark: Decimal | None
    reference_mark_as_of: datetime | None
    valuation_status: ValuationStatus
    source_updated_at: datetime | None
    observed_at: datetime
    blocked_reason_code: str | None


@dataclass(frozen=True, slots=True)
class BrokerBalancePreview:
    """Exact owner/portfolio preview scope and its local balance CAS fingerprint."""

    owner_user_id: int
    portfolio_id: int
    snapshots: tuple[BalanceSnapshot, ...]
    expected_balance_fingerprint: str


@dataclass(frozen=True, slots=True)
class BrokerImportPreviewContext:
    """Private machine context binding source bytes, facts, and local balances."""

    owner_user_id: int
    portfolio_id: int
    source_file_sha256: str
    expected_fact_set_fingerprint: str | None
    expected_balance_fingerprint: str | None
    snapshots: tuple[BalanceSnapshot, ...]
    new_fact_rows: int
    retryable_existing_rows: int
    terminal_duplicate_rows: int


@dataclass(frozen=True, slots=True)
class BrokerFactProjectionResult:
    """Outcome for one fact after a reconciliation attempt."""

    transaction_id: int
    state: BrokerReconciliationState
    outcome: ProjectionOutcomeKind
    reason_code: str | None
    resulting_balance_fingerprint: str | None


@dataclass(frozen=True, slots=True)
class BrokerFactSetReconciliationResult:
    """Per-fact result and stable conflict code for one declared fact set."""

    decision: BrokerBaselineDecision
    expected_fact_set_fingerprint: str | None
    expected_balance_fingerprint: str | None
    facts: tuple[BrokerFactProjectionResult, ...]
    conflict_code: BrokerFactPreviewConflictCode | None = None


@dataclass(frozen=True, slots=True)
class BrokerExecutionMatchResult:
    """Narrowed matcher result; matcher success never owns the broker fact."""

    outcome: MatchingOutcomeKind
    link_id: int | None
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class PendingBrokerFactQuery:
    """Owner-scoped query for unresolved persisted facts."""

    owner_user_id: int
    portfolio_id: int | None
    limit: int


class BrokerTradeReconciliationRepository(Protocol):
    """Persistence boundary for broker facts, snapshots, matching, and pending reads."""

    def capture_balance_preview(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        asset_codes: tuple[str, ...],
    ) -> BrokerBalancePreview:
        """Read owner-scoped balances without writing or creating accounts."""
        ...

    def persist_fact_first(self, candidate: BrokerFactCandidate) -> BrokerFactWriteResult:
        """Save one fact in its own atomic operation before optional work.

        This method does not claim a commit boundary across an enclosing caller
        transaction. A new row starts in awaiting-baseline state. Key reuse compares
        immutable source/economic fields and never replaces the original raw payload,
        source-file provenance, or first batch.
        """
        ...

    def get_fact_by_stable_key(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        broker_trade_key: str,
    ) -> BrokerFactRecord | None:
        """Return one owner-scoped fact by stable broker key."""
        ...

    def get_existing_real_account_id(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
    ) -> int | None:
        """Read an existing exact real-account mapping without creating one."""
        ...

    def reconcile_fact_set(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        decision_batch_id: int | None,
        transaction_ids: tuple[int, ...],
        source_file_sha256: str,
        request: BaselineRequest,
    ) -> BrokerFactSetReconciliationResult:
        """Recheck exact source/fact/balance CAS and persist reconciliation atomically.

        A pending request needs no preview and does not inspect a market provider.
        Included and excluded requests require both preview fingerprints. Legacy
        unverified facts may only be explicitly confirmed included. Excluded sells
        bypass simulated-order available gates and preserve unknown sellability.
        """
        ...

    def persist_matching_result(
        self,
        *,
        transaction_id: int,
        result: BrokerExecutionMatchResult,
    ) -> BrokerFactRecord:
        """Persist one matching outcome without changing the source fact."""
        ...

    def matching_attempt_scope(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        transaction_id: int,
    ) -> AbstractContextManager[BrokerFactRecord]:
        """Lock one persisted fact in a nested atomic scope for matcher writes.

        Matcher-side database errors must escape this context so Infrastructure can
        roll back its savepoint before Application persists a retryable failed outcome.
        Successful link creation and matching status persistence share this scope.
        """
        ...

    def list_pending_facts(
        self,
        query: PendingBrokerFactQuery,
    ) -> tuple[BrokerFactRecord, ...]:
        """Read pending facts directly from transaction reconciliation states."""
        ...


class BrokerExecutionMatcher(Protocol):
    """Compatibility shape of the recommendation matcher at its mapping boundary."""

    def record_imported_execution(
        self,
        *,
        account_id: str,
        transaction_id: int,
        security_code: str,
        actual_action: str,
        traded_at: datetime,
    ) -> Mapping[str, object]:
        """Return a matcher mapping that Application must narrow before use."""
        ...
