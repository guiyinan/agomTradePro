"""Prepare exact owner corporate-action correction requests from retained history."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, localcontext
from typing import NoReturn

from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionInputValidationError,
    CorporateActionKind,
    CorporateActionLedgerDelta,
    CorporateActionStage,
    CorporateActionStageRequest,
    calculate_corporate_action_delta,
)
from apps.simulated_trading.domain.corporate_action_share_revision import (
    plan_corporate_action_share_revision,
)
from apps.simulated_trading.domain.simulated_cash_posting_history import (
    SimulatedCashPostingHistoryStep,
    validate_simulated_cash_posting_history,
)

_MAX_REVISION_ENTRIES = 10_000
_MAX_IDENTIFIER_LENGTH = 192
_SUPPORTED_KINDS = frozenset(
    {CorporateActionKind.CASH_DIVIDEND, CorporateActionKind.SHARE_DISTRIBUTION}
)
_CASH_STAGE_ORDER = {
    CorporateActionStage.CASH_ENTITLEMENT: 0,
    CorporateActionStage.CASH_PAYMENT: 1,
}
_SHARE_STAGE_ORDER = {
    CorporateActionStage.SHARE_ENTITLEMENT: 0,
    CorporateActionStage.SHARE_DELIVERY: 1,
    CorporateActionStage.SHARE_SELLABLE_RELEASE: 2,
}


def _canonical_stage_order(
    action_kind: CorporateActionKind,
) -> tuple[
    tuple[CorporateActionStage, ...],
    tuple[CorporateActionStage, ...],
    CorporateActionStage,
]:
    """Return reversal order, successor order, and gate stage for one family."""

    if action_kind is CorporateActionKind.CASH_DIVIDEND:
        return (
            (CorporateActionStage.CASH_PAYMENT, CorporateActionStage.CASH_ENTITLEMENT),
            (CorporateActionStage.CASH_ENTITLEMENT, CorporateActionStage.CASH_PAYMENT),
            CorporateActionStage.CASH_ENTITLEMENT,
        )
    if action_kind is CorporateActionKind.SHARE_DISTRIBUTION:
        return (
            (
                CorporateActionStage.SHARE_SELLABLE_RELEASE,
                CorporateActionStage.SHARE_DELIVERY,
                CorporateActionStage.SHARE_ENTITLEMENT,
            ),
            (
                CorporateActionStage.SHARE_ENTITLEMENT,
                CorporateActionStage.SHARE_DELIVERY,
                CorporateActionStage.SHARE_SELLABLE_RELEASE,
            ),
            CorporateActionStage.SHARE_ENTITLEMENT,
        )
    _invalid("unsupported corporate-action revision family", "CORPORATE_ACTION_STAGE_UNSUPPORTED")


def _invalid(message: str, code: str = "CORPORATE_ACTION_REVISION_CONFLICT") -> NoReturn:
    """Raise a stable input failure for an incomplete or unsafe correction plan."""

    raise CorporateActionInputValidationError(message, code)


def _valid_revision_identifier(value: object) -> bool:
    """Return whether a revision identifier is a bounded exact token."""

    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and len(value) <= _MAX_IDENTIFIER_LENGTH
        and not any(character.isspace() for character in value)
    )


@dataclass(frozen=True, slots=True)
class OwnerCorporateActionRevisionEntry:
    """One read-only current-event ledger fact with its exact Domain request and delta."""

    entry_id: int
    account_revision: int
    request: CorporateActionStageRequest
    delta: CorporateActionLedgerDelta

    def __post_init__(self) -> None:
        """Require one identified, typed ledger stage before replaying its history."""

        if (
            type(self.entry_id) is not int
            or self.entry_id <= 0
            or type(self.account_revision) is not int
            or self.account_revision <= 0
            or type(self.request) is not CorporateActionStageRequest
            or type(self.delta) is not CorporateActionLedgerDelta
            or any(
                type(value) is not Decimal or not value.is_finite()
                for value in (
                    self.delta.cash,
                    self.delta.cash_receivable,
                    self.delta.shares,
                    self.delta.share_receivable,
                    self.delta.available_shares,
                )
            )
        ):
            _invalid(
                "corporate-action revision entry identity is invalid",
                "CORPORATE_ACTION_INPUT_INVALID",
            )
        try:
            self.request.__post_init__()
        except CorporateActionInputValidationError:
            raise
        except (TypeError, ValueError, AttributeError) as error:
            _invalid(
                f"corporate-action revision entry contains a malformed request: {error}",
                "CORPORATE_ACTION_INPUT_INVALID",
            )


@dataclass(frozen=True, slots=True)
class PreparedOwnerCorporateActionRevision:
    """Canonical full correction batch, gate anchor, and caller stage receipt order."""

    requests: tuple[CorporateActionStageRequest, ...]
    gate_anchor: CorporateActionStageRequest
    previous_revision_id: str
    current_revision_id: str
    caller_stage_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        """Keep the returned batch typed and its independent gate anchor in-band."""
        valid_shape = (
            type(self.requests) is tuple
            and 2 <= len(self.requests) <= 6
            and len(self.requests) % 2 == 0
            and all(type(request) is CorporateActionStageRequest for request in self.requests)
        )
        if (
            not valid_shape
            or type(self.gate_anchor) is not CorporateActionStageRequest
            or not any(request is self.gate_anchor for request in self.requests)
            or not _valid_revision_identifier(self.previous_revision_id)
            or not _valid_revision_identifier(self.current_revision_id)
            or self.previous_revision_id == self.current_revision_id
            or type(self.caller_stage_keys) is not tuple
            or any(type(key) is not str or not key for key in self.caller_stage_keys)
        ):
            _invalid(
                "prepared corporate-action revision is incomplete", "CORPORATE_ACTION_INPUT_INVALID"
            )
        batch_size = len(self.requests) // 2
        reversals = self.requests[:batch_size]
        successors = self.requests[batch_size:]
        if (
            len(self.caller_stage_keys) != batch_size
            or len(set(self.caller_stage_keys)) != batch_size
        ):
            _invalid(
                "prepared revision receipt keys are incomplete", "CORPORATE_ACTION_INPUT_INVALID"
            )
        first = self.requests[0]
        if first.action_kind not in _SUPPORTED_KINDS:
            _invalid(
                "prepared revision action family is unsupported",
                "CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )
        for request in self.requests:
            try:
                request.__post_init__()
            except CorporateActionInputValidationError:
                raise
            except (TypeError, ValueError, AttributeError) as error:
                _invalid(
                    f"prepared revision contains an invalid request: {error}",
                    "CORPORATE_ACTION_INPUT_INVALID",
                )
            if (
                request.action_kind is not first.action_kind
                or _scope(request) != _scope(first)
                or _source_facts_identity(request) != _source_facts_identity(first)
                or request.source_revision_id != self.current_revision_id
                or request.supersedes_revision_id != self.previous_revision_id
            ):
                _invalid("prepared revision requests cross source or predecessor identity")
        if any(
            item.entry_kind is not CorporateActionEntryKind.REVERSAL for item in reversals
        ) or any(item.entry_kind is not CorporateActionEntryKind.SUCCESSOR for item in successors):
            _invalid("prepared revision must contain reversals followed by successors")
        reversal_stages = tuple(item.stage for item in reversals)
        successor_stages = tuple(item.stage for item in successors)
        if len(set(reversal_stages)) != batch_size or set(reversal_stages) != set(successor_stages):
            _invalid("prepared revision must reverse and replace each stage exactly once")
        expected_reverse_order, expected_successor_order, gate_stage = _canonical_stage_order(
            first.action_kind
        )
        expected_reversals = tuple(
            stage for stage in expected_reverse_order if stage in reversal_stages
        )
        expected_successors = tuple(
            stage for stage in expected_successor_order if stage in successor_stages
        )
        if reversal_stages != expected_reversals or successor_stages != expected_successors:
            _invalid("prepared revision stages are not in canonical correction order")
        expected_receipts = {f"posting:{stage.value}" for stage in successor_stages}
        if set(self.caller_stage_keys) != expected_receipts:
            _invalid("prepared revision receipt keys do not identify its successor stages")
        if (
            self.gate_anchor.entry_kind is not CorporateActionEntryKind.SUCCESSOR
            or self.gate_anchor.stage is not gate_stage
            or self.gate_anchor not in successors
        ):
            _invalid("prepared revision gate anchor is not its entitlement successor")


def _scope(request: CorporateActionStageRequest) -> tuple[object, ...]:
    """Return the stable physical owner and logical source-event identity."""

    return (
        request.account_id,
        request.owner_user_id,
        request.security_id,
        request.asset_code,
        request.source_namespace,
        request.source_event_id,
        request.action_kind,
    )


def _source_revision_identity(request: CorporateActionStageRequest) -> tuple[object, ...]:
    """Return facts that must remain exact across stages of one source revision."""

    return (
        *_scope(request),
        request.source_record_id,
        request.source_revision_id,
        request.supersedes_revision_id,
        request.record_date,
        request.effective_date,
        request.source_payload_sha256,
        request.qualification_sha256,
        request.qualifier_identity,
        request.source_observed_at,
        request.qualified_at,
        request.posted_at,
        request.asset_name,
    )


def _source_facts_identity(request: CorporateActionStageRequest) -> tuple[object, ...]:
    """Return immutable source facts shared by stages, excluding local clocks and display name."""

    return (
        *_scope(request),
        request.source_record_id,
        request.source_revision_id,
        request.record_date,
        request.effective_date,
        request.source_payload_sha256,
        request.qualification_sha256,
        request.qualifier_identity,
        request.source_observed_at,
    )


def _validate_entry_scope(
    *,
    entries: tuple[OwnerCorporateActionRevisionEntry, ...],
    first: CorporateActionStageRequest,
) -> None:
    """Reject unknown stage families, legacy withholding, or crossed event scopes."""

    allowed_stages = (
        frozenset(_CASH_STAGE_ORDER)
        if first.action_kind is CorporateActionKind.CASH_DIVIDEND
        else frozenset(_SHARE_STAGE_ORDER)
    )
    for entry in entries:
        request = entry.request
        if (
            request.action_kind not in _SUPPORTED_KINDS
            or request.action_kind is not first.action_kind
        ):
            _invalid("revision history mixes unsupported corporate-action kinds")
        if request.stage is CorporateActionStage.TAX_WITHHOLDING:
            _invalid(
                "legacy corporate-action withholding is outside the revision helper",
                "CORPORATE_ACTION_TAX_TERMS_UNKNOWN",
            )
        if request.stage not in allowed_stages:
            _invalid(
                "revision history contains an unsupported stage",
                "CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )
        if _scope(request) != _scope(first):
            _invalid("revision history crosses account, owner, asset, or logical event scope")


def _validate_cash_history(
    entries: tuple[OwnerCorporateActionRevisionEntry, ...],
) -> None:
    """Reuse the exact persisted cash receivable and full-payment replay invariant."""

    try:
        validate_simulated_cash_posting_history(
            tuple(
                SimulatedCashPostingHistoryStep(
                    account_revision=entry.account_revision,
                    request=entry.request,
                    delta=entry.delta,
                )
                for entry in entries
            )
        )
    except (TypeError, ValueError) as error:
        _invalid(f"cash corporate-action history cannot be replayed: {error}")


def _validate_share_history(
    entries: tuple[OwnerCorporateActionRevisionEntry, ...],
) -> None:
    """Replay bounded exact share balances and require each delivery/release in full."""

    receivable = Decimal("0.000000")
    delivered = Decimal("0.000000")
    sellable = Decimal("0.000000")
    with localcontext() as context:
        # Persisted share deltas have 20 total digits and six decimal places;
        # 40 digits also cover up to 10,000 cumulative ledger rows exactly.
        context.prec = 40
        for entry in entries:
            request = entry.request
            delta = entry.delta
            if request.entry_kind is not CorporateActionEntryKind.REVERSAL:
                if delta != _canonical_delta(request):
                    _invalid("share stage delta differs from its canonical Domain request")
            if not all(
                _supported_persisted_decimal(value, max_digits=20, decimal_places=6)
                for value in (delta.shares, delta.share_receivable, delta.available_shares)
            ):
                _invalid("share history contains an unsupported persisted quantity")
            if (
                not all(
                    _supported_persisted_decimal(value, max_digits=15, decimal_places=2)
                    for value in (delta.cash, delta.cash_receivable)
                )
                or not delta.cash.is_zero()
                or not delta.cash_receivable.is_zero()
            ):
                _invalid("share history contains an unrelated or unsupported cash effect")
            if request.stage is CorporateActionStage.SHARE_DELIVERY and (
                request.entry_kind is not CorporateActionEntryKind.REVERSAL
            ):
                if request.share_amount is None or receivable != request.share_amount:
                    _invalid("share delivery does not settle the full outstanding entitlement")
            if request.stage is CorporateActionStage.SHARE_SELLABLE_RELEASE and (
                request.entry_kind is not CorporateActionEntryKind.REVERSAL
            ):
                if request.share_amount is None or delivered - sellable != request.share_amount:
                    _invalid("sellable release does not release the full undelivered balance")
            receivable += delta.share_receivable
            delivered += delta.shares
            sellable += delta.available_shares
            if receivable < 0 or delivered < 0 or sellable < 0 or sellable > delivered:
                _invalid("share history contains a partial or impossible stage sequence")


def _supported_persisted_decimal(
    value: Decimal,
    *,
    max_digits: int,
    decimal_places: int,
) -> bool:
    """Match an exact signed value to one persisted fixed-scale Decimal column."""

    if type(value) is not Decimal or not value.is_finite():
        return False
    parts = value.as_tuple()
    if type(parts.exponent) is not int or parts.exponent < -decimal_places:
        return False
    if len(parts.digits) > max_digits:
        return False
    integer_digits = max(len(parts.digits) + parts.exponent, 0)
    return integer_digits <= max_digits - decimal_places


def _canonical_delta(request: CorporateActionStageRequest) -> CorporateActionLedgerDelta:
    """Calculate a persisted stage delta independently of ambient Decimal settings."""

    with localcontext() as context:
        context.prec = 40
        return calculate_corporate_action_delta(request)


def _replay_current_active_revision(
    *,
    history: tuple[OwnerCorporateActionRevisionEntry, ...],
    expected_head_revision_id: str,
) -> tuple[str, dict[int, OwnerCorporateActionRevisionEntry]]:
    """Replay every source revision and correction to its exact current active stage set."""

    if (
        type(history) is not tuple
        or not history
        or len(history) > _MAX_REVISION_ENTRIES
        or any(type(entry) is not OwnerCorporateActionRevisionEntry for entry in history)
        or not _valid_revision_identifier(expected_head_revision_id)
    ):
        _invalid(
            "revision history is empty, unbounded, or untyped", "CORPORATE_ACTION_INPUT_INVALID"
        )
    first = history[0].request
    _validate_entry_scope(entries=history, first=first)
    identifiers: set[int] = set()
    revisions: set[str] = set()
    seen_stages: dict[str, set[CorporateActionStage]] = {}
    source_facts_by_revision: dict[str, tuple[object, ...]] = {}
    active: dict[int, OwnerCorporateActionRevisionEntry] = {}
    head: str | None = None
    previous_account_revision = 0
    index = 0

    for entry in history:
        if entry.entry_id in identifiers or entry.account_revision <= previous_account_revision:
            _invalid("revision history order or entry identity is ambiguous")
        identifiers.add(entry.entry_id)
        previous_account_revision = entry.account_revision

    while index < len(history):
        entry = history[index]
        request = entry.request
        source_facts = _source_facts_identity(request)
        known_revision_facts = source_facts_by_revision.get(request.source_revision_id)
        if known_revision_facts is not None and known_revision_facts != source_facts:
            _invalid("one source revision contains conflicting retained source facts")
        source_facts_by_revision[request.source_revision_id] = source_facts
        if request.entry_kind is CorporateActionEntryKind.POSTING:
            if head is None:
                if request.supersedes_revision_id is not None:
                    _invalid("the initial source revision unexpectedly has a predecessor")
                head = request.source_revision_id
                revisions.add(head)
            if request.source_revision_id != head or request.supersedes_revision_id is not None:
                _invalid("ordinary posting is outside the complete current source head")
            stage_set = seen_stages.setdefault(head, set())
            if request.stage in stage_set:
                _invalid("one source revision repeats an already active stage")
            if entry.delta != _canonical_delta(request):
                _invalid("ordinary stage delta differs from its canonical Domain request")
            stage_set.add(request.stage)
            active[entry.entry_id] = entry
            index += 1
            continue

        if request.entry_kind not in {
            CorporateActionEntryKind.REVERSAL,
            CorporateActionEntryKind.SUCCESSOR,
        }:
            _invalid("revision history contains an unsupported entry kind")
        new_revision_id = request.source_revision_id
        if (
            head is None
            or new_revision_id in revisions
            or new_revision_id == head
            or request.supersedes_revision_id != head
            or not active
        ):
            _invalid("correction does not name one direct predecessor revision")

        end = index
        batch: list[OwnerCorporateActionRevisionEntry] = []
        while end < len(history):
            candidate = history[end]
            candidate_request = candidate.request
            if (
                candidate_request.source_revision_id != new_revision_id
                or candidate_request.entry_kind
                not in {CorporateActionEntryKind.REVERSAL, CorporateActionEntryKind.SUCCESSOR}
            ):
                break
            batch.append(candidate)
            end += 1
        if not batch or any(
            history[position].account_revision + 1 != history[position + 1].account_revision
            for position in range(index, end - 1)
        ):
            _invalid("correction rows are not one complete account-revision batch")
        if any(
            item.request.supersedes_revision_id != head
            or _source_revision_identity(item.request)
            != _source_revision_identity(batch[0].request)
            for item in batch
        ):
            _invalid("correction batch contains mixed source facts or predecessor revisions")

        reversals = tuple(
            item for item in batch if item.request.entry_kind is CorporateActionEntryKind.REVERSAL
        )
        successors = tuple(
            item for item in batch if item.request.entry_kind is CorporateActionEntryKind.SUCCESSOR
        )
        reversal_ids = tuple(item.request.reversal_of_entry_id for item in reversals)
        if (
            not reversals
            or not successors
            or len(set(reversal_ids)) != len(reversal_ids)
            or set(reversal_ids) != set(active)
        ):
            _invalid(
                "correction must reverse every active stage exactly once and include successors"
            )
        active_stages = {item.request.stage for item in active.values()}
        successor_stages = {item.request.stage for item in successors}
        if (
            len(active_stages) != len(active)
            or len(successor_stages) != len(successors)
            or successor_stages != active_stages
        ):
            _invalid("correction must replace the exact complete active stage set")

        targets = {item.entry_id: item for item in active.values()}
        for reversal in reversals:
            target_id = reversal.request.reversal_of_entry_id
            target = targets.get(target_id or 0)
            if (
                target is None
                or reversal.request.stage is not target.request.stage
                or reversal.request.action_kind is not target.request.action_kind
                or reversal.delta != _inverse(target.delta)
            ):
                _invalid("correction reversal does not exactly negate its active predecessor")
        for successor in successors:
            if successor.delta != _canonical_delta(successor.request):
                _invalid("correction successor delta differs from its canonical request")

        if first.action_kind is CorporateActionKind.SHARE_DISTRIBUTION:
            plan = plan_corporate_action_share_revision(tuple(item.request for item in batch))
            if tuple(request.stage_key for request in plan.requests) != tuple(
                item.request.stage_key for item in batch
            ):
                _invalid(
                    "share correction was not retained in canonical reverse/forward stage order"
                )

        for reversal in reversals:
            active.pop(reversal.request.reversal_of_entry_id or 0)
        for successor in successors:
            active[successor.entry_id] = successor
        head = new_revision_id
        revisions.add(head)
        seen_stages[head] = successor_stages
        index = end

    if head != expected_head_revision_id or not active:
        _invalid("history does not end at one non-empty expected active revision head")
    if first.action_kind is CorporateActionKind.CASH_DIVIDEND:
        _validate_cash_history(history)
        active_amounts = {entry.request.cash_amount for entry in active.values()}
    else:
        _validate_share_history(history)
        active_amounts = {entry.request.share_amount for entry in active.values()}
    if len(active_amounts) != 1 or None in active_amounts:
        _invalid("active stages do not preserve one complete event quantity")
    return head, active


def read_owner_corporate_action_revision_head(
    history: tuple[OwnerCorporateActionRevisionEntry, ...],
    expected_head_revision_id: str,
) -> tuple[OwnerCorporateActionRevisionEntry, ...]:
    """Validate full source history and return its exact active immediate-head stages.

    The caller must supply every current-event ledger row from its separately
    verified readback. This pure replay checks account revision order, direct
    source predecessors, complete reversal sets, exact deltas, and cash/share
    stage invariants; it does not query the ledger or verify Audit authority.
    """

    _, active = _replay_current_active_revision(
        history=history,
        expected_head_revision_id=expected_head_revision_id,
    )
    return tuple(active.values())


def _validate_replacements(
    *,
    replacement_requests: tuple[CorporateActionStageRequest, ...],
    first_history_request: CorporateActionStageRequest,
    head_revision_id: str,
    active: dict[int, OwnerCorporateActionRevisionEntry],
    history: tuple[OwnerCorporateActionRevisionEntry, ...],
    as_of_date: date,
) -> tuple[dict[CorporateActionStage, CorporateActionStageRequest], str]:
    """Require one exact current-source POSTING template for every active stage."""

    if (
        type(replacement_requests) is not tuple
        or not replacement_requests
        or len(replacement_requests) > 3
        or type(as_of_date) is not date
    ):
        _invalid("replacement stages or current date are invalid", "CORPORATE_ACTION_INPUT_INVALID")
    first = replacement_requests[0]
    if type(first) is not CorporateActionStageRequest:
        _invalid("replacement stage is not a Domain request", "CORPORATE_ACTION_INPUT_INVALID")
    allowed_stages = (
        frozenset(_CASH_STAGE_ORDER)
        if first_history_request.action_kind is CorporateActionKind.CASH_DIVIDEND
        else frozenset(_SHARE_STAGE_ORDER)
    )
    for request in replacement_requests:
        if type(request) is not CorporateActionStageRequest:
            _invalid("replacement stage is not a Domain request", "CORPORATE_ACTION_INPUT_INVALID")
        request.__post_init__()
        if (
            request.action_kind not in _SUPPORTED_KINDS
            or request.action_kind is not first_history_request.action_kind
        ):
            _invalid("replacement action family differs from the retained event")
        if request.stage not in allowed_stages:
            _invalid(
                "replacement contains an unsupported action stage",
                "CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )
        if _scope(request) != _scope(first_history_request):
            _invalid("replacement source does not match the retained owner and event scope")
        if (
            request.entry_kind is not CorporateActionEntryKind.POSTING
            or request.supersedes_revision_id is not None
            or request.reversal_of_entry_id is not None
            or request.source_revision_id == head_revision_id
            or request.stage_date > as_of_date
        ):
            _invalid("replacement must be a reached new-source ordinary posting")
        if _source_revision_identity(request) != _source_revision_identity(first):
            _invalid("replacement stages do not share one exact current-source revision")
    current_revision_id = first.source_revision_id
    if current_revision_id in {entry.request.source_revision_id for entry in history}:
        _invalid("replacement source revision already exists in retained history")
    request_by_stage = {request.stage: request for request in replacement_requests}
    if len(request_by_stage) != len(replacement_requests):
        _invalid("replacement repeats a stage in one source revision")
    if set(request_by_stage) != {entry.request.stage for entry in active.values()}:
        _invalid("replacement must contain the exact complete current active stage set")

    if first.action_kind is CorporateActionKind.CASH_DIVIDEND:
        if CorporateActionStage.CASH_ENTITLEMENT not in request_by_stage:
            _invalid("cash correction must preserve the source entitlement")
        amounts = {request.cash_amount for request in replacement_requests}
        if any(
            request.cash_amount is None
            or not _supported_persisted_decimal(
                request.cash_amount, max_digits=15, decimal_places=2
            )
            for request in replacement_requests
        ):
            _invalid("replacement cash amount exceeds persisted exact money precision")
    else:
        amounts = {request.share_amount for request in replacement_requests}
        if any(
            request.share_amount is None
            or not _supported_persisted_decimal(
                request.share_amount, max_digits=20, decimal_places=6
            )
            for request in replacement_requests
        ):
            _invalid("replacement share amount exceeds persisted exact quantity precision")
    if len(amounts) != 1 or None in amounts:
        _invalid("all current stages must preserve one exact full source quantity")
    return request_by_stage, current_revision_id


def _inverse(delta: CorporateActionLedgerDelta) -> CorporateActionLedgerDelta:
    """Return the exact signed inverse of one retained ledger delta."""

    return CorporateActionLedgerDelta(
        cash=delta.cash.copy_negate(),
        cash_receivable=delta.cash_receivable.copy_negate(),
        shares=delta.shares.copy_negate(),
        share_receivable=delta.share_receivable.copy_negate(),
        available_shares=delta.available_shares.copy_negate(),
    )


def _reversal_request(
    *,
    template: CorporateActionStageRequest,
    target: OwnerCorporateActionRevisionEntry,
    previous_revision_id: str,
) -> CorporateActionStageRequest:
    """Bind one exact active predecessor to a current-source zero-economics reversal."""

    return replace(
        template,
        stage=target.request.stage,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        cash_amount=None,
        share_amount=None,
        tax_treatment=None,
        tax_rule_id=None,
        tax_rule_sha256=None,
        tax_basis_record_id=None,
        tax_basis_sha256=None,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        rights_terms_sha256=None,
        rights_election=None,
        odd_lot_policy=None,
        odd_lot_confirmation_sha256=None,
        supersedes_revision_id=previous_revision_id,
        reversal_of_entry_id=target.entry_id,
    )


def _successor_request(
    request: CorporateActionStageRequest,
    *,
    previous_revision_id: str,
) -> CorporateActionStageRequest:
    """Turn one current source template into its direct-predecessor successor."""

    return replace(
        request,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        supersedes_revision_id=previous_revision_id,
    )


def prepare_owner_corporate_action_revision(
    *,
    history: tuple[OwnerCorporateActionRevisionEntry, ...],
    expected_head_revision_id: str,
    replacement_requests: tuple[CorporateActionStageRequest, ...],
    as_of_date: date,
) -> PreparedOwnerCorporateActionRevision:
    """Build a complete current-source reverse-and-successor batch without writing.

    The caller supplies the complete locked/read-back event history and ordinary
    POSTING templates already built from current source and record-date evidence.
    This helper validates the whole immediate-predecessor history and exact stage
    set, then creates reversible Domain requests. It does not establish Audit,
    source, grant, window, model, account-lock, or spent-share authority.
    """

    head, active = _replay_current_active_revision(
        history=history,
        expected_head_revision_id=expected_head_revision_id,
    )
    templates, current_revision_id = _validate_replacements(
        replacement_requests=replacement_requests,
        first_history_request=history[0].request,
        head_revision_id=head,
        active=active,
        history=history,
        as_of_date=as_of_date,
    )
    reversals = tuple(
        _reversal_request(
            template=templates[entry.request.stage],
            target=entry,
            previous_revision_id=head,
        )
        for entry in active.values()
    )
    successors = tuple(
        _successor_request(request, previous_revision_id=head) for request in replacement_requests
    )
    if history[0].request.action_kind is CorporateActionKind.CASH_DIVIDEND:
        ordered_reversals = tuple(
            sorted(reversals, key=lambda request: _CASH_STAGE_ORDER[request.stage], reverse=True)
        )
        ordered_successors = tuple(
            sorted(successors, key=lambda request: _CASH_STAGE_ORDER[request.stage])
        )
        batch = ordered_reversals + ordered_successors
        gate_anchor = next(
            request
            for request in ordered_successors
            if request.stage is CorporateActionStage.CASH_ENTITLEMENT
        )
    else:
        plan = plan_corporate_action_share_revision(reversals + successors)
        batch = plan.requests
        gate_anchor = plan.gate_anchor

    return PreparedOwnerCorporateActionRevision(
        requests=batch,
        gate_anchor=gate_anchor,
        previous_revision_id=head,
        current_revision_id=current_revision_id,
        caller_stage_keys=tuple(request.stage_key for request in replacement_requests),
    )


__all__ = (
    "OwnerCorporateActionRevisionEntry",
    "PreparedOwnerCorporateActionRevision",
    "prepare_owner_corporate_action_revision",
    "read_owner_corporate_action_revision_head",
)
