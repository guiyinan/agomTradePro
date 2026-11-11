"""Atomic, account-first-locked persistence for corporate-action stages."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import NoReturn, TypeAlias
from zoneinfo import ZoneInfo

from django.db import DEFAULT_DB_ALIAS, transaction
from django.db.models import Max
from django.utils import timezone

from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
    CorporateActionPostingConflictError,
    CorporateActionPostingReceipt,
    CorporateActionPostingRepositoryProtocol,
    CorporateActionSourceQualificationVerifierProtocol,
    CorporateActionTaxBasisVerifierProtocol,
    HistoricalAccountOwnershipVerifierProtocol,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionLedgerDelta,
    CorporateActionStage,
    CorporateActionStageRequest,
    calculate_corporate_action_delta,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.order_reservation_guard import (
    lock_active_order_reservations,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
)

_ZERO_MONEY = Decimal("0.00")
_ZERO_SHARES = Decimal("0.000000")
_SHARE_QUANTUM = Decimal("0.0001")
_SZSE_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class _PlannedEntry:
    """One validated request, its persisted predecessor, and signed effect."""

    request: CorporateActionStageRequest
    reverses: CorporateActionPostingModel | None
    delta: CorporateActionLedgerDelta


_EntryRows: TypeAlias = list[CorporateActionPostingModel]


def _conflict(message: str, code: str = "CORPORATE_ACTION_REVISION_CONFLICT") -> NoReturn:
    """Raise a stable conflict for replay, predecessor, or ledger-state failures."""

    raise CorporateActionPostingConflictError(message, code=code)


def _blocked(message: str, code: str = "CORPORATE_ACTION_POSTING_BLOCKED") -> NoReturn:
    """Raise a stable business block for unavailable or unsafe ledger state."""

    raise CorporateActionPostingBlockedError(message, code=code)


def _signed_delta(value: Decimal) -> Decimal:
    """Return the exact inverse of one previously persisted decimal delta."""

    return -value


def _delta_for_reversal(
    row: CorporateActionPostingModel,
) -> CorporateActionLedgerDelta:
    """Construct the exact inverse from the immutable predecessor row."""

    return CorporateActionLedgerDelta(
        cash=_signed_delta(row.cash_delta),
        cash_receivable=_signed_delta(row.cash_receivable_delta),
        shares=_signed_delta(row.share_delta),
        share_receivable=_signed_delta(row.share_receivable_delta),
        available_shares=_signed_delta(row.available_share_delta),
    )


def _economic(row: CorporateActionPostingModel) -> bool:
    """Return whether an entry has an accounting effect."""

    return any(
        value != 0
        for value in (
            row.cash_delta,
            row.cash_receivable_delta,
            row.share_delta,
            row.share_receivable_delta,
            row.available_share_delta,
        )
    )


def _same_event_identity(
    request: CorporateActionStageRequest,
    rows: _EntryRows,
) -> bool:
    """Check immutable source-event and asset identity across stored revisions."""

    return all(
        row.source_namespace == request.source_namespace
        and row.source_record_id == request.source_record_id
        and row.source_event_id == request.source_event_id
        and row.action_kind == request.action_kind.value
        and row.asset_code == request.asset_code
        and row.security_id == request.security_id
        and row.account_id == request.account_id
        for row in rows
    )


def _effective_entries(rows: _EntryRows) -> _EntryRows:
    """Return economic rows that have not already been reversed."""

    reversed_ids = {
        row.reversal_of_id
        for row in rows
        if row.entry_kind == CorporateActionEntryKind.REVERSAL.value
        and row.reversal_of_id is not None
    }
    return [
        row
        for row in rows
        if row.entry_kind
        in {
            CorporateActionEntryKind.POSTING.value,
            CorporateActionEntryKind.SUCCESSOR.value,
        }
        and row.pk not in reversed_ids
        and _economic(row)
    ]


def _entry_effective_order(entry: _PlannedEntry) -> tuple[int, int]:
    """Order corrections so dependent stages unwind before their predecessors."""

    request = entry.request
    if request.entry_kind is CorporateActionEntryKind.REVERSAL:
        reverse_order: dict[CorporateActionStage, int] = {
            CorporateActionStage.TAX_WITHHOLDING: 0,
            CorporateActionStage.CASH_PAYMENT: 1,
            CorporateActionStage.CASH_ENTITLEMENT: 2,
            CorporateActionStage.SHARE_SELLABLE_RELEASE: 0,
            CorporateActionStage.SHARE_DELIVERY: 1,
            CorporateActionStage.SHARE_ENTITLEMENT: 2,
            CorporateActionStage.RIGHTS_NOT_EXERCISED: 3,
        }
        return (0, reverse_order[request.stage])
    successor_order: dict[CorporateActionStage, int] = {
        CorporateActionStage.CASH_ENTITLEMENT: 0,
        CorporateActionStage.SHARE_ENTITLEMENT: 0,
        CorporateActionStage.CASH_PAYMENT: 1,
        CorporateActionStage.SHARE_DELIVERY: 1,
        CorporateActionStage.TAX_WITHHOLDING: 2,
        CorporateActionStage.SHARE_SELLABLE_RELEASE: 3,
        CorporateActionStage.RIGHTS_NOT_EXERCISED: 4,
    }
    return (1, successor_order[request.stage])


class DjangoCorporateActionPostingRepository(CorporateActionPostingRepositoryProtocol):
    """Append explicit corporate-action revisions under the account serialization fence."""

    def __init__(
        self,
        *,
        source_qualifier: CorporateActionSourceQualificationVerifierProtocol | None = None,
        ownership_verifier: HistoricalAccountOwnershipVerifierProtocol | None = None,
        tax_basis_verifier: CorporateActionTaxBasisVerifierProtocol | None = None,
        using: str = DEFAULT_DB_ALIAS,
    ) -> None:
        self._source_qualifier = source_qualifier
        self._ownership_verifier = ownership_verifier
        self._tax_basis_verifier = tax_basis_verifier
        self._using = using

    @property
    def database_alias(self) -> str:
        """Return the alias used for account locks and stage persistence."""

        return self._using

    def post_revision(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Lock the account first, validate the revision, and append all its stages."""

        if type(requests) is not tuple or not requests:
            _blocked("corporate-action revision must contain at least one stage")
        for request in requests:
            request.__post_init__()
        first = requests[0]
        self._validate_batch_identity(requests, first)

        with transaction.atomic(using=self._using):
            account = (
                SimulatedAccountModel._base_manager.using(self._using)
                .select_for_update()
                .filter(
                    pk=first.account_id,
                    user_id=first.owner_user_id,
                    account_type="simulated",
                    is_active=True,
                )
                .first()
            )
            if account is None:
                _blocked(
                    "corporate action requires the active simulated account owner",
                    "CORPORATE_ACTION_ACCOUNT_SCOPE_INVALID",
                )
            if not account.cash_known or account.cash_reconciliation_status != "simulated_ledger":
                _blocked(
                    "corporate action requires a known simulated cash ledger",
                    "CORPORATE_ACTION_CASH_STATE_UNKNOWN",
                )

            event_rows = list(
                CorporateActionPostingModel._base_manager.using(self._using)
                .select_for_update()
                .filter(account_id=first.account_id, source_event_id=first.source_event_id)
                .order_by("account_revision")
            )
            if event_rows and not _same_event_identity(first, event_rows):
                _conflict(
                    "source event identity was already bound to another account asset",
                    "CORPORATE_ACTION_EVENT_IDENTITY_CONFLICT",
                )

            replay = self._resolve_exact_replay(requests, event_rows)
            if replay is not None:
                return replay

            self._verify_qualified_inputs(requests)

            self._validate_revision_transition(requests, event_rows)
            try:
                lock_active_order_reservations(
                    account_id=first.account_id,
                    using=self._using,
                )
            except SimulatedTradeExecutionBlocked as error:
                raise CorporateActionPostingBlockedError(
                    "an active simulated order reserves cash or sellable shares",
                    code="CORPORATE_ACTION_ACTIVE_RESERVATION",
                ) from error
            planned = self._plan_entries(requests, event_rows)
            account_revision = (
                CorporateActionPostingModel._base_manager.using(self._using)
                .filter(account_id=first.account_id)
                .aggregate(latest=Max("account_revision"))["latest"]
                or 0
            )
            current_cash = account.current_cash

            cash_changed = False
            created_by_stage: dict[str, CorporateActionPostingModel] = {}

            position = self._lock_position_if_needed(first, planned)
            event_cash_receivable = sum(
                (row.cash_receivable_delta for row in event_rows), _ZERO_MONEY
            )
            event_share_receivable = sum(
                (row.share_receivable_delta for row in event_rows), _ZERO_SHARES
            )
            event_cash_paid = sum(
                (
                    row.cash_delta
                    for row in event_rows
                    if row.stage == CorporateActionStage.CASH_PAYMENT.value
                ),
                _ZERO_MONEY,
            )
            event_tax_withheld = -sum(
                (
                    row.cash_delta
                    for row in event_rows
                    if row.stage == CorporateActionStage.TAX_WITHHOLDING.value
                ),
                _ZERO_MONEY,
            )
            event_shares_delivered = sum(
                (
                    row.share_delta
                    for row in event_rows
                    if row.stage == CorporateActionStage.SHARE_DELIVERY.value
                ),
                _ZERO_SHARES,
            )
            event_shares_released = sum(
                (
                    row.available_share_delta
                    for row in event_rows
                    if row.stage == CorporateActionStage.SHARE_SELLABLE_RELEASE.value
                ),
                _ZERO_SHARES,
            )

            for entry in sorted(planned, key=_entry_effective_order):
                request = entry.request
                delta = entry.delta
                if request.stage is CorporateActionStage.CASH_PAYMENT:
                    if request.entry_kind is not CorporateActionEntryKind.REVERSAL:
                        server_now = timezone.now()
                        if not timezone.is_aware(server_now):
                            _blocked(
                                "server clock is not timezone-aware for cash settlement",
                                "CORPORATE_ACTION_SERVER_CLOCK_INVALID",
                            )
                        if (
                            request.payment_date is None
                            or server_now.astimezone(_SZSE_TIMEZONE).date() < request.payment_date
                        ):
                            _blocked(
                                "the SZSE announced payment date has not been reached",
                                "CORPORATE_ACTION_PAYMENT_DATE_NOT_REACHED",
                            )
                        if event_cash_receivable != -delta.cash_receivable:
                            _blocked(
                                "cash payment must settle the full outstanding event receivable",
                                "CORPORATE_ACTION_RECEIVABLE_NOT_FULLY_SETTLED",
                            )
                    if event_cash_receivable < -delta.cash_receivable:
                        _blocked(
                            "cash payment exceeds this event's posted entitlement",
                            "CORPORATE_ACTION_RECEIVABLE_INSUFFICIENT",
                        )
                if request.stage is CorporateActionStage.TAX_WITHHOLDING:
                    if event_cash_paid - event_tax_withheld < -delta.cash:
                        _blocked(
                            "withholding exceeds the event's paid gross proceeds",
                            "CORPORATE_ACTION_TAX_BASIS_INSUFFICIENT",
                        )
                if request.stage is CorporateActionStage.SHARE_DELIVERY:
                    if event_share_receivable < -delta.share_receivable:
                        _blocked(
                            "share delivery exceeds this event's posted entitlement",
                            "CORPORATE_ACTION_SHARE_RECEIVABLE_INSUFFICIENT",
                        )
                if request.stage is CorporateActionStage.SHARE_SELLABLE_RELEASE:
                    if event_shares_delivered - event_shares_released < delta.available_shares:
                        _blocked(
                            "sellable release exceeds this event's delivered shares",
                            "CORPORATE_ACTION_SELLABLE_INSUFFICIENT",
                        )

                current_cash += delta.cash
                if current_cash < 0:
                    _blocked(
                        "corporate-action cash debit would make the ledger negative",
                        "CORPORATE_ACTION_CASH_INSUFFICIENT",
                    )
                event_cash_receivable += delta.cash_receivable
                event_share_receivable += delta.share_receivable
                if event_cash_receivable < 0 or event_share_receivable < 0:
                    _blocked(
                        "corporate-action correction would create a negative receivable",
                        "CORPORATE_ACTION_RECEIVABLE_NEGATIVE",
                    )
                event_cash_paid += (
                    delta.cash
                    if request.stage is CorporateActionStage.CASH_PAYMENT
                    else _ZERO_MONEY
                )
                event_tax_withheld -= (
                    delta.cash
                    if request.stage is CorporateActionStage.TAX_WITHHOLDING
                    else _ZERO_MONEY
                )
                event_shares_delivered += (
                    delta.shares
                    if request.stage is CorporateActionStage.SHARE_DELIVERY
                    else _ZERO_SHARES
                )
                event_shares_released += delta.available_shares

                if position is not None and (delta.shares != 0 or delta.available_shares != 0):
                    self._apply_position_delta(position, delta)

                account_revision += 1
                row = self._make_row(
                    request=request,
                    account=account,
                    account_revision=account_revision,
                    delta=delta,
                    reverses=entry.reverses,
                )
                row.save(using=self._using)
                event_rows.append(row)
                created_by_stage[request.stage_key] = row
                cash_changed = cash_changed or delta.cash != 0
                # The legacy account summary has no separately typed receivable
                # field and no trusted unadjusted-price valuation contract.
                # Keep its total_value untouched to avoid dividend double-counting.

            if cash_changed:
                account.current_cash = current_cash
                account.save(using=self._using, update_fields=("current_cash", "updated_at"))
            return tuple(
                CorporateActionPostingReceipt(
                    entry_id=created_by_stage[request.stage_key].pk,
                    account_revision=created_by_stage[request.stage_key].account_revision,
                    stage_key=created_by_stage[request.stage_key].stage_key,
                    request_payload_sha256=created_by_stage[
                        request.stage_key
                    ].request_payload_sha256,
                    replayed=False,
                )
                for request in requests
            )

    @staticmethod
    def _validate_batch_identity(
        requests: tuple[CorporateActionStageRequest, ...],
        first: CorporateActionStageRequest,
    ) -> None:
        """Require one account, source event, and exact source revision per atomic batch."""

        common_values = (
            "account_id",
            "owner_user_id",
            "security_id",
            "asset_code",
            "asset_name",
            "source_namespace",
            "source_record_id",
            "source_event_id",
            "source_revision_id",
            "source_payload_sha256",
            "qualification_sha256",
            "qualifier_identity",
            "source_observed_at",
            "qualified_at",
            "posted_at",
            "action_kind",
        )
        stage_keys: set[str] = set()
        for request in requests:
            if any(getattr(request, field) != getattr(first, field) for field in common_values):
                _blocked(
                    "all stages in one revision must share exact source and account identity",
                    "CORPORATE_ACTION_BATCH_IDENTITY_INVALID",
                )
            if request.stage_key in stage_keys:
                _conflict(
                    "one atomic revision contains a duplicate stage identity",
                    "CORPORATE_ACTION_DUPLICATE_STAGE",
                )
            stage_keys.add(request.stage_key)

    def _resolve_exact_replay(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
        event_rows: _EntryRows,
    ) -> tuple[CorporateActionPostingReceipt, ...] | None:
        """Return exact idempotent receipts or reject a reused identity."""

        if not event_rows:
            return None
        first = requests[0]
        rows_by_key = {
            row.stage_key: row
            for row in event_rows
            if row.source_revision_id == first.source_revision_id
        }
        found = [rows_by_key.get(request.stage_key) for request in requests]
        if not any(row is not None for row in found):
            return None
        if not all(row is not None for row in found):
            _conflict(
                "a revision replay must match the entire previously inserted batch",
                "CORPORATE_ACTION_REVISION_REPLAY_CONFLICT",
            )
        receipts: list[CorporateActionPostingReceipt] = []
        for request, row in zip(requests, found, strict=True):
            if row is None or row.request_payload_sha256 != request.payload_sha256:
                _conflict(
                    "event/revision/stage identity was replayed with different payload",
                    "CORPORATE_ACTION_IDEMPOTENCY_CONFLICT",
                )
            receipts.append(
                CorporateActionPostingReceipt(
                    entry_id=row.pk,
                    account_revision=row.account_revision,
                    stage_key=row.stage_key,
                    request_payload_sha256=row.request_payload_sha256,
                    replayed=True,
                )
            )
        return tuple(receipts)

    def _verify_qualified_inputs(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
    ) -> None:
        """Fail closed until local source and historical-state verifiers are wired."""

        if self._source_qualifier is None:
            _blocked(
                "official corporate-action source qualification is not configured",
                "CORPORATE_ACTION_SOURCE_VERIFIER_UNAVAILABLE",
            )
        for request in requests:
            if self._source_qualifier.verify_source(request) is not True:
                _blocked(
                    "corporate-action source or terms did not pass qualification",
                    "CORPORATE_ACTION_SOURCE_UNQUALIFIED",
                )
            needs_ownership = (
                request.stage
                in {
                    CorporateActionStage.CASH_ENTITLEMENT,
                    CorporateActionStage.SHARE_ENTITLEMENT,
                    CorporateActionStage.RIGHTS_NOT_EXERCISED,
                }
                and request.entry_kind is not CorporateActionEntryKind.REVERSAL
            )
            if needs_ownership:
                if self._ownership_verifier is None:
                    _blocked(
                        "record-date account ownership verification is not configured",
                        "CORPORATE_ACTION_OWNERSHIP_VERIFIER_UNAVAILABLE",
                    )
                if self._ownership_verifier.verify_ownership(request) is not True:
                    _blocked(
                        "record-date ownership does not match the simulated account",
                        "CORPORATE_ACTION_HISTORICAL_OWNERSHIP_UNKNOWN",
                    )
            if request.stage is CorporateActionStage.TAX_WITHHOLDING:
                if self._tax_basis_verifier is None:
                    _blocked(
                        "deferred tax-basis verification is not configured",
                        "CORPORATE_ACTION_TAX_VERIFIER_UNAVAILABLE",
                    )
                if self._tax_basis_verifier.verify_tax_basis(request) is not True:
                    _blocked(
                        "withholding amount does not match qualified tax-basis evidence",
                        "CORPORATE_ACTION_TAX_BASIS_INVALID",
                    )

    @staticmethod
    def _validate_revision_transition(
        requests: tuple[CorporateActionStageRequest, ...],
        event_rows: _EntryRows,
    ) -> None:
        """Validate stable source-version lineage without inventing ordinal versions."""

        first = requests[0]
        versions = {row.source_revision_id for row in event_rows}
        superseded_versions = {
            row.supersedes_revision_id
            for row in event_rows
            if row.supersedes_revision_id is not None
        }
        current_heads = versions - superseded_versions
        if not event_rows:
            if (
                first.entry_kind
                not in {
                    CorporateActionEntryKind.POSTING,
                    CorporateActionEntryKind.NO_EFFECT,
                }
                or first.supersedes_revision_id is not None
            ):
                _conflict(
                    "the first observed source version cannot be a correction successor",
                    "CORPORATE_ACTION_REVISION_CONFLICT",
                )
            return
        if len(current_heads) != 1:
            _conflict(
                "event history does not have exactly one unsuperseded source version",
                "CORPORATE_ACTION_REVISION_LINEAGE_INVALID",
            )
        current_head = next(iter(current_heads))
        if first.source_revision_id == current_head:
            if any(
                request.entry_kind
                not in {
                    CorporateActionEntryKind.POSTING,
                    CorporateActionEntryKind.NO_EFFECT,
                }
                or request.supersedes_revision_id is not None
                for request in requests
            ):
                _conflict(
                    "stages on the current source version cannot claim a correction predecessor",
                    "CORPORATE_ACTION_REVISION_CONFLICT",
                )
            return
        if (
            first.source_revision_id in versions
            or first.supersedes_revision_id != current_head
            or any(
                request.entry_kind
                not in {
                    CorporateActionEntryKind.REVERSAL,
                    CorporateActionEntryKind.SUCCESSOR,
                }
                for request in requests
            )
        ):
            _conflict(
                "correction must link a new stable source revision to the current head",
                "CORPORATE_ACTION_REVISION_CONFLICT",
            )

        active = _effective_entries(event_rows)
        required_reversals = {row.pk for row in active}
        supplied_reversals = {
            request.reversal_of_entry_id
            for request in requests
            if request.entry_kind is CorporateActionEntryKind.REVERSAL
        }
        if supplied_reversals != required_reversals:
            _conflict(
                "correction revision must reverse every current economic stage exactly once",
                "CORPORATE_ACTION_REVERSAL_SET_INCOMPLETE",
            )
        if not active:
            _conflict(
                "a no-effect source event has no economic predecessor to correct",
                "CORPORATE_ACTION_REVISION_NO_EFFECT",
            )
        if not any(
            request.entry_kind is CorporateActionEntryKind.SUCCESSOR for request in requests
        ):
            _conflict(
                "a correction must include at least one explicit successor stage",
                "CORPORATE_ACTION_SUCCESSOR_MISSING",
            )

    def _plan_entries(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
        event_rows: _EntryRows,
    ) -> list[_PlannedEntry]:
        """Resolve reversal targets and calculate exact immutable stage effects."""

        rows_by_id = {row.pk: row for row in event_rows}
        planned: list[_PlannedEntry] = []
        for request in requests:
            target: CorporateActionPostingModel | None = None
            if request.entry_kind is CorporateActionEntryKind.REVERSAL:
                target = rows_by_id.get(request.reversal_of_entry_id or 0)
                if (
                    target is None
                    or target.account_id != request.account_id
                    or target.source_event_id != request.source_event_id
                    or target.source_revision_id != request.supersedes_revision_id
                    or target.entry_kind
                    not in {
                        CorporateActionEntryKind.POSTING.value,
                        CorporateActionEntryKind.SUCCESSOR.value,
                    }
                    or target.stage != request.stage.value
                    or target.action_kind != request.action_kind.value
                    or not _economic(target)
                ):
                    _conflict(
                        "reversal target is outside the immediate event predecessor",
                        "CORPORATE_ACTION_REVERSAL_TARGET_INVALID",
                    )
                if target.reversal_entries.exists():
                    _conflict(
                        "an economic stage already has a retained reversal",
                        "CORPORATE_ACTION_REVERSAL_DUPLICATE",
                    )
                delta = _delta_for_reversal(target)
            else:
                delta = calculate_corporate_action_delta(request)
            planned.append(_PlannedEntry(request=request, reverses=target, delta=delta))
        return planned

    def _lock_position_if_needed(
        self,
        request: CorporateActionStageRequest,
        planned: list[_PlannedEntry],
    ) -> PositionModel | None:
        """Lock the existing cost-basis owner only when shares are actually changed."""

        if not any(
            entry.delta.shares != 0 or entry.delta.available_shares != 0 for entry in planned
        ):
            return None
        position = (
            PositionModel._base_manager.using(self._using)
            .select_for_update()
            .filter(account_id=request.account_id, asset_code=request.asset_code)
            .first()
        )
        if position is None:
            _blocked(
                "share delivery requires an existing owned position with cost basis",
                "CORPORATE_ACTION_POSITION_MISSING",
            )
        if (
            position.asset_type != "equity"
            or position.cost_basis_known is not True
            or position.available_quantity_known is not True
        ):
            _blocked(
                "share delivery requires known equity cost basis and sellable quantity",
                "CORPORATE_ACTION_POSITION_STATE_UNKNOWN",
            )
        return position

    @staticmethod
    def _apply_position_delta(
        position: PositionModel,
        delta: CorporateActionLedgerDelta,
    ) -> None:
        """Apply share quantity without changing price or market-value fields."""

        new_quantity = position.quantity + delta.shares
        new_available = position.available_quantity + delta.available_shares
        if new_quantity < 0 or new_available < 0 or new_available > new_quantity:
            _blocked(
                "corporate-action shares would invalidate held or sellable quantity",
                "CORPORATE_ACTION_POSITION_QUANTITY_INVALID",
            )
        if delta.shares != 0:
            if new_quantity == 0:
                if position.total_cost != 0:
                    _blocked(
                        "cannot remove the final shares while positive cost basis remains",
                        "CORPORATE_ACTION_POSITION_BASIS_INVALID",
                    )
                position.avg_cost = Decimal("0.0000")
            else:
                position.avg_cost = (position.total_cost / new_quantity).quantize(
                    _SHARE_QUANTUM,
                    rounding=ROUND_HALF_EVEN,
                )
            position.quantity = new_quantity
            position.valuation_known = False
        if delta.available_shares != 0:
            position.available_quantity = new_available
        position.save(
            update_fields=(
                "quantity",
                "available_quantity",
                "avg_cost",
                "valuation_known",
                "updated_at",
            )
        )

    @staticmethod
    def _make_row(
        *,
        request: CorporateActionStageRequest,
        account: SimulatedAccountModel,
        account_revision: int,
        delta: CorporateActionLedgerDelta,
        reverses: CorporateActionPostingModel | None,
    ) -> CorporateActionPostingModel:
        """Map validated Domain facts and signed effects to the immutable ORM row."""

        return CorporateActionPostingModel(
            account=account,
            account_revision=account_revision,
            source_namespace=request.source_namespace,
            source_record_id=request.source_record_id,
            source_event_id=request.source_event_id,
            source_revision_id=request.source_revision_id,
            asset_code=request.asset_code,
            security_id=request.security_id,
            asset_name=request.asset_name,
            action_kind=request.action_kind.value,
            stage=request.stage.value,
            entry_kind=request.entry_kind.value,
            stage_key=request.stage_key,
            request_payload_sha256=request.payload_sha256,
            source_payload_sha256=request.source_payload_sha256,
            qualification_sha256=request.qualification_sha256,
            qualifier_identity=request.qualifier_identity,
            source_observed_at=request.source_observed_at,
            qualified_at=request.qualified_at,
            posted_at=request.posted_at,
            record_date=request.record_date,
            effective_date=request.effective_date,
            stage_date=request.stage_date,
            payment_date=request.payment_date,
            sellable_date=request.sellable_date,
            cash_amount=request.cash_amount,
            share_amount=request.share_amount,
            tax_treatment=request.tax_treatment,
            tax_rule_id=request.tax_rule_id,
            tax_rule_sha256=request.tax_rule_sha256,
            tax_basis_record_id=request.tax_basis_record_id,
            tax_basis_sha256=request.tax_basis_sha256,
            ownership_snapshot_id=request.ownership_snapshot_id,
            ownership_snapshot_sha256=request.ownership_snapshot_sha256,
            ownership_snapshot_as_of_date=request.ownership_snapshot_as_of_date,
            ownership_snapshot_observed_at=request.ownership_snapshot_observed_at,
            eligible_quantity=request.eligible_quantity,
            entitlement_calculation_sha256=request.entitlement_calculation_sha256,
            rights_terms_sha256=request.rights_terms_sha256,
            rights_election=request.rights_election,
            odd_lot_policy=request.odd_lot_policy,
            odd_lot_confirmation_sha256=request.odd_lot_confirmation_sha256,
            supersedes_revision_id=request.supersedes_revision_id,
            reversal_of=reverses,
            cash_delta=delta.cash,
            cash_receivable_delta=delta.cash_receivable,
            share_delta=delta.shares,
            share_receivable_delta=delta.share_receivable,
            available_share_delta=delta.available_shares,
        )


__all__ = ["DjangoCorporateActionPostingRepository"]
